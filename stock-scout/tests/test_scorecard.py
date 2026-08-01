"""Offline tests for scorecard.py — the Owner's Scorecard (docs/SCORECARD-DESIGN.md).

Synthetic bundles only; no network, no files, no clock. Covers the §2 ramp (cliff-free,
clamped, inverted metrics, the ratified 15% ROIC line at the midpoint), the §5 bands and
consensus, and every §4 honesty rule: no price no verdict, missing inputs shrinking the
denominator, vetoes suppressing the score — plus the core claim of the redesign, that a
name's scorecard does not move when the universe around it does.
"""
import copy

import pytest

import scorecard
import scoring

YEARS = ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
QTRS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]

GOOD_BAL = {
    "Total Debt": 200e6, "Cash And Cash Equivalents": 800e6, "Working Capital": 500e6,
    "Total Assets": 2.5e9, "Current Assets": 1.2e9, "Current Liabilities": 600e6,
    "Stockholders Equity": 1.6e9, "Minority Interest": 0.0,
}
WRECK_BAL = {
    "Total Debt": 260e6, "Cash And Cash Equivalents": 40e6, "Working Capital": 100e6,
    "Total Assets": 900e6, "Current Assets": 300e6, "Current Liabilities": 350e6,
    "Stockholders Equity": 400e6, "Minority Interest": 0.0,
}
SHARES = 98e6


def wonderful(symbol="AAA"):
    """A wonderful business at a fair price: 36% ROIC, 70% gross margin, 30% owner-FCF
    margin, 12%/yr growth, net cash, buying back 2%/yr of its own stock, ~6.6% owner-FCF
    yield on EV. Quarterly TTM basis: revenue 1.2e9, EBIT 360e6, owner-FCF 356e6."""
    ann_inc, ann_bal, ann_cf = {}, {}, {}
    for i, pe in enumerate(YEARS):
        rev = 1.0e9 * 1.12 ** i
        ann_inc[pe] = {
            "Total Revenue": rev, "EBIT": 0.30 * rev, "EBITDA": 0.35 * rev,
            "Gross Profit": 0.70 * rev, "Operating Income": 0.30 * rev,
            "Net Income": 0.22 * rev,
            "Net Income Including Noncontrolling Interests": 0.22 * rev,
            "Interest Expense": 12e6,
        }
        ann_bal[pe] = dict(GOOD_BAL)
        ann_cf[pe] = {
            "Operating Cash Flow": 0.36 * rev, "Capital Expenditure": -0.04 * rev,
            "Depreciation And Amortization": 0.05 * rev,
            "Stock Based Compensation": 0.03 * rev,
            "Cash Dividends Paid": -0.06 * rev,
            "Repurchase Of Capital Stock": -0.10 * rev,
        }
    q_inc = {pe: {"Total Revenue": 300e6, "EBIT": 90e6, "EBITDA": 105e6,
                  "Gross Profit": 210e6, "Operating Income": 90e6, "Net Income": 70e6,
                  "Net Income Including Noncontrolling Interests": 70e6,
                  "Interest Expense": 3e6} for pe in QTRS}
    q_cf = {pe: {"Operating Cash Flow": 110e6, "Capital Expenditure": -12e6,
                 "Depreciation And Amortization": 15e6,
                 "Stock Based Compensation": 9e6} for pe in QTRS}
    return {
        "symbol": symbol, "sector": "Information Technology", "industry": "Software",
        "name": f"{symbol} Corp",
        "market_cap": 6.0e9, "yahoo_ev": None, "price": 6.0e9 / SHARES,
        "shares_series": [["2021-06-30", 106.1208e6], ["2022-06-30", 104.04e6],
                          ["2023-06-30", 102.0e6], ["2024-06-30", 100.0e6],
                          ["2025-06-30", SHARES]],
        "annual": {"income": ann_inc, "balance": ann_bal, "cashflow": ann_cf},
        "quarterly": {"income": q_inc, "balance": {"2025-12-31": dict(GOOD_BAL)},
                      "cashflow": q_cf},
    }


