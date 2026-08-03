"""Offline tests for inversion.py — the Inversion Layer (docs/INVERSION-DESIGN.md).

Synthetic bundles and synthetic price grids only; no network, no files, no clock. Covers
every §3 probe at both sides of both of its thresholds, the §4 verdict table (counted, never
averaged — a fatal probe is never cancelled by good ones), the §5 fourth lens, and the rule
the whole layer exists for: absent evidence is named and returns Unknown, never a comforting
default (§7 / SCORECARD-DESIGN.md §4).

The final class pins the anchors measured on the real export (ADBE / MEDP / CRUS / EXEL /
RMD / NVDA) using small synthetic series constructed to reproduce those same statistics;
each construction is documented where it is built.
"""
import copy
import json
from datetime import date, timedelta

import pytest

import inversion
import scorecard
import scoring


# --- Builders ----------------------------------------------------------------------------

def grid(levels, start="2016-01-04"):
    """A §3.6 weekly price grid from a list of levels, one bar per week."""
    day = date.fromisoformat(start)
    out = {}
    for level in levels:
        out[day.isoformat()] = {"close": level, "adj_close": level}
        day += timedelta(days=7)
    return out


def levels_from_returns(returns, start=100.0):
    """Price levels from a return series (the inverse of inversion.weekly_returns)."""
    out, level = [start], start
    for r in returns:
        level *= (1.0 + r)
        out.append(level)
    return out


def flat_then_drop(depth, before=30, after=40):
    """A path whose deepest peak-to-trough fall is EXACTLY `depth`: flat at 100, one step up
    to a 200 peak, one step down to 200*(1+depth), flat after. Long enough to clear the
    52-return minimum."""
    return [100.0] * before + [200.0] + [200.0 * (1.0 + depth)] * (after + 1)


# A well-behaved price record: 120 weeks alternating +2%/-2%, so the return distribution is
# symmetric (skew 0, tail ratio 1.0) and the deepest fall is a few percent — nothing for
# §3.1, §3.2 or the §3.6 dilution leg to find, but everything measured.
CLEAN_PRICES = grid(levels_from_returns([0.02, -0.02] * 60))


def years(count, last=2025, month=12, day=31):
    """`count` annual period ends, ascending, the newest ending in `last`."""
    return [date(last - i, month, day).isoformat() for i in reversed(range(count))]


def make_bundle(symbol="AAA", *, owner_fcf=None, revenue=None, op_margin=0.20,
                periods=None, balance=None, shares=None, income_extra=None,
                quarterly=None, market_cap=6.0e9, splits=None):
    """A §4.1 Bundle with exactly the rows these probes read.

    `owner_fcf` is written as OCF with a zero CapEx and no D&A/SBC rows, so
    scoring._owner_fcf (OCF - min(|CapEx|, D&A) - SBC) returns the value verbatim and the
    tests can state owner earnings directly.

    `splits` defaults to {} — what every EDGAR-built Bundle actually carries — so a test
    that wants the §3.6 dilution leg to RUN has to say so, the way the real data does."""
    owner_fcf = [100.0, 110.0, 120.0] if owner_fcf is None else owner_fcf
    periods = periods or years(len(owner_fcf))
    if revenue is None:
        revenue = [1000.0 * 1.08 ** i for i in range(len(periods))]
    income, cashflow, balances = {}, {}, {}
    for i, pe in enumerate(periods):
        rev = revenue[i]
        income[pe] = {"Total Revenue": rev, "Operating Income": op_margin * rev,
                      "EBIT": op_margin * rev, "EBITDA": (op_margin + 0.05) * rev,
                      "Gross Profit": 0.6 * rev, "Net Income": 0.7 * op_margin * rev,
                      "Net Income Including Noncontrolling Interests": 0.7 * op_margin * rev}
        income[pe].update((income_extra or {}).get(pe, {}))
        cashflow[pe] = {"Operating Cash Flow": owner_fcf[i], "Capital Expenditure": 0.0}
        balances[pe] = dict(balance or {"Total Debt": 100.0,
                                        "Cash And Cash Equivalents": 500.0})
    return {
        "symbol": symbol, "name": f"{symbol} Corp", "sector": "Information Technology",
        "industry": "Software", "market_cap": market_cap, "yahoo_ev": None,
        "price": 60.0,
        "shares_series": shares if shares is not None else [["2016-01-01", 100e6]],
        "splits": dict(splits or {}),
        "annual": {"income": income, "balance": balances, "cashflow": cashflow},
        "quarterly": quarterly or {},
    }


# A split history the ingester actually captured, all of it BEFORE the share observations
# these tests use — so scoring.adjusted_shares_series is a no-op on the numbers while the
# §3.6 dilution leg still has the restatable series it requires.
CAPTURED_SPLITS = {"2015-06-01": 2.0}


def healthy(**kwargs):
    """A business with nothing for any probe to find: owner earnings compounding every year
    (so §3.3 and §3.4 are clean), 8%/yr revenue at a constant margin (§3.5), no debt wall,
    no dilution."""
    options = {"owner_fcf": [100.0 * 1.1 ** i for i in range(10)],
               "revenue": [1000.0 * 1.08 ** i for i in range(10)],
               "periods": years(10)}
    options.update(kwargs)
    return make_bundle(**options)


HEALTHY_KWARGS = dict(prices=CLEAN_PRICES)


# --- Registry ----------------------------------------------------------------------------

class TestRegistry:
    def test_probes_are_data_in_design_order(self):
        assert list(inversion.PROBES) == [
            "price_drawdown", "return_asymmetry", "cash_engine", "stress",
            "predictability", "financing", "concentration"]
        assert [spec["section"] for spec in inversion.PROBES.values()] == [
            "3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7"]
        for spec in inversion.PROBES.values():
            assert spec["label"] and spec["question"] and spec["reads"]
            assert spec["thresholds"] and spec["provenance"]

    def test_severity_and_verdicts(self):
        assert inversion.SEVERITY == ("none", "caution", "severe")
        assert set(inversion.VERDICTS) == {"Ruinous", "Fragile", "Ordinary", "Robust",
                                           "Unknown"}

    def test_concentration_is_the_only_non_counting_probe(self):
        assert inversion.COUNTING_PROBES == (
            "price_drawdown", "return_asymmetry", "cash_engine", "stress",
            "predictability", "financing")

    def test_every_probe_reports_the_full_contract(self):
        result = inversion.inversion(healthy(), **HEALTHY_KWARGS)
        assert set(result["probes"]) == set(inversion.PROBES)
        for probe_id, probe in result["probes"].items():
            assert probe["id"] == probe_id
            assert probe["severity"] in inversion.SEVERITY
            assert isinstance(probe["measured"], bool)
            assert isinstance(probe["detail"], str)
            assert probe["detail"].endswith((".", ")"))     # a sentence, not a fragment
            assert isinstance(probe["evidence"], dict)


# --- §3.1 Ruin already demonstrated ------------------------------------------------------

