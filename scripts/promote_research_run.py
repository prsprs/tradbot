#!/usr/bin/env python3
"""Promote a scratch what-if run into the durable research corpus (WS5).

What-if runs made against a scratch `HISTORY_DIR` (e.g. `/tmp/tradbot-*-<ts>`,
per AGENTS.md hard rule #2 -- any agent run must redirect history/ outside the
repo) are currently discarded when the scratch dir is cleaned up: there is no
promotion path into a durable corpus an analyzer could later mine across many
runs. This script copies the *whatif-only, sanitized* subset of a scratch
run's `recommendations.json` into `research_corpus/recommendations.json` at
the repo root.

Design:
  - Corpus dir defaults to `research_corpus/` at repo root (never committed --
    see the multi-user never-commit norm in AGENTS.md hard rule #3; this
    script adds a `research_corpus/` entry to .gitignore if one isn't already
    present, and the corpus is never touched by any commit this script makes
    -- it makes no commits at all).
  - REFUSES to promote any record with trading_mode == 'live'. This corpus is
    what-if research data only -- a live record here would be a data-honesty
    violation (AGENTS.md: "Simulated data must never be indistinguishable
    from real").
  - REFUSES the entire promotion (not just live records) if the scratch dir's
    executions.json (see executionledger.py's module docstring for the row
    shape: a flat list under the 'executions' key, each row carrying
    trading_mode on its INTENT row) contains any row with trading_mode ==
    'live'. A scratch dir should never legitimately contain a live ledger row
    (agents only ever run --trading-mode=whatif against scratch dirs per
    AGENTS.md hard rule #2), so finding one is treated as a sign the "scratch"
    dir is not actually scratch -- refuse the whole run rather than
    cherry-pick.
  - Dedupes by recommendation `id` (historyutil.create_recommendation_record's
    'rec_<ts>_<coin>' ids) -- re-running on the same scratch dir, or on
    overlapping scratch dirs, adds nothing new. Idempotent by construction:
    this script only ever appends new ids, never rewrites existing corpus
    records.
  - `--with-panel-logs` (default off) additionally copies the run's
    `panel_responses/*.log` files into `<corpus>/panel_responses/`, skipping
    any log whose filename already exists in the corpus (log filenames are
    `<run_id>.log`; run_id is unique per process invocation).
  - `--dry-run` computes and prints what WOULD happen without writing
    anything -- corpus untouched, scratch dir untouched, .gitignore untouched.
  - Never modifies the scratch dir (read-only) or the repo's real history/
    (never opened at all -- this script only ever touches the path passed as
    <scratch_history_dir> and the corpus dir).

Usage:
    ./venv/bin/python scripts/promote_research_run.py <scratch_history_dir> \\
        [--corpus-dir DIR] [--with-panel-logs] [--dry-run]

Example (matching AGENTS.md's scratch-run convention):
    HISTORY_DIR=/tmp/tradbot-scratch-20260720T120000Z ./venv/bin/python \\
        crypto_trading_bot.py --trading-mode=whatif --llm-mode=gemini --coins=BTC
    ./venv/bin/python scripts/promote_research_run.py \\
        /tmp/tradbot-scratch-20260720T120000Z --dry-run
"""
import argparse
import glob
import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS_DIR = REPO_ROOT / 'research_corpus'
GITIGNORE_PATH = REPO_ROOT / '.gitignore'
GITIGNORE_ENTRY = 'research_corpus/'


class PromotionError(Exception):
    """Raised for input problems that should abort the whole promotion."""


def _load_json(path: Path) -> Dict:
    with open(path, 'r') as f:
        return json.load(f)


