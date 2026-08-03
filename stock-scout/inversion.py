"""The Inversion Layer — Munger's pillar (docs/INVERSION-DESIGN.md).

The scorecard asks how good a business is. This asks how it breaks. Seven deterministic
probes (§3) read ~10 years of weekly total-return prices and up to 19 years of annual
filings, each returning a severity and a sentence naming what it found; the severities are
COUNTED into a verdict (§4) and the sentences become `failure_modes`, the written answer to
"how would this lose my money?" that the system has never produced (§2).

Four rules here are load-bearing, not decoration:

  * **Severities are counted, never averaged (§4).** An average would let a good probe
    cancel a fatal one, which is precisely the inversion error. Every count in this module
    is a count.
  * **This layer never adds a point to the scorecard (§2).** Buffett's card says how good
    the business is; this says how it breaks, and folding fragility into the 100 points
    would let a high total paper over it. Nothing here returns or mutates points, and
    `inversion()` does not touch the card it is displayed beside.
  * **Silence is not safety (§7).** A probe with no evidence returns severity "none" — it
    must not invent a finding — but it is recorded in `coverage` as unmeasured and named
    out loud, and thin evidence collapses the verdict to Unknown rather than Robust. A
    verdict that asserts a failure mode (Fragile, Ruinous) still stands on thin evidence:
    missing data can refuse to certify safety, never manufacture it.
  * **Returns come from `adj_close`, never the raw close (§3.6 of RECONSTRUCTION.md).**
    Drawdowns are peak-to-trough on the cumulative series built from those returns.

It does not suppress: the §4.4 vetoes already do that on unambiguous conditions, while
inversion is judgement and judgement informs the owner (§2). The optional `--fragility-gate`
of §6 is a caller's decision, off by default; this module only supplies the verdict.

No I/O, no clock, no network — the same discipline as scoring.py and scorecard.py.

Per-probe result contract:
    {"id", "severity", "measured", "value", "detail", "evidence"}
`value` is the single number the probe's headline threshold turns on (a fraction for
drawdowns and shortfalls, a ratio for CVs and the refinancing wall), or None when there is
none; where a probe has several legs, `evidence["driver"]` names the leg that produced the
severity and `evidence` carries every input. `measured` is the §4 coverage bit: False means
no evidence was available, and the reason is in `evidence["reason"]`.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from scipy.stats import kurtosis, skew

import pit
import scoring

# --- Severities and verdicts (§4) --------------------------------------------------------

SEVERITY = ("none", "caution", "severe")
_RANK = {name: i for i, name in enumerate(SEVERITY)}

# §4's table, as data. `safe` is the fourth-lens reading (§5): True when the layer says the
# name will survive, False when it names a way it does not, None when it refuses to say.
# The ladder is CALIBRATED, and the calibration is the point. The design's original rungs
# (>=2 severe -> Ruinous, 1 severe -> Fragile) were written assuming probes fire rarely.
# Measured on the 1,904-name SEC export they fire on 2-50% of names each, so ">=2 of 6"
# is close to certain by arithmetic alone: it read Ruinous for 71% of the universe and,
# worse, read it for 68% of the scorecard's EXCEPTIONAL names against 88% of its lowest
# band — a two-point spread, which is a layer saying nothing while sounding certain.
# The rungs below were chosen against that measured distribution together with the
# permanence rules in §3.1/§3.3/§3.4. They yield Ruinous 20% / Fragile 26% / Ordinary 35% /
# Robust 4% / Unknown 15%, and the cross-tab that matters now runs 10% Ruinous in
# Exceptional to 45% in Pass — a 4.5x gradient where there was none.
VERDICTS = {
    "Ruinous": {
        "rule": "3 or more severe probes",
        "meaning": "Has already destroyed owner capital, or is built to",
        "safe": False},
    "Fragile": {
        "rule": "2 severe probes, or 4 or more cautions",
        "meaning": "Clear ways this breaks you",
        "safe": False},
    "Ordinary": {
        "rule": "at most 1 severe probe and fewer than 4 cautions",
        "meaning": "Normal business risk",
        "safe": True},
    "Robust": {
        "rule": "no severe probe and no caution",
        "meaning": "Has been tested and held",
        "safe": True},
    "Unknown": {
        "rule": "too little evidence to certify safety — a verdict that names a failure "
                "mode still stands, only Robust/Ordinary collapse to here",
        "meaning": "Said out loud, never read as safe",
        "safe": None},
}

# The two probes a verdict cannot be certified without: "ruin already demonstrated" (the
# price side) and "the cash engine breaking" (the owner's side, which §3.3 calls the one
# that matters most). Without either, the layer has not seen this name tested.
REQUIRED_PROBES = ("price_drawdown", "cash_engine")
MIN_MEASURED_COUNTING = 4       # of the 6 counting probes; below this the evidence is thin

# The ladder's rungs, in one place so `verdict_for` and the VERDICTS table cannot drift.
VERDICT_LADDER = {"ruinous_severe": 3, "fragile_severe": 2, "fragile_caution": 4}


# --- The probe registry (§3), as data ----------------------------------------------------
# Every threshold this module applies lives here, so the design's §3 maps onto the code 1:1.
# `counts` False means the probe is reported but never enters the verdict count NOR the
# coverage denominator — §3.7's "flag only", the one probe whose data is too sparse to score.
#
# Thresholds are INCLUSIVE on the risk side: a drawdown of exactly -60.0% reads severe, a
# refinancing ratio of exactly 1.0 reads severe. A layer built to name failure must not let
# a boundary read as safety.

PROBES = {
    "price_drawdown": {
        "section": "3.1",
        "label": "ruin already demonstrated",
        "question": "How far has this already fallen, and did it come back?",
        "reads": "weekly adj_close total-return series",
        "thresholds": {"severe": -0.60, "caution": -0.40, "min_bars": 52},
        "counts": True,
        "provenance": "Design §3.1 — severe past -60%, caution past -40%. `min_bars` (52 "
                      "weekly bars = one year) is declared here: the design gives no "
                      "minimum, and 'what it is capable of' cannot be read off a few "
                      "months. PERMANENCE is declared here and the design's §3.1 originally "
                      "said the opposite ('recovery is reported, never scored'): severe now "
                      "requires the deep fall to be UNRECOVERED. Measured on the 1,904-name "
                      "SEC export, 65% of names have fallen 60% at some point and 25% of "
                      "them regained the peak — scoring depth alone made the probe fire on "
                      "two names in three and say nothing. Munger's ruin is PERMANENT loss "
                      "of capital: a 70% fall that was regained is a volatile compounder "
                      "(Amazon 2022), and it is still a fall the owner had to sit through, "
                      "so it reads caution rather than nothing.",
    },
    "return_asymmetry": {
        "section": "3.2",
        "label": "return asymmetry",
        "question": "Are the losses fatter than the gains?",
        "reads": "weekly adj_close returns — skew and the 95th/5th percentile tail ratio",
        "thresholds": {"skew_severe": -0.5, "tail_ratio_severe": 0.9,
                       "min_bars": 52, "min_tail_side": 20},
        "counts": True,
        "provenance": "Design §3.2 — severe when skew < -0.5 AND tail ratio < 0.9. The "
                      "CAUTION rule is NOT in the design and is declared here: exactly one "
                      "of the two breached. `min_tail_side` (20 observations per side) is "
                      "nassim_taleb.analyze_tail_risk's own guard.",
    },
    "cash_engine": {
        "section": "3.3",
        "label": "the cash engine breaking",
        "question": "How far have owner earnings ever fallen from their own peak?",
        "reads": "annual normalized owner-FCF, one point per fiscal year "
                 "(annual_owner_fcf)",
        "thresholds": {"severe": -0.60, "caution": -0.35, "min_periods": 3,
                       "window_periods": 10, "floor": -1.0},
        "counts": True,
        "provenance": "Design §3.3 — severe past -60%, caution past -35%. `min_periods` (3) "
                      "is declared here; a peak and a single later point is not a history. "
                      "Three further rules are declared here and are load-bearing. (a) "
                      "`floor` CAPS the fall at -100%: owner-FCF is a signed difference of "
                      "large numbers, and once the trough crosses zero the percentage is "
                      "unbounded — the export's 5th percentile is -1,381%, which is not "
                      "twenty times worse than -60%, it is the denominator talking. (b) "
                      "`window_periods` (10) bounds the history to the last ten fiscal "
                      "years, the same span as the price history the other probes read, "
                      "and for the reason scoring caps the Buffett lens at 8: an engine "
                      "that broke in 2009 and has run cleanly since is not a broken engine. "
                      "(c) PERMANENCE, as in §3.1: severe requires the engine not to have "
                      "regained its peak. Unwindowed, uncapped and depth-only, this probe "
                      "read severe for 68% of the export and separated nothing.",
    },
    "stress": {
        "section": "3.4",
        "label": "stress behaviour",
        "question": "Did owner earnings survive the two occasions the world actually broke?",
        "reads": "annual owner-FCF (annual_owner_fcf) in the fiscal years covering 2020 "
                 "and 2022, against the highest owner-FCF of any prior year",
        "thresholds": {"years": (2020, 2022), "severe": -0.60, "caution": -0.35,
                       "window_start_month": 6},
        "counts": True,
        "provenance": "PERMANENCE, as in §3.1 and §3.3: a shock only reads severe when the "
                      "prior peak was never regained afterwards. Nearly every business on "
                      "earth earned less in 2020 than in 2019 — scoring the shortfall alone "
                      "made this probe say 'the cash engine buckled' for 56% of the export, "
                      "which is a description of COVID and not of the business. What "
                      "separates them is whether it came back. "
                      "Design §3.4 names the two tests but NO thresholds; -60%/-35% are "
                      "declared here, deliberately the same lines as §3.3 (the same "
                      "quantity, measured over a named window instead of the whole "
                      "history). The fiscal year covering stress year Y is the annual "
                      "period ending in [Y-06-01, Y+1-05-31] — one 12-month window, so "
                      "exactly one annual period falls in it and a January-ending filer's "
                      "FY2021 is correctly read as the 2020 demand shock.",
    },
    "predictability": {
        "section": "3.5",
        "label": "predictability",
        "question": "Can this business be valued at all?",
        "reads": "the MEAN ABSOLUTE DEVIATION of annual revenue growth, and of the "
                 "operating margin, both in points and both on annual-cadenced series",
        "thresholds": {"growth_mad_severe": 0.20, "growth_mad_caution": 0.10,
                       "margin_mad_severe": 0.10, "margin_mad_caution": 0.05,
                       "min_periods": 5},
        "counts": True,
        "provenance": "Design §3.5 names a coefficient of variation of revenue growth and "
                      "of operating margin, and NO thresholds. Neither leg uses that ratio, "
                      "for the reference's own reason: "
                      "charlie_munger.analyze_predictability measures "
                      "`sum(abs(r - avg))/len` — a MEAN ABSOLUTE DEVIATION in points — and "
                      "keeps average growth as a separate axis. Both quantities are SIGNED "
                      "and sit on top of zero, and a ratio there measures its denominator "
                      "instead of its dispersion: it grades a dead-FLAT revenue line, the "
                      "most forecastable shape there is, as maximally unpredictable "
                      "(Kenvue: +0.14%/yr average, 2.0 points of spread, CV 14.7), and it "
                      "structurally punishes any low-margin business. Flooring the "
                      "denominator patched that; measuring in points removes the need for "
                      "the patch. ABSOLUTE deviation rather than a standard deviation is "
                      "also deliberate and is the reference's: EDGAR revenue chains carry "
                      "tag-switch splices, and a squared penalty lets one of them decide "
                      "the answer — Procter & Gamble's chain contains a +121% year that a "
                      "standard deviation turns into 34 points of 'volatility' for a "
                      "business that grows 3%/yr, where the mean absolute deviation reads "
                      "20. The revenue lines 0.20/0.10 are the reference's own ('low "
                      "volatility' < 0.1, 'some volatility' < 0.2); across this 1,904-name "
                      "export they read severe for 32% of names and caution for 28%. The "
                      "margin lines 0.10/0.05 are declared here — an operating margin that "
                      "typically sits 10 points away from its own average is not a business "
                      "that can be valued — and read severe for 34%. `min_periods` (5) is "
                      "charlie_munger.analyze_predictability's own 'need 5+ years'.",
    },
    "financing": {
        "section": "3.6",
        "label": "financing fragility",
        "question": "Can it refinance without the owner, and was the owner diluted at the "
                    "bottom?",
        "reads": "debt due within twelve months vs cash + one year of owner earnings; and "
                 "the split-adjusted share count across the deepest price drawdown",
        "thresholds": {"wall_severe": 1.0, "wall_caution": 0.5,
                       "dilution_severe": 0.10, "dilution_caution": 0.03,
                       "min_drawdown": -0.30, "max_share_change": 1.0},
        "counts": True,
        "provenance": "Design §3.6 names both legs but NO thresholds. Declared here: the "
                      "wall is severe when the twelve-month maturity exceeds the resources "
                      "in hand (ratio >= 1.0). The dilution leg is measured peak-to-trough "
                      "of the deepest drawdown and only when that drawdown is at least 30% "
                      "deep — below that there is no 'bottom' to have been diluted at. "
                      "The design's 64%-of-filers figure is a property of EDGAR, NOT of "
                      "what reaches this layer: neither pit's concept table nor secsv's "
                      "tag-index fold maps the maturity tag, so on an EDGAR-built Bundle "
                      "this leg measures only through the broader "
                      "'Current Debt And Capital Lease Obligation' fallback a Yahoo-built "
                      "Bundle carries — and where nothing is found the leg is unmeasured, "
                      "never assumed safe. `max_share_change` (1.0) is declared here: a "
                      "share count that MORE THAN DOUBLES across one drawdown is not a "
                      "change this layer can attribute to an issuance — a split, a reverse "
                      "merger and a junk cover-page observation all read identically — so "
                      "it is named as unmeasured rather than reported as dilution. The leg "
                      "also requires a split history to be present at all: without one "
                      "scoring.adjusted_shares_series is a silent no-op and Amazon's 20:1 "
                      "split reads as +1,923% dilution at the 2022 bottom.",
    },
    "concentration": {
        "section": "3.7",
        "label": "customer concentration",
        "question": "Does one customer own this company's revenue?",
        "reads": "ConcentrationRiskPercentage1, tagged by ~11% of these filers",
        "thresholds": {"flag": 20.0},
        "counts": False,
        "provenance": "Design §3.7 — FLAG ONLY. Too sparse to score, so this probe never "
                      "contributes a severity and never enters the coverage denominator "
                      "(89% of names would otherwise read Unknown). Where the tag is absent "
                      "the layer says so out loud rather than implying the risk is absent — "
                      "the Cirrus Logic lesson. The 20% flag line is declared here; the SEC "
                      "requires disclosure from 10%, so any tagged value is already "
                      "material and is reported whatever its size. The design's ~11% is a "
                      "property of EDGAR and NOT of what reaches this layer: no ingester in "
                      "this repo maps ConcentrationRiskPercentage1 into the Bundle, so on "
                      "an EDGAR-built Bundle this probe is unmeasured for every name, "
                      "including the ~11% that do tag it. Mapping the tag is a data-layer "
                      "change (pit._BALANCE_CONCEPTS + secsv.INSTANT_TAGS); until it is "
                      "made, 'not tagged by this filer' means 'not carried by this Bundle'.",
    },
}

COUNTING_PROBES = tuple(pid for pid, spec in PROBES.items() if spec["counts"])

# §3.6/§3.7 row labels. Neither tag is mapped by pit.py's EDGAR concept maps or by
# scoring._CHAINS, so this module carries its own first-present-wins chains and accepts both
# the Yahoo-style spaced label and the raw EDGAR tag — whichever the ingester attaches.
# Absent from all of them -> the probe leg is unmeasured, never assumed safe (§3.6, §3.7).
#
# The first two entries are the design's own quantity. The last two are a Yahoo-only
# SUBSTITUTE that measures something BROADER — every short-term borrowing and lease, not
# just the twelve-month maturity of long-term debt — so when one of them is what fired the
# evidence says which label was read and the sentence names the substitution. On an
# EDGAR-built Bundle none of the four is present (see the §3.6 provenance).
_DEBT_DUE_12M_LABELS = (
    "Long Term Debt Maturities Repayments Of Principal In Next Twelve Months",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
    "Current Debt And Capital Lease Obligation",
    "Current Debt",
)
# The two above that are not the design's twelve-month maturity of long-term debt.
_DEBT_DUE_12M_SUBSTITUTES = _DEBT_DUE_12M_LABELS[2:]
_CONCENTRATION_LABELS = (
    "Concentration Risk Percentage1",
    "ConcentrationRiskPercentage1",
    "Concentration Risk Percentage",
)
# EDGAR tags ConcentrationRiskPercentage1 in the "pure" unit (0.90 for 90%), while a
# spreadsheet export of the same disclosure usually carries 90.0. A value at or below this
# line is therefore read as a ratio and scaled; above it, as a percentage already.
_CONCENTRATION_RATIO_CEILING = 1.5
# A tagged value of EXACTLY 100% is refused. ConcentrationRiskPercentage1 carries no axis
# member in this export, so a single-customer disclosure and the TOTAL row of a
# disaggregation table ("100% of revenue, disaggregated below") are indistinguishable — and
# 51 of the 212 filers that tag it at all tag exactly 1.0. Reading those as "one customer is
# 100% of revenue" would be the loudest false finding this probe could make, on the one
# probe whose entire job is to be believed when it speaks. Refused and named (§7).
_CONCENTRATION_TOTAL_ROW = 100.0


# --- Small numeric helpers ---------------------------------------------------------------

def _worst(*severities: str) -> str:
    """The most severe of several severities — the counting discipline in miniature: a
    clean leg never pulls a fatal one back down (§4)."""
    return max(severities, key=lambda s: _RANK[s])


def _percentile(values: list[float], q: float) -> float | None:
    """The q-th percentile with linear interpolation between order statistics (numpy's
    default 'linear' method, which is what nassim_taleb.analyze_tail_risk's np.percentile
    computes). Hand-rolled so the definition is visible and testable rather than implied."""
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * (q / 100.0)
    low = math.floor(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _finite(value):
    """A number the §3.3 grades JSON can actually hold: an infinity or a NaN becomes None.

    The consumer writes the run with `allow_nan=False` and DROPS a verdict it cannot
    serialize, so one infinity in the evidence would silently cost the name its whole
    inversion — the loudest possible way for absent-looking data to read as safety. The
    severity such a value produced is computed BEFORE this runs and is kept; only the
    unrepresentable number is dropped, and the sentence says what it was."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isinf(number) or math.isnan(number) else number