def cheap_wreck(symbol="ZZZ"):
    """§1.6's forbidden trade: a terrific price on a broken business. 3% ROIC, gross margin
    sliding 25% -> 10%, flat revenue, owner-FCF negative in half the annual periods, 6%/yr
    dilution, +11%-of-revenue accruals, levered just under the §4.4 veto — priced at 8.8%
    owner-FCF yield and a +60% margin of safety."""
    ann_inc, ann_bal, ann_cf = {}, {}, {}
    for i, pe in enumerate(YEARS):
        rev = 1.0e9
        ann_inc[pe] = {
            "Total Revenue": rev, "EBIT": 0.02 * rev, "EBITDA": 0.06 * rev,
            "Gross Profit": (0.25 - 0.05 * i) * rev, "Operating Income": 0.02 * rev,
            "Net Income": 0.25 * rev,
            "Net Income Including Noncontrolling Interests": 0.25 * rev,
            "Interest Expense": 15e6,
        }
        ann_bal[pe] = dict(WRECK_BAL)
        ann_cf[pe] = {
            "Operating Cash Flow": (0.05 if i < 2 else 0.14) * rev,
            "Capital Expenditure": -0.03 * rev,
            "Depreciation And Amortization": 0.04 * rev,
            "Stock Based Compensation": 0.08 * rev,
        }
    return {
        "symbol": symbol, "sector": "Information Technology", "industry": "Software",
        "name": f"{symbol} Corp",
        "market_cap": 120e6, "yahoo_ev": None, "price": 120e6 / 60e6,
        "shares_series": [["2023-06-30", 53.4e6], ["2024-06-30", 56.6e6],
                          ["2025-06-30", 60.0e6]],
        "annual": {"income": ann_inc, "balance": ann_bal, "cashflow": ann_cf},
        "quarterly": {},
    }


def card_of(bundle):
    """The scorecard on the §3.3 row score_universe() produces for this same bundle."""
    return scorecard.scorecard(bundle, scored_row=scoring.score_universe([bundle])[0])


# --- §2 the anchor table and the scoring rule --------------------------------------------

def test_anchor_table_sums_to_the_block_maxima_and_to_100():
    for block, total in scorecard.BLOCKS.items():
        assert sum(a["points"] for a in scorecard.ANCHORS.values()
                   if a["block"] == block) == total
    assert sum(scorecard.BLOCKS.values()) == 100 == scorecard.FULL_MAX
    assert 2 * len(scorecard.ANCHORS) == 28          # the design §3 anchor count
    for metric_id, a in scorecard.ANCHORS.items():
        assert a["invert"] is (a["target"] < a["floor"]), metric_id
        assert a["provenance"] and a["label"] and a["unit"] in scorecard._RENDER


def test_ramp_is_clamped_at_both_ends():
    assert scorecard.ramp(5.0, 5.0, 25.0, 12) == 0.0
    assert scorecard.ramp(-500.0, 5.0, 25.0, 12) == 0.0
    assert scorecard.ramp(25.0, 5.0, 25.0, 12) == 12.0
    assert scorecard.ramp(1000.0, 5.0, 25.0, 12) == 12.0


def test_ramp_is_linear_and_cliff_free():
    assert scorecard.ramp(15.0, 5.0, 25.0, 12) == pytest.approx(6.0)
    assert scorecard.ramp(10.0, 5.0, 25.0, 12) == pytest.approx(3.0)
    assert scorecard.ramp(20.0, 5.0, 25.0, 12) == pytest.approx(9.0)
    # No cliff at the ratified line: 14.9% is not punished relative to 15.1% (§2).
    just_below = scorecard.ramp(14.9, 5.0, 25.0, 12)
    just_above = scorecard.ramp(15.1, 5.0, 25.0, 12)
    assert just_above - just_below == pytest.approx(0.12, abs=1e-6)
    # Monotone non-decreasing across the whole span, with no jump larger than one step.
    steps = [scorecard.ramp(v / 10.0, 5.0, 25.0, 12) for v in range(0, 400)]
    assert all(b >= a for a, b in zip(steps, steps[1:]))
    assert max(b - a for a, b in zip(steps, steps[1:])) <= 0.061


def test_ramp_rejects_a_zero_width_anchor_pair():
    with pytest.raises(ValueError):
        scorecard.ramp(1.0, 3.0, 3.0, 5)


