#!/usr/bin/env python3
"""Experiment runner (WS8): compare panel/config variants safely and reproducibly.

Motivation (owner session): a recent session ran 5 concurrent LIVE bot
invocations to compare panels -- operationally unsafe (each `--live` process
is its own money path), rate-limit-amplifying (5x the LLM/exchange calls at
once), and incomparable (each run saw different market data, since nothing
pinned the data snapshot across the 5 processes). This script is the safe
replacement: variants run ONE AT A TIME (never concurrently), are always
forced into `--trading-mode=whatif`, and each variant's exact market-data
snapshot is captured (via the existing market_blocks/<run_id>.json sidecar
and each record's market_block_hash) so the manifest can say, precisely,
whether two variants' decisions are even comparable -- i.e. whether they saw
the same data -- rather than silently assuming it.

Input: an experiment spec JSON file (path given as argv[1]):
    {
      "name": "<experiment name>",
      "base_flags": ["--llm-mode=compare", "--coins=BTC,ETH", ...],
      "variants": [
        {"name": "variant_a", "flags": ["--primary-llm=gemini"]},
        {"name": "variant_b", "flags": ["--primary-llm=claude"]}
      ],
      "output_dir": "/some/scratch/dir/outside/the/repo"
    }

Refusals (hard error, non-zero exit, BEFORE any subprocess is started):
  - spec missing any of the required top-level keys, or a variant missing
    'name'/'flags'.
  - ANY flag (in base_flags or any variant's flags) requests live trading,
    in any recognized form: `--live`, `--trading-mode=live`,
    `--trading-mode live` (as two separate tokens), or the literal substring
    "trading-mode live"/"trading_mode=live" embedded in one flag string.
  - `output_dir` resolves inside this repo's real `history/` (per-user data
    must never be touched by an experiment run -- AGENTS.md hard rule #2/#3).

Safety invariants for every subprocess this script starts:
  - `--trading-mode=whatif --quiet --json-summary` are appended EXPLICITLY by
    this script (never trusted from the spec -- appended last, so they win
    over anything conflicting earlier in the effective flag list, since
    argparse's non-append single-value options take the LAST occurrence).
  - `--allow-concurrent` is stripped from the effective flags if present in
    the spec: this runner never passes it, and never needs to -- variants run
    strictly sequentially, each against its own scratch HISTORY_DIR, so there
    is never a concurrent whatif process to allow.
  - Each variant gets its own fresh `HISTORY_DIR=<output_dir>/runs/<variant>/`
    (removed and recreated before the run) so variants can never contaminate
    each other's history/ledger/market-block files.
  - Variants run ONE AT A TIME via subprocess (`./venv/bin/python
    crypto_trading_bot.py ...`), never in parallel.

Non-goals: no statistics, no parallelism, no replay-from-sidecar, no LLM
calls of its own (every LLM call happens inside the bot subprocess it spawns).

Usage:
    ./venv/bin/python scripts/run_experiment.py <spec.json>
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_BIN = REPO_ROOT / 'venv' / 'bin' / 'python'
BOT_SCRIPT = REPO_ROOT / 'crypto_trading_bot.py'
REAL_HISTORY_DIR = (REPO_ROOT / 'history').resolve()

sys.path.insert(0, str(REPO_ROOT))
import historyutil  # noqa: E402  (reused for market_block_hash -- see module docstring)

REQUIRED_SPEC_KEYS = ('name', 'base_flags', 'variants', 'output_dir')

# Appended AFTER the spec's flags on every subprocess invocation, so they win
# (argparse: repeated non-append single-value options resolve to the LAST
# occurrence). Never trusted from the spec -- always these exact strings.
FORCED_FLAGS = ['--trading-mode=whatif', '--quiet', '--json-summary']

# Matches `--live` as a whole token (not a prefix of some other flag).
_LIVE_FLAG_RE = re.compile(r'(?:^|\s)--live(?:[=\s]|$)', re.IGNORECASE)
# Matches --trading-mode=live / --trading-mode live / trading_mode=live, with
# either '-' or '_' as the word separator and '=' or whitespace before 'live'.
_LIVE_MODE_RE = re.compile(r'trading[-_]mode[=\s]+live\b', re.IGNORECASE)


class ExperimentError(Exception):
    """Raised for spec/input problems that abort the whole experiment before
    any subprocess is started."""


# ----------------------------------------------------------------------------
# Spec loading + refusals
# ----------------------------------------------------------------------------

def load_spec(spec_path):
    path = Path(spec_path)
    if not path.is_file():
        raise ExperimentError(f"spec file not found: {path}")
    try:
        with open(path, 'r') as f:
            spec = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ExperimentError(f"could not read/parse spec file {path}: {e}") from e
    if not isinstance(spec, dict):
        raise ExperimentError(
            f"spec file {path} must contain a JSON object, got "
            f"{type(spec).__name__}")
    return spec


def validate_spec(spec):
    """Shape validation only (missing-keys refusal). Raises ExperimentError."""
    missing = [k for k in REQUIRED_SPEC_KEYS if k not in spec]
    if missing:
        raise ExperimentError(
            f"experiment spec missing required key(s): {missing}")
    if not isinstance(spec['base_flags'], list):
        raise ExperimentError("spec 'base_flags' must be a list")
    if not isinstance(spec['variants'], list) or not spec['variants']:
        raise ExperimentError("spec 'variants' must be a non-empty list")
    for i, variant in enumerate(spec['variants']):
        if not isinstance(variant, dict) or 'name' not in variant or 'flags' not in variant:
            raise ExperimentError(
                f"variants[{i}] must be an object with 'name' and 'flags', "
                f"got {variant!r}")
        if not isinstance(variant['flags'], list):
            raise ExperimentError(f"variants[{i}]['flags'] must be a list")
    if not isinstance(spec['output_dir'], str) or not spec['output_dir']:
        raise ExperimentError("spec 'output_dir' must be a non-empty string")


def flags_request_live(flags):
    """True iff `flags` (a list of CLI tokens) requests live trading in any
    recognized form -- see module docstring for the exact list. Joining the
    tokens with spaces before matching means a live request split across two
    separate list entries (['--trading-mode', 'live']) is caught exactly the
    same as one joined string ('--trading-mode=live')."""
    joined = ' '.join(str(f) for f in flags)
    return bool(_LIVE_FLAG_RE.search(joined) or _LIVE_MODE_RE.search(joined))


def refuse_if_live(spec):
    checks = [('base_flags', spec.get('base_flags') or [])]
    for variant in spec['variants']:
        checks.append((f"variant {variant.get('name')!r}", variant.get('flags') or []))
    for label, flags in checks:
        if flags_request_live(flags):
            raise ExperimentError(
                f"{label} requests live trading -- refusing to run ANY "
                "variant. This runner is whatif-only (see module docstring); "
                "remove --live / --trading-mode=live and rerun.")


def refuse_if_output_dir_unsafe(output_dir):
    candidate = Path(output_dir).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve()
    if candidate == REAL_HISTORY_DIR or REAL_HISTORY_DIR in candidate.parents:
        raise ExperimentError(
            f"output_dir ({candidate}) is inside the repo's real history/ "
            f"({REAL_HISTORY_DIR}) -- experiments must never write into "
            "per-user history data (AGENTS.md hard rule #2/#3). Pick a "
            "scratch directory outside the repo.")


def validate_and_refuse(spec):
    """Full pre-flight: shape validation, then both refusal checks. Raises
    ExperimentError on any problem, BEFORE any subprocess runs."""
    validate_spec(spec)
    refuse_if_live(spec)
    refuse_if_output_dir_unsafe(spec['output_dir'])


# ----------------------------------------------------------------------------
# Subprocess boundary (tests monkeypatch this single function)
# ----------------------------------------------------------------------------

def _run_bot(cmd, env):
    """Run one bot invocation. Returns an object with .returncode and
    .stdout (subprocess.CompletedProcess satisfies this). This is the ONLY
    function that starts a subprocess -- tests replace it with a fake that
    writes plausible run-summary/market-block fixtures instead of actually
    invoking crypto_trading_bot.py, so the test suite never spawns a real
    process or makes network/LLM calls."""
    return subprocess.run(
        cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)


# ----------------------------------------------------------------------------
# Per-variant execution
# ----------------------------------------------------------------------------

def _sanitize_name(name):
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(name))
    return safe or 'variant'


def _fresh_dir(path):
    """Remove `path` if it exists, then (re)create it empty."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def build_effective_flags(base_flags, variant_flags):
    """base_flags + variant_flags, with any spec-supplied --allow-concurrent
    stripped (never passed -- see module docstring), then FORCED_FLAGS
    appended last so they always win."""
    flags = [str(f) for f in list(base_flags) + list(variant_flags)]
    flags = [f for f in flags if f.strip().lower() != '--allow-concurrent']
    return flags + list(FORCED_FLAGS)