def _pct(fraction: float, dp: int = 1) -> str:
    """A fraction as a magnitude percentage — the sentences say "fell 71.6%", not "-71.6%"."""
    return f"{abs(100.0 * fraction):.{dp}f}%"


def _cv(values: list[float], floor: float = 0.0) -> float:
    """Coefficient of variation: population stdev / max(|mean|, `floor`) (the same pstdev
    scoring._gross_margin_cv uses). A dispersion of zero is perfectly predictable whatever
    the mean.

    `floor` is what keeps the ratio meaningful on a SIGNED quantity. Revenue growth and an
    operating margin can both sit on top of zero, and there the raw ratio measures the
    denominator rather than the dispersion: a business whose revenue is FLAT — the most
    forecastable shape there is — divides a small spread by an average of almost nothing
    and comes out maximally unpredictable. Flooring the denominator bounds that, and the
    floor is declared in PROBES['predictability']['thresholds'] rather than hidden here.
    With the default floor of 0 the behaviour is the unfloored textbook definition: a
    non-zero dispersion around a zero mean is infinitely unpredictable, and saying so is
    more honest than a ZeroDivisionError or a comforting 0.0."""
    if len(values) < 2:
        return 0.0
    spread = statistics.pstdev(values)
    if spread == 0.0:
        return 0.0
    denominator = max(abs(sum(values) / len(values)), floor)
    return spread / denominator if denominator else math.inf


