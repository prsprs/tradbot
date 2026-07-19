"""Tests for T2 (history integrity + curated backfill, plan Phase 0).

Covers:
  1. create_recommendation_record carries trading_mode/run_id, defaulting to
     trading_mode='unknown' / run_id=None when the caller doesn't supply them.
  2. An invalid trading_mode is rejected (ValueError) rather than silently
     written.
  3. A legacy record (written before T2, missing trading_mode/run_id
     entirely) still loads fine -- load_recommendations does no schema
     validation, and the new fields are optional on read.
  4. scripts/backfill_trading_mode.py's apply_backfill / backfill_file logic,
     unit-tested against synthetic fixtures: idempotency (a second run is a
     no-op) and preservation (every unrelated field is byte-identical before
     and after).

Also includes a light regression guard: every 2026-07-18 record in the real
history/recommendations.json has an explicit entry in the production
MAPPING (read-only check; does not touch the file).
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import historyutil
import backfill_trading_mode as backfill


# ============================================================================
# 1 & 2. create_recommendation_record: trading_mode / run_id
# ============================================================================

_BASE = dict(
    coin_symbol='ETH', recommendation='HOLD', price=1900.0,
    bid_price=1899.0, ask_price=1901.0, llm_source='gemini', mode='compare',
)


def test_default_trading_mode_is_unknown_and_run_id_none():
    """A caller that doesn't pass trading_mode/run_id gets the documented
    defaults, not a missing key or a crash."""
    record = historyutil.create_recommendation_record(**_BASE)
    assert record['trading_mode'] == 'unknown'
    assert record['run_id'] is None


@pytest.mark.parametrize('mode', ['live', 'whatif', 'unknown'])
def test_valid_trading_modes_accepted(mode):
    record = historyutil.create_recommendation_record(
        trading_mode=mode, run_id='run_20260718T195400Z', **_BASE
    )
    assert record['trading_mode'] == mode
    assert record['run_id'] == 'run_20260718T195400Z'


def test_invalid_trading_mode_rejected():
    """An unrecognized trading_mode must never be silently written to
    history -- it's a data-integrity field the analyzer will rely on."""
    with pytest.raises(ValueError):
        historyutil.create_recommendation_record(trading_mode='simulated', **_BASE)


def test_invalid_trading_mode_message_names_valid_values():
    with pytest.raises(ValueError, match='live'):
        historyutil.create_recommendation_record(trading_mode='bogus', **_BASE)


def test_valid_trading_modes_constant_matches_schema():
    assert historyutil.VALID_TRADING_MODES == {'live', 'whatif', 'unknown'}


def test_run_id_accepts_a_string():
    record = historyutil.create_recommendation_record(
        run_id='run_20260718T195400Z', **_BASE
    )
    assert record['run_id'] == 'run_20260718T195400Z'


# ============================================================================
# 1b. Timestamp format regression guard (datetime.utcnow() -> timezone-aware
# migration, T11). create_recommendation_record must keep writing a NAIVE
# ISO-8601 string with a literal trailing 'Z' -- no embedded '+00:00' offset
# -- because tradeanalyzer.parse_timestamp strips a trailing 'Z' and parses
# as naive (doc: tradeanalyzer.parse_timestamp docstring). A switch to
# datetime.now(timezone.utc).isoformat() (which appends '+00:00') would
# silently corrupt every future record's timestamp into an unparseable
# '...+00:00Z' string.
# ============================================================================

import re as _re

_NAIVE_Z_TIMESTAMP_RE = _re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$'
)


def test_timestamp_is_naive_iso_with_trailing_z_not_embedded_offset():
    record = historyutil.create_recommendation_record(**_BASE)
    ts = record['timestamp']
    assert _NAIVE_Z_TIMESTAMP_RE.match(ts), (
        f"timestamp {ts!r} is not a naive 'Z'-suffixed ISO-8601 string "
        "(datetime.now(timezone.utc).isoformat() would add '+00:00' here)"
    )


def test_timestamp_round_trips_through_tradeanalyzer_parse_timestamp():
    sys.path.insert(0, str(REPO_ROOT))
    import tradeanalyzer
    record = historyutil.create_recommendation_record(**_BASE)
    parsed = tradeanalyzer.parse_timestamp(record['timestamp'])
    assert parsed is not None
    assert parsed.tzinfo is None  # parse_timestamp always returns naive


def test_record_recommendation_passes_trading_mode_and_run_id_through():
    """record_recommendation (the convenience wrapper used by the two
    crypto_trading_bot.py call sites) forwards trading_mode/run_id into the
    saved record, using a fake trader so no network/disk I/O occurs."""

    class FakeProduct:
        price = '1900.0'
        bid = '1899.0'
        ask = '1901.0'

    class FakeTrader:
        def get_product_details(self, symbol):
            return FakeProduct()

    saved = {}

    def fake_save(rec):
        saved.update(rec)

    import unittest.mock as mock
    with mock.patch.object(historyutil, 'save_recommendation', fake_save):
        result = historyutil.record_recommendation(
            coin_symbol='ETH', recommendation='HOLD', trader=FakeTrader(),
            llm_source='gemini', mode='compare',
            trading_mode='live', run_id='run_20260718T195400Z',
        )

    assert result is not None
    assert result['trading_mode'] == 'live'
    assert result['run_id'] == 'run_20260718T195400Z'
    assert saved['trading_mode'] == 'live'
    assert saved['run_id'] == 'run_20260718T195400Z'