def test_roic_ramp_puts_the_ratified_15pct_line_at_the_midpoint():
    """The design claims scoring.QV_ROIC_MIN lands at exactly the midpoint — prove it."""
    line = 100.0 * scoring.QV_ROIC_MIN
    anchor = scorecard.ANCHORS["roic"]
    assert line == (anchor["floor"] + anchor["target"]) / 2.0
    scored = scorecard.score_metric("roic", line)
    assert scored["points"] == 6.0 and scored["max"] == 12 and scored["pct"] == 50


@pytest.mark.parametrize("metric_id, worse, better", [
    ("net_debt_ebitda", 4.0, 0.0),
    ("sbc", 10.0, 2.0),
    ("accruals", 10.0, 0.0),
    ("share_count_trend", 5.0, -2.0),
    ("gross_margin_cv", 0.35, 0.05),
])
def test_inverted_metrics_score_in_the_right_direction(metric_id, worse, better):
    anchor = scorecard.ANCHORS[metric_id]
    assert anchor["invert"] is True
    assert scorecard.score_metric(metric_id, worse)["points"] == 0.0
    assert scorecard.score_metric(metric_id, better)["points"] == float(anchor["points"])
    # Beyond the target is still full marks, beyond the floor is still zero — no negatives.
    beyond = better - (worse - better)
    assert scorecard.score_metric(metric_id, beyond)["points"] == float(anchor["points"])
    assert scorecard.score_metric(metric_id, worse + 1.0)["points"] == 0.0
    midpoint = (worse + better) / 2.0
    assert scorecard.score_metric(metric_id, midpoint)["points"] == pytest.approx(
        anchor["points"] / 2.0, abs=0.05)


def test_score_metric_reports_the_value_its_own_unit_and_its_share():
    sbc = scorecard.score_metric("sbc", 11.0)
    assert sbc["points"] == 0.0 and sbc["pct"] == 0
    assert "11% of revenue" in sbc["detail"]
    yield_ = scorecard.score_metric("owner_fcf_yield", 0.08)
    assert yield_["points"] == 15.0 and "8.0%" in yield_["detail"]
    mos = scorecard.score_metric("margin_of_safety", 0.50)
    assert mos["points"] == 10.0 and "+50%" in mos["detail"]


def test_score_metric_without_a_value_is_not_a_zero():
    missing = scorecard.score_metric("roic", None)
    assert missing["points"] is None and missing["pct"] is None
    assert missing["max"] == 12 and "not computable" in missing["detail"]


# --- §1.6 / §5 the whole card ------------------------------------------------------------

def test_wonderful_business_at_a_fair_price_lands_high():
    card = card_of(wonderful())
    assert card["band"] in {"Exceptional", "Strong"}
    assert card["pct"] >= 80
    assert card["available_max"] == 100          # nothing missing in this bundle
    assert card["blocks"]["quality"]["points"] >= 30
    assert card["blocks"]["safety"]["points"] >= 20
    assert card["blocks"]["stewardship"]["points"] == 15
    assert card["score"] == pytest.approx(
        sum(b["points"] for b in card["blocks"].values()), abs=0.05)
    assert card["veto"]["vetoed"] is False


def test_a_terrific_price_does_not_paper_over_a_broken_business():
    """§1.6: the trade the framework forbids. Price block full, verdict still Pass."""
    card = card_of(cheap_wreck())
    assert card["blocks"]["price"]["points"] == 25.0     # as cheap as the scorecard allows
    assert card["blocks"]["quality"]["points"] < 5.0
    assert card["pct"] < 50 and card["band"] in {"Pass", "Weak"}
    assert card["veto"]["vetoed"] is False               # not vetoed — genuinely scored


def test_bands_follow_the_section_5_table():
    for pct, band in ((100, "Exceptional"), (80, "Exceptional"), (79, "Strong"),
                      (65, "Strong"), (64, "Mixed"), (50, "Mixed"), (49, "Weak"),
                      (35, "Weak"), (34, "Pass"), (0, "Pass")):
        assert scorecard._band_of(pct)["band"] == band
    assert {e["band"] for e in scorecard.BANDS} == {
        "Exceptional", "Strong", "Mixed", "Weak", "Pass", "VETOED", "NO PRICE"}


