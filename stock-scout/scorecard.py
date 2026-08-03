"""The Owner's Scorecard — the absolute, anchored composite (docs/SCORECARD-DESIGN.md).

100 points across four blocks, each point earned against an economically meaningful
reference line instead of against whoever else happened to be in the run: the same
business scores the same tomorrow, in a different universe, in a different sector
(design §2). Every anchor lives in the ANCHORS table below, one row per metric, so the
design's provenance table (§3) maps onto it 1:1.

This module interprets; it does not re-derive. Every raw metric comes from scoring.py —
from the §3.3 row score_universe() already produced when one is supplied, otherwise from
scoring's own phase-1 assembly of the same Bundle (§4.1) — so the live and backtest paths
read one computation and cannot disagree. Nothing here does I/O, network or clock.

The §4 honesty rules are load-bearing, not decoration:
  * no price, no verdict — an absent Price block yields the literal "NO PRICE" band and a
    quality profile that is explicitly not a verdict;
  * a missing input shrinks `available_max` and is named in `coverage`, never a silent 0;
  * a §4.4 veto suppresses the score rather than ranking it;
  * differences under NOISE_FLOOR points are not meaningful, and the output says so.

Two guards go beyond the design text, both in the direction of honesty (and both noted in
the metric's own coverage reason): a gross-margin series too thin to have a coefficient of
variation is unavailable rather than scoring the full 5 points on scoring's "no evidence of
drift" 0.0 default, and a share-count trend the §4.5 SHARE_CLASS flag has already declared
untrustworthy is unavailable rather than scored.

The inversion layer (docs/INVERSION-DESIGN.md) rides BESIDE this card, never inside it.
Buffett's scorecard says how good a business is; Munger's lens says how it breaks, and
INVERSION-DESIGN §2 forbids folding the second into the first — a fragility score inside
the 100 points would let a high total paper over fragility, the exact trade §1.6 already
forbids. So an `inversion_result` is attached under "inversion" and joins the §5 consensus
as a fourth lens, and it moves no point, no block, no band. It is optional in both
directions: `inversion.py` is imported lazily and only where it is needed, and a card
without a result keeps exactly the three-lens consensus it had (the SEC-export path has no
prices for ~470 names, so the fourth lens genuinely cannot be computed there).
"""
from __future__ import annotations

import scoring

