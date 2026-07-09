"""Shape-validation of the recorded yfinance fixture pack (contracts §4.3)."""
from __future__ import annotations

import pandas as pd
import pytest


def test_msft_history_shape(yf_frame):
    frame, currency = yf_frame("msft_history")
    assert currency == "USD"
    for col in ("Close", "Adj Close", "Dividends"):
        assert col in frame.columns
    assert len(frame) == 10
    assert frame.index.is_monotonic_increasing
    # one dividend event rides the same bar fetch (BUF-2 feed)
    assert frame.loc[pd.Timestamp("2026-06-26"), "Dividends"] == pytest.approx(0.83)
    assert (frame["Close"] > 0).all()


def test_msft_statements_shape(yf_statements):
    stmts = yf_statements("msft_statements")
    assert set(stmts) == {"income", "balance", "cashflow"}
    pinned = {
        "income": ("Total Revenue", "EBITDA"),
        "balance": ("Total Debt", "Cash And Cash Equivalents"),
        "cashflow": ("Operating Cash Flow", "Capital Expenditure", "Stock Based Compensation"),
    }
    for stype, frame in stmts.items():
        assert frame.shape[0] >= 8, f"{stype}: implausibly few rows"
        assert frame.shape[1] == 4
        for row in pinned[stype]:
            assert row in frame.index, f"{stype} missing pinned row {row}"
        # yfinance native order: newest period first
        assert frame.columns[0] == pd.Timestamp("2026-03-31")


def test_msft_shares_full_has_duplicates_and_gap(yf_series):
    s = yf_series("msft_shares_full")
    assert len(s) == 7
    assert s.index.duplicated().any(), "fixture must keep the duplicate-date shape (§7.4)"
    dupes = s.index[s.index.duplicated()].unique()
    assert pd.Timestamp("2026-01-05") in dupes and pd.Timestamp("2026-04-01") in dupes
    # 85-day observation gap (verified real-world shape: gaps to 85 days)
    diffs = pd.Series(s.index.unique()).diff().dropna()
    assert diffs.max() == pd.Timedelta(days=85)


def test_empty_frame_is_0x0(yf_frame):
    frame, currency = yf_frame("empty_frame_0x0")
    assert frame.shape == (0, 0)
    assert currency is None


def test_rate_limit_fixture_shape(yf_fixture):
    raw = yf_fixture("rate_limit_429")
    assert raw["exception"] == "YFRateLimitError"
    assert "Rate limited" in raw["message"]


def test_fx_and_benchmark_fixtures(yf_frame):
    fx, fx_cur = yf_frame("eurusd_fx")
    assert fx_cur == "EUR"
    assert len(fx) == 5 and (fx["Close"] < 1.0).all()  # USDEUR=X
    spx, spx_cur = yf_frame("sp500tr_history")
    assert spx_cur == "USD"
    assert len(spx) == 4 and (spx["Close"] > 10_000).all()


def test_officers_fixture_raw_shape(yf_fixture):
    officers = yf_fixture("officers_msft")
    assert isinstance(officers, list) and len(officers) == 3
    assert all("name" in o and "title" in o for o in officers)
    # raw shape keeps volatile fields — fetch_officers strips them (plan note 6)
    assert any("totalPay" in o for o in officers)
