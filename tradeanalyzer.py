#!/usr/bin/env python3
"""Trade Analyzer (T10 overhaul) -- score/report recommendation accuracy.

This is a SCORER / REPORTER only. It reads the recommendation history and the
execution ledger and grades past decisions. It deliberately contains **no
backtester, no equity curve, and no simulated portfolio** -- it never invents a
price series or a P&L path; it only compares a recorded decision to observed
prices.

Key properties of this overhaul (see AGENTS.md / EVALUATION_LESSONS docs):

  * Total lifecycle coverage. Every loaded record lands in exactly one terminal
    category, so nothing is silently dropped. For the live/whatif directional
    subset the three lifecycle buckets are SCORED / PENDING / EXPIRED_UNSCORABLE
    and they cover 0h..infinity with no gap.

  * Benchmark-relative scoring. A BUY on coin X over the window [t_rec, now] is
    judged on X's return MINUS the benchmark's (BTC) return over the SAME window
    MINUS the round-trip fee floor (2.4% measured, or the ACTUAL fee from the
    execution ledger when a fill row joins by run_id). A BUY that beats neither
    the benchmark nor fees is a LOSS even if the coin rose.

  * Live and whatif scored separately. trading_mode='unknown' is excluded from
    scoring entirely (reported in a count line only).

  * Blocked panel decisions (recommendation 'NONE') are not scoreable trades but
    produce panel-behavior stats (block-reason histogram, consensus-state
    distribution, per-LLM vote/abstain patterns).

  * Judged-flag persistence. Once a record is scored its outcome is frozen in a
    sidecar state file so re-runs (against a moved market) don't re-grade it.

  * Backup files (*.bak-*) are never read as data.

CLI:  python tradeanalyzer.py --help
"""

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Defaults (all overridable on the CLI). Reported as judgment calls in the
# task summary -- the spec pinned only the 2.4% fee floor and the BTC benchmark.
# ---------------------------------------------------------------------------
DEFAULT_MATURITY_HOURS = 24          # a decision younger than this is "pending"
DEFAULT_FEE_FLOOR_PCT = 2.4          # measured round-trip fee (~1.2%/side)
DEFAULT_BENCHMARK = 'BTC'            # BUY judged vs holding BTC over same window

# Terminal categories. Every record maps to exactly one of these (totality).
NON_TRADING = 'non_trading'            # not a trade record (e.g. llm_compare rows)
EXCLUDED_UNKNOWN = 'excluded_unknown'  # trading_mode unknown/missing -> not scored
BLOCKED = 'blocked'                    # recommendation 'NONE' (panel block)
PENDING = 'pending'                    # live/whatif decision younger than maturity
SCORED = 'scored'                      # graded (WIN/LOSS for BUY/SELL, NEUTRAL for HOLD)
EXPIRED_UNSCORABLE = 'expired_unscorable'  # mature but ungradeable (missing data)

# The three lifecycle buckets the task calls out, in report order.
LIFECYCLE_BUCKETS = (SCORED, PENDING, EXPIRED_UNSCORABLE)

# Outcomes for a graded directional decision.
WIN = 'WIN'
LOSS = 'LOSS'
NEUTRAL = 'NEUTRAL'   # HOLD -- recorded, never win/loss

DIRECTIONAL_ACTIONS = frozenset({'BUY', 'SELL'})

# Scoring methodology (F4): whether the endpoint prices were taken AT the
# decision's maturity horizon (rec_time + maturity_hours, from historical
# candles) or degraded to run-time current prices because a needed candle was
# unreachable. Flagged per record so the two are never silently mixed.
AT_MATURITY = 'at_maturity'
AT_RUN_TIME = 'scored_at_run_time'

# Sidecar judged-state schema version (F4). Bumped when the state KEY scheme or
# stored shape changes; a file whose version doesn't match is discarded and
# regenerated (the state is derived data, so re-scoring is safe). v1 was the
# implicit rec-id-keyed format with no version field; v2 is composite-keyed and
# stores `methodology`.
STATE_VERSION = 2


def state_key(rec: Dict) -> str:
    """Collision-safe judged-state key for a record (F4).

    The old analyzer keyed frozen outcomes on the record `id` alone, whose
    uniqueness is unenforced -- two records emitted in the same second for the
    same coin could collide and one would inherit the other's frozen verdict.
    This hashes the record's identifying tuple (id + timestamp + coin + action)
    so distinct records get distinct keys even when their `id`s clash.
    """
    parts = '|'.join(str(rec.get(k, '')) for k in
                     ('id', 'timestamp', 'coin_symbol', 'recommendation'))
    return hashlib.sha256(parts.encode('utf-8')).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Pure helpers (no I/O -- unit-tested directly)
# ---------------------------------------------------------------------------
def parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 history timestamp to a naive UTC datetime.

    History timestamps look like '2026-04-10T19:48:06.600002Z'. We strip the
    trailing 'Z' and parse as naive UTC (matching how the bot writes, via
    datetime.now(timezone.utc).replace(tzinfo=None)), returning None on
    anything unparseable.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace('Z', ''))
    except ValueError:
        return None