# --- The anchor table (design §2 blocks, §3 provenance) ----------------------------------
# floor -> 0 points, target -> full points, linear in between (§2). `invert` records that
# the metric reads lower-better (target < floor); the ramp needs no special case for it.
# `unit` selects the renderer used in every human sentence this module emits.
ANCHORS = {
    # Block 1 — Business quality · 35 pts · "Would I want to own this business?"
    "roic": {
        "block": "quality", "label": "ROIC", "floor": 5.0, "target": 25.0, "points": 12,
        "invert": False, "unit": "pct",
        "provenance": "Inherited — scoring.QV_ROIC_MIN (15%) sits at this ramp's exact "
                      "midpoint; the 5%/25% endpoints bracket it symmetrically (§3)"},
    "gross_margin": {
        "block": "quality", "label": "gross margin", "floor": 20.0, "target": 60.0,
        "points": 6, "invert": False, "unit": "pct",
        "provenance": "New — the 20%/60% band spans commodity to software economics (§3)"},
    "gross_margin_cv": {
        "block": "quality", "label": "gross-margin stability (CV)", "floor": 0.35,
        "target": 0.05, "points": 5, "invert": True, "unit": "ratio",
        "provenance": "New — not enumerated in the §3 provenance table; brackets a stable "
                      "margin (CV <= 0.05) against a visibly drifting one (CV >= 0.35)"},
    "owner_fcf_margin": {
        "block": "quality", "label": "owner-FCF margin", "floor": 0.0, "target": 20.0,
        "points": 7, "invert": False, "unit": "pct",
        "provenance": "New — a 1-in-5 cash conversion is exceptional (§3)"},
    "revenue_growth": {
        "block": "quality", "label": "revenue growth", "floor": 0.0, "target": 15.0,
        "points": 5, "invert": False, "unit": "pct_per_year",
        "provenance": "New — 15%/yr is the growth the G pillar already gates at 10%/yr "
                      "for reinvestors (§3)"},
    # Block 2 — Price · 25 pts · "Am I paying a fair price?"
    "owner_fcf_yield": {
        "block": "price", "label": "owner-FCF yield on EV", "floor": 0.02, "target": 0.08,
        "points": 15, "invert": False, "unit": "yield_pct",
        "provenance": "New — 8% ~ 12.5x owner earnings, Buffett's habitual 'fair' (§3)"},
    "margin_of_safety": {
        "block": "price", "label": "margin of safety", "floor": -0.25, "target": 0.50,
        "points": 10, "invert": False, "unit": "mos_pct",
        "provenance": "New — mirrors ai-hedge-fund's 25% margin-of-safety convention (§3)"},
    # Block 3 — Safety · 25 pts · "Can this be permanently impaired?" (Munger)
    "net_debt_ebitda": {
        "block": "safety", "label": "net debt/EBITDA", "floor": 4.0, "target": 0.0,
        "points": 10, "invert": True, "unit": "ratio",
        "provenance": "Inherited — scoring.NET_DEBT_EBITDA_VETO (4.0), the §4.4 leverage "
                      "veto line, used as the ramp floor (§3)"},
    "self_funding": {
        "block": "safety", "label": "self-funding", "floor": 0.5, "target": 1.0,
        "points": 8, "invert": False, "unit": "share_of_periods",
        "provenance": "New — not enumerated in the §3 provenance table; half the annual "
                      "periods self-funding is the floor, every period the target"},
    "sbc": {
        "block": "safety", "label": "SBC", "floor": 10.0, "target": 2.0, "points": 4,
        "invert": True, "unit": "pct_of_revenue",
        "provenance": "New — 2% is the conventional 'low SBC' for profitable software (§3)"},
    "current_ratio": {
        "block": "safety", "label": "current ratio", "floor": 1.0, "target": 2.0,
        "points": 3, "invert": False, "unit": "ratio",
        "provenance": "Inherited — the ai-hedge-fund Buffett-checklist current ratio > 1.5 "
                      "sits at this ramp's midpoint (§3)"},
    # Block 4 — Stewardship · 15 pts · "Is management on my side?"
    "share_count_trend": {
        "block": "stewardship", "label": "share-count trend", "floor": 5.0, "target": -2.0,
        "points": 7, "invert": True, "unit": "pct_per_year",
        "provenance": "Inherited — scoring.DILUTION_PENALTY_PCT (+5%/yr), the §4.4 "
                      "dilution-penalty line, used as the ramp floor (§3)"},
    "accruals": {
        "block": "stewardship", "label": "accruals", "floor": 10.0, "target": 0.0,
        "points": 5, "invert": True, "unit": "pct_of_revenue",
        "provenance": "New — not enumerated in the §3 provenance table; earnings that fully "
                      "become cash (0%) score full, +10% of revenue scores none"},
    "capital_returned": {
        "block": "stewardship", "label": "capital returned / owner-FCF", "floor": 0.0,
        "target": 0.5, "points": 3, "invert": False, "unit": "ratio",
        "provenance": "New — half of owner earnings returned is shareholder-friendly (§3)"},
}

BLOCKS = {"quality": 35, "price": 25, "safety": 25, "stewardship": 15}
FULL_MAX = sum(BLOCKS.values())         # 100 — the design's undiminished denominator
NOISE_FLOOR = 5.0                       # §4.4 — differences under this are not meaningful

# Evidence tiers — how much of the 100-point card could actually be measured. A percentage
# of the AVAILABLE points (§4.2) silently rewards ignorance: a name measured on 64 points
# scoring 97% outranks one measured on 87 scoring 94%, though the second is the better
# evidenced business. Ranking must therefore respect the tier first and the score second,
# so a thinly-evidenced name can never outrank a fully-measured one on a technicality.
EVIDENCE_TIERS = (("full", 0.85), ("partial", 0.60), ("thin", 0.0))


def evidence_tier(available_max: float) -> str:
    """The §4.2 evidence tier for a card's available_max (share of the full 100 points)."""
    share = (available_max or 0.0) / FULL_MAX
    for name, floor in EVIDENCE_TIERS:
        if share >= floor:
            return name
    return "thin"


def rank_key(card: dict) -> tuple:
    """Sort key for presenting cards: evidence tier first, then percentage, so more-measured
    names lead. Vetoed/no-verdict cards sort last. Use with reverse=False."""
    order = {name: i for i, (name, _) in enumerate(EVIDENCE_TIERS)}
    pct = card.get("pct")
    if pct is None:
        return (len(order) + 1, 0.0, card.get("symbol") or "")
    return (order.get(card.get("evidence"), len(order)), -float(pct), "")