def load_scratch_recommendations(scratch_dir: Path) -> List[Dict]:
    """Read <scratch_dir>/recommendations.json's 'recommendations' list.

    Raises PromotionError with a clear message for a missing scratch dir, a
    missing recommendations.json, or a malformed file -- this script never
    guesses at a partial/corrupt input, it refuses loudly (same fail-closed
    posture as executionledger.load_executions).
    """
    if not scratch_dir.is_dir():
        raise PromotionError(
            f"scratch history dir not found or not a directory: {scratch_dir}")
    rec_path = scratch_dir / 'recommendations.json'
    if not rec_path.exists():
        raise PromotionError(
            f"no recommendations.json in {scratch_dir} -- nothing to promote "
            "(did the run actually write any recommendations?)")
    try:
        data = _load_json(rec_path)
    except (json.JSONDecodeError, IOError, OSError, UnicodeDecodeError) as e:
        raise PromotionError(f"{rec_path} is unreadable/malformed: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get('recommendations'), list):
        raise PromotionError(
            f"{rec_path} has the wrong shape (expected an object with a "
            f"'recommendations' list, got {type(data).__name__})")
    return data['recommendations']


def scratch_has_live_execution_rows(scratch_dir: Path) -> bool:
    """True if <scratch_dir>/executions.json contains any row with
    trading_mode == 'live'. A missing or malformed executions.json is NOT an
    error here (many scratch runs never place an order and so never write a
    ledger at all) -- it's simply treated as "no live rows found". A
    malformed file is reported via a printed warning, not a crash, since the
    absence of a ledger is common and this check is a safety net on top of
    the per-record trading_mode check, not the primary gate.
    """
    ledger_path = scratch_dir / 'executions.json'
    if not ledger_path.exists():
        return False
    try:
        data = _load_json(ledger_path)
    except (json.JSONDecodeError, IOError, OSError, UnicodeDecodeError) as e:
        print(f"[PROMOTE] warning: could not read {ledger_path}: {e} "
              "(treating as no live rows found, but you should inspect it)")
        return False
    rows = data.get('executions') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        print(f"[PROMOTE] warning: {ledger_path} has an unexpected shape "
              "(treating as no live rows found, but you should inspect it)")
        return False
    return any(isinstance(row, dict) and row.get('trading_mode') == 'live'
               for row in rows)


def load_corpus_recommendations(corpus_dir: Path) -> List[Dict]:
    """Read <corpus>/recommendations.json, or [] if it doesn't exist yet."""
    rec_path = corpus_dir / 'recommendations.json'
    if not rec_path.exists():
        return []
    try:
        data = _load_json(rec_path)
    except (json.JSONDecodeError, IOError, OSError, UnicodeDecodeError) as e:
        raise PromotionError(
            f"corpus file {rec_path} exists but is unreadable/malformed: {e} "
            "-- refusing to promote on top of a corrupt corpus; fix or move "
            "it aside by hand first.") from e
    if not isinstance(data, dict) or not isinstance(data.get('recommendations'), list):
        raise PromotionError(
            f"corpus file {rec_path} has the wrong shape (expected an "
            f"object with a 'recommendations' list, got {type(data).__name__})")
    return data['recommendations']


def select_promotable(
    scratch_records: List[Dict],
    existing_corpus_ids: set,
) -> Tuple[List[Dict], List[Tuple[Dict, str]]]:
    """Split scratch records into (promotable, skipped).

    promotable: whatif-mode records whose id isn't already in the corpus.
    skipped: (record, reason) pairs for everything else -- live records,
        records with no trading_mode at all (pre-T2 / unknown -- refused,
        same as 'live' is refused: this corpus is whatif-only, and a record
        this script cannot positively confirm as whatif is never promoted),
        and duplicates already present in the corpus.
    """
    promotable = []
    skipped = []
    for rec in scratch_records:
        rec_id = rec.get('id')
        mode = rec.get('trading_mode')
        if mode == 'live':
            skipped.append((rec, f"trading_mode='live' (id={rec_id!r}) -- "
                                  "this corpus is whatif-only research data"))
            continue
        if mode != 'whatif':
            skipped.append((rec, f"trading_mode={mode!r} (id={rec_id!r}) -- "
                                  "only 'whatif' records are promoted"))
            continue
        if rec_id in existing_corpus_ids:
            skipped.append((rec, f"id={rec_id!r} already in corpus (dedup)"))
            continue
        promotable.append(rec)
    return promotable, skipped


def promote(
    scratch_dir: Path,
    corpus_dir: Path,
    with_panel_logs: bool = False,
    dry_run: bool = False,
) -> Dict:
    """Run the full promotion. Returns a result dict for programmatic use
    (tests, callers). Never modifies scratch_dir. Never writes anything when
    dry_run=True."""
    scratch_records = load_scratch_recommendations(scratch_dir)

    if scratch_has_live_execution_rows(scratch_dir):
        raise PromotionError(
            f"{scratch_dir}/executions.json contains one or more rows with "
            "trading_mode='live' -- refusing to promote ANY record from this "
            "run. A scratch HISTORY_DIR should never contain live ledger "
            "rows (AGENTS.md hard rule #2); this looks like it isn't "
            "actually a scratch dir. Inspect it by hand before retrying.")

    corpus_records = load_corpus_recommendations(corpus_dir)
    existing_ids = {r.get('id') for r in corpus_records}

    promotable, skipped = select_promotable(scratch_records, existing_ids)

    print(f"[PROMOTE] scratch dir: {scratch_dir}")
    print(f"[PROMOTE] corpus dir:  {corpus_dir}")
    print(f"[PROMOTE] scratch records: {len(scratch_records)} total, "
          f"{len(promotable)} promotable, {len(skipped)} skipped")
    for rec, reason in skipped:
        print(f"  SKIP {rec.get('id')!r}: {reason}")

    result = {
        'promoted': len(promotable),
        'skipped': len(skipped),
        'skipped_details': skipped,
        'panel_logs_copied': 0,
        'gitignore_updated': False,
    }

    gitignore_needs_entry = _gitignore_missing_entry()
    if gitignore_needs_entry:
        print(f"[PROMOTE] .gitignore is missing {GITIGNORE_ENTRY!r} "
              f"{'(would add' if dry_run else '-- adding'})")

    if dry_run:
        print("[PROMOTE] --dry-run: not writing anything.")
        if with_panel_logs:
            to_copy = _panel_logs_to_copy(scratch_dir, corpus_dir)
            print(f"[PROMOTE] --dry-run: would copy {len(to_copy)} panel log(s)")
            result['panel_logs_copied'] = len(to_copy)
        result['gitignore_updated'] = False
        return result

    if gitignore_needs_entry:
        _add_gitignore_entry()
        result['gitignore_updated'] = True

    if promotable:
        corpus_dir.mkdir(parents=True, exist_ok=True)
        new_corpus_records = corpus_records + promotable
        rec_path = corpus_dir / 'recommendations.json'
        tmp = corpus_dir / f'.recommendations.{os.getpid()}.tmp'
        with open(tmp, 'w') as f:
            json.dump({'recommendations': new_corpus_records}, f, indent=2)
        os.replace(tmp, rec_path)
        print(f"[PROMOTE] wrote {len(new_corpus_records)} total records to {rec_path} "
              f"({len(promotable)} newly promoted)")
    else:
        print("[PROMOTE] nothing new to promote (idempotent no-op).")

    if with_panel_logs:
        result['panel_logs_copied'] = _copy_panel_logs(scratch_dir, corpus_dir)

    return result


def _gitignore_missing_entry() -> bool:
    if not GITIGNORE_PATH.exists():
        return True
    text = GITIGNORE_PATH.read_text()
    lines = {ln.strip() for ln in text.splitlines()}
    return GITIGNORE_ENTRY not in lines and GITIGNORE_ENTRY.rstrip('/') not in lines


def _add_gitignore_entry():
    text = GITIGNORE_PATH.read_text() if GITIGNORE_PATH.exists() else ''
    if text and not text.endswith('\n'):
        text += '\n'
    text += (
        "\n# WS5: research_corpus/ holds promoted what-if run data (never "
        "committed -- see scripts/promote_research_run.py)\n"
        f"{GITIGNORE_ENTRY}\n"
    )
    GITIGNORE_PATH.write_text(text)


def _panel_logs_to_copy(scratch_dir: Path, corpus_dir: Path) -> List[Path]:
    src_dir = scratch_dir / 'panel_responses'
    if not src_dir.is_dir():
        return []
    dest_dir = corpus_dir / 'panel_responses'
    to_copy = []
    for src in sorted(Path(p) for p in glob.glob(str(src_dir / '*.log'))):
        dest = dest_dir / src.name
        if not dest.exists():
            to_copy.append(src)
    return to_copy


def _copy_panel_logs(scratch_dir: Path, corpus_dir: Path) -> int:
    to_copy = _panel_logs_to_copy(scratch_dir, corpus_dir)
    if not to_copy:
        return 0
    dest_dir = corpus_dir / 'panel_responses'
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in to_copy:
        shutil.copy2(src, dest_dir / src.name)
        print(f"[PROMOTE] copied panel log {src.name}")
    return len(to_copy)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Promote a scratch what-if run into the durable, '
                     'never-committed research_corpus/ (WS5).'
    )
    parser.add_argument(
        'scratch_history_dir',
        help='Path to the scratch HISTORY_DIR used for the run (e.g. '
             '/tmp/tradbot-scratch-<ts>)'
    )
    parser.add_argument(
        '--corpus-dir', default=str(DEFAULT_CORPUS_DIR),
        help='Destination corpus directory (default: research_corpus/ at '
             'repo root)'
    )
    parser.add_argument(
        '--with-panel-logs', action='store_true',
        help='Also copy panel_responses/*.log files into '
             '<corpus>/panel_responses/ (default: off)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Compute and print what would happen without writing anything'
    )
    args = parser.parse_args(argv)

    try:
        promote(
            Path(args.scratch_history_dir),
            Path(args.corpus_dir),
            with_panel_logs=args.with_panel_logs,
            dry_run=args.dry_run,
        )
    except PromotionError as e:
        parser.error(str(e))


if __name__ == '__main__':
    main()
