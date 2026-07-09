"""agentcy/journal.py — Decision Journal (F.1): immutable entries; grades append, never mutate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from agentcy import db
from agentcy.clock import Clock

DECISION_TYPES = frozenset({
    "buy", "add_to_position", "trim", "sell", "hold_after_review", "advice_rejected",
    "alert_ignored", "gate_verdict", "trigger_resolution", "thesis_revision",
    "config_or_designation",
})
# F.1: auto-created entries are alert_ignored and gate_verdict; everything else is owner-initiated
AUTO_TYPES = frozenset({"alert_ignored", "gate_verdict"})
OWNER_INITIATED = DECISION_TYPES - AUTO_TYPES
GRADEABLE = frozenset({"buy", "add_to_position", "trim", "sell", "hold_after_review"})
VALID_GRADES = frozenset({"good", "neutral", "bad", "too_early"})


@dataclass(frozen=True)
class EntryIn:
    """F.1 input; journal.append validates before db.append_journal_entry."""
    decision_type: str
    decision_subtype: str | None = None
    ticker: str | None = None
    thesis_ref: str | None = None
    system_recommendation: str | None = None
    owner_action: str | None = None
    reasoning_at_the_moment: str | None = None
    expectation_and_falsifier: str | None = None
    review_horizon: str | None = None
    inputs_ref: int | None = None
    process: str | None = None
    process_deviation_note: str | None = None
    emotional_note: str | None = None
    ask_ref: str | None = None
    actor: str = "owner"


def append(conn, entry: EntryIn, *, clock: Clock) -> int:
    """Validate F.1 and insert; returns entry_id."""
    if entry.decision_type not in DECISION_TYPES:
        raise ValueError(f"unknown decision_type {entry.decision_type!r} (F.1)")
    if entry.decision_type in OWNER_INITIATED and not (entry.reasoning_at_the_moment or "").strip():
        raise ValueError("reasoning_at_the_moment is mandatory for owner-initiated types (F.1)")
    if entry.process == "deviated" and not (entry.process_deviation_note or "").strip():
        raise ValueError("process=deviated requires a process_deviation_note (F.1)")
    now = clock.now()
    review_horizon = entry.review_horizon
    if review_horizon is None and entry.decision_type in GRADEABLE:
        review_horizon = db.to_iso(now + timedelta(days=365))          # default +1y
    expectation = entry.expectation_and_falsifier
    if expectation is None and entry.decision_type in ("buy", "add_to_position") and entry.thesis_ref:
        expectation = entry.thesis_ref                                  # F5: the thesis IS the falsifier
    return db.append_journal_entry(conn, {
        "ts": db.to_iso(now),
        "decision_type": entry.decision_type,
        "decision_subtype": entry.decision_subtype,
        "ticker": entry.ticker,
        "thesis_ref": entry.thesis_ref,
        "system_recommendation": entry.system_recommendation,
        "owner_action": entry.owner_action,
        "reasoning_at_the_moment": entry.reasoning_at_the_moment,
        "expectation_and_falsifier": expectation,
        "review_horizon": review_horizon,
        "inputs_ref": entry.inputs_ref,
        "process": entry.process,
        "process_deviation_note": entry.process_deviation_note,
        "emotional_note": entry.emotional_note,
        "ask_ref": entry.ask_ref,
        "actor": entry.actor,
    })


def bootstrap_entry_id() -> int:
    """The migration-000 bootstrap journal entry — journal-FK anchor for early config writes."""
    return 1


def grade(conn, entry_id: int, *, outcome_grade: str, note: str | None, clock: Clock) -> None:
    """Append a journal_grade row — judged against expectation/falsifier, never raw price (F.1)."""
    if outcome_grade not in VALID_GRADES:
        raise ValueError(f"outcome_grade must be one of {sorted(VALID_GRADES)}")
    if db.fetch_journal_entry(conn, entry_id) is None:
        raise KeyError(entry_id)
    db.append_journal_grade(conn, entry_id=entry_id, graded_at=db.to_iso(clock.now()),
                            outcome_grade=outcome_grade, note=note)


def due_for_review(conn, *, as_of: datetime) -> list:
    """Entries at/past review_horizon without a grade; 'too_early' re-queues one horizon (+1y)."""
    out = []
    for row in db.fetch_journal_entries(conn):
        if not row["review_horizon"] or db.from_iso(row["review_horizon"]) > as_of:
            continue
        grades = db.fetch_grades_for(conn, row["entry_id"])
        if not grades:
            out.append(row)
        else:
            last = grades[-1]
            # too_early re-queues one horizon from the review point (review_horizon), not the
            # wall-clock grading time — so a grade recorded early still defers a full horizon.
            if (last["outcome_grade"] == "too_early"
                    and db.from_iso(row["review_horizon"]) + timedelta(days=365) <= as_of):
                out.append(row)
    return out


def review_matrix(conn, period: tuple[str, str]) -> dict:
    """F.2 quarterly batch: the 2x2, dangerous wins, followed/overridden %, override hit-rate,
    alert_ignored count, no-action ratio. Entries counted by ts within [start, end]."""
    start, end = period
    entries = [r for r in db.fetch_journal_entries(conn) if start <= r["ts"] <= end]
    matrix: dict[tuple[str, str], list[int]] = {}
    dangerous, overridden, followed, over_good = [], 0, 0, 0
    for r in entries:
        grades = db.fetch_grades_for(conn, r["entry_id"])
        if r["owner_action"] == "followed":
            followed += 1
        elif r["owner_action"] == "overridden":
            overridden += 1
        if not grades or r["process"] is None:
            continue
        g = grades[-1]["outcome_grade"]
        matrix.setdefault((r["process"], g), []).append(r["entry_id"])
        if r["process"] == "deviated" and g == "good":
            dangerous.append(r["entry_id"])            # DANGEROUS WIN — flagged loudest (F.2)
        if r["owner_action"] == "overridden" and g == "good":
            over_good += 1
    acted = followed + overridden
    no_action = sum(1 for r in entries if r["owner_action"] == "no_action")
    return {
        "matrix": matrix,
        "dangerous_wins": dangerous,
        "followed_pct": 100.0 * followed / acted if acted else 0.0,
        "overridden_pct": 100.0 * overridden / acted if acted else 0.0,
        "override_hit_rate": 100.0 * over_good / overridden if overridden else 0.0,
        "alert_ignored": sum(1 for r in entries if r["decision_type"] == "alert_ignored"),
        "no_action_ratio": no_action / len(entries) if entries else 0.0,
    }