def pct_change(old: float, new: float) -> Optional[float]:
    """Percentage change from old to new, or None if old is not usable."""
    if old is None or new is None:
        return None
    try:
        old = float(old)
        new = float(new)
    except (TypeError, ValueError):
        return None
    if old == 0:
        return None
    return (new - old) / old * 100.0


def excess_return_pct(action: str, coin_return_pct: float,
                      benchmark_return_pct: float, fee_floor_pct: float) -> float:
    """Benchmark- and fee-adjusted excess return for a directional decision.

    BUY:  coin must beat the benchmark AND clear the fee floor:
              excess = (coin_return - benchmark_return) - fee_floor
    SELL: the inverse bet -- the coin must UNDER-perform the benchmark by more
          than the fee floor (getting out was worth the exit cost):
              excess = (benchmark_return - coin_return) - fee_floor

    NOTE (judgment call): the spec pinned only the BUY rule. SELL is defined
    symmetrically here, and it subtracts the same fee floor an exit incurs.
    """
    rel = coin_return_pct - benchmark_return_pct
    if action == 'BUY':
        return rel - fee_floor_pct
    if action == 'SELL':
        return (-rel) - fee_floor_pct
    raise ValueError(f"excess_return_pct: non-directional action {action!r}")


def grade(action: str, coin_return_pct: float, benchmark_return_pct: float,
          fee_floor_pct: float) -> Tuple[str, float]:
    """Return (WIN|LOSS, excess_pct) for a directional decision.

    A decision that fails to clear both the benchmark and the fee floor is a
    LOSS -- ties (excess == 0) are LOSSES, since a flat trade lost its fees.
    """
    excess = excess_return_pct(action, coin_return_pct, benchmark_return_pct, fee_floor_pct)
    return (WIN if excess > 0 else LOSS), excess


def normalize_block_reason(reason: Optional[str]) -> str:
    """Collapse a block_reason to its category for histogramming.

    block_reason strings carry a category prefix plus a detail, e.g.
    'abstain(openai:error)', 'sub_quorum: 1 of 3', 'disagreement'. We keep the
    leading category token (up to the first '(' , ':' or whitespace) so the
    histogram groups 'abstain(...)' variants together.
    """
    if not reason:
        return 'unknown'
    token = str(reason).strip()
    for sep in ('(', ':', ' '):
        idx = token.find(sep)
        if idx > 0:
            token = token[:idx]
    return token.strip().lower() or 'unknown'


def is_backup_file(name: str) -> bool:
    """True for a rotated backup ('*.bak-*') that must never be read as data."""
    return '.bak-' in os.path.basename(name)


# ---------------------------------------------------------------------------
# Loading (skips backups; reads directly from an explicit dir so tests never
# depend on module globals or the real history dir)
# ---------------------------------------------------------------------------
def recommendation_files(history_dir: str) -> List[str]:
    """Full paths of recommendation data files in history_dir, backups excluded.

    Reads recommendations.json plus any recommendations*.json shards, but NEVER
    a recommendations.json.bak-<ts> backup (T10 item 8).
    """
    out = []
    if not os.path.isdir(history_dir):
        return out
    for name in sorted(os.listdir(history_dir)):
        if not name.startswith('recommendations') or not name.endswith('.json'):
            continue
        if is_backup_file(name):
            continue
        out.append(os.path.join(history_dir, name))
    return out


def load_records(history_dir: str) -> List[Dict]:
    """Load all recommendation records from history_dir (backups skipped)."""
    recs: List[Dict] = []
    for path in recommendation_files(history_dir):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            recs.extend(data.get('recommendations', []))
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: could not read {path}: {e}")
    return recs


def load_ledger(history_dir: str) -> List[Dict]:
    """Load execution-ledger rows from history_dir/executions.json ([] if absent)."""
    path = os.path.join(history_dir, 'executions.json')
    if is_backup_file(path) or not os.path.exists(path):
        return []
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        return data.get('executions', [])
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: could not read execution ledger {path}: {e}")
        return []


# ---------------------------------------------------------------------------
# Execution-ledger fee join (pure -- takes rows explicitly)
# ---------------------------------------------------------------------------
def actual_roundtrip_fee_pct(run_id: Optional[str], coin: str,
                             ledger_rows: List[Dict], side: str = 'BUY') -> Optional[float]:
    """Actual round-trip fee % for a decision, joined from the execution ledger.

    Joins recommendation -> ledger by (run_id, coin, side): intent rows carry
    run_id/coin/side; fill rows carry fees_usd + filled_size + avg_fill_price and
    share the intent's ledger_id. We sum actual fees and actual notional across
    the matched fills and return the ENTRY fee as a percentage, DOUBLED to
    estimate the round trip (the ledger only records BUY-side fills today; the
    exit fee is assumed symmetric).

    Returns None when nothing joins (no run_id, no matching intent, or no fill
    with fee data) so the caller degrades gracefully to the assumed fee floor.

    NOTE (judgment call): the x2 round-trip estimate and the symmetric-exit
    assumption are analyzer conventions, not something the ledger records.
    """
    if not run_id:
        return None
    intent_ids = {
        r.get('ledger_id')
        for r in ledger_rows
        if r.get('status') == 'intent'
        and r.get('run_id') == run_id
        and r.get('coin') == coin
        and (r.get('side') or 'BUY').upper() == side.upper()
    }
    if not intent_ids:
        return None
    total_fees = 0.0
    total_notional = 0.0
    for r in ledger_rows:
        if r.get('ledger_id') not in intent_ids:
            continue
        fees = r.get('fees_usd')
        size = r.get('filled_size')
        price = r.get('avg_fill_price')
        if fees is None or size is None or price is None:
            continue
        try:
            notional = float(size) * float(price)
            if notional <= 0:
                continue
            total_fees += float(fees)
            total_notional += notional
        except (TypeError, ValueError):
            continue
    if total_notional <= 0:
        return None
    entry_fee_pct = total_fees / total_notional * 100.0
    return entry_fee_pct * 2.0  # round-trip estimate (entry + symmetric exit)