VETOED_BAND = "VETOED"
NO_PRICE_BAND = "NO PRICE"
NO_PRICE_MEANING = ("Quality profile only — no price data, so this is NOT a verdict: the "
                    "points below say what the business looks like, not whether to buy it "
                    "(§4.1)")

# §5 band table, richest first; the two special bands carry no numeric range.
BANDS = (
    {"band": "Exceptional", "floor": 80,
     "meaning": "Wonderful business at a fair price — take to the Gate first"},
    {"band": "Strong", "floor": 65, "meaning": "Worth the Gate's homework"},
    {"band": "Mixed", "floor": 50, "meaning": "One or more legs genuinely weak"},
    {"band": "Weak", "floor": 35, "meaning": "Needs a special reason"},
    {"band": "Pass", "floor": 0, "meaning": "Not a candidate"},
    {"band": VETOED_BAND, "floor": None,
     "meaning": "A §4.4 gate tripped — score suppressed, reason printed"},
    {"band": NO_PRICE_BAND, "floor": None, "meaning": NO_PRICE_MEANING},
)
_BAND = {entry["band"]: entry for entry in BANDS}

# §5 consensus thresholds — independent lenses, each with its own definition of good; these
# three are on every card, the fourth below joins when the inversion layer has an answer.
CONSENSUS_SCORECARD_PCT = 60.0
CONSENSUS_BUFFETT_SCORE = 9
CONSENSUS_LENSES = ("scorecard", "margin_of_safety", "buffett")

# The fourth lens (INVERSION-DESIGN §5). The three above all answer "is this good?"; this
# one answers "will it survive?", which is the question they share a blind spot on. It is
# NOT a fourth always-present lens: it joins only when an inversion result is supplied, so
# a card built without prices still reports an honest three-of-three rather than a
# permanently unknown quarter. CONSENSUS_LENSES therefore stays the three lenses every card
# carries, and `of` is the number of lenses actually consulted.
CONSENSUS_SURVIVAL_LENS = "survival"
CONSENSUS_LENSES_ALL = CONSENSUS_LENSES + (CONSENSUS_SURVIVAL_LENS,)

# Verdict -> "does it survive?". inversion.consensus_lens owns this judgement; the table is
# the fallback for the case where that module is not importable at all (the two layers ship
# separately), so the lens degrades to the published §4 verdict table rather than to a
# comforting default. Unknown maps to None — said out loud, never read as safe (§4, §7).
INVERSION_UNKNOWN = "Unknown"
INVERSION_SURVIVES = {"robust": True, "ordinary": True,
                      "fragile": False, "ruinous": False, INVERSION_UNKNOWN.lower(): None}
_LENS_COUNT_WORD = {3: "three", 4: "four"}

# Capital returned to owners, newest annual cash-flow period; first present per chain wins,
# an absent sibling row means that channel returned nothing. pit.py maps both chains from
# EDGAR (PaymentsOfDividendsCommonStock / PaymentsForRepurchaseOfCommonStock), so live and
# backtest cards share this metric and their headline percentages stay comparable.
_CAPITAL_RETURN_CHAINS = (
    ("Cash Dividends Paid", "Common Stock Dividend Paid", "Dividends Paid"),
    ("Repurchase Of Capital Stock", "Common Stock Payments"),
)

# Anchor id -> (scoring._evaluate key, §3.3 leg id carrying the same raw value).
_LEG_OF = {
    "roic": ("roic", "q_roic"),
    "gross_margin": ("gm_level", "q_gm"),
    "owner_fcf_margin": ("ofcf_margin", "q_ofcf_margin"),
    "revenue_growth": ("rev_growth", "g_revenue"),
    "owner_fcf_yield": ("v_yield", "v_yield"),
    "net_debt_ebitda": ("nd2e", "d_net_debt"),
    "sbc": ("sbc_pct", "d_sbc"),
    "share_count_trend": ("share_trend", "m_shares"),
    "accruals": ("accrual", "m_accruals"),
}

