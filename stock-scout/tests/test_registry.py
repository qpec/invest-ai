"""Registry v2 — the richer vocabulary, held to the same discipline as the old one.

Fully offline (R15). The load-bearing property — the frozen decision layer is
bit-identical with supplements present — was proven on the full 1,904-name universe
(0 differing values, 2026-08-03); here the same property is held structurally.
"""
from __future__ import annotations

import pytest

import pit
import registry
import scoring
import thesis


def entry(end, filed, val, start=None):
    e = {"end": end, "filed": filed, "form": "10-K", "val": val}
    if start:
        e["start"] = start
    return e


def concept(*entries, unit="USD"):
    return {"label": "x", "units": {unit: list(entries)}}


def facts_payload(us_gaap):
    return {"cik": None, "entityName": None, pit.SYMBOL_KEY: "AAA",
            "facts": {"us-gaap": us_gaap}}


def year_flow(tag_values, start_year=2022):
    """{year_offset: value} -> full-year duration entries filed the following Feb."""
    out = []
    for offset, value in tag_values.items():
        year = start_year + offset
        out.append(entry(f"{year}-12-31", f"{year + 1}-02-15", value,
                         start=f"{year}-01-01"))
    return out


def build_bundle(us_gaap, as_of="2026-08-01"):
    return pit.as_of_bundle(facts_payload(us_gaap), "AAA", None, as_of, {})


BASE = {
    "Revenues": concept(*year_flow({0: 800.0, 1: 900.0, 2: 1000.0})),
    "OperatingIncomeLoss": concept(*year_flow({0: 120.0, 1: 150.0, 2: 200.0})),
    "NetIncomeLoss": concept(*year_flow({0: 80.0, 1: 100.0, 2: 140.0})),
    "GrossProfit": concept(*year_flow({0: 400.0, 1: 460.0, 2: 550.0})),
    "NetCashProvidedByUsedInOperatingActivities":
        concept(*year_flow({0: 150.0, 1: 170.0, 2: 220.0})),
    "PaymentsToAcquirePropertyPlantAndEquipment":
        concept(*year_flow({0: 30.0, 1: 30.0, 2: 40.0})),
    "Assets": concept(entry("2022-12-31", "2023-02-15", 900.0),
                      entry("2023-12-31", "2024-02-15", 1000.0),
                      entry("2024-12-31", "2025-02-15", 1100.0)),
    "StockholdersEquity": concept(entry("2022-12-31", "2023-02-15", 500.0),
                                  entry("2023-12-31", "2024-02-15", 560.0),
                                  entry("2024-12-31", "2025-02-15", 640.0)),
    "CashAndCashEquivalentsAtCarryingValue":
        concept(entry("2022-12-31", "2023-02-15", 100.0),
                entry("2023-12-31", "2024-02-15", 120.0),
                entry("2024-12-31", "2025-02-15", 150.0)),
    "LongTermDebt": concept(entry("2022-12-31", "2023-02-15", 200.0),
                            entry("2023-12-31", "2024-02-15", 200.0),
                            entry("2024-12-31", "2025-02-15", 180.0)),
    "AssetsCurrent": concept(entry("2024-12-31", "2025-02-15", 300.0)),
    "LiabilitiesCurrent": concept(entry("2024-12-31", "2025-02-15", 200.0)),
}


class TestSupplementStream:
    def test_supplements_never_touch_the_statement_sections(self):
        """The hazard the design exists to avoid: a supplement tag with a NEWER period
        than revenue's must not mint a period row inside income/cashflow, where the
        frozen TTM selection would pick it and lose revenue."""
        us_gaap = dict(BASE)
        us_gaap["ResearchAndDevelopmentExpense"] = concept(
            entry("2025-12-31", "2026-03-01", 50.0, start="2025-01-01"))
        bundle = build_bundle(us_gaap)
        income_periods = set((bundle["annual"] or {}).get("income") or {})
        assert "2025-12-31" not in income_periods
        assert "2025-12-31" in bundle["supplements"]["flows"][
            "Research And Development"]["annual"]
        assert scoring.evaluate(bundle)["ttm"]["revenue"] == 1000.0

    def test_pit_filter_applies_to_supplements(self):
        us_gaap = dict(BASE)
        us_gaap["InterestExpense"] = concept(
            entry("2024-12-31", "2026-09-01", 10.0, start="2024-01-01"))  # filed future
        bundle = build_bundle(us_gaap, as_of="2026-08-01")
        assert bundle["supplements"]["flows"]["Interest Expense"]["annual"] == {}

    def test_stale_point_is_refused_not_ratioed(self):
        """A 2019 goodwill over a 2024 asset base is two unrelated numbers."""
        us_gaap = dict(BASE)
        us_gaap["Goodwill"] = concept(entry("2019-12-31", "2020-02-15", 400.0))
        bundle = build_bundle(us_gaap)
        assert registry.extras(bundle)["goodwill_pct"] is None


