"""The Low-Cap Desk's pure decision layer (docs/plans/2026-08-14-low-cap-desk-design.md,
owner-ratified 2026-08-14).

Small caps are a different game, not a smaller version of the main desk's game: there is
no size premium (Alquist/Israel/Moskowitz 2018), only a hunting ground where mispricing
signals are largest because nobody is looking — and where junk is the default state
(Asness et al. 2018) and dilution the dominant capital destroyer (Pontiff/Woodgate 2008).
So the lane's constitution is **Survive → Lenses → Scuttlebutt**:

- **The Forge (Pillar 1).** Deterministic survival probes — dilution, cash runway,
  distress, delisting jeopardy, overhang, accrual mirage — severities counted, never
  averaged (inversion.py's exact pattern). Any severe finding forges the name out before
  any lens looks at it: the lane's Hell-No filter, run first (invariant 12's ordering).
- **Four lenses (Pillar 2), side by side, never merged.** Personas differ in judgment,
  not arithmetic (ai-hedge-fund's hardest-won lesson — every metric is computed once
  here, each lens is a checklist over the shared numbers with its own named thresholds).
  A lens SPEAKS, stays SILENT, or REFUSES (inputs unmeasured — refuse, never guess).
  No composite low-cap score exists anywhere: the interface shows four shortlists side
  by side, and a name on two lists is visibly on two lists (invariant 2 generalized).
- **Scuttlebutt (Pillar 3)** lives in the agent seam (lowcap briefs), not here.

Absolute anchors, not sector percentiles: 4,099 SEC-merge universe rows carry no sector
metadata, so percentile cohorts are garbage exactly where this lane lives.

Pure module: no I/O, no network, no clock. Same Bundle (+ weekly price grid) in ⇒ same
answers out. "As of" is always derived from the data itself (the newest price bar or
share observation), never from the wall clock.
"""
from __future__ import annotations

import math
import statistics

import picks
import pit
import scoring

# --- The lane's eligibility band (design §3) ---------------------------------------------
# $50M–$2B on listed exchanges: below $50M is the promotion/shell tier (MicroCapClub's
# excluded ~82%), above $2B the main desk already covers it. $300M–$2B names appear on
# BOTH surfaces on purpose — different questions, different answers. Price ≥ $1 is the
# exchange survival line (the main desk's $5 is a large-cap respectability floor); the
# Forge's delisting probe handles the approach to it. Unlike the main desk's floor, the
# band is a POSITIVE claim: membership of the low-cap lane requires the qualifying
# figure — a missing market cap cannot certify a name small (refuse, never guess).
LOWCAP_MIN_MARKET_CAP = 50e6
LOWCAP_MAX_MARKET_CAP = 2e9
LOWCAP_MIN_PRICE = 1.0

SHORTLIST_PER_LENS = 3      # work-order budget: top 3 per lens per cycle, overlap collapses

# --- Forge thresholds (design §2 Pillar 1; every number journaled in the research bundle) -
NSI_SEVERE_PCT = 10.0       # practitioner "critical" serial-diluter line (>10%/yr)
NSI_CAUTION_PCT = 5.0       # literature action point (Pontiff/Woodgate ~ -0.3-0.5%/yr per 1%)
NSI_REPEAT_YEARS = 2        # >5%/yr in >= 2 of the last 3 yearly windows = serial, severe
RUNWAY_SEVERE_MONTHS = 12.0  # the ASC 205-40 going-concern horizon
DISTRESS_TLMTA = 0.5        # CHS-style leverage-at-market threshold
DISTRESS_VOL_ANNUAL = 0.60  # annualized weekly vol; the "high vol" leg (declared here —
                            # CHS uses 3-month daily sigma; weekly is what the grid carries)
DELISTING_PRICE = 1.0       # the exchange $1 rule
DELISTING_WEEKS = 6         # ~30 trading days of sub-$1 closes, on a weekly grid
EQUITY_FLOOR = 2.5e6        # Nasdaq 5550(b)(1) continued-listing equity standard
REVERSE_SPLIT_MONTHS = 24   # a reverse split this recent marks the delisting treadmill
ACCRUAL_ASSETS_CAUTION = 10.0  # (NI - OCF)/assets > +10% ~ Sloan's top quintile
OVERHANG_CAUTION_PCT = 10.0    # diluted vs basic weighted shares gap

FORGE_MIN_MEASURED = 3      # of the 6 probes; below this the evidence is thin
REQUIRED_FORGE_PROBES = ("serial_diluter", "cash_runway")  # survival cannot be certified
                                                           # without the two capital drains

FORGE_VERDICTS = {
    "Forged-out": {
        "rule": "any severe probe",
        "meaning": "A named way this takes your capital to stay alive — no work order",
        "survives": False},
    "Watch": {
        "rule": "2 or more cautions",
        "meaning": "Survives today; the margin is thin and named",
        "survives": True},
    "Survivor": {
        "rule": "no severe probe and fewer than 2 cautions",
        "meaning": "The business does not need the capital market to live",
        "survives": True},
    "Unknown": {
        "rule": "too little evidence to certify survival — a named finding still stands, "
                "only Survivor/Watch collapse to here",
        "meaning": "Said out loud, never read as safe",
        "survives": None},
}