_MISSING_REASON = {
    "roic": "no TTM EBIT or Greenblatt capital base (or the base is <= 0 with EBIT <= 0)",
    "gross_margin": "no TTM gross profit or revenue",
    "owner_fcf_margin": "no TTM owner-FCF",
    "owner_fcf_yield": "no market cap, own EV <= 0, or no TTM owner-FCF",
    "net_debt_ebitda": "TTM EBITDA is 0 or missing, or debt/cash missing",
    "sbc": "no TTM SBC or revenue",
    "share_count_trend": "no usable share-count series",
    "accruals": "no TTM net income incl. NCI, OCF or revenue",
}

_RENDER = {
    "pct": lambda v: f"{v:.0f}%",
    "pct_of_revenue": lambda v: f"{v:.0f}% of revenue",
    "pct_per_year": lambda v: f"{v:+.1f}%/yr",
    "yield_pct": lambda v: f"{100.0 * v:.1f}%",
    "mos_pct": lambda v: f"{100.0 * v:+.0f}%",
    "ratio": lambda v: f"{v:.2f}",
    "share_of_periods": lambda v: f"{100.0 * v:.0f}% of annual periods",
}


def _render(metric_id: str, value: float) -> str:
    """The metric's value in its own unit — the design's units are NOT uniform and every
    sentence this module prints passes through here (RECONSTRUCTION.md §3.3)."""
    return _RENDER[ANCHORS[metric_id]["unit"]](value)


# --- The scoring rule (§2) ---------------------------------------------------------------

def ramp(value: float, floor: float, target: float, points: float) -> float:
    """§2: clamp((value - floor) / (target - floor), 0, 1) x points — linear between the
    two anchors, no cliffs, clamped at both ends. target < floor is the lower-is-better
    direction and needs no special case. A zero-width ramp is a table error, not an input."""
    if target == floor:
        raise ValueError("ramp needs distinct floor and target anchors")
    frac = (value - floor) / (target - floor)
    return round(max(0.0, min(1.0, frac)) * points, 6)


def score_metric(metric_id: str, value: float | None) -> dict:
    """One anchored metric -> {value, points, max, pct, detail}. `value` None means the
    input was not computable: points and pct are None (§4.2 — a reduced maximum, never a
    silent zero), and the caller replaces `detail` with the specific reason."""
    a = ANCHORS[metric_id]
    if value is None:
        return {"value": None, "points": None, "max": a["points"], "pct": None,
                "detail": f"{a['label']}: not computable — scored out of a reduced "
                          f"maximum (§4.2)"}
    pts = round(ramp(value, a["floor"], a["target"], a["points"]), 1)
    return {"value": value, "points": pts, "max": a["points"],
            "pct": round(100.0 * pts / a["points"]),
            "detail": f"{a['label']} {_render(metric_id, value)} -> {pts}/{a['points']} pts "
                      f"(0 at {_render(metric_id, a['floor'])}, "
                      f"full at {_render(metric_id, a['target'])})"}


def _band_of(pct: float) -> dict:
    """§5 band for a whole-number percentage of the AVAILABLE maximum; Pass (floor 0) is
    the default row, so the lookup stays total (mirrors scoring.grade_letter)."""
    for entry in BANDS:
        if entry["floor"] is not None and pct >= entry["floor"]:
            return entry
    return _BAND["Pass"]


# --- Values: the row first, scoring.py's own assembly otherwise --------------------------

def _gross_margin_cv(bundle: dict, evaluated: dict) -> tuple[float | None, str | None]:
    """Gross-margin CV, but only when there is a series to have one. scoring returns 0.0
    with fewer than two usable annual gross-margin periods ("no evidence of drift") — a
    percentile-engine convenience that would hand a name with no history at all the full 5
    stability points here, which §4.2 forbids in either direction."""
    inc = (bundle.get("annual") or {}).get("income") or {}
    usable = sum(1 for pe in inc
                 if scoring._row(inc[pe], "gross_profit") is not None
                 and scoring._row(inc[pe], "revenue"))
    if usable < 2:
        return None, f"only {usable} usable annual gross-margin period(s) — a CV needs 2"
    return evaluated["gm_cv"], None


def _self_funding(bundle: dict) -> tuple[float | None, str | None]:
    """Share of annual periods with positive normalized owner-FCF (design Block 3) — the
    same annual series the §4.2 cash-destruction test runs on."""
    points = scoring._annual_owner_fcf_points(bundle)
    if not points:
        return None, "no usable annual owner-FCF periods"
    return sum(1 for _, v in points if v > 0) / len(points), None