class TestPriceDrawdown:
    @pytest.mark.parametrize("depth,expected", [
        (-0.75, "severe"),      # past the severe line
        (-0.601, "severe"),
        (-0.60, "severe"),      # AT the line: inclusive on the risk side
        (-0.599, "caution"),    # just short of it
        (-0.41, "caution"),
        (-0.40, "caution"),     # AT the caution line
        (-0.399, "none"),
        (-0.05, "none"),
    ])
    def test_thresholds_in_both_directions(self, depth, expected):
        result = inversion.probe_price_drawdown(grid(flat_then_drop(depth)))
        assert result["severity"] == expected
        assert result["value"] == pytest.approx(depth)
        assert result["measured"] is True

    def test_recovery_is_what_separates_a_ruin_from_a_fall(self):
        """§3.1's permanence rule. Munger's ruin is PERMANENT loss of capital, so a 65%
        fall that was regained is a volatile compounder — real, and worth a caution,
        because the owner had to sit through it — while the same fall still underwater is
        severe. Scoring depth alone made this probe fire on 65% of the SEC export."""
        fell = flat_then_drop(-0.65)
        recovered = inversion.probe_price_drawdown(grid(fell + [200.0] * 5))
        assert recovered["severity"] == "caution"
        assert recovered["evidence"]["recovered"] is True
        assert "has since regained that peak" in recovered["detail"]
        assert "volatile, not ruined" in recovered["detail"]

        underwater = inversion.probe_price_drawdown(grid(fell))
        assert underwater["severity"] == "severe"
        assert underwater["evidence"]["recovered"] is False
        assert "permanently impaired" in underwater["detail"]

    def test_a_shallow_fall_that_recovered_is_not_even_a_caution(self):
        """The caution rung is deep-and-recovered OR moderate-and-underwater — not every
        dip. A 45% fall that came back is normal equity behaviour.

        Recovery to EXACTLY the old peak is the case that matters here: the cumulative
        series is an accumulated product of returns, so it lands a few ulps short and a
        strict comparison would call a fully recovered price permanently impaired."""
        result = inversion.probe_price_drawdown(
            grid(flat_then_drop(-0.45) + [200.0] * 5))
        assert result["severity"] == "none"
        assert result["evidence"]["recovered"] is True

    def test_the_first_bar_can_be_the_peak(self):
        """A series that OPENS at its all-time high and never recovers: the deepest
        peak-to-trough is -60% and it must read -60%. Building the cumulative series from
        the returns alone drops the level belonging to bar 0, so bar 0 can never be picked
        as the peak and this path reports no drawdown at all."""
        result = inversion.probe_price_drawdown(grid([200.0] + [80.0] * 80))
        assert result["value"] == pytest.approx(-0.60)
        assert result["severity"] == "severe"
        assert result["evidence"]["peak_day"] == "2016-01-04"        # the very first bar
        assert result["evidence"]["recovered"] is False

    def test_a_peak_on_the_first_bar_also_reaches_the_dilution_leg(self):
        """§3.6 gates its dilution leg on the same computation, so the blind spot suppressed
        the leg as "no bottom" on any name whose record opens at its high."""
        prices = grid([200.0] + [80.0] * 80)
        result = inversion.probe_financing(
            dilution_bundle(shares=[["2016-01-04", 100e6], ["2016-01-11", 120e6]]),
            prices=prices)
        assert result["evidence"]["drawdown"] == pytest.approx(-0.60)
        assert result["evidence"]["peak_day"] == "2016-01-04"
        assert result["severity"] == "severe"

    def test_short_history_is_unmeasured_not_clean(self):
        result = inversion.probe_price_drawdown(grid([100.0, 50.0] * 10))
        assert result["measured"] is False
        assert result["severity"] == "none"
        assert "fewer than the 52" in result["evidence"]["reason"]
        assert "Absent evidence is not safety" in result["detail"]

    def test_no_prices_at_all_is_unmeasured(self):
        for empty in (None, {}, {"ZZZ": {}}):
            assert inversion.probe_price_drawdown(empty, "AAA")["measured"] is False

    def test_reads_adj_close_never_the_raw_close(self):
        """The raw close would read every dividend as a loss. A grid whose raw closes fall
        70% while its adjusted closes only dip 10% must produce the 10% answer."""
        bars = {}
        raw = flat_then_drop(-0.70)
        adj = flat_then_drop(-0.10)
        for day, r, a in zip(sorted(grid(raw)), raw, adj):
            bars[day] = {"close": r, "adj_close": a}
        result = inversion.probe_price_drawdown(bars)
        assert result["value"] == pytest.approx(-0.10)
        assert result["severity"] == "none"

    def test_symbol_keyed_grid_is_accepted(self):
        by_symbol = {"AAA": grid(flat_then_drop(-0.65)), "BBB": grid(flat_then_drop(-0.01))}
        assert inversion.probe_price_drawdown(by_symbol, "AAA")["severity"] == "severe"
        assert inversion.probe_price_drawdown(by_symbol, "BBB")["severity"] == "none"


# --- §3.2 Return asymmetry ---------------------------------------------------------------

def two_point_returns(up_count, up, down_count, down):
    """A two-point weekly-return distribution: `up_count` weeks of `up` and `down_count` of
    `down`. Its skew is (1-2p)/sqrt(p(1-p)) with p = up_count/(up_count+down_count) —
    independent of the two values — and its tail ratio is exactly up/|down|, because every
    gain and every loss is its own side's 95th/5th percentile."""
    return [up] * up_count + [down] * down_count


class TestReturnAsymmetry:
    def test_severe_needs_both_legs_breached(self):
        # skew ~ -1.09 (p = 0.75) and tail ratio 0.5
        returns = two_point_returns(90, 0.01, 30, -0.02)
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert result["severity"] == "severe"
        assert result["evidence"]["skew"] < -0.5
        assert result["evidence"]["tail_ratio"] < 0.9

    def test_caution_when_only_the_tail_ratio_is_breached(self):
        # symmetric counts -> skew 0; tail ratio 0.85
        returns = two_point_returns(60, 0.0425, 60, -0.05)
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert result["severity"] == "caution"
        assert result["evidence"]["skew"] == pytest.approx(0.0, abs=1e-9)
        assert result["evidence"]["tail_ratio"] == pytest.approx(0.85)

    def test_caution_when_only_the_skew_is_breached(self):
        # p = 0.75 -> skew ~ -1.09; tail ratio 2.0, so only one leg is bad
        returns = two_point_returns(90, 0.04, 30, -0.02)
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert result["severity"] == "caution"
        assert result["evidence"]["skew"] < -0.5
        assert result["evidence"]["tail_ratio"] == pytest.approx(2.0)

    def test_clean_when_neither_leg_is_breached(self):
        returns = two_point_returns(60, 0.05, 60, -0.05)
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert result["severity"] == "none"
        assert result["evidence"]["tail_ratio"] == pytest.approx(1.0)

    def test_positive_skew_is_never_a_finding(self):
        returns = two_point_returns(30, 0.06, 90, -0.01)
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert result["evidence"]["skew"] > 0.5
        assert result["severity"] == "none"

    def test_tail_ratio_needs_twenty_observations_per_side(self):
        """Fewer than 20 loss weeks: the tail ratio is not computable, so the probe can
        reach caution on the skew alone but never severe — and it says why."""
        returns = [0.01] * 105 + [-0.30] * 15
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert result["evidence"]["skew"] < -0.5
        assert result["evidence"]["tail_ratio"] is None
        assert result["severity"] == "caution"
        assert "fewer than the 20 per side" in result["detail"]

    def test_short_history_is_unmeasured(self):
        result = inversion.probe_return_asymmetry(grid([100.0] * 20))
        assert result["measured"] is False and result["severity"] == "none"

    def test_a_dispersionless_series_has_no_skew_and_says_so(self):
        """A price that never moves gives scipy a NaN skew. That is nothing to find, not a
        finding — and it must never reach the output as a NaN."""
        result = inversion.probe_return_asymmetry(grid([100.0] * 80))
        assert result["measured"] is True
        assert result["severity"] == "none"
        assert result["evidence"]["skew"] is None
        assert result["evidence"]["excess_kurtosis"] is None
        assert "no dispersion at all" in result["detail"]


# --- §3.3 The cash engine breaking -------------------------------------------------------