# --- The Forge probe registry, as data (inversion.py's pattern) ---------------------------
FORGE_PROBES = {
    "serial_diluter": {
        "label": "serial diluter",
        "question": "Does this company pay for its life with your ownership?",
        "reads": "split-adjusted shares_series, yearly net share issuance",
        "thresholds": {"severe": NSI_SEVERE_PCT, "caution": NSI_CAUTION_PCT,
                       "repeat_years": NSI_REPEAT_YEARS},
        "provenance": "Design Pillar 1. Net share issuance is the most robust negative "
                      "predictor in the cross-section (Pontiff/Woodgate 2008) and one of "
                      "only two anomalies pervasive even in microcaps (Fama/French 2008); "
                      "practitioner alert levels 5%/yr moderate, 10%/yr critical. The main "
                      "desk's 20%/yr veto is calibrated for large caps; down here 20%/yr "
                      "is the death spiral already turning. SHARE_CLASS names are refused "
                      "rather than measured — an Up-C count mismatch reads as dilution.",
    },
    "cash_runway": {
        "label": "cash runway",
        "question": "Can it fund itself for the going-concern horizon without raising?",
        "reads": "latest balance cash (+ ST investments chain) vs TTM operating burn",
        "thresholds": {"severe_months": RUNWAY_SEVERE_MONTHS},
        "provenance": "Design Pillar 1; mirrors the ASC 205-40 twelve-month substantial-"
                      "doubt horizon. OCF >= 0 means the runway is infinite — a "
                      "self-funding company cannot be killed by a closed capital market "
                      "(Cassel). Committed capex and maturities are not subtracted; the "
                      "probe understates the risk and says so.",
    },
    "distress": {
        "label": "distress",
        "question": "Is this the cheap-because-dying cohort?",
        "reads": "TTM net income, total liabilities at market (TLMTA), weekly volatility",
        "thresholds": {"tlmta": DISTRESS_TLMTA, "vol_annual": DISTRESS_VOL_ANNUAL},
        "provenance": "Campbell/Hilscher/Szilagyi 2008: the highest-failure-probability "
                      "decile earned -17%/yr alpha — distress is penalized, not rewarded, "
                      "and 'cheap because dying' is the most consistent way to lose money "
                      "in this universe. Severe needs all three legs measured AND true "
                      "(loss-making, TLMTA > 0.5, high vol); two of three reads caution; "
                      "fewer than three measurable legs refuses.",
    },
    "delisting": {
        "label": "delisting jeopardy",
        "question": "Is the listing itself at risk?",
        "reads": "raw weekly closes, stockholders' equity, split history",
        "thresholds": {"price": DELISTING_PRICE, "weeks": DELISTING_WEEKS,
                       "equity_floor": EQUITY_FLOOR,
                       "reverse_split_months": REVERSE_SPLIT_MONTHS},
        "provenance": "The exchange $1 rule (30 consecutive trading days, proxied as "
                      f"{DELISTING_WEEKS} weekly closes), Nasdaq 5550(b)(1) equity >= "
                      "$2.5M, and the reverse-split-then-offering treadmill (Nasdaq "
                      "tightened rules around it in 2025). These are listing-survival "
                      "facts, not price triggers on a thesis (invariant 7 stands).",
    },
    "overhang": {
        "label": "convertible/warrant overhang",
        "question": "Are shares already promised that have not printed yet?",
        "reads": "diluted vs basic weighted-average share rows, where the filer tags them",
        "thresholds": {"caution": OVERHANG_CAUTION_PCT},
        "provenance": "Design Pillar 1: a diluted count running ahead of basic is the "
                      "early warning BEFORE the shares print (the toxic-convertible "
                      "signature). Caution only — the instrument may be benign — and "
                      "unmeasured for the many small filers who tag neither row.",
    },
    "accrual_mirage": {
        "label": "accrual mirage",
        "question": "Are the earnings cash, or bookkeeping?",
        "reads": "TTM (net income - OCF) over total assets",
        "thresholds": {"caution": ACCRUAL_ASSETS_CAUTION},
        "provenance": "Sloan 1996; the anomaly decayed in large caps but persists where "
                      "arbitrage is costly — exactly here (Mashruwala et al. 2006). "
                      "Accruals above ~+10% of assets is the top-quintile territory the "
                      "literature vetoes. Caution, not severe: a mirage flag, not a "
                      "demonstrated drain.",
    },
}


# --- Small helpers ------------------------------------------------------------------------

def _result(probe_id: str, severity: str, value, detail: str, evidence: dict,
            measured: bool = True) -> dict:
    return {"id": probe_id, "severity": severity, "measured": measured, "value": value,
            "detail": detail, "evidence": evidence}


def _unmeasured(probe_id: str, reason: str, evidence: dict | None = None) -> dict:
    """A probe with no evidence: severity "none" (it must not invent a finding) but
    measured=False, so coverage names it and the verdict cannot read it as survival."""
    spec = FORGE_PROBES[probe_id]
    return _result(probe_id, "none", None,
                   f"Not measured — {spec['label']}: {reason}. Absent evidence is not "
                   f"survival.", {**(evidence or {}), "reason": reason}, measured=False)


def _close_series(prices, symbol: str | None = None) -> list[tuple[str, float]]:
    """Ascending (day, RAW close) from a weekly grid — the delisting probe is about the
    exchange's number, and the adjusted close would restate old bars through later
    splits/dividends. Bars without a raw close of their own (legacy float grids) fall
    back through pit.bar_value; non-positive bars are dropped."""
    if not prices:
        return []
    grid = prices
    if not all(_is_day(k) for k in grid):
        grid = (prices.get(symbol) or {}) if symbol is not None else {}
    out = []
    for day in sorted(grid):
        value = pit.bar_value(grid[day], "close")
        if value is not None and value > 0:
            out.append((str(day), float(value)))
    return out


