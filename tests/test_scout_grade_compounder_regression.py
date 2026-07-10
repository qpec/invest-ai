"""Stage-1.5 regression (design 'Cost & testing'): a reinvesting compounder is no longer
dominated OR vetoed by a mature cash cow in the same sector. The compounder has high CapEx
(so its CONSERVATIVE owner-FCF is thin/negative) but modest D&A, high ROIC, and strong
revenue + per-share growth; the cash cow has low CapEx, flat revenue, lower ROIC.

Under the OLD grader the compounder would be suppressed (cash-destruction veto) or ranked
below the cow (owner-earnings penalized by growth CapEx). Under Stage-1.5 it grades, is
spared any cash-destruction veto, and its composite is competitive.
"""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
COLS = pd.to_datetime(["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])
SHARE_INDEX = pd.to_datetime(["2025-06-20", "2025-12-20", "2026-06-20"])


def _seed(conn, sym, *, revenue, ebit, ocf, capex, da, sbc, debt, cash, shares):
    inc = pd.DataFrame(index=["Total Revenue", "Cost Of Revenue", "Gross Profit",
                              "Operating Income", "EBITDA", "EBIT", "Net Income"],
                       columns=COLS, dtype=float)
    bal = pd.DataFrame(index=["Total Debt", "Cash And Cash Equivalents", "Total Assets",
                              "Current Assets", "Working Capital"], columns=COLS, dtype=float)
    cf = pd.DataFrame(index=["Operating Cash Flow", "Capital Expenditure",
                             "Stock Based Compensation", "Depreciation And Amortization"],
                      columns=COLS, dtype=float)
    for i, c in enumerate(COLS):                            # i=0 newest ... i=3 oldest
        rev = revenue[i]
        inc.loc["Total Revenue", c] = rev
        inc.loc["Gross Profit", c] = rev * 0.70
        inc.loc["Cost Of Revenue", c] = rev * 0.30
        inc.loc["Operating Income", c] = ebit[i]
        inc.loc["EBIT", c] = ebit[i]
        inc.loc["EBITDA", c] = ebit[i] * 1.2
        inc.loc["Net Income", c] = ebit[i] * 0.75
        bal.loc["Total Debt", c] = debt
        bal.loc["Cash And Cash Equivalents", c] = cash
        bal.loc["Total Assets", c] = rev * 2.5
        bal.loc["Current Assets", c] = rev * 1.5
        bal.loc["Working Capital", c] = rev * 0.15
        cf.loc["Operating Cash Flow", c] = ocf[i]
        cf.loc["Capital Expenditure", c] = -capex[i]
        cf.loc["Stock Based Compensation", c] = sbc
        cf.loc["Depreciation And Amortization", c] = da[i]
    store.store_statements(conn, sym, {"income": inc, "balance": bal, "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, sym, pd.Series(shares, index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")


def test_reinvesting_compounder_not_dominated_or_vetoed_by_cash_cow(tmp_db):
    # COMPOUNDER: strong revenue growth, high ROIC, HIGH CapEx (conservative owner-FCF thin),
    # modest D&A (normalized owner-FCF healthy), shrinking shares (per-share growth positive).
    _seed(tmp_db, "COMP",
          revenue=[80e9, 62e9, 48e9, 38e9], ebit=[36e9, 28e9, 22e9, 17e9],
          ocf=[34e9, 27e9, 21e9, 16e9], capex=[30e9, 24e9, 19e9, 15e9],   # near-OCF CapEx
          da=[6e9, 6e9, 6e9, 6e9], sbc=1e9, debt=10e9, cash=40e9,
          shares=[1.10e9, 1.05e9, 1.00e9])
    # CASH COW: flat revenue, lower ROIC, LOW CapEx (fat conservative owner-FCF), flat shares.
    _seed(tmp_db, "COW",
          revenue=[50e9, 50e9, 50e9, 50e9], ebit=[15e9, 15e9, 15e9, 15e9],
          ocf=[18e9, 18e9, 18e9, 18e9], capex=[2e9, 2e9, 2e9, 2e9],
          da=[2e9, 2e9, 2e9, 2e9], sbc=1e9, debt=10e9, cash=40e9,
          shares=[1.00e9, 1.00e9, 1.00e9])
    universe = pd.DataFrame({
        "symbol": ["COMP", "COW"],
        "sector": ["Technology", "Technology"],
        "industry": ["Software", "Software"],
        "market_cap": ["large_cap", "large_cap"],
    })
    market = {
        "COMP": {"market_cap": 6.0e11, "total_debt": 10e9, "cash": 40e9},
        "COW": {"market_cap": 6.0e11, "total_debt": 10e9, "cash": 40e9},
    }
    graded = sg.grade_universe(tmp_db, universe, market_data=market, as_of=AS_OF)
    by = {g.symbol: g for g in graded}
    # the compounder is NOT suppressed
    assert by["COMP"].grade not in ("VETOED", "INSUFFICIENT"), by["COMP"].note
    assert by["COMP"].composite is not None
    # and it is competitive: the growth pillar + normalized earnings lift it to at least the
    # cash cow's composite (the whole point of Stage-1.5 - it is no longer dominated).
    assert by["COMP"].composite >= by["COW"].composite
    # the compounder's Growth pillar strictly beats the flat cash cow's
    assert by["COMP"].g > by["COW"].g
