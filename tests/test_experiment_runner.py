"""Tests for scripts/run_experiment.py (WS8): the safe, reproducible
panel/config comparison runner.

Motivation (see the script's module docstring): a session once ran 5
concurrent LIVE bot invocations to compare panels -- unsafe and
incomparable. These tests never invoke a real subprocess: `run_experiment
._run_bot` is the injected subprocess boundary, monkeypatched to a fake that
records invocation order and writes plausible run-summary/market-block
fixtures directly, mirroring what a real `crypto_trading_bot.py` run under
`--json-summary` would leave behind. No network, no LLM calls, no real
process spawned.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
# scripts/ isn't a package; add it explicitly so `import run_experiment` resolves.
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import run_experiment as exp  # noqa: E402


# ----------------------------------------------------------------------------
# Fake subprocess boundary
# ----------------------------------------------------------------------------

class FakeResult:
    def __init__(self, returncode=0, stdout=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ''


class FakeBot:
    """Records every _run_bot invocation (cmd, env) in call order, and writes
    plausible fixtures for real (non --print-config) runs.

    `variant_fixtures` maps variant-name -> list of coin dicts:
        {'coin': 'BTC', 'outcome': 'HOLD', 'block_text': '...',
         'hash_override': None, 'exit_code': 0}
    `hash_override`, when set, is written as the record's market_block_hash
    INSTEAD of the hash actually computed from block_text -- this is how
    tests manufacture a stored-hash/sidecar mismatch or cross-variant drift
    without needing two different block texts.
    """

    def __init__(self, variant_fixtures, print_config_json=None):
        self.variant_fixtures = variant_fixtures
        self.print_config_json = print_config_json if print_config_json is not None else {'settings': {}}
        self.calls = []  # list of (cmd, env) in invocation order

    def _variant_name_from_history_dir(self, history_dir):
        # HISTORY_DIR is always <output_dir>/runs/<sanitized-variant-name>/
        return Path(history_dir).name

    def __call__(self, cmd, env):
        self.calls.append((list(cmd), dict(env)))
        if '--print-config' in cmd:
            return FakeResult(returncode=0, stdout=json.dumps(self.print_config_json))

        history_dir = Path(env['HISTORY_DIR'])
        history_dir.mkdir(parents=True, exist_ok=True)
        variant_name = self._variant_name_from_history_dir(history_dir)
        coins = self.variant_fixtures.get(variant_name, [])
        run_id = f'run_fake_{variant_name}'

        # market_blocks/<run_id>.json sidecar
        blocks = {c['coin']: c['block_text'] for c in coins if c.get('block_text') is not None}
        if blocks:
            mb_dir = history_dir / 'market_blocks'
            mb_dir.mkdir(parents=True, exist_ok=True)
            (mb_dir / f'{run_id}.json').write_text(json.dumps(blocks))

        # recommendations.json
        records = []
        for c in coins:
            block_text = c.get('block_text')
            if 'hash_override' in c and c['hash_override'] is not None:
                mb_hash = c['hash_override']
            elif block_text is not None:
                mb_hash = exp.historyutil.market_block_hash(block_text)
            else:
                mb_hash = None
            records.append({
                'id': f"rec_{run_id}_{c['coin']}",
                'coin_symbol': c['coin'],
                'recommendation': c['outcome'],
                'trading_mode': 'whatif',
                'run_id': run_id,
                'market_block_hash': mb_hash,
            })
        (history_dir / 'recommendations.json').write_text(
            json.dumps({'recommendations': records}))

        # run_summaries/<run_id>.json
        summary = {
            'run_id': run_id,
            'trading_mode': 'whatif',
            'coins': [{'coin': c['coin'], 'outcome': c['outcome'],
                       'bought': False, 'excluded': False} for c in coins],
        }
        rs_dir = history_dir / 'run_summaries'
        rs_dir.mkdir(parents=True, exist_ok=True)
        (rs_dir / f'{run_id}.json').write_text(json.dumps(summary))

        exit_code = self.variant_fixtures.get(f'{variant_name}__exit_code', 0)
        return FakeResult(returncode=exit_code, stdout='')


def make_spec(output_dir, variants, base_flags=None, name='exp1'):
    return {
        'name': name,
        'base_flags': base_flags if base_flags is not None else ['--llm-mode=compare'],
        'variants': variants,
        'output_dir': str(output_dir),
    }


# ============================================================================
# Refusals (no subprocess boundary needed -- these must fail before any run)
# ============================================================================

class TestLiveRefusal:
    @pytest.mark.parametrize('live_flags', [
        ['--live'],
        ['--trading-mode=live'],
        ['--trading-mode', 'live'],
        ['--coins=BTC', '--trading-mode=live'],
        ['some --trading_mode=live embedded'],
    ])
    def test_base_flags_live_refused(self, tmp_path, live_flags):
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}],
                          base_flags=live_flags)
        with pytest.raises(exp.ExperimentError, match='live'):
            exp.validate_and_refuse(spec)

    @pytest.mark.parametrize('live_flags', [
        ['--live'],
        ['--trading-mode=live'],
        ['--trading-mode', 'live'],
    ])
    def test_variant_flags_live_refused(self, tmp_path, live_flags):
        spec = make_spec(tmp_path / 'out', variants=[
            {'name': 'a', 'flags': []},
            {'name': 'b', 'flags': live_flags},
        ])
        with pytest.raises(exp.ExperimentError, match='live'):
            exp.validate_and_refuse(spec)

    def test_no_run_bot_call_on_live_refusal(self, tmp_path, monkeypatch):
        fake = FakeBot({})
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': ['--live']}])
        with pytest.raises(exp.ExperimentError):
            exp.validate_and_refuse(spec)
        assert fake.calls == []

    def test_whatif_flags_not_refused(self):
        assert exp.flags_request_live(['--trading-mode=whatif', '--quiet']) is False
        assert exp.flags_request_live(['--coins=BTC,ETH']) is False


class TestOutputDirRefusal:
    def test_inside_repo_history_refused(self):
        spec = make_spec(exp.REPO_ROOT / 'history' / 'scratch',
                          variants=[{'name': 'a', 'flags': []}])
        with pytest.raises(exp.ExperimentError, match='history'):
            exp.validate_and_refuse(spec)

    def test_repo_history_dir_itself_refused(self):
        spec = make_spec(exp.REPO_ROOT / 'history',
                          variants=[{'name': 'a', 'flags': []}])
        with pytest.raises(exp.ExperimentError, match='history'):
            exp.validate_and_refuse(spec)

    def test_outside_repo_ok(self, tmp_path):
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}])
        exp.validate_and_refuse(spec)  # should not raise


class TestMissingKeysRefusal:
    @pytest.mark.parametrize('drop_key', ['name', 'base_flags', 'variants', 'output_dir'])
    def test_missing_required_key(self, tmp_path, drop_key):
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}])
        del spec[drop_key]
        with pytest.raises(exp.ExperimentError, match='missing'):
            exp.validate_and_refuse(spec)

    def test_variant_missing_name(self, tmp_path):
        spec = make_spec(tmp_path / 'out', variants=[{'flags': []}])
        with pytest.raises(exp.ExperimentError):
            exp.validate_and_refuse(spec)

    def test_variant_missing_flags(self, tmp_path):
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a'}])
        with pytest.raises(exp.ExperimentError):
            exp.validate_and_refuse(spec)

    def test_empty_variants_refused(self, tmp_path):
        spec = make_spec(tmp_path / 'out', variants=[])
        with pytest.raises(exp.ExperimentError, match='variants'):
            exp.validate_and_refuse(spec)


# ============================================================================
# Forced flags / --allow-concurrent stripping
# ============================================================================

class TestEffectiveFlags:
    def test_forced_flags_appended(self):
        flags = exp.build_effective_flags(['--coins=BTC'], ['--primary-llm=gemini'])
        assert flags[:2] == ['--coins=BTC', '--primary-llm=gemini']
        assert flags[-3:] == ['--trading-mode=whatif', '--quiet', '--json-summary']

    def test_forced_flags_win_over_spec_supplied_trading_mode(self):
        # Even if a variant tried to sneak in a (non-live) trading-mode flag,
        # the forced flag comes last and argparse's last-wins semantics apply.
        flags = exp.build_effective_flags(['--trading-mode=whatif'], [])
        assert flags.count('--trading-mode=whatif') == 2
        assert flags[-3:] == ['--trading-mode=whatif', '--quiet', '--json-summary']

    def test_allow_concurrent_stripped(self):
        flags = exp.build_effective_flags(['--allow-concurrent', '--coins=BTC'], [])
        assert '--allow-concurrent' not in flags

    def test_allow_concurrent_stripped_from_variant_flags_too(self):
        flags = exp.build_effective_flags([], ['--allow-concurrent'])
        assert '--allow-concurrent' not in flags


# ============================================================================
# Sequentiality + HISTORY_DIR per variant
# ============================================================================

class TestSequentialExecution:
    def test_runs_sequentially_in_variant_order(self, tmp_path, monkeypatch):
        fake = FakeBot({
            'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'blockA'}],
            'b': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'blockA'}],
            'c': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'blockA'}],
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[
            {'name': 'a', 'flags': []},
            {'name': 'b', 'flags': []},
            {'name': 'c', 'flags': []},
        ])
        exp.validate_and_refuse(spec)
        exp.run_experiment(spec)

        # Two calls per variant (print-config probe, then the real run), in
        # strict variant order -- never interleaved, never parallel.
        assert len(fake.calls) == 6
        history_dirs_in_order = [Path(env['HISTORY_DIR']).name for _, env in fake.calls]
        assert history_dirs_in_order == ['a', 'a', 'b', 'b', 'c', 'c']
        # print-config call precedes the real run within each variant.
        assert '--print-config' in fake.calls[0][0]
        assert '--print-config' not in fake.calls[1][0]

    def test_history_dir_per_variant(self, tmp_path, monkeypatch):
        fake = FakeBot({
            'variant_one': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'x'}],
            'variant_two': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'x'}],
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        out = tmp_path / 'out'
        spec = make_spec(out, variants=[
            {'name': 'variant_one', 'flags': []},
            {'name': 'variant_two', 'flags': []},
        ])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)

        history_dirs = {v['name']: v['history_dir'] for v in manifest['variants']}
        assert history_dirs['variant_one'] == str((out.resolve() / 'runs' / 'variant_one'))
        assert history_dirs['variant_two'] == str((out.resolve() / 'runs' / 'variant_two'))
        assert history_dirs['variant_one'] != history_dirs['variant_two']

    def test_never_passes_allow_concurrent_to_run_bot(self, tmp_path, monkeypatch):
        fake = FakeBot({'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'x'}]})
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[
            {'name': 'a', 'flags': ['--allow-concurrent']},
        ])
        exp.validate_and_refuse(spec)
        exp.run_experiment(spec)
        for cmd, _env in fake.calls:
            assert '--allow-concurrent' not in cmd

    def test_forced_flags_present_in_every_run_bot_call(self, tmp_path, monkeypatch):
        fake = FakeBot({'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'x'}]})
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}])
        exp.validate_and_refuse(spec)
        exp.run_experiment(spec)
        for cmd, _env in fake.calls:
            assert '--trading-mode=whatif' in cmd
            assert '--quiet' in cmd
            assert '--json-summary' in cmd


# ============================================================================
# Manifest shape
# ============================================================================

class TestManifestShape:
    def test_manifest_top_level_fields(self, tmp_path, monkeypatch):
        fake = FakeBot({
            'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'x'}],
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}], name='my_exp')
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)

        assert manifest['experiment'] == 'my_exp'
        assert 'generated_at' in manifest
        assert 'variants' in manifest and 'comparison' in manifest
        v = manifest['variants'][0]
        for key in ('name', 'flags', 'exit_code', 'run_id', 'summary_path'):
            assert key in v
        assert v['name'] == 'a'
        assert v['exit_code'] == 0
        assert v['run_id'] == 'run_fake_a'

    def test_manifest_written_to_disk(self, tmp_path, monkeypatch):
        fake = FakeBot({'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'x'}]})
        monkeypatch.setattr(exp, '_run_bot', fake)
        out = tmp_path / 'out'
        spec = make_spec(out, variants=[{'name': 'a', 'flags': []}])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)

        manifest_path = Path(manifest['manifest_path'])
        assert manifest_path.exists()
        on_disk = json.loads(manifest_path.read_text())
        assert on_disk['experiment'] == manifest['experiment']

    def test_exit_code_recorded(self, tmp_path, monkeypatch):
        fake = FakeBot({
            'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'x'}],
            'a__exit_code': 1,
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)
        assert manifest['variants'][0]['exit_code'] == 1


# ============================================================================
# Comparability + drift surfacing
# ============================================================================

class TestComparability:
    def test_comparable_true_when_hashes_match(self, tmp_path, monkeypatch):
        fake = FakeBot({
            'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'identical-block'}],
            'b': [{'coin': 'BTC', 'outcome': 'BUY', 'block_text': 'identical-block'}],
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[
            {'name': 'a', 'flags': []}, {'name': 'b', 'flags': []},
        ])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)

        btc = manifest['comparison']['coins']['BTC']
        assert btc['comparable'] is True
        assert btc['outcomes'] == {'a': 'HOLD', 'b': 'BUY'}
        assert 'differing_hashes' not in btc

    def test_comparable_false_when_hashes_differ(self, tmp_path, monkeypatch):
        fake = FakeBot({
            'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'block-version-1'}],
            'b': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'block-version-2'}],
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[
            {'name': 'a', 'flags': []}, {'name': 'b', 'flags': []},
        ])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)

        btc = manifest['comparison']['coins']['BTC']
        assert btc['comparable'] is False
        assert 'differing_hashes' in btc
        assert btc['differing_hashes']['a'] != btc['differing_hashes']['b']
        assert btc['differing_hashes']['a'] is not None
        assert btc['differing_hashes']['b'] is not None

    def test_comparable_false_when_coin_missing_from_one_variant(self, tmp_path, monkeypatch):
        fake = FakeBot({
            'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'blockA'}],
            'b': [{'coin': 'ETH', 'outcome': 'HOLD', 'block_text': 'blockB'}],
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[
            {'name': 'a', 'flags': []}, {'name': 'b', 'flags': []},
        ])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)

        btc = manifest['comparison']['coins']['BTC']
        assert btc['comparable'] is False
        assert btc['market_block_hashes']['b'] is None

        eth = manifest['comparison']['coins']['ETH']
        assert eth['comparable'] is False
        assert eth['market_block_hashes']['a'] is None

    def test_drift_hashes_surfaced_verbatim(self, tmp_path, monkeypatch, capsys):
        fake = FakeBot({
            'a': [{'coin': 'SOL', 'outcome': 'BUY', 'block_text': 'v1'}],
            'b': [{'coin': 'SOL', 'outcome': 'BUY', 'block_text': 'v2'}],
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[
            {'name': 'a', 'flags': []}, {'name': 'b', 'flags': []},
        ])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)
        exp.print_comparison_table(manifest)
        captured = capsys.readouterr()

        sol = manifest['comparison']['coins']['SOL']
        assert sol['differing_hashes']['a'] in captured.out
        assert sol['differing_hashes']['b'] in captured.out
        assert 'drift' in captured.out.lower()

    def test_single_variant_coin_is_trivially_comparable(self, tmp_path, monkeypatch):
        fake = FakeBot({'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'blockA'}]})
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)
        assert manifest['comparison']['coins']['BTC']['comparable'] is True

    def test_stored_hash_sidecar_mismatch_warns(self, tmp_path, monkeypatch, capsys):
        # hash_override makes the record's stored market_block_hash disagree
        # with the hash recomputed from the sidecar block_text -- an
        # integrity problem that must be warned about loudly, not silently
        # trusted.
        fake = FakeBot({
            'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'real-block-text',
                   'hash_override': 'deadbeefdeadbeef'}],
        })
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}])
        exp.validate_and_refuse(spec)
        exp.run_experiment(spec)
        captured = capsys.readouterr()
        assert 'does not match' in captured.out or 'WARN' in captured.out


# ============================================================================
# Print-config capture
# ============================================================================

class TestPrintConfigCapture:
    def test_print_config_written_per_variant(self, tmp_path, monkeypatch):
        fake = FakeBot(
            {'a': [{'coin': 'BTC', 'outcome': 'HOLD', 'block_text': 'x'}]},
            print_config_json={'settings': {'trading_mode': {'value': 'whatif'}}},
        )
        monkeypatch.setattr(exp, '_run_bot', fake)
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)

        pc_path = Path(manifest['variants'][0]['print_config_path'])
        assert pc_path.exists()
        data = json.loads(pc_path.read_text())
        assert data['settings']['trading_mode']['value'] == 'whatif'


# ============================================================================
# Missing run summary (a variant whose run failed / never wrote one)
# ============================================================================

class TestMissingRunSummary:
    def test_missing_summary_does_not_crash_and_is_recorded_as_none(self, tmp_path, monkeypatch):
        def fake_run_bot(cmd, env):
            if '--print-config' in cmd:
                return FakeResult(returncode=0, stdout=json.dumps({'settings': {}}))
            # Simulate a run that failed before writing anything.
            return FakeResult(returncode=1, stdout='')

        monkeypatch.setattr(exp, '_run_bot', fake_run_bot)
        spec = make_spec(tmp_path / 'out', variants=[{'name': 'a', 'flags': []}])
        exp.validate_and_refuse(spec)
        manifest = exp.run_experiment(spec)

        v = manifest['variants'][0]
        assert v['exit_code'] == 1
        assert v['run_id'] is None
        assert v['summary_path'] is None
        assert manifest['comparison']['coins'] == {}