def _mad(values: list[float]) -> float:
    """Mean absolute deviation about the mean, in the units of `values` —
    charlie_munger.analyze_predictability's own `sum(abs(r - avg))/len`.

    ABSOLUTE, not squared, and that is the point: EDGAR concept chains carry tag-switch
    splices, and a standard deviation lets one of them decide the answer. Procter & Gamble's
    revenue chain contains a +121% year that never happened as a business event — a standard
    deviation turns it into 34 points of 'volatility' for a company that grows 3%/yr, where
    this reads 20. Neither is zero, because the splice IS in the data and pretending
    otherwise would be its own dishonesty; one of them is survivable."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum(abs(value - mean) for value in values) / len(values)


def _is_day(key) -> bool:
    """A §3.6 grid key ("YYYY-MM-DD") rather than a symbol."""
    text = str(key)
    return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _grid(prices, symbol: str | None = None) -> dict:
    """One name's §3.6 weekly grid from either shape callers hold it in: the bare
    date-keyed grid {"YYYY-MM-DD": bar}, or the {symbol: grid} map pit.price_at takes."""
    if not prices:
        return {}
    if all(_is_day(key) for key in prices):
        return prices
    if symbol is not None and symbol in prices:
        return prices[symbol] or {}
    return {}


def price_series(prices, symbol: str | None = None) -> list[tuple[str, float]]:
    """Ascending (day, adj_close) from a §3.6 weekly grid — the ADJUSTED close, always.
    Total-return math is the only thing this layer does with a price, and the raw close
    would make every dividend and split read as a loss. Bars are read through pit.bar_value,
    so a legacy plain-float grid still loads (degraded, its one value standing for both
    fields). Non-positive or unreadable bars are dropped rather than silently zeroed."""
    grid = _grid(prices, symbol)
    out = []
    for day in sorted(grid):
        value = pit.bar_value(grid[day], "adj_close")
        if value is not None and value > 0:
            out.append((str(day), float(value)))
    return out


def weekly_returns(series: list[tuple[str, float]]) -> list[float]:
    """Simple period-over-period returns of an ascending (day, adj_close) series."""
    return [series[i][1] / series[i - 1][1] - 1.0 for i in range(1, len(series))]


def cumulative(returns: list[float]) -> list[float]:
    """The cumulative total-return series from 1.0 — the series §3.1's drawdown is measured
    peak-to-trough on. ONE LEVEL PER BAR: level i belongs to the bar that produced
    returns[i-1], and level 0 is the starting 1.0 of the bar the first return is measured
    FROM. Dropping that starting level (as (1 + returns).cumprod() does, and as this
    function used to) makes the first bar unable to be the peak, so a series that opens at
    its all-time high reports no drawdown at all — the design says "deepest peak-to-trough
    in the weekly total-return series", and the first bar is in that series."""
    out, level = [1.0], 1.0
    for r in returns:
        level *= (1.0 + r)
        out.append(level)
    return out


def max_drawdown(levels: list[float]) -> dict:
    """Deepest peak-to-trough fall in a cumulative series -> {drawdown, peak_index,
    trough_index, recovered}. `drawdown` is a non-positive fraction; `recovered` is whether
    the series ever regained the peak it fell from. An empty or non-positive-peaked series
    yields drawdown None."""
    peak, peak_index = None, None
    worst = {"drawdown": None, "peak_index": None, "trough_index": None, "recovered": False}
    for i, level in enumerate(levels):
        if peak is None or level > peak:
            peak, peak_index = level, i
        if peak is None or peak <= 0:
            continue
        fall = (level - peak) / peak
        if worst["drawdown"] is None or fall < worst["drawdown"]:
            worst = {"drawdown": fall, "peak_index": peak_index, "trough_index": i,
                     "recovered": False}
    if worst["drawdown"] is not None and worst["peak_index"] is not None:
        # Compared with a relative tolerance because `levels` is an accumulated PRODUCT of
        # returns: a price that climbs back to exactly its old peak lands a few ulps below
        # it (1.1 * (200/110) = 1.9999999999999998), and a strict >= would report a fully
        # recovered series as permanently impaired. Now that §3.1 scores recovery, that
        # knife-edge is the difference between "caution" and "ruin".
        peak_level = levels[worst["peak_index"]] * (1.0 - RECOVERY_TOLERANCE)
        worst["recovered"] = any(level >= peak_level
                                 for level in levels[worst["trough_index"] + 1:])
    return worst


def series_drawdown(points: list[tuple[str, float]]) -> dict:
    """Deepest peak-to-trough fall in a dated (period, value) series, ignoring falls from a
    non-positive peak (a fall from a peak of zero has no percentage). Returns
    {drawdown, peak, peak_period, trough, trough_period, positive_peaks}."""
    peak, peak_period = None, None
    out = {"drawdown": None, "peak": None, "peak_period": None, "trough": None,
           "trough_period": None, "positive_peaks": False}
    for period, value in points:
        if peak is None or value > peak:
            peak, peak_period = value, period
        if peak is None or peak <= 0:
            continue
        out["positive_peaks"] = True
        fall = (value - peak) / peak
        if out["drawdown"] is None or fall < out["drawdown"]:
            out.update({"drawdown": fall, "peak": peak, "peak_period": peak_period,
                        "trough": value, "trough_period": period})
    return out


# Relative slack on "did it regain the peak" (§3.1). Purely numerical — see max_drawdown.
RECOVERY_TOLERANCE = 1e-9

MIN_ANNUAL_GAP_DAYS = 300       # §3.3/§3.4: one point per fiscal year, declared here


