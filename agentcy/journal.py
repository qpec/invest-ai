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
