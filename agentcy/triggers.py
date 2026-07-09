"""agentcy/triggers.py — Trigger taxonomy (B): the five evaluators, B.3 fire wiring."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from agentcy import db
from agentcy.clock import Clock, effective_elapsed
from agentcy.fetch import store
from agentcy.freshness import CheckResult, DataState

_QUARTER = timedelta(days=91)
_WINDOW_QUARTERS = {"single_observation": 1, "2_consecutive_quarters": 2, "ttm": 4}


@dataclass(frozen=True)
class CheckOutcome:
    trigger_id: int
    result: str                      # PASS | FIRE | STALE | BOOTSTRAPPING | UNVERIFIABLE
    observed_value: float | None
    headroom: float | None
    evaluable_from: str | None
    note: str | None


def _outcome(tid, result, *, observed=None, headroom=None, evaluable_from=None, note=None):
    return CheckOutcome(trigger_id=tid, result=result, observed_value=observed,
                        headroom=headroom, evaluable_from=evaluable_from, note=note)


def _breaches(value: float, comparator: str, threshold: float) -> bool:
    return value < threshold if comparator == "<" else value > threshold


def _headroom(value: float, comparator: str, threshold: float) -> float:
    """Signed distance from the threshold, positive = safe. '<' floor: value - threshold;
    '>' ceiling: threshold - value."""
    return value - threshold if comparator == "<" else threshold - value


def evaluate(conn, trigger_row, *, as_of: datetime) -> CheckOutcome:
    """Dispatch by type; stale/empty -> STALE (invariant 6); short archive -> BOOTSTRAPPING."""
    t = trigger_row["type"]
    if t == "owner_attested_event":
        return _eval_prompted(conn, trigger_row, as_of=as_of)
    if t in ("growth_floor", "margin_erosion", "balance_sheet_safety"):
        return _eval_series(conn, trigger_row, as_of=as_of)
    if t == "dilution":
        return _eval_scalar(conn, trigger_row, store.shares_yoy, as_of=as_of)
    raise ValueError(f"unknown trigger type {t!r}")


def _eval_series(conn, trigger_row, *, as_of: datetime) -> CheckOutcome:
    tid = trigger_row["trigger_id"]
    # Resolve by name so only the branch actually taken touches store; margin_series /
    # balance_safety_series land in P3.13 and must not be dereferenced eagerly here.
    fetcher_name = {
        "growth_floor": "revenue_yoy_series",
        "margin_erosion": "margin_series",
        "balance_sheet_safety": "balance_safety_series",
    }[trigger_row["type"]]
    fetcher = getattr(store, fetcher_name)
    stamped = fetcher(conn, _yf(conn, trigger_row), as_of=as_of)
    if stamped is None or not stamped.usable():
        state = stamped.state.value.upper() if stamped else "STALE"
        return _outcome(tid, "STALE" if state == "STALE" else state,
                        note="input not fresh (invariant 6)")
    series = list(stamped.value)                       # [(period_end, value), ...] ascending
    need = _WINDOW_QUARTERS[trigger_row["persistence"]]
    if len(series) < need:
        last = series[-1][0] if series else db.to_iso(as_of)[:10]
        evaluable = (datetime.fromisoformat(last) + _QUARTER * (need - len(series))).date().isoformat()
        return _outcome(tid, "BOOTSTRAPPING", evaluable_from=evaluable,
                        note=f"archive has {len(series)}/{need} periods (MA-1)")
    window = series[-need:]
    latest = window[-1][1]
    comparator, threshold = trigger_row["comparator"], trigger_row["threshold"]
    fires = all(_breaches(v, comparator, threshold) for _, v in window)
    return _outcome(tid, "FIRE" if fires else "PASS", observed=latest,
                    headroom=_headroom(latest, comparator, threshold))


def _eval_scalar(conn, trigger_row, fetcher, *, as_of: datetime) -> CheckOutcome:
    tid = trigger_row["trigger_id"]
    stamped = fetcher(conn, _yf(conn, trigger_row), as_of=as_of)
    if stamped is None or not stamped.usable():
        state = stamped.state.value.upper() if stamped else "STALE"
        return _outcome(tid, "STALE" if state == "STALE" else state,
                        note="input not fresh (invariant 6)")
    v = float(stamped.value)
    comparator, threshold = trigger_row["comparator"], trigger_row["threshold"]
    return _outcome(tid, "FIRE" if _breaches(v, comparator, threshold) else "PASS",
                    observed=v, headroom=_headroom(v, comparator, threshold))


def _yf(conn, trigger_row) -> str:
    """Resolve the thesis ticker to its yf_ticker (symbol_map latest wins; else the ticker)."""
    ticker = db.fetch_thesis(conn, trigger_row["thesis_id"])["ticker"]
    return db.fetch_current_symbol_map(conn).get(ticker, ticker)
