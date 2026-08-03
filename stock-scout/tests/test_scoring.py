"""Offline tests for scoring.py — the shared decision layer (RECONSTRUCTION.md §4).

Synthetic bundles only; no network, no files, no clock. Covers TTM basis selection,
every §4.4 veto and §4.5 flag, the §4.6 percentile/composite machinery, the §4.7 v3
quality engine and the §4.8 shadow layers (MoS DCF, Buffett checklist, portfolio clamps),
plus the v2.4 review fixes: split-adjusted share counts, the aligned TTM window, the
EBIT-gated ROIC cap, SHARE_CLASS suppressing the hard dilution veto, the zero-EBITDA
leverage veto and the derived reference EV behind EV_GAP/SHARE_CLASS.
"""
import copy

import pandas as pd
import pytest

import populate
import scoring

YEARS = ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
QTRS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]

BAL_CELL = {
    "Total Debt": 100e6, "Cash And Cash Equivalents": 300e6, "Working Capital": 200e6,
    "Total Assets": 2e9, "Current Assets": 800e6, "Current Liabilities": 400e6,
    "Stockholders Equity": 1e9, "Minority Interest": 0.0,
}


def base_bundle(symbol="AAA", sector="Information Technology", industry="Software"):
    """A healthy graded name: quarterly TTM basis, positive owner-FCF, no veto, no flags.

    TTM (quarterly): revenue 1.28e9, EBIT 260e6, EBITDA 320e6, OCF 280e6, owner-FCF 212e6.
    Own EV = 10e9 + 100e6 - 300e6 = 9.8e9 (yahoo_ev set equal -> gap 0)."""
    ann_inc, ann_bal, ann_cf = {}, {}, {}
    for i, pe in enumerate(YEARS):
        rev = 1.0e9 + i * 0.1e9
        ann_inc[pe] = {
            "Total Revenue": rev, "EBIT": 250e6, "EBITDA": 320e6,
            "Gross Profit": 0.6 * rev, "Operating Income": 0.25 * rev,
            "Net Income": 170e6 + i * 10e6,
            "Net Income Including Noncontrolling Interests": 170e6 + i * 10e6,
            "Interest Expense": 5e6,
        }
        ann_bal[pe] = dict(BAL_CELL)
        ann_cf[pe] = {"Operating Cash Flow": 280e6, "Capital Expenditure": -50e6,
                      "Stock Based Compensation": 20e6, "Depreciation And Amortization": 60e6}
    q_inc, q_cf = {}, {}
    for pe in QTRS:
        q_inc[pe] = {
            "Total Revenue": 320e6, "EBIT": 65e6, "EBITDA": 80e6, "Gross Profit": 192e6,
            "Operating Income": 80e6, "Net Income": 55e6,
            "Net Income Including Noncontrolling Interests": 55e6, "Interest Expense": 1.25e6,
        }
        q_cf[pe] = {"Operating Cash Flow": 70e6, "Capital Expenditure": -12e6,
                    "Stock Based Compensation": 5e6, "Depreciation And Amortization": 15e6}
    return {
        "symbol": symbol, "sector": sector, "industry": industry, "name": f"{symbol} Corp",
        "market_cap": 10e9, "yahoo_ev": 9.8e9, "price": 100.0,
        "shares_series": [[f"{y}-06-30", 100e6] for y in range(2021, 2026)]
                         + [["2025-12-15", 100e6]],
        "annual": {"income": ann_inc, "balance": ann_bal, "cashflow": ann_cf},
        "quarterly": {"income": q_inc, "balance": {"2025-12-31": dict(BAL_CELL)},
                      "cashflow": q_cf},
    }


def run_one(bundle):
    return scoring.score_universe([bundle])[0]


def set_all_balances(b, **rows):
    for pe in b["annual"]["balance"]:
        b["annual"]["balance"][pe].update(rows)
    for pe in b["quarterly"]["balance"]:
        b["quarterly"]["balance"][pe].update(rows)


def flag_codes(row):
    return {f["code"] for f in row["flags"]}


# --- §4.2 TTM assembly -------------------------------------------------------------------

def test_ttm_quarterly_basis():
    ttm = scoring.assemble_ttm(base_bundle())
    assert ttm["basis"] == "quarterly"
    assert ttm["quarters"] == 4
    assert ttm["through"] == "2025-12-31"
    assert ttm["revenue"] == pytest.approx(1.28e9)
    assert ttm["owner_fcf"] == pytest.approx(4 * (70e6 - 12e6 - 5e6))


def test_ttm_annual_fallback():
    b = base_bundle()
    b["quarterly"] = {}
    ttm = scoring.assemble_ttm(b)
    assert ttm["basis"] == "annual"
    assert ttm["quarters"] == 1
    assert ttm["through"] == "2025-12-31"
    assert ttm["revenue"] == pytest.approx(1.3e9)          # newest annual only
    assert ttm["owner_fcf"] == pytest.approx(280e6 - 50e6 - 20e6)