def _current_ratio(bundle: dict) -> tuple[float | None, str | None]:
    """Current assets / current liabilities on the latest balance sheet — scoring's
    quarterly-preferred `_latest_balance`, the same sheet net debt/EBITDA is read from."""
    bal = scoring._latest_balance(bundle)
    ca = scoring._row(bal, "current_assets")
    cl = scoring._row(bal, "current_liabilities")
    if ca is None or not cl or cl <= 0:
        return None, "no current assets/liabilities on the latest balance sheet"
    return ca / cl, None


def _capital_returned(bundle: dict) -> tuple[float | None, str | None]:
    """(Dividends paid + buybacks) / owner-FCF over the SAME newest annual period, keeping
    numerator and denominator on one window (§4.2's discipline). Sign-agnostic: Yahoo
    reports both as outflows."""
    cf = (bundle.get("annual") or {}).get("cashflow") or {}
    if not cf:
        return None, "no annual cash-flow statement"
    period = max(cf)
    cell = cf[period]
    paid = []
    for chain in _CAPITAL_RETURN_CHAINS:
        for label in chain:
            value = scoring._num(cell.get(label))
            if value is not None:
                paid.append(abs(value))
                break
    if not paid:
        return None, ("no dividend or buyback row in the newest annual cash-flow statement "
                      "(the EDGAR/PIT path carries neither)")
    points = scoring._annual_owner_fcf_points(bundle)
    if not points or points[-1][0] != period:
        return None, f"no owner-FCF for the {period} annual period"
    owner_fcf = points[-1][1]
    if owner_fcf <= 0:
        return None, f"owner-FCF <= 0 in {period} — the ratio would not be meaningful"
    return sum(paid) / owner_fcf, None


def _values(bundle: dict, scored_row: dict | None, evaluated: dict,
            mos: dict | None) -> tuple[dict, dict, list[str]]:
    """Raw value and missing-reason per anchor, plus run notes -> (values, reasons, notes).

    A §3.3 row's `legs[...]["raw"]` wins when present — that is the value score_universe
    itself scored, so live and backtest read one computation. Everything else comes from
    scoring's own phase-1 assembly of the same Bundle (§4.1), never from a second recipe."""
    legs = (scored_row or {}).get("legs") or {}
    values, reasons, notes = {}, {}, []

    for metric_id, (key, leg_id) in _LEG_OF.items():
        leg = legs.get(leg_id)
        value = leg["raw"] if leg is not None and "raw" in leg else evaluated[key]
        values[metric_id] = value
        if value is None:
            reasons[metric_id] = (evaluated["rev_note"] if metric_id == "revenue_growth"
                                  else _MISSING_REASON[metric_id])

    if evaluated["share_class"] and values["share_count_trend"] is not None:
        values["share_count_trend"] = None
        reasons["share_count_trend"] = ("SHARE_CLASS — §4.5 already declares this name's "
                                        "share-count trend untrustworthy")

    for metric_id, (value, reason) in {
            "gross_margin_cv": _gross_margin_cv(bundle, evaluated),
            "self_funding": _self_funding(bundle),
            "current_ratio": _current_ratio(bundle),
            "capital_returned": _capital_returned(bundle)}.items():
        values[metric_id] = value
        if value is None:
            reasons[metric_id] = reason

    values["margin_of_safety"] = None if mos is None else mos.get("mos_pct")
    if values["margin_of_safety"] is None:
        reasons["margin_of_safety"] = ("no DCF margin of safety — market cap unusable or "
                                       "base owner-FCF <= 0 (§4.8)")

    funding_periods = len(scoring._annual_owner_fcf_points(bundle))
    if 0 < funding_periods < 3:
        notes.append(f"Self-funding is measured over only {funding_periods} annual "
                     f"period(s) — thin evidence.")
    return values, reasons, notes


# --- The inversion layer, beside the points (INVERSION-DESIGN §2, §5) --------------------

def _inversion_module():
    """`inversion.py`, imported lazily and here only. The inversion layer is optional to
    this module — a checkout without it must still import, score and render a card — so the
    dependency lives inside the one function that needs it rather than at module scope."""
    try:
        import inversion
    except ImportError:
        return None
    return inversion


def _failure_sentence(mode) -> str:
    """One failure mode as a sentence. INVERSION-DESIGN §4 wants plain language; whether the
    layer hands over the sentence itself or a probe record carrying one, the card shows the
    sentence and never a repr."""
    if isinstance(mode, dict):
        for key in ("sentence", "detail", "note", "reason", "label"):
            if mode.get(key):
                return str(mode[key])
        return ""
    return str(mode or "")