def test_pct_carries_no_false_precision():
    card = card_of(wonderful())
    assert isinstance(card["pct"], int)
    for metric in card["metrics"].values():
        assert metric["pct"] is None or isinstance(metric["pct"], int)
    assert card["notes"][-1] == "Differences under 5 points are not meaningful (§4.4)."
    assert scorecard.NOISE_FLOOR == 5.0


# --- §4.1 no price, no verdict -----------------------------------------------------------

def test_no_price_no_verdict():
    bundle = wonderful()
    bundle["market_cap"] = None                  # no market cap -> no EV, no yield, no MoS
    bundle["price"] = None
    card = card_of(bundle)

    assert card["band"] == "NO PRICE"
    assert "not a verdict" in card["band_meaning"].lower()
    assert "quality profile" in card["band_meaning"].lower()
    assert card["blocks"]["price"] == {"points": 0.0, "max": 0, "metrics": []}
    assert card["available_max"] == 75           # the quality side, reported honestly
    assert card["score"] == pytest.approx(card["available_max"], abs=25)
    assert {m["metric"] for m in card["coverage"]["missing"]} == {
        "owner_fcf_yield", "margin_of_safety"}
    assert any("not a verdict" in note for note in card["notes"])
    # Nothing in the output presents a 0-100 verdict: the band is not a §5 numeric band.
    assert card["band"] not in {e["band"] for e in scorecard.BANDS if e["floor"] is not None}
    assert card["consensus"]["lenses"]["scorecard"] is None


# --- §4.2 missing inputs shrink the denominator ------------------------------------------

def test_missing_metrics_shrink_available_max_and_are_named():
    bundle = wonderful()
    for statement in (bundle["annual"]["income"], bundle["quarterly"]["income"]):
        for cell in statement.values():
            del cell["Gross Profit"]
    card = card_of(bundle)

    assert card["metrics"]["gross_margin"]["points"] is None      # not a silent 0
    assert card["metrics"]["gross_margin_cv"]["points"] is None
    assert card["available_max"] == 100 - 6 - 5
    assert card["coverage"]["missing_points"] == 11
    named = {m["metric"]: m for m in card["coverage"]["missing"]}
    assert set(named) == {"gross_margin", "gross_margin_cv"}
    assert named["gross_margin"]["block"] == "quality" and named["gross_margin"]["reason"]
    assert "CV needs 2" in named["gross_margin_cv"]["reason"]
    assert "gross_margin" not in card["blocks"]["quality"]["metrics"]
    assert card["blocks"]["quality"]["max"] == 35 - 11
    assert any("out of 89 of 100 possible points" in note for note in card["notes"])


def test_a_thin_gross_margin_series_is_unavailable_not_free_points():
    """scoring returns CV 0.0 with <2 usable periods ("no evidence of drift"); handing that
    the full 5 stability points would be a silent full credit for missing data."""
    bundle = wonderful()
    bundle["annual"]["income"] = {YEARS[-1]: bundle["annual"]["income"][YEARS[-1]]}
    card = card_of(bundle)
    assert scoring._gross_margin_cv(bundle) == 0.0
    assert card["metrics"]["gross_margin_cv"]["points"] is None


def test_capital_returned_is_unavailable_without_a_dividend_or_buyback_row():
    bundle = wonderful()
    for cell in bundle["annual"]["cashflow"].values():
        del cell["Cash Dividends Paid"]
        del cell["Repurchase Of Capital Stock"]
    card = card_of(bundle)
    assert card["metrics"]["capital_returned"]["points"] is None
    assert card["available_max"] == 97
    reason = card["coverage"]["missing"][0]["reason"]
    assert "dividend or buyback" in reason and "PIT" in reason


def test_capital_returned_sums_dividends_and_buybacks_over_owner_fcf():
    card = card_of(wonderful())
    # Newest annual period: (6% + 10% of revenue) / owner-FCF (29% of revenue) = 0.55.
    assert card["metrics"]["capital_returned"]["value"] == pytest.approx(0.16 / 0.29, 1e-6)
    assert card["metrics"]["capital_returned"]["points"] == 3.0