class TestExtras:
    def test_tier1_metrics_compute_from_plain_statements(self):
        bundle = build_bundle(BASE)
        ex = registry.extras(bundle)
        assert ex["op_margin"] == pytest.approx(20.0)          # 200/1000
        assert ex["capex_intensity"] == pytest.approx(4.0)     # 40/1000
        assert ex["fcf_conversion"] == pytest.approx(180 / 140 * 100)
        assert ex["current_ratio"] == pytest.approx(1.5)
        assert ex["op_margin_mad"] is not None                 # 3 annual points

    def test_windows_match_the_ttm_not_a_lookalike(self):
        """A supplement flow missing the TTM's own period is None — never a sum over
        whatever periods happened to exist."""
        us_gaap = dict(BASE)
        us_gaap["ResearchAndDevelopmentExpense"] = concept(   # only an OLD year tagged
            *year_flow({0: 50.0}))
        bundle = build_bundle(us_gaap)
        assert registry.extras(bundle)["rd_intensity"] is None

    def test_interest_coverage_from_supplement(self):
        us_gaap = dict(BASE)
        us_gaap["InterestExpense"] = concept(*year_flow({2: 20.0}))
        bundle = build_bundle(us_gaap)
        assert registry.extras(bundle)["interest_coverage"] == pytest.approx(10.0)

    def test_capital_allocation_defaults_to_zero_not_unchecked(self):
        """An untagged dividend overwhelmingly means none was paid; None would mark
        every dividend-free compounder UNCHECKED on its capital-return metrics."""
        ex = registry.extras(build_bundle(BASE))
        assert ex["dividends_pct_ocf"] == 0.0
        assert ex["acquisitions_pct_ocf"] == 0.0

    def test_fcf_conversion_refused_against_a_loss(self):
        us_gaap = dict(BASE)
        us_gaap["NetIncomeLoss"] = concept(*year_flow({0: -10.0, 1: -10.0, 2: -5.0}))
        ex = registry.extras(build_bundle(us_gaap))
        assert ex["fcf_conversion"] is None

    def test_incremental_roic_refuses_a_shrinking_capital_base(self):
        us_gaap = dict(BASE)
        us_gaap["StockholdersEquity"] = concept(
            entry("2022-12-31", "2023-02-15", 900.0),
            entry("2023-12-31", "2024-02-15", 700.0),
            entry("2024-12-31", "2025-02-15", 500.0))
        ex = registry.extras(build_bundle(us_gaap))
        assert ex["incremental_roic"] is None

    def test_extras_can_never_shadow_the_decision_layer(self):
        """registry_evaluate merges extras FIRST, evaluate second — if both dicts ever
        carried the same key, the frozen layer's value wins."""
        bundle = build_bundle(BASE)
        merged = thesis.registry_evaluate(bundle)
        evaluated = scoring.evaluate(bundle)
        for key, value in evaluated.items():
            assert merged[key] == value or (merged[key] is value)


class TestMetricsDeclaration:
    def test_every_metric_resolves_through_registry_evaluate(self):
        bundle = build_bundle(BASE)
        evaluated = thesis.registry_evaluate(bundle)
        for name in thesis.METRICS:
            thesis.metric_value(name, bundle, evaluated)   # KeyError = a broken mapping

    def test_no_price_metric_entered_the_registry(self):
        """FR4/FR7: v2 added no quote-derived quantity. The one legacy exception is the
        EV yield, named here so a future addition has to argue with this test."""
        quote_derived = {"owner_fcf_yield_pct"}
        for name, (key, _, _t) in thesis.METRICS.items():
            if name in quote_derived:
                continue
            assert key not in ("v_yield", "p_ofcf", "mos_pct"), name

    def test_a_new_metric_trigger_flows_through_the_monitor(self):
        import monitor
        trigger = {"id": "t", "kind": "metric", "action": "review", "statement": "",
                   "metric": "interest_coverage_x", "op": "<", "threshold": 4.0,
                   "consecutive_checks": 1, "question": None}
        outcome = monitor.check_trigger(trigger, symbol="AAA", bundle={},
                                        evaluated={"interest_coverage": 2.5},
                                        as_of="2026-08-08")
        assert outcome["checked"] and outcome["tripped"]


