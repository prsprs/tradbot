"""T9: real Coinbase market-data injection (plan Phase 2).

The 2026-07-18 evaluation's binding finding (EVALUATION_LESSONS_LEARNED
§1.4): frontier models converge on HOLD-by-default because the pipeline
supplies almost no hard data -- only Google-Trends *search interest*, itself
often zero-filled or 429'd (§3.1, §5.3.9). The one validated fix (§5.6): 7
days of Coinbase hourly candles fed through the Fibonacci analyzer produced
coherent, verifiable analyses in seconds. This module turns that route into
the PRIMARY data section carried by every analysis prompt.

Pipeline:
    fetch_candles(client, product_id)  -> normalized OHLCV rows (strings
                                          coerced to numbers)
    summarize_market_data(rows)        -> compact price/volume/volatility dict
    fib_summary(rows)                  -> retracement levels via
                                          fibonacci_analyzer (degrades to None)
    build_market_block(coin, summary, fib, trends_status)
                                       -> a compact, plainly-labeled text block
                                          ("MARKET DATA (Coinbase, verifiable
                                          by all panelists): ...") with a hard
                                          rule stated to the model, the demoted
                                          Google-Trends/CMC/SOCIAL SECONDARY
                                          sections, and -- on any failure --
                                          an explicit "<X> UNAVAILABLE:
                                          <reason>" line (never silence).

    T12/T13 add two more self-fetching SECONDARY sections, each classified
    and rendered the same way as Google Trends:
      fetch_cmc_status(coin) / build_cmc_section(status)       -> CoinMarketCap
          rank, market-cap dominance, circulating/max supply, %-change
          1h/24h/7d/30d (one call, reuses coinmarketcaputil's key handling
          and throttle). F3: resolves symbol -> CMC id first (id-based
          quotes/latest lookup) so a colliding ticker never silently
          returns a different asset's data[0]; an unmappable symbol falls
          back to a symbol query with an explicit ambiguity disclosure in
          the rendered section instead (see _resolve_cmc_id).
      fetch_social_status(coin) / build_social_section(status) -> LunarCrush
          SOCIAL: galaxy_score, alt_rank, an interaction-weighted aggregate
          of per-network sentiment, and interactions/contributors/posts
          volume (two calls: /coins/:SYMBOL/v1 then /topic/:name/v1).
    build_market_block calls both itself (using the `coin` argument it
    already takes) when the caller doesn't pass pre-fetched
    cmc_status/social_status, so the ONE existing per-coin-per-run cache in
    crypto_trading_bot.py (MARKET_BLOCK_CACHE / build_market_block_for_coin)
    is the only cache these need -- see build_market_block's docstring.

Design notes:
  - The block is provider-AGNOSTIC and built once per coin per run (the bot
    caches it). Per-provider grounding disclosure is a separate one-liner
    (grounding_label) attached at call time, so the cache stays shared.
  - Google Trends / CMC / SOCIAL are each demoted to a labeled SECONDARY
    signal. Absence is DISCLOSED (all-zero Trends series -> "below
    measurement floor"; any CMC/LunarCrush fetch failure, missing topic, or
    quota exhaustion -> "<X> DATA UNAVAILABLE: <reason>"), never silently
    omitted (doc 5.3.9).
  - fib_summary is wrapped so a Fibonacci failure degrades the block to a
    price/volume summary rather than dropping market data entirely.
  - Prompt-injection surface: CMC/LunarCrush responses carry free-text
    fields (tags, related_topics, title, ...). Only explicitly-extracted
    numeric/enum fields are ever placed in the block; free text from either
    API is never passed through.

No network at import; fetch_candles is the only function that calls out
unconditionally when handed a live client. fetch_cmc_status/
fetch_social_status also call out (guarded by their own try/except -- see
above) whenever build_market_block isn't given pre-fetched status dicts.
"""

import os
import statistics
import time
from datetime import datetime, timezone

# Fibonacci analysis is an ENHANCEMENT: if the import or the analysis fails,
# the market block degrades to the price/volume summary (disclosed), never an
# exception on the money-adjacent prompt path.
try:
    from fibonacci_analyzer import FibonacciAnalyzer, PricePoint
    _FIB_AVAILABLE = True
except Exception:  # pragma: no cover - defensive
    _FIB_AVAILABLE = False

# T12/T13: CoinMarketCap and LunarCrush add two more DISCLOSED sections to
# the block (CMC rank/dominance/supply/%-changes; LunarCrush SOCIAL score/
# sentiment/volume). coinmarketcaputil has no network calls at import time
# (env-var read only), so a plain import is safe; it supplies the API-key
# resolution and client-side throttle these functions reuse rather than
# duplicate.
import coinmarketcaputil