# ---------------------------------------------------------------------------
# Price providers
# ---------------------------------------------------------------------------
class MappingPriceProvider:
    """In-memory price provider for tests / offline use.

    current: {coin: price}. historical: {(coin, iso_timestamp): price} -- used
    for the benchmark's price at a decision's timestamp. Missing keys return
    None (which drives graceful degradation just like a failed network call).
    """

    def __init__(self, current: Optional[Dict[str, float]] = None,
                 historical: Optional[Dict[Tuple[str, str], float]] = None):
        self.current = dict(current or {})
        self.historical = dict(historical or {})

    def current_price(self, coin: str, exchange: Optional[str] = None) -> Optional[float]:
        return self.current.get(coin)

    def price_at(self, coin: str, when: datetime) -> Optional[float]:
        # Exact ISO key first, then a bare-second key, then None.
        for key in (when.isoformat(), when.isoformat() + 'Z',
                    when.replace(microsecond=0).isoformat()):
            if (coin, key) in self.historical:
                return self.historical[(coin, key)]
        return self.historical.get((coin, when.isoformat()))


class NullPriceProvider:
    """Provider that knows no prices -- used by the fast startup summary so the
    bot never blocks on the network. Every lookup returns None."""

    def current_price(self, coin: str, exchange: Optional[str] = None) -> Optional[float]:
        return None

    def price_at(self, coin: str, when: datetime) -> Optional[float]:
        return None


class CoinbasePriceProvider:
    """Best-effort live provider: Coinbase (+CoinGecko) for current prices and
    Coinbase candles for the benchmark's historical price.

    This is the only code here that touches the network, and it is intentionally
    NOT unit-tested (tests use MappingPriceProvider). Every path degrades to None
    on failure so a missing price makes a record EXPIRED_UNSCORABLE rather than
    crashing the run.
    """

    def __init__(self):
        self._trader = None
        self._client = None
        self._candle_cache: Dict[Tuple[str, str], List[Dict]] = {}
        try:
            from coinbaseutil2 import BlobbyTrader
            self._trader = BlobbyTrader()
            self._client = getattr(self._trader, 'client', None)
        except Exception as e:  # pragma: no cover - network/credential dependent
            print(f"Warning: Coinbase client unavailable ({e}); "
                  "current prices limited to fallbacks.")

    def current_price(self, coin: str, exchange: Optional[str] = None) -> Optional[float]:
        # Reuse the module-level helper (Coinbase -> CoinGecko -> Jupiter).
        return get_current_price(coin, self._trader, exchange)

    def price_at(self, coin: str, when: datetime) -> Optional[float]:  # pragma: no cover
        if self._client is None:
            return None
        try:
            import marketdata
            # Stays naive (matches `when`, a naive UTC datetime from
            # parse_timestamp) -- datetime.now(timezone.utc) is just a
            # non-deprecated source for the naive value.
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            age_days = max(1, (now - when).days + 2)
            granularity = 'ONE_HOUR' if age_days <= 10 else 'ONE_DAY'
            # Coinbase caps ~300 candles/request; cap the lookback accordingly.
            days = min(age_days, 12 if granularity == 'ONE_HOUR' else 290)
            cache_key = (coin, granularity)
            rows = self._candle_cache.get(cache_key)
            if rows is None:
                rows = marketdata.fetch_candles(self._client, f"{coin}-USD",
                                                days=days, granularity=granularity)
                self._candle_cache[cache_key] = rows
            if not rows:
                return None
            target = when.timestamp()
            closest = min(rows, key=lambda r: abs(r['time'] - target))
            return closest['close']
        except Exception as e:
            print(f"Warning: historical price for {coin} at {when} unavailable ({e})")
            return None


# ---------------------------------------------------------------------------
# Current-price fetch (kept from the previous analyzer; used by the live
# provider). Soft imports so the module loads with or without each backend.
# ---------------------------------------------------------------------------
try:
    from coinbaseutil2 import BlobbyTrader  # noqa: F401  (re-exported for provider)
    COINBASE_AVAILABLE = True
except ImportError:
    COINBASE_AVAILABLE = False

try:
    from coingeckoutil import get_coingecko_price
    COINGECKO_AVAILABLE = True
except ImportError:
    COINGECKO_AVAILABLE = False

try:
    from dex.jupiterutil import JupiterClient
    JUPITER_AVAILABLE = True
except ImportError:
    JUPITER_AVAILABLE = False