class TestCashEngine:
    @pytest.mark.parametrize("trough,expected", [
        (10.0, "severe"),       # -90%
        (40.0, "severe"),       # exactly -60%, inclusive on the risk side
        (40.2, "caution"),      # -59.8%
        (65.0, "caution"),      # exactly -35%
        (65.2, "none"),         # -34.8%
        (99.0, "none"),
    ])
    def test_thresholds_in_both_directions(self, trough, expected):
        bundle = make_bundle(owner_fcf=[50.0, 100.0, trough, trough + 1.0])
        result = inversion.probe_cash_engine(bundle)
        assert result["severity"] == expected
        assert result["value"] == pytest.approx((trough - 100.0) / 100.0)

    def test_a_never_falling_engine_reads_zero(self):
        result = inversion.probe_cash_engine(make_bundle(owner_fcf=[10.0, 20.0, 30.0, 40.0]))
        assert result["value"] == 0.0 and result["severity"] == "none"
        assert "never fell below their own running peak" in result["detail"]

    def test_drawdown_is_peak_to_trough_not_first_to_last(self):
        """A recovery does not erase the fall: 100 -> 20 -> 130 is still -80%. It does
        change what the fall MEANS — an engine that came back to a new high is cyclical,
        not broken — so the depth is unchanged and the severity is a caution."""
        result = inversion.probe_cash_engine(make_bundle(owner_fcf=[100.0, 20.0, 130.0]))
        assert result["value"] == pytest.approx(-0.80)
        assert result["severity"] == "caution"
        assert result["evidence"]["recovered"] is True
        assert "a cyclical engine, not a broken one" in result["detail"]

    def test_a_deep_fall_still_underwater_is_severe(self):
        result = inversion.probe_cash_engine(make_bundle(owner_fcf=[100.0, 20.0, 30.0]))
        assert result["value"] == pytest.approx(-0.80)
        assert result["severity"] == "severe"
        assert result["evidence"]["recovered"] is False
        assert "has not regained that peak" in result["detail"]

    def test_the_window_bounds_how_far_back_a_break_counts(self):
        """§3.3's `window_periods`. An engine that broke twelve years ago and has run
        cleanly since is not a broken engine — the same reason scoring caps the Buffett
        lens at 8 years. The collapse below is outside the ten-year window entirely."""
        window = inversion.PROBES["cash_engine"]["thresholds"]["window_periods"]
        fcf = [100.0, 5.0] + [float(100 + i) for i in range(window)]
        result = inversion.probe_cash_engine(
            make_bundle(owner_fcf=fcf, periods=years(len(fcf))))
        assert result["evidence"]["periods"] == window
        assert result["evidence"]["periods_available"] == len(fcf)
        assert result["severity"] == "none"

    def test_the_fall_is_capped_at_one_hundred_percent(self):
        """Owner-FCF is a signed difference of large numbers, so once the trough crosses
        zero the percentage is unbounded — the SEC export's 5th percentile is -1,381%,
        which is the denominator talking rather than a fall twenty times worse than -60%.
        The uncapped figure is kept in evidence; the scored value is capped."""
        result = inversion.probe_cash_engine(make_bundle(owner_fcf=[100.0, -900.0, 10.0]))
        assert result["value"] == pytest.approx(-1.0)
        assert result["evidence"]["uncapped_drawdown"] == pytest.approx(-10.0)

    def test_only_a_later_trough_counts(self):
        """A low year BEFORE the peak is not a drawdown from it."""
        result = inversion.probe_cash_engine(make_bundle(owner_fcf=[20.0, 100.0, 120.0]))
        assert result["value"] == 0.0 and result["severity"] == "none"

    def test_an_engine_that_never_ran_is_severe_not_unmeasured(self):
        result = inversion.probe_cash_engine(make_bundle(owner_fcf=[-10.0, -20.0, -5.0]))
        assert result["severity"] == "severe"
        assert result["measured"] is True
        assert "never positive" in result["detail"]

    def test_a_trough_below_zero_that_never_came_back_is_named(self):
        """Going negative and staying there is severe on its own — the engine stopped
        producing owner earnings and has not started again — whatever the capped depth."""
        result = inversion.probe_cash_engine(make_bundle(owner_fcf=[100.0, -50.0, 10.0]))
        assert result["value"] == pytest.approx(-1.0)          # capped
        assert result["evidence"]["went_negative"] is True
        assert result["evidence"]["recovered"] is False
        assert result["severity"] == "severe"
        assert "went negative and has not come back" in result["detail"]

    def test_too_few_periods_is_unmeasured(self):
        result = inversion.probe_cash_engine(make_bundle(owner_fcf=[100.0, 10.0]))
        assert result["measured"] is False and result["severity"] == "none"
        assert "fewer than the 3" in result["evidence"]["reason"]

    def test_missing_capex_drops_the_period_rather_than_zeroing_it(self):
        bundle = make_bundle(owner_fcf=[100.0, 110.0, 120.0])
        del bundle["annual"]["cashflow"][years(3)[1]]["Capital Expenditure"]
        assert inversion.probe_cash_engine(bundle)["measured"] is False


# --- §3.4 Stress behaviour ---------------------------------------------------------------

class TestStress:
    def test_reads_the_december_periods_for_2020_and_2022(self):
        bundle = make_bundle(owner_fcf=[100.0, 110.0, 40.0, 130.0, 50.0, 160.0],
                             periods=years(6, last=2023))
        result = inversion.probe_stress(bundle)
        tested = {t["year"]: t for t in result["evidence"]["tested"]}
        assert tested[2020]["period"] == "2020-12-31"
        assert tested[2022]["period"] == "2022-12-31"
        assert tested[2020]["prior_peak"] == 110.0
        assert tested[2020]["shortfall"] == pytest.approx((40.0 - 110.0) / 110.0)
        # Both shocks were deep and both prior peaks came back (130 > 110, 160 > 130), so
        # the engine bent rather than broke: caution, not severe (§3.4's permanence rule).
        assert tested[2020]["recovered"] is True and tested[2022]["recovered"] is True
        assert result["severity"] == "caution"

    def test_a_january_ending_fiscal_year_maps_to_the_shock_it_covers(self):
        """A filer whose FY2021 ends 2021-01-31 lived the 2020 demand shock in that year,
        not in 2021 — the window [2020-06-01, 2021-05-31] picks it up."""
        periods = [date(y, 1, 31).isoformat() for y in range(2018, 2025)]
        bundle = make_bundle(owner_fcf=[100.0, 110.0, 120.0, 30.0, 140.0, 150.0, 160.0],
                             periods=periods)
        tested = {t["year"]: t for t in inversion.probe_stress(bundle)["evidence"]["tested"]}
        assert tested[2020]["period"] == "2021-01-31"
        assert tested[2020]["owner_fcf"] == 30.0
        assert tested[2022]["period"] == "2023-01-31"

    def test_a_november_ending_fiscal_year_maps_to_its_own_calendar_year(self):
        periods = [date(y, 11, 27).isoformat() for y in range(2018, 2024)]
        bundle = make_bundle(owner_fcf=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
                             periods=periods)
        tested = {t["year"]: t for t in inversion.probe_stress(bundle)["evidence"]["tested"]}
        assert tested[2020]["period"] == "2020-11-27"
        assert tested[2022]["period"] == "2022-11-27"

    @pytest.mark.parametrize("stressed,expected", [
        (30.0, "severe"),       # -70%, never regained
        (40.0, "severe"),       # exactly -60%, inclusive on the risk side
        (41.0, "caution"),      # -59%
        (65.0, "caution"),      # exactly -35%
        (66.0, "none"),         # -34%
    ])
    def test_thresholds_when_the_engine_never_came_back(self, stressed, expected):
        """Every year after the 2020 shock sits at 99, below the 100 prior peak, so the
        shortfall is permanent. (99 is also the 2022 reading, a 1% shortfall of its own —
        inside every line, so only the 2020 test drives the severity here.)"""
        bundle = make_bundle(owner_fcf=[80.0, 100.0, stressed, 99.0, 99.0, 99.0],
                             periods=years(6, last=2023))
        assert inversion.probe_stress(bundle)["severity"] == expected

    @pytest.mark.parametrize("stressed", [30.0, 40.0])
    def test_a_shock_the_engine_came_back_from_is_a_caution_not_a_ruin(self, stressed):
        """§3.4's permanence rule. Nearly every business on earth earned less in 2020 than
        in 2019 — scoring the shortfall alone made this probe say "the cash engine buckled"
        for 56% of the 1,904-name SEC export, which is a description of COVID and not of
        the business. What separates them is whether the prior peak came back."""
        bundle = make_bundle(owner_fcf=[80.0, 100.0, stressed, 120.0, 130.0, 140.0],
                             periods=years(6, last=2023))
        result = inversion.probe_stress(bundle)
        assert result["severity"] == "caution"
        assert "it came back" in result["detail"]

    def test_earning_above_the_prior_peak_through_a_shock_is_never_a_finding(self):
        bundle = make_bundle(owner_fcf=[80.0, 100.0, 150.0, 160.0, 170.0, 180.0],
                             periods=years(6, last=2023))
        assert inversion.probe_stress(bundle)["severity"] == "none"

    def test_surviving_both_tests_is_stated_as_evidence(self):
        bundle = make_bundle(owner_fcf=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
                             periods=years(6, last=2023))
        result = inversion.probe_stress(bundle)
        assert result["severity"] == "none"
        assert "held through both real tests" in result["detail"]
        assert "demand shock" in result["detail"] and "rate shock" in result["detail"]

    def test_a_shortfall_inside_the_lines_is_not_called_holding(self):
        """-34% clears the -35% caution line, so the severity is none — but the headline
        must not say owner earnings HELD when its own body says they fell a third (§7)."""
        bundle = make_bundle(owner_fcf=[80.0, 90.0, 100.0, 66.0, 105.0, 115.0, 120.0],
                             periods=years(7, last=2023))
        result = inversion.probe_stress(bundle)
        assert result["severity"] == "none"
        assert result["value"] == pytest.approx(-0.34)
        assert "held through" not in result["detail"]
        assert "stayed inside the lines" in result["detail"]

    def test_one_test_is_never_reported_as_two(self):
        bundle = make_bundle(owner_fcf=[80.0, 90.0, 100.0, 110.0],
                             periods=years(4, last=2021))
        result = inversion.probe_stress(bundle)
        assert result["evidence"]["years_tested"] == 1
        assert result["evidence"]["both_tests_ran"] is False
        assert "the test it could run" in result["detail"]
        assert "tests" not in result["detail"].split("(")[0]

    def test_the_worst_of_the_two_years_drives_the_severity(self):
        """2020 is a 5% dip against a 200 peak; 2022 collapses 80% against a 300 peak and
        never regains it. The worse year is the one that speaks."""
        bundle = make_bundle(owner_fcf=[100.0, 200.0, 190.0, 300.0, 60.0, 90.0],
                             periods=years(6, last=2023))
        result = inversion.probe_stress(bundle)
        assert result["severity"] == "severe"
        assert result["evidence"]["driver"] == "2022"

    def test_a_stress_year_with_no_prior_history_is_skipped_not_passed(self):
        bundle = make_bundle(owner_fcf=[50.0, 60.0, 70.0], periods=years(3, last=2022))
        result = inversion.probe_stress(bundle)
        skipped = " ".join(result["evidence"]["skipped"])
        assert "no annual period before 2020-12-31" in skipped
        assert result["evidence"]["tested"][0]["year"] == 2022

    def test_no_stress_years_in_the_record_is_unmeasured(self):
        bundle = make_bundle(owner_fcf=[100.0, 110.0, 120.0], periods=years(3, last=2018))
        result = inversion.probe_stress(bundle)
        assert result["measured"] is False and result["severity"] == "none"

    def test_a_quarter_inside_annual_cashflow_never_wins_a_stress_window(self):
        """Real `annual.cashflow` sections carry quarterly period ends and short transition
        stubs. A quarter divided by an ANNUAL prior peak manufactures a shortfall of
        hundreds of percent, and picking the LATEST end in the window hands it the year."""
        bundle = make_bundle(owner_fcf=[80.0, 90.0, 100.0, 110.0, 120.0, 130.0],
                             periods=years(6, last=2023))
        bundle["annual"]["cashflow"]["2021-03-31"] = {"Operating Cash Flow": 12.0,
                                                      "Capital Expenditure": 0.0}
        result = inversion.probe_stress(bundle)
        assert [t["period"] for t in result["evidence"]["tested"]] == ["2020-12-31",
                                                                      "2022-12-31"]
        assert result["severity"] == "none"


