"""Stage-1 Value pillar raw metrics (design §1 Pillar V): owner-FCF yield + P/owner-FCF."""
from datetime import datetime, timezone

from agentcy import db
from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed_msft(conn, yf_statements, yf_series):
    """Seed the append-only archive from the recorded MSFT statements + shares."""
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_value_metrics_owner_fcf_yield_and_p_ofcf(tmp_db, yf_statements, yf_series):
    _seed_msft(tmp_db, yf_statements, yf_series)
    # market cap in USD (native) so EV/price are in the statement currency
    m = sg.value_metrics(tmp_db, "MSFT", market_cap=2.8e12, total_debt=59e9,
                         cash=84e9, as_of=AS_OF)
    assert m is not None
    # owner-FCF TTM = sum(OCF - |CapEx|) - SBC over 4 quarters
    #   FCF = (36-13)+(34-12)+(32-11)+(30-10) = 86e9 ; SBC = 2.8+2.7+2.6+2.5 = 10.6e9
    #   owner_fcf = 75.4e9
    assert round(m["owner_fcf_ttm"] / 1e9, 1) == 75.4
    # EV = mktcap + debt - cash = 2.8e12 + 59e9 - 84e9 = 2.775e12
    #   owner-FCF yield = 75.4e9 / 2.775e12
    assert round(m["owner_fcf_yield"], 4) == round(75.4e9 / 2.775e12, 4)
    # P/owner-FCF = mktcap / owner_fcf (display companion)
    assert round(m["p_owner_fcf"], 2) == round(2.8e12 / 75.4e9, 2)


def test_value_metrics_none_when_ownerfcf_not_computable(tmp_db, yf_series):
    # only shares, no statements -> owner_fcf_ttm returns None -> value_metrics None
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    assert sg.value_metrics(tmp_db, "MSFT", market_cap=2.8e12, total_debt=0.0,
                            cash=0.0, as_of=AS_OF) is None


def test_value_metrics_yield_none_when_ev_non_positive(tmp_db, yf_statements, yf_series):
    # RF5 groundwork: EV <= 0 -> owner_fcf_yield returns None cleanly, never raises.
    _seed_msft(tmp_db, yf_statements, yf_series)
    m = sg.value_metrics(tmp_db, "MSFT", market_cap=50e9, total_debt=0.0,
                         cash=100e9, as_of=AS_OF)  # EV = 50e9 - 100e9 = -50e9 <= 0
    assert m is not None
    assert m["owner_fcf_yield"] is None
    # owner_fcf > 0 and market_cap > 0 so the P/owner-FCF companion is still computable
    assert round(m["p_owner_fcf"], 2) == round(50e9 / 75.4e9, 2)


def test_value_uses_normalized_owner_fcf(tmp_db, yf_statements, yf_series):
    """Stage-1.5: V consumes the NORMALIZED owner-FCF. Inject a small D&A row so normalized
    (101.4e9) > conservative (75.4e9); the yield/p_owner_fcf must reflect 101.4e9."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    cf.loc["Depreciation And Amortization"] = [5e9, 5e9, 5e9, 5e9]
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    m = sg.value_metrics(tmp_db, "MSFT", market_cap=2.8e12, total_debt=59e9,
                         cash=84e9, as_of=AS_OF)
    assert round(m["owner_fcf_ttm"] / 1e9, 1) == 101.4       # normalized, not 75.4
    assert round(m["owner_fcf_yield"], 4) == round(101.4e9 / 2.775e12, 4)