def _is_day(key) -> bool:
    text = str(key)
    return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _adj_series(prices, symbol: str | None = None) -> list[tuple[str, float]]:
    """Ascending (day, adj_close) — volatility is total-return arithmetic."""
    if not prices:
        return []
    grid = prices
    if not all(_is_day(k) for k in grid):
        grid = (prices.get(symbol) or {}) if symbol is not None else {}
    out = []
    for day in sorted(grid):
        value = pit.bar_value(grid[day], "adj_close")
        if value is not None and value > 0:
            out.append((str(day), float(value)))
    return out


def _annualized_vol(prices, symbol: str | None = None) -> float | None:
    """Annualized weekly volatility from the adj_close series; None under a year of bars
    (a volatility claim needs a cycle's worth of observations)."""
    series = _adj_series(prices, symbol)
    if len(series) < 52:
        return None
    returns = [series[i][1] / series[i - 1][1] - 1.0 for i in range(1, len(series))]
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns) * math.sqrt(52.0)


def _total_liabilities(bundle: dict) -> float | None:
    """Total liabilities by the accounting identity assets − (equity + NCI) — the rows
    every balance carries — because the lane lives exactly where supplement tags thin
    out. NCI absent reads 0 (a filer with none untagged); assets or equity absent
    refuses."""
    bal = scoring._latest_balance(bundle)
    assets = scoring._row(bal, "total_assets")
    equity = scoring._row(bal, "equity")
    if assets is None or equity is None:
        return None
    return assets - equity - (scoring._row(bal, "nci") or 0.0)


