"""agentcy/register.py — Thesis Register (A): versioning, status log, goalpost guard."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from agentcy import config as _config
from agentcy import db
from agentcy.clock import Clock, effective_elapsed

MOAT_TYPES = frozenset({"network_effects", "switching_costs", "cost_advantage",
                        "brand_trust", "regulatory_barrier"})
CONVICTION = frozenset({"high", "medium", "low"})
MGMT_TRUST = frozenset({"trusted_owner_operator", "trusted_professional", "neutral", "distrust"})
CIRCLE_FIT = frozenset({"core", "edge"})
STATUSES = frozenset({"draft", "intact", "under_review", "broken", "retired"})
_SENTENCE = re.compile(r"[.!?]+")


@dataclass(frozen=True)
class TriggerSpec:
    type: str
    statement: str
    metric: str | None
    comparator: str | None
    threshold: float | None
    moat_link: str | None
    persistence: str
    yes_means: str | None = None


@dataclass(frozen=True)
class ThesisFields:
    business_model_2s: str
    moat_types: tuple[str, ...]
    moat_evidence: str
    owner_earnings_json: str
    owner_earnings_narrative: str
    value_at_purchase: float | None
    fair_band_low: float
    fair_band_high: float
    denominator_note: str | None
    conviction: str
    mgmt_trust: str
    mgmt_trust_note: str | None
    circle_fit: str
    circle_fit_note: str | None
    ten_year_statement: str
    status_buy_flag: bool
    status_buy_note: str | None


def _sentence_count(text: str) -> int:
    return len([s for s in _SENTENCE.split(text) if s.strip()])


def _validate_fields(f: ThesisFields) -> None:
    if _sentence_count(f.business_model_2s) > 2:
        raise ValueError("business_model_2s exceeds the hard 2 sentence limit (A.1)")
    if not f.moat_types or not set(f.moat_types) <= MOAT_TYPES:
        raise ValueError("moat_types: at least one, from the enumerated set (A.1)")
    if f.conviction not in CONVICTION:
        raise ValueError(f"conviction must be one of {sorted(CONVICTION)}")
    if f.mgmt_trust not in MGMT_TRUST:
        raise ValueError(f"mgmt_trust must be one of {sorted(MGMT_TRUST)}")
    if f.circle_fit not in CIRCLE_FIT:
        raise ValueError(f"circle_fit must be one of {sorted(CIRCLE_FIT)}")


def _validate_triggers(triggers: Sequence[TriggerSpec]) -> None:
    if not (2 <= len(triggers) <= 5):
        raise ValueError("a thesis carries between 2 and 5 triggers (A.1)")
    if not any(t.moat_link for t in triggers):
        raise ValueError("at least one trigger must carry a moat_link (BUF-4)")


def _next_thesis_id(conn, ticker: str) -> str:
    existing = [t["thesis_id"] for t in db.fetch_theses(conn) if t["ticker"] == ticker]
    return f"TH-{ticker}-{len(existing) + 1:03d}"


def create_thesis(conn, *, ticker: str, origin: str, fields: ThesisFields,
                  triggers: Sequence[TriggerSpec], journal_ref: int, clock: Clock) -> str:
    """Mint TH-{TICKER}-{NNN}, v1, status draft; validates A.1 before any append."""
    if origin not in ("gate", "backfill"):
        raise ValueError("origin must be 'gate' or 'backfill'")
    _validate_fields(fields)
    _validate_triggers(triggers)
    now = db.to_iso(clock.now())
    tid = _next_thesis_id(conn, ticker)
    db.append_thesis(conn, thesis_id=tid, ticker=ticker, origin=origin, created_at=now)
    db.append_thesis_version(conn, {
        "thesis_id": tid, "version": 1,
        "business_model_2s": fields.business_model_2s,
        "moat_types_json": json.dumps(list(fields.moat_types)),
        "moat_evidence": fields.moat_evidence,
        "owner_earnings_json": fields.owner_earnings_json,
        "owner_earnings_narrative": fields.owner_earnings_narrative,
        "anchor_metric": "P_FCF_owner",
        "value_at_purchase": None,                     # v1: null until activation; backfill stays null
        "fair_band_low": fields.fair_band_low, "fair_band_high": fields.fair_band_high,
        "denominator_note": fields.denominator_note,
        "conviction": fields.conviction, "mgmt_trust": fields.mgmt_trust,
        "mgmt_trust_note": fields.mgmt_trust_note, "circle_fit": fields.circle_fit,
        "circle_fit_note": fields.circle_fit_note, "time_horizon": "10y_plus",
        "ten_year_statement": fields.ten_year_statement,
        "status_buy_flag": 1 if fields.status_buy_flag else 0,
        "status_buy_note": fields.status_buy_note,
        "diff_json": None, "reason": None, "actor": "owner",
        "journal_ref": journal_ref, "created_at": now,
    })
    db.append_thesis_status(conn, thesis_id=tid, status="draft", changed_at=now,
                            cause="created", cause_ref=str(journal_ref))
    for t in triggers:
        commit_trigger(conn, tid, t, introduced_version=1, journal_ref=journal_ref)
    return tid


def commit_trigger(conn, thesis_id: str, spec: TriggerSpec, *, introduced_version: int,
                   journal_ref: int) -> int:
    """Append a trigger definition row (tightening/adding is always free, A.3)."""
    return db.append_trigger(conn, {
        "thesis_id": thesis_id, "introduced_version": introduced_version, "type": spec.type,
        "statement": spec.statement, "metric": spec.metric, "comparator": spec.comparator,
        "threshold": spec.threshold, "moat_link": spec.moat_link, "persistence": spec.persistence,
        "check_method": "prompted" if spec.type == "owner_attested_event" else "automated",
        "data_source": _DATA_SOURCE[spec.type], "cadence": _CADENCE[spec.type],
        "yes_means": spec.yes_means,
    })


_DATA_SOURCE = {
    "growth_floor": "yf_quarterly_statements", "margin_erosion": "yf_quarterly_statements",
    "balance_sheet_safety": "yf_quarterly_statements", "dilution": "yf_shares_full",
    "owner_attested_event": "owner_attestation",
}
_CADENCE = {
    "growth_floor": "weekly", "margin_erosion": "weekly", "balance_sheet_safety": "weekly",
    "dilution": "weekly", "owner_attested_event": "event",
}


def current(conn, thesis_id: str):
    """Current version row (max version) — status/trigger state fetched separately (derived)."""
    return db.fetch_current_thesis_version(conn, thesis_id)


def live_thesis_for(conn, ticker: str) -> str | None:
    """The non-retired thesis for a ticker, if any."""
    for t in db.fetch_theses(conn):
        if t["ticker"] != ticker:
            continue
        st = db.fetch_current_thesis_status(conn, t["thesis_id"])
        if st and st["status"] != "retired":
            return t["thesis_id"]
    return None


_ALLOWED = {
    "draft": {"intact", "retired"},
    "intact": {"under_review", "retired"},
    "under_review": {"intact", "broken", "retired"},
    "broken": {"retired"},
    "retired": set(),
}


def activate(conn, thesis_id: str, *, cause: str, clock: Clock) -> None:
    """draft -> intact when the position appears in a Snapshot / backfill confirmed (A.2)."""
    transition(conn, thesis_id, "intact", cause=cause, cause_ref=None, clock=clock)


def transition(conn, thesis_id: str, new_status: str, *, cause: str, cause_ref: str | None,
               clock: Clock) -> None:
    """Validated A.2 transition (broken terminal; broken->intact does not exist)."""
    if new_status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    cur = db.fetch_current_thesis_status(conn, thesis_id)
    if cur is None:
        raise KeyError(thesis_id)
    if new_status not in _ALLOWED[cur["status"]]:
        raise ValueError(
            f"illegal transition {cur['status']!r} -> {new_status!r} (A.2; broken is terminal)")
    now = db.to_iso(clock.now())
    review_deadline = None
    if new_status == "under_review":
        days = _config.get_int(conn, "alert_decision_days")
        review_deadline = db.to_iso(clock.now() + timedelta(days=days))
    db.append_thesis_status(conn, thesis_id=thesis_id, status=new_status, changed_at=now,
                            cause=cause, cause_ref=cause_ref, review_deadline=review_deadline)