def _inversion_card(inversion_result: dict) -> dict:
    """The §5 card projection. The verdict and its failure modes are guaranteed keys — a
    result naming neither is Unknown rather than blank — and everything else the layer
    produced (probes, coverage, notes) rides along untouched, so a renderer never has to
    reach back past the card. A copy: the caller's dict cannot mutate a built card."""
    attached = dict(inversion_result)
    attached["verdict"] = inversion_result.get("verdict") or INVERSION_UNKNOWN
    attached["failure_modes"] = list(inversion_result.get("failure_modes") or [])
    return attached


def survival_lens(inversion_result: dict | None) -> bool | None:
    """The §5 fourth lens for one inversion result: True it has survived, False it has a
    named way of breaking you, None not known.

    `inversion.consensus_lens` owns this judgement and is asked first — with the normalized
    result, then with the bare verdict, since which of the two that function takes is the
    other module's to decide. INVERSION_SURVIVES answers only when the module is absent or
    refuses both call shapes, never in place of a verdict that module did make. No result at
    all is None: the lens is absent, which is neither green nor a silent red.

    The guard is `Exception`, not `TypeError`. The layer ships separately, so this seam is
    defensive by design — and this is the SECOND entry point into it (grade.run calls
    scorecard() bare, unlike inversion_for, which wraps its own call). A lens that raises
    anything at all must cost this card its fourth lens, never the whole grading run."""
    if not inversion_result:
        return None
    asked = _inversion_card(inversion_result)
    lens = getattr(_inversion_module(), "consensus_lens", None)
    if lens is not None:
        for argument in (asked, asked["verdict"]):
            try:
                return lens(argument)
            except Exception:
                continue
    return INVERSION_SURVIVES.get(str(asked["verdict"]).strip().lower())


def _survival_note(inversion_result: dict) -> str:
    """The §5 consensus evidence line for the survival lens: the verdict and, where the
    layer named one, the failure mode that decided it. An Unknown verdict says so in words
    — §4/§7: too little evidence is stated, never read as safety."""
    attached = _inversion_card(inversion_result)
    verdict = attached["verdict"]
    modes = [s for s in (_failure_sentence(m) for m in attached["failure_modes"]) if s]
    if modes:
        return f"inversion {verdict} — {modes[0]}"
    if str(verdict).strip().lower() == INVERSION_UNKNOWN.lower():
        return (f"inversion {verdict} — too little evidence to say how this breaks; "
                f"not read as safe")
    return f"inversion {verdict}"


def _why_entry(metric_id: str, metric: dict, verb: str) -> dict:
    """§5 "why, in words" — one metric named with its raw value, its unit and its points."""
    anchor = ANCHORS[metric_id]
    return {"metric": metric_id, "label": anchor["label"], "value": metric["value"],
            "points": metric["points"], "max": metric["max"], "pct": metric["pct"],
            "sentence": f"{verb} {anchor['label']} at {_render(metric_id, metric['value'])} "
                        f"({metric['points']:.1f}/{anchor['points']:g})"}