def _yearly_nsi(shares_adj: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Yearly net-share-issuance observations (%/yr) off the split-adjusted series:
    newest-first year-over-year steps on an annual cadence (>= 300-day gaps), each
    annualized by its actual span."""
    cadence: list[tuple[str, float]] = []
    for day, value in shares_adj:
        if not cadence or (scoring._years(cadence[-1][0], day) * 365.25) >= 300:
            cadence.append((day, value))
        else:
            cadence[-1] = (day, value)      # newest observation within the year wins
    out = []
    for i in range(1, len(cadence)):
        (d0, v0), (d1, v1) = cadence[i - 1], cadence[i]
        if v0 > 0 and v1 > 0:
            out.append((d1, scoring._cagr_pct(d0, v0, d1, v1)))
    return out


def _as_of(bundle: dict, prices, symbol: str | None) -> str | None:
    """The data's own "today": the newest raw close date, else the newest share
    observation. Pure layer — the wall clock is never consulted."""
    closes = _close_series(prices, symbol)
    if closes:
        return closes[-1][0]
    shares = scoring.adjusted_shares_series(bundle)
    return shares[-1][0] if shares else None


# --- The Forge probes (Pillar 1) ----------------------------------------------------------

def probe_serial_diluter(bundle: dict, evaluated: dict) -> dict:
    pid = "serial_diluter"
    if bundle.get("shares_series_stale"):
        return _unmeasured(pid, "share series is stale — ancient dilution is not current")
    if evaluated.get("share_class"):
        return _unmeasured(pid, "SHARE_CLASS structure — the listed-class count mismatch "
                                "would read as dilution")
    trend = evaluated.get("share_trend")
    shares_adj = scoring.adjusted_shares_series(bundle)
    yearly = _yearly_nsi(shares_adj)
    if trend is None and not yearly:
        return _unmeasured(pid, "fewer than two usable share observations")
    recent = yearly[-3:]
    repeat = sum(1 for _, pct in recent if pct > NSI_CAUTION_PCT)
    evidence = {"nsi_trailing_pct": trend, "nsi_yearly": recent,
                "repeat_years_over_caution": repeat}
    if (trend is not None and trend > NSI_SEVERE_PCT) or repeat >= NSI_REPEAT_YEARS:
        why = (f"issued {trend:+.1f}%/yr" if trend is not None and trend > NSI_SEVERE_PCT
               else f"issued >{NSI_CAUTION_PCT:.0f}%/yr in {repeat} of the last "
                    f"{len(recent)} years")
        return _result(pid, "severe", trend,
                       f"Serial diluter — {why}; this company pays for its life with "
                       f"your ownership.", evidence)
    if trend is not None and trend > NSI_CAUTION_PCT:
        return _result(pid, "caution", trend,
                       f"Diluting at {trend:+.1f}%/yr — above the {NSI_CAUTION_PCT:.0f}%/yr "
                       f"literature action point.", evidence)
    return _result(pid, "none", trend,
                   "Share count flat or shrinking — the owner's slice is not the funding "
                   "source.", evidence)


def probe_cash_runway(bundle: dict, evaluated: dict) -> dict:
    pid = "cash_runway"
    ocf = (evaluated.get("ttm") or {}).get("ocf")
    if ocf is None:
        return _unmeasured(pid, "TTM operating cash flow not measurable")
    if ocf >= 0:
        return _result(pid, "none", None,
                       "Self-funding — operating cash flow is non-negative, the runway "
                       "is not finite.", {"ttm_ocf": ocf, "runway_months": None})
    cash = scoring._row(scoring._latest_balance(bundle), "cash")
    if cash is None:
        return _unmeasured(pid, "cash position not measurable against a negative OCF",
                           {"ttm_ocf": ocf})
    runway = cash / (-ocf / 12.0)
    evidence = {"ttm_ocf": ocf, "cash": cash, "runway_months": runway}
    if runway < RUNWAY_SEVERE_MONTHS:
        return _result(pid, "severe", runway,
                       f"Cash runway ~{runway:.0f} months at the TTM burn — inside the "
                       f"going-concern horizon; the next financing is not optional.",
                       evidence)
    return _result(pid, "none", runway,
                   f"Burning cash with ~{runway:.0f} months of runway — outside the "
                   f"going-concern horizon, watched not flagged.", evidence)


def probe_distress(bundle: dict, evaluated: dict, prices=None,
                   symbol: str | None = None) -> dict:
    pid = "distress"
    ni = (evaluated.get("ttm") or {}).get("ni_incl_nci")
    liabilities = _total_liabilities(bundle)
    mcap = scoring._num(bundle.get("market_cap"))
    tlmta = (liabilities / (liabilities + mcap)
             if None not in (liabilities, mcap) and liabilities + mcap > 0 else None)
    vol = _annualized_vol(prices, symbol)
    legs = {"loss_making": ni < 0 if ni is not None else None,
            "leveraged_at_market": tlmta > DISTRESS_TLMTA if tlmta is not None else None,
            "high_volatility": vol > DISTRESS_VOL_ANNUAL if vol is not None else None}
    measured = [v for v in legs.values() if v is not None]
    evidence = {"legs": legs, "ttm_ni": ni, "tlmta": tlmta, "vol_annual": vol}
    if len(measured) < 3:
        missing = [k for k, v in legs.items() if v is None]
        return _unmeasured(pid, f"only {len(measured)} of 3 legs measurable "
                                f"(missing: {', '.join(missing)})", evidence)
    fired = sum(measured)
    if fired == 3:
        return _result(pid, "severe", tlmta,
                       "Cheap-because-dying profile — loss-making, leveraged at market "
                       f"(TLMTA {tlmta:.2f}) and high-volatility at once: the cohort the "
                       "literature says is penalized, not rewarded.", evidence)
    if fired == 2:
        return _result(pid, "caution", tlmta,
                       "Two of three distress legs fire — not yet the dying cohort, but "
                       "the direction is named.", evidence)
    return _result(pid, "none", tlmta,
                   "No distress profile — at most one leg fires.", evidence)


def probe_delisting(bundle: dict, prices=None, symbol: str | None = None) -> dict:
    pid = "delisting"
    closes = _close_series(prices, symbol)
    equity = scoring._row(scoring._latest_balance(bundle), "equity")
    as_of = _as_of(bundle, prices, symbol)

    legs: dict[str, bool | None] = {}
    tail = [c for _, c in closes[-DELISTING_WEEKS:]]
    legs["sub_dollar"] = (all(c < DELISTING_PRICE for c in tail)
                          if len(tail) >= DELISTING_WEEKS else None)
    legs["equity_floor"] = equity < EQUITY_FLOOR if equity is not None else None
    reverse = None
    if as_of is not None:
        window_days = REVERSE_SPLIT_MONTHS * 30.44
        reverse = any(
            ratio is not None and 0 < ratio < 1.0
            and 0 <= (scoring._years(str(day), as_of) * 365.25) <= window_days
            for day, raw in (bundle.get("splits") or {}).items()
            if (ratio := scoring._num(raw)) is not None and str(day) <= as_of)
    legs["recent_reverse_split"] = reverse

    evidence = {"legs": legs, "last_closes": tail, "equity": equity, "as_of": as_of}
    if all(v is None for v in legs.values()):
        return _unmeasured(pid, "no price history, equity or split record to read",
                           evidence)
    fired = [name for name, v in legs.items() if v]
    if fired:
        return _result(pid, "severe", fired,
                       f"Listing in jeopardy — {', '.join(fired).replace('_', ' ')}: the "
                       f"delisting treadmill is where small-cap capital goes to die.",
                       evidence)
    return _result(pid, "none", [],
                   "No delisting jeopardy in the measured legs.", evidence)


def probe_overhang(bundle: dict) -> dict:
    """Diluted vs basic weighted-average shares, from the income rows where the filer
    tags them (many small filers tag neither — unmeasured, said out loud)."""
    pid = "overhang"
    for scope in ("quarterly", "annual"):
        income = (bundle.get(scope) or {}).get("income") or {}
        for pe in sorted(income, reverse=True):
            basic = scoring._num(income[pe].get("Basic Average Shares"))
            diluted = scoring._num(income[pe].get("Diluted Average Shares"))
            if basic and diluted and basic > 0:
                gap = 100.0 * (diluted - basic) / basic
                evidence = {"period": pe, "basic": basic, "diluted": diluted,
                            "gap_pct": gap}
                if gap > OVERHANG_CAUTION_PCT:
                    return _result(pid, "caution", gap,
                                   f"Diluted share count runs {gap:.0f}% ahead of basic — "
                                   f"shares already promised that have not printed.",
                                   evidence)
                return _result(pid, "none", gap,
                               f"Diluted vs basic gap {gap:.1f}% — no material overhang "
                               f"in the tagged counts.", evidence)
    return _unmeasured(pid, "filer tags neither basic nor diluted weighted shares")


def probe_accrual_mirage(bundle: dict, evaluated: dict) -> dict:
    pid = "accrual_mirage"
    ttm = evaluated.get("ttm") or {}
    ni, ocf = ttm.get("ni_incl_nci"), ttm.get("ocf")
    assets = scoring._row(scoring._latest_balance(bundle), "total_assets")
    if None in (ni, ocf) or not assets or assets <= 0:
        return _unmeasured(pid, "net income, OCF or total assets not measurable")
    accrual_assets = 100.0 * (ni - ocf) / assets
    evidence = {"ttm_ni": ni, "ttm_ocf": ocf, "total_assets": assets,
                "accruals_pct_assets": accrual_assets}
    if accrual_assets > ACCRUAL_ASSETS_CAUTION:
        return _result(pid, "caution", accrual_assets,
                       f"Accruals {accrual_assets:+.0f}% of assets — earnings running "
                       f"ahead of cash in top-quintile territory (Sloan).", evidence)
    return _result(pid, "none", accrual_assets,
                   "Earnings are cash-backed at the accrual check.", evidence)


def forge(bundle: dict, *, evaluated: dict | None = None, prices=None) -> dict:
    """Pillar 1 for one name -> {verdict, findings, probes, coverage}. Severities are
    counted, never averaged; any severe stands whatever the evidence density; only a
    verdict resting on no named finding collapses to Unknown."""
    e = evaluated if evaluated is not None else scoring.evaluate(bundle)
    symbol = bundle.get("symbol")
    probes = {
        "serial_diluter": probe_serial_diluter(bundle, e),
        "cash_runway": probe_cash_runway(bundle, e),
        "distress": probe_distress(bundle, e, prices, symbol),
        "delisting": probe_delisting(bundle, prices, symbol),
        "overhang": probe_overhang(bundle),
        "accrual_mirage": probe_accrual_mirage(bundle, e),
    }
    severe = [p for p in probes.values() if p["severity"] == "severe"]
    caution = [p for p in probes.values() if p["severity"] == "caution"]
    measured = [pid for pid, p in probes.items() if p["measured"]]
    required_missing = [pid for pid in REQUIRED_FORGE_PROBES
                        if not probes[pid]["measured"]]
    thin = bool(required_missing) or len(measured) < FORGE_MIN_MEASURED

    if severe:
        verdict = "Forged-out"
    elif len(caution) >= 2:
        verdict = "Watch"                     # named findings stand, thin or not
    elif thin:
        verdict = "Unknown"
    else:
        verdict = "Survivor"

    findings = [p["detail"] for p in severe] + [p["detail"] for p in caution]
    coverage = {"measured": measured, "measured_count": len(measured),
                "total": len(FORGE_PROBES), "required_missing": required_missing,
                "thin": thin, "severe": len(severe), "caution": len(caution)}
    return {"verdict": verdict, "verdict_rule": FORGE_VERDICTS[verdict]["rule"],
            "verdict_meaning": FORGE_VERDICTS[verdict]["meaning"],
            "findings": findings, "probes": probes, "coverage": coverage}


# --- The shared metric table (Pillar 2's arithmetic, computed once) -----------------------

NORMALIZED_FCF_YEARS = 5     # Pabrai's normalization window
NORMALIZED_FCF_MIN_YEARS = 3  # an average of two points is not a normalization


def _eps_points(bundle: dict) -> list[tuple[str, float]]:
    """Ascending (period_end, split-adjusted EPS) over the annual income — net income
    over the shares outstanding at that period end (weighted-average rows are not
    reliably tagged down here; the point-in-time count is the honest proxy, and the
    same one the per-share owner-FCF leg uses)."""
    shares = scoring.adjusted_shares_series(bundle)
    income = (bundle.get("annual") or {}).get("income") or {}
    out = []
    for pe in sorted(income):
        ni = scoring._row(income[pe], "net_income")
        sh = scoring._shares_at(shares, pe)
        if ni is not None and sh:
            out.append((pe, ni / sh))
    return out


def _eps_cagr(bundle: dict) -> float | None:
    """Annual EPS CAGR %/yr, oldest usable -> newest, demanding >= 3 POSITIVE points so a
    depressed base cannot manufacture growth (Slater: growth must not come from a low
    base)."""
    pts = [(pe, v) for pe, v in _eps_points(bundle) if v > 0]
    if len(pts) < 3:
        return None
    (d0, v0), (d1, v1) = pts[0], pts[-1]
    return scoring._cagr_pct(d0, v0, d1, v1)


def _op_margin_stats(bundle: dict) -> tuple[float | None, bool | None]:
    """(5y operating-margin mean-abs-deviation in points, improving?) — the compounder
    lens's stability test, computed here so no lens re-derives arithmetic."""
    income = (bundle.get("annual") or {}).get("income") or {}
    series = []
    for pe in sorted(income):
        ebit = scoring._row(income[pe], "ebit")
        revenue = scoring._row(income[pe], "revenue")
        if ebit is not None and revenue is not None and revenue > 0:
            series.append(100.0 * ebit / revenue)
    series = series[-5:]
    if len(series) < 3:
        return None, None
    mean = sum(series) / len(series)
    mad = sum(abs(v - mean) for v in series) / len(series)
    return mad, series[-1] >= mean


def metrics(bundle: dict, evaluated: dict | None = None) -> dict:
    """Every number the lenses judge, computed once (None when unmeasured — the lens
    refuses rather than the metric guessing)."""
    e = evaluated if evaluated is not None else scoring.evaluate(bundle)
    ttm = e.get("ttm") or {}
    bal = scoring._latest_balance(bundle)
    mcap = scoring._num(bundle.get("market_cap"))
    price = scoring._num(bundle.get("price"))
    ni, ocf = ttm.get("ni_incl_nci"), ttm.get("ocf")
    ebit = ttm.get("ebit")
    own_ev = e.get("own_ev")

    shares = scoring.adjusted_shares_series(bundle)
    latest_shares = shares[-1][1] if shares else None
    debt, cash = scoring._row(bal, "total_debt"), scoring._row(bal, "cash")
    equity = scoring._row(bal, "equity")
    assets = scoring._row(bal, "total_assets")
    current_assets = scoring._row(bal, "current_assets")
    current_liabilities = scoring._row(bal, "current_liabilities")
    liabilities = _total_liabilities(bundle)

    net_cash = cash - debt if None not in (cash, debt) else None
    ncav = (current_assets - liabilities
            if None not in (current_assets, liabilities) else None)
    eps_ttm = ni / latest_shares if ni is not None and latest_shares else None
    bvps = equity / latest_shares if equity is not None and latest_shares else None
    graham_number = (math.sqrt(22.5 * eps_ttm * bvps)
                     if eps_ttm is not None and bvps is not None
                     and eps_ttm > 0 and bvps > 0 else None)
    pe_ratio = mcap / ni if mcap is not None and ni is not None and ni > 0 else None
    eps_cagr = _eps_cagr(bundle)
    peg = (pe_ratio / eps_cagr
           if pe_ratio is not None and eps_cagr is not None and eps_cagr > 0 else None)

    fcf_points = [v for _, v in scoring._annual_owner_fcf_points(bundle)]
    fcf_window = fcf_points[-NORMALIZED_FCF_YEARS:]
    norm_fcf = (sum(fcf_window) / len(fcf_window)
                if len(fcf_window) >= NORMALIZED_FCF_MIN_YEARS else None)
    norm_fcf_yield = (100.0 * norm_fcf / mcap
                      if norm_fcf is not None and mcap is not None and mcap > 0 else None)
    op_margin_mad, op_margin_improving = _op_margin_stats(bundle)

    return {
        "market_cap": mcap, "price": price,
        "ttm_net_income": ni, "ttm_ocf": ocf,
        "net_cash": net_cash,
        "de_ratio": (debt / equity if debt is not None and equity is not None
                     and equity > 0 else None),
        "liabilities_to_assets": (liabilities / assets
                                  if liabilities is not None and assets else None),
        "current_ratio": (current_assets / current_liabilities
                          if current_assets is not None and current_liabilities
                          else None),
        "ncav": ncav,
        "mcap_to_ncav": (mcap / ncav if mcap is not None and ncav is not None
                         and ncav > 0 else None),
        "eps_ttm": eps_ttm, "bvps": bvps,
        "graham_number": graham_number,
        "price_to_graham": (price / graham_number
                            if price is not None and graham_number else None),
        "pe": pe_ratio, "eps_cagr_pct": eps_cagr, "peg": peg,
        "ocf_to_ni": (ocf / ni if ocf is not None and ni is not None and ni > 0
                      else None),
        "ev_ebit": (own_ev / ebit if own_ev is not None and ebit is not None
                    and ebit > 0 and own_ev > 0 else None),
        "norm_fcf_yield_pct": norm_fcf_yield,
        "share_trend_pct": e.get("share_trend"),
        "roic_pct": e.get("roic"),
        "rev_growth_pct": e.get("rev_growth"),
        "op_margin_mad_pts": op_margin_mad,
        "op_margin_improving": op_margin_improving,
    }


# --- The four lenses (Pillar 2) -----------------------------------------------------------
# Verdict grammar: SPEAKS (qualifies, carries a rank — lower is better within the lens),
# SILENT (measured, does not qualify), REFUSES (decisive inputs unmeasured). Each lens is
# a checklist over the shared metric table; none of them reads another's verdict, and no
# code path anywhere combines two lenses into one number.

NET_NET_DISCOUNT = 2.0 / 3.0     # Graham: pay 66 cents for a dollar of NCAV
GARP_PEG_MAX = 1.0               # Lynch's buy zone (Slater strict at 0.75 is noted)
GARP_GROWTH_MIN = 15.0           # Slater's floor ...
GARP_GROWTH_MAX = 30.0           # ... and Lynch's distrust-above ceiling: a band, not a floor
GARP_GEARING_MAX = 0.5           # Slater: net gearing < 50%
DOWNSIDE_CR_MIN = 2.0            # Pabrai's floor legs
DOWNSIDE_DE_MAX = 0.3
DOWNSIDE_YIELD_MIN = 8.0         # Burry's lowest FCF-yield band
DOWNSIDE_EV_EBIT_MAX = 6.0       # Burry's EV/EBIT line
COMPOUNDER_SHARE_TREND_MAX = 2.0  # Cassel: self-funding, share CAGR <= +2%/yr
COMPOUNDER_ROIC_MIN = 15.0       # the Munger line the main desk also uses
COMPOUNDER_GROWTH_MIN = 10.0     # sustained, not spectacular
COMPOUNDER_MARGIN_MAD_MAX = 3.0  # Fisher-style stability, in margin points


def _lens(name: str, verdict: str, checks: dict, rank: float | None,
          detail: str) -> dict:
    return {"lens": name, "verdict": verdict, "checks": checks, "rank": rank,
            "detail": detail}


def _refusal(name: str, checks: dict, missing: list[str]) -> dict:
    return _lens(name, "refuses", checks, None,
                 f"Refuses to judge: {', '.join(missing)} unmeasured. A verdict without "
                 f"its inputs would be a guess.")


def lens_graham(m: dict) -> dict:
    """Deep value / asset floor: the net-net (price < 2/3 NCAV, still earning) or the
    Graham Number with the defensive balance-sheet checks. The one lens that essentially
    only exists down-cap.

    "Unmeasured" and "measured, fails" are kept apart deliberately: an unprofitable name
    has NO Graham Number (a measured fact — the lens is silent), while a balance sheet
    that never reported current assets cannot be judged at all (the lens refuses)."""
    name = "graham"
    # A side is JUDGEABLE when its inputs were measured; only then may it say yes or no.
    net_net_judgeable = (m["ncav"] is not None and m["market_cap"] is not None
                         and m["ttm_net_income"] is not None)
    gn_judgeable = (m["eps_ttm"] is not None and m["bvps"] is not None
                    and m["price"] is not None and m["current_ratio"] is not None
                    and m["liabilities_to_assets"] is not None)
    checks = {
        "net_net": (m["ncav"] > 0 and m["mcap_to_ncav"] is not None
                    and m["mcap_to_ncav"] < NET_NET_DISCOUNT
                    if net_net_judgeable else None),
        "still_earning": (m["ttm_net_income"] > 0
                          if m["ttm_net_income"] is not None else None),
        "under_graham_number": ((m["price_to_graham"] is not None
                                 and m["price_to_graham"] < 1.0)
                                if gn_judgeable else None),
        "current_ratio_2x": (m["current_ratio"] >= 2.0
                             if m["current_ratio"] is not None else None),
        "liabilities_under_half_assets": (m["liabilities_to_assets"] < 0.5
                                          if m["liabilities_to_assets"] is not None
                                          else None),
    }
    if checks["net_net"] and checks["still_earning"]:
        return _lens(name, "speaks", checks, m["mcap_to_ncav"],
                     f"Net-net: the market prices this at {m['mcap_to_ncav']:.2f}x net "
                     f"current asset value while it still earns — Graham's classic "
                     f"deep-value case. (Preferred stock is not netted; verify in the "
                     f"filing.)")
    if (checks["under_graham_number"] and checks["current_ratio_2x"]
            and checks["liabilities_under_half_assets"]):
        return _lens(name, "speaks", checks, 1.0 + m["price_to_graham"],
                     f"Priced under the Graham Number ({m['price_to_graham']:.2f}x) with "
                     f"the defensive balance-sheet checks intact.")
    if not net_net_judgeable and not gn_judgeable:
        return _refusal(name, checks, ["net_net", "under_graham_number"])
    return _lens(name, "silent", checks, None,
                 "Judged on the measured side(s), and neither the net-net nor the "
                 "Graham Number case holds.")


def lens_garp(m: dict) -> dict:
    """Growth at a reasonable price (Lynch/Slater): PEG in the buy zone, growth in a
    BAND — Lynch distrusts >30%/yr as fad territory — cash-backed earnings, low
    gearing."""
    name = "garp"
    growth = m["eps_cagr_pct"]
    checks = {
        "peg_buy_zone": m["peg"] <= GARP_PEG_MAX if m["peg"] is not None else None,
        "growth_in_band": (GARP_GROWTH_MIN <= growth <= GARP_GROWTH_MAX
                           if growth is not None else None),
        "cash_backed": (m["ocf_to_ni"] >= 1.0
                        if m["ocf_to_ni"] is not None else None),
        "low_gearing": (m["net_cash"] is not None and m["net_cash"] >= 0)
                       or (m["de_ratio"] < GARP_GEARING_MAX
                           if m["de_ratio"] is not None else None),
    }
    missing = [k for k, v in checks.items() if v is None]
    if missing:
        return _refusal(name, checks, missing)
    if all(checks.values()):
        slater = " (inside Slater's strict 0.75)" if m["peg"] <= 0.75 else ""
        return _lens(name, "speaks", checks, m["peg"],
                     f"GARP: {growth:.0f}%/yr EPS growth at PEG {m['peg']:.2f}{slater}, "
                     f"cash-backed and lightly geared — the ten-bagger hunting profile.")
    return _lens(name, "silent", checks, None,
                 "Measured, and the growth/price/cash tests do not all hold.")


def lens_downside(m: dict) -> dict:
    """Downside-first deep value (Pabrai/Burry): the floor before the upside — heads I
    win, tails I don't lose much. Hated is fine; the Forge already removed dying."""
    name = "downside"
    floor = ((m["net_cash"] is not None and m["net_cash"] > 0)
             or (m["current_ratio"] is not None and m["current_ratio"] >= DOWNSIDE_CR_MIN
                 and m["de_ratio"] is not None and m["de_ratio"] < DOWNSIDE_DE_MAX))
    floor_unmeasured = (m["net_cash"] is None and
                        (m["current_ratio"] is None or m["de_ratio"] is None))
    cheap_yield = (m["norm_fcf_yield_pct"] is not None
                   and m["norm_fcf_yield_pct"] >= DOWNSIDE_YIELD_MIN)
    cheap_ebit = m["ev_ebit"] is not None and m["ev_ebit"] <= DOWNSIDE_EV_EBIT_MAX
    checks = {"downside_floor": None if floor_unmeasured else floor,
              "normalized_fcf_yield": (None if m["norm_fcf_yield_pct"] is None
                                       else cheap_yield),
              "ev_ebit_cheap": None if m["ev_ebit"] is None else cheap_ebit}
    if floor_unmeasured:
        return _refusal(name, checks, ["downside_floor"])
    if m["norm_fcf_yield_pct"] is None and m["ev_ebit"] is None:
        return _refusal(name, checks, ["normalized_fcf_yield", "ev_ebit"])
    if floor and (cheap_yield or cheap_ebit):
        via = (f"{m['norm_fcf_yield_pct']:.0f}% normalized owner-FCF yield" if cheap_yield
               else f"EV/EBIT {m['ev_ebit']:.1f}")
        rank = -m["norm_fcf_yield_pct"] if cheap_yield else -100.0 / m["ev_ebit"]
        return _lens(name, "speaks", checks, rank,
                     f"Downside protected (the floor holds) and cheap on {via} — "
                     f"low-risk, high-uncertainty: heads I win, tails I don't lose much.")
    return _lens(name, "silent", checks, None,
                 "Measured, and either the floor or the cheapness is absent.")


def lens_compounder(m: dict) -> dict:
    """The owner-operator quality compounder (Cassel/Fisher): profitable before scale,
    self-funding, stable economics, real returns on capital. Its qualitative half —
    owner-operators, niche dominance — is Pillar 3's scuttlebutt, not a number here."""
    name = "compounder"
    stable = None
    if m["op_margin_mad_pts"] is not None:
        stable = (m["op_margin_mad_pts"] <= COMPOUNDER_MARGIN_MAD_MAX
                  or bool(m["op_margin_improving"]))
    checks = {
        "profitable_before_scale": (m["ttm_net_income"] > 0 and m["ttm_ocf"] > 0
                                    if None not in (m["ttm_net_income"], m["ttm_ocf"])
                                    else None),
        "self_funding": (m["share_trend_pct"] <= COMPOUNDER_SHARE_TREND_MAX
                         if m["share_trend_pct"] is not None else None),
        "roic_15": (m["roic_pct"] >= COMPOUNDER_ROIC_MIN
                    if m["roic_pct"] is not None else None),
        "growth_sustained": (m["rev_growth_pct"] >= COMPOUNDER_GROWTH_MIN
                             if m["rev_growth_pct"] is not None else None),
        "margins_stable_or_improving": stable,
    }
    missing = [k for k, v in checks.items() if v is None]
    if missing:
        return _refusal(name, checks, missing)
    if all(checks.values()):
        return _lens(name, "speaks", checks, -m["rev_growth_pct"],
                     f"Compounder profile: profitable and self-funding, ROIC "
                     f"{m['roic_pct']:.0f}%, revenue compounding {m['rev_growth_pct']:.0f}%/yr "
                     f"on stable margins — now the scuttlebutt work decides.")
    return _lens(name, "silent", checks, None,
                 "Measured, and the compounder tests do not all hold.")


LENS_ORDER = ("graham", "garp", "downside", "compounder")
_LENS_FNS = {"graham": lens_graham, "garp": lens_garp,
             "downside": lens_downside, "compounder": lens_compounder}


def lenses(bundle: dict, evaluated: dict | None = None,
           metric_table: dict | None = None) -> dict:
    m = metric_table if metric_table is not None else metrics(bundle, evaluated)
    return {name: _LENS_FNS[name](m) for name in LENS_ORDER}


# --- Eligibility and the one-name analysis ------------------------------------------------

def eligible(bundle: dict) -> tuple[bool, str]:
    """The lane's band. A POSITIVE claim: unlike the main desk's floor (where a missing
    figure never excludes), low-cap membership requires the qualifying figures."""
    mcap = scoring._num(bundle.get("market_cap"))
    price = scoring._num(bundle.get("price"))
    if mcap is None:
        return False, "market cap unmeasured — cannot certify the name small"
    if not (LOWCAP_MIN_MARKET_CAP <= mcap < LOWCAP_MAX_MARKET_CAP):
        side = "below $50M (promotion/shell tier)" if mcap < LOWCAP_MIN_MARKET_CAP \
            else "above $2B (the main desk's ground)"
        return False, f"market cap ${mcap / 1e6:,.0f}M is {side}"
    if price is None:
        return False, "price unmeasured"
    if price < LOWCAP_MIN_PRICE:
        return False, f"price ${price:.2f} under the $1 exchange survival line"
    return True, f"${mcap / 1e6:,.0f}M at ${price:.2f} — inside the lane's band"


def analyze(bundle: dict, *, evaluated: dict | None = None, prices=None) -> dict:
    """The whole lane for one name: eligibility, the Forge, the shared metric table and
    the four lens verdicts — assembled, never combined."""
    e = evaluated if evaluated is not None else scoring.evaluate(bundle)
    ok, reason = eligible(bundle)
    m = metrics(bundle, e)
    return {
        "symbol": bundle.get("symbol"),
        "eligible": ok, "eligibility": reason,
        "forge": forge(bundle, evaluated=e, prices=prices),
        "metrics": m,
        "lenses": lenses(bundle, e, m),
    }


def _survives_main_inversion(row: dict) -> bool:
    """The same two tests the main desk applies (thesis._survives_inversion's logic):
    Fragile/Ruinous or any severe probe is out; a missing result is NOT an exclusion —
    absence of evidence is not a veto, and Unknown is not a veto (invariant 12)."""
    inv = row.get("inversion")
    if not isinstance(inv, dict):
        return True
    if inv.get("verdict") in picks.SHORTLIST_EXCLUDE_VERDICTS:
        return False
    return (inv.get("coverage") or {}).get("severe", 0) <= picks.SHORTLIST_MAX_SEVERE


def shortlists(rows: list[dict], per_lens: int = SHORTLIST_PER_LENS) -> dict:
    """The interface's four side-by-side lists. A row is a candidate when it is inside
    the band, not Forged-out (the lane's own gate), and survives the main inversion
    layer (Hell-No runs before the dossier in BOTH lanes). Each lens ranks only within
    its own logic; a name on several lists appears on several lists.

    Rows carry {"symbol", "lowcap": analyze(...), "inversion": optional main-desk
    result}. Watch and Unknown names remain listable — their Forge verdict rides along
    visibly — only a named severe finding (Forged-out) closes the door."""
    lists: dict[str, list[dict]] = {name: [] for name in LENS_ORDER}
    for row in rows:
        lane = row.get("lowcap") or {}
        if not lane.get("eligible"):
            continue
        if (lane.get("forge") or {}).get("verdict") == "Forged-out":
            continue
        if not _survives_main_inversion(row):
            continue
        for name in LENS_ORDER:
            lens_result = (lane.get("lenses") or {}).get(name) or {}
            if lens_result.get("verdict") == "speaks" \
                    and lens_result.get("rank") is not None:
                lists[name].append({
                    "symbol": row.get("symbol") or lane.get("symbol"),
                    "rank": lens_result["rank"],
                    "detail": lens_result.get("detail"),
                    "forge_verdict": (lane.get("forge") or {}).get("verdict"),
                })
    out = {}
    for name in LENS_ORDER:
        ranked = sorted(lists[name], key=lambda r: (r["rank"], r["symbol"] or ""))
        out[name] = ranked[:per_lens]
    return out