def test_share_class_drops_the_share_trend_rather_than_scoring_it():
    """§4.5 declares the trend untrustworthy for these names; the percentile engine parks
    the leg at neutral 50, and an absolute scorecard has no neutral to park it at."""
    bundle = wonderful()
    bundle["shares_series"] = [["2024-06-30", 50e6], ["2025-06-30", 100e6]]   # Up-C shape
    bundle["yahoo_ev"] = 8.0e9                   # units the listed class does not count
    for scope in ("annual", "quarterly"):
        for cell in bundle[scope]["balance"].values():
            cell["Minority Interest"] = 900e6
    row = scoring.score_universe([bundle])[0]
    assert "SHARE_CLASS" in {f["code"] for f in row["flags"]}
    assert row["grade"] != "VETOED"               # §4.4: the flag suppresses the veto too

    card = scorecard.scorecard(bundle, scored_row=row)
    assert card["metrics"]["share_count_trend"]["points"] is None
    assert card["available_max"] == 93
    assert any(m["metric"] == "share_count_trend" and "SHARE_CLASS" in m["reason"]
               for m in card["coverage"]["missing"])


# --- §4.3 vetoes suppress, never rank ----------------------------------------------------

def test_vetoed_row_is_suppressed_with_its_reason():
    bundle = wonderful()
    for scope in ("annual", "quarterly"):
        for cell in bundle[scope]["balance"].values():
            cell["Total Debt"] = 5e9                    # net debt/EBITDA ~ 10 -> §4.4 veto
    row = scoring.score_universe([bundle])[0]
    assert row["grade"] == "VETOED"

    card = scorecard.scorecard(bundle, scored_row=row)
    assert card["band"] == "VETOED"
    assert card["score"] is None and card["pct"] is None
    assert card["veto"]["vetoed"] is True
    assert "leverage veto" in card["band_meaning"]
    assert card["band_meaning"] == row["veto"]["reason"]
    assert any("suppressed" in note for note in card["notes"])
    assert card["consensus"]["lenses"]["scorecard"] is False


def test_the_veto_layer_also_runs_on_the_bundle_only_path():
    bundle = wonderful()
    for scope in ("annual", "quarterly"):
        for cell in bundle[scope]["balance"].values():
            cell["Total Debt"] = 5e9
    card = scorecard.scorecard(bundle)                  # no scored_row supplied
    assert card["band"] == "VETOED" and card["score"] is None


# --- §5 why, in words --------------------------------------------------------------------

def test_why_names_the_genuinely_strongest_and_weakest_metric():
    card = card_of(cheap_wreck())
    why = card["why"]
    # Strongest: the owner-FCF yield is full marks and has the most points at stake.
    assert why["strongest"]["metric"] == "owner_fcf_yield"
    assert why["strongest"]["points"] == 15.0 and why["strongest"]["pct"] == 100
    assert why["strongest"]["sentence"].startswith("carried by owner-FCF yield on EV at ")
    assert why["strongest"]["sentence"].endswith("(15.0/15)")
    # Weakest: ROIC scores nothing and is the biggest of the zero-scoring metrics.
    assert why["weakest"]["metric"] == "roic"
    assert why["weakest"]["sentence"] == "held back by ROIC at 3% (0.0/12)"


def test_why_on_a_wonderful_business_points_at_its_own_ceiling():
    why = card_of(wonderful())["why"]
    assert why["strongest"]["metric"] == "roic"         # full marks, most points at stake
    assert why["strongest"]["sentence"] == "carried by ROIC at 36% (12.0/12)"
    assert why["weakest"]["pct"] < 100


# --- §5 consensus ------------------------------------------------------------------------

def test_consensus_three_of_three_on_the_wonderful_business():
    bundle = wonderful()
    card = card_of(bundle)
    assert card["consensus"] == scorecard.consensus(
        card, scoring.margin_of_safety(bundle), scoring.buffett_checklist(bundle))
    assert card["consensus"]["green"] == 3 and card["consensus"]["of"] == 3
    assert card["consensus"]["lenses"] == {
        "scorecard": True, "margin_of_safety": True, "buffett": True}
    assert card["consensus"]["label"] == "3 of 3 — all three lenses agree"