# Coinbase Advanced Trade granularity -> seconds per candle.
GRANULARITY_SECONDS = {
    'ONE_MINUTE': 60,
    'FIVE_MINUTE': 300,
    'FIFTEEN_MINUTE': 900,
    'THIRTY_MINUTE': 1800,
    'ONE_HOUR': 3600,
    'TWO_HOUR': 7200,
    'SIX_HOUR': 21600,
    'ONE_DAY': 86400,
}


# --- Grounding disclosure (deliverable #4) ---------------------------------
# Gemini (GoogleSearch), Grok (web_search tool) and Perplexity (native live
# search) can pull their own data; Claude and OpenAI cannot. The panel can
# only verify the shared MARKET DATA section, so grounded models are told to
# label their own-search claims distinctly (doc 1.4 comparability concern).
GROUNDED_PROVIDERS = frozenset({'gemini', 'grok', 'perplexity'})

GROUNDED_LABEL = (
    "GROUNDING: You may have live search access. Clearly separate any claims "
    "from your own search from the supplied MARKET DATA section -- other "
    "panelists can only verify the MARKET DATA."
)
UNGROUNDED_LABEL = (
    "GROUNDING: The MARKET DATA section is your primary evidence."
)


def grounding_label(llm_name):
    """One-sentence grounding disclosure for `llm_name` (deliverable #4)."""
    return GROUNDED_LABEL if (llm_name or '').lower() in GROUNDED_PROVIDERS else UNGROUNDED_LABEL


# --- Candle fetch -----------------------------------------------------------

def _cval(candle, key):
    """Read a field from a Coinbase Candle (dict-like or attribute-style)."""
    if isinstance(candle, dict):
        return candle.get(key)
    return getattr(candle, key, None)


def fetch_candles(client, product_id, days=7, granularity='ONE_HOUR'):
    """Fetch `days` of candles for `product_id` via a Coinbase RESTClient.

    Coinbase's get_candles takes UNIX-second string bounds and returns rows
    whose numeric fields are STRINGS (doc "API gotchas"); this coerces them
    and returns rows sorted OLDEST-first:

        {'time': int(unix_s), 'timestamp': datetime(utc),
         'open','high','low','close','volume': float}

    Returns [] when the response carries no candles. Raises on network /
    credential / API errors -- the caller wraps the call and discloses the
    reason in the market block (never a silent empty block).
    """
    now = int(time.time())
    start = now - int(days) * 86400
    resp = client.get_candles(
        product_id=product_id,
        start=str(start),
        end=str(now),
        granularity=granularity,
    )
    candles = getattr(resp, 'candles', None)
    if candles is None and isinstance(resp, dict):
        candles = resp.get('candles')
    if not candles:
        return []

    rows = []
    for c in candles:
        t = _cval(c, 'start')
        if t is None:
            continue
        t = int(float(t))
        rows.append({
            'time': t,
            'timestamp': datetime.fromtimestamp(t, tz=timezone.utc),
            'open': float(_cval(c, 'open')),
            'high': float(_cval(c, 'high')),
            'low': float(_cval(c, 'low')),
            'close': float(_cval(c, 'close')),
            'volume': float(_cval(c, 'volume')),
        })
    rows.sort(key=lambda r: r['time'])
    return rows


# --- Summary ----------------------------------------------------------------

def _price_at_or_before(rows, target_time):
    """Close of the last row at or before `target_time`, or None when the
    window doesn't reach back that far (insufficient history)."""
    prior = None
    for r in rows:
        if r['time'] <= target_time:
            prior = r
        else:
            break
    return prior['close'] if prior else None


def _pct_change(current, past):
    if past is None or past == 0:
        return None
    return (current - past) / past * 100.0


