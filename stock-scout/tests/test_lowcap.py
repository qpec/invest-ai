"""Offline tests for lowcap.py — the Low-Cap Desk's pure decision layer
(docs/plans/2026-08-14-low-cap-desk-design.md).

Synthetic bundles only; no network, no files, no clock. What they protect: the lane's
band is a positive claim (a missing figure cannot certify a name small), the Forge
counts severities and never averages, a named finding survives thin evidence while
certified survival does not, every lens keeps "unmeasured" apart from "measured and
fails", and no code path anywhere merges two lenses into one number.
"""
from datetime import date, timedelta

import lowcap
import scoring

YEARS = ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
QTRS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]


def lane_bundle(symbol="LOW"):
    """A healthy lane-scale name ($500M): profitable, self-funding, ROIC ~17%, revenue
    compounding ~11%/yr on stable margins — the compounder lens's home case.

    TTM (quarterly): revenue 260e6, EBIT 44e6, NI 33e6, OCF 48e6.
    Liabilities (identity) 150e6; NCAV 0; net cash +70e6."""
    revenues = [190e6, 210e6, 235e6, 260e6]
    ebits = [32e6, 36e6, 40e6, 44e6]
    incomes = [24e6, 27e6, 30e6, 33e6]
    ann_inc, ann_bal, ann_cf = {}, {}, {}
    bal_cell = {
        "Total Debt": 10e6, "Cash And Cash Equivalents": 80e6,
        "Working Capital": 90e6, "Total Assets": 400e6, "Current Assets": 150e6,
        "Current Liabilities": 60e6, "Stockholders Equity": 250e6,
        "Minority Interest": 0.0,
    }
    for i, pe in enumerate(YEARS):
        ann_inc[pe] = {
            "Total Revenue": revenues[i], "EBIT": ebits[i], "EBITDA": ebits[i] + 10e6,
            "Gross Profit": 0.55 * revenues[i], "Net Income": incomes[i],
            "Net Income Including Noncontrolling Interests": incomes[i],
        }
        ann_bal[pe] = dict(bal_cell)
        ann_cf[pe] = {"Operating Cash Flow": 45e6, "Capital Expenditure": -8e6,
                      "Stock Based Compensation": 2e6,
                      "Depreciation And Amortization": 10e6}
    q_inc, q_cf = {}, {}
    for pe in QTRS:
        q_inc[pe] = {
            "Total Revenue": 65e6, "EBIT": 11e6, "EBITDA": 13.5e6,
            "Gross Profit": 36e6, "Net Income": 8.25e6,
            "Net Income Including Noncontrolling Interests": 8.25e6,
        }
        q_cf[pe] = {"Operating Cash Flow": 12e6, "Capital Expenditure": -2e6,
                    "Stock Based Compensation": 0.5e6,
                    "Depreciation And Amortization": 2.5e6}
    return {
        "symbol": symbol, "name": f"{symbol} Corp",
        "market_cap": 500e6, "price": 10.0,
        "shares_series": [[f"{y}-06-30", 50e6] for y in range(2021, 2026)],
        "annual": {"income": ann_inc, "balance": ann_bal, "cashflow": ann_cf},
        "quarterly": {"income": q_inc, "balance": {"2025-12-31": dict(bal_cell)},
                      "cashflow": q_cf},
    }


def set_all_balances(b, **rows):
    for pe in b["annual"]["balance"]:
        b["annual"]["balance"][pe].update(rows)
    for pe in b["quarterly"]["balance"]:
        b["quarterly"]["balance"][pe].update(rows)


def weekly_grid(closes, start="2024-06-02"):
    day = date.fromisoformat(start)
    grid = {}
    for close in closes:
        grid[day.isoformat()] = {"close": close, "adj_close": close}
        day += timedelta(days=7)
    return grid


def run_forge(bundle, prices=None):
    return lowcap.forge(bundle, evaluated=scoring.evaluate(bundle), prices=prices)


# --- Eligibility: the band is a positive claim --------------------------------------------