# ============================================================================
# 3. Legacy records (pre-T2 schema) load fine
# ============================================================================

_LEGACY_RECORD = {
    'id': 'rec_20260410_194806_SHIB',
    'timestamp': '2026-04-10T19:48:06.600002Z',
    'coin_symbol': 'SHIB',
    'recommendation': 'HOLD',
    'price_at_recommendation': 6.01e-06,
    'bid_price': 6.01e-06,
    'ask_price': 6.01e-06,
    'llm_source': 'grok',
    'mode': 'compare,',
    'consensus': None,
}


def test_legacy_record_without_new_fields_loads_fine(tmp_path, monkeypatch):
    """A record written before T2 (no trading_mode/run_id keys at all)
    round-trips through load_recommendations without error, and the missing
    fields are simply absent (not None, not a crash) -- callers use .get()."""
    legacy_file = tmp_path / 'recommendations.json'
    legacy_file.write_text(json.dumps({'recommendations': [_LEGACY_RECORD]}))
    monkeypatch.setattr(historyutil, 'RECOMMENDATIONS_FILE', str(legacy_file))

    loaded = historyutil.load_recommendations()

    assert len(loaded) == 1
    assert loaded[0]['coin_symbol'] == 'SHIB'
    assert 'trading_mode' not in loaded[0]
    assert 'run_id' not in loaded[0]
    assert loaded[0].get('trading_mode', 'unknown') == 'unknown'


def test_legacy_and_new_records_coexist_in_the_same_file(tmp_path, monkeypatch):
    """A file with a mix of pre-T2 and post-T2 records loads both without
    error (the real history/recommendations.json is exactly this shape
    after the backfill: 8 records with a real mode, 40 with 'unknown')."""
    new_record = historyutil.create_recommendation_record(
        trading_mode='live', run_id='run_20260718T195400Z', **_BASE
    )
    mixed_file = tmp_path / 'recommendations.json'
    mixed_file.write_text(json.dumps({'recommendations': [_LEGACY_RECORD, new_record]}))
    monkeypatch.setattr(historyutil, 'RECOMMENDATIONS_FILE', str(mixed_file))

    loaded = historyutil.load_recommendations()

    assert len(loaded) == 2
    assert 'trading_mode' not in loaded[0]
    assert loaded[1]['trading_mode'] == 'live'


# ============================================================================
# 4. Backfill script: apply_backfill / backfill_file against synthetic fixtures
# ============================================================================

def _synth_record(rec_id, coin='ETH', rec='HOLD', extra=None):
    r = {
        'id': rec_id,
        'timestamp': '2026-04-10T19:48:06.600002Z',
        'coin_symbol': coin,
        'recommendation': rec,
        'price_at_recommendation': 100.0,
        'bid_price': 100.0,
        'ask_price': 100.0,
        'llm_source': 'gemini',
        'mode': 'compare',
        'consensus': None,
    }
    if extra:
        r.update(extra)
    return r


def test_apply_backfill_maps_known_ids_and_defaults_unknown():
    records = [
        _synth_record('rec_live_1'),
        _synth_record('rec_whatif_1'),
        _synth_record('rec_not_in_mapping'),
    ]
    mapping = {'rec_live_1': 'live', 'rec_whatif_1': 'whatif'}

    new_records, changed, skipped = backfill.apply_backfill(records, mapping=mapping)

    assert changed == 3
    assert skipped == 0
    by_id = {r['id']: r for r in new_records}
    assert by_id['rec_live_1']['trading_mode'] == 'live'
    assert by_id['rec_whatif_1']['trading_mode'] == 'whatif'
    assert by_id['rec_not_in_mapping']['trading_mode'] == 'unknown'


def test_apply_backfill_idempotent_second_run_is_noop():
    records = [_synth_record('rec_a'), _synth_record('rec_b')]
    mapping = {'rec_a': 'live', 'rec_b': 'whatif'}

    first_pass, changed1, skipped1 = backfill.apply_backfill(records, mapping=mapping)
    assert changed1 == 2
    assert skipped1 == 0

    second_pass, changed2, skipped2 = backfill.apply_backfill(first_pass, mapping=mapping)
    assert changed2 == 0
    assert skipped2 == 2
    assert second_pass == first_pass


def test_apply_backfill_skips_records_that_already_have_trading_mode():
    """A record that already carries trading_mode (from any source, not
    just a prior backfill run) is left completely alone, even if the
    mapping would say something different -- presence of the key wins."""
    already_tagged = _synth_record('rec_c', extra={'trading_mode': 'live'})
    untagged = _synth_record('rec_d')
    mapping = {'rec_c': 'whatif', 'rec_d': 'whatif'}  # deliberately conflicting for rec_c

    new_records, changed, skipped = backfill.apply_backfill([already_tagged, untagged], mapping=mapping)

    assert changed == 1
    assert skipped == 1
    by_id = {r['id']: r for r in new_records}
    assert by_id['rec_c']['trading_mode'] == 'live'  # untouched, not overwritten to whatif
    assert by_id['rec_d']['trading_mode'] == 'whatif'


