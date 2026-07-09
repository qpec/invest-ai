"""agentcy/study.py — The Study (F.3): weekly digest, rotation, notes. No performance numbers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from agentcy import db, journal
from agentcy.clock import Clock

# Fixed mental-model prompts (Naval loop; tightening a trigger is always free — F.3 §2).
MENTAL_MODELS = (
    "Invert: what would make {ticker} worthless in 10 years? Is any of that a missing trigger?",
    "Second-order: if {ticker}'s biggest customer built this in-house, what breaks the moat?",
    "Base rates: how often do businesses with this moat type keep it for a decade?",
    "Opportunity cost: which held name would you sell to add to {ticker} today, and why not?",
)


@dataclass(frozen=True)
class StudyContext:
    """F.3, capped at one screen; no performance numbers by construction."""
    restudy_ticker: str
    restudy_excerpt: str
    restudy_question: str
    mental_model_prompt: str
    journal_previews: tuple[str, ...]
    reading_line: str
    circle_note_ask_id: str | None


def _next_thesis(conn) -> "db.Row | None":
    theses = [t for t in db.fetch_theses(conn)
              if (db.fetch_current_thesis_status(conn, t["thesis_id"]) or {})["status"]
              not in ("draft", "retired")]
    if not theses:
        return None
    last = db.fetch_study_state(conn)["last_restudied_thesis_id"]
    ids = [t["thesis_id"] for t in theses]
    if last in ids:
        idx = (ids.index(last) + 1) % len(ids)
    else:
        idx = 0
    return theses[idx]


def build_digest(conn, *, as_of: datetime) -> StudyContext:
    """F.3 five sections from study_state rotation; NEVER performance numbers or new ideas."""
    t = _next_thesis(conn)
    if t is None:
        return StudyContext("", "", "", MENTAL_MODELS[0].format(ticker="the portfolio"),
                            (), "Nothing to restudy yet.", None)
    ticker = t["ticker"]
    version = db.fetch_current_thesis_version(conn, t["thesis_id"])
    mm_index = db.fetch_study_state(conn)["mental_model_index"] % len(MENTAL_MODELS)
    previews = []
    horizon = as_of + timedelta(days=30)
    for e in journal.due_for_review(conn, as_of=horizon)[:3]:
        previews.append(f"JE-{e['entry_id']:04d} {e['decision_type']} {e['ticker'] or ''} "
                        f"— review approaching")
    return StudyContext(
        restudy_ticker=ticker,
        restudy_excerpt=f"{ticker} v{version['version']}: {version['business_model_2s']}",
        restudy_question="What changed this quarter, and is it a missing trigger?",
        mental_model_prompt=MENTAL_MODELS[mm_index].format(ticker=ticker),
        journal_previews=tuple(previews),
        reading_line=f"Re-read {ticker}'s latest weekly section (20 minutes).",
        circle_note_ask_id=None,
    )


def advance_rotation(conn, *, thesis_id: str | None, model_index: int, clock: Clock) -> None:
    """Move the rotation pointer after the weekly digest is built."""
    db.update_study_state(conn, last_restudied_thesis_id=thesis_id, mental_model_index=model_index,
                          updated_at=db.to_iso(clock.now()))


def record_note(conn, *, kind: str, text: str, ask_ref: str | None, clock: Clock) -> int:
    """Append a study_note (circle_note / restudy_response); optional, unescalated."""
    if kind not in ("circle_note", "restudy_response"):
        raise ValueError("study note kind must be circle_note or restudy_response")
    return db.append_study_note(conn, ts=db.to_iso(clock.now()), kind=kind, text=text,
                                ask_ref=ask_ref)