def test_ttm_basis_reported_in_scored_row():
    assert run_one(base_bundle())["ttm"] == {
        "quarters": 4, "through": "2025-12-31", "basis": "quarterly"}
    b = base_bundle()
    b["quarterly"] = {}
    assert run_one(b)["ttm"]["basis"] == "annual"


def test_owner_fcf_da_absent_falls_back_to_capex():
    # D&A absent -> maintenance proxy = |CapEx| (§4.2): 70 - 12 - 5 = 53 unchanged here,
    # but with D&A 8 < |CapEx| 12 the maintenance drops to 8.
    cell = {"Operating Cash Flow": 70.0, "Capital Expenditure": -12.0,
            "Stock Based Compensation": 5.0}
    assert scoring._owner_fcf(cell) == pytest.approx(53.0)
    cell["Depreciation And Amortization"] = 8.0
    assert scoring._owner_fcf(cell) == pytest.approx(70.0 - 8.0 - 5.0)


def test_ttm_window_is_the_intersection_of_income_and_cashflow_periods():
    """§4.2 (v2.4): income and cashflow must be summed over the SAME four quarters.
    Yahoo here is one quarter ahead on income (through 2025-12-31) and one behind on
    cashflow (through 2025-09-30); the aligned window is the newest 4 common ends."""
    b = base_bundle()
    inc, cf = {}, {}
    for pe in ["2024-12-31"] + QTRS:                   # 5 income quarters
        inc[pe] = dict(b["quarterly"]["income"][QTRS[0]])
        inc[pe]["Total Revenue"] = 400e6 if pe == "2025-12-31" else 300e6
    for pe in ["2024-09-30", "2024-12-31"] + QTRS[:3]:  # 5 cashflow quarters, one behind
        cf[pe] = dict(b["quarterly"]["cashflow"][QTRS[0]])
        cf[pe]["Operating Cash Flow"] = 100e6 if pe == "2024-09-30" else 70e6
    b["quarterly"]["income"], b["quarterly"]["cashflow"] = inc, cf

    ttm = scoring.assemble_ttm(b)
    assert ttm["basis"] == "quarterly" and ttm["quarters"] == 4
    assert ttm["periods"] == ["2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30"]
    assert ttm["through"] == "2025-09-30"
    # Revenue over the ALIGNED window: 4 x 300e6 — the misaligned newest-4-income window
    # (which drops 2024-12-31 and picks up the 400e6 quarter) would have summed 1.3e9.
    assert ttm["revenue"] == pytest.approx(1.2e9)
    assert ttm["ocf"] == pytest.approx(4 * 70e6)       # 2024-09-30's 100e6 stays out
    assert ttm["owner_fcf"] == pytest.approx(4 * (70e6 - 12e6 - 5e6))


def test_ttm_falls_back_to_annual_when_fewer_than_four_common_quarters():
    b = base_bundle()
    cf = {pe: dict(b["quarterly"]["cashflow"][QTRS[0]])
          for pe in ["2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"]}
    b["quarterly"]["cashflow"] = cf                    # only 2025-03-31 is common
    ttm = scoring.assemble_ttm(b)
    assert ttm["basis"] == "annual" and ttm["quarters"] == 1
    assert ttm["periods"] == ["2025-12-31"]
    assert ttm["revenue"] == pytest.approx(1.3e9)


# --- §4.4 vetoes -------------------------------------------------------------------------

def test_leverage_veto_net_debt_over_4x():
    b = base_bundle()
    set_all_balances(b, **{"Total Debt": 5e9, "Cash And Cash Equivalents": 100e6})
    row = run_one(b)
    assert row["grade"] == "VETOED"
    assert row["veto"]["vetoed"] is True
    assert "leverage" in row["veto"]["reason"]
    assert row["composite"] is None and row["quality_score"] is None


def test_leverage_veto_negative_ebitda_with_net_debt():
    b = base_bundle()
    for pe in QTRS:
        b["quarterly"]["income"][pe]["EBITDA"] = -10e6
    set_all_balances(b, **{"Total Debt": 500e6, "Cash And Cash Equivalents": 100e6})
    row = run_one(b)
    assert row["grade"] == "VETOED"
    assert "EBITDA <= 0" in row["veto"]["reason"]


def test_cash_flow_quality_veto_24_pct_does_not_fire():
    b = base_bundle()
    for pe in QTRS:                                    # TTM OCF 280e6; 24% = 67.2e6 total
        b["quarterly"]["cashflow"][pe]["Provision For Doubtful Accounts"] = 16.8e6
    row = run_one(b)
    assert row["veto"]["vetoed"] is False
    assert row["grade"] in "ABCDF"