def summarize_market_data(rows):
    """Compact market summary from normalized candle rows.

    Returns a dict:
        last_price, as_of (ISO), n_candles, window_days,
        change_24h / change_72h / change_7d (percent, None if history is
            too short to cover the lookback),
        high / low (over the window), range_position_pct (where last sits in
            [low, high], 0-100),
        avg_daily_volume, volume_trend ('rising' | 'falling' | 'steady'),
        volatility_pct (stdev of hourly close-to-close returns, percent).

    Returns None for empty input (the caller renders MARKET DATA UNAVAILABLE).
    """
    if not rows:
        return None

    last = rows[-1]
    last_price = last['close']
    last_time = last['time']
    span_seconds = last_time - rows[0]['time']
    window_days = span_seconds / 86400.0 if span_seconds > 0 else 0.0

    highs = [r['high'] for r in rows]
    lows = [r['low'] for r in rows]
    high = max(highs)
    low = min(lows)
    rng = high - low
    range_position_pct = ((last_price - low) / rng * 100.0) if rng > 0 else 100.0

    change_24h = _pct_change(last_price, _price_at_or_before(rows, last_time - 24 * 3600))
    change_72h = _pct_change(last_price, _price_at_or_before(rows, last_time - 72 * 3600))
    # 7d: reach for a 7d-ago price; fall back to the oldest row we have.
    price_7d = _price_at_or_before(rows, last_time - 7 * 86400)
    if price_7d is None:
        price_7d = rows[0]['close']
    change_7d = _pct_change(last_price, price_7d)

    volumes = [r['volume'] for r in rows]
    total_volume = sum(volumes)
    avg_daily_volume = total_volume / window_days if window_days >= 1e-9 else total_volume

    # Volume trend: mean of the second half vs the first half.
    half = len(volumes) // 2
    if half >= 1:
        first_mean = statistics.fmean(volumes[:half]) if volumes[:half] else 0.0
        second_mean = statistics.fmean(volumes[half:]) if volumes[half:] else 0.0
        if first_mean <= 0:
            volume_trend = 'steady'
        elif second_mean > first_mean * 1.1:
            volume_trend = 'rising'
        elif second_mean < first_mean * 0.9:
            volume_trend = 'falling'
        else:
            volume_trend = 'steady'
    else:
        volume_trend = 'steady'

    # Hourly (period-to-period) close-to-close returns.
    returns = []
    for i in range(1, len(rows)):
        prev_close = rows[i - 1]['close']
        if prev_close:
            returns.append((rows[i]['close'] - prev_close) / prev_close)
    volatility_pct = (statistics.pstdev(returns) * 100.0) if len(returns) >= 2 else 0.0

    return {
        'last_price': last_price,
        'as_of': last['timestamp'].strftime('%Y-%m-%dT%H:%MZ'),
        'n_candles': len(rows),
        'window_days': window_days,
        'change_24h': change_24h,
        'change_72h': change_72h,
        'change_7d': change_7d,
        'high': high,
        'low': low,
        'range_position_pct': range_position_pct,
        'avg_daily_volume': avg_daily_volume,
        'volume_trend': volume_trend,
        'volatility_pct': volatility_pct,
    }


# --- Fibonacci summary ------------------------------------------------------

def fib_summary(rows, symbol='COIN'):
    """Key Fibonacci retracement levels for `rows`, via fibonacci_analyzer.

    Returns a dict:
        trend_direction ('up' | 'down'),
        most_respected_level (e.g. '23.6%'), most_respected_eff (float|None),
        nearest: up to 3 levels closest to the current price, each
            {label, price, distance_pct, effectiveness (0-100|None), touch_count}

    Wrapped end-to-end in try/except: ANY Fibonacci failure (import, too few
    points, analysis error) returns None so build_market_block degrades to a
    price/volume-only block with a disclosed note -- never an exception.
    """
    try:
        if not _FIB_AVAILABLE or not rows or len(rows) < 4:
            return None
        prices = [PricePoint(timestamp=r['timestamp'], price=r['close']) for r in rows]
        analyzer = FibonacciAnalyzer()
        report = analyzer.analyze(symbol, prices=prices)
        if report is None or not report.levels:
            return None

        last_price = rows[-1]['close']
        levels = []
        for label, lvl in report.levels.items():
            distance_pct = _pct_change(lvl.price, last_price)
            levels.append({
                'label': label,
                'price': lvl.price,
                'distance_pct': distance_pct if distance_pct is not None else 0.0,
                'effectiveness': lvl.effectiveness,
                'touch_count': lvl.touch_count,
            })
        nearest = sorted(levels, key=lambda x: abs(x['distance_pct']))[:3]

        mr_label = report.most_respected_level
        mr_eff = None
        if mr_label and mr_label in report.levels:
            mr_eff = report.levels[mr_label].effectiveness

        return {
            'trend_direction': report.trend_direction,
            'most_respected_level': mr_label,
            'most_respected_eff': mr_eff,
            'nearest': nearest,
            'high': report.high_price,
            'low': report.low_price,
        }
    except Exception:  # pragma: no cover - defensive degrade-to-summary
        return None


