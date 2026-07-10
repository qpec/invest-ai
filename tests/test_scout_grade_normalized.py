"""Stage-1.5 normalized owner earnings (design change 1): OCF - min(|CapEx|, D&A) - SBC,
per-period + TTM + per-share + margin, Scout discovery only. store.owner_fcf_ttm is
UNCHANGED and remains the conservative figure.

D&A source is the cashflow 'Depreciation And Amortization' row; when it is ABSENT for a
period the maintenance proxy falls back to |CapEx| so normalized collapses to conservative
(a safe degradation, never an error). The recorded msft_statements fixture has NO D&A row,
so for MSFT normalized == conservative; the discount is exercised by injecting a D&A row.
"""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed_msft(conn, yf_statements, yf_series):
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_normalized_equals_conservative_when_no_da_row(tmp_db, yf_statements, yf_series):
    """The fixture has no 'Depreciation And Amortization' row, so min(|CapEx|, D&A) falls
    back to |CapEx| and normalized owner-FCF == store.owner_fcf_ttm's conservative figure."""
    _seed_msft(tmp_db, yf_statements, yf_series)
    norm = sg.normalized_owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF)
    cons = store.owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF)
    assert norm is not None and cons is not None
    # conservative TTM owner_fcf = 75.4e9 (see test_scout_grade_value)
    assert round(norm.owner_fcf_ttm / 1e9, 1) == 75.4
    assert round(norm.owner_fcf_ttm, 2) == round(cons.value.owner_fcf_ttm, 2)
    # margin + per-share also match the conservative figure in the D&A-absent case
    assert round(norm.owner_fcf_margin_ttm, 8) == round(cons.value.owner_fcf_margin_ttm, 8)
    assert round(norm.owner_fcf_per_share_ttm, 6) == round(cons.value.owner_fcf_per_share_ttm, 6)


def test_normalized_discounts_capex_to_da_when_da_present(tmp_db, yf_statements, yf_series):
    """With a D&A row SMALLER than |CapEx|, maintenance CapEx = D&A, so normalized owner-FCF
    is HIGHER than conservative (growth CapEx is no longer fully subtracted)."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    # |CapEx| per period = 13,12,11,10 e9. Add D&A = 5e9 each < |CapEx|, so min = 5e9.
    cf.loc["Depreciation And Amortization"] = [5e9, 5e9, 5e9, 5e9]
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    norm = sg.normalized_owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF)
    # conservative TTM = sum(OCF) - sum(|CapEx|) - sum(SBC)
    #   = (36+34+32+30) - (13+12+11+10) - (2.8+2.7+2.6+2.5) = 132 - 46 - 10.6 = 75.4e9
    # normalized TTM = sum(OCF) - sum(min(|CapEx|,D&A)) - sum(SBC)
    #   = 132 - (5*4) - 10.6 = 132 - 20 - 10.6 = 101.4e9
    assert round(norm.owner_fcf_ttm / 1e9, 1) == 101.4


def test_normalized_per_period_fallback_is_per_period(tmp_db, yf_statements, yf_series):
    """A D&A row present in SOME periods and absent (NaN) in others: each period uses its own
    maintenance proxy - D&A where present, |CapEx| where absent."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    cols = list(cf.columns)                       # newest first: 2026-03-31 ... 2025-06-30
    # D&A present only in the two newest periods (5e9), NaN in the two oldest.
    cf.loc["Depreciation And Amortization"] = [5e9, 5e9, float("nan"), float("nan")]
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    norm = sg.normalized_owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF)
    # newest two: min(13,5)=5 and min(12,5)=5 ; oldest two fall back to |CapEx| 11 and 10.
    # maintenance sum = 5+5+11+10 = 31e9 ; OCF sum 132e9 ; SBC 10.6e9
    #   normalized = 132 - 31 - 10.6 = 90.4e9
    assert round(norm.owner_fcf_ttm / 1e9, 1) == 90.4


def test_normalized_none_when_not_computable(tmp_db, yf_series):
    # no statements -> not computable -> None (matches store.owner_fcf_ttm's contract)
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    assert sg.normalized_owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF) is None