class TestAnnualCadence:
    def test_a_clean_annual_series_passes_through_untouched(self):
        points = [(pe, float(i)) for i, pe in enumerate(years(19))]
        assert inversion.annual_cadence(points) == points

    def test_a_fifty_two_week_fiscal_year_is_not_thinned(self):
        """52/53-week filers wobble to ~364 days and sometimes 357 — well above the
        300-day line, so nothing legitimate is dropped."""
        day = date(2016, 1, 30)
        points = []
        for _ in range(6):
            points.append((day.isoformat(), 100.0))
            day += timedelta(days=364)
        assert inversion.annual_cadence(points) == points

    def test_a_stub_and_a_quarter_are_dropped(self):
        points = [("2021-12-31", 100.0), ("2022-06-30", 40.0),   # 181-day stub
                  ("2022-12-31", 110.0), ("2023-03-31", 25.0),   # a quarter
                  ("2023-12-31", 120.0)]
        assert inversion.annual_cadence(points) == [
            ("2021-12-31", 100.0), ("2022-12-31", 110.0), ("2023-12-31", 120.0)]

    def test_predictability_does_not_read_a_quarter_as_a_wild_swing(self):
        """A quarter among the annual revenues reads as a -75% year followed by a +300%
        one — inventing the exact unpredictability §3.5 is looking for."""
        periods = years(8)
        bundle = make_bundle(owner_fcf=[100.0] * 8,
                             revenue=[1000.0 * 1.08 ** i for i in range(8)],
                             periods=periods)
        clean = inversion.probe_predictability(bundle)
        bundle["annual"]["income"]["2023-03-31"] = {
            "Total Revenue": 300.0, "Operating Income": 60.0, "EBIT": 60.0}
        result = inversion.probe_predictability(bundle)
        assert result["evidence"]["growth_mad"] == pytest.approx(
            clean["evidence"]["growth_mad"])
        assert result["severity"] == "none"

    def test_the_cash_engine_does_not_read_a_quarter_as_a_collapse(self):
        bundle = make_bundle(owner_fcf=[100.0, 110.0, 120.0, 130.0],
                             periods=years(4, last=2023))
        assert inversion.probe_cash_engine(bundle)["value"] == 0.0
        bundle["annual"]["cashflow"]["2023-03-31"] = {"Operating Cash Flow": 20.0,
                                                      "Capital Expenditure": 0.0}
        result = inversion.probe_cash_engine(bundle)
        assert result["value"] == 0.0
        assert result["severity"] == "none"


# --- §3.5 Predictability -----------------------------------------------------------------

class TestPredictability:
    def test_a_steady_series_is_predictable(self):
        bundle = make_bundle(owner_fcf=[100.0] * 8,
                             revenue=[1000.0 * 1.08 ** i for i in range(8)],
                             periods=years(8))
        result = inversion.probe_predictability(bundle)
        assert result["evidence"]["growth_mad"] == pytest.approx(0.0)
        assert result["evidence"]["margin_mad"] == pytest.approx(0.0)
        assert result["severity"] == "none"
        assert "can be forecast" in result["detail"]

    def test_an_erratic_series_is_not(self):
        revenue = [1000.0]
        for i in range(7):
            revenue.append(revenue[-1] * (1.5 if i % 2 == 0 else 0.7))
        bundle = make_bundle(owner_fcf=[100.0] * 8, revenue=revenue, periods=years(8))
        result = inversion.probe_predictability(bundle)
        assert result["evidence"]["growth_mad"] > 0.20
        assert result["severity"] == "severe"
        assert "resists valuation" in result["detail"]

    @pytest.mark.parametrize("growth,expected", [
        ([0.10] * 5, "none"),                                     # MAD 0 — dead steady
        ([0.125, 0.0, 0.0, 0.0, 0.0], "none"),                    # MAD 0.04
        ([0.3125, 0.0, 0.0, 0.0, 0.0], "caution"),                # MAD 0.10, AT the line
        ([0.25, 0.0, 0.25, 0.0, 0.25, 0.0], "caution"),           # MAD 0.125
        ([0.625, 0.0, 0.0, 0.0, 0.0], "severe"),                  # MAD 0.20, AT the line
        ([1.00, -0.50, 1.00, -0.50, 1.00, -0.50], "severe"),      # MAD 0.75
    ])
    def test_growth_dispersion_thresholds(self, growth, expected):
        """§3.5 measures the MEAN ABSOLUTE DEVIATION of growth in points — the reference's
        own axis and its own 0.10/0.20 lines — so these rows read directly. Every rate is a
        dyadic fraction (1/8, 5/16, 1/4, 5/8, 1/2), so the revenue path round-trips exactly
        and the two boundary rows land ON the line rather than a hair either side."""
        revenue = [1000.0]
        for g in growth:
            revenue.append(revenue[-1] * (1.0 + g))
        bundle = make_bundle(owner_fcf=[100.0] * len(revenue), revenue=revenue,
                             periods=years(len(revenue)))
        result = inversion.probe_predictability(bundle)
        assert result["severity"] == expected

    def test_margin_dispersion_drives_the_verdict_when_it_is_the_worse_leg(self):
        """Revenue grows at a dead-steady 8%/yr, but the operating margin swings from 4% to
        36% — the growth leg is clean and the probe still fires, because the two legs are
        taken at their worst and never averaged."""
        periods = years(8)
        revenue = [1000.0 * 1.08 ** i for i in range(8)]
        margins = [0.04, 0.36, 0.05, 0.35, 0.04, 0.36, 0.05, 0.35]
        extra = {pe: {"Operating Income": margins[i] * revenue[i], "EBIT": margins[i] * revenue[i]}
                 for i, pe in enumerate(periods)}
        bundle = make_bundle(owner_fcf=[100.0] * 8, revenue=revenue, periods=periods,
                             income_extra=extra)
        result = inversion.probe_predictability(bundle)
        assert result["evidence"]["growth_mad"] == pytest.approx(0.0)
        assert result["evidence"]["margin_mad"] > 0.10
        assert result["severity"] == "severe"
        assert result["evidence"]["driver"] == "operating margin"

    def test_too_short_a_history_is_unmeasured(self):
        bundle = make_bundle(owner_fcf=[100.0] * 4, revenue=[1000.0] * 4, periods=years(4))
        result = inversion.probe_predictability(bundle)
        assert result["measured"] is False and result["severity"] == "none"
        assert "fewer than the 5" in result["evidence"]["reason"]

    def test_one_measurable_leg_still_reports_and_names_the_other(self):
        periods = years(6)
        bundle = make_bundle(owner_fcf=[100.0] * 6,
                             revenue=[1000.0 * 1.05 ** i for i in range(6)], periods=periods)
        for pe in periods:                      # strip the operating-margin leg entirely
            bundle["annual"]["income"][pe].pop("Operating Income")
            bundle["annual"]["income"][pe].pop("EBIT")
        result = inversion.probe_predictability(bundle)
        assert result["measured"] is True
        assert result["evidence"]["margin_mad"] is None
        assert result["evidence"]["driver"] == "revenue growth"
        assert "Not measured" in result["detail"]

    def test_a_series_swinging_around_a_flat_line_is_read_by_its_swing(self):
        """+30% then -23% every year: revenue ends where it started, so a ratio would
        divide a 25-point swing by an average of nearly nothing and scream. Measuring in
        points reads the swing itself, and 25 points past the 20-point line is severe on
        its own terms rather than on its denominator's."""
        revenue = [1000.0, 1300.0, 1000.0, 1300.0, 1000.0, 1300.0]
        bundle = make_bundle(owner_fcf=[100.0] * 6, revenue=revenue, periods=years(6))
        result = inversion.probe_predictability(bundle)
        assert result["evidence"]["growth_mad"] == pytest.approx(0.255, abs=0.005)
        assert result["evidence"]["mean_growth"] < 0.09      # revenue ends where it began
        assert result["severity"] == "severe"

    def test_a_zero_mean_growth_reads_its_dispersion_not_its_denominator(self):
        """Revenue alternating x1.5 and x0.5 gives growth rates of +0.5 and -0.5 in equal
        number — both exact in binary, so the average growth is exactly nothing. A
        coefficient of variation is then INFINITE, which says everything about the divisor
        and nothing about the business; that is why §3.5 measures points instead. The
        spread is 50 growth points, far past the severe line, and the number survives the
        strict JSON write instead of being dropped as an infinity."""
        revenue = [1000.0]
        for i in range(6):
            revenue.append(revenue[-1] * (1.5 if i % 2 == 0 else 0.5))
        bundle = make_bundle(owner_fcf=[100.0] * 7, revenue=revenue, periods=years(7))
        result = inversion.probe_predictability(bundle)
        assert result["severity"] == "severe"
        assert result["evidence"]["growth_mad"] == pytest.approx(0.5)
        assert result["evidence"]["mean_growth"] == pytest.approx(0.0)
        assert result["value"] is not None
        assert json.loads(json.dumps(result, allow_nan=False)) is not None

    def test_a_flat_revenue_line_is_the_most_forecastable_shape_there_is(self):
        """Kenvue's five reported years: 15,054 / 14,950 / 15,444 / 15,455 / 15,124 $m —
        +0.14%/yr average growth with 2.0 growth points of spread and a 5.5pp full range.
        A coefficient of variation reads 14.7 and grades the flattest revenue line in the
        universe SEVERE — 'this business resists valuation' — for being steady. That is the
        filter inverted, and it is why the revenue leg measures points instead of a ratio."""
        revenue = [15054.0, 14950.0, 15444.0, 15455.0, 15124.0]
        bundle = make_bundle(symbol="KVUE", owner_fcf=[100.0] * 5, revenue=revenue,
                             periods=years(5))
        result = inversion.probe_predictability(bundle)
        assert inversion._cv([revenue[i] / revenue[i - 1] - 1.0
                              for i in range(1, 5)]) > 10.0        # as a ratio: absurd
        assert result["evidence"]["growth_mad"] < 0.02             # ~1.6 growth points
        assert result["severity"] == "none"

    def test_one_measured_leg_never_claims_the_business_can_be_forecast(self):
        periods = years(6)
        bundle = make_bundle(owner_fcf=[100.0] * 6,
                             revenue=[1000.0 * 1.05 ** i for i in range(6)], periods=periods)
        for pe in periods:
            bundle["annual"]["income"][pe].pop("Operating Income")
            bundle["annual"]["income"][pe].pop("EBIT")
        result = inversion.probe_predictability(bundle)
        assert result["severity"] == "none"
        assert "can be forecast" not in result["detail"]
        assert "What could be measured is steady" in result["detail"]