# --- CoinMarketCap (T12) -----------------------------------------------------
# Adds rank/dominance/supply/multi-window %-change -- data the Coinbase
# candles don't carry. One call per coin per run to
# /v3/cryptocurrency/quotes/latest (~1 credit; free tier is 15k credits/mo,
# 50 req/min -- see AGENTS.md gotchas). Reuses coinmarketcaputil's API-key
# resolution (both COINMARKETCAP_API_KEY and CMC_API_KEY) and client-side
# throttle instead of duplicating them.
#
# F3 (wrong-asset risk): CMC symbols COLLIDE -- looking quotes/latest up by
# `symbol` and taking data[0] can silently return a DIFFERENT asset's rank/
# dominance/supply for an obscure ticker. _resolve_cmc_id resolves symbol ->
# CMC id first (coinmarketcaputil.SYMBOL_TO_CMC_ID / auto_resolve_symbol,
# the latter backed by the free /v1/cryptocurrency/map endpoint) and
# _fetch_cmc_quote_raw queries by `id` whenever resolution succeeds.
# Verified live 2026-07-19 (tests/fixtures/coinmarketcap_quotes_latest_btc_v3_by_id.json):
# querying by `id` returns the SAME list-shaped `data` as querying by
# `symbol` -- no extra response-parsing branch needed, only the request
# params differ. When a symbol truly can't be resolved (unmapped and not
# found via /v1/cryptocurrency/map), this falls back to the symbol query
# but the returned data carries `id_resolved: False` so build_cmc_section
# renders an explicit ambiguity disclosure -- data[0] is never silently
# trusted as "the" asset for that ticker.


def _resolve_cmc_id(coin_symbol):
    """Resolve `coin_symbol` to a CoinMarketCap numeric id, cheapest path
    first.

    1. coinmarketcaputil.get_cmc_id -- the static/already-cached
       SYMBOL_TO_CMC_ID dict. No network call.
    2. coinmarketcaputil.auto_resolve_symbol -- one call to the FREE
       (0-credit, but still rate-limited -- AGENTS.md gotcha)
       /v1/cryptocurrency/map endpoint. On success it writes the mapping
       back into SYMBOL_TO_CMC_ID itself (add_to_cache=True, its default),
       so every later call in this process for the same symbol resolves
       via step 1 -- the symbol->id resolution is cached automatically,
       not re-fetched per run or per coin repeat.

    Returns the CMC id (int), or None when the symbol truly can't be
    mapped -- callers must then fall back to a symbol-based query AND
    disclose the ambiguity risk (never silently trust data[0]).
    """
    cmc_id = coinmarketcaputil.get_cmc_id(coin_symbol)
    if cmc_id is not None:
        return cmc_id
    return coinmarketcaputil.auto_resolve_symbol(coin_symbol)


def _fetch_cmc_quote_raw(coin_symbol):
    """Single real CMC quotes/latest call for `coin_symbol`.

    Raises on ANY failure (no key, throttled, HTTP error, malformed/missing
    payload) -- never returns a silent/partial result. `fetch_cmc_status`
    catches and classifies the reason for disclosure.

    v3's `quote` field is a LIST of per-currency dicts (verified live
    2026-07-18, tests/fixtures/coinmarketcap_quotes_latest_btc_v3.json),
    unlike v1/v2's `quote: {USD: {...}}` dict shape -- mirrors the parsing
    already used by coinmarketcaputil.get_cmc_price. Same list shape holds
    for an id-based query too (verified 2026-07-19, F3 fixture above).
    """
    import requests

    if not coinmarketcaputil.CMC_API_KEY:
        raise RuntimeError('COINMARKETCAP_API_KEY (or CMC_API_KEY) not set')

    cmc_id = _resolve_cmc_id(coin_symbol)

    if not coinmarketcaputil._rate_limit():
        raise RuntimeError('CMC client-side daily call budget exhausted')

    url = f"{coinmarketcaputil.CMC_API_BASE}/v3/cryptocurrency/quotes/latest"
    headers = {
        "X-CMC_PRO_API_KEY": coinmarketcaputil.CMC_API_KEY,
        "Accept": "application/json",
    }
    if cmc_id is not None:
        params = {"id": str(cmc_id), "convert": "USD"}
    else:
        params = {"symbol": coin_symbol.upper(), "convert": "USD"}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    payload = resp.json()

    rows = payload.get('data') or []
    if not rows:
        raise RuntimeError(f'no CMC data returned for {coin_symbol}')
    coin = rows[0]

    quotes = coin.get('quote') or []
    usd = next((q for q in quotes
                if q.get('symbol') == 'USD' or q.get('id') == 2781), None)
    if usd is None:
        raise RuntimeError(f'no USD quote in CMC response for {coin_symbol}')

    circulating = coin.get('circulating_supply')
    max_supply = coin.get('max_supply')
    supply_ratio_pct = None
    if circulating is not None and max_supply:
        supply_ratio_pct = circulating / max_supply * 100.0

    return {
        'cmc_rank': coin.get('cmc_rank'),
        'market_cap_dominance': usd.get('market_cap_dominance'),
        'circulating_supply': circulating,
        'max_supply': max_supply,
        'supply_ratio_pct': supply_ratio_pct,
        'percent_change_1h': usd.get('percent_change_1h'),
        'percent_change_24h': usd.get('percent_change_24h'),
        'percent_change_7d': usd.get('percent_change_7d'),
        'percent_change_30d': usd.get('percent_change_30d'),
        # F3: True when the request was id-based (unambiguous asset); False
        # means an unmappable symbol forced a symbol-based fallback query --
        # build_cmc_section discloses this so the panel never silently
        # trusts a possibly-wrong-asset data[0].
        'id_resolved': cmc_id is not None,
    }


