"""WS-7: cross-process rate limiting and TTL caching for external data
sources (LunarCrush today; written generically enough for CMC to adopt
later -- see AGENTS.md/marketdata.py; this cycle does not change CMC/
Trends behavior).

Motivation: five bot processes running independently each believed they
were within LunarCrush's 10 req/min cap because the old throttle
(marketdata._lunarcrush_last_call / _LUNARCRUSH_MIN_INTERVAL) was an
in-process module global -- invisible across processes -- and got HTTP
429s with no backoff and no shared cache to dedupe identical fetches.

This module replaces that with three generic primitives backed by
flock-guarded files in a shared state directory:

  throttle(key, min_interval)         -- cross-process min-interval gate
  cached_call(key, ttl, fetch_fn)     -- flock-guarded TTL cache
  request_with_retry(do_request, ...) -- bounded 429/backoff retry wrapper

State dir resolution (`_state_dir`): `TRADBOT_STATE_DIR` env var if set,
else `~/.cache/tradbot`. Deliberately NOT under HISTORY_DIR -- HISTORY_DIR
redirection (crypto_trading_bot.py's per-run scratch-dir override) is an
unrelated knob; sharing it would split the rate limiter across bot
processes started with different HISTORY_DIR values, defeating the whole
point of a *shared* gate. Lazy: the directory is only resolved/created the
first time one of these functions actually runs -- never at import.

Everything here is keyed by a caller-supplied string, so a future CMC/
Trends adopter needs no new plumbing, just its own key prefix.
"""
import fcntl
import json
import os
import random
import time


def _state_dir():
    """Resolve (and lazily create) the shared state directory. Never
    called at import time -- only when a throttle/cache/lock is actually
    exercised."""
    d = os.environ.get('TRADBOT_STATE_DIR') or os.path.expanduser('~/.cache/tradbot')
    os.makedirs(d, exist_ok=True)
    return d


def _with_file_lock(lock_name, fn):
    """Run `fn()` (zero-arg) while holding an exclusive flock on
    <state_dir>/<lock_name>.lock. Blocks other processes/threads using the
    same lock_name until fn() returns (or raises); the lock is released
    either way."""
    lock_path = os.path.join(_state_dir(), f'{lock_name}.lock')
    with open(lock_path, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def throttle(key, min_interval, sleep_fn=time.sleep, now_fn=time.time):
    """Cross-process min-interval gate keyed by `key`. Blocks the calling
    process until at least `min_interval` seconds have elapsed since the
    last call to `throttle` with the same key IN ANY PROCESS sharing the
    state dir, then records now as the last-call time -- all while holding
    the lock, so two processes can never both slip through for the same
    interval window (the second one queues on the flock and re-checks the
    elapsed time once it acquires it, rather than racing on a stale read
    of the timestamp file).
    """
    ts_path = os.path.join(_state_dir(), f'throttle_{key}.json')

    def _do():
        last = 0.0
        try:
            with open(ts_path) as f:
                last = json.load(f).get('last_call', 0.0)
        except Exception:
            last = 0.0
        elapsed = now_fn() - last
        if elapsed < min_interval:
            sleep_fn(min_interval - elapsed)
        with open(ts_path, 'w') as f:
            json.dump({'last_call': now_fn()}, f)

    _with_file_lock(f'throttle_{key}', _do)


def cached_call(key, ttl, fetch_fn):
    """TTL-cached call keyed by `key`, shared across processes via a
    flock-guarded JSON file. Returns `(value, cache_age)`:
      - fresh fetch: `(value, None)`
      - cache hit:   `(value, age_in_seconds)`

    A corrupt/unreadable cache file is treated as a miss -- never raises,
    never crashes the caller; it just re-fetches and overwrites it.
    `fetch_fn` exceptions propagate to the caller unchanged, and nothing is
    written to the cache on failure (so a transient error never poisons
    other processes' next TTL window).
    """
    cache_path = os.path.join(_state_dir(), f'cache_{key}.json')
    box = {}

    def _do():
        now = time.time()
        try:
            with open(cache_path) as f:
                payload = json.load(f)
            age = now - payload['ts']
            if age < ttl:
                box['value'] = payload['value']
                box['age'] = age
                return
        except Exception:
            pass
        value = fetch_fn()
        box['value'] = value
        box['age'] = None
        try:
            with open(cache_path, 'w') as f:
                json.dump({'ts': now, 'value': value}, f)
        except Exception:
            pass

    _with_file_lock(f'cache_{key}', _do)
    return box['value'], box['age']


def request_with_retry(do_request, max_retries=2, sleep_ceiling=30.0,
                        base_delay=1.0, sleep_fn=time.sleep,
                        jitter_fn=random.uniform):
    """Call `do_request()` (a zero-arg callable performing one HTTP
    attempt and returning a response-like object with `.status_code` and
    `.headers`), retrying on HTTP 429 up to `max_retries` times.

    Honors a numeric `Retry-After` header when present; otherwise a
    bounded exponential backoff with jitter (`base_delay * 2**attempt +
    U(0, base_delay)`). Total sleep across all retries never exceeds
    `sleep_ceiling` seconds -- this never blocks indefinitely. The final
    response (whether 200 or a still-429 after exhausting retries) is
    returned as-is; this function never raises and never calls
    `raise_for_status()` itself, so callers keep their existing
    `resp.raise_for_status()` -> degrade-on-exception path unchanged.

    A response without a `.status_code` (e.g. a minimal legacy test double
    that only implements `.json()`/`.raise_for_status()`) is treated as
    non-429 and returned immediately on the first attempt -- fully
    backward compatible with callers that don't model status codes.
    """
    total_slept = 0.0
    attempt = 0
    while True:
        resp = do_request()
        status = getattr(resp, 'status_code', 200)
        if status != 429 or attempt >= max_retries or total_slept >= sleep_ceiling:
            return resp

        headers = getattr(resp, 'headers', None) or {}
        retry_after = headers.get('Retry-After')
        delay = None
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = None
        if delay is None:
            delay = base_delay * (2 ** attempt) + jitter_fn(0, base_delay)

        delay = max(0.0, min(delay, sleep_ceiling - total_slept))
        if delay > 0:
            sleep_fn(delay)
            total_slept += delay
        attempt += 1