def get_current_price(coin_symbol: str, trader=None, exchange: str = None) -> Optional[float]:
    """Current USD price from the best available source, or None.

    Order: Jupiter (for solana-dex records) -> Coinbase -> CoinGecko.
    """
    if exchange == 'solana-dex' and JUPITER_AVAILABLE:
        try:
            price_data = JupiterClient().get_price(coin_symbol)
            if price_data:
                return price_data[0]
        except Exception as e:
            print(f"Jupiter error for {coin_symbol}: {e}")

    if trader is not None and COINBASE_AVAILABLE:
        try:
            product = trader.get_product_details(f"{coin_symbol}-USD")
            if product and hasattr(product, 'price'):
                return float(product.price)
        except Exception as e:
            print(f"Coinbase error for {coin_symbol}: {e}")

    if COINGECKO_AVAILABLE:
        price = get_coingecko_price(coin_symbol)
        if price is not None:
            return price
    return None


# ---------------------------------------------------------------------------
# Per-record scoring
# ---------------------------------------------------------------------------
@dataclass
class ScoredRecord:
    """The analyzer's verdict on one history record."""
    rec_id: str
    timestamp: str
    trading_mode: str
    coin: str
    action: str
    llm_source: str
    category: str                       # one of the terminal categories
    reason: str = ''                    # why it landed there
    rec_price: Optional[float] = None
    current_price: Optional[float] = None
    coin_return_pct: Optional[float] = None
    benchmark_return_pct: Optional[float] = None
    fee_floor_pct: Optional[float] = None
    fee_source: str = ''                # 'assumed' | 'ledger'
    excess_return_pct: Optional[float] = None
    outcome: Optional[str] = None       # WIN | LOSS | NEUTRAL | None
    methodology: str = ''               # AT_MATURITY | AT_RUN_TIME (F4)
    frozen: bool = False                # reused from persisted state


def _is_trading_record(rec: Dict) -> bool:
    """A record we can even consider a trade: has a coin and a rec price key."""
    return 'coin_symbol' in rec and 'price_at_recommendation' in rec


def score_record(rec: Dict, now: datetime, maturity_hours: float,
                 fee_floor_pct: float, benchmark: str,
                 provider, ledger_rows: List[Dict],
                 frozen_state: Optional[Dict[str, Dict]] = None) -> ScoredRecord:
    """Classify and (where possible) grade one record.

    Returns a ScoredRecord whose .category is exactly one terminal category.
    A previously-scored record (present in frozen_state) is returned verbatim
    from that state so re-runs never re-grade against a moved market.
    """
    rec_id = rec.get('id', '')
    ts_raw = rec.get('timestamp', '')
    coin = rec.get('coin_symbol', 'UNKNOWN')
    action = (rec.get('recommendation') or 'UNKNOWN').upper().strip()
    llm_source = rec.get('llm_source', '')
    mode = rec.get('trading_mode', 'unknown')

    def make(category, **kw):
        return ScoredRecord(rec_id=rec_id, timestamp=ts_raw, trading_mode=mode,
                            coin=coin, action=action, llm_source=llm_source,
                            category=category, **kw)

    # 0. Frozen: a record scored on a prior run stays scored (T10 item 3),
    #    keyed collision-safely on the record's identifying tuple (F4).
    skey = state_key(rec)
    if frozen_state and skey in frozen_state:
        s = frozen_state[skey]
        return make(SCORED, reason='frozen', frozen=True,
                    rec_price=s.get('rec_price'), current_price=s.get('current_price'),
                    coin_return_pct=s.get('coin_return_pct'),
                    benchmark_return_pct=s.get('benchmark_return_pct'),
                    fee_floor_pct=s.get('fee_floor_pct'), fee_source=s.get('fee_source', ''),
                    excess_return_pct=s.get('excess_return_pct'),
                    outcome=s.get('outcome'),
                    methodology=s.get('methodology', ''))

    # 1. Not a trade record at all.
    if not _is_trading_record(rec):
        return make(NON_TRADING, reason='no coin/price fields')

    # 2. Blocked panel decision -> panel-behavior track, never price-scored.
    if action == 'NONE':
        return make(BLOCKED, reason=rec.get('block_reason', ''))

    # 3. trading_mode unknown/missing -> excluded from scoring entirely.
    if mode not in ('live', 'whatif'):
        return make(EXCLUDED_UNKNOWN, reason=f"trading_mode={mode}")

    # 4. Lifecycle for live/whatif records.
    ts = parse_timestamp(ts_raw)
    if ts is None:
        return make(EXPIRED_UNSCORABLE, reason='bad_timestamp')
    age_hours = (now - ts).total_seconds() / 3600.0
    if age_hours < maturity_hours:
        return make(PENDING, reason=f"age {age_hours:.1f}h < maturity {maturity_hours:.0f}h")

    # The grading window ends at a FIXED horizon -- rec_time + maturity_hours --
    # not at "whenever the analyzer happened to run" (F4). Prices at that horizon
    # come from historical candles; if a needed candle is unreachable we degrade
    # to run-time current prices and FLAG it (methodology), never mixing the two.
    maturity_time = ts + timedelta(hours=maturity_hours)

    # 4a. HOLD -- non-directional; recorded as NEUTRAL (informational move).
    if action == 'HOLD':
        cur = provider.price_at(coin, maturity_time)
        methodology = AT_MATURITY
        if cur is None:
            cur = provider.current_price(coin, rec.get('exchange'))
            methodology = AT_RUN_TIME
        rec_price = rec.get('price_at_recommendation')
        move = pct_change(rec_price, cur) if cur is not None else None
        return make(SCORED, reason='hold_neutral', outcome=NEUTRAL,
                    rec_price=rec_price, current_price=cur, coin_return_pct=move,
                    methodology=methodology)

    # 4b. Unrecognized action (not BUY/SELL/HOLD/NONE) -- cannot grade.
    if action not in DIRECTIONAL_ACTIONS:
        return make(EXPIRED_UNSCORABLE, reason=f"unrecognized_action:{action}")

    # 4c. Directional BUY/SELL -- benchmark-relative grading at maturity.
    rec_price = rec.get('price_at_recommendation')
    try:
        rec_price = float(rec_price)
    except (TypeError, ValueError):
        rec_price = 0.0
    if not rec_price or rec_price <= 0:
        return make(EXPIRED_UNSCORABLE, reason='no_rec_price')

    # Window-END prices at the maturity horizon (preferred). If EITHER the coin's
    # or the benchmark's maturity candle is unreachable, degrade BOTH endpoints
    # to run-time current prices so the record is never graded on a mix.
    coin_end = provider.price_at(coin, maturity_time)
    bench_end = coin_end if coin == benchmark else provider.price_at(benchmark, maturity_time)
    if coin_end is not None and bench_end is not None:
        methodology = AT_MATURITY
    else:
        methodology = AT_RUN_TIME
        coin_end = provider.current_price(coin, rec.get('exchange'))
        bench_end = coin_end if coin == benchmark else provider.current_price(benchmark)

    if coin_end is None:
        return make(EXPIRED_UNSCORABLE, reason='no_current_price', methodology=methodology)
    coin_return = pct_change(rec_price, coin_end)
    if coin_return is None:
        return make(EXPIRED_UNSCORABLE, reason='no_current_price', methodology=methodology)

    # Benchmark return over the SAME window [t_rec, endpoint]. When the coin IS
    # the benchmark, there is no alternative asset -> benchmark return is 0 and
    # the decision is judged on absolute return vs fees.
    if coin == benchmark:
        bench_return = 0.0
    else:
        bench_then = provider.price_at(benchmark, ts)
        bench_return = pct_change(bench_then, bench_end) if (bench_then and bench_end) else None
        if bench_return is None:
            return make(EXPIRED_UNSCORABLE, reason='no_benchmark', methodology=methodology)

    # Fee: actual from ledger if a fill joins, else the assumed floor.
    actual_fee = actual_roundtrip_fee_pct(rec.get('run_id'), coin, ledger_rows,
                                          side=action)
    if actual_fee is not None:
        fee = actual_fee
        fee_source = 'ledger'
    else:
        fee = fee_floor_pct
        fee_source = 'assumed'

    outcome, excess = grade(action, coin_return, bench_return, fee)
    return make(SCORED, reason='graded', outcome=outcome,
                rec_price=rec_price, current_price=coin_end, coin_return_pct=coin_return,
                benchmark_return_pct=bench_return, fee_floor_pct=fee,
                fee_source=fee_source, excess_return_pct=excess,
                methodology=methodology)