def fetch_cmc_status(coin_symbol):
    """CMC status dict for `coin_symbol`, classified like get_trends_status:

        {'status': 'present', 'data': {...}, 'reason': None}          on success
        {'status': 'unavailable', 'data': None, 'reason': '<why>'}    on ANY failure

    Never raises -- build_market_block always gets something it can render,
    and a failure is always a disclosed "CMC DATA UNAVAILABLE: <reason>"
    line, never silence or invented values.
    """
    try:
        data = _fetch_cmc_quote_raw(coin_symbol)
        return {'status': 'present', 'data': data, 'reason': None}
    except Exception as e:
        reason = f'{type(e).__name__}: {e}'
        print(f"[CMC] fetch failed for {coin_symbol}: {reason}")
        return {'status': 'unavailable', 'data': None, 'reason': reason}


def build_cmc_section(cmc_status, coin='COIN'):
    """Render the CMC section from a status dict (see fetch_cmc_status)."""
    status = (cmc_status or {}).get('status', 'unavailable')
    data = (cmc_status or {}).get('data')
    if status != 'present' or not data:
        reason = (cmc_status or {}).get('reason') or 'no data returned'
        return f"CMC DATA UNAVAILABLE ({coin}): {reason}."

    rank = data.get('cmc_rank')
    rank_str = f"#{rank}" if rank is not None else 'n/a'
    dom = data.get('market_cap_dominance')
    dom_str = f"{dom:.1f}%" if dom is not None else 'n/a'

    circ = data.get('circulating_supply')
    max_s = data.get('max_supply')
    ratio = data.get('supply_ratio_pct')
    if circ is not None and max_s is not None:
        supply_line = f"{_num(circ)} / {_num(max_s)} max"
        if ratio is not None:
            supply_line += f" ({ratio:.1f}%)"
    elif circ is not None:
        supply_line = f"{_num(circ)} circulating (no max supply cap)"
    else:
        supply_line = 'n/a'

    lines = [
        f"CMC (CoinMarketCap, fetched this run): Rank {rank_str} | "
        f"Market cap dominance {dom_str}",
        f"- Supply: {supply_line}",
        f"- Change: 1h {_pct(data.get('percent_change_1h'))} | "
        f"24h {_pct(data.get('percent_change_24h'))} | "
        f"7d {_pct(data.get('percent_change_7d'))} | "
        f"30d {_pct(data.get('percent_change_30d'))}",
    ]
    # F3: id_resolved defaults True when absent so pre-F3 callers/tests that
    # never set the field render unchanged -- only an EXPLICIT False (an
    # unmappable symbol forced a fallback to a plain symbol query) adds the
    # disclosure. CMC symbols collide; never let data[0] pass as verified.
    if not data.get('id_resolved', True):
        lines.append(
            f"- AMBIGUITY WARNING: no CoinMarketCap id could be resolved "
            f"for {coin}; this data was fetched by SYMBOL lookup only, "
            "which can silently return a DIFFERENT asset for a colliding "
            "ticker -- treat the rank/dominance/supply/change figures "
            "above as UNVERIFIED."
        )
    return "\n".join(lines)


# --- LunarCrush SOCIAL (T13) -------------------------------------------------
# Individual plan since 2026-07-18 (10 req/min, 2,000 req/day -- AGENTS.md
# gotchas). Two calls per coin per run: /coins/:SYMBOL/v1 (galaxy_score,
# alt_rank) then /topic/:name/v1 (topic slug = the coin's lowercased NAME
# from the first call, e.g. "bitcoin" not "BTC"; interactions/contributors/
# posts + per-network types_sentiment). Auth needs Authorization: Bearer
# <key> AND a real User-Agent -- Python's default UA gets a Cloudflare 403
# "error code: 1010" that looks like an auth failure but isn't.