def test_cash_flow_quality_veto_26_pct_fires():
    b = base_bundle()
    for pe in QTRS:                                    # 26% = 72.8e6 total
        b["quarterly"]["cashflow"][pe]["Provision For Doubtful Accounts"] = 18.2e6
    row = run_one(b)
    assert row["grade"] == "VETOED"
    assert "cash-flow quality" in row["veto"]["reason"]
    assert "26%" in row["veto"]["reason"]


def test_dilution_21_pct_hard_veto():
    b = base_bundle()
    b["shares_series"] = [["2024-12-31", 100e6], ["2025-12-31", 121e6]]
    row = run_one(b)
    assert row["grade"] == "VETOED"
    assert "dilution veto" in row["veto"]["reason"]


def test_dilution_15_pct_penalty_not_veto():
    b = base_bundle()
    b["shares_series"] = [["2024-12-31", 100e6], ["2025-12-31", 115e6]]
    row = run_one(b)
    assert row["veto"]["vetoed"] is False
    assert row["veto"]["penalty"] == -15
    assert "dilution penalty" in row["veto"]["reason"]
    assert row["grade"] in "ABCDF"
    # composite carries the -15 (§4.6 clamp): recompute from pillars.
    p = row["pillars"]
    raw = (0.25 * p["v"] + 0.25 * p["q"] + 0.20 * p["g"] + 0.15 * p["d"]
           + 0.15 * p["m"] - 15)
    assert row["composite"] == pytest.approx(max(0.0, raw), abs=0.2)


def test_stock_split_is_not_dilution():
    """§4.3/§4.5 (v2.4): raw Yahoo share counts are split-UNadjusted, so a 2-for-1 doubles
    the series overnight. Unadjusted that trips the >20%/yr hard veto and drags the
    per-share owner-FCF CAGR deeply negative; with the cache's split history the trend is
    ~0%/yr and the per-share leg is flat."""
    b = base_bundle()
    b["shares_series"] = ([[f"{y}-06-30", 50e6] for y in range(2021, 2025)]
                          + [["2025-06-30", 100e6]])
    unadjusted = run_one(b)                            # the bug this fix removes
    assert unadjusted["grade"] == "VETOED"
    assert "dilution veto" in unadjusted["veto"]["reason"]

    b["splits"] = {"2025-01-15": 2.0}
    row = run_one(b)
    assert row["veto"]["vetoed"] is False and row["veto"]["penalty"] == 0
    assert row["grade"] in "ABCDF"
    assert row["legs"]["m_shares"]["raw"] == pytest.approx(0.0, abs=1e-9)
    # Per-share owner-FCF: flat owner-FCF on a constant split-adjusted count -> ~0%/yr,
    # against the ~-20%/yr the raw series produces.
    assert row["legs"]["g_ps_ofcf"]["raw"] == pytest.approx(0.0, abs=1e-9)
    assert scoring._per_share_ofcf_growth(
        {**b, "splits": {}})[0] == pytest.approx(-20.6, abs=0.5)


def test_genuine_issuer_still_hard_vetoed_with_split_history_present():
    b = base_bundle()
    b["shares_series"] = [["2024-12-31", 100e6], ["2025-12-15", 125e6]]   # +26%/yr real
    b["splits"] = {"2019-05-01": 2.0}                  # an old split, before both points
    row = run_one(b)
    assert row["grade"] == "VETOED"
    assert "dilution veto" in row["veto"]["reason"]


def test_splits_absent_or_unusable_leave_the_series_untouched():
    b = base_bundle()
    b["shares_series"] = [["2024-12-31", 100e6], ["2025-12-15", 125e6]]
    assert scoring.adjusted_shares_series(b) == [("2024-12-31", 100e6),
                                                 ("2025-12-15", 125e6)]
    b["splits"] = {"2025-06-01": 0.0, "2025-07-01": None}   # never rescale on junk
    assert scoring.adjusted_shares_series(b) == [("2024-12-31", 100e6),
                                                 ("2025-12-15", 125e6)]


def test_cache_entry_carries_the_split_history(tmp_path):
    """The §3.2 cache side of the same fix: split events ride the one daily-bar call."""
    bars = pd.DataFrame(
        {"close": [10.0, 5.0, 5.5], "adj_close": [10.0, 5.0, 5.5],
         "dividend": [0.0, 0.0, 0.0], "split": [0.0, 2.0, 0.0],
         "currency": ["USD", "USD", "USD"]},
        index=pd.DatetimeIndex(["2025-01-14", "2025-01-15", "2025-01-16"]))
    assert populate.splits_payload(bars) == {"2025-01-15": 2.0}
    annual = {st: pd.DataFrame({pd.Timestamp("2025-12-31"): {"Total Revenue": 1.0}})
              for st in populate.STATEMENT_TYPES}
    entry = populate.build_cache_entry("TST", {}, {"currency": "USD"}, bars, None, annual)
    assert entry["splits"] == {"2025-01-15": 2.0}
    # A frame without the column (older callers / fixtures) -> {}, i.e. no adjustment.
    assert populate.splits_payload(bars.drop(columns=["split"])) == {}