class TestComposites:
    def test_composites_report_how_much_was_measured(self):
        comp = registry.composites(build_bundle(BASE))
        p = comp["piotroski"]
        assert p["of"] == 9 and 0 < p["measured"] <= 9
        assert p["score"] <= p["measured"]

    def test_altman_refuses_partial_inputs(self):
        comp = registry.composites(build_bundle(BASE))   # no mcap, no retained earnings
        assert comp["altman"]["z"] is None and comp["altman"]["zone"] is None

    def test_composites_are_not_trigger_capable(self):
        """The constitutional seam: no composite key exists in the METRICS registry, so
        validate() refuses any trigger naming one."""
        for name, (key, _, _t) in thesis.METRICS.items():
            assert "piotroski" not in key and "altman" not in key, name
        doc = {"symbol": "AAA", "triggers": [
            {"id": "t", "kind": "metric", "action": "break", "statement": "",
             "metric": "piotroski_f", "op": "<", "threshold": 4,
             "consecutive_checks": 1, "question": None}]}
        problems = thesis.validate(doc)
        assert any("not in" in p and "registry" in p for p in problems)


class TestOracle:
    def test_formulas_agree_with_financetoolkit(self):
        """FinanceToolkit (MIT) is the adopted desk-side ratio canon; its pure functions
        double as an oracle. Skipped when the research extra is not installed."""
        # financetoolkit's package __init__ transitively imports yaml, which its own
        # dist does not declare — the research extra installs pyyaml beside it. Without
        # both, this oracle skips (and says so) rather than red-barring the suite.
        ft_liquidity = pytest.importorskip("financetoolkit.ratios.liquidity_model")
        ft_profit = pytest.importorskip("financetoolkit.ratios.profitability_model")
        pd = pytest.importorskip("pandas")
        ours = registry.extras(build_bundle(BASE))
        current = ft_liquidity.get_current_ratio(
            pd.Series([300.0]), pd.Series([200.0])).iloc[0]
        assert ours["current_ratio"] == pytest.approx(current)
        op_margin = ft_profit.get_operating_margin(
            pd.Series([200.0]), pd.Series([1000.0])).iloc[0]
        assert ours["op_margin"] == pytest.approx(op_margin * 100.0)


class TestCapexIsGrossCapex:
    def test_capex_intensity_is_not_the_owner_fcf_residual(self):
        """Review 2026-08-03 (self-caught): owner_fcf = OCF - min(|capex|, D&A) - SBC,
        so `ocf - owner_fcf` is maintenance-capex-plus-SBC — NOT capex. With D&A below
        capex and SBC present, the wrong derivation and the right number diverge."""
        us_gaap = dict(BASE)
        us_gaap["DepreciationDepletionAndAmortization"] = concept(*year_flow({2: 10.0}))
        us_gaap["ShareBasedCompensation"] = concept(*year_flow({2: 25.0}))
        bundle = build_bundle(us_gaap)
        ex = registry.extras(bundle)
        assert ex["capex_intensity"] == pytest.approx(4.0)      # 40 / 1000, the real capex
        ttm = scoring.evaluate(bundle)["ttm"]
        residual = ttm["ocf"] - ttm["owner_fcf"]                # = min(40,10) + 25 = 35
        assert residual != 40.0                                 # the trap, demonstrated