_LUNARCRUSH_BASE = "https://lunarcrush.com/api4/public"
_LUNARCRUSH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Client-side throttle for the Individual plan's 10 req/min cap (conservative
# fixed interval, mirroring coinmarketcaputil's approach rather than a token
# bucket -- this module makes at most 2 calls per coin per run).
_LUNARCRUSH_MIN_INTERVAL = 6.5
_lunarcrush_last_call = 0.0


def _lunarcrush_throttle():
    global _lunarcrush_last_call
    elapsed = time.time() - _lunarcrush_last_call
    if elapsed < _LUNARCRUSH_MIN_INTERVAL:
        time.sleep(_LUNARCRUSH_MIN_INTERVAL - elapsed)
    _lunarcrush_last_call = time.time()


def _lunarcrush_headers():
    key = os.environ.get('LUNARCRUSH_API_KEY', '')
    return {
        "Authorization": f"Bearer {key}",
        "User-Agent": _LUNARCRUSH_USER_AGENT,
        "Accept": "application/json",
    }


def _fetch_lunarcrush_coin_raw(coin_symbol):
    """Real /coins/:SYMBOL/v1 call. Raises on any failure."""
    import requests

    key = os.environ.get('LUNARCRUSH_API_KEY', '')
    if not key:
        raise RuntimeError('LUNARCRUSH_API_KEY not set')
    _lunarcrush_throttle()
    url = f"{_LUNARCRUSH_BASE}/coins/{coin_symbol.lower()}/v1"
    resp = requests.get(url, headers=_lunarcrush_headers(), timeout=10)
    resp.raise_for_status()
    data = (resp.json() or {}).get('data')
    if not data:
        raise RuntimeError(f'no LunarCrush coin data for {coin_symbol}')
    return data


def _fetch_lunarcrush_topic_raw(topic_slug):
    """Real /topic/:topic/v1 call. Raises on any failure (incl. missing
    topic)."""
    import requests

    key = os.environ.get('LUNARCRUSH_API_KEY', '')
    if not key:
        raise RuntimeError('LUNARCRUSH_API_KEY not set')
    _lunarcrush_throttle()
    url = f"{_LUNARCRUSH_BASE}/topic/{topic_slug}/v1"
    resp = requests.get(url, headers=_lunarcrush_headers(), timeout=10)
    resp.raise_for_status()
    data = (resp.json() or {}).get('data')
    if not data:
        raise RuntimeError(f'no LunarCrush topic data for {topic_slug}')
    return data


def _aggregate_sentiment(types_sentiment, types_interactions):
    """Aggregate LunarCrush's per-network `types_sentiment` (each 0-100)
    into one number (T13 judgment call).

    Networks vary hugely in volume (2026-07-18 BTC sample: ~60M tweet
    interactions vs. ~24K on Instagram) so a plain per-network mean would
    let a near-silent network swing the aggregate as much as Twitter.
    Weighting by `types_interactions` (also on the topic/v1 response, so no
    extra call) favors the networks actually carrying the conversation.
    Falls back to a simple mean when interaction weights are absent/zero.
    """
    if not types_sentiment:
        return None
    weights = types_interactions or {}
    total_w = sum(weights.get(k, 0) for k in types_sentiment)
    if total_w > 0:
        return sum(types_sentiment[k] * weights.get(k, 0)
                   for k in types_sentiment) / total_w
    values = list(types_sentiment.values())
    return statistics.fmean(values) if values else None


def fetch_social_status(coin_symbol):
    """LunarCrush SOCIAL status dict for `coin_symbol`, classified like
    fetch_cmc_status / get_trends_status.

    ANY failure -- missing key, HTTP error, missing/unresolvable topic, quota
    exhaustion, malformed payload -- classifies as 'unavailable' with a
    reason. Never raises, never returns a partial/invented section: either
    both calls succeed and the section is 'present', or nothing is asserted.
    """
    try:
        coin_data = _fetch_lunarcrush_coin_raw(coin_symbol)
        name = coin_data.get('name')
        if not name:
            raise RuntimeError(
                f'no name field for {coin_symbol} (cannot derive topic slug)')
        topic_slug = name.strip().lower()
        topic_data = _fetch_lunarcrush_topic_raw(topic_slug)

        types_sentiment = topic_data.get('types_sentiment') or {}
        types_interactions = topic_data.get('types_interactions') or {}

        data = {
            'galaxy_score': coin_data.get('galaxy_score'),
            'alt_rank': coin_data.get('alt_rank'),
            'topic_rank': topic_data.get('topic_rank'),
            'sentiment_aggregate': _aggregate_sentiment(types_sentiment, types_interactions),
            'sentiment_networks': len(types_sentiment),
            'interactions_24h': topic_data.get('interactions_24h'),
            'num_contributors': topic_data.get('num_contributors'),
            'num_posts': topic_data.get('num_posts'),
        }
        return {'status': 'present', 'data': data, 'reason': None}
    except Exception as e:
        reason = f'{type(e).__name__}: {e}'
        print(f"[LUNARCRUSH] fetch failed for {coin_symbol}: {reason}")
        return {'status': 'unavailable', 'data': None, 'reason': reason}