def _subprocess_env(history_dir):
    env = dict(os.environ)
    env['HISTORY_DIR'] = str(history_dir)
    # Defensive belt-and-suspenders on top of refuse_if_live: even though no
    # --live flag ever reaches the subprocess, never let an inherited
    # live-arming var leak through either (AGENTS.md hard rule #1).
    env.pop('LIVE_TRADING_CONFIRMED', None)
    env['TRADING_MODE'] = 'whatif'
    return env


def _write_print_config(path, result):
    """Write the --print-config probe's stdout to `path`. The real bot always
    emits pretty-printed JSON here (see emit_config_report_and_exit); if a
    fake or a broken run emits something else, fall back to writing the raw
    text rather than losing it."""
    stdout = getattr(result, 'stdout', '') or ''
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        print(f"[EXPERIMENT WARN] --print-config output for {path} was not "
              "valid JSON; writing raw stdout instead")
        path.write_text(stdout)
        return
    path.write_text(json.dumps(parsed, indent=2))


def _collect_run_summary(history_dir):
    """Find and load the run summary this variant's run wrote under
    <history_dir>/run_summaries/ (WS8's --json-summary default path -- see
    crypto_trading_bot.resolve_json_summary_path). Returns
    (run_id, summary_dict_or_None, path_or_None). Missing/unreadable is not
    fatal -- a failed run may never have written one."""
    run_summaries_dir = history_dir / 'run_summaries'
    if not run_summaries_dir.is_dir():
        return None, None, None
    files = sorted(run_summaries_dir.glob('*.json'))
    if not files:
        return None, None, None
    if len(files) > 1:
        print(f"[EXPERIMENT WARN] multiple run summaries in "
              f"{run_summaries_dir}; using the most recently modified")
        files.sort(key=lambda p: p.stat().st_mtime)
    path = files[-1]
    try:
        summary = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[EXPERIMENT WARN] could not read run summary {path}: {e}")
        return None, None, path
    run_id = summary.get('run_id') or path.stem
    return run_id, summary, path


