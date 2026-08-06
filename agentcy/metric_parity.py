"""Deterministic comparison between legacy bundle and ledger metric outputs."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ParityResult:
    verdict: str
    reason: str
    absolute_difference: float | None


def compare(*, legacy_value: float | None, ledger_value: float | None,
            legacy_status: str, ledger_status: str,
            tolerance_abs: float, tolerance_rel: float) -> ParityResult:
    """Compare missingness, state, and then numeric values in that strict order."""
    if tolerance_abs < 0 or tolerance_rel < 0:
        raise ValueError("parity tolerances must be non-negative")
    if (legacy_value is None) != (ledger_value is None):
        return ParityResult("FAIL", "missingness mismatch", None)
    if legacy_status != ledger_status:
        return ParityResult("FAIL", "state mismatch", None)
    if legacy_value is None:
        return ParityResult("PASS", "both missing with matching state", None)

    left, right = float(legacy_value), float(ledger_value)
    if not math.isfinite(left) or not math.isfinite(right):
        return ParityResult("FAIL", "non-finite value", None)
    difference = round(abs(left - right), 12)
    allowed = max(tolerance_abs, tolerance_rel * max(abs(left), abs(right)))
    if difference <= allowed:
        return ParityResult("PASS", "within tolerance", difference)
    return ParityResult("FAIL", "numeric mismatch", difference)