# --- §3.6 Financing fragility ------------------------------------------------------------

WALL_BALANCE = {"Total Debt": 900.0, "Cash And Cash Equivalents": 200.0}


def wall_bundle(due, *, label="Long Term Debt Maturities Repayments Of Principal In Next "
                            "Twelve Months", cash=200.0, fcf=100.0, **kwargs):
    """Cash + one year of owner earnings = `cash` + `fcf`; `due` is the twelve-month wall."""
    balance = dict(WALL_BALANCE)
    balance["Cash And Cash Equivalents"] = cash
    if due is not None:
        balance[label] = due
    return make_bundle(owner_fcf=[fcf, fcf, fcf], balance=balance, **kwargs)


def dilution_bundle(**kwargs):
    """A wall_bundle whose split history was captured, so the §3.6 dilution leg runs."""
    kwargs.setdefault("splits", CAPTURED_SPLITS)
    return wall_bundle(0.0, **kwargs)


class TestFinancingWall:
    @pytest.mark.parametrize("due,expected", [
        (600.0, "severe"),      # 2.0x
        (300.0, "severe"),      # exactly 1.0x, inclusive on the risk side
        (299.0, "caution"),
        (150.0, "caution"),     # exactly 0.5x
        (149.0, "none"),
        (0.0, "none"),
    ])
    def test_thresholds_in_both_directions(self, due, expected):
        result = inversion.probe_financing(wall_bundle(due))
        assert result["severity"] == expected
        assert result["evidence"]["wall_ratio"] == pytest.approx(due / 300.0)

    def test_the_raw_edgar_tag_is_accepted_too(self):
        result = inversion.probe_financing(
            wall_bundle(600.0,
                        label="LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths"))
        assert result["severity"] == "severe"
        assert result["evidence"]["debt_due_12m"] == 600.0

    def test_missing_maturity_data_is_unmeasured_never_safe(self):
        result = inversion.probe_financing(wall_bundle(None))
        assert result["measured"] is False
        assert result["severity"] == "none"
        assert "no twelve-month debt maturity" in result["evidence"]["reason"]
        assert "Absent evidence is not safety" in result["detail"]

    def test_negative_owner_earnings_do_not_pay_a_maturity(self):
        """A loss-making year contributes 0 to the cushion, not a negative — so the wall is
        measured against cash alone (200) and 200 due reads as exactly 1.0x."""
        result = inversion.probe_financing(wall_bundle(200.0, fcf=-500.0))
        assert result["evidence"]["wall_ratio"] == pytest.approx(1.0)
        assert result["severity"] == "severe"

    def test_no_cushion_at_all_with_debt_due_is_severe(self):
        """Past any ratio, not a huge one: the severity stands, the unrepresentable number
        does not travel (it would cost the name its whole verdict downstream)."""
        result = inversion.probe_financing(wall_bundle(50.0, cash=0.0, fcf=-10.0))
        assert result["severity"] == "severe"
        assert result["evidence"]["wall_uncovered"] is True
        assert result["evidence"]["wall_ratio"] is None
        assert result["value"] is None
        assert "no cash and no positive year of owner earnings" in result["detail"]


def diluting_prices():
    """A 60% drawdown whose peak is 2016-08-01 and whose trough is 2016-08-08."""
    return grid(flat_then_drop(-0.60))