def _load_market_blocks(history_dir, run_id):
    """Load <history_dir>/market_blocks/<run_id>.json (the {coin: block_text}
    sidecar) or {} if missing/unreadable/no run_id."""
    if not run_id:
        return {}
    path = history_dir / 'market_blocks' / f'{run_id}.json'
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_recommendations(history_dir):
    """Load <history_dir>/recommendations.json's 'recommendations' list, or
    [] if missing/malformed."""
    rec_path = history_dir / 'recommendations.json'
    if not rec_path.exists():
        return []
    try:
        data = json.loads(rec_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    records = data.get('recommendations') if isinstance(data, dict) else None
    return records if isinstance(records, list) else []


def _collect_variant_data(history_dir, market_blocks):
    """Per-coin (outcome, market_block_hash) from this variant's records,
    with a last-record-wins policy per coin (mirrors the corpus scripts'
    dedupe convention). Cross-checks each record's stored market_block_hash
    against a fresh recompute from the sidecar block text (via
    historyutil.market_block_hash, the SAME hash function write_market_blocks
    uses) and warns loudly on any mismatch -- drift is reported, never
    papered over."""
    outcomes = {}
    hashes = {}
    for rec in _load_recommendations(history_dir):
        if not isinstance(rec, dict):
            continue
        coin = rec.get('coin_symbol')
        if coin is None:
            continue
        outcomes[coin] = rec.get('recommendation')
        hashes[coin] = rec.get('market_block_hash')
        sidecar_text = market_blocks.get(coin)
        if sidecar_text is not None:
            recomputed = historyutil.market_block_hash(sidecar_text)
            stored = hashes[coin]
            if stored is not None and recomputed is not None and recomputed != stored:
                print(f"[EXPERIMENT WARN] {coin}: record market_block_hash "
                      f"{stored!r} does not match the recomputed hash of "
                      f"its market_blocks sidecar entry {recomputed!r}")
    return outcomes, hashes


def _apply_summary_outcomes(summary, outcomes):
    """Prefer the run summary's per-coin 'outcome' (WS8's vote-outcome label,
    e.g. 'BUY->ordered') over the raw recommendation string when a summary is
    available -- it's the richer, more decision-accurate label. Falls back to
    whatever _collect_variant_data already derived from recommendations.json
    when no summary was written."""
    if not summary:
        return outcomes
    merged = dict(outcomes)
    for entry in summary.get('coins', []):
        if isinstance(entry, dict) and entry.get('coin') is not None:
            merged[entry['coin']] = entry.get('outcome')
    return merged


def run_variant(base_flags, variant, output_dir):
    name = variant['name']
    history_dir = output_dir / 'runs' / _sanitize_name(name)
    _fresh_dir(history_dir)
    effective_flags = build_effective_flags(base_flags, variant.get('flags') or [])
    env = _subprocess_env(history_dir)
    cmd_prefix = [str(PYTHON_BIN), str(BOT_SCRIPT)]

    print(f"[EXPERIMENT] variant {name!r}: capturing --print-config")
    print_config_path = history_dir / 'print_config.json'
    pc_result = _run_bot(cmd_prefix + effective_flags + ['--print-config'], env)
    _write_print_config(print_config_path, pc_result)

    print(f"[EXPERIMENT] variant {name!r}: running "
          f"(HISTORY_DIR={history_dir})")
    run_result = _run_bot(cmd_prefix + effective_flags, env)

    run_id, summary, summary_path = _collect_run_summary(history_dir)
    market_blocks = _load_market_blocks(history_dir, run_id)
    outcomes, hashes = _collect_variant_data(history_dir, market_blocks)
    outcomes = _apply_summary_outcomes(summary, outcomes)

    return {
        'name': name,
        'flags': effective_flags,
        'exit_code': run_result.returncode,
        'history_dir': str(history_dir),
        'print_config_path': str(print_config_path),
        'run_id': run_id,
        'summary_path': str(summary_path) if summary_path else None,
        'outcomes': outcomes,
        'hashes': hashes,
    }


# ----------------------------------------------------------------------------
# Comparison + manifest
# ----------------------------------------------------------------------------

def build_comparison(variant_results):
    """Per-coin decision matrix: outcome per variant, plus a `comparable`
    boolean that is true iff every variant's market_block_hash for that coin
    is present AND identical. A coin a variant never analyzed at all
    contributes a None hash for that variant, which correctly makes
    `comparable` False -- differing coverage IS a form of "not directly
    comparable", surfaced rather than hidden. When not comparable, the full
    hash-per-variant map is included under 'differing_hashes' so the drift is
    visible verbatim, never papered over."""
    all_coins = set()
    for vr in variant_results:
        all_coins.update(vr['outcomes'].keys())
        all_coins.update(vr['hashes'].keys())

    coins_section = {}
    for coin in sorted(all_coins):
        outcomes = {vr['name']: vr['outcomes'].get(coin) for vr in variant_results}
        hashes = {vr['name']: vr['hashes'].get(coin) for vr in variant_results}
        distinct = set(hashes.values())
        comparable = len(distinct) == 1 and None not in distinct
        entry = {
            'outcomes': outcomes,
            'market_block_hashes': hashes,
            'comparable': comparable,
        }
        if not comparable:
            entry['differing_hashes'] = hashes
        coins_section[coin] = entry
    return {'coins': coins_section}


def build_manifest(spec, output_dir, variant_results):
    manifest_path = output_dir / 'manifest.json'
    return {
        'experiment': spec['name'],
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'output_dir': str(output_dir),
        'manifest_path': str(manifest_path),
        'variants': [
            {
                'name': vr['name'],
                'flags': vr['flags'],
                'exit_code': vr['exit_code'],
                'run_id': vr['run_id'],
                'history_dir': vr['history_dir'],
                'print_config_path': vr['print_config_path'],
                'summary_path': vr['summary_path'],
            }
            for vr in variant_results
        ],
        'comparison': build_comparison(variant_results),
    }


def run_experiment(spec):
    """Full experiment run: validated spec in, written manifest.json (and its
    dict) out. Runs every variant SEQUENTIALLY (never in parallel -- see
    module docstring)."""
    output_dir = Path(spec['output_dir']).expanduser()
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    base_flags = spec.get('base_flags') or []
    variant_results = [
        run_variant(base_flags, variant, output_dir)
        for variant in spec['variants']
    ]

    manifest = build_manifest(spec, output_dir, variant_results)
    manifest_path = Path(manifest['manifest_path'])
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    return manifest


# ----------------------------------------------------------------------------
# Human-readable stdout report
# ----------------------------------------------------------------------------

def print_comparison_table(manifest):
    variants = manifest['variants']
    names = [v['name'] for v in variants]
    coins = manifest['comparison']['coins']

    print()
    print(f"Experiment: {manifest['experiment']}")
    print(f"Output dir: {manifest['output_dir']}")
    print()
    col_width = max(12, *(len(n) + 2 for n in names)) if names else 12
    header = "COIN".ljust(10) + ''.join(n.ljust(col_width) for n in names) + "COMPARABLE"
    print(header)
    print('-' * len(header))
    for coin in sorted(coins):
        entry = coins[coin]
        row = coin.ljust(10)
        for name in names:
            row += str(entry['outcomes'].get(name) or '-').ljust(col_width)
        row += 'yes' if entry['comparable'] else 'NO (drift/coverage differs)'
        print(row)

    drifted = sorted(c for c, e in coins.items() if not e['comparable'])
    if drifted:
        print()
        print("Market-block drift / coverage gaps detected:")
        for c in drifted:
            print(f"  {c}: {coins[c]['market_block_hashes']}")

    print()
    for v in variants:
        print(f"[{v['name']}] exit_code={v['exit_code']} run_id={v['run_id']} "
              f"summary={v['summary_path']}")
    print()
    print(f"Manifest written to {manifest['manifest_path']}")


# ----------------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------------

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("Usage: run_experiment.py <spec.json>", file=sys.stderr)
        return 1

    try:
        spec = load_spec(argv[0])
        validate_and_refuse(spec)
    except ExperimentError as e:
        print(f"[REFUSING TO RUN] {e}", file=sys.stderr)
        return 1

    manifest = run_experiment(spec)
    print_comparison_table(manifest)
    return 0


if __name__ == '__main__':
    sys.exit(main())