def _burner(b, *, ttm_positive):
    """Annual owner-FCF negative every period; quarterly TTM positive or negative."""
    for pe in YEARS:
        b["annual"]["cashflow"][pe] = {
            "Operating Cash Flow": 10e6, "Capital Expenditure": -60e6,
            "Stock Based Compensation": 20e6, "Depreciation And Amortization": 70e6,
        }                                              # 10 - 60 - 20 = -70e6 every year
    if not ttm_positive:
        for pe in QTRS:
            b["quarterly"]["cashflow"][pe] = {
                "Operating Cash Flow": 5e6, "Capital Expenditure": -15e6,
                "Stock Based Compensation": 5e6, "Depreciation And Amortization": 20e6,
            }                                          # 5 - 15 - 5 = -15e6/q -> TTM -60e6
    return b


def test_cash_destruction_recovered_burner_escapes():
    row = run_one(_burner(base_bundle(), ttm_positive=True))
    assert row["veto"]["vetoed"] is False
    assert row["grade"] in "ABCDF"
    assert "REINVESTOR" not in flag_codes(row)


def test_cash_destruction_still_burner_vetoed():
    row = run_one(_burner(base_bundle(), ttm_positive=False))
    assert row["grade"] == "VETOED"
    assert "cash-destruction" in row["veto"]["reason"]


def test_cash_destruction_reinvestor_carve_out():
    b = _burner(base_bundle(), ttm_positive=False)
    for i, pe in enumerate(YEARS):                     # revenue CAGR 14.5%/yr > 10%
        b["annual"]["income"][pe]["Total Revenue"] = [1.0e9, 1.15e9, 1.3e9, 1.5e9][i]
    row = run_one(b)                                   # ROIC ~23.6% > 15%
    assert row["veto"]["vetoed"] is False
    assert "REINVESTOR" in flag_codes(row)
    assert "reinvestor" in row["veto"]["reason"]
    assert row["grade"] in "ABCDF"


# --- §4.5 flags --------------------------------------------------------------------------

def test_ev_gap_flag():
    b = base_bundle()
    b["yahoo_ev"] = 9.8e9 * 0.80                       # |gap| 20% > 15%
    row = run_one(b)
    assert "EV_GAP" in flag_codes(row)
    assert row["ev"]["own"] == pytest.approx(9.8e9)
    assert row["ev"]["gap_pct"] == pytest.approx(20.0)
    assert "EV_GAP" not in flag_codes(run_one(base_bundle()))


def test_share_class_requires_both_conditions():
    # Tenet case (§4.5): 41% NCI with only a 10% EV gap must NOT flag.
    b = base_bundle()
    set_all_balances(b, **{"Stockholders Equity": 590e6, "Minority Interest": 410e6})
    b["yahoo_ev"] = 9.8e9 * 0.90
    assert "SHARE_CLASS" not in flag_codes(run_one(b))
    # Both conditions -> flag + m_shares leg neutral 50.
    b["yahoo_ev"] = 9.8e9 * 0.80
    row = run_one(b)
    assert "SHARE_CLASS" in flag_codes(row)
    leg = row["legs"]["m_shares"]
    assert leg["score"] == 50.0
    assert leg["percentile"] is None


def test_share_class_suppresses_the_hard_dilution_veto_too():
    """§4.4/§4.5 (v2.4): the trend the system just declared untrustworthy (leg forced to
    neutral 50, penalty off) may not hard-veto the name either — while the same trend on
    an unflagged name still does."""
    b = base_bundle()
    set_all_balances(b, **{"Stockholders Equity": 590e6, "Minority Interest": 410e6})
    b["yahoo_ev"] = 9.8e9 * 0.80
    b["shares_series"] = [["2024-12-31", 100e6], ["2025-12-15", 130e6]]   # ~+32%/yr
    row = run_one(b)
    assert "SHARE_CLASS" in flag_codes(row)
    assert row["veto"]["vetoed"] is False and row["veto"]["penalty"] == 0
    assert row["grade"] in "ABCDF"
    assert row["legs"]["m_shares"]["score"] == 50.0

    plain = base_bundle()
    plain["shares_series"] = [["2024-12-31", 100e6], ["2025-12-15", 130e6]]
    assert run_one(plain)["grade"] == "VETOED"


def test_share_class_suppresses_dilution_penalty():
    b = base_bundle()
    set_all_balances(b, **{"Stockholders Equity": 590e6, "Minority Interest": 410e6})
    b["yahoo_ev"] = 9.8e9 * 0.80
    b["shares_series"] = [["2024-12-31", 100e6], ["2025-12-31", 115e6]]   # 15%/yr
    row = run_one(b)
    assert "SHARE_CLASS" in flag_codes(row)
    assert row["veto"]["penalty"] == 0
    assert row["veto"]["vetoed"] is False