# ---------------------------------------------------------------------------
# Analysis over a full history
# ---------------------------------------------------------------------------
@dataclass
class AnalysisResult:
    scored: List[ScoredRecord] = field(default_factory=list)
    all_records: List[ScoredRecord] = field(default_factory=list)
    total_loaded: int = 0

    def by_category(self, category: str) -> List[ScoredRecord]:
        return [s for s in self.all_records if s.category == category]

    def category_counts(self) -> Dict[str, int]:
        counts = {c: 0 for c in (NON_TRADING, EXCLUDED_UNKNOWN, BLOCKED,
                                 PENDING, SCORED, EXPIRED_UNSCORABLE)}
        for s in self.all_records:
            counts[s.category] = counts.get(s.category, 0) + 1
        return counts

    def scoring_universe(self) -> List[ScoredRecord]:
        """live/whatif records that enter the SCORED/PENDING/EXPIRED lifecycle."""
        return [s for s in self.all_records
                if s.trading_mode in ('live', 'whatif')
                and s.category in LIFECYCLE_BUCKETS]

    def lifecycle_counts(self) -> Dict[str, int]:
        counts = {b: 0 for b in LIFECYCLE_BUCKETS}
        for s in self.scoring_universe():
            counts[s.category] += 1
        return counts


def analyze(records: List[Dict], now: datetime, maturity_hours: float,
            fee_floor_pct: float, benchmark: str, provider,
            ledger_rows: Optional[List[Dict]] = None,
            frozen_state: Optional[Dict[str, Dict]] = None) -> AnalysisResult:
    """Classify + grade every record. Populates newly-scored records into
    frozen_state (in place) so the caller can persist them."""
    ledger_rows = ledger_rows or []
    result = AnalysisResult(total_loaded=len(records))
    for rec in records:
        s = score_record(rec, now, maturity_hours, fee_floor_pct, benchmark,
                         provider, ledger_rows, frozen_state)
        result.all_records.append(s)
        if s.category == SCORED:
            result.scored.append(s)
            # Freeze a newly graded/neutral directional or HOLD record under its
            # collision-safe composite key (F4).
            if frozen_state is not None and not s.frozen:
                frozen_state[state_key(rec)] = {
                    'rec_price': s.rec_price, 'current_price': s.current_price,
                    'coin_return_pct': s.coin_return_pct,
                    'benchmark_return_pct': s.benchmark_return_pct,
                    'fee_floor_pct': s.fee_floor_pct, 'fee_source': s.fee_source,
                    'excess_return_pct': s.excess_return_pct, 'outcome': s.outcome,
                    'methodology': s.methodology,
                    'scored_at': now.isoformat() + 'Z',
                }
    return result