def scorecard(bundle: dict, *, scored_row: dict | None = None,
              inversion_result: dict | None = None) -> dict:
    """The whole §2-§5 scorecard for one name: points, blocks, band, why, consensus,
    coverage, veto and notes.

    `scored_row` is the §3.3 row score_universe() produced for this same Bundle; its raw
    metric values are reused so the live and backtest paths never disagree. Without one the
    values come from scoring's own assembly of the Bundle and the §4.4 veto layer is run
    here (scoring.veto_check) rather than read off the row.

    `inversion_result` is what `inversion.inversion()` returned for this same Bundle. It is
    attached under "inversion" and adds the §5 survival lens to the consensus — and that is
    all it does: INVERSION-DESIGN §2 keeps Munger's lens out of Buffett's points, so `score`,
    `available_max`, `pct`, `band` and every block are bit-for-bit what they are without it.
    Omitting it is a first-class case, not a degraded one: the card is then exactly the
    three-lens card it has always been, with no "inversion" key at all.

    Honesty (§4): a vetoed name keeps its evidence but loses its score — VETOED, reason
    printed, `score` and `pct` None, so nothing can rank it. An empty Price block yields
    the literal NO PRICE band, whose meaning states outright that the points are a quality
    profile and not a verdict. Unavailable metrics shrink `available_max` and are each
    named in `coverage`; `pct` is a whole number of the available maximum."""
    if scored_row is not None:
        want, got = bundle.get("symbol"), scored_row.get("symbol")
        if want and got and want != got:
            raise ValueError(f"scored_row is for {got}, bundle is for {want}")

    evaluated = scoring._evaluate(bundle)
    mos = (scored_row or {}).get("mos") or scoring.margin_of_safety(bundle)
    buffett = (scored_row or {}).get("buffett") or scoring.buffett_checklist(bundle)
    values, reasons, notes = _values(bundle, scored_row, evaluated, mos)

    metrics = {}
    for metric_id in ANCHORS:
        metric = score_metric(metric_id, values[metric_id])
        if metric["points"] is None:
            metric["detail"] = (f"{ANCHORS[metric_id]['label']}: not computable — "
                                f"{reasons[metric_id]} (§4.2)")
        metrics[metric_id] = metric

    blocks, missing = {}, []
    for block in BLOCKS:
        ids = [m for m in ANCHORS if ANCHORS[m]["block"] == block]
        scored_ids = [m for m in ids if metrics[m]["points"] is not None]
        blocks[block] = {
            "points": round(sum(metrics[m]["points"] for m in scored_ids), 1),
            "max": sum(ANCHORS[m]["points"] for m in scored_ids),
            "metrics": scored_ids}
        missing += [{"metric": m, "label": ANCHORS[m]["label"], "block": block,
                     "points": ANCHORS[m]["points"], "reason": reasons[m]}
                    for m in ids if metrics[m]["points"] is None]

    score = round(sum(b["points"] for b in blocks.values()), 1)
    available_max = sum(b["max"] for b in blocks.values())
    pct = round(100.0 * score / available_max) if available_max else None
    coverage = {"available_max": available_max, "full_max": FULL_MAX,
                "scored": [m for m in ANCHORS if metrics[m]["points"] is not None],
                "missing": missing,
                "missing_points": sum(m["points"] for m in missing)}

    if scored_row is not None and scored_row.get("veto") is not None:
        veto = dict(scored_row["veto"])
    else:
        veto, _ = scoring.veto_check(
            net_debt_to_ebitda=evaluated["nd2e"], ebitda=evaluated["ebitda"],
            net_debt=evaluated["net_debt"], credit_loss=evaluated["credit_loss"],
            ocf=evaluated["ocf"], share_trend_pct=evaluated["share_trend"],
            share_class=evaluated["share_class"],
            annual_all_negative=evaluated["annual_all_negative"],
            ttm_owner_fcf=evaluated["owner_fcf"], roic_pct=evaluated["roic"],
            revenue_growth_pct=evaluated["rev_growth"])

    no_price = blocks["price"]["max"] == 0
    if veto.get("vetoed"):
        band, meaning = VETOED_BAND, veto.get("reason") or _BAND[VETOED_BAND]["meaning"]
        notes.append(f"Score suppressed — {meaning} (§4.3: vetoes suppress, never rank).")
        score, pct = None, None
    elif no_price:
        band, meaning = NO_PRICE_BAND, NO_PRICE_MEANING
        notes.append("No owner-FCF yield and no margin of safety: the Price block is empty, "
                     "so this is a quality profile and not a verdict (§4.1).")
    else:
        entry = _band_of(pct)
        band, meaning = entry["band"], entry["meaning"]

    if available_max < FULL_MAX:
        notes.append(f"{len(missing)} metric(s) not computable — scored out of "
                     f"{available_max} of {FULL_MAX} possible points (§4.2).")
    if veto.get("penalty"):
        notes.append(f"The percentile composite applies a {veto['penalty']} penalty here "
                     f"({veto.get('reason', '')}); the scorecard scores dilution directly "
                     f"in the share-count-trend metric instead.")
    notes.append(f"Differences under {NOISE_FLOOR:.0f} points are not meaningful (§4.4).")

    scored_ids = coverage["scored"]
    order = list(ANCHORS)
    if scored_ids:
        share = {m: metrics[m]["points"] / ANCHORS[m]["points"] for m in scored_ids}
        strongest = max(scored_ids,
                        key=lambda m: (share[m], ANCHORS[m]["points"], -order.index(m)))
        weakest = min(scored_ids,
                      key=lambda m: (share[m], -ANCHORS[m]["points"], order.index(m)))
        why = {"strongest": _why_entry(strongest, metrics[strongest], "carried by"),
               "weakest": _why_entry(weakest, metrics[weakest], "held back by")}
    else:
        why = {"strongest": None, "weakest": None}

    card = {"score": score, "available_max": available_max, "pct": pct, "band": band,
            "band_meaning": meaning, "blocks": blocks, "metrics": metrics, "why": why,
            "evidence": evidence_tier(available_max), "consensus": None, "coverage": coverage,
            "veto": {"vetoed": bool(veto.get("vetoed")), "reason": veto.get("reason", ""),
                     "penalty": veto.get("penalty", 0)},
            "notes": notes}
    if inversion_result is not None:
        card["inversion"] = _inversion_card(inversion_result)
        # Before the noise-floor line, which stays last, and stating the separation §2
        # insists on: the verdict sits beside the score and buys or costs no points.
        notes.insert(-1, f"Inversion verdict: {card['inversion']['verdict']} — Munger's "
                         f"lens sits BESIDE the score and moves none of its points "
                         f"(INVERSION-DESIGN §2).")
    card["consensus"] = consensus(card, mos, buffett, inversion_result=inversion_result)
    return card