def test_float_roic_flag():
    b = base_bundle()
    set_all_balances(b, **{"Current Deferred Revenue": 500e6})   # 39% of 1.28e9 TTM revenue
    row = run_one(b)
    assert "FLOAT_ROIC" in flag_codes(row)
    assert "FLOAT_ROIC" not in flag_codes(run_one(base_bundle()))


def test_low_base_drops_per_share_leg():
    b = base_bundle()
    b["annual"]["cashflow"][YEARS[0]] = {
        "Operating Cash Flow": 25e6, "Capital Expenditure": -10e6,
        "Stock Based Compensation": 5e6, "Depreciation And Amortization": 60e6,
    }                                # base-year owner-FCF 10e6 = 1% of 1e9 revenue (<2%)
    row = run_one(b)
    assert "LOW_BASE" in flag_codes(row)
    assert row["legs"]["g_ps_ofcf"]["score"] is None
    assert "LOW_BASE" in row["legs"]["g_ps_ofcf"]["note"]
    assert row["legs"]["g_revenue"]["score"] is not None       # other G leg still scores


def test_roic_capped_on_non_positive_denominator():
    b = base_bundle()
    set_all_balances(b, **{"Working Capital": -950e6})   # denom = -950e6 + 900e6 = -50e6
    row = run_one(b)
    assert "ROIC_CAPPED" in flag_codes(row)
    assert row["legs"]["q_roic"]["raw"] == pytest.approx(1000.0)
    assert row["grade"] in "ABCDF"                       # capped, not suspended


def test_roic_cap_requires_positive_ebit():
    """§4.3 (v2.4): the 1000% cap is the capital-light/float-financed case (EBIT > 0).
    A loss-maker over a negative capital base is not a 1000% return on capital — the leg
    suspends, so it can claim neither the ROIC floor factor nor cohort-topping Q/G credit."""
    assert scoring._roic_pct(-80e6, dict(BAL_CELL, **{"Working Capital": -950e6})) \
        == (None, False)
    b = base_bundle()
    set_all_balances(b, **{"Working Capital": -950e6})
    for pe in QTRS:
        b["quarterly"]["income"][pe]["EBIT"] = -20e6     # TTM EBIT -80e6
    row = run_one(b)
    assert row["grade"] == "INSUFFICIENT"
    assert "ROIC" in row["note"]
    assert "ROIC_CAPPED" not in flag_codes(row)
    assert row["composite"] is None


def test_negative_ebit_cannot_buy_the_reinvestor_carve_out():
    b = _burner(base_bundle(), ttm_positive=False)
    set_all_balances(b, **{"Working Capital": -950e6})   # non-positive capital base
    for i, pe in enumerate(YEARS):                       # revenue CAGR 14.5%/yr > 10%
        b["annual"]["income"][pe]["Total Revenue"] = [1.0e9, 1.15e9, 1.3e9, 1.5e9][i]
    for pe in QTRS:
        b["quarterly"]["income"][pe]["EBIT"] = -20e6
    row = run_one(b)
    assert row["grade"] == "VETOED"                      # not spared, not INSUFFICIENT
    assert "cash-destruction" in row["veto"]["reason"]
    assert "REINVESTOR" not in flag_codes(row)


def test_zero_ebitda_with_net_debt_is_vetoed_not_insufficient():
    """§4.4 (v2.4): EBITDA exactly 0 leaves net debt/EBITDA uncomputable, and the veto
    layer runs BEFORE the §4.6 integrity-suspend — so the leverage veto fires instead of
    the name silently dropping out as INSUFFICIENT."""
    b = base_bundle()
    for pe in QTRS:
        b["quarterly"]["income"][pe]["EBITDA"] = 0.0
    set_all_balances(b, **{"Total Debt": 500e6, "Cash And Cash Equivalents": 100e6})
    row = run_one(b)
    assert row["grade"] == "VETOED"
    assert "EBITDA <= 0" in row["veto"]["reason"]
    assert row["legs"] == {} and row["composite"] is None


def test_insufficient_still_wins_when_no_veto_fires():
    b = base_bundle()
    for pe in QTRS:
        del b["quarterly"]["income"][pe]["EBITDA"]       # EBITDA missing, no net debt
    assert run_one(b)["grade"] == "INSUFFICIENT"


# --- §4.5 EV_GAP / SHARE_CLASS on a derived reference EV (v2.4) --------------------------