def annual_cadence(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """The longest ~yearly-spaced run of a dated series, oldest first: a point is kept only
    when it lands at least MIN_ANNUAL_GAP_DAYS after the last point kept.

    §3.3 and §3.4 both compare one year of owner earnings against another year of owner
    earnings, and `annual.cashflow` does not always hold one point per year. Real bundles
    carry quarterly period ends and short transition stubs in that section (a 184-day stub,
    a quarter sitting inside a stress window), and a sub-annual figure divided by an ANNUAL
    prior peak manufactures a shortfall of hundreds of percent out of nothing. Overlapping
    trailing-twelve-month points ending each quarter are the same problem in reverse: they
    are not extra evidence, they are the same year counted four times.

    A clean annual series passes through untouched, which is the normal case; only a series
    that is not annual is thinned. 300 days is declared here — below a 52/53-week fiscal
    year (pit.annual_flows accepts 330-400 days) with room for the wobble, and far above a
    quarter, so nothing legitimate is dropped and nothing sub-annual survives."""
    kept, last = [], None
    for period_end, value in points:
        try:
            day = date.fromisoformat(str(period_end))
        except ValueError:
            continue
        if last is not None and (day - last).days < MIN_ANNUAL_GAP_DAYS:
            continue
        kept.append((period_end, value))
        last = day
    return kept


def annual_owner_fcf(bundle: dict) -> list[tuple[str, float]]:
    """§3.3/§3.4's input: scoring's annual owner-FCF points, thinned to one per fiscal year
    (annual_cadence). The layer measures a YEAR against a YEAR or it does not measure."""
    return annual_cadence(scoring._annual_owner_fcf_points(bundle))


def _result(probe_id: str, severity: str, value, detail: str, evidence: dict,
            measured: bool = True) -> dict:
    return {"id": probe_id, "severity": severity, "measured": measured, "value": value,
            "detail": detail, "evidence": evidence}


def _unmeasured(probe_id: str, reason: str, evidence: dict | None = None) -> dict:
    """A probe with no evidence: severity "none" (it must not invent a finding) but
    measured=False, so coverage names it and the verdict cannot read it as safety (§7)."""
    spec = PROBES[probe_id]
    return _result(probe_id, "none", None,
                   f"Not measured — {spec['label']}: {reason}. Absent evidence is not "
                   f"safety (§7).", {**(evidence or {}), "reason": reason}, measured=False)


# --- §3.1 Ruin already demonstrated ------------------------------------------------------

def probe_price_drawdown(prices, symbol: str | None = None) -> dict:
    """§3.1 — the deepest peak-to-trough fall in the weekly total-return series, and whether
    it recovered. A business that has already fallen 70% has told you what it is capable of.

    RECOVERY IS SCORED, and this is the change that makes the probe mean something. Munger's
    ruin is PERMANENT loss of capital, so severe requires the deep fall to be unrecovered.
    On the 1,904-name SEC export 65% of names have fallen 60% at some point — a probe that
    fires on two names in three is not a filter — and a quarter of those regained the peak.
    A recovered 70% fall is a volatile compounder, not a ruined business; it is still a 70%
    fall the owner had to sit through, so it reads caution rather than nothing."""
    thresholds = PROBES["price_drawdown"]["thresholds"]
    series = price_series(prices, symbol)
    returns = weekly_returns(series)
    if len(returns) < thresholds["min_bars"]:
        return _unmeasured("price_drawdown",
                           f"only {len(returns)} weekly return(s), fewer than the "
                           f"{thresholds['min_bars']} a drawdown history needs",
                           {"bars": len(returns)})

    worst = max_drawdown(cumulative(returns))
    if worst["drawdown"] is None:
        return _unmeasured("price_drawdown",
                           "the cumulative total-return series never holds a positive peak "
                           "— the grid is not a usable price history",
                           {"bars": len(returns)})
    depth = worst["drawdown"]
    # cumulative() returns one level per BAR, so index i of the cumulative series is
    # series[i] — including index 0, the bar the first return is measured from.
    peak_day = series[worst["peak_index"]][0]
    trough_day = series[worst["trough_index"]][0]

    recovered = worst["recovered"]
    if depth <= thresholds["severe"] and not recovered:
        severity = "severe"
    elif depth <= thresholds["severe"] or (depth <= thresholds["caution"] and not recovered):
        severity = "caution"
    else:
        severity = "none"

    if severity == "severe":
        detail = (f"The price has fallen {_pct(depth)} peak-to-trough ({peak_day} -> "
                  f"{trough_day}) and has NOT regained that peak — capital put in at the "
                  f"top has been permanently impaired, which is what ruin means.")
    elif severity == "caution" and recovered:
        detail = (f"The price fell {_pct(depth)} peak-to-trough ({peak_day} -> "
                  f"{trough_day}) and has since regained that peak — volatile, not ruined, "
                  f"but a fall the owner had to sit through.")
    elif severity == "caution":
        detail = (f"The price has fallen {_pct(depth)} peak-to-trough ({peak_day} -> "
                  f"{trough_day}) and has not regained that peak.")
    else:
        tail = (" and regained it" if recovered else "")
        detail = (f"The deepest fall in the total-return record is {_pct(depth)} "
                  f"({peak_day} -> {trough_day}){tail} — this price has not yet shown the "
                  f"owner a ruinous move.")
    return _result("price_drawdown", severity, depth, detail,
                   {"drawdown": depth, "peak_day": peak_day, "trough_day": trough_day,
                    "recovered": worst["recovered"], "bars": len(returns)})


# --- §3.2 Return asymmetry ---------------------------------------------------------------

def probe_return_asymmetry(prices, symbol: str | None = None) -> dict:
    """§3.2 — skew of the weekly returns and the tail ratio (95th percentile of the gains
    over the 5th percentile of the losses, nassim_taleb.analyze_tail_risk's own definition).
    A name whose losses are fatter than its gains is paying you less than it charges you.

    Severe needs BOTH breached, per the design. Caution on exactly one is declared here.
    Excess kurtosis is carried in the evidence as context — the design's rule does not use
    it, and this layer does not invent thresholds it was not given a purpose for.

    Because severe is an AND, a probe whose tail leg has no evidence CANNOT reach severe
    however negative the skew is. That bounds the claim, not the risk, so the missing leg
    is pushed onto `evidence["unmeasured"]` the way §3.6's legs are and the sentence says
    in words that severe was out of reach — an absence that silently caps a severity while
    the probe still reports itself measured is the §7 error in miniature."""
    thresholds = PROBES["return_asymmetry"]["thresholds"]
    returns = weekly_returns(price_series(prices, symbol))
    if len(returns) < thresholds["min_bars"]:
        return _unmeasured("return_asymmetry",
                           f"only {len(returns)} weekly return(s), fewer than the "
                           f"{thresholds['min_bars']} a return distribution needs",
                           {"bars": len(returns)})

    # A series with no dispersion at all has no skew to speak of (scipy returns NaN); that
    # is "nothing to find", not a finding, and it must not reach the JSON as a NaN.
    skewness = _finite(skew(returns, bias=False))
    excess_kurtosis = _finite(kurtosis(returns, bias=False))
    gains = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    tail_ratio, tail_note = None, None
    if len(gains) >= thresholds["min_tail_side"] and len(losses) >= thresholds["min_tail_side"]:
        right = _percentile(gains, 95.0)
        left = abs(_percentile(losses, 5.0))
        tail_ratio = right / left if left > 0 else None
    else:
        tail_note = (f"tail ratio not computable — {len(gains)} gain week(s) and "
                     f"{len(losses)} loss week(s), fewer than the "
                     f"{thresholds['min_tail_side']} per side it needs")

    skew_bad = skewness is not None and skewness < thresholds["skew_severe"]
    tail_bad = tail_ratio is not None and tail_ratio < thresholds["tail_ratio_severe"]
    if skew_bad and tail_bad:
        severity = "severe"
    elif skew_bad or tail_bad:
        severity = "caution"
    else:
        severity = "none"

    tail_text = "not computable" if tail_ratio is None else f"{tail_ratio:.2f}"
    skew_text = ("undefined — the weekly returns have no dispersion at all"
                 if skewness is None else f"{skewness:+.2f}")
    if severity == "severe":
        detail = (f"Losses are fatter than gains on both counts: weekly-return skew "
                  f"{skew_text} and a tail ratio of {tail_text} — this name is paying "
                  f"the owner less than it charges him.")
    elif severity == "caution":
        broken = (f"the return distribution leans to the downside (skew {skew_text})"
                  if skew_bad else
                  f"the worst weeks are bigger than the best ones (tail ratio {tail_text})")
        detail = (f"Returns are asymmetric on one of the two counts: {broken}, with "
                  f"skew {skew_text} and tail ratio {tail_text}.")
    else:
        detail = (f"Gains and losses are symmetric enough: weekly-return skew "
                  f"{skew_text}, tail ratio {tail_text}.")
    if tail_note:
        detail = (f"{detail} (Not measured: {tail_note} — severe needs BOTH legs breached, "
                  f"so this probe could not reach it.)")
    return _result("return_asymmetry", severity, skewness, detail,
                   {"skew": skewness, "tail_ratio": tail_ratio,
                    "excess_kurtosis": excess_kurtosis, "gain_weeks": len(gains),
                    "loss_weeks": len(losses), "bars": len(returns),
                    "driver": "skew and tail ratio", "note": tail_note,
                    "severe_reachable": tail_ratio is not None,
                    "unmeasured": [tail_note] if tail_note else []})


# --- §3.3 The cash engine breaking -------------------------------------------------------

def probe_cash_engine(bundle: dict) -> dict:
    """§3.3 — the deepest peak-to-trough fall in ANNUAL owner earnings. The one that matters
    most to an owner: the share price recovering is optional, the cash engine recovering is
    not. On real data it separates names the scorecard cannot (Medpace 0%, Cirrus -89%).

    A history in which owner earnings were NEVER positive is severe, not unmeasured: the
    evidence is present and it says the engine has never run. Calling that "no data" would
    be exactly the silence §7 forbids.

    THREE rules make this probe discriminate rather than describe (see the §3.3 provenance).
    The fall is CAPPED at `floor` — owner-FCF is a signed difference of large numbers and
    the percentage is unbounded once the trough crosses zero, so the export's 5th percentile
    is -1,381% and depth stops ordering anything. The history is WINDOWED to the last
    `window_periods` fiscal years, because an engine that broke in 2009 and has run cleanly
    since is not a broken engine — the same reason scoring caps the Buffett lens at 8 years.
    And severe requires PERMANENCE: the peak was never regained, or the trough went
    negative and stayed there. A cyclical engine that fell hard and came back is a caution.

    The series is read through annual_cadence: a quarter or a stub sitting in
    `annual.cashflow` is a smaller number for a shorter period, and letting one become the
    trough of a peak-to-trough measured on YEARS invents a collapse that did not happen."""
    thresholds = PROBES["cash_engine"]["thresholds"]
    full = annual_owner_fcf(bundle)
    points = full[-thresholds["window_periods"]:]
    if len(points) < thresholds["min_periods"]:
        return _unmeasured("cash_engine",
                           f"only {len(points)} usable annual owner-FCF period(s), fewer "
                           f"than the {thresholds['min_periods']} a peak-to-trough needs",
                           {"periods": len(points)})

    fall = series_drawdown(points)
    if not fall["positive_peaks"]:
        return _result("cash_engine", "severe", thresholds["floor"],
                       f"Owner earnings were never positive in the {len(points)} annual "
                       f"period(s) held ({points[0][0]} -> {points[-1][0]}) — there is no "
                       f"peak to fall from because the cash engine has never run.",
                       {"periods": len(points), "positive_peaks": False,
                        "first_period": points[0][0], "last_period": points[-1][0]})

    # Capped: below -100% the ratio is the denominator talking, not a deeper fall.
    depth = max(fall["drawdown"], thresholds["floor"])
    after = [value for period, value in points if period > (fall["trough_period"] or "")]
    recovered = any(value >= fall["peak"] for value in after)
    went_negative = fall["trough"] is not None and fall["trough"] < 0

    if not recovered and (went_negative or depth <= thresholds["severe"]):
        severity = "severe"
    elif depth <= thresholds["severe"] or (not recovered
                                           and depth <= thresholds["caution"]):
        severity = "caution"
    else:
        severity = "none"

    span = f"{points[0][0]} -> {points[-1][0]}"
    if severity == "none" and depth == 0.0:
        detail = (f"Owner earnings never fell below their own running peak across "
                  f"{len(points)} annual periods ({span}) — the cash engine has not broken "
                  f"in the window held.")
    elif severity == "none":
        detail = (f"Owner earnings dipped {_pct(depth, 0)} below their {fall['peak_period']} "
                  f"peak in {fall['trough_period']} and recovered — a dip, not a break.")
    elif severity == "caution":
        detail = (f"The cash engine fell {_pct(depth, 0)} from its {fall['peak_period']} "
                  f"peak to its {fall['trough_period']} trough"
                  + (" and has since regained that peak — a cyclical engine, not a broken "
                     "one." if recovered else
                     f", and is still below it ({span})."))
    else:
        why = ("went negative and has not come back" if went_negative and not recovered
               else "has not regained that peak")
        detail = (f"The cash engine fell {_pct(depth, 0)} from its {fall['peak_period']} "
                  f"peak to its {fall['trough_period']} trough and {why} — the price "
                  f"recovering is optional, owner earnings recovering is not.")
    return _result("cash_engine", severity, depth, detail,
                   {"drawdown": depth, "uncapped_drawdown": fall["drawdown"],
                    "peak": fall["peak"], "peak_period": fall["peak_period"],
                    "trough": fall["trough"], "trough_period": fall["trough_period"],
                    "recovered": recovered, "went_negative": went_negative,
                    "periods": len(points), "periods_available": len(full)})


# --- §3.4 Stress behaviour ---------------------------------------------------------------

def _stress_period(points: list[tuple[str, float]], year: int, start_month: int):
    """The annual period covering stress year `year`: the one ending inside the 12-month
    window that opens on `start_month` of that year. One window exactly 12 months wide, so
    exactly one annual period of a normal filer falls in it — and a January-ending filer's
    FY2021 (Feb 2020 - Jan 2021) is correctly read as the 2020 demand shock rather than a
    2021 event. The latest match wins if a restatement leaves two.

    `points` must already be annual-cadenced (annual_owner_fcf): a quarter or a stub inside
    the window would otherwise win it on end date alone and be divided by an ANNUAL prior
    peak, which reads as a shortfall of several hundred percent that never happened."""
    lo = date(year, start_month, 1).isoformat()
    hi = (date(year + 1, start_month, 1) - timedelta(days=1)).isoformat()
    matches = [p for p in points if lo <= p[0] <= hi]
    return matches[-1] if matches else None


def probe_stress(bundle: dict) -> dict:
    """§3.4 — owner-FCF in the fiscal years covering 2020 (a demand shock) and 2022 (a rate
    shock), each against the highest owner-FCF of any prior year. Not a simulation: two
    occasions on which the world actually broke, inside the data we hold. A business that
    kept earning through both has evidence no model can manufacture."""
    thresholds = PROBES["stress"]["thresholds"]
    points = annual_owner_fcf(bundle)
    tested, skipped = [], []
    for year in thresholds["years"]:
        match = _stress_period(points, year, thresholds["window_start_month"])
        if match is None:
            skipped.append(f"no annual period covers {year}")
            continue
        prior = [v for pe, v in points if pe < match[0]]
        if not prior:
            skipped.append(f"no annual period before {match[0]} to take a prior peak from")
            continue
        peak = max(prior)
        if peak <= 0:
            skipped.append(f"owner earnings before {match[0]} never exceeded 0, so the "
                           f"{year} shortfall has no percentage")
            continue
        # PERMANENCE, as in §3.1 and §3.3: did any later year regain the peak it fell from?
        # Nearly every business earned less in 2020 than in 2019; what separates them is
        # whether the shortfall was a dip or a step down.
        recovered = any(value >= peak for period, value in points if period > match[0])
        tested.append({"year": year, "period": match[0], "owner_fcf": match[1],
                       "prior_peak": peak, "shortfall": (match[1] - peak) / peak,
                       "recovered": recovered})

    if not tested:
        return _unmeasured("stress", "; ".join(skipped) or "no annual owner-FCF history",
                           {"skipped": skipped})

    severity = "none"
    for test in tested:
        deep = test["shortfall"] <= thresholds["severe"]
        if deep and not test["recovered"]:
            severity = _worst(severity, "severe")
        elif deep or (test["shortfall"] <= thresholds["caution"] and not test["recovered"]):
            severity = _worst(severity, "caution")
    deepest = min(tested, key=lambda t: t["shortfall"])

    shocks = {2020: "demand shock", 2022: "rate shock"}
    parts = []
    for test in tested:
        shock = shocks.get(test["year"], "shock")
        if test["shortfall"] < 0:
            back = (" and it came back" if test["recovered"]
                    else " and it has not come back")
            parts.append(f"the {test['year']} {shock} took owner earnings "
                         f"{_pct(test['shortfall'], 0)} below the prior peak "
                         f"({test['period']}){back}")
        else:
            parts.append(f"the {test['year']} {shock} left owner earnings "
                         f"{_pct(test['shortfall'], 0)} ABOVE the prior peak "
                         f"({test['period']})")
    joined = "; ".join(parts)
    # The claim is scaled to the evidence (§7). "Held through the real tests" is a plural
    # claim about BOTH of the design's two tests, and it is only made when both actually
    # ran and neither took owner earnings below the prior peak — a 34% shortfall is inside
    # this layer's lines but it is not "held", and one test is not "the tests".
    all_tested = not skipped and len(tested) == len(thresholds["years"])
    kept_earning = all(test["shortfall"] >= 0 for test in tested)
    noun = "test" if len(tested) == 1 else "tests"
    if severity == "none" and all_tested and kept_earning:
        detail = (f"Owner earnings held through both real tests — {joined}. That is "
                  f"evidence no model can manufacture.")
    elif severity == "none":
        detail = (f"Owner earnings stayed inside the lines this layer draws on the "
                  f"{noun} it could run — {joined}.")
    elif severity == "caution":
        # The headline must not outrun its own body: every shock at this rung either was
        # shallow or was recovered from, and "buckled" is a claim about a break (§7).
        detail = (f"The cash engine bent when the world tilted: {joined}.")
    else:
        detail = f"The cash engine buckled when the world tilted: {joined}."
    if skipped:
        detail = f"{detail} (Not tested: {'; '.join(skipped)}.)"
    return _result("stress", severity, deepest["shortfall"], detail,
                   {"tested": tested, "skipped": skipped, "driver": str(deepest["year"]),
                    "years_tested": len(tested), "both_tests_ran": all_tested,
                    "unmeasured": list(skipped)})


# --- §3.5 Predictability -----------------------------------------------------------------

def _annual_operating_margins(bundle: dict) -> list[tuple[str, float]]:
    """Ascending (period, operating income / revenue) over the annual income statement,
    thinned to one point per fiscal year (annual_cadence) so four overlapping
    trailing-twelve-month points do not count one year four times."""
    inc = (bundle.get("annual") or {}).get("income") or {}
    out = []
    for pe in sorted(inc):
        op = scoring._row(inc[pe], "operating_income")
        rev = scoring._row(inc[pe], "revenue")
        if op is not None and rev is not None and rev > 0:
            out.append((pe, op / rev))
    return annual_cadence(out)


def probe_predictability(bundle: dict) -> dict:
    """§3.5 — Munger's own filter. An unpredictable business cannot be valued, and what
    cannot be valued must be avoided regardless of how cheap it looks; this is also the
    constitution's "if the thesis needs a spreadsheet with 47 assumptions, walk away".

    BOTH legs measure a MEAN ABSOLUTE DEVIATION IN POINTS, not a coefficient of variation —
    charlie_munger.analyze_predictability's own measure, and the fix for two real defects of
    the ratio. Revenue growth and an operating margin are signed quantities that sit on top
    of zero, so a ratio there measures its denominator rather than its dispersion: it grades
    a dead-flat revenue line as maximally unpredictable and punishes every low-margin
    business for arithmetic rather than instability. And an ABSOLUTE deviation, rather than
    a standard one, keeps a single EDGAR tag-switch splice from deciding the answer (see the
    §3.5 provenance and its Procter & Gamble case).

    The two legs are taken at their WORST, never averaged — the same counting discipline
    the verdict runs on."""
    thresholds = PROBES["predictability"]["thresholds"]
    # Both series are annual-cadenced: a quarter sitting among the annual revenues would
    # otherwise read as a -75% year followed by a +300% one, and invent the very
    # unpredictability this probe is looking for.
    revenues = annual_cadence(scoring._annual_revenue_points(bundle))
    margins = _annual_operating_margins(bundle)
    minimum = thresholds["min_periods"]

    growth_mad, mean_growth, margin_mad, mean_margin, missing = None, None, None, None, []
    if len(revenues) >= minimum:
        growth = [revenues[i][1] / revenues[i - 1][1] - 1.0
                  for i in range(1, len(revenues)) if revenues[i - 1][1] > 0]
    else:
        growth = []
        missing.append(f"only {len(revenues)} usable annual revenue period(s), fewer than "
                       f"the {minimum} a growth dispersion needs")
    if len(growth) >= 2:
        mean_growth = sum(growth) / len(growth)
        growth_mad = _mad(growth)
    elif not missing:
        missing.append("fewer than two usable year-over-year revenue growth rates")
    if len(margins) >= minimum:
        values = [m for _, m in margins]
        mean_margin = sum(values) / len(values)
        margin_mad = _mad(values)
    else:
        missing.append(f"only {len(margins)} usable annual operating-margin period(s), "
                       f"fewer than the {minimum} a margin dispersion needs")

    if growth_mad is None and margin_mad is None:
        return _unmeasured("predictability", "; ".join(missing),
                           {"revenue_periods": len(revenues),
                            "margin_periods": len(margins)})

    def severity_of(value, caution, severe):
        if value is None:
            return "none"
        if value >= severe:
            return "severe"
        return "caution" if value >= caution else "none"

    growth_severity = severity_of(growth_mad, thresholds["growth_mad_caution"],
                                  thresholds["growth_mad_severe"])
    margin_severity = severity_of(margin_mad, thresholds["margin_mad_caution"],
                                  thresholds["margin_mad_severe"])
    severity = _worst(growth_severity, margin_severity)
    # The driver is the leg that produced the severity; on a tie the leg that actually has a
    # number wins, so an unmeasured leg never becomes the headline of a measured probe.
    if (_RANK[growth_severity], growth_mad is not None) >= (_RANK[margin_severity],
                                                            margin_mad is not None):
        driver, value = "revenue growth", growth_mad
    else:
        driver, value = "operating margin", margin_mad

    growth_text = margin_text = None
    if growth_mad is not None:
        growth_text = (f"annual revenue growth is typically {100 * growth_mad:.0f} points "
                       f"away from its {100 * mean_growth:.0f}%/yr average")
    if margin_mad is not None:
        margin_text = (f"the operating margin is typically {100 * margin_mad:.0f} points "
                       f"away from its {100 * mean_margin:.0f}% average")
    parts = [text for text in (growth_text, margin_text) if text]
    joined = " and ".join(parts)
    # "This business can be forecast" is a claim about the business; it is only made when
    # both of the design's two legs were measured. With one leg missing the sentence says
    # what was measured instead — a forward claim from half the evidence is the §7 error
    # ("inversion with evidence, not foresight").
    if severity == "none" and not missing:
        detail = (f"This business can be forecast: {joined} — steady enough to be valued "
                  f"without a spreadsheet of assumptions.")
    elif severity == "none":
        detail = (f"What could be measured is steady: {joined} — but not every leg of "
                  f"this probe had evidence, so this is not a verdict on the whole "
                  f"business.")
    else:
        detail = (f"This business resists valuation: {joined} — what cannot be valued must "
                  f"be avoided however cheap it looks.")
    if missing:
        detail = f"{detail} (Not measured: {'; '.join(missing)}.)"
    return _result("predictability", severity, _finite(value), detail,
                   {"growth_mad": _finite(growth_mad), "mean_growth": _finite(mean_growth),
                    "margin_mad": _finite(margin_mad), "mean_margin": _finite(mean_margin),
                    "driver": driver, "revenue_periods": len(revenues),
                    "margin_periods": len(margins), "missing": missing})


# --- §3.6 Financing fragility ------------------------------------------------------------

def _disclosure(bundle: dict, label: str) -> dict:
    """One dated point out of the Bundle's `disclosures` block (pit._DISCLOSURE_CONCEPTS),
    or {} when the filer never tagged it. The block carries `end` and `filed` beside the
    value, which is what lets these probes say how OLD a disclosure is instead of
    presenting a nine-year-old fact as a description of the business today."""
    point = (bundle.get("disclosures") or {}).get(label)
    return point if isinstance(point, dict) and point.get("value") is not None else {}


def _debt_due_12m(bundle: dict) -> tuple[float | None, str | None]:
    """(debt due within twelve months, the label it was read from). The Bundle's
    `disclosures` block first — that is the design's own quantity, EDGAR's
    LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths, tagged by ~66% of the
    filers in the SEC export — then the latest balance sheet, first present wins along
    _DEBT_DUE_12M_LABELS. Absent -> (None, None) -> not scored, never assumed safe (§3.6).

    The label travels with the number because the last two entries of the chain are a
    BROADER substitute — all short-term borrowings and leases rather than the twelve-month
    maturity of long-term debt the design names — and a probe that silently swaps its own
    quantity is not auditable."""
    point = _disclosure(bundle, "debt_due_12m")
    if point:
        return abs(float(point["value"])), _DEBT_DUE_12M_LABELS[1]
    balance = scoring._latest_balance(bundle)
    for label in _DEBT_DUE_12M_LABELS:
        value = scoring._num(balance.get(label))
        if value is not None:
            return abs(value), label
    return None, None


def _one_year_owner_earnings(bundle: dict) -> tuple[float | None, str]:
    """One year of owner earnings for the refinancing denominator: the TTM figure the rest
    of the system prices off, else the newest annual period."""
    ttm = scoring.assemble_ttm(bundle).get("owner_fcf")
    if ttm is not None:
        return ttm, "TTM owner-FCF"
    points = annual_owner_fcf(bundle)
    if points:
        return points[-1][1], f"{points[-1][0]} annual owner-FCF"
    return None, "no owner-FCF"


def probe_financing(bundle: dict, prices=None, symbol: str | None = None,
                    share_class: bool = False) -> dict:
    """§3.6 — two ways the financing side takes the owner's money.

    The refinancing wall: debt due within twelve months against cash plus one year of owner
    earnings. Only owner earnings above zero help pay a maturity, so a negative year adds
    nothing rather than subtracting twice.

    Dilution during a drawdown: a rising split-adjusted share count between the peak and the
    trough of the deepest price drawdown means the owner was diluted at the bottom, which is
    how permanent loss actually happens. Measured only when that drawdown is at least
    `min_drawdown` deep, and suppressed entirely on a §4.5 SHARE_CLASS name, where scoring
    has already declared the share-count series untrustworthy.

    The dilution leg also requires a SPLIT HISTORY to exist on the Bundle. Raw share counts
    are point-in-time and split-unadjusted, and scoring.adjusted_shares_series documents
    that it passes them through unchanged when `splits` is absent — so on a Bundle with no
    split events a 20:1 split reads as +1,923% dilution at the very bottom of a drawdown,
    the loudest false finding this layer can make. An empty split map cannot be told apart
    from a name that never split (pit.market_cap_at says the same thing about the market
    cap and raises the same flag), so both are treated as an unadjustable series: the leg
    is unmeasured and NAMED, which §7 says is the honest state, rather than scored either
    way. A change beyond `max_share_change` is refused for the same reason.

    A leg that could not be evaluated is never written as 0.0. A vacuous "nothing to
    measure" reading would make the probe report itself measured, count toward
    MIN_MEASURED_COUNTING and print "the financing side holds" on a name whose financing
    side was never looked at — silence read as safety, which is what this layer exists to
    prevent."""
    thresholds = PROBES["financing"]["thresholds"]
    evidence, legs, unmeasured = {}, {}, []

    # --- leg 1: the refinancing wall
    due, due_label = _debt_due_12m(bundle)
    cash = scoring._row(scoring._latest_balance(bundle), "cash")
    earnings, earnings_source = _one_year_owner_earnings(bundle)
    substituted = due_label in _DEBT_DUE_12M_SUBSTITUTES
    if due is None:
        unmeasured.append("no twelve-month debt maturity on the latest balance sheet "
                          "(no ingester in this repo maps the EDGAR tag; see the §3.6 "
                          "provenance)")
    elif cash is None:
        unmeasured.append("no cash balance to weigh the maturity against")
    else:
        cushion = cash + max(earnings or 0.0, 0.0)
        # No cushion at all against a live maturity is past any ratio, not a huge one: the
        # leg is uncovered, the severity is severe, and the number stays None (_finite).
        ratio = math.inf if cushion <= 0 < due else (due / cushion if cushion > 0 else 0.0)
        legs["wall"] = ratio
        evidence.update({"debt_due_12m": due, "debt_due_12m_label": due_label,
                         "debt_due_12m_substituted": substituted, "cash": cash,
                         "owner_earnings_1y": earnings,
                         "owner_earnings_source": earnings_source,
                         "wall_ratio": _finite(ratio),
                         "wall_uncovered": math.isinf(ratio)})
        if earnings is None:
            evidence["wall_note"] = ("one year of owner earnings not computable — the wall "
                                     "is measured against cash alone, the conservative "
                                     "direction")

    # --- leg 2: dilution at the bottom
    series = price_series(prices, symbol)
    shares = scoring.adjusted_shares_series(bundle)
    splits = bundle.get("splits") or {}
    if share_class:
        unmeasured.append("SHARE_CLASS — §4.5 already declares this name's share-count "
                          "series untrustworthy")
    elif len(series) < 2 or not shares:
        unmeasured.append("no price history and share-count series to compare across a "
                          "drawdown")
    else:
        fall = max_drawdown(cumulative(weekly_returns(series)))
        depth = fall["drawdown"]
        if depth is None:
            unmeasured.append("the cumulative total-return series never holds a positive "
                              "peak, so there is no drawdown to measure dilution across")
        elif depth > thresholds["min_drawdown"]:
            unmeasured.append(
                f"deepest drawdown {_pct(depth)} is shallower than the "
                f"{_pct(thresholds['min_drawdown'], 0)} this leg needs — no bottom to have "
                f"been diluted at")
        elif not splits:
            unmeasured.append("no split history on this Bundle, so the raw share counts "
                              "cannot be restated — a split and an issuance read "
                              "identically and neither may be called dilution")
        else:
            peak_day = series[fall["peak_index"]][0]
            trough_day = series[fall["trough_index"]][0]
            at_peak = scoring._shares_at(shares, peak_day)
            at_trough = scoring._shares_at(shares, trough_day)
            if not at_peak or at_trough is None:
                unmeasured.append(f"no split-adjusted share count at the {peak_day} peak "
                                  f"and the {trough_day} trough")
            else:
                change = at_trough / at_peak - 1.0
                if abs(change) > thresholds["max_share_change"]:
                    evidence["share_change_refused"] = change
                    unmeasured.append(
                        f"the share count moved {_pct(change)} between the {peak_day} peak "
                        f"and the {trough_day} trough — beyond the "
                        f"{_pct(thresholds['max_share_change'], 0)} this layer can "
                        f"attribute to an issuance, so it is not read as dilution")
                else:
                    legs["dilution"] = change
                    evidence.update({"drawdown": depth, "peak_day": peak_day,
                                     "trough_day": trough_day, "shares_at_peak": at_peak,
                                     "shares_at_trough": at_trough,
                                     "share_change": change})

    if not legs:
        return _unmeasured("financing", "; ".join(unmeasured), evidence)

    wall_severity, dilution_severity = "none", "none"
    if "wall" in legs:
        if legs["wall"] >= thresholds["wall_severe"]:
            wall_severity = "severe"
        elif legs["wall"] >= thresholds["wall_caution"]:
            wall_severity = "caution"
    if "dilution" in legs:
        if legs["dilution"] >= thresholds["dilution_severe"]:
            dilution_severity = "severe"
        elif legs["dilution"] >= thresholds["dilution_caution"]:
            dilution_severity = "caution"
    severity = _worst(wall_severity, dilution_severity)
    if _RANK[wall_severity] >= _RANK[dilution_severity] and "wall" in legs:
        driver, value = "refinancing wall", _finite(legs["wall"])
    else:
        driver, value = "dilution at the bottom", legs.get("dilution")

    parts = []
    if "wall" in legs:
        ratio = legs["wall"]
        quantity = ("short-term borrowings and lease obligations" if substituted
                    else "debt due within twelve months")
        parts.append(
            f"{quantity} against no cash and no positive year of owner earnings to pay "
            f"them with" if math.isinf(ratio) else
            f"{quantity} are {ratio:.2f}x cash plus a year of owner earnings")
        if substituted:
            parts[-1] += (f" (read from '{due_label}', which is broader than the "
                          f"twelve-month maturity §3.6 names)")
    if "dilution" in legs and evidence.get("share_change") is not None:
        change = evidence["share_change"]
        direction = "rose" if change > 0 else "fell"
        parts.append(f"the share count {direction} {_pct(change)} between the "
                     f"{evidence['peak_day']} peak and the {evidence['trough_day']} "
                     f"trough of a {_pct(evidence['drawdown'])} drawdown")
    joined = "; ".join(parts) or "no financing evidence beyond the notes below"
    # A clean severity is only ever claimed for the legs that RAN. With one leg missing the
    # headline names the one that held instead of asserting the whole financing side (§7).
    held = ("the refinancing wall holds" if "wall" in legs and "dilution" not in legs else
            "the dilution leg holds" if "dilution" in legs and "wall" not in legs else
            "the financing side holds")
    if severity == "severe" and driver == "dilution at the bottom":
        detail = (f"The owner was diluted at the bottom: {joined} — that is how permanent "
                  f"loss actually happens.")
    elif severity == "severe":
        detail = (f"The refinancing wall is bigger than the resources in hand: {joined}.")
    elif severity == "caution":
        detail = f"The financing side is not comfortable: {joined}."
    else:
        detail = f"{held[0].upper()}{held[1:]}: {joined}."
    if unmeasured:
        detail = f"{detail} (Not measured: {'; '.join(unmeasured)}.)"
    evidence.update({"driver": driver, "unmeasured": unmeasured,
                     "legs_measured": sorted(legs)})
    return _result("financing", severity, value, detail, evidence)


# --- §3.7 Concentration (flag only) ------------------------------------------------------

def probe_concentration(bundle: dict) -> dict:
    """§3.7 — ConcentrationRiskPercentage1 where the filer tags it, reported as a FLAG and
    never as a severity: at ~11% coverage the tag is far too sparse to score, and scoring it
    would make its absence the loudest thing about most names.

    Where the tag is absent this probe says so out loud rather than implying the risk is
    absent. That is the Cirrus Logic lesson — ~90% of revenue from Apple, invisible to the
    model — and the reason §3.3 exists to catch the same fragility by another route.

    A flag is not a severity, but it is also not nothing: `inversion()` records it in
    `coverage["flagged"]` and `consensus_lens` refuses to certify survival while one
    stands, so a green fourth lens can never sit beside a sentence naming a risk."""
    threshold = PROBES["concentration"]["thresholds"]["flag"]
    value, as_of_end = None, None
    point = _disclosure(bundle, "concentration_risk")
    if point:
        value, as_of_end = float(point["value"]), point.get("end")
    else:                                   # a Yahoo-built Bundle carries it in a section
        annual = bundle.get("annual") or {}
        for section in ("income", "cashflow", "balance"):
            payloads = annual.get(section) or {}
            for period in sorted(payloads, reverse=True):
                for label in _CONCENTRATION_LABELS:
                    raw = scoring._num(payloads[period].get(label))
                    if raw is not None:
                        value, as_of_end = raw, period
                        break
                if value is not None:
                    break
            if value is not None:
                break

    if value is None:
        return _result("concentration", "none", None,
                       "This filer does not tag customer concentration, so this layer "
                       "cannot see it — and silence here is not safety (§3.7); the cash-"
                       "engine probe is what catches the same fragility by another route.",
                       {"disclosed": False, "flagged": False,
                        "reason": "the filer does not tag ConcentrationRiskPercentage1 "
                                  "(~11% of these filers do)"}, measured=False)
    if abs(value) <= _CONCENTRATION_RATIO_CEILING:
        value *= 100.0
    if value >= _CONCENTRATION_TOTAL_ROW:
        return _result("concentration", "none", None,
                       f"This filer tags concentration at {value:.0f}%, which this layer "
                       f"refuses: the tag carries no axis member, so a single-customer "
                       f"disclosure and the TOTAL row of a disaggregation table read "
                       f"identically, and 100% is what a total row looks like. Not read "
                       f"as concentration, and not read as safety either (§7).",
                       {"disclosed": True, "flagged": False, "refused": value,
                        "as_of_end": as_of_end,
                        "reason": "a tagged 100% is the total row of a disaggregation, not "
                                  "one customer"}, measured=False)
    flagged = value >= threshold
    # The date is not decoration. The median concentration disclosure in the 2026 SEC
    # export ENDS IN 2017 — the tag is not merely sparse, it is largely abandoned — and a
    # nine-year-old fact read as a description of the business today is its own trap.
    dated = f" as last tagged for {as_of_end}" if as_of_end else ""
    if flagged:
        detail = (f"Disclosed customer concentration is {value:.0f}% of revenue{dated} — "
                  f"one customer's decision is the owner's risk (flagged, not scored: "
                  f"§3.7). This is the last figure the filer tagged, not necessarily the "
                  f"figure today.")
    else:
        detail = (f"Disclosed customer concentration is {value:.0f}% of revenue{dated}, "
                  f"below the {threshold:.0f}% line this layer flags (reported, not "
                  f"scored: §3.7).")
    return _result("concentration", "none", value, detail,
                   {"disclosed": True, "flagged": flagged, "percent_of_revenue": value,
                    "as_of_end": as_of_end, "filed": point.get("filed") or None})


# --- The verdict (§4) --------------------------------------------------------------------

def verdict_for(severe: int, caution: int) -> str:
    """§4's table, counted and never averaged: >= 3 severe -> Ruinous; 2 severe or >= 4
    cautions -> Fragile; anything else with a finding -> Ordinary; nothing -> Robust. A
    good probe cannot cancel a fatal one because nothing here can subtract.

    The rungs are calibrated against the measured firing rates of the six counting probes
    rather than assumed — see the comment above VERDICTS for what the design's original
    ">= 2 severe" did to a real universe."""
    if severe >= VERDICT_LADDER["ruinous_severe"]:
        return "Ruinous"
    if severe >= VERDICT_LADDER["fragile_severe"] or caution >= VERDICT_LADDER[
            "fragile_caution"]:
        return "Fragile"
    if severe or caution:
        return "Ordinary"
    return "Robust"


def inversion(bundle: dict, *, prices=None, scored_row: dict | None = None) -> dict:
    """The whole §3-§4 inversion for one name -> {verdict, failure_modes, probes, coverage,
    notes}.

    `prices` is the name's §3.6 weekly grid ({day: bar}), or the {symbol: grid} map, from
    which only adj_close is ever read. `scored_row` is the §3.3 row score_universe()
    produced for this same Bundle; its flags are reused so the two layers agree about a
    SHARE_CLASS name rather than deciding separately (without one, scoring.evaluate is asked
    the same question).

    `failure_modes` is the headline output (§2): the severe sentences first, then the
    cautions, then any §3.7 flag — flags last and never counted, so the list can be read top
    to bottom as "how would this lose my money?".

    Nothing here reads or writes a scorecard. The two live in different columns on purpose
    (§2): a name can be Exceptional and Fragile at once, and that pairing is the most useful
    thing this layer produces."""
    symbol = bundle.get("symbol")
    if scored_row is not None:
        got = scored_row.get("symbol")
        if symbol and got and symbol != got:
            raise ValueError(f"scored_row is for {got}, bundle is for {symbol}")
        flags = scored_row.get("flags") or []
    else:
        flags = scoring.evaluate(bundle)["flags"]
    share_class = any(flag.get("code") == "SHARE_CLASS" for flag in flags)

    probes = {
        "price_drawdown": probe_price_drawdown(prices, symbol),
        "return_asymmetry": probe_return_asymmetry(prices, symbol),
        "cash_engine": probe_cash_engine(bundle),
        "stress": probe_stress(bundle),
        "predictability": probe_predictability(bundle),
        "financing": probe_financing(bundle, prices=prices, symbol=symbol,
                                     share_class=share_class),
        "concentration": probe_concentration(bundle),
    }

    counting = [probes[pid] for pid in COUNTING_PROBES]
    severe = [p for p in counting if p["severity"] == "severe"]
    caution = [p for p in counting if p["severity"] == "caution"]
    measured = [pid for pid in COUNTING_PROBES if probes[pid]["measured"]]
    required_missing = [pid for pid in REQUIRED_PROBES if not probes[pid]["measured"]]
    thin = bool(required_missing) or len(measured) < MIN_MEASURED_COUNTING

    counted = verdict_for(len(severe), len(caution))
    # Thin evidence can refuse to certify safety; it can never manufacture it, and it must
    # never DELETE a finding either. The test is the evidence, not the label: any severe
    # probe stands whatever rung it lands on, and only a verdict resting on no named
    # failure mode collapses to Unknown (§4, §7). Keying this on VERDICTS[...]["safe"]
    # alone was safe while 1 severe meant Fragile; under the calibrated ladder Ordinary can
    # hold one severe finding, and collapsing that to Unknown would erase the sentence the
    # layer exists to write.
    verdict = "Unknown" if thin and not severe and VERDICTS[counted]["safe"] else counted

    flagged = [pid for pid in PROBES
               if not PROBES[pid]["counts"] and probes[pid]["evidence"].get("flagged")]
    failure_modes = ([p["detail"] for p in severe] + [p["detail"] for p in caution]
                     + [f"Flag — {probes[pid]['detail']}" for pid in flagged])

    unmeasured = [{"id": pid, "label": PROBES[pid]["label"], "section": PROBES[pid]["section"],
                   "counts": PROBES[pid]["counts"],
                   "reason": probes[pid]["evidence"].get("reason", "not tagged by this filer")}
                  for pid in PROBES if not probes[pid]["measured"]]
    coverage = {"measured": measured, "counting": list(COUNTING_PROBES),
                "measured_counting": len(measured), "counting_total": len(COUNTING_PROBES),
                "unmeasured": unmeasured, "required_missing": required_missing,
                "thin": thin, "severe": len(severe), "caution": len(caution),
                "flagged": flagged}

    notes = ["This layer adds no points to the scorecard: the card says how good the "
             "business is, this says how it breaks, and they stay in different columns (§2)."]
    for pid in flagged:
        notes.append(f"A §{PROBES[pid]['section']} flag stands ({PROBES[pid]['label']}), "
                     f"so the §5 survival lens says nothing rather than green: the flag is "
                     f"too sparse to score into the verdict (§3.7), and evidence too thin "
                     f"to grade is far too thin to certify safety on.")
    for entry in unmeasured:
        notes.append(f"Not measured — {entry['label']} (§{entry['section']}): "
                     f"{entry['reason']}. Absent evidence is not safety (§7).")
    if verdict == "Unknown":
        reason = ("the probes this verdict cannot be certified without are unmeasured "
                  f"({', '.join(required_missing)})" if required_missing
                  else f"only {len(measured)} of {len(COUNTING_PROBES)} probes could be "
                       f"measured")
        notes.append(f"Verdict is Unknown rather than {counted} because {reason} — thin "
                     f"evidence is said out loud, never read as safe (§4).")
    notes.append("This layer reads what already happened to the cash and the price. It "
                 "cannot see lawsuits, regulation, a competitor's roadmap, a fraud not yet "
                 "in the numbers, or an untagged customer concentration (§7).")

    return {"verdict": verdict, "verdict_meaning": VERDICTS[verdict]["meaning"],
            "verdict_rule": VERDICTS[verdict]["rule"], "counted_verdict": counted,
            "failure_modes": failure_modes, "probes": probes, "coverage": coverage,
            "notes": notes}


def _standing_flags(card_inversion) -> list:
    """The §3.7-style flags a result carries: `coverage["flagged"]` when the layer recorded
    it, else read off the non-counting probes. A bare verdict string carries neither."""
    if not isinstance(card_inversion, dict):
        return []
    flagged = (card_inversion.get("coverage") or {}).get("flagged")
    if flagged is not None:
        return list(flagged)
    probes = card_inversion.get("probes") or {}
    return [pid for pid, spec in PROBES.items() if not spec["counts"]
            and ((probes.get(pid) or {}).get("evidence") or {}).get("flagged")]


def _severe_count(card_inversion) -> int:
    """How many counting probes fired severe: `coverage["severe"]` when the layer recorded
    it, else read off the probes. A bare verdict string carries neither, and returns 0 —
    the caller then has only the rung to go on, which is all a string ever offered."""
    if not isinstance(card_inversion, dict):
        return 0
    recorded = (card_inversion.get("coverage") or {}).get("severe")
    if recorded is not None:
        return int(recorded)
    probes = card_inversion.get("probes") or {}
    return sum(1 for pid in COUNTING_PROBES
               if (probes.get(pid) or {}).get("severity") == "severe")


def consensus_lens(card_inversion) -> bool | None:
    """§5's fourth lens: three lenses currently answer "is this good?" in three ways; this
    one answers "will it survive?", the question the other three share a blind spot on.

    True on Robust/Ordinary, False on Fragile/Ruinous, None on Unknown — and None on no
    inversion at all, so an absent layer never counts as a green lens and never shrinks the
    denominator (scorecard.consensus's own rule for a lens with no data).

    A STANDING FLAG also returns None. §3.7 forbids scoring the concentration tag, so the
    verdict stays whatever §4's counting made it — but "too sparse to score" cannot become
    "certified survivor": a disclosed 90%-of-revenue single customer is the exact case §1
    names (Cirrus Logic), and pairing a green survival tick with the sentence that names
    that risk is the failure this layer was built to stop. The lens refuses to say instead,
    which shrinks the consensus denominator rather than filling it with a comfort. A
    verdict that already names a failure mode is unaffected: False stays False.

    A STANDING SEVERE PROBE does the same, for the same reason. Under the calibrated ladder
    Ordinary can hold one severe finding — one demonstrated way this loses the owner's
    money — and "normal business risk" is a fair label for that while a green survival tick
    beside it is not. The lens reads the evidence, not the rung."""
    if card_inversion is None:
        return None
    verdict = (card_inversion if isinstance(card_inversion, str)
               else card_inversion.get("verdict"))
    safe = VERDICTS.get(verdict, {}).get("safe")
    if safe and (_standing_flags(card_inversion) or _severe_count(card_inversion)):
        return None
    return safe