def consensus(card: dict, mos: dict | None, buffett: dict | None, *,
              inversion_result: dict | None = None) -> dict:
    """§5 consensus — how many INDEPENDENT lenses call the name good: the scorecard (>= 60%
    of its available points), the DCF margin of safety (> 0), the 13-point Buffett checklist
    (>= 9) and, when an inversion result is supplied, survival (INVERSION-DESIGN §5). All of
    them agreeing is the real signal.

    The first three all ask "is this good?"; the fourth asks "will it survive?" — the
    question the other three share a blind spot on — and it is present only when the
    inversion layer had the data to answer. `of` is therefore the number of lenses actually
    consulted, three or four, and both are honest numbers rather than one being a truncated
    version of the other.

    A lens with no data is None: it never counts as green, never counts as a silent red and
    never shrinks the denominator, and the label says how many are unknown. That holds for
    the survival lens too — an Unknown verdict is a consulted-but-unknown fourth lens, which
    is not the same thing as no fourth lens. A NO PRICE card has no scorecard lens at all
    (§4.1); a VETOED card's scorecard lens is a definite no, not an unknown."""
    band, pct = card.get("band"), card.get("pct")
    if band == VETOED_BAND:
        scorecard_lens, scorecard_note = False, card.get("band_meaning", "vetoed")
    elif band == NO_PRICE_BAND or pct is None:
        scorecard_lens, scorecard_note = None, "no price — the scorecard has no verdict"
    else:
        scorecard_lens = pct >= CONSENSUS_SCORECARD_PCT
        scorecard_note = f"scorecard {pct}% (>= {CONSENSUS_SCORECARD_PCT:.0f}%)"

    mos_pct = None if not mos else mos.get("mos_pct")
    mos_lens = None if mos_pct is None else mos_pct > 0
    mos_note = ("no DCF margin of safety" if mos_pct is None
                else f"margin of safety {100.0 * mos_pct:+.0f}% (> 0%)")

    score = None if not buffett else buffett.get("score")
    buffett_lens = None if score is None else score >= CONSENSUS_BUFFETT_SCORE
    buffett_note = ("no Buffett checklist" if score is None
                    else f"Buffett {score}/{buffett.get('max', 13)} "
                         f"(>= {CONSENSUS_BUFFETT_SCORE})")

    lenses = {"scorecard": scorecard_lens, "margin_of_safety": mos_lens,
              "buffett": buffett_lens}
    evidence = {"scorecard": scorecard_note, "margin_of_safety": mos_note,
                "buffett": buffett_note}
    if inversion_result is not None:
        lenses[CONSENSUS_SURVIVAL_LENS] = survival_lens(inversion_result)
        evidence[CONSENSUS_SURVIVAL_LENS] = _survival_note(inversion_result)

    green = sum(1 for lens in lenses.values() if lens is True)
    unknown = sum(1 for lens in lenses.values() if lens is None)
    of = len(lenses)
    if green == of:
        label = f"{green} of {of} — all {_LENS_COUNT_WORD.get(of, of)} lenses agree"
    else:
        label = f"{green} of {of}" + (f" ({unknown} unknown)" if unknown else "")
    return {"green": green, "of": of, "lenses": lenses, "label": label,
            "evidence": evidence}
