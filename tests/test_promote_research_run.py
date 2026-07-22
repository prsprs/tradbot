"""Tests for scripts/promote_research_run.py (WS5: scratch-run promotion).

All offline -- these tests only touch tmp_path fixtures, never the repo's
real history/ or research_corpus/. The module's DEFAULT_CORPUS_DIR and
GITIGNORE_PATH module globals are monkeypatched to tmp_path locations in
every test so a test run can never write to the real repo root .gitignore
or create a real research_corpus/ directory (see AGENTS.md's test-authoring
traps: never let a test touch real repo paths that a legitimate run would
also touch).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / 'scripts' / 'promote_research_run.py'

# scripts/ is excluded from pytest collection (pytest.ini norecursedirs) and
# is not a package, so load the module directly by path rather than a normal
# import -- mirrors how one-off repo scripts are exercised in isolation.
_spec = importlib.util.spec_from_file_location('promote_research_run', SCRIPT_PATH)
promote_research_run = importlib.util.module_from_spec(_spec)
sys.modules['promote_research_run'] = promote_research_run
_spec.loader.exec_module(promote_research_run)


def make_rec(rec_id, coin='BTC', trading_mode='whatif', recommendation='BUY'):
    return {
        'id': rec_id,
        'timestamp': '2026-07-20T12:00:00Z',
        'coin_symbol': coin,
        'recommendation': recommendation,
        'price_at_recommendation': 100.0,
        'bid_price': 99.5,
        'ask_price': 100.5,
        'llm_source': 'gemini',
        'mode': 'gemini',
        'consensus': None,
        'discovery_llm': None,
        'trading_mode': trading_mode,
        'run_id': 'run_20260720T120000Z',
    }


def write_recommendations(scratch_dir, records):
    scratch_dir.mkdir(parents=True, exist_ok=True)
    with open(scratch_dir / 'recommendations.json', 'w') as f:
        json.dump({'recommendations': records}, f)


def write_executions(scratch_dir, rows):
    scratch_dir.mkdir(parents=True, exist_ok=True)
    with open(scratch_dir / 'executions.json', 'w') as f:
        json.dump({'executions': rows}, f)


def read_corpus_recommendations(corpus_dir):
    path = corpus_dir / 'recommendations.json'
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)['recommendations']


@pytest.fixture(autouse=True)
def isolate_repo_paths(tmp_path, monkeypatch):
    """Redirect the module's repo-root-relative globals into tmp_path so no
    test can ever touch the real .gitignore or create a real
    research_corpus/ directory."""
    fake_gitignore = tmp_path / '.gitignore'
    fake_gitignore.write_text("history/*\n!history/__init__.py\n")
    monkeypatch.setattr(promote_research_run, 'GITIGNORE_PATH', fake_gitignore)
    return fake_gitignore


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_promotes_whatif_records(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [
        make_rec('rec_1', trading_mode='whatif'),
        make_rec('rec_2', trading_mode='whatif'),
    ])

    result = promote_research_run.promote(scratch, corpus)

    assert result['promoted'] == 2
    assert result['skipped'] == 0
    corpus_recs = read_corpus_recommendations(corpus)
    assert {r['id'] for r in corpus_recs} == {'rec_1', 'rec_2'}


def test_happy_path_adds_gitignore_entry(tmp_path, isolate_repo_paths):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])

    promote_research_run.promote(scratch, corpus)

    text = isolate_repo_paths.read_text()
    assert 'research_corpus/' in text


def test_gitignore_entry_not_duplicated_when_already_present(tmp_path, isolate_repo_paths, monkeypatch):
    isolate_repo_paths.write_text("history/*\nresearch_corpus/\n")
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])

    promote_research_run.promote(scratch, corpus)

    text = isolate_repo_paths.read_text()
    assert text.count('research_corpus/') == 1


def test_with_panel_logs_copies_new_logs(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])
    panel_dir = scratch / 'panel_responses'
    panel_dir.mkdir(parents=True)
    (panel_dir / 'run_20260720T120000Z.log').write_text('panel transcript text')

    result = promote_research_run.promote(scratch, corpus, with_panel_logs=True)

    assert result['panel_logs_copied'] == 1
    dest = corpus / 'panel_responses' / 'run_20260720T120000Z.log'
    assert dest.exists()
    assert dest.read_text() == 'panel transcript text'


def test_without_panel_logs_flag_no_logs_copied(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])
    panel_dir = scratch / 'panel_responses'
    panel_dir.mkdir(parents=True)
    (panel_dir / 'run_20260720T120000Z.log').write_text('panel transcript text')

    promote_research_run.promote(scratch, corpus, with_panel_logs=False)

    assert not (corpus / 'panel_responses').exists()


# ---------------------------------------------------------------------------
# Dedupe / idempotency
# ---------------------------------------------------------------------------

def test_rerun_on_same_scratch_dir_adds_nothing(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1'), make_rec('rec_2')])

    first = promote_research_run.promote(scratch, corpus)
    second = promote_research_run.promote(scratch, corpus)

    assert first['promoted'] == 2
    assert second['promoted'] == 0
    assert second['skipped'] == 2
    corpus_recs = read_corpus_recommendations(corpus)
    assert len(corpus_recs) == 2


def test_partial_overlap_only_promotes_new_ids(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])
    promote_research_run.promote(scratch, corpus)

    write_recommendations(scratch, [make_rec('rec_1'), make_rec('rec_2')])
    result = promote_research_run.promote(scratch, corpus)

    assert result['promoted'] == 1
    corpus_recs = read_corpus_recommendations(corpus)
    assert {r['id'] for r in corpus_recs} == {'rec_1', 'rec_2'}


def test_panel_log_copy_is_idempotent(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])
    panel_dir = scratch / 'panel_responses'
    panel_dir.mkdir(parents=True)
    (panel_dir / 'run_x.log').write_text('v1')

    r1 = promote_research_run.promote(scratch, corpus, with_panel_logs=True)
    r2 = promote_research_run.promote(scratch, corpus, with_panel_logs=True)

    assert r1['panel_logs_copied'] == 1
    assert r2['panel_logs_copied'] == 0


# ---------------------------------------------------------------------------
# Live-record refusal
# ---------------------------------------------------------------------------

def test_live_record_is_skipped_not_promoted(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [
        make_rec('rec_live', trading_mode='live'),
        make_rec('rec_whatif', trading_mode='whatif'),
    ])

    result = promote_research_run.promote(scratch, corpus)

    assert result['promoted'] == 1
    corpus_recs = read_corpus_recommendations(corpus)
    ids = {r['id'] for r in corpus_recs}
    assert ids == {'rec_whatif'}
    assert 'rec_live' not in ids


def test_unknown_trading_mode_record_is_skipped(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1', trading_mode='unknown')])

    result = promote_research_run.promote(scratch, corpus)

    assert result['promoted'] == 0
    assert read_corpus_recommendations(corpus) == []


def test_live_execution_ledger_row_refuses_entire_run(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1', trading_mode='whatif')])
    write_executions(scratch, [
        {'ledger_id': 'led_1', 'run_id': 'run_x', 'trading_mode': 'live',
         'coin': 'BTC', 'side': 'BUY', 'status': 'intent'},
    ])

    with pytest.raises(promote_research_run.PromotionError, match='live'):
        promote_research_run.promote(scratch, corpus)

    # Corpus must be left completely untouched.
    assert not corpus.exists()


def test_whatif_only_execution_ledger_does_not_block(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1', trading_mode='whatif')])
    write_executions(scratch, [
        {'ledger_id': 'led_1', 'run_id': 'run_x', 'trading_mode': 'whatif',
         'coin': 'BTC', 'side': 'BUY', 'status': 'intent'},
    ])

    result = promote_research_run.promote(scratch, corpus)

    assert result['promoted'] == 1


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def test_dry_run_makes_no_changes(tmp_path, isolate_repo_paths):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])
    gitignore_before = isolate_repo_paths.read_text()

    result = promote_research_run.promote(scratch, corpus, dry_run=True)

    assert result['promoted'] == 1  # reports what WOULD be promoted
    assert not corpus.exists()
    assert isolate_repo_paths.read_text() == gitignore_before


def test_dry_run_does_not_copy_panel_logs(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])
    panel_dir = scratch / 'panel_responses'
    panel_dir.mkdir(parents=True)
    (panel_dir / 'run_x.log').write_text('v1')

    promote_research_run.promote(scratch, corpus, with_panel_logs=True, dry_run=True)

    assert not (corpus / 'panel_responses').exists()


def test_dry_run_never_touches_scratch_dir(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])
    rec_path = scratch / 'recommendations.json'
    before = rec_path.read_bytes()

    promote_research_run.promote(scratch, corpus, dry_run=True)

    assert rec_path.read_bytes() == before


# ---------------------------------------------------------------------------
# Missing / malformed scratch dir
# ---------------------------------------------------------------------------

def test_missing_scratch_dir_raises_clear_error(tmp_path):
    scratch = tmp_path / 'does_not_exist'
    corpus = tmp_path / 'corpus'

    with pytest.raises(promote_research_run.PromotionError, match='not found'):
        promote_research_run.promote(scratch, corpus)


def test_scratch_dir_missing_recommendations_file_raises_clear_error(tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    corpus = tmp_path / 'corpus'

    with pytest.raises(promote_research_run.PromotionError, match='recommendations.json'):
        promote_research_run.promote(scratch, corpus)


def test_scratch_dir_malformed_json_raises_clear_error(tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    (scratch / 'recommendations.json').write_text('{not valid json')
    corpus = tmp_path / 'corpus'

    with pytest.raises(promote_research_run.PromotionError, match='unreadable|malformed'):
        promote_research_run.promote(scratch, corpus)


def test_scratch_dir_wrong_shape_raises_clear_error(tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    (scratch / 'recommendations.json').write_text(json.dumps({'not_recommendations': []}))
    corpus = tmp_path / 'corpus'

    with pytest.raises(promote_research_run.PromotionError, match='wrong shape'):
        promote_research_run.promote(scratch, corpus)


def test_malformed_corpus_file_raises_clear_error(tmp_path):
    scratch = tmp_path / 'scratch'
    corpus = tmp_path / 'corpus'
    write_recommendations(scratch, [make_rec('rec_1')])
    corpus.mkdir(parents=True)
    (corpus / 'recommendations.json').write_text('{not valid json')

    with pytest.raises(promote_research_run.PromotionError, match='unreadable|malformed'):
        promote_research_run.promote(scratch, corpus)


# ---------------------------------------------------------------------------
# select_promotable (unit-level, no filesystem)
# ---------------------------------------------------------------------------

def test_select_promotable_splits_correctly():
    records = [
        make_rec('a', trading_mode='whatif'),
        make_rec('b', trading_mode='live'),
        make_rec('c', trading_mode='whatif'),
    ]
    promotable, skipped = promote_research_run.select_promotable(records, existing_corpus_ids={'c'})

    assert [r['id'] for r in promotable] == ['a']
    skipped_ids = [r['id'] for r, _ in skipped]
    assert skipped_ids == ['b', 'c']