class TestFinancingDilution:
    def test_shares_issued_at_the_bottom_are_severe(self):
        prices = diluting_prices()
        result = inversion.probe_financing(
            dilution_bundle(shares=[["2016-01-04", 100e6], ["2016-08-08", 115e6]]),
            prices=prices)
        assert result["evidence"]["share_change"] == pytest.approx(0.15)
        assert result["severity"] == "severe"
        assert result["evidence"]["driver"] == "dilution at the bottom"
        assert "diluted at the bottom" in result["detail"]

    @pytest.mark.parametrize("shares_at_trough,expected", [
        (120e6, "severe"),      # +20%
        (110e6, "severe"),      # exactly +10%
        (109e6, "caution"),
        (103e6, "caution"),     # exactly +3%
        (102e6, "none"),
        (100e6, "none"),
        (95e6, "none"),         # buying back INTO the drawdown is not a finding
    ])
    def test_thresholds_in_both_directions(self, shares_at_trough, expected):
        result = inversion.probe_financing(
            dilution_bundle(shares=[["2016-01-04", 100e6],
                                    ["2016-08-08", shares_at_trough]]),
            prices=diluting_prices())
        assert result["severity"] == expected

    def test_a_shallow_dip_has_no_bottom_to_be_diluted_at(self):
        """No bottom is NOT a clean dilution reading: the leg goes unmeasured and says so,
        so it can never count toward coverage as evidence that nothing happened."""
        result = inversion.probe_financing(
            dilution_bundle(shares=[["2016-01-04", 100e6], ["2016-08-08", 200e6]]),
            prices=grid(flat_then_drop(-0.20)))
        assert result["severity"] == "none"
        assert "shallower than the 30%" in " ".join(result["evidence"]["unmeasured"])
        assert "dilution" not in result["evidence"]["legs_measured"]

    def test_a_leg_that_could_not_run_is_never_scored_as_holding(self):
        """The §7 case the whole probe turns on: with no maturity tag and a drawdown too
        shallow to have a bottom, NOTHING was measured — so the probe must be unmeasured
        rather than report "the financing side holds" and count toward the coverage bit."""
        bundle = dilution_bundle(shares=[["2016-01-04", 100e6], ["2016-08-08", 200e6]])
        del bundle["annual"]["balance"][years(3)[-1]][
            "Long Term Debt Maturities Repayments Of Principal In Next Twelve Months"]
        result = inversion.probe_financing(bundle, prices=CLEAN_PRICES)
        assert result["measured"] is False
        assert result["severity"] == "none"
        assert "holds" not in result["detail"]
        assert "Absent evidence is not safety" in result["detail"]

    def test_a_single_measured_leg_names_itself_rather_than_the_whole_side(self):
        result = inversion.probe_financing(dilution_bundle(shares=[]))
        assert result["measured"] is True
        assert result["detail"].startswith("The refinancing wall holds")

    def test_share_class_suppresses_the_leg_the_scorecard_also_distrusts(self):
        bundle = dilution_bundle(shares=[["2016-01-04", 100e6], ["2016-08-08", 200e6]])
        result = inversion.probe_financing(bundle, prices=diluting_prices(),
                                           share_class=True)
        assert result["severity"] == "none"
        assert "SHARE_CLASS" in " ".join(result["evidence"]["unmeasured"])

    def test_splits_are_not_read_as_dilution(self):
        """A 2-for-1 split doubles the raw count; scoring.adjusted_shares_series restates it,
        so the leg sees 0% dilution rather than +100%."""
        bundle = wall_bundle(0.0, shares=[["2016-01-04", 100e6], ["2016-08-08", 200e6]],
                             splits={"2016-03-01": 2.0})
        result = inversion.probe_financing(bundle, prices=diluting_prices())
        assert result["evidence"]["share_change"] == pytest.approx(0.0)
        assert result["severity"] == "none"

    def test_a_bundle_with_no_split_history_cannot_read_dilution_at_all(self):
        """Every EDGAR-built Bundle carries `splits == {}`, which makes
        scoring.adjusted_shares_series a silent no-op — so a 20:1 split looks exactly like
        +1900% dilution at the bottom. The leg refuses to measure instead (§7)."""
        bundle = wall_bundle(0.0, shares=[["2016-01-04", 100e6], ["2016-08-08", 2.0e9]])
        assert bundle["splits"] == {}
        result = inversion.probe_financing(bundle, prices=diluting_prices())
        assert result["severity"] == "none"
        assert "share_change" not in result["evidence"]
        assert "no split history" in " ".join(result["evidence"]["unmeasured"])

    def test_an_unattributable_jump_is_refused_even_with_a_split_history(self):
        """A share count that more than doubles across one drawdown is a split, a reverse
        merger or a junk cover-page observation — never a finding this layer may make."""
        result = inversion.probe_financing(
            dilution_bundle(shares=[["2016-01-04", 1000.0], ["2016-08-08", 1.148e8]]),
            prices=diluting_prices())
        assert result["severity"] == "none"
        assert "share_change" not in result["evidence"]
        assert "beyond the 100%" in " ".join(result["evidence"]["unmeasured"])
        assert result["evidence"]["share_change_refused"] > 1000.0

    def test_both_legs_missing_makes_the_probe_unmeasured(self):
        result = inversion.probe_financing(wall_bundle(None, shares=[]))
        assert result["measured"] is False

    def test_the_worse_leg_drives_the_probe(self):
        result = inversion.probe_financing(
            wall_bundle(600.0, shares=[["2016-01-04", 100e6], ["2016-08-08", 100e6]],
                        splits=CAPTURED_SPLITS),
            prices=diluting_prices())
        assert result["severity"] == "severe"
        assert result["evidence"]["driver"] == "refinancing wall"

    def test_a_broader_substitute_row_names_the_substitution(self):
        """'Current Debt' is every short-term borrowing, not the twelve-month maturity of
        long-term debt §3.6 names — so when it is what fired, the sentence says so."""
        result = inversion.probe_financing(wall_bundle(600.0, label="Current Debt"))
        assert result["severity"] == "severe"
        assert result["evidence"]["debt_due_12m_substituted"] is True
        assert "broader than the twelve-month maturity" in result["detail"]


# --- §3.7 Concentration (flag only) ------------------------------------------------------

class TestConcentration:
    def test_absent_says_so_out_loud(self):
        result = inversion.probe_concentration(make_bundle())
        assert result["measured"] is False
        assert result["severity"] == "none"
        assert result["evidence"]["flagged"] is False
        assert "silence here is not safety" in result["detail"]

    @pytest.mark.parametrize("raw,percent", [(0.90, 90.0), (90.0, 90.0), (0.12, 12.0)])
    def test_a_pure_ratio_and_a_percentage_read_the_same(self, raw, percent):
        periods = years(3)
        bundle = make_bundle(income_extra={periods[-1]: {"ConcentrationRiskPercentage1": raw}})
        result = inversion.probe_concentration(bundle)
        assert result["value"] == pytest.approx(percent)

    def test_high_concentration_is_flagged_but_never_scored(self):
        periods = years(3)
        bundle = make_bundle(income_extra={periods[-1]: {"Concentration Risk Percentage1": 0.9}})
        result = inversion.probe_concentration(bundle)
        assert result["evidence"]["flagged"] is True
        assert result["severity"] == "none"          # flag only — §3.7
        assert "flagged, not scored" in result["detail"]

    def test_below_the_line_it_is_reported_without_a_flag(self):
        periods = years(3)
        bundle = make_bundle(income_extra={periods[-1]: {"ConcentrationRiskPercentage1": 0.12}})
        result = inversion.probe_concentration(bundle)
        assert result["evidence"]["flagged"] is False
        assert "below the 20% line" in result["detail"]

    def test_it_never_enters_the_verdict_or_the_coverage_denominator(self):
        periods = years(10)
        flagged = healthy(income_extra={periods[-1]: {"ConcentrationRiskPercentage1": 0.95}})
        clean = healthy()
        with_flag = inversion.inversion(flagged, **HEALTHY_KWARGS)
        without = inversion.inversion(clean, **HEALTHY_KWARGS)
        assert with_flag["verdict"] == without["verdict"]
        assert with_flag["coverage"]["counting_total"] == 6
        assert "concentration" not in with_flag["coverage"]["counting"]
        assert any(mode.startswith("Flag —") for mode in with_flag["failure_modes"])
        assert not any(mode.startswith("Flag —") for mode in without["failure_modes"])


# --- §4 The verdict ----------------------------------------------------------------------

class TestVerdictCounting:
    @pytest.mark.parametrize("severe,caution,expected", [
        (4, 0, "Ruinous"),
        (3, 0, "Ruinous"),
        (3, 5, "Ruinous"),
        (2, 0, "Fragile"),
        (2, 6, "Fragile"),
        (0, 4, "Fragile"),
        (0, 5, "Fragile"),
        (1, 3, "Ordinary"),
        (1, 0, "Ordinary"),
        (0, 3, "Ordinary"),
        (0, 1, "Ordinary"),
        (0, 0, "Robust"),
    ])
    def test_the_design_table(self, severe, caution, expected):
        assert inversion.verdict_for(severe, caution) == expected

    def test_the_ladder_is_calibrated_not_assumed(self):
        """The rungs come from the measured firing rates of the six counting probes, not
        from an assumption that probes fire rarely. The design's original ">= 2 severe"
        read Ruinous for 71% of the 1,904-name export — and for 68% of the scorecard's
        EXCEPTIONAL names against 88% of its lowest band, a spread of two points."""
        assert inversion.VERDICT_LADDER == {"ruinous_severe": 3, "fragile_severe": 2,
                                            "fragile_caution": 4}
        assert "3 or more severe" in inversion.VERDICTS["Ruinous"]["rule"]
        assert len(inversion.COUNTING_PROBES) == 6

    def test_severities_are_counted_never_averaged(self):
        """Five clean probes cannot cancel a fatal one — the whole point of §4. The cash
        engine falls 90% and never regains its peak; everything else is spotless. Nothing
        here subtracts, so the finding survives into the verdict and into the sentences."""
        bundle = healthy(owner_fcf=[100.0, 200.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0,
                                    80.0, 90.0], periods=years(10, last=2018))
        result = inversion.inversion(bundle, **HEALTHY_KWARGS)
        severities = {pid: probe["severity"] for pid, probe in result["probes"].items()}
        assert severities["cash_engine"] == "severe"
        assert [s for s in severities.values() if s == "severe"] == ["severe"]
        assert result["coverage"]["severe"] == 1
        assert any("cash engine fell" in mode for mode in result["failure_modes"])
        assert result["verdict"] == "Ordinary"
        # ... and "Ordinary" is never a green survival tick while a severe probe stands.
        assert inversion.consensus_lens(result) is None

    def test_a_clean_well_evidenced_name_is_robust(self):
        result = inversion.inversion(healthy(), **HEALTHY_KWARGS)
        assert result["verdict"] == "Robust"
        assert result["failure_modes"] == []
        assert result["coverage"]["thin"] is False

    def test_three_severe_probes_are_ruinous(self):
        """The price never came back from a 70% fall; the cash engine collapsed in the year
        covering the 2020 shock and never regained its peak (§3.3 and §3.4 both fire, which
        is honest — they are the same engine read over different windows); and revenue
        growth swings 50 points. Three named ways to lose the money."""
        bundle = healthy(owner_fcf=[100.0, 200.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0,
                                    80.0, 90.0],
                         revenue=[1000.0 * (1.5 if i % 2 else 0.5) ** 1 * (1.0 + i)
                                  for i in range(10)],
                         periods=years(10, last=2023))
        result = inversion.inversion(bundle, prices=grid(flat_then_drop(-0.70)))
        assert result["coverage"]["severe"] >= 3
        assert result["verdict"] == "Ruinous"
        assert len(result["failure_modes"]) >= 3

    def test_failure_modes_lead_with_the_severe_sentences(self):
        bundle = healthy(owner_fcf=[100.0, 200.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0,
                                    80.0, 90.0], periods=years(10, last=2018))
        result = inversion.inversion(
            bundle, prices=grid(flat_then_drop(-0.65) + [200.0] * 5))
        assert (result["coverage"]["severe"], result["coverage"]["caution"]) == (1, 1)
        assert "cash engine fell" in result["failure_modes"][0]      # severe leads
        assert "price fell" in result["failure_modes"][1]            # caution follows


