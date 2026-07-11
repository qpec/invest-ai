"""Grade-time market_data assembly from the archive (populator design 5, plan note 2).
market_cap = latest v_price close x latest shares; total_debt/cash from the latest balance
row; currency mismatch -> ticker omitted -> grade_universe emits INSUFFICIENT (no FX)."""
from datetime import datetime, timezone

import pandas as pd

from agentcy import scout_grade as sg
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed(conn, sym, yf_statements, yf_series, *, currency="USD", close=500.0):
    store.store_statements(conn, sym, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"),
                       fetched_at="2026-07-07T00:00:00Z")
    frame = pd.DataFrame({"close": [close], "adj_close": [close], "dividend": [0.0],
                          "currency": [currency]}, index=pd.to_datetime(["2026-07-07"]))
    store.store_price_bars(conn, sym, frame, run_id=None, fetched_at="2026-07-07T00:00:00Z")


def test_assembler_builds_market_cap_debt_cash_from_archive(tmp_db, yf_statements, yf_series):
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    md = sg._market_data_from_archive(tmp_db, ["MSFT"], as_of=AS_OF)
    entry = md["MSFT"]
    # latest shares from the recorded series; market_cap = close x shares
    shares = store.shares_history(tmp_db, "MSFT", as_of=AS_OF)
    latest_shares = float(shares.value[shares.value.index <= pd.Timestamp(AS_OF.date())].iloc[-1])
    assert entry["market_cap"] == 500.0 * latest_shares
    assert entry["total_debt"] is not None
    assert entry["cash"] is not None


def test_missing_price_or_shares_yields_none_market_cap(tmp_db, yf_statements, yf_series):
    # statements only, no price/shares -> market_cap None -> the name is uncomputable (RF5).
    store.store_statements(tmp_db, "NOPX", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    md = sg._market_data_from_archive(tmp_db, ["NOPX"], as_of=AS_OF)
    assert md["NOPX"]["market_cap"] is None


def test_currency_mismatch_omits_the_ticker(tmp_db, yf_statements, yf_series):
    # price in EUR, statement currency declared USD -> mismatch -> omitted (no FX, design 9).
    _seed(tmp_db, "SAP", yf_statements, yf_series, currency="EUR")
    md = sg._market_data_from_archive(tmp_db, ["SAP"], as_of=AS_OF,
                                      statement_currency={"SAP": "USD"})
    assert "SAP" not in md