# ---------------------------------------------------------------------------
# Panel-behavior stats from blocked (NONE) records
# ---------------------------------------------------------------------------
def panel_stats(records: List[Dict]) -> Dict:
    """Panel-behavior stats from blocked-decision (recommendation 'NONE') rows.

    Returns block_reason histogram (by normalized category), consensus_state
    distribution, and per-LLM vote/abstain patterns.
    """
    blocked = [r for r in records if (r.get('recommendation') or '').upper() == 'NONE']
    reason_hist: Dict[str, int] = {}
    state_hist: Dict[str, int] = {}
    per_llm: Dict[str, Dict[str, int]] = {}
    for r in blocked:
        reason = normalize_block_reason(r.get('block_reason'))
        reason_hist[reason] = reason_hist.get(reason, 0) + 1
        state = r.get('consensus_state') or 'unknown'
        state_hist[state] = state_hist.get(state, 0) + 1
        for llm, vote in (r.get('votes') or {}).items():
            bucket = 'ABSTAIN' if str(vote).upper().startswith('ABSTAIN') else str(vote).upper()
            d = per_llm.setdefault(llm, {})
            d[bucket] = d.get(bucket, 0) + 1
    return {
        'blocked_total': len(blocked),
        'block_reason_hist': reason_hist,
        'consensus_state_hist': state_hist,
        'per_llm_votes': per_llm,
    }


# ---------------------------------------------------------------------------
# Timing-only preview (no prices) for the fast, non-fatal bot-startup summary
# ---------------------------------------------------------------------------
def timing_preview(records: List[Dict], now: datetime, maturity_hours: float) -> Dict:
    """Bucket records by timing/type WITHOUT touching prices.

    Used by the bot-startup summary so it never blocks on the network. Reports
    the counts that are knowable structurally: per-mode split, mature-vs-pending
    for the live/whatif directional subset, blocked/non-trading/unknown counts.
    """
    counts = {'total': len(records), 'live': 0, 'whatif': 0, 'unknown': 0,
              'non_trading': 0, 'blocked': 0, 'mature_directional': 0,
              'pending_directional': 0, 'hold': 0}
    for r in records:
        if not _is_trading_record(r):
            counts['non_trading'] += 1
            continue
        action = (r.get('recommendation') or '').upper().strip()
        if action == 'NONE':
            counts['blocked'] += 1
            continue
        mode = r.get('trading_mode', 'unknown')
        if mode not in ('live', 'whatif'):
            counts['unknown'] += 1
            continue
        counts[mode] += 1
        if action == 'HOLD':
            counts['hold'] += 1
            continue
        if action not in DIRECTIONAL_ACTIONS:
            continue
        ts = parse_timestamp(r.get('timestamp'))
        if ts is None:
            counts['mature_directional'] += 1
            continue
        age_hours = (now - ts).total_seconds() / 3600.0
        if age_hours < maturity_hours:
            counts['pending_directional'] += 1
        else:
            counts['mature_directional'] += 1
    return counts


# ---------------------------------------------------------------------------
# Judged-flag persistence (sidecar state file)
# ---------------------------------------------------------------------------
def load_state(path: str) -> Dict[str, Dict]:
    """Load the judged-state sidecar, or {} (F4 versioned).

    A file whose `version` doesn't match STATE_VERSION -- including the v1
    format that had no version field and keyed on record `id` -- is DISCARDED
    and regenerated: the state is derived data, so those records are simply
    re-scored once (and re-frozen under the new composite key) on this run. This
    is the migration path -- no in-place rewrite of the old keys.
    """
    if not path or not os.path.exists(path) or is_backup_file(path):
        return {}
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: could not read analyzer state {path}: {e}")
        return {}
    if data.get('version') != STATE_VERSION:
        print(f"Note: analyzer state {path} is version {data.get('version')!r} "
              f"(expected {STATE_VERSION}); discarding and regenerating "
              "(derived data -- records will be re-scored).")
        return {}
    return data.get('scored', {})


def save_state(path: str, state: Dict[str, Dict]):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as f:
        json.dump({'version': STATE_VERSION, 'scored': state}, f, indent=2)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _accuracy_line(label: str, records: List[ScoredRecord]) -> str:
    wins = sum(1 for s in records if s.outcome == WIN)
    losses = sum(1 for s in records if s.outcome == LOSS)
    judged = wins + losses
    if judged == 0:
        return f"  {label}: none graded"
    return f"  {label}: {wins}/{judged} win ({100 * wins / judged:.1f}%)"