class TestUnknown:
    def test_missing_price_history_is_unknown_not_robust(self):
        result = inversion.inversion(healthy(), prices=None)
        assert result["counted_verdict"] == "Robust"
        assert result["verdict"] == "Unknown"
        assert "price_drawdown" in result["coverage"]["required_missing"]
        assert any("never read as safe" in note for note in result["notes"])

    def test_missing_cash_engine_history_is_unknown_not_robust(self):
        bundle = healthy()
        bundle["annual"]["cashflow"] = {}
        result = inversion.inversion(bundle, **HEALTHY_KWARGS)
        assert result["verdict"] == "Unknown"
        assert "cash_engine" in result["coverage"]["required_missing"]

    def test_an_empty_bundle_is_unknown_and_names_every_gap(self):
        result = inversion.inversion({"symbol": "AAA"})
        assert result["verdict"] == "Unknown"
        assert len(result["coverage"]["unmeasured"]) == len(inversion.PROBES)
        assert result["coverage"]["measured_counting"] == 0

    def test_too_few_measured_probes_is_unknown_even_with_both_required_ones(self):
        """Both load-bearing probes are measured, but only 3 of the 6 counting probes are —
        under MIN_MEASURED_COUNTING, so the layer refuses to certify."""
        bundle = make_bundle(owner_fcf=[100.0, 110.0, 120.0], periods=years(3, last=2018),
                             shares=[])
        for payload in bundle["annual"]["income"].values():
            for row in ("Total Revenue", "Operating Income", "EBIT"):
                payload.pop(row)
        result = inversion.inversion(bundle, **HEALTHY_KWARGS)
        assert result["coverage"]["required_missing"] == []
        assert result["coverage"]["measured_counting"] == 3
        assert result["coverage"]["thin"] is True
        assert result["counted_verdict"] == "Robust"
        assert result["verdict"] == "Unknown"
        assert any("only 3 of 6 probes" in note for note in result["notes"])

    def test_thin_evidence_never_deletes_a_named_failure_mode(self):
        """Absent data can refuse to certify safety — it can never manufacture it, and it
        must never erase a finding either (§7). The cash engine fell 90% and never came
        back; nothing else could be measured. Under the calibrated ladder one severe lands
        on Ordinary, so collapsing every "safe" rung to Unknown would delete the one
        sentence this layer had to say. The test is the evidence, not the label."""
        bundle = make_bundle(owner_fcf=[100.0, 200.0, 20.0])     # -90%, and nothing else
        result = inversion.inversion(bundle, prices=None)
        assert result["coverage"]["thin"] is True
        assert result["coverage"]["severe"] == 1
        assert result["counted_verdict"] == "Ordinary"
        assert result["verdict"] == "Ordinary"
        assert any("cash engine fell" in mode for mode in result["failure_modes"])

    def test_a_caution_on_thin_evidence_is_unknown(self):
        bundle = make_bundle(owner_fcf=[100.0, 200.0, 120.0])    # -40%: one caution
        result = inversion.inversion(bundle, prices=None)
        assert result["counted_verdict"] == "Ordinary"
        assert result["verdict"] == "Unknown"


# --- §5 The fourth lens ------------------------------------------------------------------

