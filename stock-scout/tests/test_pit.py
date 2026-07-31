"""Offline tests for the EDGAR point-in-time layer (RECONSTRUCTION.md §5.8, §5.9, §3.6):
filed-date discipline, tag fallback chains, YTD->quarter derivation (incl. a broken
fiscal year exercising the +/-365d prior-YTD window and Q4 = FY minus the 9-month YTD),
multi-class shares, debt composition, the weekly price grid, and one end-to-end
synthetic-facts -> as_of_bundle -> scoring.score_universe integration. Synthetic
companyfacts JSON only — no network, no real caches."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import bt_fetch
import pit
import scoring

META = {"name": "Synthetic Corp", "sector": "Information Technology", "industry": "Software"}


def dfact(start, end, val, filed):
    """One duration (flow) companyfacts unit entry."""
    return {"start": start, "end": end, "val": val, "form": "10-Q", "filed": filed}


def ifact(end, val, filed):
    """One instant (balance / dei shares) companyfacts unit entry."""
    return {"end": end, "val": val, "form": "10-Q", "filed": filed}


def facts_of(gaap=None, shares=None):
    """Synthetic companyfacts payload in the raw SEC shape (§3.6)."""
    payload = {"cik": 123, "entityName": "Synthetic Corp", "facts": {}}
    if gaap:
        payload["facts"]["us-gaap"] = {
            tag: {"label": tag, "units": {"USD": entries}} for tag, entries in gaap.items()}
    if shares is not None:
        payload["facts"]["dei"] = {
            "EntityCommonStockSharesOutstanding": {"label": "shares",
                                                   "units": {"shares": shares}}}
    return payload


def _rev_quarters(gaap, as_of="2025-03-01"):
    bundle = pit.as_of_bundle(facts_of(gaap=gaap), "SYN", META, as_of, {})
    return {end: payload["Total Revenue"]
            for end, payload in bundle["quarterly"]["income"].items()
            if "Total Revenue" in payload}


# ------------------------------------------------------ filed-date discipline (§5.9)

def test_fact_filed_after_as_of_is_invisible():
    facts = facts_of(gaap={"Revenues": [
        dfact("2024-01-01", "2024-12-31", 100.0, "2025-02-15"),
        dfact("2024-01-01", "2024-12-31", 120.0, "2025-06-01")]})   # later restatement
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-03-01", {})
    assert bundle["annual"]["income"]["2024-12-31"]["Total Revenue"] == 100.0
    # Before the first filing nothing is knowable -> no bundle at all.
    assert pit.as_of_bundle(facts, "SYN", META, "2025-01-01", {}) is None


def test_latest_filed_value_wins_once_the_restatement_is_visible():
    facts = facts_of(gaap={"Revenues": [
        dfact("2024-01-01", "2024-12-31", 100.0, "2025-02-15"),
        dfact("2024-01-01", "2024-12-31", 120.0, "2025-06-01")]})
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-07-01", {})
    assert bundle["annual"]["income"]["2024-12-31"]["Total Revenue"] == 120.0


# ------------------------------------------------------ Revenues chain fallback (§5.9)

def test_revenues_chain_fallback_for_adbe_style_filers():
    facts = facts_of(gaap={"Revenues": [dfact("2024-01-01", "2024-12-31", 400.0, "2025-02-01")]})
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-03-01", {})
    assert bundle["annual"]["income"]["2024-12-31"]["Total Revenue"] == 400.0


def test_revenue_chain_priority_prefers_the_contract_tag():
    facts = facts_of(gaap={
        "Revenues": [dfact("2024-01-01", "2024-12-31", 400.0, "2025-02-01")],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            dfact("2024-01-01", "2024-12-31", 500.0, "2025-02-01")]})
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-03-01", {})
    assert bundle["annual"]["income"]["2024-12-31"]["Total Revenue"] == 500.0


# ------------------------------------------------- YTD -> quarter derivation (§5.9)

def test_ytd_subtraction_and_q4_from_fy_minus_prior_ytd():
    # Q4 is implemented as FY minus the 9-month YTD (one subtraction through the same
    # prior-YTD rule), not FY-minus-3-quarters — documented in pit.quarterly_flows.
    gaap = {"Revenues": [
        dfact("2024-01-01", "2024-03-31", 10.0, "2024-05-01"),   # true quarter (<=100d)
        dfact("2024-01-01", "2024-06-30", 25.0, "2024-08-01"),   # 6M YTD
        dfact("2024-01-01", "2024-09-30", 45.0, "2024-11-01"),   # 9M YTD
        dfact("2024-01-01", "2024-12-31", 70.0, "2025-02-01")]}  # FY
    assert _rev_quarters(gaap) == {"2024-03-31": 10.0, "2024-06-30": 15.0,
                                   "2024-09-30": 20.0, "2024-12-31": 25.0}


def test_prior_year_ytd_never_masquerades_as_a_quarter():
    gaap = {"Revenues": [
        dfact("2023-01-01", "2023-06-30", 999.0, "2023-08-01"),   # prior-year 6M YTD
        dfact("2024-01-01", "2024-06-30", 25.0, "2024-08-01"),    # this-year 6M YTD
        dfact("2024-01-01", "2024-12-31", 70.0, "2025-02-01")]}   # annual anchor
    # The only prior candidate ends 366 days earlier -> derived span > 100d -> refused.
    assert _rev_quarters(gaap) == {}


def test_broken_fiscal_year_prior_ytd_matches_within_365d_window():
    # Fiscal-calendar switch: the transition cumulative starts 2023-08-01 while the last
    # quarter filed under the old calendar started 2023-07-01 — a 31-day start drift an
    # exact-start matcher would refuse; the +/-365d window (msg 44) accepts it and the
    # <=100d derived-span guard confirms the result is a quarter.
    gaap = {"Revenues": [
        dfact("2023-07-01", "2023-09-30", 30.0, "2023-11-01"),    # true quarter, old calendar
        dfact("2023-08-01", "2023-12-31", 75.0, "2024-03-01"),    # transition stub (152d)
        dfact("2024-01-01", "2024-12-31", 400.0, "2025-02-01")]}  # annual anchor
    quarters = _rev_quarters(gaap)
    assert quarters["2023-09-30"] == 30.0
    assert quarters["2023-12-31"] == 75.0 - 30.0


# ------------------------------------------------------- multi-class shares (§5.9)

def test_multi_class_shares_summed_per_filed_date():
    shares = [
        ifact("2024-01-25", 100e6, "2024-02-01"), ifact("2024-01-25", 50e6, "2024-02-01"),
        ifact("2024-04-25", 100e6, "2024-05-01"), ifact("2024-04-25", 55e6, "2024-05-01"),
        ifact("2025-04-25", 60e6, "2025-05-01")]   # filed after as_of -> invisible
    series = pit.shares_series(facts_of(shares=shares), "2025-03-01")
    assert series == [["2024-01-25", 150e6], ["2024-04-25", 155e6]]
    assert pit.shares_at(series, "2024-02-01") == 150e6
    assert pit.shares_at(series, "2024-01-01") is None


def test_inconsistent_share_classes_empty_the_series():
    shares = [ifact("2024-01-25", 100e6, "2024-02-01"),
              ifact("2024-01-26", 50e6, "2024-02-01")]   # two measurement dates, one filing
    facts = facts_of(gaap={"Revenues": [dfact("2024-01-01", "2024-12-31", 100.0, "2025-02-01")]},
                     shares=shares)
    assert pit.shares_series(facts, "2025-03-01") == []
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-03-01",
                              {"SYN": {"2025-02-28": 10.0}})
    assert bundle["shares_series"] == []
    assert bundle["market_cap"] is None   # no shares -> no PIT market cap


# ------------------------------------------------------- debt composition (§5.9)

def _debt_of(gaap_extra):
    gaap = {"Revenues": [dfact("2024-01-01", "2024-12-31", 100.0, "2025-02-01")], **gaap_extra}
    bundle = pit.as_of_bundle(facts_of(gaap=gaap), "SYN", META, "2025-03-01", {})
    return bundle["quarterly"]["balance"].get("2024-12-31", {}).get("Total Debt")


def test_debt_composition_rule():
    filed = "2025-02-01"
    # LongTermDebt wins outright over the pieces.
    assert _debt_of({"LongTermDebt": [ifact("2024-12-31", 50.0, filed)],
                     "LongTermDebtNoncurrent": [ifact("2024-12-31", 99.0, filed)]}) == 50.0
    # Composed: noncurrent + current + short-term borrowings.
    assert _debt_of({"LongTermDebtNoncurrent": [ifact("2024-12-31", 80.0, filed)],
                     "LongTermDebtCurrent": [ifact("2024-12-31", 20.0, filed)],
                     "ShortTermBorrowings": [ifact("2024-12-31", 5.0, filed)]}) == 105.0
    # A single long-term piece: the missing legs count as 0.
    assert _debt_of({"LongTermDebtNoncurrent": [ifact("2024-12-31", 80.0, filed)]}) == 80.0
    # Short-term borrowings alone never make Total Debt (§5.9 "else None").
    assert _debt_of({"ShortTermBorrowings": [ifact("2024-12-31", 5.0, filed)]}) is None


# ------------------------------------------------- weekly price grid (§5.9, §3.6)

def test_price_at_and_market_cap_from_weekly_grid():
    prices = {"SYN": {"2025-02-14": 10.0, "2025-02-21": 11.0, "2025-02-28": 12.0}}
    assert pit.price_at(prices, "SYN", "2025-02-23") == 11.0
    assert pit.price_at(prices, "SYN", "2025-02-14") == 10.0
    assert pit.price_at(prices, "SYN", "2025-02-01") is None
    assert pit.price_at(prices, "MISSING", "2025-02-23") is None
    facts = facts_of(gaap={"Revenues": [dfact("2024-01-01", "2024-12-31", 100.0, "2025-02-01")]},
                     shares=[ifact("2025-01-15", 1_000_000.0, "2025-01-20")])
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-02-23", prices)
    assert bundle["market_cap"] == pytest.approx(1_000_000.0 * 11.0)
    assert bundle["price"] == 11.0


def test_quarter_ends_take_the_last_weekly_bar_per_calendar_quarter():
    spy = {"2024-03-22": 1.0, "2024-03-28": 1.0, "2024-04-05": 1.0,
           "2024-06-28": 1.0, "2024-07-03": 1.0, "2024-09-27": 1.0}
    assert pit.quarter_ends(spy, "2024-01-01", "2024-12-31") == \
        ["2024-03-28", "2024-06-28", "2024-09-27"]
    assert pit.quarter_ends(spy, "2024-04-01", "2024-06-30") == ["2024-06-28"]


# ------------------------------------------------------ bt_fetch pure helpers (§5.8)

def test_bt_fetch_cik_map_facts_url_and_user_agent():
    raw = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
           "1": {"cik_str": 796343, "ticker": "adbe", "title": "ADOBE INC."}}
    ciks = bt_fetch.cik_map(raw)
    assert ciks == {"AAPL": 320193, "ADBE": 796343}
    assert bt_fetch.FACTS_URL.format(cik=ciks["ADBE"]).endswith("CIK0000796343.json")
    assert bt_fetch.USER_AGENT == "stock-agentcy scout (y.n.hanekamp@gmail.com)"
    assert bt_fetch.EDGAR_SPACING_SECONDS >= 0.15


def test_bt_fetch_prices_payload_and_period_ladder():
    idx = pd.to_datetime(["2019-12-27", "2020-01-03", "2020-01-10"], utc=True)
    frame = pd.DataFrame({"adj_close": [1.0, 2.0, 3.0], "currency": "USD"}, index=idx)
    assert bt_fetch.prices_payload(frame, "2020-01-01") == {"2020-01-03": 2.0,
                                                            "2020-01-10": 3.0}
    assert bt_fetch.yf_period("2020-01-01", today=date(2026, 7, 31)) == "10y"
    assert bt_fetch.yf_period("2026-01-01", today=date(2026, 7, 31)) == "1y"
    assert bt_fetch.yf_period("2010-01-01", today=date(2026, 7, 31)) == "max"


# ---------------------------------------- integration: facts -> bundle -> scoring

def _year_flows(year, q1, q2, q3, q4, filed_fy):
    start = f"{year}-01-01"
    return [dfact(start, f"{year}-03-31", q1, f"{year}-05-01"),
            dfact(start, f"{year}-06-30", q1 + q2, f"{year}-08-01"),
            dfact(start, f"{year}-09-30", q1 + q2 + q3, f"{year}-11-01"),
            dfact(start, f"{year}-12-31", q1 + q2 + q3 + q4, filed_fy)]


def _integration_facts():
    fy24, fy23 = "2025-02-01", "2024-02-01"
    gaap = {
        "Revenues": _year_flows(2024, 100, 100, 100, 100, fy24)
        + [dfact("2023-01-01", "2023-12-31", 360.0, fy23)],
        "OperatingIncomeLoss": _year_flows(2024, 20, 20, 20, 20, fy24)
        + [dfact("2023-01-01", "2023-12-31", 70.0, fy23)],
        "GrossProfit": _year_flows(2024, 60, 60, 60, 60, fy24)
        + [dfact("2023-01-01", "2023-12-31", 220.0, fy23)],
        "NetIncomeLoss": _year_flows(2024, 15, 15, 15, 15, fy24)
        + [dfact("2023-01-01", "2023-12-31", 55.0, fy23)],
        "ProfitLoss": _year_flows(2024, 16, 16, 16, 16, fy24)
        + [dfact("2023-01-01", "2023-12-31", 58.0, fy23)],
        "NetCashProvidedByUsedInOperatingActivities": _year_flows(2024, 30, 30, 30, 30, fy24)
        + [dfact("2023-01-01", "2023-12-31", 100.0, fy23)],
        "PaymentsToAcquirePropertyPlantAndEquipment": _year_flows(2024, 5, 5, 5, 5, fy24)
        + [dfact("2023-01-01", "2023-12-31", 18.0, fy23)],
        "ShareBasedCompensation": _year_flows(2024, 2, 2, 2, 2, fy24)
        + [dfact("2023-01-01", "2023-12-31", 8.0, fy23)],
        "DepreciationDepletionAndAmortization": _year_flows(2024, 6, 6, 6, 6, fy24)
        + [dfact("2023-01-01", "2023-12-31", 20.0, fy23)],
        "LongTermDebt": [ifact("2023-12-31", 40.0, fy23), ifact("2024-12-31", 50.0, fy24)],
        "CashAndCashEquivalentsAtCarryingValue": [ifact("2023-12-31", 80.0, fy23),
                                                  ifact("2024-12-31", 100.0, fy24)],
        "Assets": [ifact("2023-12-31", 900.0, fy23), ifact("2024-12-31", 1000.0, fy24)],
        "AssetsCurrent": [ifact("2023-12-31", 350.0, fy23), ifact("2024-12-31", 400.0, fy24)],
        "LiabilitiesCurrent": [ifact("2023-12-31", 180.0, fy23),
                               ifact("2024-12-31", 200.0, fy24)],
        "StockholdersEquity": [ifact("2023-12-31", 450.0, fy23),
                               ifact("2024-12-31", 500.0, fy24)],
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
            ifact("2023-12-31", 458.0, fy23), ifact("2024-12-31", 510.0, fy24)],
    }
    shares = [ifact("2023-01-10", 1_000_000.0, "2023-01-15"),
              ifact("2024-01-15", 1_000_000.0, "2024-01-20"),
              ifact("2025-01-15", 1_010_000.0, "2025-01-20")]
    return facts_of(gaap=gaap, shares=shares)


def test_integration_synthetic_facts_score_end_to_end():
    prices = {"SYN": {"2025-02-14": 45.0, "2025-02-21": 50.0}}
    bundle = pit.as_of_bundle(_integration_facts(), "SYN", META, "2025-03-01", prices)
    assert bundle is not None
    assert bundle["market_cap"] == pytest.approx(1_010_000.0 * 50.0)
    # EBITDA = EBIT + D&A per matched period, both sections (§5.9).
    assert bundle["annual"]["income"]["2024-12-31"]["EBITDA"] == pytest.approx(80.0 + 24.0)
    assert bundle["quarterly"]["income"]["2024-06-30"]["EBITDA"] == pytest.approx(20.0 + 6.0)
    # Yahoo sign convention: capex negative (§5.9 sign flip).
    assert bundle["quarterly"]["cashflow"]["2024-03-31"]["Capital Expenditure"] == -5.0

    rows = scoring.score_universe([bundle])
    assert len(rows) == 1
    row = rows[0]
    assert row["grade"] in set("ABCDF")            # graded, not INSUFFICIENT/VETOED
    assert not row["veto"]["vetoed"]
    assert row["composite"] is not None and row["composite"] > 0
    assert row["quality_score"] is not None
    assert row["ttm"] == {"quarters": 4, "through": "2024-12-31", "basis": "quarterly"}
    assert row["tier"] == "Core"
    assert row["ev"]["yahoo"] is None              # no Yahoo EV in the PIT world
    assert all(flag["code"] != "SHARE_CLASS" for flag in row["flags"])
