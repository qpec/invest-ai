"""agentcy/backfill.py - backfill-thesis onboarding (deterministic scaffolding).

Detects held positions with no live thesis, computes a fundamentals baseline as of the
invested moment, auto-derives the four Moderate invalidation triggers, creates an
origin='backfill' DRAFT thesis anchored to the invested moment, and mints a Telegram
ratification ask (approve -> intact + armed; edit -> stays draft). The Claude qualitative
drafting is Part B (out of scope); until then the NOT-NULL qualitative fields carry explicit
DRAFT placeholders and the thesis stays draft (UNmonitored) until ratified. Cost basis is
RECORD-KEEPING only and never enters positions_advice (invariant 4)."""
from __future__ import annotations

from dataclasses import dataclass

from agentcy import db, mirror, register


@dataclass(frozen=True)
class HeldWithoutThesis:
    symbol: str
    yf_ticker: str | None
    instrument_type: str
    quantity: float
    opened_at: str | None
    invested_eur: float | None


def detect_thesis_less(conn, *, as_of) -> list[HeldWithoutThesis]:
    """Non-cash holdings in the latest snapshot with no live thesis, joined to their
    invested-moment position_detail (opened_at, invested_eur). Backed by advice_positions
    (invariant 4) + fetch_position_details (record-keeping companion)."""
    snap = db.fetch_latest_snapshot(conn)
    if snap is None:
        return []
    details = {d["symbol"]: d for d in db.fetch_position_details(conn, snap["snapshot_id"])}
    out: list[HeldWithoutThesis] = []
    for p in mirror.advice_positions(conn, snap["snapshot_id"]):
        if p.instrument_type == "cash":
            continue
        if register.live_thesis_for(conn, p.symbol) is not None:
            continue
        d = details.get(p.symbol)
        out.append(HeldWithoutThesis(
            symbol=p.symbol, yf_ticker=p.yf_ticker, instrument_type=p.instrument_type,
            quantity=p.quantity,
            opened_at=(d["opened_at"] if d else None),
            invested_eur=(d["invested_eur"] if d else None)))
    return out