class TestConsensusLens:
    @pytest.mark.parametrize("verdict,expected", [
        ("Robust", True), ("Ordinary", True),
        ("Fragile", False), ("Ruinous", False),
        ("Unknown", None),
    ])
    def test_tri_state(self, verdict, expected):
        assert inversion.consensus_lens({"verdict": verdict}) is expected
        assert inversion.consensus_lens(verdict) is expected

    def test_no_inversion_at_all_is_none(self):
        assert inversion.consensus_lens(None) is None
        assert inversion.consensus_lens({}) is None
        assert inversion.consensus_lens({"verdict": "nonsense"}) is None

    def test_it_reads_the_layer_s_own_output(self):
        assert inversion.consensus_lens(
            inversion.inversion(healthy(), **HEALTHY_KWARGS)) is True
        assert inversion.consensus_lens(inversion.inversion(healthy())) is None

    def test_a_standing_flag_stops_the_lens_certifying_survival(self):
        """INVERSION-DESIGN §1's own motivating case: Cirrus Logic, ~90% of revenue from
        one customer. §3.7 forbids scoring the flag, so the counted verdict stays Robust —
        but a green survival tick beside the sentence naming that risk is exactly the
        failure this layer was built to stop, so the lens refuses to say."""
        periods = years(10)
        flagged = healthy(
            income_extra={periods[-1]: {"ConcentrationRiskPercentage1": 0.90}})
        result = inversion.inversion(flagged, **HEALTHY_KWARGS)
        assert result["verdict"] == "Robust"                 # §3.7: never scored
        assert result["coverage"]["flagged"] == ["concentration"]
        assert inversion.consensus_lens(result) is None
        assert any("says nothing rather than green" in n for n in result["notes"])

    def test_a_flag_below_the_line_leaves_the_lens_alone(self):
        periods = years(10)
        quiet = healthy(
            income_extra={periods[-1]: {"ConcentrationRiskPercentage1": 0.12}})
        result = inversion.inversion(quiet, **HEALTHY_KWARGS)
        assert result["coverage"]["flagged"] == []
        assert inversion.consensus_lens(result) is True

    def test_a_flag_never_turns_a_named_failure_mode_green(self):
        periods = years(10)
        bundle = healthy(
            owner_fcf=[100.0, 200.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
            income_extra={periods[-1]: {"ConcentrationRiskPercentage1": 0.90}})
        result = inversion.inversion(bundle, **HEALTHY_KWARGS)
        assert result["verdict"] == "Fragile"
        assert inversion.consensus_lens(result) is False


# --- The layer's boundary with the scorecard ---------------------------------------------

class TestNoScorecardContact:
    def test_it_returns_no_points(self):
        result = inversion.inversion(healthy(), **HEALTHY_KWARGS)
        assert set(result) == {"verdict", "verdict_meaning", "verdict_rule",
                               "counted_verdict", "failure_modes", "probes", "coverage",
                               "notes"}
        assert "points" not in result and "score" not in result

    def test_it_does_not_mutate_the_bundle(self):
        bundle = healthy()
        before = copy.deepcopy(bundle)
        inversion.inversion(bundle, prices=CLEAN_PRICES)
        assert bundle == before

    def test_the_card_is_identical_either_side_of_it(self):
        bundle = healthy()
        before = scorecard.scorecard(bundle)
        inversion.inversion(bundle, prices=CLEAN_PRICES)
        assert scorecard.scorecard(bundle) == before

    def test_exceptional_and_fragile_can_coexist(self):
        """§5: a name can be strong on the card and fragile on this lens, and that pairing
        must survive rather than be reconciled away."""
        bundle = healthy(owner_fcf=[100.0, 200.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0,
                                    80.0, 90.0])
        card = scorecard.scorecard(bundle)
        result = inversion.inversion(bundle, **HEALTHY_KWARGS)
        assert card["score"] is not None
        assert result["verdict"] == "Fragile"

    @pytest.mark.parametrize("case", ["clean", "ruinous", "empty", "no_prices", "degenerate"])
    def test_the_whole_result_survives_a_strict_json_write(self, case):
        """The run that consumes this writes with allow_nan=False and DROPS a verdict it
        cannot serialize — so one infinity anywhere in the evidence would cost a name its
        whole inversion. Every shape this layer can produce must round-trip."""
        if case == "clean":
            result = inversion.inversion(healthy(), **HEALTHY_KWARGS)
        elif case == "ruinous":
            revenue = [1000.0]
            for i in range(9):
                revenue.append(revenue[-1] * (1.25 if i % 2 == 0 else 0.8))
            bundle = healthy(
                owner_fcf=[100.0, 200.0, 20.0, 5.0, -50.0, 30.0, 40.0, 50.0, 60.0, 70.0],
                revenue=revenue,
                balance={"Total Debt": 900.0, "Cash And Cash Equivalents": 0.0,
                         "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths": 900.0})
            result = inversion.inversion(bundle, prices=grid(flat_then_drop(-0.80)))
            assert result["verdict"] == "Ruinous"
        elif case == "empty":
            result = inversion.inversion({"symbol": "AAA"})
        elif case == "no_prices":
            result = inversion.inversion(healthy())
        else:
            result = inversion.inversion(healthy(), prices=grid([100.0] * 80))
        assert json.loads(json.dumps(result, allow_nan=False)) is not None

    def test_a_scored_row_for_another_symbol_is_refused(self):
        with pytest.raises(ValueError, match="scored_row is for"):
            inversion.inversion(healthy(symbol="AAA"), scored_row={"symbol": "BBB"})

    def test_the_share_class_flag_is_read_from_the_row_when_supplied(self):
        bundle = healthy(shares=[["2016-01-04", 100e6], ["2016-08-08", 200e6]])
        row = {"symbol": "AAA", "flags": [{"code": "SHARE_CLASS", "message": "x"}]}
        result = inversion.inversion(bundle, prices=diluting_prices(), scored_row=row)
        assert "SHARE_CLASS" in result["probes"]["financing"]["detail"]


# --- Numeric helpers ---------------------------------------------------------------------

class TestHelpers:
    def test_percentile_matches_linear_interpolation(self):
        values = [1.0, 2.0, 3.0, 4.0]
        assert inversion._percentile(values, 0.0) == 1.0
        assert inversion._percentile(values, 100.0) == 4.0
        assert inversion._percentile(values, 50.0) == pytest.approx(2.5)
        assert inversion._percentile(values, 25.0) == pytest.approx(1.75)
        assert inversion._percentile([], 50.0) is None
        assert inversion._percentile([7.0], 95.0) == 7.0

    def test_cv_of_a_flat_series_is_zero_whatever_the_mean(self):
        assert inversion._cv([0.0, 0.0, 0.0]) == 0.0
        assert inversion._cv([5.0, 5.0, 5.0]) == 0.0

    def test_cv_around_a_zero_mean_is_infinite(self):
        assert inversion._cv([-1.0, 1.0, -1.0, 1.0]) == float("inf")

    def test_worst_never_lets_a_clean_leg_win(self):
        assert inversion._worst("none", "severe", "caution") == "severe"
        assert inversion._worst("none", "caution") == "caution"
        assert inversion._worst("none", "none") == "none"

    def test_max_drawdown_reports_the_recovery(self):
        levels = [1.0, 2.0, 1.0, 2.5]
        worst = inversion.max_drawdown(levels)
        assert worst["drawdown"] == pytest.approx(-0.5)
        assert worst["recovered"] is True
        assert inversion.max_drawdown([1.0, 2.0, 1.0])["recovered"] is False
        assert inversion.max_drawdown([])["drawdown"] is None


# --- Regression: the anchors measured on the real export ---------------------------------

class TestRealDataAnchors:
    """Every number below was measured on the live export (~521 weekly bars back to 2016 for
    1,874 names, annual filings up to 19 periods). The real series are not in this repo, so
    each anchor is reproduced by the smallest synthetic series that carries the SAME
    statistic — the construction is documented on each test, and any change to a probe's
    definition breaks these.

    The real ADBE series carries three of these at once; the fixtures below isolate one
    statistic each, because a max drawdown is a property of the PATH while skew and the tail
    ratio are properties of the DISTRIBUTION, and pinning all three exactly at once would
    over-constrain a small series."""

    @pytest.mark.parametrize("name,anchor", [
        ("ADBE", -0.716), ("MEDP", -0.412), ("CRUS", -0.523),
    ])
    def test_price_max_drawdown(self, name, anchor):
        """Construction: 30 flat weeks at 100, one step to a 200 peak, one step down to
        200*(1+anchor), then flat. The deepest peak-to-trough fall is the anchor exactly,
        and there are 71 weekly returns — past the 52-return minimum."""
        result = inversion.probe_price_drawdown(grid(flat_then_drop(anchor)))
        assert round(result["value"], 3) == anchor
        assert result["severity"] == ("severe" if anchor <= -0.60 else "caution")

    def test_adbe_weekly_return_skew_and_tail_ratio(self):
        """Construction: a two-point weekly-return distribution, 307 weeks of +4.25% and 193
        of -5.00% (n = 500). For two values the skew is (1-2p)/sqrt(p(1-p)) with
        p = 307/500 = 0.614, giving -0.4697 -> -0.47; every gain is its own side's 95th
        percentile and every loss its 5th, so the tail ratio is 0.0425/0.05 = 0.85 exactly.
        Both are ADBE's measured values, and together they land the name on CAUTION rather
        than severe: -0.47 does not clear the -0.5 skew line the design requires for severe."""
        returns = two_point_returns(307, 0.0425, 193, -0.05)
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert round(result["evidence"]["skew"], 2) == -0.47
        assert round(result["evidence"]["tail_ratio"], 2) == 0.85
        assert result["severity"] == "caution"

    def test_exel_weekly_return_skew(self):
        """Construction: 127 weeks of +8% and 373 of -2% (p = 127/500 = 0.254 on the HIGH
        value), giving skew +1.1337 -> +1.13 — EXEL's measured value, and a positive skew is
        never a finding."""
        returns = two_point_returns(127, 0.08, 373, -0.02)
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert round(result["evidence"]["skew"], 2) == 1.13
        assert result["severity"] == "none"

    def test_medp_tail_ratio(self):
        """Construction: 60 weeks of +5.6% and 60 of -5.0% -> tail ratio 1.12 exactly, MEDP's
        measured value; balanced counts leave the skew at 0, so nothing fires."""
        returns = two_point_returns(60, 0.056, 60, -0.05)
        result = inversion.probe_return_asymmetry(grid(levels_from_returns(returns)))
        assert round(result["evidence"]["tail_ratio"], 2) == 1.12
        assert result["severity"] == "none"

    @pytest.mark.parametrize("name,anchor,severity", [
        ("CRUS", -0.89, "severe"),
        ("EXEL", -0.84, "severe"),
        ("RMD", -0.77, "severe"),
        ("MEDP", 0.0, "none"),
        ("NVDA", 0.0, "none"),
    ])
    def test_annual_owner_fcf_drawdown(self, name, anchor, severity):
        """Construction: an annual owner-FCF series that rises to a peak of 100 and falls to
        100*(1+anchor) the next year, then recovers — the recovery must not erase the fall.
        The two 0% names get a monotonically rising series instead, which is exactly what
        their filings show: Medpace and NVIDIA never let owner earnings fall below their own
        running peak, and that is the separation §3.3 exists to make."""
        if anchor == 0.0:
            series = [50.0, 75.0, 100.0, 140.0]
        else:
            series = [50.0, 100.0, 100.0 * (1.0 + anchor), 100.0 * (1.0 + anchor) * 1.2]
        result = inversion.probe_cash_engine(make_bundle(symbol=name, owner_fcf=series))
        assert round(result["value"], 2) == anchor
        assert result["severity"] == severity

    def test_the_cash_engine_separates_names_the_scorecard_cannot(self):
        """The §3.3 headline claim: Medpace (0%) and Cirrus Logic (-89%) are one verdict
        apart on this probe while nothing else in the record distinguishes them."""
        medp = inversion.probe_cash_engine(
            make_bundle(symbol="MEDP", owner_fcf=[50.0, 75.0, 100.0, 140.0]))
        crus = inversion.probe_cash_engine(
            make_bundle(symbol="CRUS", owner_fcf=[50.0, 100.0, 11.0, 13.2]))
        assert (medp["severity"], crus["severity"]) == ("none", "severe")
        assert round(crus["value"], 2) == -0.89