class TestEligibility:
    def test_in_band_passes(self):
        ok, reason = lowcap.eligible(lane_bundle())
        assert ok and "inside the lane's band" in reason

    def test_a_missing_market_cap_cannot_certify_small(self):
        """The main desk's floor never excludes on a missing figure; the lane's band is
        the opposite kind of claim — membership NEEDS the qualifying figure."""
        b = lane_bundle()
        b["market_cap"] = None
        ok, reason = lowcap.eligible(b)
        assert not ok and "cannot certify" in reason

    def test_the_band_edges(self):
        for mcap, expected in [(49e6, False), (50e6, True), (1.99e9, True), (2e9, False)]:
            b = lane_bundle()
            b["market_cap"] = mcap
            assert lowcap.eligible(b)[0] is expected, mcap

    def test_the_dollar_line(self):
        b = lane_bundle()
        b["price"] = 0.99
        assert not lowcap.eligible(b)[0]
        b["price"] = None
        assert not lowcap.eligible(b)[0]


# --- The Forge ----------------------------------------------------------------------------

class TestForge:
    def test_a_healthy_name_is_a_survivor(self):
        result = run_forge(lane_bundle())
        assert result["verdict"] == "Survivor"
        assert result["coverage"]["severe"] == 0 and result["coverage"]["caution"] == 0

    def test_trailing_dilution_over_ten_percent_forges_out(self):
        b = lane_bundle()
        b["shares_series"] = [[f"{2021 + i}-06-30", 50e6 * (1.12 ** i)]
                              for i in range(5)]
        result = run_forge(b)
        assert result["probes"]["serial_diluter"]["severity"] == "severe"
        assert result["verdict"] == "Forged-out"
        assert any("Serial diluter" in f for f in result["findings"])

    def test_repeat_dilution_is_severe_even_under_the_trailing_line(self):
        """+6%/yr in 2 of the last 3 years is a serial diluter, though no single year
        crosses 10% — the pattern is the finding."""
        b = lane_bundle()
        b["shares_series"] = [["2021-06-30", 50e6], ["2022-06-30", 50e6],
                              ["2023-06-30", 50e6], ["2024-06-30", 53e6],
                              ["2025-06-30", 56.2e6]]
        probe = run_forge(b)["probes"]["serial_diluter"]
        assert probe["severity"] == "severe"
        assert probe["evidence"]["repeat_years_over_caution"] >= 2

    def test_one_diluting_year_is_a_caution_not_a_severe(self):
        b = lane_bundle()
        b["shares_series"] = [["2021-06-30", 50e6], ["2022-06-30", 50e6],
                              ["2023-06-30", 50e6], ["2024-06-30", 50e6],
                              ["2025-06-30", 53e6]]
        assert run_forge(b)["probes"]["serial_diluter"]["severity"] == "caution"

    def test_a_share_class_name_is_refused_not_measured(self):
        """scoring suppresses its dilution veto for SHARE_CLASS; the Forge mirrors that
        by refusing — an Up-C count mismatch must not read as dilution."""
        b = lane_bundle()
        evaluated = dict(scoring.evaluate(b), share_class=True)
        probe = lowcap.probe_serial_diluter(b, evaluated)
        assert not probe["measured"]

    def test_runway_under_twelve_months_forges_out(self):
        b = lane_bundle()
        for pe in QTRS:
            b["quarterly"]["cashflow"][pe]["Operating Cash Flow"] = -5e6
        set_all_balances(b, **{"Cash And Cash Equivalents": 15e6})
        result = run_forge(b)
        probe = result["probes"]["cash_runway"]
        assert probe["severity"] == "severe" and probe["value"] < 12
        assert result["verdict"] == "Forged-out"

    def test_a_self_funder_has_no_finite_runway(self):
        probe = run_forge(lane_bundle())["probes"]["cash_runway"]
        assert probe["severity"] == "none" and "Self-funding" in probe["detail"]

    def test_the_distress_triad_forges_out(self):
        """Loss-making + leveraged at market + high volatility at once: the cohort CHS
        measured at -17%/yr alpha."""
        b = lane_bundle()
        b["market_cap"] = 300e6
        for pe in YEARS + QTRS:
            scope = "annual" if pe in YEARS else "quarterly"
            b[scope]["income"][pe]["Net Income Including Noncontrolling Interests"] = -6e6
            b[scope]["income"][pe]["Net Income"] = -6e6
        set_all_balances(b, **{"Total Assets": 1e9, "Stockholders Equity": 100e6})
        prices = weekly_grid([10.0 if i % 2 == 0 else 13.0 for i in range(53)])
        result = run_forge(b, prices=prices)
        probe = result["probes"]["distress"]
        assert probe["severity"] == "severe"
        assert all(probe["evidence"]["legs"].values())
        assert result["verdict"] == "Forged-out"

    def test_two_distress_legs_read_caution(self):
        b = lane_bundle()          # profitable, so loss_making is False
        b["market_cap"] = 100e6
        set_all_balances(b, **{"Total Assets": 1e9, "Stockholders Equity": 100e6})
        prices = weekly_grid([10.0 if i % 2 == 0 else 13.0 for i in range(53)])
        assert run_forge(b, prices=prices)["probes"]["distress"]["severity"] == "caution"

    def test_distress_refuses_below_three_measurable_legs(self):
        probe = run_forge(lane_bundle())["probes"]["distress"]   # no price grid -> no vol
        assert not probe["measured"]

    def test_sustained_sub_dollar_closes_forge_out(self):
        b = lane_bundle()
        prices = weekly_grid([5.0] * 10 + [0.8] * 6)
        result = run_forge(b, prices=prices)
        assert result["probes"]["delisting"]["severity"] == "severe"
        assert result["verdict"] == "Forged-out"

    def test_equity_under_the_listing_floor_forges_out(self):
        b = lane_bundle()
        set_all_balances(b, **{"Stockholders Equity": 2e6})
        assert run_forge(b)["probes"]["delisting"]["severity"] == "severe"

    def test_a_recent_reverse_split_forges_out_and_an_old_one_does_not(self):
        recent = lane_bundle()
        recent["shares_series"] = [["2024-06-30", 1000e6], ["2025-06-30", 100e6]]
        recent["splits"] = {"2025-01-15": 0.1}
        prices = weekly_grid([5.0] * 60, start="2024-11-03")
        assert run_forge(recent, prices=prices)["probes"]["delisting"][
            "severity"] == "severe"

        old = lane_bundle()
        old["splits"] = {"2020-01-15": 0.1}
        old["shares_series"] = [["2021-06-30", 50e6], ["2025-06-30", 50e6]]
        assert run_forge(old, prices=prices)["probes"]["delisting"]["severity"] == "none"

    def test_accruals_over_ten_percent_of_assets_read_caution(self):
        b = lane_bundle()
        for pe in QTRS:
            b["quarterly"]["income"][pe][
                "Net Income Including Noncontrolling Interests"] = 25e6
        assert run_forge(b)["probes"]["accrual_mirage"]["severity"] == "caution"

    def test_overhang_reads_the_tagged_gap_and_refuses_without_it(self):
        b = lane_bundle()
        assert not run_forge(b)["probes"]["overhang"]["measured"]
        b["quarterly"]["income"]["2025-12-31"].update(
            {"Basic Average Shares": 50e6, "Diluted Average Shares": 57.5e6})
        probe = run_forge(b)["probes"]["overhang"]
        assert probe["severity"] == "caution" and probe["value"] == 15.0

    def test_two_cautions_read_watch(self):
        b = lane_bundle()
        b["shares_series"] = [["2021-06-30", 50e6], ["2022-06-30", 50e6],
                              ["2023-06-30", 50e6], ["2024-06-30", 50e6],
                              ["2025-06-30", 53e6]]          # dilution caution
        for pe in QTRS:
            b["quarterly"]["income"][pe][
                "Net Income Including Noncontrolling Interests"] = 25e6  # accrual caution
        result = run_forge(b)
        assert result["coverage"]["caution"] == 2
        assert result["verdict"] == "Watch"

    def test_thin_evidence_collapses_survivor_to_unknown(self):
        """No share series -> a required probe is unmeasured; with no named finding the
        verdict refuses to certify survival rather than granting it."""
        b = lane_bundle()
        b["shares_series"] = []
        result = run_forge(b)
        assert result["coverage"]["required_missing"] == ["serial_diluter"]
        assert result["verdict"] == "Unknown"

    def test_a_severe_finding_survives_thin_evidence(self):
        """Thin evidence can refuse to certify survival; it can never delete a
        finding."""
        b = lane_bundle()
        b["shares_series"] = []
        for pe in QTRS:
            b["quarterly"]["cashflow"][pe]["Operating Cash Flow"] = -5e6
        set_all_balances(b, **{"Cash And Cash Equivalents": 15e6})
        result = run_forge(b)
        assert result["coverage"]["thin"]
        assert result["verdict"] == "Forged-out"