class TestReviewRegressions2:
    def test_tagged_but_wrong_cadence_is_unmeasured_not_zero(self):
        """Review 2026-08-03: a 10-K-only dividend filer under a quarterly TTM read as
        0% capital return. Tagged-but-not-summable is UNCHECKED, never zero."""
        us_gaap = {k: v for k, v in BASE.items()}
        # quarterly TTM basis: four common income+cashflow quarters in the newest year
        for tag, yearly in (("Revenues", 1000.0),
                            ("NetCashProvidedByUsedInOperatingActivities", 220.0),
                            ("PaymentsToAcquirePropertyPlantAndEquipment", 40.0)):
            entries = list(us_gaap[tag]["units"]["USD"])
            for q in range(4):
                start = f"2024-{q * 3 + 1:02d}-01"
                end = [f"2024-03-31", f"2024-06-30", f"2024-09-30", f"2024-12-31"][q]
                entries.append(entry(end, "2025-02-15", yearly / 4, start=start))
            us_gaap[tag] = concept(*entries)
        us_gaap["PaymentsOfDividends"] = concept(*year_flow({2: 80.0}))  # FY only
        bundle = build_bundle(us_gaap)
        assert scoring.evaluate(bundle)["ttm"]["basis"] == "quarterly"
        ex = registry.extras(bundle)
        assert ex["dividends_pct_ocf"] is None          # tagged, not summable -> refuse
        assert ex["acquisitions_pct_ocf"] == 0.0        # truly untagged -> genuinely none

    def test_incremental_roic_needs_a_material_capital_base(self):
        """Review 2026-08-03: IC near zero with a tiny positive delta published a
        five-digit percentage. A capital-light business has no incremental ROIC."""
        us_gaap = dict(BASE)
        us_gaap["Revenues"] = concept(*year_flow({0: 800.0, 1: 850.0, 2: 900.0,
                                                  3: 1000.0}, start_year=2021))
        us_gaap["OperatingIncomeLoss"] = concept(*year_flow(
            {0: 120.0, 1: 140.0, 2: 160.0, 3: 200.0}, start_year=2021))
        # IC ~ 3-5 against assets of 1,100: immaterial base, growing slightly
        us_gaap["StockholdersEquity"] = concept(
            *[entry(f"{y}-12-31", f"{y + 1}-02-15", v)
              for y, v in ((2021, 903.0), (2022, 904.0), (2023, 904.5), (2024, 905.0))])
        us_gaap["CashAndCashEquivalentsAtCarryingValue"] = concept(
            *[entry(f"{y}-12-31", f"{y + 1}-02-15", 1100.0)
              for y in (2021, 2022, 2023, 2024)])
        us_gaap["LongTermDebt"] = concept(
            *[entry(f"{y}-12-31", f"{y + 1}-02-15", 200.0)
              for y in (2021, 2022, 2023, 2024)])
        us_gaap["Assets"] = concept(
            *[entry(f"{y}-12-31", f"{y + 1}-02-15", 1100.0)
              for y in (2021, 2022, 2023, 2024)])
        assert registry.extras(build_bundle(us_gaap))["incremental_roic"] is None

    def test_incremental_roic_happy_path_over_four_years(self):
        us_gaap = dict(BASE)
        us_gaap["Revenues"] = concept(*year_flow(
            {0: 700.0, 1: 800.0, 2: 900.0, 3: 1000.0}, start_year=2021))
        us_gaap["OperatingIncomeLoss"] = concept(*year_flow(
            {0: 100.0, 1: 120.0, 2: 150.0, 3: 200.0}, start_year=2021))
        us_gaap["StockholdersEquity"] = concept(
            *[entry(f"{y}-12-31", f"{y + 1}-02-15", v)
              for y, v in ((2021, 400.0), (2022, 500.0), (2023, 560.0), (2024, 640.0))])
        us_gaap["CashAndCashEquivalentsAtCarryingValue"] = concept(
            *[entry(f"{y}-12-31", f"{y + 1}-02-15", 100.0)
              for y in (2021, 2022, 2023, 2024)])
        us_gaap["LongTermDebt"] = concept(
            *[entry(f"{y}-12-31", f"{y + 1}-02-15", 200.0)
              for y in (2021, 2022, 2023, 2024)])
        us_gaap["Assets"] = concept(
            *[entry(f"{y}-12-31", f"{y + 1}-02-15", 1100.0)
              for y in (2021, 2022, 2023, 2024)])
        ex = registry.extras(build_bundle(us_gaap))
        # dNOPAT = (200-100)*0.75 = 75; dIC = 740-500 = 240 -> 31.25%
        assert ex["incremental_roic"] == pytest.approx(31.25)

    def test_cross_tag_differencing_cannot_fabricate_a_quarter(self):
        """Review 2026-08-03 (the CRM case): FY tagged under one D&A concept, YTDs under
        another — the chain-merge-then-difference path booked a NEGATIVE fourth quarter.
        Flows now derive per tag, so no cross-tag subtraction can exist."""
        us_gaap = dict(BASE)
        us_gaap["DepreciationDepletionAndAmortization"] = concept(   # FY only, narrower
            entry("2024-12-31", "2025-02-15", 1200.0, start="2024-01-01"))
        us_gaap["DepreciationAndAmortization"] = concept(            # YTDs, fuller
            entry("2024-03-31", "2024-05-15", 900.0, start="2024-01-01"),
            entry("2024-09-30", "2024-11-15", 2511.0, start="2024-01-01"))
        bundle = build_bundle(us_gaap)
        cf_q = (bundle.get("quarterly") or {}).get("cashflow") or {}
        derived = [scoring._row(row, "da") for row in cf_q.values()]
        assert all(v is None or v >= 0 for v in derived), derived

    def test_supplement_dividend_chain_is_the_statement_chain(self):
        """Review 2026-08-03: the supplement chain shipped narrower than the statement
        chain, and zero-default turned the drift into a confident 0%."""
        assert pit._SUPPLEMENT_FLOW_CONCEPTS["Cash Dividends Paid"] \
            == pit._CASHFLOW_CONCEPTS["Cash Dividends Paid"]
        assert pit._SUPPLEMENT_FLOW_CONCEPTS["Repurchase Of Capital Stock"] \
            == pit._CASHFLOW_CONCEPTS["Repurchase Of Capital Stock"]