def build_social_section(social_status, coin='COIN'):
    """Render the SOCIAL section from a status dict (see fetch_social_status)."""
    status = (social_status or {}).get('status', 'unavailable')
    data = (social_status or {}).get('data')
    if status != 'present' or not data:
        reason = (social_status or {}).get('reason') or 'no data returned'
        return f"SOCIAL DATA UNAVAILABLE ({coin}): {reason}."

    galaxy = data.get('galaxy_score')
    alt = data.get('alt_rank')
    sentiment = data.get('sentiment_aggregate')
    n_net = data.get('sentiment_networks') or 0
    interactions = data.get('interactions_24h')
    contributors = data.get('num_contributors')
    posts = data.get('num_posts')

    sentiment_line = (
        f"- Aggregate sentiment (interaction-weighted across {n_net} "
        f"networks, 0-100): {sentiment:.0f}"
        if sentiment is not None else "- Aggregate sentiment: n/a"
    )

    lines = [
        f"SOCIAL (LunarCrush, fetched this run): Galaxy score "
        f"{galaxy if galaxy is not None else 'n/a'} | Alt rank "
        f"{alt if alt is not None else 'n/a'}",
        sentiment_line,
        f"- Social volume 24h: "
        f"{_num(interactions) if interactions is not None else 'n/a'} "
        f"interactions across "
        f"{_num(contributors) if contributors is not None else 'n/a'} "
        f"contributors "
        f"({_num(posts) if posts is not None else 'n/a'} posts)",
    ]
    return "\n".join(lines)


# --- Google Trends (SECONDARY signal) --------------------------------------

def build_trends_section(trends_status):
    """Render the demoted Google-Trends SECONDARY section.

    `trends_status` is a dict {'status': ..., 'data': ...} where status is:
        'present'     -> real data, rendered with the max=100 normalization note
        'below_floor' -> all-zero series (search volume below Google's floor)
        'failed'      -> fetch/429 failure -> claims unsupported
        'unavailable' -> no series at all
    Absence is always DISCLOSED, never silently omitted (doc 5.3.9).
    """
    status = (trends_status or {}).get('status', 'unavailable')
    data = (trends_status or {}).get('data')
    if status == 'present' and data:
        return (
            "GOOGLE TRENDS (secondary signal -- search interest, not price):\n"
            f"{data}\n"
            "Note: values are scaled so the window maximum = 100; on low-volume "
            "tickers a single stray minute can appear as a spike to 100. "
            "Absolute search volume may be near zero."
        )
    if status == 'below_floor':
        return (
            "GOOGLE TRENDS (secondary signal): search volume below measurement "
            "floor for this ticker -- no signal."
        )
    if status == 'failed':
        return (
            "GOOGLE TRENDS (secondary signal): data collection failed (rate "
            "limit) -- treat any search-interest claims as unsupported."
        )
    return "GOOGLE TRENDS (secondary signal): no data available for this ticker."


# --- Formatting helpers -----------------------------------------------------

def _usd(value):
    if value is None:
        return 'n/a'
    if abs(value) >= 1:
        return f"${value:,.2f}"
    # Sub-dollar coins (BONK, SHIB, PEPE): show more precision.
    return f"${value:,.8f}".rstrip('0').rstrip('.')


def _pct(value):
    if value is None:
        return 'n/a'
    return f"{value:+.1f}%"


def _num(value):
    if value is None:
        return 'n/a'
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 1:
        return f"{value:,.1f}"
    return f"{value:,.4f}"