# --- The metric table ---------------------------------------------------------------------

class TestMetrics:
    def test_ncav_and_graham_number(self):
        b = lane_bundle()
        set_all_balances(b, **{"Current Assets": 250e6})
        m = lowcap.metrics(b)
        assert m["ncav"] == 100e6                      # 250e6 - (400e6 - 250e6)
        # EPS 33e6/50e6 = 0.66; BVPS 250e6/50e6 = 5.0 -> GN = sqrt(22.5*0.66*5.0)
        assert round(m["graham_number"], 2) == 8.62
        assert round(m["mcap_to_ncav"], 1) == 5.0

    def test_peg_needs_three_positive_eps_points(self):
        m = lowcap.metrics(lane_bundle())
        assert m["peg"] is not None and m["eps_cagr_pct"] is not None
        b = lane_bundle()
        for pe in YEARS[:2]:
            b["annual"]["income"][pe]["Net Income"] = -1e6
        assert lowcap.metrics(b)["eps_cagr_pct"] is None

    def test_normalized_fcf_yield_averages_the_annual_years(self):
        m = lowcap.metrics(lane_bundle())
        # annual owner-FCF = 45 - min(8,10) - 2 = 35e6 each year; /500e6 = 7%
        assert round(m["norm_fcf_yield_pct"], 1) == 7.0

    def test_unmeasured_inputs_stay_none(self):
        m = lowcap.metrics({"symbol": "X", "annual": {}, "quarterly": {}})
        assert m["ncav"] is None and m["peg"] is None and m["graham_number"] is None


