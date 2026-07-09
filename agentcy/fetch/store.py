"""Cache-is-archive read/write surface (tech-arch §7.5; contracts §3.7).

Writes go through agentcy.db append helpers only; freshness/TTL stamps are
computed here at READ time. Frame shapes are the fetch/yf.py normalized ones."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from agentcy import db
from agentcy.freshness import DataState, Stamped

PRICE_STALE_WEEKDAYS = 2            # §7.5: STALE after 2 trading days without a new bar (plan note 2)
STATEMENT_EARNINGS_GRACE_DAYS = 14  # §7.5 "14 failed days" after a passed earnings date (plan note 1)
STATEMENT_MAX_AGE_DAYS = 135        # no-calendar fallback: quarter + reporting lag + slack (plan note 1)
SHARES_GAP_DAYS = 90                # §7.4 gap tolerance
CALENDAR_PREVIEW_DAYS = 21          # D.1 check 5 (MA-7)


@dataclass(frozen=True)
class PriceBar:
    bar_date: str
    close: float
    adj_close: float
    dividend: float
    currency: str


def store_price_bars(conn, yf_ticker: str, frame: pd.DataFrame, *, run_id: int | None, fetched_at: str) -> int:
    """Append bars (re-fetches append, never overwrite; v_price serves latest); returns rows written."""
    rows = [
        {
            "yf_ticker": yf_ticker,
            "bar_date": pd.Timestamp(idx).date().isoformat(),
            "close": float(r["close"]),
            "adj_close": float(r["adj_close"]),
            "dividend": float(r["dividend"]),
            "currency": str(r["currency"]),
            "fetched_at": fetched_at,
            "run_id": run_id,
        }
        for idx, r in frame.iterrows()
    ]
    return db.append_price_rows(conn, rows)


def _weekdays_between(d0: date, d1: date) -> int:
    """Weekdays strictly between d0 and d1 — the calendar-free trading-day proxy (plan note 2)."""
    n, d = 0, d0 + timedelta(days=1)
    while d < d1:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def _bar_state(bar_date: str, as_of: datetime) -> DataState:
    behind = _weekdays_between(date.fromisoformat(bar_date), as_of.date())
    return DataState.STALE if behind >= PRICE_STALE_WEEKDAYS else DataState.FRESH


def latest_close(conn, yf_ticker: str, *, as_of: datetime) -> Stamped[PriceBar] | None:
    """Latest bar at/before as_of, stamped; STALE after 2 trading days without refresh (§7.5)."""
    rows = db.fetch_v_price(conn, yf_ticker, end=as_of.date().isoformat())
    if not rows:
        return None
    row = max(rows, key=lambda r: r["bar_date"])
    state = _bar_state(row["bar_date"], as_of)
    note = None
    if state is DataState.STALE:
        note = f"last bar {row['bar_date']} — stale at {as_of.date().isoformat()} (§7.5 ladder)"
    bar = PriceBar(row["bar_date"], float(row["close"]), float(row["adj_close"]),
                   float(row["dividend"]), row["currency"])
    return Stamped(bar, db.from_iso(row["fetched_at"]), state, note)


def price_state(conn, yf_ticker: str, *, as_of: datetime) -> DataState:
    """FRESH/STALE per the §7.5 ladder; no bars at all is STALE."""
    stamped = latest_close(conn, yf_ticker, as_of=as_of)
    return DataState.STALE if stamped is None else stamped.state


def fx_rate_eur(conn, currency: str, *, as_of: datetime) -> Stamped[float] | None:
    """{CUR}EUR=X latest close, stamped; EUR itself returns 1.0 FRESH."""
    cur = currency.upper()
    if cur == "EUR":
        return Stamped(1.0, as_of, DataState.FRESH)
    stamped = latest_close(conn, f"{cur}EUR=X", as_of=as_of)
    if stamped is None:
        return None
    return Stamped(float(stamped.value.close), stamped.fetched_at, stamped.state, stamped.note)
