"""fetch/store.py — cache-is-archive read/write surface (tech-arch §7.5; contracts §3.7)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from agentcy.freshness import DataState

T1 = "2026-07-08T05:05:00Z"
T2 = "2026-07-08T06:00:00Z"
T3 = "2026-07-09T05:05:00Z"


def _bars(yf_frame, name="msft_history"):
    from agentcy.fetch import yf as yfd  # reuse the normalizer: fixture -> normalized frame
    frame, currency = yf_frame(name)
    out = pd.DataFrame(
        {
            "close": frame["Close"].astype(float),
            "adj_close": frame["Adj Close"].astype(float),
            "dividend": frame["Dividends"].fillna(0.0).astype(float),
        },
        index=frame.index,
    )
    out["currency"] = currency
    return out


def test_store_and_read_latest_close_fresh(tmp_db, fixed_clock, yf_frame):
    from agentcy.fetch import store
    n = store.store_price_bars(tmp_db, "MSFT", _bars(yf_frame), run_id=None, fetched_at=T1)
    assert n == 10
    st = store.latest_close(tmp_db, "MSFT", as_of=fixed_clock.now())
    assert st is not None and st.state is DataState.FRESH and st.usable()
    assert st.value.bar_date == "2026-07-07"
    assert st.value.close == pytest.approx(523.60)
    assert st.value.currency == "USD"
    assert st.fetched_at == datetime(2026, 7, 8, 5, 5, tzinfo=timezone.utc)


def test_dividend_column_persists(tmp_db, fixed_clock, yf_frame):
    from agentcy import db
    from agentcy.fetch import store
    store.store_price_bars(tmp_db, "MSFT", _bars(yf_frame), run_id=None, fetched_at=T1)
    rows = db.fetch_v_price(tmp_db, "MSFT")
    by_date = {r["bar_date"]: r for r in rows}
    assert by_date["2026-06-26"]["dividend"] == pytest.approx(0.83)   # BUF-2 receipts feed
    assert by_date["2026-07-07"]["dividend"] == 0.0


def test_refetch_appends_and_v_price_serves_latest(tmp_db, fixed_clock, yf_frame):
    from agentcy.fetch import store
    store.store_price_bars(tmp_db, "MSFT", _bars(yf_frame), run_id=None, fetched_at=T1)
    fix = pd.DataFrame(
        {"close": [523.75], "adj_close": [523.75], "dividend": [0.0], "currency": ["USD"]},
        index=[pd.Timestamp("2026-07-07")],
    )
    store.store_price_bars(tmp_db, "MSFT", fix, run_id=None, fetched_at=T2)   # append, never overwrite
    st = store.latest_close(tmp_db, "MSFT", as_of=fixed_clock.now())
    assert st.value.close == pytest.approx(523.75)
    assert st.fetched_at == datetime(2026, 7, 8, 6, 0, tzinfo=timezone.utc)


def test_weekday_staleness_ladder(tmp_db, yf_frame):
    from agentcy.fetch import store
    store.store_price_bars(tmp_db, "MSFT", _bars(yf_frame), run_id=None, fetched_at=T1)
    # last bar Tue 2026-07-07: Thu 07-09 -> 1 weekday behind -> FRESH; Fri 07-10 -> 2 -> STALE
    assert store.price_state(tmp_db, "MSFT", as_of=datetime(2026, 7, 9, 5, 0, tzinfo=timezone.utc)) is DataState.FRESH
    st = store.latest_close(tmp_db, "MSFT", as_of=datetime(2026, 7, 10, 5, 0, tzinfo=timezone.utc))
    assert st.state is DataState.STALE and not st.usable() and st.note is not None


def test_weekdays_between_weekend_arithmetic():
    from agentcy.fetch import store
    assert store._weekdays_between(date(2026, 7, 3), date(2026, 7, 6)) == 0   # Fri -> Mon
    assert store._weekdays_between(date(2026, 7, 3), date(2026, 7, 7)) == 1   # Fri -> Tue
    assert store._weekdays_between(date(2026, 7, 3), date(2026, 7, 8)) == 2   # Fri -> Wed


def test_unknown_ticker_returns_none_and_stale(tmp_db, fixed_clock):
    from agentcy.fetch import store
    assert store.latest_close(tmp_db, "NOPE", as_of=fixed_clock.now()) is None
    assert store.price_state(tmp_db, "NOPE", as_of=fixed_clock.now()) is DataState.STALE


def test_fx_rate_eur(tmp_db, fixed_clock, yf_frame):
    from agentcy.fetch import store
    store.store_price_bars(tmp_db, "USDEUR=X", _bars(yf_frame, "eurusd_fx"), run_id=None, fetched_at=T1)
    st = store.fx_rate_eur(tmp_db, "USD", as_of=fixed_clock.now())
    assert st.value == pytest.approx(0.8577) and st.state is DataState.FRESH
    eur = store.fx_rate_eur(tmp_db, "EUR", as_of=fixed_clock.now())
    assert eur.value == 1.0 and eur.state is DataState.FRESH
    assert store.fx_rate_eur(tmp_db, "GBP", as_of=fixed_clock.now()) is None
