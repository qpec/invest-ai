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


def _stmt_frames(yf_statements):
    return yf_statements()


def test_store_statements_appends_per_period_returns_new_fingerprints(tmp_db, yf_statements):
    from agentcy.fetch import store
    new = store.store_statements(tmp_db, "MSFT", _stmt_frames(yf_statements), run_id=None, fetched_at=T1)
    # 3 statement types x 4 periods = 12 unseen fingerprints on first sight (D.3 feed)
    assert len(new) == 12
    # idempotent re-fetch of identical statements writes nothing
    assert store.store_statements(tmp_db, "MSFT", _stmt_frames(yf_statements), run_id=None, fetched_at=T2) == []


def test_store_statements_revised_period_reappends(tmp_db, yf_statements):
    from agentcy.fetch import store
    store.store_statements(tmp_db, "MSFT", _stmt_frames(yf_statements), run_id=None, fetched_at=T1)
    stmts = _stmt_frames(yf_statements)
    newest = stmts["income"].columns[0]
    stmts["income"].loc["Total Revenue", newest] = 6.7e10   # a restatement of the newest quarter
    new = store.store_statements(tmp_db, "MSFT", stmts, run_id=None, fetched_at=T2)
    assert any(f.startswith("income:") for f in new)         # only the changed period re-appends
    assert len(new) == 1


def test_statement_history_latest_fingerprint_ascending_and_fresh(tmp_db, yf_statements, fixed_clock):
    from agentcy.fetch import store
    store.store_statements(tmp_db, "MSFT", _stmt_frames(yf_statements), run_id=None, fetched_at=T1)
    st = store.statement_history(tmp_db, "MSFT", "income", as_of=fixed_clock.now())
    assert st.state is DataState.FRESH and st.usable()
    periods = [r["period_end"] for r in st.value]
    assert periods == sorted(periods)                        # ascending
    assert periods[-1] == "2026-03-31"


def test_statement_history_stale_when_newest_period_too_old(tmp_db, yf_statements):
    from agentcy.fetch import store
    store.store_statements(tmp_db, "MSFT", _stmt_frames(yf_statements), run_id=None, fetched_at=T1)
    # no calendar signal -> newest period_end 2026-03-31; >135d later is STALE (plan note 1b)
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)
    st = store.statement_history(tmp_db, "MSFT", "income", as_of=as_of)
    assert st.state is DataState.STALE and not st.usable() and st.note is not None


def test_statement_history_stale_after_passed_earnings_grace(tmp_db, yf_statements):
    from agentcy.fetch import store
    if not hasattr(store, "store_calendar"):
        pytest.skip("store_calendar lands in P2.11; this P2.9 test auto-activates once it exists (plan note P2.9)")
    store.store_statements(tmp_db, "MSFT", _stmt_frames(yf_statements), run_id=None, fetched_at=T1)
    # calendar says earnings 2026-07-20 (newer than newest archived period 2026-03-31);
    # >14 days after it with no new period -> STALE (plan note 1a)
    store.store_calendar(tmp_db, "MSFT", "2026-07-20", run_id=None, fetched_at=T1)
    as_of = datetime(2026, 8, 10, tzinfo=timezone.utc)       # 21 days past the earnings date
    st = store.statement_history(tmp_db, "MSFT", "income", as_of=as_of)
    assert st.state is DataState.STALE


def test_statement_history_earnings_grace_branch_via_db_calendar(tmp_db, yf_statements):
    # P2.9-local coverage of the passed-earnings-grace STALE branch without P2.11's
    # store.store_calendar: write the calendar row through the committed db helper.
    from agentcy import db
    from agentcy.fetch import store
    store.store_statements(tmp_db, "MSFT", _stmt_frames(yf_statements), run_id=None, fetched_at=T1)
    db.append_earnings_calendar(tmp_db, yf_ticker="MSFT", expected_date="2026-07-20",
                                fetched_at=T1, run_id=None)
    # 21 days past the earnings date (>14d grace), no new period -> STALE (plan note 1a)
    as_of = datetime(2026, 8, 10, tzinfo=timezone.utc)
    st = store.statement_history(tmp_db, "MSFT", "income", as_of=as_of)
    assert st.state is DataState.STALE and st.note is not None
    # still within grace (10 days past) -> newest period 2026-03-31 is <135d old -> FRESH
    within = datetime(2026, 7, 30, tzinfo=timezone.utc)
    assert store.statement_history(tmp_db, "MSFT", "income", as_of=within).state is DataState.FRESH


def test_statement_history_empty_archive_is_stale(tmp_db, fixed_clock):
    from agentcy.fetch import store
    st = store.statement_history(tmp_db, "NOPE", "income", as_of=fixed_clock.now())
    assert st.value == [] and st.state is DataState.STALE and not st.usable()


def test_store_shares_appends_raw_with_duplicates(tmp_db, yf_series):
    from agentcy.fetch import store
    n = store.store_shares(tmp_db, "MSFT", yf_series(), fetched_at=T1)
    assert n == 7                                            # raw, duplicates preserved (§7.4)


def test_shares_history_dedups_last_per_date_at_read(tmp_db, yf_series):
    from agentcy.fetch import store
    store.store_shares(tmp_db, "MSFT", yf_series(), fetched_at=T1)
    # as_of near the last observation 2026-06-25 -> FRESH; dedup keeps LAST value per date
    st = store.shares_history(tmp_db, "MSFT", as_of=datetime(2026, 7, 1, tzinfo=timezone.utc))
    s = st.value
    assert not s.index.duplicated().any()                   # deduped
    assert len(s) == 5                                       # 7 raw rows, 2 duplicate dates collapsed
    assert s.loc[pd.Timestamp("2026-01-05")] == pytest.approx(7.440e9)   # LAST value on the dup date
    assert s.loc[pd.Timestamp("2026-04-01")] == pytest.approx(7.434e9)
    assert st.state is DataState.FRESH and st.usable()


def test_shares_history_stale_after_90_day_gap(tmp_db, yf_series):
    from agentcy.fetch import store
    store.store_shares(tmp_db, "MSFT", yf_series(), fetched_at=T1)
    # last obs 2026-06-25; 100 days later -> STALE (§7.4 gap tolerance)
    st = store.shares_history(tmp_db, "MSFT", as_of=datetime(2026, 10, 3, tzinfo=timezone.utc))
    assert st.state is DataState.STALE and not st.usable() and st.note is not None


def test_shares_history_empty_is_stale(tmp_db, fixed_clock):
    from agentcy.fetch import store
    st = store.shares_history(tmp_db, "NOPE", as_of=fixed_clock.now())
    assert len(st.value) == 0 and st.state is DataState.STALE