def _market_section(coin, s):
    product_id = f"{coin}-USD"
    window_days = s.get('window_days') or 0
    lines = [
        f"MARKET DATA (Coinbase {product_id}, verifiable by all panelists; "
        f"{s['n_candles']} candles / {window_days:.1f}d):",
        f"- Last price: {_usd(s['last_price'])} (as of {s['as_of']})",
        f"- Change: 24h {_pct(s['change_24h'])} | 72h {_pct(s['change_72h'])} "
        f"| 7d {_pct(s['change_7d'])}",
        f"- Range: {_usd(s['low'])} low / {_usd(s['high'])} high; "
        f"now at {s['range_position_pct']:.0f}% of range",
        f"- Avg daily volume: {_num(s['avg_daily_volume'])} {coin} "
        f"({s['volume_trend']})",
        f"- Volatility (stdev of hourly returns): {s['volatility_pct']:.2f}%",
    ]
    return "\n".join(lines)


def _fib_section(fib):
    trend = fib.get('trend_direction', 'n/a')
    mr = fib.get('most_respected_level')
    mr_eff = fib.get('most_respected_eff')
    header = f"FIBONACCI (retracement; trend {trend}"
    if mr:
        if mr_eff is not None:
            header += f"; most-respected {mr} @ {mr_eff:.0f}% bounce"
        else:
            header += f"; most-respected {mr}"
    header += "):"

    parts = []
    for lvl in fib.get('nearest', []):
        eff = lvl.get('effectiveness')
        eff_str = f"{eff:.0f}% eff" if eff is not None else "n/a eff"
        parts.append(
            f"{lvl['label']} {_usd(lvl['price'])} "
            f"({_pct(lvl['distance_pct'])}, {eff_str})"
        )
    nearest_line = "- Nearest levels to price: " + " | ".join(parts) if parts else \
        "- No significant levels within the window."
    return header + "\n" + nearest_line


HARD_RULE = (
    "RULE: Base your recommendation on the labeled data above. Do not invent "
    "indicator values (RSI, EMA, MACD, order-book depth, ETF/on-chain flows) "
    "that are not derivable from it, and do not invent CMC rank/dominance/"
    "supply or social/sentiment figures beyond what the CMC and SOCIAL "
    "sections state."
)


def build_market_block(coin, summary, fib, trends_status, unavailable_reason=None,
                       cmc_status=None, social_status=None):
    """Assemble the compact, plainly-labeled analysis data block for `coin`.

    Layout (market data PRIMARY, trends/CMC/SOCIAL SECONDARY, one hard rule):
        MARKET DATA (...): ...          [or MARKET DATA UNAVAILABLE: <reason>]
        FIBONACCI (...): ...            [or a degraded-to-summary note]
        GOOGLE TRENDS (secondary ...): ...
        CMC (...): ...                  [or CMC DATA UNAVAILABLE: <reason>]
        SOCIAL (...): ...               [or SOCIAL DATA UNAVAILABLE: <reason>]
        RULE: ...

    Provider-agnostic and short (~<=500 tokens for a normal coin). On any
    fetch/compute failure (`summary is None`) it emits an explicit
    "MARKET DATA UNAVAILABLE: <reason>" line -- never an empty/silent block.
    Trends/CMC/SOCIAL are each rendered independently, so a market-data
    failure still carries whatever secondary signal (or disclosed absence)
    exists for the others.

    `cmc_status` / `social_status` (T12/T13) are the same shape as
    `trends_status` -- {'status': ..., 'data': ..., 'reason': ...}. When not
    supplied (the normal call path: this is the only place they're fetched,
    from `coin`, via fetch_cmc_status/fetch_social_status), this function
    fetches them itself so the ONE existing per-coin-per-run cache around
    build_market_block (crypto_trading_bot.MARKET_BLOCK_CACHE /
    build_market_block_for_coin) is the only cache CMC and LunarCrush need --
    no new cache was added. Tests inject fakes via these params (or monkey-
    patch fetch_cmc_status/fetch_social_status) so no test hits the network.
    """
    if cmc_status is None:
        cmc_status = fetch_cmc_status(coin)
    if social_status is None:
        social_status = fetch_social_status(coin)

    lines = []
    if summary is None:
        reason = unavailable_reason or 'no verifiable price/volume series was supplied'
        lines.append(f"MARKET DATA UNAVAILABLE ({coin}-USD): {reason}.")
    else:
        lines.append(_market_section(coin, summary))
        if fib:
            lines.append(_fib_section(fib))
        else:
            lines.append(
                "FIBONACCI: retracement levels unavailable for this window "
                "(degraded to price/volume summary only)."
            )
    lines.append(build_trends_section(trends_status))
    lines.append(build_cmc_section(cmc_status, coin))
    lines.append(build_social_section(social_status, coin))
    lines.append(HARD_RULE)
    return "\n".join(lines)
