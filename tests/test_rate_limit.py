"""WS-7: cross-process LunarCrush rate limiting (ratelimit.py).

Motivation (see ratelimit.py's module docstring and marketdata.py's
_lunarcrush_throttle): five bot processes sharing one LunarCrush API key
each believed they were within the 10 req/min cap because the old throttle
was an in-process module global, invisible across processes, and
collectively drew HTTP 429s with no backoff and no shared cache to dedupe
identical fetches.

Covers three generic primitives in ratelimit.py directly (no marketdata.py
involvement needed -- they're deliberately provider-agnostic):
  - throttle(key, min_interval)          cross-process min-interval gate
  - request_with_retry(do_request, ...)  bounded 429/backoff retry
  - cached_call(key, ttl, fetch_fn)      flock-guarded TTL cache

No real network anywhere: request_with_retry is exercised against fake
response doubles (status_code/headers/json only), never requests.get.
multiprocessing.Process (not Manager, which would open a local socket and
trip tests/conftest.py's network guard) is used for the cross-process
throttle test, communicating results via a plain file instead of IPC.

Every test either sets TRADBOT_STATE_DIR itself or relies on
tests/conftest.py's `_isolated_rate_limit_state_dir` autouse fixture --
either way, nothing here ever touches the real ~/.cache/tradbot.
"""
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import ratelimit


# =========================== import purity ==================================

