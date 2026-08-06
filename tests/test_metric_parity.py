"""Legacy bundle versus Metric Evidence Ledger parity rules."""
from __future__ import annotations

from agentcy.metric_parity import compare


def test_close_fresh_values_pass_with_relative_tolerance():
    result = compare(
        legacy_value=100.0,
        ledger_value=100.005,
        legacy_status="FRESH",
        ledger_status="FRESH",
        tolerance_abs=0.0,
        tolerance_rel=0.0001,
    )
    assert result.verdict == "PASS"
    assert result.absolute_difference == 0.005


def test_missingness_mismatch_fails_even_when_states_differ_openly():
    result = compare(
        legacy_value=None,
        ledger_value=10.0,
        legacy_status="MISSING",
        ledger_status="FRESH",
        tolerance_abs=0.01,
        tolerance_rel=0.01,
    )
    assert result.verdict == "FAIL"
    assert result.reason == "missingness mismatch"


def test_state_mismatch_fails_even_when_values_match():
    result = compare(
        legacy_value=10.0,
        ledger_value=10.0,
        legacy_status="FRESH",
        ledger_status="STALE",
        tolerance_abs=0.01,
        tolerance_rel=0.01,
    )
    assert result.verdict == "FAIL"
    assert result.reason == "state mismatch"


def test_two_missing_values_with_same_state_pass():
    result = compare(
        legacy_value=None,
        ledger_value=None,
        legacy_status="MISSING",
        ledger_status="MISSING",
        tolerance_abs=0.0,
        tolerance_rel=0.0,
    )
    assert result.verdict == "PASS"
    assert result.absolute_difference is None