# --- The lenses ---------------------------------------------------------------------------

def metric_stub(**overrides):
    keys = ("market_cap", "price", "ttm_net_income", "ttm_ocf", "net_cash", "de_ratio",
            "liabilities_to_assets", "current_ratio", "ncav", "mcap_to_ncav", "eps_ttm",
            "bvps", "graham_number", "price_to_graham", "pe", "eps_cagr_pct", "peg",
            "ocf_to_ni", "ev_ebit", "norm_fcf_yield_pct", "share_trend_pct", "roic_pct",
            "rev_growth_pct", "op_margin_mad_pts", "op_margin_improving")
    m = {k: None for k in keys}
    m.update(overrides)
    return m


class TestLenses:
    def test_graham_speaks_on_a_net_net(self):
        m = metric_stub(market_cap=60e6, ncav=100e6, mcap_to_ncav=0.6,
                        ttm_net_income=2e6)
        result = lowcap.lens_graham(m)
        assert result["verdict"] == "speaks" and result["rank"] == 0.6
        assert "Net-net" in result["detail"]

    def test_graham_speaks_under_the_graham_number(self):
        m = metric_stub(market_cap=100e6, price=7.0, eps_ttm=0.66, bvps=5.0,
                        graham_number=8.62, price_to_graham=7.0 / 8.62,
                        current_ratio=2.5, liabilities_to_assets=0.3,
                        ncav=-10e6, ttm_net_income=2e6)
        result = lowcap.lens_graham(m)
        assert result["verdict"] == "speaks"
        assert result["rank"] > 1.0        # net-nets always rank ahead of GN qualifiers

    def test_graham_keeps_unprofitable_apart_from_unmeasured(self):
        # Measured and unprofitable: no Graham Number EXISTS -> silent, not refusing.
        silent = lowcap.lens_graham(metric_stub(
            market_cap=100e6, price=5.0, eps_ttm=-0.5, bvps=5.0, ncav=-10e6,
            ttm_net_income=-25e6, current_ratio=1.0, liabilities_to_assets=0.8))
        assert silent["verdict"] == "silent"
        # Nothing measured on either side -> refuses.
        assert lowcap.lens_graham(metric_stub())["verdict"] == "refuses"

    def test_garp_speaks_in_the_band_and_distrusts_hypergrowth(self):
        base = dict(peg=0.8, eps_cagr_pct=20.0, ocf_to_ni=1.3, net_cash=10e6,
                    de_ratio=0.1)
        assert lowcap.lens_garp(metric_stub(**base))["verdict"] == "speaks"
        hyper = dict(base, eps_cagr_pct=40.0, peg=0.4)
        result = lowcap.lens_garp(metric_stub(**hyper))
        assert result["verdict"] == "silent"          # a band, not a floor
        assert result["checks"]["growth_in_band"] is False

    def test_garp_refuses_without_a_peg(self):
        result = lowcap.lens_garp(metric_stub(eps_cagr_pct=20.0))
        assert result["verdict"] == "refuses" and "peg" in result["detail"]

    def test_downside_speaks_on_floor_plus_cheapness(self):
        m = metric_stub(net_cash=50e6, norm_fcf_yield_pct=12.0)
        result = lowcap.lens_downside(m)
        assert result["verdict"] == "speaks" and result["rank"] == -12.0

    def test_downside_ranks_by_the_leg_that_qualified(self):
        """A measured-but-thin yield must not become the rank when EV/EBIT is what
        qualified the name."""
        m = metric_stub(net_cash=50e6, norm_fcf_yield_pct=3.0, ev_ebit=5.0)
        result = lowcap.lens_downside(m)
        assert result["verdict"] == "speaks" and result["rank"] == -20.0

    def test_downside_is_silent_without_the_floor(self):
        m = metric_stub(net_cash=-200e6, current_ratio=1.1, de_ratio=2.0,
                        norm_fcf_yield_pct=15.0)
        assert lowcap.lens_downside(m)["verdict"] == "silent"

    def test_downside_refuses_when_the_floor_is_unmeasurable(self):
        assert lowcap.lens_downside(metric_stub(
            norm_fcf_yield_pct=15.0))["verdict"] == "refuses"

    def test_compounder_speaks_on_the_full_profile(self):
        m = metric_stub(ttm_net_income=33e6, ttm_ocf=48e6, share_trend_pct=0.0,
                        roic_pct=17.0, rev_growth_pct=11.0, op_margin_mad_pts=0.5,
                        op_margin_improving=True)
        result = lowcap.lens_compounder(m)
        assert result["verdict"] == "speaks" and result["rank"] == -11.0
        assert "scuttlebutt" in result["detail"]

    def test_compounder_refuses_on_any_missing_leg(self):
        m = metric_stub(ttm_net_income=33e6, ttm_ocf=48e6, share_trend_pct=0.0,
                        rev_growth_pct=11.0, op_margin_mad_pts=0.5)
        result = lowcap.lens_compounder(m)
        assert result["verdict"] == "refuses" and "roic_15" in result["detail"]

    def test_the_base_bundle_end_to_end(self):
        """The healthy lane name: compounder speaks, the value lenses stay silent (it is
        fairly priced), nothing refuses on the fundamentals side."""
        result = lowcap.analyze(lane_bundle())
        assert result["eligible"]
        assert result["forge"]["verdict"] == "Survivor"
        verdicts = {name: result["lenses"][name]["verdict"]
                    for name in lowcap.LENS_ORDER}
        assert verdicts["compounder"] == "speaks"
        assert verdicts["graham"] == "silent" and verdicts["downside"] == "silent"

    def test_no_composite_exists(self):
        """Invariant 2 generalized: four lenses, side by side, and no key anywhere that
        adds them up."""
        result = lowcap.analyze(lane_bundle())
        assert set(result["lenses"]) == set(lowcap.LENS_ORDER)
        forbidden = {"score", "composite", "total", "blend", "consensus"}
        assert not (forbidden & set(result))
        assert not (forbidden & set(result["forge"]))