def test_apply_backfill_preserves_unrelated_fields_verbatim():
    """Every field other than the newly-added trading_mode is byte-for-byte
    (via equality) identical to the input -- the backfill adds exactly one
    key and touches nothing else."""
    original = _synth_record('rec_e', coin='PEPE', rec='SELL',
                              extra={'exchange': 'cex', 'discovery_llm': 'gemini'})
    original_copy = json.loads(json.dumps(original))  # deep copy for comparison

    new_records, changed, _ = backfill.apply_backfill([original], mapping={'rec_e': 'live'})
    assert changed == 1
    (patched,) = new_records

    assert patched['trading_mode'] == 'live'
    without_new_field = {k: v for k, v in patched.items() if k != 'trading_mode'}
    assert without_new_field == original_copy
    # the input list's dict itself must not have been mutated in place
    assert 'trading_mode' not in original


def test_apply_backfill_rejects_mapping_with_invalid_mode():
    records = [_synth_record('rec_f')]
    with pytest.raises(ValueError):
        backfill.apply_backfill(records, mapping={'rec_f': 'simulated'})


def test_mode_counts_distinguishes_missing_from_unknown():
    has_none = _synth_record('rec_g', extra={'trading_mode': 'unknown'})
    has_nothing = _synth_record('rec_h')
    counts = backfill.mode_counts([has_none, has_nothing])
    assert counts == {'live': 0, 'whatif': 0, 'unknown': 1, 'missing': 1}


# ---- backfill_file: end-to-end against a temp JSON file -------------------

def test_backfill_file_end_to_end_writes_backup_and_updates(tmp_path):
    target = tmp_path / 'recommendations.json'
    original_records = [_synth_record('rec_x'), _synth_record('rec_y')]
    target.write_text(json.dumps({'recommendations': original_records}, indent=2))
    original_text = target.read_text()

    result = backfill.backfill_file(
        target, mapping={'rec_x': 'live', 'rec_y': 'whatif'}
    )

    assert result['changed'] == 2
    assert result['skipped'] == 0
    assert result['before'] == {'live': 0, 'whatif': 0, 'unknown': 0, 'missing': 2}
    assert result['after'] == {'live': 1, 'whatif': 1, 'unknown': 0, 'missing': 0}

    # backup exists and is byte-identical to the pre-backfill content
    backup_path = Path(result['backup'])
    assert backup_path.exists()
    assert backup_path.read_text() == original_text

    updated = json.loads(target.read_text())['recommendations']
    by_id = {r['id']: r for r in updated}
    assert by_id['rec_x']['trading_mode'] == 'live'
    assert by_id['rec_y']['trading_mode'] == 'whatif'


def test_backfill_file_second_run_is_noop_and_writes_no_new_backup(tmp_path):
    target = tmp_path / 'recommendations.json'
    target.write_text(json.dumps({'recommendations': [_synth_record('rec_z')]}, indent=2))

    first = backfill.backfill_file(target, mapping={'rec_z': 'live'})
    assert first['changed'] == 1
    assert first['backup'] is not None

    after_first_run = target.read_text()
    second = backfill.backfill_file(target, mapping={'rec_z': 'live'})

    assert second['changed'] == 0
    assert second['skipped'] == 1
    assert second['backup'] is None  # no backup written for a no-op run
    assert target.read_text() == after_first_run  # file untouched


def test_backfill_file_dry_run_does_not_write(tmp_path):
    target = tmp_path / 'recommendations.json'
    original_text = json.dumps({'recommendations': [_synth_record('rec_w')]}, indent=2)
    target.write_text(original_text)

    result = backfill.backfill_file(target, mapping={'rec_w': 'live'}, dry_run=True)

    assert result['changed'] == 1
    assert result['backup'] is None
    assert target.read_text() == original_text  # unchanged on disk
    # and no backup file was created
    assert list(tmp_path.glob('*.bak-*')) == []


# ============================================================================
# Regression guard: the production MAPPING in scripts/backfill_trading_mode.py
# explicitly covers every 2026-07-18 record in the real history file (read-
# only -- does not modify history/recommendations.json).
# ============================================================================

def test_production_mapping_values_are_all_valid():
    assert set(backfill.MAPPING.values()) <= backfill.VALID_MODES


def test_production_mapping_covers_every_2026_07_18_record_in_real_history():
    real_history = REPO_ROOT / 'history' / 'recommendations.json'
    if not real_history.exists():
        pytest.skip('history/recommendations.json not present in this checkout')
    with open(real_history) as f:
        records = json.load(f).get('recommendations', [])
    july18_ids = {r['id'] for r in records if r['timestamp'].startswith('2026-07-18')}
    missing = july18_ids - set(backfill.MAPPING.keys())
    assert not missing, f"2026-07-18 records with no explicit MAPPING entry: {sorted(missing)}"