def test_derived_reference_ev_flags_an_up_c_structure():
    """yfinance's FastInfo has no enterprise-value field and the `info` path is banned, so
    `yahoo_ev` is None in live runs. The Up-C signal is a share-count mismatch: the quoted
    market cap counts ALL units (125M x $100) while get_shares_full reports the listed
    class (100M). Rebuilding the listed-class reference EV revives both flags."""
    b = base_bundle()
    b["yahoo_ev"] = None
    b["market_cap"] = 12.5e9
    set_all_balances(b, **{"Stockholders Equity": 590e6, "Minority Interest": 410e6})
    row = run_one(b)
    assert row["ev"]["yahoo_source"] == "derived"
    assert row["ev"]["yahoo"] == pytest.approx(9.8e9)     # 100 x 100e6 + 100e6 - 300e6
    assert row["ev"]["own"] == pytest.approx(12.3e9)
    assert row["ev"]["gap_pct"] == pytest.approx(20.3, abs=0.1)
    assert {"EV_GAP", "SHARE_CLASS"} <= flag_codes(row)
    assert row["legs"]["m_shares"]["score"] == 50.0


def test_derived_reference_ev_silent_for_a_single_class_high_nci_name():
    # The Tenet case (§4.5): 41% NCI but one share class -> implied units == reported
    # shares -> gap 0 -> neither flag.
    b = base_bundle()
    b["yahoo_ev"] = None
    set_all_balances(b, **{"Stockholders Equity": 590e6, "Minority Interest": 410e6})
    row = run_one(b)
    assert row["ev"]["yahoo_source"] == "derived"
    assert row["ev"]["gap_pct"] == pytest.approx(0.0, abs=1e-9)
    assert flag_codes(row) == set()


def test_supplied_yahoo_ev_wins_and_source_is_reported():
    row = run_one(base_bundle())                         # yahoo_ev 9.8e9 supplied
    assert row["ev"]["yahoo_source"] == "field"
    assert row["ev"]["yahoo"] == pytest.approx(9.8e9)
    b = base_bundle()
    b["yahoo_ev"], b["price"] = None, None               # nothing to derive from
    row = run_one(b)
    assert row["ev"]["yahoo_source"] is None
    assert row["ev"]["yahoo"] is None and row["ev"]["gap_pct"] is None
    assert flag_codes(row) == set()


# --- §4.6 scoring machinery --------------------------------------------------------------

def test_singleton_cohorts_are_neutral_50():
    row = run_one(base_bundle())
    for leg_id in ("v_yield", "q_roic", "q_ofcf_margin", "g_revenue", "g_ps_ofcf",
                   "d_net_debt", "d_sbc", "m_shares", "m_accruals"):
        leg = row["legs"][leg_id]
        assert leg["percentile"] == 50.0, leg_id
        assert leg["cohort_n"] == 1, leg_id
    assert row["legs"]["d_self_funding"]["score"] == 100.0
    assert row["pillars"]["v"] == 50.0


def test_percentiles_ordered_within_sector_cohort():
    bundles = []
    for sym, ocf in (("AAA", 40e6), ("BBB", 70e6), ("CCC", 100e6)):
        b = base_bundle(symbol=sym)
        for pe in QTRS:
            b["quarterly"]["cashflow"][pe]["Operating Cash Flow"] = ocf
        bundles.append(b)
    rows = {r["symbol"]: r for r in scoring.score_universe(bundles)}
    p = [rows[s]["legs"]["v_yield"]["percentile"] for s in ("AAA", "BBB", "CCC")]
    assert p[0] < p[1] < p[2]
    assert p[1] == pytest.approx(50.0)
    assert all(rows[s]["legs"]["v_yield"]["cohort_n"] == 3 for s in rows)


def test_cross_sector_cohorts_are_isolated():
    b1 = base_bundle(symbol="AAA", sector="Information Technology")
    b2 = base_bundle(symbol="BBB", sector="Health Care")
    for pe in QTRS:
        b2["quarterly"]["cashflow"][pe]["Operating Cash Flow"] = 140e6
    rows = scoring.score_universe([b1, b2])
    assert all(r["legs"]["v_yield"]["cohort_n"] == 1 for r in rows)
    assert all(r["legs"]["v_yield"]["percentile"] == 50.0 for r in rows)


def test_insufficient_on_missing_market_cap():
    b = base_bundle()
    b["market_cap"] = None
    row = run_one(b)
    assert row["grade"] == "INSUFFICIENT"
    assert "owner-FCF yield" in row["note"]
    assert row["composite"] is None
    assert row["pillars"] == {"v": None, "q": None, "g": None, "d": None, "m": None}


def test_insufficient_on_missing_gross_profit():
    b = base_bundle()
    for pe in QTRS:
        del b["quarterly"]["income"][pe]["Gross Profit"]
    row = run_one(b)
    assert row["grade"] == "INSUFFICIENT"
    assert "gross-margin" in row["note"]