def print_mode_section(mode: str, result: AnalysisResult):
    """Print the scored section for one trading_mode (live or whatif)."""
    scored = [s for s in result.scored if s.trading_mode == mode]
    directional = [s for s in scored if s.action in DIRECTIONAL_ACTIONS]
    holds = [s for s in scored if s.action == 'HOLD']
    print(f"\n--- {mode.upper()} SCORED ({len(scored)} records) ---")
    if not scored:
        print("  (none)")
        return
    print(_accuracy_line('BUY ', [s for s in directional if s.action == 'BUY']))
    print(_accuracy_line('SELL', [s for s in directional if s.action == 'SELL']))
    if holds:
        print(f"  HOLD: {len(holds)} recorded (no win/loss)")
    ledger_fees = sum(1 for s in directional if s.fee_source == 'ledger')
    if ledger_fees:
        print(f"  fees: {ledger_fees}/{len(directional)} graded used ACTUAL ledger fees")
    at_mat = sum(1 for s in directional if s.methodology == AT_MATURITY)
    at_run = sum(1 for s in directional if s.methodology == AT_RUN_TIME)
    if directional:
        print(f"  methodology: {at_mat} at-maturity, {at_run} degraded to run-time")
    # per-LLM
    per_llm: Dict[str, Dict[str, int]] = {}
    for s in directional:
        d = per_llm.setdefault(s.llm_source or 'unknown', {'win': 0, 'loss': 0})
        if s.outcome == WIN:
            d['win'] += 1
        elif s.outcome == LOSS:
            d['loss'] += 1
    if per_llm:
        print("  per-LLM:")
        for llm, d in sorted(per_llm.items()):
            judged = d['win'] + d['loss']
            if judged:
                print(f"    {llm}: {d['win']}/{judged} win ({100 * d['win'] / judged:.1f}%)")
            else:
                print(f"    {llm}: 0 graded")


def print_report(result: AnalysisResult, records: List[Dict], now: datetime,
                 maturity_hours: float, verbose: bool = False):
    print("=== TRADING BOT ANALYSIS REPORT ===")
    print(f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC "
          f"(maturity {maturity_hours:.0f}h)")
    print(f"Total records loaded: {result.total_loaded}")

    cc = result.category_counts()
    print("\n--- RECORD ACCOUNTING (every record in exactly one category) ---")
    print(f"  non-trading:        {cc[NON_TRADING]}")
    print(f"  excluded (unknown): {cc[EXCLUDED_UNKNOWN]}")
    print(f"  blocked (NONE):     {cc[BLOCKED]}")
    print(f"  pending:            {cc[PENDING]}")
    print(f"  scored:             {cc[SCORED]}")
    print(f"  expired-unscorable: {cc[EXPIRED_UNSCORABLE]}")
    print(f"  sum:                {sum(cc.values())} (== total loaded: "
          f"{sum(cc.values()) == result.total_loaded})")

    lc = result.lifecycle_counts()
    print("\n--- LIFECYCLE (live/whatif directional+HOLD; 0h..inf coverage) ---")
    print(f"  SCORED {lc[SCORED]} | PENDING {lc[PENDING]} | "
          f"EXPIRED_UNSCORABLE {lc[EXPIRED_UNSCORABLE]}")

    print_mode_section('live', result)
    print_mode_section('whatif', result)

    # Expired-unscorable reasons (so nothing is a silent drop).
    expired = result.by_category(EXPIRED_UNSCORABLE)
    if expired:
        reason_hist: Dict[str, int] = {}
        for s in expired:
            reason_hist[s.reason] = reason_hist.get(s.reason, 0) + 1
        print("\n--- EXPIRED-UNSCORABLE REASONS ---")
        for reason, n in sorted(reason_hist.items()):
            print(f"  {reason}: {n}")

    # Panel behavior from blocked records.
    ps = panel_stats(records)
    if ps['blocked_total']:
        print(f"\n--- PANEL BEHAVIOR ({ps['blocked_total']} blocked decisions) ---")
        print("  block_reason histogram:")
        for reason, n in sorted(ps['block_reason_hist'].items(), key=lambda kv: -kv[1]):
            print(f"    {reason}: {n}")
        print("  consensus_state distribution:")
        for state, n in sorted(ps['consensus_state_hist'].items(), key=lambda kv: -kv[1]):
            print(f"    {state}: {n}")
        if ps['per_llm_votes']:
            print("  per-LLM vote/abstain patterns:")
            for llm, votes in sorted(ps['per_llm_votes'].items()):
                parts = ', '.join(f"{k}={v}" for k, v in sorted(votes.items()))
                print(f"    {llm}: {parts}")

    if verbose:
        print("\n--- PER-RECORD DETAIL ---")
        for s in result.all_records:
            extra = ''
            if s.outcome is not None:
                extra = (f" {s.outcome} excess={s.excess_return_pct:.2f}%"
                         if s.excess_return_pct is not None else f" {s.outcome}")
            print(f"  [{s.category}] {s.trading_mode}/{s.coin}/{s.action}"
                  f"{extra} ({s.reason})")


CSV_FIELDS = ['rec_id', 'timestamp', 'trading_mode', 'coin', 'action', 'llm_source',
              'category', 'reason', 'rec_price', 'current_price', 'coin_return_pct',
              'benchmark_return_pct', 'fee_floor_pct', 'fee_source',
              'excess_return_pct', 'outcome', 'methodology', 'frozen']


