"""Stage-1 Durability pillar (design §1 Pillar D): net debt/EBITDA, owner-FCF self-funding,
SBC/revenue.

RF2 — durability_metrics must ALSO return the raw TTM ``ebitda`` and raw
``net_debt = total_debt - cash`` it computes internally (Task 9 feeds those REAL values
into veto_check, never a fabricated placeholder).
RF3 — cash-destruction veto is PER-PERIOD: expose ``owner_fcf_negative_all_periods`` =
owner-FCF < 0 in EVERY available period (computed from the archive, NOT the sign of the
TTM sum). Task 9's veto uses that boolean.
"""
from datetime import datetime, timezone

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed(conn, yf_statements, yf_series):
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_durability_metrics(tmp_db, yf_statements, yf_series):
    _seed(tmp_db, yf_statements, yf_series)
    d = sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert d is not None
    # net debt / EBITDA (TTM EBITDA = 37+36+35+34 = 142e9 ; net debt = debt(latest 59e9) - cash(84e9) = -25e9)
    assert round(d["net_debt_to_ebitda"], 4) == round(-25e9 / 142e9, 4)
    # self-funding: owner-FCF TTM positive -> True
    assert d["owner_fcf_positive"] is True
    # SBC / revenue TTM = 10.6e9 / 252e9  -> %
    assert round(d["sbc_to_revenue_pct"], 3) == round(100.0 * 10.6e9 / 252e9, 3)


def test_durability_metrics_exposes_raw_ebitda_and_net_debt(tmp_db, yf_statements, yf_series):
    """RF2 — veto_check (Task 9) needs the REAL raw EBITDA and net debt, not just the ratio."""
    _seed(tmp_db, yf_statements, yf_series)
    d = sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert d is not None
    assert d["ebitda"] == 37e9 + 36e9 + 35e9 + 34e9          # raw TTM EBITDA = 142e9
    assert d["net_debt"] == 59e9 - 84e9                       # raw net debt (latest period) = -25e9
    # the ratio is exactly the raw figures divided (no hidden re-derivation)
    assert d["net_debt_to_ebitda"] == d["net_debt"] / d["ebitda"]


def test_durability_owner_fcf_negative_all_periods_false_for_healthy_filer(
        tmp_db, yf_statements, yf_series):
    """RF3 — MSFT is owner-FCF positive in every recorded quarter, so the per-period
    cash-destruction flag is False."""
    _seed(tmp_db, yf_statements, yf_series)
    d = sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert d is not None
    assert d["owner_fcf_negative_all_periods"] is False


def test_durability_owner_fcf_negative_all_periods_per_period_not_ttm_sign(
        tmp_db, yf_statements, yf_series):
    """RF3 — the flag is per-period, NOT the sign of the TTM sum. Craft a cashflow archive
    whose TTM sum is POSITIVE yet whose owner-FCF is negative in EVERY period is impossible
    (a positive sum needs a positive period), so the discriminating case is the inverse:
    a filer whose TTM sum is NEGATIVE but that is owner-FCF-POSITIVE in one period -> flag
    must be False (a TTM-sign rule would wrongly report True)."""
    cash = yf_statements("msft_statements")["cashflow"]
    inc = yf_statements("msft_statements")["income"]
    bal = yf_statements("msft_statements")["balance"]
    # Periods (newest->oldest in the fixture): 2026-03-31, 2025-12-31, 2025-09-30, 2025-06-30.
    # Make three periods deeply cash-destructive and ONE (the newest) strongly positive so the
    # TTM SUM is negative but not-all-periods-negative.
    ocf = cash.loc["Operating Cash Flow"].copy()
    capex = cash.loc["Capital Expenditure"].copy()
    sbc = cash.loc["Stock Based Compensation"].copy()
    cols = list(cash.columns)                                 # Timestamps, newest first
    # newest period: big positive owner-FCF
    ocf[cols[0]], capex[cols[0]], sbc[cols[0]] = 40e9, -5e9, 1e9      # owner-FCF = +34e9
    for c in cols[1:]:                                        # three destructive periods
        ocf[c], capex[c], sbc[c] = 1e9, -20e9, 2e9           # owner-FCF = 1-20-2 = -21e9 each
    cash.loc["Operating Cash Flow"] = ocf
    cash.loc["Capital Expenditure"] = capex
    cash.loc["Stock Based Compensation"] = sbc
    store.store_statements(tmp_db, "MSFT", {"income": inc, "balance": bal, "cashflow": cash},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    d = sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert d is not None
    # TTM owner-FCF sum = 34e9 - 21e9*3 = -29e9 -> NEGATIVE
    assert d["owner_fcf_positive"] is False
    # but NOT negative in every period (the newest is +34e9) -> per-period flag False
    assert d["owner_fcf_negative_all_periods"] is False


def test_durability_owner_fcf_negative_all_periods_true_when_every_period_negative(
        tmp_db, yf_statements, yf_series):
    """RF3 — a serial cash-burner: owner-FCF negative in EVERY recorded period -> flag True."""
    cash = yf_statements("msft_statements")["cashflow"]
    inc = yf_statements("msft_statements")["income"]
    bal = yf_statements("msft_statements")["balance"]
    ocf = cash.loc["Operating Cash Flow"].copy()
    capex = cash.loc["Capital Expenditure"].copy()
    sbc = cash.loc["Stock Based Compensation"].copy()
    for c in list(cash.columns):
        ocf[c], capex[c], sbc[c] = 1e9, -10e9, 3e9           # owner-FCF = 1-10-3 = -12e9 each
    cash.loc["Operating Cash Flow"] = ocf
    cash.loc["Capital Expenditure"] = capex
    cash.loc["Stock Based Compensation"] = sbc
    store.store_statements(tmp_db, "MSFT", {"income": inc, "balance": bal, "cashflow": cash},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    d = sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert d is not None
    assert d["owner_fcf_positive"] is False
    assert d["owner_fcf_negative_all_periods"] is True


def test_durability_self_funding_uses_normalized(tmp_db, yf_statements, yf_series):
    """Stage-1.5: D's self-funding leg + the per-period cash-destruction flag are computed
    from the NORMALIZED per-period figure. A name that is conservative-negative but
    normalized-positive in a period is NOT flagged as destroying cash."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    # Heavy growth CapEx makes conservative owner-FCF negative every period, but modest D&A
    # makes NORMALIZED owner-FCF positive every period.
    for c in list(cf.columns):
        cf.loc["Operating Cash Flow", c] = 20e9
        cf.loc["Capital Expenditure", c] = -30e9            # conservative: 20-30-sbc < 0
        cf.loc["Stock Based Compensation", c] = 1e9
        cf.loc["Depreciation And Amortization", c] = 4e9    # normalized: 20-4-1 = +15e9 > 0
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    d = sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert d["owner_fcf_positive"] is True                   # normalized TTM > 0
    assert d["owner_fcf_negative_all_periods"] is False      # normalized positive every period


def test_durability_none_when_absent(tmp_db):
    assert sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF) is None