def test_universe_order_preserved_and_vetoed_suppressed():
    good = base_bundle(symbol="GOOD")
    bad = base_bundle(symbol="BAD")
    set_all_balances(bad, **{"Total Debt": 5e9, "Cash And Cash Equivalents": 0.0})
    thin = base_bundle(symbol="THIN")
    thin["market_cap"] = None
    rows = scoring.score_universe([good, bad, thin])
    assert [r["symbol"] for r in rows] == ["GOOD", "BAD", "THIN"]
    assert rows[1]["grade"] == "VETOED" and rows[1]["composite"] is None
    assert rows[2]["grade"] == "INSUFFICIENT"


def test_grade_bands():
    for comp, letter in ((100, "A"), (80, "A"), (79.99, "B"), (65, "B"), (64.9, "C"),
                         (50, "C"), (49.9, "D"), (35, "D"), (34.99, "F"), (0, "F")):
        assert scoring.grade_letter(comp) == letter, comp


def test_composite_recomputes_from_pillars():
    row = run_one(base_bundle())
    p = row["pillars"]
    raw = 0.25 * p["v"] + 0.25 * p["q"] + 0.20 * p["g"] + 0.15 * p["d"] + 0.15 * p["m"]
    assert row["composite"] == pytest.approx(raw, abs=0.2)
    assert row["grade"] == scoring.grade_letter(row["composite"])


def test_g_neutral_50_when_both_legs_missing():
    b = base_bundle()
    only = YEARS[-1]                                   # a single annual period: no CAGRs
    for st in ("income", "balance", "cashflow"):
        b["annual"][st] = {only: b["annual"][st][only]}
    row = run_one(b)
    assert row["legs"]["g_revenue"]["score"] is None
    assert row["legs"]["g_ps_ofcf"]["score"] is None
    assert row["pillars"]["g"] == 50.0


def test_tiering():
    assert run_one(base_bundle(industry="Software"))["tier"] == "Core"
    assert run_one(base_bundle(industry="IT Services"))["tier"] == "Adjacent"
    assert run_one(base_bundle(industry="Insurance"))["tier"] == "Outside"


# --- §4.7 v3 quality engine --------------------------------------------------------------

def test_quality_score_weights():
    assert scoring.quality_score(q=80, g=60, d=40, m=20) == pytest.approx(58.0)
    assert scoring.W_QUALITY == {"q": 0.40, "g": 0.25, "d": 0.20, "m": 0.15}
    assert (scoring.GATE_V_PCTL, scoring.PERSISTENCE_QUARTERS, scoring.EXIT_RANK,
            scoring.EXIT_V_PCTL, scoring.SLOTS) == (20.0, 2, 40, 5.0, 15)


def test_quality_score_stored_for_graded_only():
    row = run_one(base_bundle())
    p = row["pillars"]
    expected = 0.40 * p["q"] + 0.25 * p["g"] + 0.20 * p["d"] + 0.15 * p["m"]
    assert row["quality_score"] == pytest.approx(expected, abs=0.2)
    bad = base_bundle()
    set_all_balances(bad, **{"Total Debt": 5e9, "Cash And Cash Equivalents": 0.0})
    assert run_one(bad)["quality_score"] is None


# --- §4.8 margin of safety ---------------------------------------------------------------

def test_dcf_positive_and_wacc_monotonic():
    lo = scoring.dcf_intrinsic(100e6, 0.10, 0.08)
    hi = scoring.dcf_intrinsic(100e6, 0.10, 0.12)
    assert lo > 0 and hi > 0
    assert hi < lo


def test_wacc_clamped():
    assert scoring.wacc_estimate(market_cap=1e9, total_debt=0, cash=0) == pytest.approx(0.105)
    w = scoring.wacc_estimate(market_cap=1e9, total_debt=50e9, cash=0, interest_coverage=0.5)
    assert 0.06 <= w <= 0.20


def test_margin_of_safety_healthy_name():
    mos = scoring.margin_of_safety(base_bundle())
    assert mos is not None
    assert mos["intrinsic_value"] > 0
    assert mos["base_fcf"] == pytest.approx(212e6)     # TTM > 0.85 * 210e6 annual avg
    assert mos["mos_pct"] == pytest.approx(
        (mos["intrinsic_value"] - 10e9) / 10e9)
    assert 0.06 <= mos["wacc"] <= 0.20
    assert mos["growth"] == pytest.approx(0.0914, abs=0.002)   # revenue CAGR, under cap


def test_margin_of_safety_none_for_burner():
    assert scoring.margin_of_safety(_burner(base_bundle(), ttm_positive=False)) is None


def test_margin_of_safety_mega_cap_growth_cap():
    b = base_bundle()
    b["market_cap"] = 250e9
    for i, pe in enumerate(YEARS):                     # 20%/yr revenue CAGR
        b["annual"]["income"][pe]["Total Revenue"] = 1.0e9 * 1.2 ** i
    assert scoring.margin_of_safety(b)["growth"] == pytest.approx(0.10)


# --- §4.8 Buffett checklist --------------------------------------------------------------