def export_csv(result: AnalysisResult, mode: str, output_dir: str, now: datetime) -> Optional[str]:
    rows = [s for s in result.scored if s.trading_mode == mode]
    if not rows:
        return None
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"analysis_{mode}_{now.strftime('%Y%m%d')}.csv")
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for s in rows:
            writer.writerow({k: getattr(s, k) for k in CSV_FIELDS})
    return path


# ---------------------------------------------------------------------------
# Startup summary (called from crypto_trading_bot.main(); must be NON-FATAL)
# ---------------------------------------------------------------------------
def run_startup_summary(history_dir: Optional[str] = None,
                        maturity_hours: float = DEFAULT_MATURITY_HOURS) -> None:
    """Fast, price-free, non-fatal history summary for bot startup.

    Prints structural counts (per-mode split, mature-vs-pending directional,
    blocked panel stats) that need no network. Any exception is swallowed with a
    warning -- this must NEVER block trading.
    """
    try:
        history_dir = history_dir or os.environ.get('HISTORY_DIR', './history/')
        records = load_records(history_dir)
        # Naive UTC (matches parse_timestamp's naive output) via the
        # non-deprecated source.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = timing_preview(records, now, maturity_hours)
        print("\n[ANALYZER] History summary "
              f"({p['total']} records from {history_dir}):")
        print(f"  live={p['live']} whatif={p['whatif']} unknown={p['unknown']} "
              f"blocked={p['blocked']} non-trading={p['non_trading']}")
        print(f"  directional: {p['mature_directional']} mature (scoreable), "
              f"{p['pending_directional']} pending (<{maturity_hours:.0f}h); "
              f"HOLD={p['hold']}")
        ps = panel_stats(records)
        if ps['blocked_total']:
            top = sorted(ps['block_reason_hist'].items(), key=lambda kv: -kv[1])
            summary = ', '.join(f"{r}={n}" for r, n in top[:4])
            print(f"  panel blocks by reason: {summary}")
        print("  (run `python tradeanalyzer.py` for full benchmark-relative scoring)")
    except Exception as e:  # non-fatal by contract
        print(f"[ANALYZER] startup summary skipped (non-fatal): {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Trade Analyzer -- benchmark-relative scorer/reporter for '
                    'recommendation history (no backtester, no equity curve).',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--history-dir',
                        default=os.environ.get('HISTORY_DIR', './history/'),
                        help='Directory holding recommendations.json + executions.json')
    parser.add_argument('--output-dir', default=None,
                        help='Where to write CSVs + state file (default: history-dir)')
    parser.add_argument('--maturity-hours', type=float, default=DEFAULT_MATURITY_HOURS,
                        help='A decision younger than this is pending, not scored')
    parser.add_argument('--fee-floor-pct', type=float, default=DEFAULT_FEE_FLOOR_PCT,
                        help='Assumed round-trip fee floor when the ledger has no fill')
    parser.add_argument('--benchmark', default=DEFAULT_BENCHMARK,
                        help='Benchmark symbol a BUY must beat over the same window')
    parser.add_argument('--now', default=None,
                        help='Override evaluation time (ISO-8601 UTC); default: utcnow')
    parser.add_argument('--offline', action='store_true',
                        help='Do not fetch live prices (uses the null provider)')
    parser.add_argument('--no-csv', action='store_true', help='Skip CSV export')
    parser.add_argument('--no-state', action='store_true',
                        help='Disable judged-flag persistence (do not read/write state)')
    parser.add_argument('--state-file', default=None,
                        help='Path to the judged-flag state file '
                             '(default: <output-dir>/analyzer_state.json)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Print a per-record detail line')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Suppress the console report (still writes CSV/state)')
    return parser


def cli_main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir or args.history_dir
    # Naive UTC (matches parse_timestamp's naive output, and `parsed` below)
    # via the non-deprecated source.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if args.now:
        parsed = parse_timestamp(args.now)
        if parsed is None:
            print(f"Warning: could not parse --now {args.now!r}; using utcnow")
        else:
            now = parsed

    records = load_records(args.history_dir)
    ledger_rows = load_ledger(args.history_dir)

    provider = NullPriceProvider() if args.offline else CoinbasePriceProvider()

    state_path = None
    frozen_state: Optional[Dict[str, Dict]] = None
    if not args.no_state:
        state_path = args.state_file or os.path.join(output_dir, 'analyzer_state.json')
        frozen_state = load_state(state_path)

    result = analyze(records, now, args.maturity_hours, args.fee_floor_pct,
                     args.benchmark, provider, ledger_rows, frozen_state)

    if not args.quiet:
        print_report(result, records, now, args.maturity_hours, verbose=args.verbose)

    written = []
    if not args.no_csv:
        for mode in ('live', 'whatif'):
            path = export_csv(result, mode, output_dir, now)
            if path:
                written.append(path)
    if state_path is not None and frozen_state is not None:
        save_state(state_path, frozen_state)
        written.append(state_path)
    if written and not args.quiet:
        print("\nWritten:")
        for p in written:
            print(f"  {p}")
    return 0


def main():  # backwards-compatible entry point
    sys.exit(cli_main())


if __name__ == '__main__':
    main()