def test_consensus_counts_only_green_lenses():
    card = {"band": "Mixed", "pct": 55}
    result = scorecard.consensus(card, {"mos_pct": 0.4}, {"score": 4, "max": 13})
    assert result["green"] == 1 and result["of"] == 3
    assert result["lenses"] == {"scorecard": False, "margin_of_safety": True,
                                "buffett": False}
    assert result["label"] == "1 of 3"


def test_consensus_thresholds_are_the_design_lines():
    at_the_line = scorecard.consensus({"band": "Mixed", "pct": 60}, {"mos_pct": 0.0},
                                      {"score": 9, "max": 13})
    assert at_the_line["lenses"] == {"scorecard": True, "margin_of_safety": False,
                                     "buffett": True}
    assert at_the_line["green"] == 2 and at_the_line["label"] == "2 of 3"


def test_consensus_unknown_lens_is_neither_green_nor_a_smaller_denominator():
    result = scorecard.consensus({"band": "Strong", "pct": 72}, None, {"score": 11})
    assert result["lenses"]["margin_of_safety"] is None
    assert result["green"] == 2 and result["of"] == 3
    assert result["label"] == "2 of 3 (1 unknown)"
    assert "no DCF margin of safety" in result["evidence"]["margin_of_safety"]


def test_consensus_with_nothing_known_is_zero_of_three():
    result = scorecard.consensus({"band": "NO PRICE", "pct": 90}, None, None)
    assert result["green"] == 0 and result["of"] == 3
    assert result["label"] == "0 of 3 (3 unknown)"


# --- §2/§6 stability: the core claim of the redesign -------------------------------------

def pool_variant(index):
    """A same-sector peer, perturbed enough to move every sector percentile."""
    bundle = wonderful(f"P{index:02d}")
    bundle["market_cap"] = 2.0e9 + 0.4e9 * index
    for cell in bundle["quarterly"]["cashflow"].values():
        cell["Operating Cash Flow"] = 60e6 + 1.0e6 * index
    for cell in bundle["quarterly"]["income"].values():
        cell["Gross Profit"] = 120e6 + 1.5e6 * index
    return bundle


def test_the_scorecard_does_not_move_when_the_universe_does():
    """The whole point of the redesign: absolute anchors, not peer ranks. The same bundle
    scored alone and scored inside a 50-name pool gives an identical scorecard, while the
    percentile composite it sits next to moves by tens of points."""
    bundle = wonderful()
    alone = scoring.score_universe([copy.deepcopy(bundle)])[0]
    pool = scoring.score_universe(
        [copy.deepcopy(bundle)] + [pool_variant(i) for i in range(49)])
    in_pool = pool[0]
    assert in_pool["symbol"] == "AAA" and len(pool) == 50

    assert scorecard.scorecard(bundle, scored_row=in_pool) == \
        scorecard.scorecard(bundle, scored_row=alone)
    # ... and the percentile composite next to it genuinely did move.
    assert abs(in_pool["composite"] - alone["composite"]) > scorecard.NOISE_FLOOR


def test_the_row_path_and_the_bundle_only_path_agree():
    bundle = wonderful()
    assert card_of(bundle) == scorecard.scorecard(bundle)


def test_an_insufficient_row_still_scores_what_it_can():
    """score_universe suppresses the legs of an INSUFFICIENT name; the scorecard falls back
    to scoring's own assembly of the same bundle rather than reporting an empty card."""
    bundle = wonderful()
    for cell in bundle["quarterly"]["cashflow"].values():
        del cell["Operating Cash Flow"]
    for cell in bundle["annual"]["cashflow"].values():
        del cell["Operating Cash Flow"]
    row = scoring.score_universe([bundle])[0]
    assert row["grade"] == "INSUFFICIENT" and row["legs"] == {}

    card = scorecard.scorecard(bundle, scored_row=row)
    assert card["metrics"]["roic"]["points"] == 12.0        # ROIC is still computable
    assert card["metrics"]["owner_fcf_margin"]["points"] is None
    assert card["available_max"] < 100 and card["band"] == "NO PRICE"


def test_a_row_for_another_symbol_is_refused():
    with pytest.raises(ValueError, match="scored_row is for"):
        scorecard.scorecard(wonderful("AAA"),
                            scored_row=scoring.score_universe([wonderful("BBB")])[0])