def test_buffett_13_of_13():
    b = base_bundle()
    for i, pe in enumerate(YEARS):
        rev = b["annual"]["income"][pe]["Total Revenue"]
        b["annual"]["income"][pe]["Operating Income"] = 0.25 * rev    # 25% margin, stable
        b["annual"]["income"][pe]["Net Income"] = 200e6 + i * 10e6    # ROE 20%+, rising
    chk = scoring.buffett_checklist(b)
    assert chk["max"] == 13
    assert chk["score"] == 13
    assert len(chk["items"]) == 7
    assert all(i["pass"] for i in chk["items"])


def test_buffett_6_of_13():
    b = base_bundle()
    for pe in YEARS:
        rev = b["annual"]["income"][pe]["Total Revenue"]
        b["annual"]["income"][pe]["Operating Income"] = 0.16 * rev    # 16%: +2 but no moat
        b["annual"]["income"][pe]["Net Income"] = 100e6               # ROE 10%: 0 pts
        b["annual"]["balance"][pe]["Total Debt"] = 600e6              # D/E 0.6: 0 pts
    chk = scoring.buffett_checklist(b)                                # CR 2.0 +1, NI flat +3
    assert chk["score"] == 6
    assert chk["max"] == 13


def test_buffett_none_without_annual_income():
    b = base_bundle()
    b["annual"]["income"] = {}
    assert scoring.buffett_checklist(b) is None


# --- §4.8 proposal portfolio -------------------------------------------------------------

def test_portfolio_clamps_and_cash():
    scored = [{"symbol": "AAA", "composite": 90.0}, {"symbol": "BBB", "composite": 60.0},
              {"symbol": "VET", "composite": None}]                  # abstention excluded
    port = scoring.build_portfolio(scored)
    syms = {p["symbol"] for p in port["positions"]}
    assert syms == {"AAA", "BBB"}
    assert all(p["weight"] == pytest.approx(0.10) for p in port["positions"])
    assert port["cash"] == pytest.approx(0.80)
    assert {c["ticker"] for c in port["clamps"]} == {"AAA", "BBB"}
    assert all(c["limit"] == "max_position_pct" for c in port["clamps"])
    assert port["positions"][0]["conviction"] == 90.0                # ranked by weight/sym


def test_portfolio_no_clamps_when_diversified():
    scored = [{"symbol": f"S{i:02d}", "composite": 50.0} for i in range(12)]
    port = scoring.build_portfolio(scored)
    assert len(port["positions"]) == 12
    assert all(p["weight"] == pytest.approx(1 / 12) for p in port["positions"])
    assert port["cash"] == pytest.approx(0.0, abs=1e-9)
    assert port["clamps"] == []


def test_portfolio_top_n_and_empty():
    scored = [{"symbol": f"S{i:02d}", "composite": float(i)} for i in range(1, 21)]
    port = scoring.build_portfolio(scored, top_n=15)
    assert len(port["positions"]) == 15
    assert port["positions"][0]["symbol"] == "S20"                   # highest conviction
    assert scoring.build_portfolio([]) == {"positions": [], "cash": 1.0, "clamps": []}


# --- deep-copy hygiene: score_universe must not mutate its input -------------------------

def test_score_universe_does_not_mutate_bundles():
    b = base_bundle()
    snapshot = copy.deepcopy(b)
    scoring.score_universe([b])
    assert b == snapshot


def test_buffett_checklist_judges_a_decade_not_two():
    # EDGAR serves ~19 annual periods. Over that span "net income non-decreasing every
    # year" and "ROE > 15% in >=80% of years" are all but unreachable, so two of the three
    # legs quietly died and the consensus lens they feed could never turn green. The window
    # is capped at BUFFETT_WINDOW_YEARS (the reference implementation's limit=8).
    def year(n, ni, equity):
        return f"20{n:02d}-12-31", ni, equity
    inc, bal = {}, {}
    for i in range(19):                       # oldest years are weak, recent 8 are strong
        pe = f"{2007 + i}-12-31"
        strong = i >= 11
        inc[pe] = {"Net Income": 100.0 + i, "Operating Income": 40.0 if strong else 5.0,
                   "Total Revenue": 100.0}
        bal[pe] = {"Stockholders Equity": 100.0 if strong else 1000.0,
                   "Total Debt": 10.0, "Current Assets": 300.0, "Current Liabilities": 100.0}
    card = scoring.buffett_checklist({"annual": {"income": inc, "balance": bal}})
    items = {i["name"]: i for i in card["items"]}
    moat = items["Moat: ROE consistency"]
    assert moat["points"] == 2, moat["detail"]        # 100% of the recent 8, not 42% of 19
    assert "of 8 periods" in moat["detail"]
    # and the consistency leg reads only that window too
    assert "8 annual NI periods" in items["Earnings consistency (NI non-decreasing)"]["detail"]
    assert scoring.BUFFETT_WINDOW_YEARS == 8
