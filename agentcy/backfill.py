"""agentcy/backfill.py - backfill-thesis onboarding (deterministic scaffolding).

Detects held positions with no live thesis, computes a fundamentals baseline as of the
invested moment, auto-derives the four Moderate invalidation triggers, creates an
origin='backfill' DRAFT thesis anchored to the invested moment, and mints a Telegram
ratification ask (approve -> intact + armed; edit -> stays draft). The Claude qualitative
drafting is Part B (out of scope); until then the NOT-NULL qualitative fields carry explicit
DRAFT placeholders and the thesis stays draft (UNmonitored) until ratified. Cost basis is
RECORD-KEEPING only and never enters positions_advice (invariant 4)."""
from __future__ import annotations

import json
from dataclasses import dataclass

from agentcy import db, mirror, register
from agentcy.fetch import store


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


@dataclass(frozen=True)
class Baseline:
    """The invested-moment fundamentals anchor for a backfill thesis. Every leg is None when
    its underlying series/scalar is absent/stale/thin -> that leg is skipped downstream
    (BOOTSTRAPPING), never faked."""
    yf_ticker: str
    revenue_yoy: float | None
    owner_fcf_margin: float | None
    net_debt_ebitda: float | None
    shares_yoy: float | None
    owner_earnings_json: str


def _last_series_value(stamped) -> float | None:
    """Last (period_end, value) value of a usable series Stamped, else None."""
    if stamped is None or not stamped.usable():
        return None
    series = stamped.value
    if not series:
        return None
    return series[-1][1]


def _scalar_value(stamped) -> float | None:
    """Scalar of a usable Stamped (None value / stale / absent -> None)."""
    if stamped is None or not stamped.usable():
        return None
    return stamped.value


def compute_baseline(conn, yf_ticker, *, as_of) -> Baseline:
    """The invested-moment fundamentals anchor. Every leg is None-safe: a leg with no
    computable/usable series is None (skipped / BOOTSTRAPPING downstream, never faked)."""
    rev = _last_series_value(store.revenue_yoy_series(conn, yf_ticker, as_of=as_of))
    margin = _last_series_value(store.margin_series(conn, yf_ticker, as_of=as_of))
    ndte = _last_series_value(store.balance_safety_series(conn, yf_ticker, as_of=as_of))
    shares = _scalar_value(store.shares_yoy(conn, yf_ticker, as_of=as_of))
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    oe_json = "{}"
    if oe is not None and oe.usable():
        v = oe.value
        oe_json = json.dumps({
            "fcf_ttm": v.fcf_ttm, "sbc_ttm": v.sbc_ttm, "owner_fcf_ttm": v.owner_fcf_ttm,
            "owner_fcf_per_share_ttm": v.owner_fcf_per_share_ttm,
            "owner_fcf_margin_ttm": v.owner_fcf_margin_ttm,
            "periods_used": list(v.periods_used)})
    return Baseline(yf_ticker=yf_ticker, revenue_yoy=rev, owner_fcf_margin=margin,
                    net_debt_ebitda=ndte, shares_yoy=shares, owner_earnings_json=oe_json)