def test_import_performs_no_filesystem_writes(tmp_path):
    """Importing ratelimit must not create the state dir or any file --
    state-dir resolution/creation is lazy, only triggered by an actual
    throttle/cached_call/_with_file_lock call. Run in a subprocess (the
    only way to observe true import-time behavior), matching
    tests/test_import_purity.py's pattern."""
    target = tmp_path / "should_not_be_created"
    code = (
        "import os\n"
        f"os.environ['TRADBOT_STATE_DIR'] = {str(target)!r}\n"
        "import ratelimit\n"
        f"assert not os.path.exists({str(target)!r}), 'import created the state dir'\n"
        "print('IMPORT_IS_PURE')\n"
    )
    result = subprocess.run(
        [sys.executable, '-c', code],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'IMPORT_IS_PURE' in result.stdout
    assert not target.exists()


# ========================= state dir resolution ==============================

class TestStateDir:

    def test_auto_created_and_override(self, tmp_path, monkeypatch):
        target = tmp_path / "custom_state"
        assert not target.exists()
        monkeypatch.setenv('TRADBOT_STATE_DIR', str(target))
        resolved = ratelimit._state_dir()
        assert resolved == str(target)
        assert target.is_dir()

    def test_default_is_not_under_history_dir(self, tmp_path, monkeypatch):
        """The state dir must not be derivable from HISTORY_DIR -- a run
        that redirects HISTORY_DIR to a scratch dir (a common pattern, see
        AGENTS.md/executionledger.py) must NOT also split the rate
        limiter across processes that happen to use different HISTORY_DIR
        values. Only TRADBOT_STATE_DIR (or the ~/.cache/tradbot default)
        controls it."""
        monkeypatch.delenv('TRADBOT_STATE_DIR', raising=False)
        monkeypatch.setenv('HISTORY_DIR', str(tmp_path / "history_scratch"))
        resolved = ratelimit._state_dir()
        assert 'history_scratch' not in resolved
        assert resolved == os.path.expanduser('~/.cache/tradbot')


# ============================ throttle (cross-process) ======================

def _throttle_worker(state_dir, key, min_interval, out_path):
    """Multiprocessing target (must be module-level to be picklable under
    spawn). Sets TRADBOT_STATE_DIR itself since the child re-imports fresh
    under spawn -- inheriting the parent's os.environ isn't guaranteed to
    reflect a monkeypatch.setenv done via pytest fixtures scoped to the
    parent's own process object, so this is set explicitly and directly."""
    os.environ['TRADBOT_STATE_DIR'] = state_dir
    import ratelimit as rl
    rl.throttle(key, min_interval)
    with open(out_path, 'a') as f:
        f.write(json.dumps({'t': time.time()}) + '\n')


class TestCrossProcessThrottle:

    def test_two_processes_respect_min_interval_via_shared_file(self, tmp_path):
        state_dir = str(tmp_path / "state")
        out_path = str(tmp_path / "calls.jsonl")
        min_interval = 1.0

        p1 = mp.Process(target=_throttle_worker, args=(state_dir, 'testkey', min_interval, out_path))
        p2 = mp.Process(target=_throttle_worker, args=(state_dir, 'testkey', min_interval, out_path))
        p1.start()
        p2.start()
        p1.join(timeout=20)
        p2.join(timeout=20)
        assert p1.exitcode == 0
        assert p2.exitcode == 0

        with open(out_path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 2
        times = sorted(l['t'] for l in lines)
        # Small tolerance for scheduling jitter -- the point is the two
        # processes serialized on the shared file rather than both firing
        # near-simultaneously (which is what the old in-process-only
        # timestamp allowed).
        assert times[1] - times[0] >= min_interval - 0.1

    def test_single_process_sleeps_for_remaining_interval(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TRADBOT_STATE_DIR', str(tmp_path / "state"))
        sleeps = []
        fake_now = {'t': 1000.0}
        ratelimit.throttle('solo', 6.5, sleep_fn=lambda s: sleeps.append(s), now_fn=lambda: fake_now['t'])
        assert sleeps == []  # first call, nothing to wait for
        fake_now['t'] = 1002.0  # only 2s elapsed of the 6.5s interval
        ratelimit.throttle('solo', 6.5, sleep_fn=lambda s: sleeps.append(s), now_fn=lambda: fake_now['t'])
        assert sleeps == pytest.approx([4.5])


# ============================ request_with_retry =============================

class FakeResp:
    def __init__(self, status_code=200, headers=None, json_body=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_body = json_body if json_body is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')

    def json(self):
        return self._json_body


class TestRequestWithRetry:

    def test_retry_after_header_honored_then_succeeds(self):
        calls = []
        sleeps = []

        def do_request():
            calls.append(1)
            if len(calls) == 1:
                return FakeResp(429, headers={'Retry-After': '2'})
            return FakeResp(200, json_body={'ok': True})

        resp = ratelimit.request_with_retry(do_request, sleep_fn=lambda s: sleeps.append(s))
        assert resp.status_code == 200
        assert len(calls) == 2
        assert sleeps == [2.0]

    def test_no_retry_after_uses_bounded_exponential_backoff_with_jitter(self):
        calls = []
        sleeps = []

        def do_request():
            calls.append(1)
            if len(calls) <= 2:
                return FakeResp(429)
            return FakeResp(200)

        resp = ratelimit.request_with_retry(
            do_request, max_retries=2, base_delay=1.0,
            sleep_fn=lambda s: sleeps.append(s), jitter_fn=lambda a, b: 0.0)
        assert resp.status_code == 200
        assert len(calls) == 3
        assert sleeps == [1.0, 2.0]  # base_delay * 2**attempt, jitter pinned to 0

    def test_max_two_retries_then_gives_up_and_returns_response(self):
        """On exhaustion, the function returns the (still-429) response
        rather than raising itself -- the caller's own raise_for_status()
        degrades exactly as it did before WS-7 (fetch_social_status's
        try/except classifies it 'unavailable')."""
        calls = []
        sleeps = []

        def do_request():
            calls.append(1)
            return FakeResp(429)  # always rate-limited

        resp = ratelimit.request_with_retry(
            do_request, max_retries=2, sleep_fn=lambda s: sleeps.append(s),
            jitter_fn=lambda a, b: 0.0)
        assert len(calls) == 3  # initial attempt + 2 retries, never more
        assert resp.status_code == 429
        assert len(sleeps) == 2
        with pytest.raises(RuntimeError, match='429'):
            resp.raise_for_status()

    def test_sleep_ceiling_never_exceeded(self):
        calls = []
        sleeps = []

        def do_request():
            calls.append(1)
            return FakeResp(429)

        resp = ratelimit.request_with_retry(
            do_request, max_retries=2, sleep_ceiling=3.0, base_delay=100.0,
            sleep_fn=lambda s: sleeps.append(s), jitter_fn=lambda a, b: 0.0)
        assert sum(sleeps) <= 3.0
        # Ceiling reached after the first (clamped) sleep -- the second
        # retry attempt is skipped entirely rather than sleeping further.
        assert len(sleeps) == 1
        assert resp.status_code == 429

    def test_non_429_returns_immediately_no_sleep(self):
        calls = []
        sleeps = []

        def do_request():
            calls.append(1)
            return FakeResp(500)

        resp = ratelimit.request_with_retry(do_request, sleep_fn=lambda s: sleeps.append(s))
        assert len(calls) == 1
        assert sleeps == []
        assert resp.status_code == 500

    def test_legacy_response_without_status_code_is_backward_compatible(self):
        """A minimal test double (only .raise_for_status()/.json(), no
        .status_code -- the shape tests/test_market_data.py's existing
        LunarCrush FakeResp used before WS-7) must pass through unchanged,
        so pre-existing tests/callers keep working without modification."""
        class LegacyResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {'data': {'ok': True}}

        calls = []

        def do_request():
            calls.append(1)
            return LegacyResp()

        resp = ratelimit.request_with_retry(do_request)
        assert len(calls) == 1
        assert resp.json() == {'data': {'ok': True}}


# =============================== cached_call ==================================

class TestCachedCall:

    def test_hit_avoids_second_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TRADBOT_STATE_DIR', str(tmp_path))
        calls = []

        def fetch():
            calls.append(1)
            return {'v': 42}

        v1, age1 = ratelimit.cached_call('k1', 120, fetch)
        v2, age2 = ratelimit.cached_call('k1', 120, fetch)
        assert v1 == v2 == {'v': 42}
        assert age1 is None          # fresh fetch
        assert age2 is not None      # cache hit, observable age
        assert age2 >= 0
        assert len(calls) == 1

    def test_expired_ttl_refetches(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TRADBOT_STATE_DIR', str(tmp_path))
        calls = []

        def fetch():
            calls.append(1)
            return {'v': len(calls)}

        v1, age1 = ratelimit.cached_call('k2', 0.05, fetch)
        time.sleep(0.12)
        v2, age2 = ratelimit.cached_call('k2', 0.05, fetch)
        assert len(calls) == 2
        assert age1 is None
        assert age2 is None  # expired -> treated as a fresh fetch, not a hit
        assert v1 != v2

    def test_corrupt_cache_file_is_treated_as_miss(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TRADBOT_STATE_DIR', str(tmp_path))
        cache_path = tmp_path / 'cache_k3.json'
        cache_path.write_text('{not valid json at all')
        calls = []

        def fetch():
            calls.append(1)
            return {'v': 'fresh'}

        v, age = ratelimit.cached_call('k3', 120, fetch)
        assert v == {'v': 'fresh'}
        assert age is None
        assert len(calls) == 1
        # and it must have overwritten the corrupt file with valid JSON
        with open(cache_path) as f:
            payload = json.load(f)
        assert payload['value'] == {'v': 'fresh'}

    def test_fetch_exception_propagates_and_nothing_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TRADBOT_STATE_DIR', str(tmp_path))

        def boom():
            raise RuntimeError('upstream failed')

        with pytest.raises(RuntimeError, match='upstream failed'):
            ratelimit.cached_call('k4', 120, boom)
        assert not (tmp_path / 'cache_k4.json').exists()