# --- Shortlists ---------------------------------------------------------------------------

def lane_row(symbol, *, eligible=True, forge_verdict="Survivor", speaks=(),
             rank=1.0, inversion=None):
    lenses = {}
    for name in lowcap.LENS_ORDER:
        if name in speaks:
            lenses[name] = {"lens": name, "verdict": "speaks", "rank": rank,
                            "detail": f"{name} speaks", "checks": {}}
        else:
            lenses[name] = {"lens": name, "verdict": "silent", "rank": None,
                            "detail": "silent", "checks": {}}
    row = {"symbol": symbol,
           "lowcap": {"symbol": symbol, "eligible": eligible,
                      "eligibility": "test", "forge": {"verdict": forge_verdict},
                      "lenses": lenses, "metrics": {}}}
    if inversion is not None:
        row["inversion"] = inversion
    return row


class TestShortlists:
    def test_each_lens_ranks_only_within_its_own_logic(self):
        rows = [lane_row("AAA", speaks=("garp",), rank=0.9),
                lane_row("BBB", speaks=("garp",), rank=0.5),
                lane_row("CCC", speaks=("downside",), rank=-12.0)]
        lists = lowcap.shortlists(rows)
        assert [r["symbol"] for r in lists["garp"]] == ["BBB", "AAA"]
        assert [r["symbol"] for r in lists["downside"]] == ["CCC"]
        assert lists["graham"] == [] and lists["compounder"] == []

    def test_a_name_on_two_lists_is_visibly_on_two_lists(self):
        rows = [lane_row("BOTH", speaks=("graham", "downside"), rank=0.5)]
        lists = lowcap.shortlists(rows)
        assert [r["symbol"] for r in lists["graham"]] == ["BOTH"]
        assert [r["symbol"] for r in lists["downside"]] == ["BOTH"]

    def test_forged_out_names_never_reach_a_list(self):
        rows = [lane_row("DEAD", forge_verdict="Forged-out", speaks=("graham",))]
        assert all(not lst for lst in lowcap.shortlists(rows).values())

    def test_watch_and_unknown_remain_listable_with_the_verdict_riding_along(self):
        rows = [lane_row("WATCH", forge_verdict="Watch", speaks=("garp",)),
                lane_row("UNK", forge_verdict="Unknown", speaks=("garp",), rank=2.0)]
        garp = lowcap.shortlists(rows)["garp"]
        assert [r["symbol"] for r in garp] == ["WATCH", "UNK"]
        assert garp[0]["forge_verdict"] == "Watch"

    def test_the_main_inversion_layer_still_gates_the_lane(self):
        """Hell-No before the dossier holds in BOTH lanes: Fragile/Ruinous or any severe
        probe excludes; a missing result and Unknown do not."""
        fragile = {"verdict": "Fragile", "coverage": {"severe": 2, "caution": 0}}
        one_severe = {"verdict": "Ordinary", "coverage": {"severe": 1, "caution": 0}}
        unknown = {"verdict": "Unknown", "coverage": {"severe": 0, "caution": 0}}
        rows = [lane_row("FRAG", speaks=("garp",), inversion=fragile),
                lane_row("SEV", speaks=("garp",), inversion=one_severe),
                lane_row("UNK", speaks=("garp",), inversion=unknown),
                lane_row("NOINV", speaks=("garp",), rank=2.0)]
        garp = lowcap.shortlists(rows)["garp"]
        assert [r["symbol"] for r in garp] == ["UNK", "NOINV"]

    def test_ineligible_rows_never_reach_a_list(self):
        rows = [lane_row("BIG", eligible=False, speaks=("compounder",))]
        assert all(not lst for lst in lowcap.shortlists(rows).values())

    def test_the_per_lens_budget_caps_each_list(self):
        rows = [lane_row(f"S{i}", speaks=("graham",), rank=float(i)) for i in range(6)]
        lists = lowcap.shortlists(rows, per_lens=3)
        assert [r["symbol"] for r in lists["graham"]] == ["S0", "S1", "S2"]
