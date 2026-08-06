"""Offline tests for the EDGAR point-in-time layer (RECONSTRUCTION.md §5.8, §5.9, §3.6):
filed-date discipline, tag fallback chains, YTD->quarter derivation (incl. a broken
fiscal year exercising the +/-365d prior-YTD window, the refusal of a discrete-quarter
subtrahend, and Q4 = FY minus the 9-month YTD), multi-class shares (empty trend series +
market-cap fallback), raw-vs-adjusted price selection, the declared price BASIS (the
envelope round trip, both legacy shapes, the refusal of an unknown declaration, and a
synthetic 10:1 split between the tick and today proving the today-basis market cap lands
on the true historical dollar figure while the share-trend leg is untouched), the
reversible filename sanitization, and one end-to-end synthetic-facts -> as_of_bundle ->
scoring.score_universe integration. Synthetic companyfacts JSON only — no network, no
real caches."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import bt_fetch
import pit
import populate
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
    # Fiscal-calendar switch: the new-calendar cumulative starts 2023-08-01 while the last
    # CUMULATIVE filed under the old calendar started 2023-07-01 — a 31-day start drift an
    # exact-start matcher would refuse; the +/-365d window (msg 44) accepts it because the
    # candidate is itself a cumulative (183 days), and the <=100d derived-span guard
    # confirms the result is a quarter.
    gaap = {"Revenues": [
        dfact("2023-07-01", "2023-12-31", 60.0, "2024-02-01"),    # old-calendar 6M cumulative
        dfact("2023-08-01", "2024-03-31", 100.0, "2024-05-01"),   # new-calendar 8M cumulative
        dfact("2024-01-01", "2024-12-31", 400.0, "2025-02-01")]}  # annual anchor
    assert _rev_quarters(gaap) == {"2024-03-31": pytest.approx(40.0)}


def test_a_discrete_quarter_is_never_the_ytd_subtrahend():
    # The 6M YTD is missing (filers do skip cumulatives) but a DISCRETE Q2 is present.
    # Subtracting it from the 9M YTD yields Q1+Q3 booked as Q3 (45 - 12 = 33 instead of
    # the true 23) — the ±365d start window alone accepts that (91-day start drift), so
    # the subtrahend must also be a cumulative. Q3 is then simply not derivable, which is
    # the honest outcome; Q4 = FY - 9M still lands through the same-start rule.
    gaap = {"Revenues": [
        dfact("2024-01-01", "2024-03-31", 10.0, "2024-05-01"),   # Q1, doubles as the 3M YTD
        dfact("2024-04-01", "2024-06-30", 12.0, "2024-08-01"),   # DISCRETE Q2
        dfact("2024-01-01", "2024-09-30", 45.0, "2024-11-01"),   # 9M YTD (no 6M YTD filed)
        dfact("2024-01-01", "2024-12-31", 70.0, "2025-02-01")]}  # FY
    quarters = _rev_quarters(gaap)
    assert "2024-09-30" not in quarters
    assert quarters == {"2024-03-31": 10.0, "2024-06-30": 12.0,
                        "2024-12-31": pytest.approx(25.0)}


def test_a_52_53_week_start_wobble_still_counts_as_the_same_ytd_start():
    # 52/53-week filers restate the fiscal-year start by a day or two; that must not cost
    # them their quarters, while staying orders of magnitude below a quarter boundary.
    gaap = {"Revenues": [
        dfact("2024-01-01", "2024-06-30", 25.0, "2024-08-01"),    # 6M YTD
        dfact("2024-01-03", "2024-09-30", 45.0, "2024-11-01"),    # 9M YTD, start 2 days off
        dfact("2024-01-01", "2024-12-31", 70.0, "2025-02-01")]}
    assert _rev_quarters(gaap)["2024-09-30"] == pytest.approx(20.0)


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


def test_inconsistent_share_classes_empty_the_series_but_keep_a_market_cap():
    # The SERIES stays empty (msg 44: the M share-trend leg goes neutral) — but the name
    # must still get a market cap from the best count at as_of, otherwise scoring
    # integrity-suspends it as INSUFFICIENT at every tick and it silently disappears from
    # the backtest universe. (This assertion used to demand market_cap is None.)
    shares = [ifact("2024-01-25", 100e6, "2024-02-01"),
              ifact("2024-01-26", 50e6, "2024-02-01")]   # two measurement dates, one filing
    facts = facts_of(gaap={"Revenues": [dfact("2024-01-01", "2024-12-31", 100.0, "2025-02-01")]},
                     shares=shares)
    assert pit.shares_series(facts, "2025-03-01") == []
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-03-01",
                              {"SYN": {"2025-02-28": {"close": 10.0, "adj_close": 5.0}}})
    assert bundle["shares_series"] == []
    assert bundle["shares_basis"] == "fallback-sum"
    assert bundle["market_cap"] == pytest.approx(150e6 * 10.0)   # summed classes x RAW close


def test_shares_fallback_paths_and_filed_date_discipline():
    # Class rows measured days apart are one cover page -> summed.
    close = facts_of(shares=[ifact("2025-01-14", 700e3, "2025-01-20"),
                             ifact("2025-01-15", 310e3, "2025-01-20")])
    assert pit.shares_fallback(close, "2025-03-01") == (1_010e3, "fallback-sum")
    # Rows half a year apart cannot be one company-wide count -> the largest class stands in.
    far = facts_of(shares=[ifact("2024-06-30", 900e3, "2025-01-20"),
                           ifact("2025-01-15", 1_000e3, "2025-01-20")])
    assert pit.shares_fallback(far, "2025-03-01") == (1_000e3, "fallback-largest")
    # Filed-date discipline holds for the fallback too, and nothing knowable -> (None, None).
    assert pit.shares_fallback(far, "2025-01-01") == (None, None)
    assert pit.shares_fallback(facts_of(), "2025-03-01") == (None, None)


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
    # Legacy float bars (grids written before the split-safe format) still load: the one
    # value stands for both fields — degraded, and flagged as such.
    prices = {"SYN": {"2025-02-14": 10.0, "2025-02-21": 11.0, "2025-02-28": 12.0}}
    assert pit.price_at(prices, "SYN", "2025-02-23") == 11.0
    assert pit.price_at(prices, "SYN", "2025-02-23", "adj_close") == 11.0
    assert pit.price_at(prices, "SYN", "2025-02-14") == 10.0
    assert pit.price_at(prices, "SYN", "2025-02-01") is None
    assert pit.price_at(prices, "MISSING", "2025-02-23") is None
    assert pit.grid_is_degraded(prices["SYN"])
    facts = facts_of(gaap={"Revenues": [dfact("2024-01-01", "2024-12-31", 100.0, "2025-02-01")]},
                     shares=[ifact("2025-01-15", 1_000_000.0, "2025-01-20")])
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-02-23", prices)
    assert bundle["market_cap"] == pytest.approx(1_000_000.0 * 11.0)
    assert bundle["price"] == 11.0
    assert bundle["shares_basis"] == "series"


def test_price_at_selects_raw_or_adjusted_and_a_missing_field_falls_back():
    prices = {"SYN": {"2025-02-14": {"close": 100.0, "adj_close": 50.0},
                      "2025-02-21": {"close": 110.0, "adj_close": 55.0}},
              "HALF": {"2025-02-21": {"adj_close": 55.0}}}      # adjusted-only bar
    assert pit.price_at(prices, "SYN", "2025-02-23") == 110.0         # default = RAW close
    assert pit.price_at(prices, "SYN", "2025-02-23", "close") == 110.0
    assert pit.price_at(prices, "SYN", "2025-02-23", "adj_close") == 55.0
    assert pit.price_at(prices, "HALF", "2025-02-23", "close") == 55.0   # falls back
    assert not pit.grid_is_degraded(prices["SYN"])
    assert pit.grid_is_degraded(prices["HALF"])     # adjusted-only bar = degraded
    assert pit.bar_value({"close": 3.0, "adj_close": 1.5}, "adj_close") == 1.5
    assert pit.bar_value(7.0, "close") == pit.bar_value(7.0, "adj_close") == 7.0
    assert pit.bar_value(None) is None


def test_a_later_split_cannot_rewrite_the_historical_market_cap():
    # A 2:1 split AFTER the tick retroactively halves every earlier adj_close; the raw
    # close is untouched. dei share counts are as-reported, so the market cap must be built
    # on the raw close — otherwise every historical tick silently imports the future
    # (contaminating V, the entry gate, own EV, WACC and MoS).
    facts = facts_of(gaap={"Revenues": [dfact("2024-01-01", "2024-12-31", 100.0, "2025-02-01")]},
                     shares=[ifact("2025-01-15", 1_000_000.0, "2025-01-20")])
    before = {"SYN": {"2025-02-14": {"close": 100.0, "adj_close": 100.0},
                      "2025-02-21": {"close": 110.0, "adj_close": 110.0}}}
    after = {"SYN": {"2025-02-14": {"close": 100.0, "adj_close": 50.0},   # split rescaled
                     "2025-02-21": {"close": 110.0, "adj_close": 55.0}}}
    b0 = pit.as_of_bundle(facts, "SYN", META, "2025-02-23", before)
    b1 = pit.as_of_bundle(facts, "SYN", META, "2025-02-23", after)
    assert b0["market_cap"] == b1["market_cap"] == pytest.approx(1_000_000.0 * 110.0)
    assert b0["price"] == b1["price"] == 110.0
    # The adjusted grid is exactly the contamination the raw close avoids.
    assert pit.price_at(after, "SYN", "2025-02-23", "adj_close") == 55.0


# ------------------------------------ price basis: basis-aware market cap (§3.6, §5.9)
#
# One synthetic 10:1 split on 2026-06-10, AFTER the 2026-02-23 tick (NVDA's actual shape).
# The numbers are chosen so the true dollar market cap at the tick is unambiguous:
#   as-reported dei count at the tick     2,000,000     x  as-traded close  $500  = $1.0bn
#   the same count in today's terms      20,000,000     x  today-basis close $50  = $1.0bn
# A today-basis close read as raw gives $0.1bn — wrong by exactly the split factor.
TICK = "2026-02-23"
SPLIT_DAY, SPLIT_RATIO = "2026-06-10", 10.0
TRUE_MARKET_CAP = 1_000_000_000.0
RAW_GRID = {"SYN": {"2026-02-13": {"close": 480.0, "adj_close": 480.0},
                    "2026-02-20": {"close": 500.0, "adj_close": 500.0}}}
TODAY_GRID = {"SYN": {"2026-02-13": {"close": 48.0, "adj_close": 48.0},
                      "2026-02-20": {"close": 50.0, "adj_close": 50.0}}}


def _splitter_facts():
    """One annual period (so a bundle exists) plus two dei observations a year apart, both
    as-reported in PRE-split terms — 1.98m -> 2.00m shares, ~+1%/yr."""
    return facts_of(
        gaap={"Revenues": [dfact("2025-01-01", "2025-12-31", 400.0, "2026-02-01")]},
        shares=[ifact("2025-01-15", 1_980_000.0, "2025-01-20"),
                ifact("2026-01-15", 2_000_000.0, "2026-01-20")])


def test_price_file_declares_its_basis_and_the_loader_surfaces_it():
    bars = {"2026-02-20": {"close": 50.0, "adj_close": 50.0}}
    payload = pit.price_file("SYN", bars, {SPLIT_DAY: SPLIT_RATIO},
                             pit.BASIS_SPLIT_ADJUSTED_TODAY)
    assert payload[pit.BASIS_KEY] == "split_adjusted_today"
    loaded = pit.load_price_file(payload)
    assert loaded == ("SYN", bars, {SPLIT_DAY: SPLIT_RATIO})   # still exactly a 3-tuple ...
    symbol, grid, events = loaded                              # ... and unpacks as one
    assert (symbol, grid, events) == ("SYN", bars, {SPLIT_DAY: SPLIT_RATIO})
    assert loaded.price_basis == pit.BASIS_SPLIT_ADJUSTED_TODAY
    assert pit.price_file("SYN", bars)[pit.BASIS_KEY] == pit.BASIS_RAW   # written out always


def test_both_legacy_price_file_shapes_still_load_and_mean_raw():
    # Absence of the field is not "unknown": every cache written before it held as-traded
    # closes, so it keeps its original meaning and no stored file changes value.
    bars = {"2026-02-13": 48.0, "2026-02-20": 50.0}          # bare date-keyed floats
    loaded = pit.load_price_file(dict(bars))
    assert loaded == (None, bars, {}) and loaded.price_basis == pit.BASIS_RAW
    older = pit.load_price_file({"symbol": "SYN", "bars": bars,
                                 "splits": {SPLIT_DAY: SPLIT_RATIO}})   # pre-basis envelope
    assert older == ("SYN", bars, {SPLIT_DAY: SPLIT_RATIO})
    assert older.price_basis == pit.BASIS_RAW
    annotated = pit.load_price_file(dict(bars, symbol="SYN", splits={}, price_basis="raw"))
    assert annotated == ("SYN", bars, {})      # annotations never leak into the bars
    assert pit.load_price_file("not a payload") == (None, {}, {})


def test_an_unknown_basis_declaration_is_refused_rather_than_defaulted():
    # Guessing what an unrecognized declaration means is precisely the silent assumption
    # this layer removes — the cost of guessing wrong is a whole split factor.
    with pytest.raises(ValueError):
        pit.price_file("SYN", {}, {}, "adjusted")
    with pytest.raises(ValueError):
        pit.load_price_file({"symbol": "SYN", "bars": {}, "price_basis": "close"})
    with pytest.raises(ValueError):
        pit.as_of_bundle(_splitter_facts(), "SYN", META, TICK, RAW_GRID, None, "yahoo")
    assert pit.basis_for(None) == pit.BASIS_RAW
    assert pit.basis_for({"OTHER": pit.BASIS_SPLIT_ADJUSTED_TODAY}, "SYN") == pit.BASIS_RAW


def test_raw_basis_market_cap_is_untouched_by_a_later_split():
    # (i) The raw path is exactly what it always was: as-reported shares x as-traded close.
    # The split history is irrelevant to it — supplied or not, the figure does not move.
    facts = _splitter_facts()
    for supplied in ({}, {"SYN": {SPLIT_DAY: SPLIT_RATIO}}):
        bundle = pit.as_of_bundle(facts, "SYN", META, TICK, RAW_GRID, supplied)
        assert bundle["market_cap"] == pytest.approx(TRUE_MARKET_CAP)
        assert bundle["market_cap_basis"] == pit.BASIS_RAW
        assert bundle["market_cap_split_unadjusted"] is False
    explicit = pit.as_of_bundle(facts, "SYN", META, TICK, RAW_GRID, None, pit.BASIS_RAW)
    assert explicit["market_cap"] == pytest.approx(TRUE_MARKET_CAP)   # declared == default


def test_today_basis_market_cap_equals_the_true_historical_dollar_figure():
    # (ii) 2,000,000 as-reported shares restated 10:1 = 20,000,000, times the $50 close the
    # vendor states in today's share terms = the $1.0bn the market actually put on the
    # company on 2026-02-20. The future split factor multiplies the count and divides the
    # close, so it cancels: no future information survives, only the units agree.
    facts = _splitter_facts()
    splits = {"SYN": {SPLIT_DAY: SPLIT_RATIO}}
    bundle = pit.as_of_bundle(facts, "SYN", META, TICK, TODAY_GRID, splits,
                              pit.BASIS_SPLIT_ADJUSTED_TODAY)
    assert bundle["market_cap"] == pytest.approx(TRUE_MARKET_CAP)
    assert bundle["market_cap_basis"] == pit.BASIS_SPLIT_ADJUSTED_TODAY
    assert bundle["market_cap_split_unadjusted"] is False
    assert bundle["market_cap"] == pytest.approx(
        pit.as_of_bundle(facts, "SYN", META, TICK, RAW_GRID, splits)["market_cap"])
    # Reading that same grid as raw is the failure the declaration prevents: $0.1bn.
    misread = pit.as_of_bundle(facts, "SYN", META, TICK, TODAY_GRID, splits)
    assert misread["market_cap"] == pytest.approx(TRUE_MARKET_CAP / SPLIT_RATIO)
    # A {symbol: basis} map declares it just as well (a mixed-provider cache).
    per_symbol = pit.as_of_bundle(facts, "SYN", META, TICK, TODAY_GRID, splits,
                                  {"SYN": pit.BASIS_SPLIT_ADJUSTED_TODAY})
    assert per_symbol["market_cap"] == pytest.approx(TRUE_MARKET_CAP)


def test_today_basis_without_split_history_is_flagged_not_silently_wrong():
    # (iii) No events to restate by -> the count stays as-reported against a today-basis
    # close, so the figure IS wrong by the split factor. It is published with the flag up
    # rather than silently: an honest "unverified" beats a confident $0.1bn.
    facts = _splitter_facts()
    bundle = pit.as_of_bundle(facts, "SYN", META, TICK, TODAY_GRID, None,
                              pit.BASIS_SPLIT_ADJUSTED_TODAY)
    assert bundle["market_cap_split_unadjusted"] is True
    assert bundle["market_cap_basis"] == pit.BASIS_SPLIT_ADJUSTED_TODAY
    assert bundle["market_cap"] == pytest.approx(TRUE_MARKET_CAP / SPLIT_RATIO)
    # An empty map for the name is the same situation: it cannot be told apart from a name
    # that never split, so both raise the flag.
    empty = pit.as_of_bundle(facts, "SYN", META, TICK, TODAY_GRID, {"SYN": {}},
                             pit.BASIS_SPLIT_ADJUSTED_TODAY)
    assert empty["market_cap_split_unadjusted"] is True
    # A priced name is a precondition for the flag meaning anything: no market cap, no claim.
    priceless = pit.as_of_bundle(facts, "SYN", META, TICK, {}, None,
                                 pit.BASIS_SPLIT_ADJUSTED_TODAY)
    assert priceless["market_cap"] is None
    assert priceless["market_cap_split_unadjusted"] is False


def test_the_multi_class_fallback_count_is_restated_into_todays_terms_too():
    # The fallback count carries its own measurement date, so the today-basis restatement
    # reaches the multi-class path as well — otherwise exactly the names that already lost
    # their share-trend leg would also get a 10x-too-small market cap.
    facts = facts_of(
        gaap={"Revenues": [dfact("2025-01-01", "2025-12-31", 400.0, "2026-02-01")]},
        shares=[ifact("2026-01-10", 1_400_000.0, "2026-01-20"),     # class A
                ifact("2026-01-15", 600_000.0, "2026-01-20")])      # class B, 5 days apart
    bundle = pit.as_of_bundle(facts, "SYN", META, TICK, TODAY_GRID,
                              {"SYN": {SPLIT_DAY: SPLIT_RATIO}},
                              pit.BASIS_SPLIT_ADJUSTED_TODAY)
    assert bundle["shares_series"] == [] and bundle["shares_basis"] == "fallback-sum"
    assert bundle["market_cap"] == pytest.approx(TRUE_MARKET_CAP)


def test_the_share_trend_leg_is_identical_under_both_price_bases():
    # (iv) The market cap and the M share-trend leg use DIFFERENT split windows on purpose
    # (pit.as_of_bundle): bundle["splits"] stays filtered to <= as_of, because the
    # 2026-06-10 event was unknowable at the tick (§6.14), while the today-basis market cap
    # must look past it to match its price side. The trend cannot care either way — a
    # factor common to both endpoints cancels in the ratio.
    facts = _splitter_facts()
    splits = {"SYN": {SPLIT_DAY: SPLIT_RATIO}}
    raw = pit.as_of_bundle(facts, "SYN", META, TICK, RAW_GRID, splits)
    today = pit.as_of_bundle(facts, "SYN", META, TICK, TODAY_GRID, splits,
                             pit.BASIS_SPLIT_ADJUSTED_TODAY)
    assert raw["splits"] == today["splits"] == {}          # post-tick event hidden in BOTH
    assert raw["shares_series"] == today["shares_series"]
    assert scoring.adjusted_shares_series(raw) == scoring.adjusted_shares_series(today)
    trend = scoring._share_trend_pct(scoring.adjusted_shares_series(raw))
    assert trend == pytest.approx(
        scoring._share_trend_pct(scoring.adjusted_shares_series(today)))
    restated = [[day, val * SPLIT_RATIO] for day, val in raw["shares_series"]]
    assert scoring._share_trend_pct(restated) == pytest.approx(trend)   # the factor cancels
    assert trend == pytest.approx(1.01, abs=0.05)          # ~+1%/yr dilution, not +900%


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


def test_bt_fetch_prices_payload_carries_both_prices_and_the_true_symbol():
    idx = pd.to_datetime(["2019-12-27", "2020-01-03", "2020-01-10"], utc=True)
    frame = pd.DataFrame({"close": [2.0, 4.0, 6.0], "adj_close": [1.0, 2.0, 3.0],
                          "currency": "USD"}, index=idx)
    # The envelope now also DECLARES the share terms of its closes (§3.6 price_basis);
    # Yahoo's raw column is as-traded, so this writer declares "raw" (this assertion used
    # to pin the pre-declaration envelope).
    assert bt_fetch.prices_payload(frame, "2020-01-01", "BRK/B",
                                   {"2020-01-06": 2.0}) == {
        "symbol": "BRK/B",
        "bars": {"2020-01-03": {"close": 4.0, "adj_close": 2.0},
                 "2020-01-10": {"close": 6.0, "adj_close": 3.0}},
        "splits": {"2020-01-06": 2.0},
        "price_basis": "raw"}
    # An adjusted-only frame (today's vendored fetch_weekly_bars shape) degrades honestly.
    legacy = pd.DataFrame({"adj_close": [1.0, 2.0, 3.0], "currency": "USD"}, index=idx)
    degraded = bt_fetch.prices_payload(legacy, "2020-01-01", "SYN")
    assert degraded["bars"]["2020-01-03"] == {"adj_close": 2.0}   # no fake raw close
    assert pit.grid_is_degraded(degraded["bars"])
    assert pit.price_at({"SYN": degraded["bars"]}, "SYN", "2020-01-10") == 3.0  # falls back


def test_bt_fetch_period_ladder():
    assert bt_fetch.yf_period("2020-01-01", today=date(2026, 7, 31)) == "10y"
    assert bt_fetch.yf_period("2026-01-01", today=date(2026, 7, 31)) == "1y"
    assert bt_fetch.yf_period("2010-01-01", today=date(2026, 7, 31)) == "max"


def test_weekly_frame_takes_raw_closes_and_degrades_only_when_they_are_absent(monkeypatch):
    idx = pd.to_datetime(["2024-03-28", "2024-06-28"], utc=True)
    vendor = pd.DataFrame({"adj_close": [50.0, 55.0], "currency": "USD"}, index=idx)
    monkeypatch.setattr(bt_fetch.yf_fetch, "fetch_weekly_bars",
                        lambda symbol, **kw: vendor.copy())
    # Today's vendor keeps only Adj Close -> bt_fetch's own paced call supplies raw Close.
    monkeypatch.setattr(bt_fetch, "_raw_weekly_frame",
                        lambda symbol, **kw: (pd.Series([100.0, 110.0], index=idx),
                                              {"2024-05-01": 2.0}))
    frame, degraded, splits = bt_fetch.weekly_frame("SYN", state_dir=Path("."), period="2y")
    assert not degraded and splits == {"2024-05-01": 2.0}   # split events ride the same call
    assert list(frame["close"]) == [100.0, 110.0] and list(frame["adj_close"]) == [50.0, 55.0]
    # No raw closes to be had -> adjusted-only (never a fake raw close), and the run says so.
    monkeypatch.setattr(bt_fetch, "_raw_weekly_frame", lambda symbol, **kw: (None, {}))
    frame, degraded, _ = bt_fetch.weekly_frame("SYN", state_dir=Path("."), period="2y")
    assert degraded and "close" not in frame.columns
    assert pit.grid_is_degraded(bt_fetch.prices_payload(frame, "2020-01-01", "SYN")["bars"])
    # A future vendor that returns close itself is used as-is (no supplementary call).
    both = pd.DataFrame({"close": [100.0, 110.0], "adj_close": [50.0, 55.0]}, index=idx)
    monkeypatch.setattr(bt_fetch.yf_fetch, "fetch_weekly_bars", lambda symbol, **kw: both.copy())

    def _never(*a, **kw):
        raise AssertionError("vendor already exposes raw closes — no second fetch")

    monkeypatch.setattr(bt_fetch, "_raw_weekly_frame", _never)
    frame, degraded, _ = bt_fetch.weekly_frame("SYN", state_dir=Path("."), period="2y")
    assert not degraded and list(frame["close"]) == [100.0, 110.0]


def test_cache_stem_mirrors_the_writer_filename_rule():
    # pit.cache_stem is the loader's mirror of populate.cache_filename — the two rules
    # must not drift, or a sanitized filename stops round-tripping to its symbol.
    for symbol in ("BRK/B", "ADBE", "ASML.AS", "RDS/A"):
        assert populate.cache_filename(symbol) == pit.cache_stem(symbol) + ".json"
    assert pit.cache_stem("BRK/B") == "BRK-B"


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
    prices = {"SYN": {"2025-02-14": {"close": 45.0, "adj_close": 22.5},
                      "2025-02-21": {"close": 50.0, "adj_close": 25.0}}}
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
    # No Yahoo EV field exists in the PIT world (scoring may derive a reference EV from the
    # bundle's own price x listed shares; that one agrees with own EV here, so no EV_GAP).
    assert bundle["yahoo_ev"] is None
    assert all(flag["code"] not in ("EV_GAP", "SHARE_CLASS") for flag in row["flags"])
    assert bundle["shares_basis"] == "series"


def test_multi_class_fallback_grades_with_a_neutral_share_trend_leg():
    # msg 44's "multi-class-shares-fallback met neutrale M-leg", end to end: inconsistent
    # class rows empty the trend SERIES (the M share-trend leg carries no weight) while the
    # market cap survives on the fallback count — so the name GRADES. With market_cap None
    # it used to integrity-suspend as INSUFFICIENT and vanish from the backtest universe.
    facts = _integration_facts()
    facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"] = [
        ifact("2025-01-10", 700_000.0, "2025-01-20"),    # class A, counted 10 Jan
        ifact("2025-01-15", 310_000.0, "2025-01-20")]    # class B, counted 15 Jan
    prices = {"SYN": {"2025-02-14": {"close": 45.0, "adj_close": 22.5},
                      "2025-02-21": {"close": 50.0, "adj_close": 25.0}}}
    bundle = pit.as_of_bundle(facts, "SYN", META, "2025-03-01", prices)
    assert bundle["shares_series"] == []
    assert bundle["shares_basis"] == "fallback-sum"
    assert bundle["market_cap"] == pytest.approx(1_010_000.0 * 50.0)

    rows = scoring.score_universe([bundle])
    row = rows[0]
    assert row["grade"] in set("ABCDF")               # survives scoring, not INSUFFICIENT
    assert row["composite"] is not None and row["quality_score"] is not None
    # The share-trend leg is neutral: suspended, so M rests on the accruals leg alone.
    assert row["legs"]["m_shares"]["score"] is None
    assert row["pillars"]["m"] == pytest.approx(row["legs"]["m_accruals"]["score"], abs=0.06)


# ---------------------- real-filing coverage gaps (found by the EDGAR smoke run)

def test_a_repaid_borrowing_leaves_a_properly_tagged_date_unlevered_not_absent():
    # EDGAR stops carrying LongTermDebt* once a filer repays: Exelixis and Medpace both had
    # NO debt tag at their recent balance dates on real filings, which made EV incomputable
    # and suspended the name at every tick — the fortress balance sheets this framework
    # prizes were the ones dropped. A properly tagged date (assets AND cash) reads as zero.
    gaap = {
        "Assets": [ifact("2024-03-31", 900.0, "2024-04-15"),
                   ifact("2026-03-31", 1000.0, "2026-04-15")],
        "CashAndCashEquivalentsAtCarryingValue": [ifact("2024-03-31", 400.0, "2024-04-15"),
                                                  ifact("2026-03-31", 500.0, "2026-04-15")],
        "LongTermDebt": [ifact("2024-03-31", 300.0, "2024-04-15")],   # repaid, never re-tagged
    }
    maps = pit._balance_maps(facts_of(gaap=gaap), "2026-07-30")
    assert maps["Total Debt"]["2024-03-31"] == 300.0     # while it was still outstanding
    assert maps["Total Debt"]["2026-03-31"] == 0.0       # two years later: genuinely unlevered


def test_a_recent_debt_balance_is_carried_forward_rather_than_called_zero():
    # The error must always lean toward MORE leverage: a tagging gap one quarter after a
    # reported borrowing carries the debt forward, so it can never sneak a levered company
    # past the §4.4 leverage veto.
    gaap = {
        "Assets": [ifact("2026-03-31", 1000.0, "2026-04-15"),
                   ifact("2026-06-30", 1000.0, "2026-07-15")],
        "CashAndCashEquivalentsAtCarryingValue": [ifact("2026-03-31", 100.0, "2026-04-15"),
                                                  ifact("2026-06-30", 100.0, "2026-07-15")],
        "LongTermDebt": [ifact("2026-03-31", 800.0, "2026-04-15")],   # untagged next quarter
    }
    maps = pit._balance_maps(facts_of(gaap=gaap), "2026-07-30")
    assert maps["Total Debt"]["2026-06-30"] == 800.0


def test_gross_profit_is_derived_when_only_the_cost_side_is_tagged():
    # Filers need not present a gross-profit line; Exelixis tags CostOfGoodsAndServicesSold
    # and no recent GrossProfit. Since the Q gross-margin leg is REQUIRED (§4.6), an
    # untagged line suspended the whole name on real filings.
    income = {
        "Total Revenue": {"2026-03-31": 1000.0, "2026-06-30": 1200.0},
        "Cost Of Revenue": {"2026-03-31": 400.0, "2026-06-30": 500.0},
        "Gross Profit": {"2026-03-31": 555.0},          # a tagged value always wins
    }
    out = pit._gross_profit(income)
    assert out["2026-03-31"] == 555.0
    assert out["2026-06-30"] == 700.0                   # 1200 - 500, derived
    # Neither side tagged (Medpace's shape) -> no gross profit, and the name suspends honestly.
    assert pit._gross_profit({"Total Revenue": {"2026-06-30": 1200.0}}) == {}


class TestShareCountFreshness:
    """2026-08-05 defect: COKE published a $1.3bn market cap for a ~$13bn company.

    Its cover-page share count is tagged PER CLASS (companyfacts omits dimensional
    facts), so the non-dimensional series stopped in 2016 — and a 2016 count times a
    2026 price, across a 10-for-1 split, is a fabrication, not a measurement. It carried
    a 19.8% owner-FCF yield into the shortlist and the thesis desk's top 1%."""

    def _facts(self, share_entries, weighted=None):
        facts = {"facts": {"dei": {pit._SHARES_TAG: {"units": {"shares": share_entries}}}}}
        # a minimal annual income period so as_of_bundle builds at all
        facts["facts"]["us-gaap"] = {"Revenues": {"units": {"USD": [
            {"start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01",
             "form": "10-K", "val": 1000.0}]}}}
        if weighted is not None:
            facts["facts"]["us-gaap"][pit._WEIGHTED_SHARES_TAGS[0]] = {"units": {"shares": weighted}}
        return facts

    def test_a_stale_cover_page_count_refuses_the_market_cap(self):
        facts = self._facts([{"end": "2016-03-04", "filed": "2016-03-18",
                              "form": "10-K", "val": 7_141_447.0}])
        b = pit.as_of_bundle(facts, "COKE", None, "2026-08-01", {"COKE": {"2026-07-27": {"close": 187.9}}})
        assert b["market_cap"] is None
        assert b["shares_basis"] == "stale-refused"
        assert "stale" in b["shares_note"]

    def test_the_weighted_average_count_repairs_it_and_says_so(self):
        facts = self._facts(
            [{"end": "2010-02-17", "filed": "2010-02-26", "form": "10-K", "val": 713_924_267.0}],
            weighted=[{"start": "2026-04-01", "end": "2026-06-30", "filed": "2026-07-30",
                       "form": "10-Q", "val": 851_000_000.0}])
        b = pit.as_of_bundle(facts, "UPS", None, "2026-08-01", {"UPS": {"2026-07-27": {"close": 100.0}}})
        assert b["shares_basis"] == "weighted-average"
        assert b["market_cap"] == pytest.approx(851_000_000.0 * 100.0)
        assert "weighted-average" in b["shares_note"]

    def test_a_fresh_count_is_untouched(self):
        facts = self._facts([{"end": "2026-06-30", "filed": "2026-07-15",
                              "form": "10-Q", "val": 1_000_000.0}])
        b = pit.as_of_bundle(facts, "OK", None, "2026-08-01", {"OK": {"2026-07-27": {"close": 10.0}}})
        assert b["market_cap"] == pytest.approx(10_000_000.0)
        assert b["shares_note"] is None and b["shares_basis"] != "stale-refused"

    def test_a_stale_weighted_average_is_refused_too(self):
        facts = self._facts(
            [{"end": "2016-03-04", "filed": "2016-03-18", "form": "10-K", "val": 7_141_447.0}],
            weighted=[{"start": "2015-01-01", "end": "2015-12-31", "filed": "2016-02-01",
                       "form": "10-K", "val": 9_000_000.0}])
        b = pit.as_of_bundle(facts, "COKE", None, "2026-08-01", {"COKE": {"2026-07-27": {"close": 187.9}}})
        assert b["market_cap"] is None and b["shares_basis"] == "stale-refused"

    def test_the_age_travels_with_the_bundle(self):
        facts = self._facts([{"end": "2025-06-30", "filed": "2025-07-15",
                              "form": "10-Q", "val": 5.0}])
        b = pit.as_of_bundle(facts, "X", None, "2026-08-01", {})
        assert b["shares_as_of"] == "2025-06-30" and b["shares_age_days"] == 397
        assert b["shares_series_age_days"] == 397 and b["shares_series_stale"] is False

    def test_a_repaired_market_cap_still_declares_the_series_stale(self):
        """The guard the 2026-08-05 fix did NOT provide, and the one that matters most.

        When the weighted-average count repairs the market cap, the name grades normally —
        but the dei SERIES behind the share-count TREND is still years dead, and the trend
        is both a scored criterion and a legal thesis-trigger metric. Measured on the real
        universe: CMCSA's series is 6,062 days old and yielded +0.19%/yr, UPS 6,014 days
        and +3.63%/yr — numbers about a company a decade ago, reported as this year's."""
        facts = self._facts(
            [{"end": "2010-02-17", "filed": "2010-02-26", "form": "10-K", "val": 713_924_267.0}],
            weighted=[{"start": "2026-04-01", "end": "2026-06-30", "filed": "2026-07-30",
                       "form": "10-Q", "val": 851_000_000.0}])
        b = pit.as_of_bundle(facts, "UPS", None, "2026-08-01",
                             {"UPS": {"2026-07-27": {"close": 100.0}}})
        assert b["market_cap"] == pytest.approx(851_000_000.0 * 100.0)   # cap is fine
        assert b["shares_age_days"] < pit.SHARES_MAX_AGE_DAYS            # the POINT is fresh
        assert b["shares_series_stale"] is True                          # the SERIES is not
        assert b["shares_series_age_days"] > 5000

    def test_a_stale_price_grid_refuses_the_market_cap_too(self):
        """The same rule with the operands swapped. Nothing in the repo ever refreshed the
        price grid (prices.py is that producer, added 2026-08-06), so a box whose sweep had
        stopped kept multiplying a months-old close by a current share count. Prices move
        slowly, so the product stays plausible — which is what makes it dangerous."""
        facts = self._facts([{"end": "2026-06-30", "filed": "2026-07-15",
                              "form": "10-Q", "val": 1_000_000.0}])
        b = pit.as_of_bundle(facts, "X", None, "2026-08-01",
                             {"X": {"2026-04-10": {"close": 10.0}}})   # 113 days behind
        assert b["price"] is None and b["market_cap"] is None
        assert b["price_age_days"] == 113 and "stale close" in b["price_note"]

    def test_a_price_inside_the_bound_is_used_and_dated(self):
        facts = self._facts([{"end": "2026-06-30", "filed": "2026-07-15",
                              "form": "10-Q", "val": 1_000_000.0}])
        b = pit.as_of_bundle(facts, "X", None, "2026-08-01",
                             {"X": {"2026-07-27": {"close": 10.0}}})
        assert b["market_cap"] == pytest.approx(10_000_000.0)
        assert b["price_as_of"] == "2026-07-27" and b["price_note"] is None

    def test_price_at_itself_stays_unbounded_for_the_backtest(self):
        # A series that simply stops is how backtest3 models a delisting, and booking the
        # name out at its last known price is correct there. The bound is a market-cap
        # rule, not a lookup rule.
        grid = {"D": {"2024-08-02": {"close": 60.0}}}
        assert pit.price_at(grid, "D", "2026-08-01") == 60.0
        assert pit.price_point_at(grid, "D", "2026-08-01") == ("2024-08-02", 60.0)

    def test_an_empty_series_reports_an_unknown_age_rather_than_stale(self):
        # No observations at all is a different fact from observations that stopped, and
        # the trend already reports absent for it. Calling it "stale" would invent a date.
        facts = self._facts([])
        b = pit.as_of_bundle(facts, "X", None, "2026-08-01", {})
        assert b["shares_series_age_days"] is None
        assert b["shares_series_stale"] is False
