"""Regression tests for the discovery-report test-detail printer.

The verbose analyze run crashed with `TypeError: unsupported format string
passed to NoneType.__format__` when statsmodels was not installed: the
Granger causality test skips and stores p_value=None, but the printer
applied `:.4f` to it (observed 2026-07-19, correlation_tracker.py:2804).
The crash also aborted the run before discovery_report.json was written,
which broke leading_indicator_tester.py downstream.
"""

import pytest

# Aliased so pytest does not try to collect the dataclass as a test class.
from correlation_tracker import TestResult as TrackerTestResult
from correlation_tracker import print_test_result_detail


def _skipped_granger_result():
    # Mirrors the exact shape built in CorrelationAnalyzer (TEST 3) when
    # granger_was_run is False.
    return TrackerTestResult(
        test_name="Granger Causality",
        passed="Skipped",
        metrics={
            'test_type': 'ssr_ftest',
            'p_value': None,
            'significance_threshold': 0.05,
            'test_run': False,
        },
        reason="Test skipped - statsmodels not installed or insufficient data",
        reason_code="GRANGER_SKIPPED",
    )


def test_skipped_granger_does_not_crash(capsys):
    print_test_result_detail(3, _skipped_granger_result())
    out = capsys.readouterr().out
    assert "Granger Causality" in out
    assert "skipped" in out
    assert "SKIPPED" in out          # status line, not a false "PASS"
    assert "None" not in out


def test_run_granger_prints_pvalue(capsys):
    result = TrackerTestResult(
        test_name="Granger Causality",
        passed=True,
        metrics={
            'test_type': 'ssr_ftest',
            'p_value': 0.0123,
            'significance_threshold': 0.05,
            'test_run': True,
        },
        reason="p=0.0123 < 0.05, statistically significant predictive relationship",
        reason_code=None,
    )
    print_test_result_detail(3, result)
    out = capsys.readouterr().out
    assert "0.0123" in out
    assert "PASS" in out


def test_all_test_names_print_without_error(capsys):
    # Every branch of the printer with production-shaped metrics; a new
    # None-able metric in any branch should be caught here.
    results = [
        TrackerTestResult("Data Validation", True,
                   {'leader_samples': 20, 'follower_samples': 20,
                    'minimum_required': 10},
                   "Sufficient samples available"),
        TrackerTestResult("Cross-Correlation Analysis", True,
                   {'lag_range_periods': (-10, 10), 'correlation_at_zero': 0.4523,
                    'correlation_at_optimal': 0.7754, 'optimal_lag_periods': 10,
                    'optimal_lag_seconds': 300, 'improvement_over_zero': 0.3231,
                    'improvement_pct': 71.4},
                   "Leader precedes follower by 10 periods"),
        _skipped_granger_result(),
        TrackerTestResult("Rolling Correlation Stability", False,
                   {'window_size': 10, 'mean_correlation': 0.5,
                    'std_deviation': 0.3, 'stability_score': 0.7,
                    'stability_threshold': 0.7},
                   "Unstable correlation"),
        TrackerTestResult("Confidence Score Calculation", False,
                   {'factors': {'correlation': {'value': 0.5, 'weight': 0.4,
                                                'contribution': 0.2}},
                    'total_score': 0.27, 'confidence_level': 'low'},
                   "Below threshold"),
    ]
    for i, result in enumerate(results, 1):
        print_test_result_detail(i, result)
    out = capsys.readouterr().out
    assert out.count("RESULT:") == len(results)
