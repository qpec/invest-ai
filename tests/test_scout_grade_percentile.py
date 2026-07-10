"""Stage-1 sector-percentile scoring (design §1 'each raw metric -> percentile within the
ticker's own sector -> [0,100]'). Higher-better vs lower-better handled per metric.

RF4 — the ROIC>15% reference line (one of only two fixed reference lines, design §1) must
exist and be blended into the ROIC leg: a ROIC below 15% caps/discounts the leg via the
absolute floor, reusing the v1 constant name QV_ROIC_MIN = 0.15.
"""
from agentcy import scout_grade as sg


def test_percentile_higher_is_better():
    pop = [10.0, 20.0, 30.0, 40.0]
    assert sg.sector_percentile(30.0, pop, higher_better=True) == 62.5  # scipy 'mean' rank
    assert sg.sector_percentile(40.0, pop, higher_better=True) == 87.5


def test_percentile_lower_is_better_inverts():
    pop = [1.0, 2.0, 3.0, 4.0]
    # low net-debt should score HIGH: value 1.0 (best) -> high percentile
    assert sg.sector_percentile(1.0, pop, higher_better=False) == 87.5
    assert sg.sector_percentile(4.0, pop, higher_better=False) == 12.5


def test_percentile_singleton_cohort_is_neutral_50():
    assert sg.sector_percentile(5.0, [5.0], higher_better=True) == 50.0


def test_percentile_all_missing_cohort_is_neutral_50():
    # RF4 — an all-missing (or empty) cohort scores 50.0 (neutral), never a false signal.
    assert sg.sector_percentile(5.0, [None, float("nan")], higher_better=True) == 50.0
    assert sg.sector_percentile(5.0, [], higher_better=False) == 50.0


def test_percentile_ignores_none_and_nan():
    pop = [10.0, None, 30.0, float("nan"), 40.0]
    assert sg.sector_percentile(30.0, pop, higher_better=True) == round(
        sg.sector_percentile(30.0, [10.0, 30.0, 40.0], higher_better=True), 6)


# --- RF4: ROIC leg blends the sector percentile with the absolute 15% reference line -----

def test_qv_roic_min_reference_line_exists():
    # RF4 — the >15% reference line is inherited from v1 as the RATIO 0.15 (roic as a fraction).
    assert sg.QV_ROIC_MIN == 0.15


def test_roic_leg_full_percentile_when_at_or_above_floor():
    # ROIC at/above 15% -> no discount, the leg IS the raw sector percentile.
    pop = [5.0, 10.0, 20.0, 30.0]  # ROIC values as PERCENTAGES (roic_pct)
    pct = sg.sector_percentile(20.0, pop, higher_better=True)
    assert sg.roic_leg_score(20.0, pop) == pct
    # exactly at the floor (15%) -> min(1, 15/15) = 1.0, still full percentile
    assert sg.roic_leg_score(15.0, [15.0, 15.0, 15.0]) == sg.sector_percentile(
        15.0, [15.0, 15.0, 15.0], higher_better=True)


def test_roic_leg_discounted_below_floor():
    # ROIC below 15% caps/discounts the leg by min(1, ROIC/15).
    pop = [3.0, 6.0, 9.0, 12.0]  # a cohort of sub-floor ROICs
    pct = sg.sector_percentile(9.0, pop, higher_better=True)
    # 9% ROIC -> factor 9/15 = 0.6
    assert sg.roic_leg_score(9.0, pop) == round(pct * 0.6, 6)


def test_roic_leg_zero_roic_scores_zero():
    # A non-positive ROIC fully collapses the leg regardless of cohort rank.
    assert sg.roic_leg_score(0.0, [0.0, 5.0, 10.0]) == 0.0


def test_roic_leg_singleton_cohort_neutral_then_discounted():
    # Singleton cohort -> neutral 50 percentile; a sub-floor ROIC still discounts it.
    assert sg.roic_leg_score(7.5, [7.5]) == round(50.0 * 0.5, 6)  # 7.5/15 = 0.5
    assert sg.roic_leg_score(30.0, [30.0]) == 50.0                # above floor, no discount
