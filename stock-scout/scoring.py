"""stock-scout decision layer — the shared pure core (RECONSTRUCTION.md §4).

grade.py (live yfinance cache) and backtest*.py (EDGAR point-in-time) both feed
score_universe() the same Bundle (§4.1) and must get bit-identical scores (§1 msg 44).
No I/O, no clock, no network. Percentile machinery, veto layer, composite weights and
tiering are semantically identical to vendor/scout_grade.py; the v2.1-v2.3 amendments
(own EV, TTM assembly, cash-flow-quality/dilution vetoes, flags, shadow layers) and the
frozen v3 owner-mode constants follow §4.2-§4.8.
"""
from __future__ import annotations

import math
import statistics
from datetime import date

from scipy.stats import percentileofscore

# --- Composite / grading constants (§4.6 — identical to vendor/scout_grade.py) ----------
W_V, W_Q, W_G, W_D, W_M = 0.25, 0.25, 0.20, 0.15, 0.15
_GRADE_BANDS = ((80.0, "A"), (65.0, "B"), (50.0, "C"), (35.0, "D"))
QV_ROIC_MIN = 0.15          # the >15% ROIC reference line, as a ratio (vendored RF4)
NEUTRAL_G = 50.0            # G degrades to neutral 50 when both growth legs are missing
ROIC_CAP_PCT = 1000.0       # §4.3 v2.2 — ROIC capped at 1000%

# --- Veto / penalty constants (§4.4) -----------------------------------------------------
NET_DEBT_EBITDA_VETO = 4.0          # leverage veto floor
CASH_FLOW_QUALITY_VETO = 0.25       # credit-loss add-backs >= 25% of positive TTM OCF
DILUTION_VETO_PCT = 20.0            # share CAGR > 20%/yr -> hard veto (v2.2)
DILUTION_PENALTY_PCT = 5.0          # 5-20%/yr -> -15 penalty
DILUTION_PENALTY = -15

# --- Flag thresholds (§4.5) --------------------------------------------------------------
EV_GAP_THRESHOLD_PCT = 15.0         # |own EV - Yahoo EV| / own EV
SHARE_CLASS_NCI_PCT = 10.0          # NCI / total equity, needed TOGETHER with the EV gap
FLOAT_DEFERRED_PCT = 30.0           # deferred revenue / TTM revenue
LOW_BASE_FRACTION = 0.02            # base-year owner-FCF < 2% of that year's revenue

# --- v3 owner-mode constants (§4.7 — frozen) ---------------------------------------------
W_QUALITY = {"q": 0.40, "g": 0.25, "d": 0.20, "m": 0.15}
GATE_V_PCTL = 20.0
PERSISTENCE_QUARTERS = 2
EXIT_RANK = 40
EXIT_V_PCTL = 5.0
SLOTS = 15

# --- Proposal-portfolio limits (§4.8, ai-hedge-fund limits.py) ---------------------------
GROSS_TARGET = 1.0
MAX_POSITION_PCT = 0.10
MAX_GROSS_EXPOSURE = 1.0

# --- Row-label fallback chains (§4.1 — first present wins) -------------------------------
_CHAINS = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "ebit": ("EBIT", "Operating Income"),
    "net_income": ("Net Income",),
    "ni_incl_nci": ("Net Income Including Noncontrolling Interests",
                    "Net Income Continuous Operations", "Net Income"),
    "gross_profit": ("Gross Profit",),
    "operating_income": ("Operating Income", "EBIT"),
    "interest_expense": ("Interest Expense",),   # WACC cost-of-debt input (§4.8)
    "total_debt": ("Total Debt",),
    "cash": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
    "working_capital": ("Working Capital",),
    "total_assets": ("Total Assets",),
    "current_assets": ("Current Assets",),
    "current_liabilities": ("Current Liabilities",),
    "equity": ("Stockholders Equity", "Common Stock Equity"),
    "nci": ("Minority Interest",),
    "ocf": ("Operating Cash Flow",),
    "capex": ("Capital Expenditure",),
    "sbc": ("Stock Based Compensation",),
    "da": ("Depreciation And Amortization", "Depreciation Amortization Depletion"),
}

# §4.1 credit-loss / write-off add-backs — summed when present (v2.2 cash-flow-quality veto)
_CREDIT_LOSS_ROWS = (
    "Provision For Doubtful Accounts",
    "Provisionand Write Offof Assets",
    "Change In Loss Reserves",
    "Provision For Loan Lease And Other Losses",
    "Allowance For Funds Used During Construction",
)


def _num(x) -> float | None:
    """None/NaN guard -> float | None (§3.2 NaN -> null; None never reaches a percentile)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _row(payload: dict, key: str) -> float | None:
    """First present (non-None/NaN) value along the §4.1 fallback chain for `key`."""
    for label in _CHAINS[key]:
        v = _num(payload.get(label))
        if v is not None:
            return v
    return None


def _deferred_revenue(bal: dict) -> float | None:
    """§4.1 deferred-revenue chain: Current (+ Non Current when present) -> Deferred Revenue."""
    cur = _num(bal.get("Current Deferred Revenue"))
    if cur is not None:
        return cur + (_num(bal.get("Non Current Deferred Revenue")) or 0.0)
    return _num(bal.get("Deferred Revenue"))


def _owner_fcf(cell: dict) -> float | None:
    """§4.2 per-period normalized owner-FCF: OCF - min(|CapEx|, D&A) - SBC; D&A absent ->
    maintenance proxy = |CapEx| (vendored scout_grade lines 34-76). None when OCF/CapEx missing."""
    ocf = _row(cell, "ocf")
    capex = _row(cell, "capex")
    if ocf is None or capex is None:
        return None
    capex_abs = abs(capex)
    da = _row(cell, "da")
    maint = min(capex_abs, da) if da is not None else capex_abs
    return ocf - maint - (_row(cell, "sbc") or 0.0)


def _credit_loss(cell: dict) -> float:
    """Sum of the §4.1 credit-loss add-back rows present in a cashflow period (absent -> 0)."""
    return sum(v for r in _CREDIT_LOSS_ROWS if (v := _num(cell.get(r))) is not None)


def _years(d0: str, d1: str) -> float:
    """Calendar span in years between two ISO dates, floored at 1e-9 (vendored guard)."""
    return max((date.fromisoformat(d1) - date.fromisoformat(d0)).days / 365.25, 1e-9)


def _cagr_pct(d0: str, v0: float, d1: str, v1: float) -> float:
    """Annualized growth %/yr from (d0, v0) to (d1, v1); both values must be positive."""
    return 100.0 * ((v1 / v0) ** (1.0 / _years(d0, d1)) - 1.0)


# --- TTM assembly (§4.2) -----------------------------------------------------------------

def assemble_ttm(bundle: dict) -> dict:
    """§4.2 TTM assembly over ONE aligned window: the newest 4 period_ends present in BOTH
    the quarterly income and cashflow statements (the intersection), each carrying the
    needed rows (revenue on income, OCF+CapEx on cashflow) -> sum over exactly those
    periods, basis "quarterly"; fewer than 4 common periods -> the newest annual period as
    proxy, basis "annual". Balance-sheet items stay latest-period (_latest_balance).
    Summing both statements over the same 12 months is what keeps accrual divergence,
    owner-FCF/revenue and SBC/revenue on comparable windows when Yahoo's newest income and
    cashflow quarters differ. Each summed item is None when a required row is missing in
    any summed period (integrity — never a partial TTM); SBC and credit-loss default 0.
    `periods` reports the window that was actually summed (ascending)."""
    quarterly = bundle.get("quarterly") or {}
    annual = bundle.get("annual") or {}
    q_inc = quarterly.get("income") or {}
    q_cf = quarterly.get("cashflow") or {}
    common = sorted(set(q_inc) & set(q_cf), reverse=True)[:4]
    quarterly_ok = (
        len(common) == 4
        and all(_row(q_inc[p], "revenue") is not None for p in common)
        and all(_row(q_cf[p], "ocf") is not None and _row(q_cf[p], "capex") is not None
                for p in common))
    if quarterly_ok:
        basis, quarters = "quarterly", 4
        inc_src, cf_src, inc_periods, cf_periods = q_inc, q_cf, common, common
    else:
        basis, quarters = "annual", 1
        inc_src = annual.get("income") or {}
        cf_src = annual.get("cashflow") or {}
        inc_periods = sorted(inc_src, reverse=True)[:1]
        cf_periods = sorted(cf_src, reverse=True)[:1]

    def isum(key: str) -> float | None:
        vals = [_row(inc_src[p], key) for p in inc_periods]
        return sum(vals) if vals and None not in vals else None

    owner = [_owner_fcf(cf_src[p]) for p in cf_periods]
    ocf = [_row(cf_src[p], "ocf") for p in cf_periods]
    capex = [_row(cf_src[p], "capex") for p in cf_periods]
    used = sorted(set(inc_periods) | set(cf_periods))
    return {
        "basis": basis, "quarters": quarters, "through": max(used) if used else None,
        "periods": used,
        # Registry v2 (additive): the EXACT per-statement windows this TTM summed, so a
        # consumer summing supplement flows uses the same periods instead of re-deriving
        # a window that could drift from this one.
        "inc_periods": list(inc_periods), "cf_periods": list(cf_periods),
        "revenue": isum("revenue"), "ebit": isum("ebit"), "ebitda": isum("ebitda"),
        "gross_profit": isum("gross_profit"), "ni_incl_nci": isum("ni_incl_nci"),
        "interest_expense": isum("interest_expense"),
        "ocf": sum(ocf) if ocf and None not in ocf else None,
        # Registry v2 (additive): GROSS capex over the same window. Deliberately not
        # derivable from owner_fcf, which subtracts min(|capex|, D&A) + SBC — a
        # "capex" reconstructed from that difference is maintenance-capex-plus-SBC
        # wearing the wrong name.
        "capex": (abs(sum(capex)) if capex and None not in capex else None),
        "sbc": sum(_row(cf_src[p], "sbc") or 0.0 for p in cf_periods) if cf_periods else None,
        "owner_fcf": sum(owner) if owner and None not in owner else None,
        "credit_loss": sum(_credit_loss(cf_src[p]) for p in cf_periods) if cf_periods else None,
    }


def _latest_balance(bundle: dict) -> dict:
    """Newest balance payload, quarterly preferred over annual (v2.2 TTM currency of data)."""
    for scope in ("quarterly", "annual"):
        bal = (bundle.get(scope) or {}).get("balance") or {}
        if bal:
            return bal[max(bal)]
    return {}


# --- Annual series (§4.2: growth CAGRs and cash-destruction stay on the annual basis) ----

def _annual_owner_fcf_points(bundle: dict) -> list[tuple[str, float]]:
    """Ascending (period_end, normalized owner-FCF) over the annual cashflow; periods with
    missing OCF/CapEx are dropped (never a silent zero)."""
    cf = (bundle.get("annual") or {}).get("cashflow") or {}
    out = []
    for pe in sorted(cf):
        v = _owner_fcf(cf[pe])
        if v is not None:
            out.append((pe, v))
    return out


def _annual_all_negative(bundle: dict) -> bool:
    """§4.2 cash-destruction input: normalized owner-FCF < 0 in EVERY available annual
    period (empty series -> False, mirroring the vendored grader)."""
    pts = _annual_owner_fcf_points(bundle)
    return bool(pts) and all(v < 0 for _, v in pts)


def _annual_revenue_points(bundle: dict) -> list[tuple[str, float]]:
    """Ascending (period_end, revenue) over the annual income; only positive revenues."""
    inc = (bundle.get("annual") or {}).get("income") or {}
    return [(pe, r) for pe in sorted(inc) if (r := _row(inc[pe], "revenue")) is not None and r > 0]


def _revenue_growth(bundle: dict) -> tuple[float | None, str]:
    """§4.3 G — annual revenue CAGR %/yr, oldest usable -> newest usable, annualized by the
    actual calendar span. None with <2 usable periods."""
    pts = _annual_revenue_points(bundle)
    if len(pts) < 2:
        return None, "not computable: <2 usable annual revenue periods"
    (d0, v0), (d1, v1) = pts[0], pts[-1]
    return _cagr_pct(d0, v0, d1, v1), f"annual revenue CAGR {d0} -> {d1}"


def _split_factor(splits: dict, pe: str) -> float:
    """Cumulative split ratio applied strictly AFTER `pe` (no later split -> 1.0).
    Non-numeric/non-positive ratios are ignored — a corrupt cache entry must not
    silently rescale a share series."""
    factor = 1.0
    for day, raw in (splits or {}).items():
        ratio = _num(raw)
        if ratio is not None and ratio > 0 and str(day) > pe:
            factor *= ratio
    return factor


def adjusted_shares_series(bundle: dict) -> list[tuple[str, float]]:
    """§4.1 `shares_series` restated in TODAY's share terms: every observation is scaled by
    the cumulative split ratio applied after its date, so a 2:1 split reads as ~0%/yr
    instead of +100%/yr dilution. Raw Yahoo share counts are point-in-time and split-
    UNadjusted; without this the §4.4 >20%/yr hard veto fires on any recent splitter for a
    year and the per-share owner-FCF CAGR flips deeply negative. `splits` absent (older
    cache entries, PIT bundles) -> the series passes through unchanged. Ascending,
    non-positive/unparsable observations dropped."""
    splits = bundle.get("splits") or {}
    out = []
    for day, raw in bundle.get("shares_series") or []:
        value = _num(raw)
        if value is None or value <= 0:
            continue
        out.append((str(day), value * _split_factor(splits, str(day))))
    return sorted(out)


def _shares_at(shares_series: list, pe: str) -> float | None:
    """Last share observation dated at or before `pe` from the ascending §4.1 series."""
    best = None
    for d, v in shares_series or []:
        val = _num(v)
        if val is not None and val > 0 and d <= pe:
            best = val
    return best


def _per_share_ofcf_growth(bundle: dict) -> tuple[float | None, str, bool]:
    """§4.3 G — annual per-share owner-FCF CAGR %/yr -> (cagr, note, low_base_flag).
    The leg is DROPPED (None + LOW_BASE flag) when the base-year owner-FCF is < 2% of that
    year's revenue (§4.5 v2.1 item 4); non-positive endpoints are not computable (no flag).
    Share counts are SPLIT-ADJUSTED first (adjusted_shares_series) — otherwise a split
    would show up as a per-share collapse."""
    shares = adjusted_shares_series(bundle)
    pts = []
    for pe, ofcf in _annual_owner_fcf_points(bundle):
        sh = _shares_at(shares, pe)
        if sh is not None:
            pts.append((pe, ofcf, ofcf / sh))
    if len(pts) < 2:
        return None, "not computable: <2 usable annual per-share owner-FCF points", False
    (base_pe, base_ofcf, base_ps), (new_pe, _, new_ps) = pts[0], pts[-1]
    if base_ps <= 0 or new_ps <= 0:
        return None, "not computable: non-positive owner-FCF endpoint", False
    inc = (bundle.get("annual") or {}).get("income") or {}
    base_rev = _row(inc.get(base_pe, {}), "revenue")
    if base_rev is not None and base_rev > 0 and base_ofcf < LOW_BASE_FRACTION * base_rev:
        return None, "dropped: LOW_BASE — base-year owner-FCF < 2% of that year's revenue", True
    return _cagr_pct(base_pe, base_ps, new_pe, new_ps), \
        f"annual per-share owner-FCF CAGR {base_pe} -> {new_pe}", False


def _share_trend_pct(shares_series: list) -> float | None:
    """§4.3 M — share-count trend %/yr: newest observation vs the one at-or-before a year
    prior (fallback: oldest), annualized by the actual span. None with <2 usable
    observations or a span under ~3 months (annualizing noise). Callers pass the
    SPLIT-ADJUSTED series (adjusted_shares_series) — a raw series reads a split as
    dilution.

    Freshness is NOT checked here: the series' age against `as_of` is knowable only to the
    data layer, which stamps `shares_series_stale` on the bundle. `_evaluate` refuses on
    that flag before calling this, so a decade-old series never reaches the arithmetic."""
    ser = sorted((d, v) for d, raw in shares_series or []
                 if (v := _num(raw)) is not None and v > 0)
    if len(ser) < 2:
        return None
    d1, v1 = ser[-1]
    target = date.fromisoformat(d1).toordinal() - 365
    prior = [p for p in ser[:-1] if date.fromisoformat(p[0]).toordinal() <= target]
    d0, v0 = prior[-1] if prior else ser[0]
    if _years(d0, d1) < 0.25:
        return None
    return 100.0 * ((v1 / v0) ** (1.0 / _years(d0, d1)) - 1.0)


def _roic_pct(ttm_ebit: float | None, bal: dict) -> tuple[float | None, bool]:
    """§4.3 Q — Greenblatt ROIC: TTM EBIT / (Working Capital + (Total Assets - Current
    Assets - Cash)), capped at 1000% -> (roic_pct, capped_flag).

    A non-positive denominator returns the cap WITH the ROIC_CAPPED flag (v2.2) ONLY when
    TTM EBIT is positive — that is the genuinely capital-light / float-financed case
    (the msg-23 Adobe catch). EBIT <= 0 over a non-positive capital base is not a 1000%
    return on capital: the leg suspends (None), which also denies it the ROIC floor
    factor, top-of-cohort Q/G credit and the §4.4 reinvestor carve-out."""
    wc, ta = _row(bal, "working_capital"), _row(bal, "total_assets")
    ca, cash = _row(bal, "current_assets"), _row(bal, "cash")
    if None in (ttm_ebit, wc, ta, ca, cash):
        return None, False
    denom = wc + (ta - ca - cash)
    if denom <= 0:
        return (ROIC_CAP_PCT, True) if ttm_ebit > 0 else (None, False)
    return min(ROIC_CAP_PCT, 100.0 * ttm_ebit / denom), False


def _gross_margin_cv(bundle: dict) -> float:
    """Coefficient of variation of the annual gross-margin series (stability ingredient of
    the single §4.3 Q gross-margin leg); <2 usable periods -> 0.0 (no evidence of drift)."""
    inc = (bundle.get("annual") or {}).get("income") or {}
    gm = []
    for pe in sorted(inc):
        gp, rev = _row(inc[pe], "gross_profit"), _row(inc[pe], "revenue")
        if gp is not None and rev:
            gm.append(gp / rev)
    if len(gm) < 2:
        return 0.0
    mean = sum(gm) / len(gm)
    return (statistics.pstdev(gm) / mean) if mean else 0.0


# --- Veto / penalty layer (§4.4 — evaluated before scoring) ------------------------------

def veto_check(*, net_debt_to_ebitda, ebitda, net_debt, credit_loss, ocf,
               share_trend_pct, share_class, annual_all_negative, ttm_owner_fcf,
               roic_pct, revenue_growth_pct) -> tuple[dict, bool]:
    """§4.4 veto/penalty order -> ({vetoed, penalty, reason}, reinvestor_spared).

    1. leverage: net debt/EBITDA > 4 (TTM) or EBITDA <= 0 with net debt > 0;
    2. cash-flow quality: credit-loss add-backs >= 25% of positive TTM OCF;
    3. dilution hard veto: share CAGR > 20%/yr — suppressed when SHARE_CLASS is set, the
       same §4.5 verdict that already forces the M leg to neutral 50 and switches the
       penalty off: a trend the system just declared untrustworthy cannot hard-veto;
    4. cash destruction: owner-FCF negative every annual period AND TTM <= 0 (a recovered
       burner escapes); reinvestor carve-out (ROIC > 15% and revenue growth > 10%/yr) is
       spared and flagged, never vetoed (an unusable ROIC — None — never qualifies);
    5. dilution penalty: 5-20%/yr -> -15, suppressed when SHARE_CLASS (§4.5)."""
    if net_debt_to_ebitda is not None and net_debt_to_ebitda > NET_DEBT_EBITDA_VETO:
        return {"vetoed": True, "penalty": 0,
                "reason": f"leverage veto: net debt/EBITDA {net_debt_to_ebitda:.1f} > 4.0"}, False
    if ebitda is not None and ebitda <= 0 and net_debt is not None and net_debt > 0:
        return {"vetoed": True, "penalty": 0,
                "reason": "leverage veto: EBITDA <= 0 while carrying net debt"}, False
    if ocf is not None and ocf > 0 and credit_loss is not None \
            and credit_loss / ocf >= CASH_FLOW_QUALITY_VETO:
        return {"vetoed": True, "penalty": 0,
                "reason": f"cash-flow quality: OCF leans {100.0 * credit_loss / ocf:.0f}% "
                          f"on credit-loss/write-off add-backs"}, False
    if share_trend_pct is not None and not share_class \
            and share_trend_pct > DILUTION_VETO_PCT:
        return {"vetoed": True, "penalty": 0,
                "reason": f"dilution veto: shares +{share_trend_pct:.1f}%/yr (>20%/yr)"}, False
    if annual_all_negative and ttm_owner_fcf is not None and ttm_owner_fcf <= 0:
        if roic_pct is not None and roic_pct > 100.0 * QV_ROIC_MIN \
                and revenue_growth_pct is not None and revenue_growth_pct > 10.0:
            return {"vetoed": False, "penalty": 0,
                    "reason": f"flagged — owner-FCF negative every period, spared as a "
                              f"reinvestor (ROIC {roic_pct:.0f}% > 15%, revenue growth "
                              f"{revenue_growth_pct:.0f}%/yr > 10%)"}, True
        return {"vetoed": True, "penalty": 0,
                "reason": "cash-destruction veto: owner-FCF negative every annual period "
                          "and TTM <= 0"}, False
    if share_trend_pct is not None and not share_class \
            and DILUTION_PENALTY_PCT < share_trend_pct <= DILUTION_VETO_PCT:
        return {"vetoed": False, "penalty": DILUTION_PENALTY,
                "reason": f"dilution penalty: shares +{share_trend_pct:.1f}%/yr"}, False
    return {"vetoed": False, "penalty": 0, "reason": ""}, False


# --- Sector-percentile scoring (§4.6 — verbatim vendored semantics) ----------------------

def sector_percentile(value: float, cohort, *, higher_better: bool) -> float:
    """Cross-sectional percentile of `value` in its sector cohort; None/NaN members dropped;
    a singleton (or all-missing) cohort scores 50.0 neutral; lower-better inverts."""
    clean = [float(x) for x in cohort
             if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(clean) <= 1:
        return 50.0
    p = float(percentileofscore(clean, float(value), kind="mean"))
    return p if higher_better else 100.0 - p


def _leg_pct(value: float, cohort, *, higher_better: bool) -> tuple[float, int]:
    """sector_percentile plus the clean cohort size (the §3.3 legs[].cohort_n field)."""
    clean = [float(x) for x in cohort
             if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return sector_percentile(value, clean, higher_better=higher_better), len(clean)


def _roic_floor_factor(roic_pct: float) -> float:
    """The absolute >15% ROIC reference line as a leg discount: min(1, ROIC/15%) (RF4)."""
    return max(0.0, min(1.0, roic_pct / (100.0 * QV_ROIC_MIN)))


def pillar_score(legs) -> float | None:
    """Equal-weighted mean of the present leg scores; None when all missing (never a 0)."""
    present = [x for x in legs if x is not None]
    return sum(present) / len(present) if present else None


def composite(*, v: float, q: float, g: float, d: float, m: float, penalty: int) -> float:
    """§4.6 composite 0.25/0.25/0.20/0.15/0.15 + penalty, floored at 0, capped at 100."""
    raw = W_V * v + W_Q * q + W_G * g + W_D * d + W_M * m + penalty
    return max(0.0, min(100.0, round(raw, 4)))


def grade_letter(comp: float) -> str:
    """A/B/C/D/F per the §4.6 bands (>=80 A / >=65 B / >=50 C / >=35 D / F)."""
    for lo, letter in _GRADE_BANDS:
        if comp >= lo:
            return letter
    return "F"


def quality_score(*, q: float, g: float, d: float, m: float) -> float:
    """§4.7 v3 quality engine B = 0.40*Q + 0.25*G + 0.20*D + 0.15*M (price/V excluded)."""
    return round(W_QUALITY["q"] * q + W_QUALITY["g"] * g
                 + W_QUALITY["d"] * d + W_QUALITY["m"] * m, 4)


# --- Circle-of-competence tiering (vendored scout_grade tier_of, RF10 sets) --------------
_CORE_INDUSTRIES = frozenset({"software", "health care technology"})
_ADJACENT_INDUSTRIES = frozenset({
    "it services", "semiconductors & semiconductor equipment",
    "health care equipment & supplies", "life sciences tools & services",
    "interactive media & services", "capital markets",
})


def tier_of(*, sector, industry) -> str:
    """Core / Adjacent / Outside — exact-match on the FinanceDatabase industry categorical,
    case-insensitive; None/unknown -> Outside. Orthogonal to grade, never blended."""
    ind = (industry or "").strip().lower()
    if ind in _CORE_INDUSTRIES:
        return "Core"
    if ind in _ADJACENT_INDUSTRIES:
        return "Adjacent"
    return "Outside"


# --- Per-bundle metric assembly (§4.1-§4.5) ----------------------------------------------

_REQUIRED = (        # §4.6 integrity-suspend order, mirroring the vendored grader (RF5)
    ("v_yield", "owner-FCF yield (EV <= 0 or not computable)"),
    ("roic", "ROIC"),
    ("gm_level", "gross-margin level"),
    ("ofcf_margin", "owner-FCF margin"),
    ("nd2e", "net debt/EBITDA"),
    ("sbc_pct", "SBC/revenue"),
    ("accrual", "accrual divergence"),
)


def _evaluate(bundle: dict) -> dict:
    """Phase-1 assembly for one Bundle: TTM, own EV, raw pillar metrics, flags (§4.5,
    REINVESTOR excepted — that is a veto-path outcome) and the first missing required
    metric (§4.6 integrity-suspend reason)."""
    ttm = assemble_ttm(bundle)
    bal = _latest_balance(bundle)
    mcap = _num(bundle.get("market_cap"))
    yahoo_ev = _num(bundle.get("yahoo_ev"))
    price = _num(bundle.get("price"))
    shares_adj = adjusted_shares_series(bundle)
    latest_shares = shares_adj[-1][1] if shares_adj else None
    debt, cash = _row(bal, "total_debt"), _row(bal, "cash")

    own_ev = mcap + debt - cash if None not in (mcap, debt, cash) else None
    # Reference EV for the §4.5 gap. yfinance's FastInfo carries no enterprise value and
    # the `info`/quoteSummary path is banned (and blocked here), so `yahoo_ev` is None in
    # live runs — which used to make EV_GAP and SHARE_CLASS structurally dead. The Up-C
    # signal those flags were built on IS a share-count mismatch: the quoted market cap
    # counts ALL units, while get_shares_full reports the registrant's listed class. So
    # when no EV field is supplied, rebuild the listed-class reference EV from the cache
    # itself: price x latest listed shares + debt - cash. A single-class company has
    # implied units ~= reported shares -> gap ~0 -> no flag (Tenet's 41% NCI stays silent);
    # an Up-C shows a positive gap. An explicitly supplied yahoo_ev always wins.
    ref_ev, ev_source = yahoo_ev, ("field" if yahoo_ev is not None else None)
    if ref_ev is None and price is not None and price > 0 \
            and None not in (latest_shares, debt, cash):
        ref_ev, ev_source = price * latest_shares + debt - cash, "derived"
    gap_pct = (100.0 * (own_ev - ref_ev) / own_ev
               if own_ev is not None and own_ev > 0 and ref_ev is not None else None)
    net_debt = debt - cash if None not in (debt, cash) else None

    owner_fcf, rev = ttm["owner_fcf"], ttm["revenue"]
    v_yield = (owner_fcf / own_ev
               if owner_fcf is not None and own_ev is not None and own_ev > 0 else None)
    p_ofcf = (mcap / owner_fcf
              if mcap is not None and owner_fcf is not None and owner_fcf > 0 else None)

    roic, roic_capped = _roic_pct(ttm["ebit"], bal)
    gm_level = (100.0 * ttm["gross_profit"] / rev
                if ttm["gross_profit"] is not None and rev is not None and rev > 0 else None)
    gm_cv = _gross_margin_cv(bundle)
    # A missing revenue denominator is NOT a 0% margin. The vendored grader returned 0.0
    # here, and that sentinel is a lie with teeth now that monitor.py tests this metric
    # against pre-committed thresholds: a bundle with owner-FCF but no revenue would read
    # as the worst possible margin and trip a "< 12%" break trigger on a data gap.
    # Returning None routes it to the "not computable -> UNCHECKED" path instead, and
    # matches §4.7's rule that absent data shrinks a denominator rather than scoring zero.
    # Provably inert for the GRADE: this branch only fires when rev is None or <= 0, and
    # gm_level is None under exactly that condition and sits BEFORE ofcf_margin in
    # _REQUIRED — so the name already suspends as INSUFFICIENT with the same reason.
    ofcf_margin = (100.0 * owner_fcf / rev
                   if owner_fcf is not None and rev is not None and rev > 0 else None)

    rev_growth, rev_note = _revenue_growth(bundle)
    ps_growth, ps_note, low_base = _per_share_ofcf_growth(bundle)

    ebitda = ttm["ebitda"]
    # EBITDA exactly 0 leaves the ratio undefined (not a huge number): the name is handed
    # to the §4.4 leverage veto ("EBITDA <= 0 with net debt > 0") instead, which is why the
    # veto layer runs BEFORE the §4.6 integrity-suspend in score_universe.
    nd2e = (net_debt / ebitda
            if net_debt is not None and ebitda is not None and ebitda != 0 else None)
    sbc_pct = (100.0 * ttm["sbc"] / rev
               if ttm["sbc"] is not None and rev is not None and rev > 0 else None)

    # A share series that stopped years ago describes a company that no longer exists in
    # that shape; annualizing its last two points would report ancient dilution as current
    # (pit.as_of_bundle sets the flag, and owns the threshold).
    share_trend = None if bundle.get("shares_series_stale") else _share_trend_pct(shares_adj)
    accrual = (100.0 * (ttm["ni_incl_nci"] - ttm["ocf"]) / rev
               if None not in (ttm["ni_incl_nci"], ttm["ocf"])
               and rev is not None and rev > 0 else None)

    flags = []
    if gap_pct is not None and abs(gap_pct) > EV_GAP_THRESHOLD_PCT:
        source = ("derived reference EV (price x listed shares + debt - cash)"
                  if ev_source == "derived" else "Yahoo EV")
        flags.append({"code": "EV_GAP",
                      "message": f"own EV vs {source} gap {gap_pct:+.1f}% (>15%)"})
    equity, nci = _row(bal, "equity"), _row(bal, "nci")
    share_class = False
    if None not in (equity, nci) and equity + nci > 0:
        nci_pct = 100.0 * nci / (equity + nci)
        if nci_pct > SHARE_CLASS_NCI_PCT and gap_pct is not None \
                and abs(gap_pct) > EV_GAP_THRESHOLD_PCT:
            share_class = True
            flags.append({"code": "SHARE_CLASS",
                          "message": f"NCI {nci_pct:.0f}% of total equity AND EV gap "
                                     f"{gap_pct:+.0f}% — share-trend leg neutral 50, "
                                     f"dilution penalty off"})
    deferred = _deferred_revenue(bal)
    if deferred is not None and rev is not None and rev > 0 \
            and 100.0 * deferred / rev > FLOAT_DEFERRED_PCT:
        flags.append({"code": "FLOAT_ROIC",
                      "message": f"ROIC float-driven: deferred revenue "
                                 f"{100.0 * deferred / rev:.0f}% of TTM revenue (>30%)"})
    if low_base:
        flags.append({"code": "LOW_BASE",
                      "message": "per-share owner-FCF CAGR dropped: base-year owner-FCF "
                                 "< 2% of that year's revenue"})
    if roic_capped:
        flags.append({"code": "ROIC_CAPPED",
                      "message": "capital base <= 0 — ROIC capped at 1000%"})

    metrics = {
        "v_yield": v_yield, "p_ofcf": p_ofcf,
        "roic": roic, "gm_level": gm_level, "gm_cv": gm_cv, "ofcf_margin": ofcf_margin,
        "rev_growth": rev_growth, "rev_note": rev_note,
        "ps_growth": ps_growth, "ps_note": ps_note,
        "nd2e": nd2e, "owner_fcf": owner_fcf, "sbc_pct": sbc_pct,
        "share_trend": share_trend,
        "m_shares_cohort": None if share_class else share_trend,
        "accrual": accrual,
        "ebitda": ebitda, "net_debt": net_debt,
        "credit_loss": ttm["credit_loss"], "ocf": ttm["ocf"],
        "share_class": share_class,
        "annual_all_negative": _annual_all_negative(bundle),
        "own_ev": own_ev, "ref_ev": ref_ev, "ev_source": ev_source, "gap_pct": gap_pct,
        "flags": flags, "ttm": ttm,
    }
    metrics["required_gap"] = next(
        (label for key, label in _REQUIRED if metrics[key] is None), None)
    return metrics


# --- Batch scoring (§4.6 -> the §3.3 names[] element) ------------------------------------

# Phase-1 assembly is PUBLIC API: scorecard.py builds its absolute card from exactly the raw
# metrics that produced this row's leg values, so the two layers agree by construction rather
# than by coincidence. Renaming or reshaping _evaluate's return breaks that contract.
evaluate = _evaluate


def score_universe(bundles: list[dict]) -> list[dict]:
    """§4.6 two-phase pass over §4.1 Bundles -> §3.3 names[] dicts, universe order
    preserved. Phase 1: metrics + flags, then the §4.4 veto layer (VETOED suppressed,
    never ranked) and only afterwards the integrity-suspend (INSUFFICIENT, reason in
    `note`) — §4.4 vetoes are bundle facts, so a name whose EBITDA is 0 while it carries
    net debt must be VETOED on the leverage rule rather than suspended for the ratio that
    same 0 makes uncomputable. Phase 2: sector-percentile legs, pillars, composite/grade
    and the §4.7 v3 quality_score for every graded name."""
    order, results, surv = [], {}, {}
    for b in bundles:
        sym = b["symbol"]
        order.append(sym)
        e = _evaluate(b)
        row = {
            "symbol": sym, "name": b.get("name"), "sector": b.get("sector"),
            "industry": b.get("industry"),
            "tier": tier_of(sector=b.get("sector"), industry=b.get("industry")),
            "grade": None, "composite": None, "quality_score": None,
            "pillars": {"v": None, "q": None, "g": None, "d": None, "m": None},
            "legs": {},
            "veto": {"vetoed": False, "reason": "", "penalty": 0},
            "flags": e["flags"],
            "ev": {"own": e["own_ev"], "yahoo": e["ref_ev"], "gap_pct": e["gap_pct"],
                   "yahoo_source": e["ev_source"]},
            "ttm": {"quarters": e["ttm"]["quarters"], "through": e["ttm"]["through"],
                    "basis": e["ttm"]["basis"]},
            "note": "",
        }
        veto, reinvestor = veto_check(
            net_debt_to_ebitda=e["nd2e"], ebitda=e["ebitda"], net_debt=e["net_debt"],
            credit_loss=e["credit_loss"], ocf=e["ocf"],
            share_trend_pct=e["share_trend"], share_class=e["share_class"],
            annual_all_negative=e["annual_all_negative"], ttm_owner_fcf=e["owner_fcf"],
            roic_pct=e["roic"], revenue_growth_pct=e["rev_growth"])
        if veto["vetoed"]:                       # §4.4 before §4.6: a veto is a bundle fact
            row["veto"] = veto
            row["note"] = veto["reason"]
            row["grade"] = "VETOED"
            results[sym] = row
            continue
        if e["required_gap"] is not None:        # not vetoed -> can it be scored at all?
            row["grade"] = "INSUFFICIENT"
            row["note"] = f"insufficient data: {e['required_gap']}"
            results[sym] = row
            continue
        row["veto"] = veto
        row["note"] = veto["reason"]
        if reinvestor:
            row["flags"] = e["flags"] + [{
                "code": "REINVESTOR",
                "message": "spared cash-destruction veto: ROIC > 15% and revenue "
                           "growth > 10%/yr — a caution, not a suppression"}]
        surv[sym] = (e, row)

    def cohort(sector, key):
        return [ev[key] for ev, r in surv.values() if r["sector"] == sector]

    for sym, (e, row) in surv.items():
        sec = row["sector"]
        legs = {}
        # V — owner-FCF yield on own EV (§4.3), P/owner-FCF as display companion.
        pct, n = _leg_pct(e["v_yield"], cohort(sec, "v_yield"), higher_better=True)
        legs["v_yield"] = {"raw": e["v_yield"], "percentile": pct, "cohort_n": n,
                           "score": round(pct, 6),
                           "note": f"P/owner-FCF {e['p_ofcf']:.1f}" if e["p_ofcf"] is not None
                                   else "P/owner-FCF n/a (owner-FCF <= 0)"}
        v = pillar_score([legs["v_yield"]["score"]])
        # Q — ROIC leg blends the sector percentile with the >15% floor (RF4).
        pct, n = _leg_pct(e["roic"], cohort(sec, "roic"), higher_better=True)
        factor = _roic_floor_factor(e["roic"])
        legs["q_roic"] = {"raw": e["roic"], "percentile": pct, "cohort_n": n,
                          "score": round(pct * factor, 6),
                          "note": "" if factor >= 1.0
                                  else f"ROIC floor factor {factor:.2f} (<15%)"}
        # Q — gross margin: ONE leg, level percentile x stability percentile/100 (RF8).
        lvl, n = _leg_pct(e["gm_level"], cohort(sec, "gm_level"), higher_better=True)
        stab, _ = _leg_pct(e["gm_cv"], cohort(sec, "gm_cv"), higher_better=False)
        legs["q_gm"] = {"raw": e["gm_level"], "percentile": lvl, "cohort_n": n,
                        "score": round(lvl * stab / 100.0, 6),
                        "note": f"level pctl {lvl:.0f} x stability pctl {stab:.0f} "
                                f"(CV {e['gm_cv']:.3f})"}
        pct, n = _leg_pct(e["ofcf_margin"], cohort(sec, "ofcf_margin"), higher_better=True)
        legs["q_ofcf_margin"] = {"raw": e["ofcf_margin"], "percentile": pct, "cohort_n": n,
                                 "score": round(pct, 6), "note": ""}
        q = pillar_score([legs["q_roic"]["score"], legs["q_gm"]["score"],
                          legs["q_ofcf_margin"]["score"]])
        # G — ROIC-gated growth legs (§4.3); both missing -> neutral 50, never punished.
        g_scores = []
        for leg_id, key, note_key in (("g_revenue", "rev_growth", "rev_note"),
                                      ("g_ps_ofcf", "ps_growth", "ps_note")):
            raw = e[key]
            if raw is None:
                legs[leg_id] = {"raw": None, "percentile": None, "cohort_n": 0,
                                "score": None, "note": e[note_key]}
                continue
            pct, n = _leg_pct(raw, cohort(sec, key), higher_better=True)
            score = round(pct * factor, 6)
            legs[leg_id] = {"raw": raw, "percentile": pct, "cohort_n": n,
                            "score": score, "note": e[note_key]}
            g_scores.append(score)
        g = pillar_score(g_scores)
        if g is None:
            g = NEUTRAL_G
        # D — net debt/EBITDA, self-funding 100/0, SBC/revenue (§4.3).
        pct, n = _leg_pct(e["nd2e"], cohort(sec, "nd2e"), higher_better=False)
        legs["d_net_debt"] = {"raw": e["nd2e"], "percentile": pct, "cohort_n": n,
                              "score": round(pct, 6), "note": ""}
        sf = 100.0 if e["owner_fcf"] > 0 else 0.0
        legs["d_self_funding"] = {"raw": e["owner_fcf"], "percentile": None, "cohort_n": 0,
                                  "score": sf,
                                  "note": "TTM owner-FCF positive" if sf else
                                          "TTM owner-FCF <= 0"}
        pct, n = _leg_pct(e["sbc_pct"], cohort(sec, "sbc_pct"), higher_better=False)
        legs["d_sbc"] = {"raw": e["sbc_pct"], "percentile": pct, "cohort_n": n,
                         "score": round(pct, 6), "note": ""}
        d = pillar_score([legs["d_net_debt"]["score"], legs["d_self_funding"]["score"],
                          legs["d_sbc"]["score"]])
        # M — share trend (neutral 50 under SHARE_CLASS, §4.5) + accruals incl. NCI.
        m_scores = []
        if e["share_class"]:
            legs["m_shares"] = {"raw": e["share_trend"], "percentile": None, "cohort_n": 0,
                                "score": 50.0,
                                "note": "SHARE_CLASS — leg neutral 50, dilution penalty off"}
            m_scores.append(50.0)
        elif e["share_trend"] is None:
            legs["m_shares"] = {"raw": None, "percentile": None, "cohort_n": 0,
                                "score": None,
                                "note": "no usable share-count series — leg suspended"}
        else:
            pct, n = _leg_pct(e["share_trend"], cohort(sec, "m_shares_cohort"),
                              higher_better=False)
            legs["m_shares"] = {"raw": e["share_trend"], "percentile": pct, "cohort_n": n,
                                "score": round(pct, 6), "note": ""}
            m_scores.append(legs["m_shares"]["score"])
        pct, n = _leg_pct(e["accrual"], cohort(sec, "accrual"), higher_better=False)
        legs["m_accruals"] = {"raw": e["accrual"], "percentile": pct, "cohort_n": n,
                              "score": round(pct, 6), "note": ""}
        m_scores.append(legs["m_accruals"]["score"])
        m = pillar_score(m_scores)

        comp = composite(v=v, q=q, g=g, d=d, m=m, penalty=row["veto"]["penalty"])
        row["legs"] = legs
        row["pillars"] = {"v": round(v, 1), "q": round(q, 1), "g": round(g, 1),
                          "d": round(d, 1), "m": round(m, 1)}
        row["composite"] = comp
        row["grade"] = grade_letter(comp)
        row["quality_score"] = quality_score(q=q, g=g, d=d, m=m)
        results[sym] = row
    return [results[s] for s in order]


# --- v2.3 shadow layers (§4.8 — never enter the composite) -------------------------------

def wacc_estimate(*, market_cap, total_debt, cash, interest_coverage=None) -> float:
    """§4.8 WACC per ai-hedge-fund calculate_wacc: CAPM cost of equity (rf 4.5%, beta 1.0,
    MRP 6%), cost of debt from interest coverage (default spread when unknown), 25% tax
    shield, clamped to [6%, 20%]."""
    rf, mrp = 0.045, 0.06
    coe = rf + 1.0 * mrp
    if interest_coverage is not None and interest_coverage > 0:
        cod = max(rf + 0.01, rf + 10.0 / interest_coverage)
    else:
        cod = rf + 0.05
    net_debt = max((total_debt or 0.0) - (cash or 0.0), 0.0)
    total_value = (market_cap or 0.0) + net_debt
    wacc = ((market_cap / total_value) * coe + (net_debt / total_value) * cod * 0.75
            if total_value > 0 else coe)
    return min(max(wacc, 0.06), 0.20)


def _fcf_volatility(history: list[float]) -> float:
    """ai-hedge-fund calculate_fcf_volatility: CV of the positive FCF history (sample
    stdev), capped at 1.0; defaults 0.5 (<3 points) / 0.8 (mostly negative)."""
    if len(history) < 3:
        return 0.5
    pos = [f for f in history if f > 0]
    if len(pos) < 2:
        return 0.8
    mean = statistics.mean(pos)
    if mean <= 0:
        return 0.8
    return min(statistics.stdev(pos) / mean, 1.0)


def dcf_intrinsic(base_fcf: float, growth: float, wacc: float) -> float:
    """§4.8 3-stage DCF present value (ai-hedge-fund calculate_enhanced_dcf_value, without
    the volatility quality factor): years 1-3 at `growth`, years 4-7 declining transition
    ((growth+3%)/2 fading to 0), terminal min(3%, 0.6*growth) (adjusted to 0.8*wacc when
    wacc <= terminal)."""
    transition = (growth + 0.03) / 2.0
    terminal = min(0.03, growth * 0.6)
    pv = 0.0
    for year in range(1, 4):
        pv += base_fcf * (1 + growth) ** year / (1 + wacc) ** year
    for year in range(4, 8):
        rate = transition * (8 - year) / 4.0
        pv += base_fcf * (1 + growth) ** 3 * (1 + rate) ** (year - 3) / (1 + wacc) ** year
    final = base_fcf * (1 + growth) ** 3 * (1 + transition) ** 4
    if wacc <= terminal:
        terminal = wacc * 0.8
    return pv + final * (1 + terminal) / (wacc - terminal) / (1 + wacc) ** 7


def margin_of_safety(bundle: dict) -> dict | None:
    """§4.8 shadow margin of safety — never scored. base FCF = max(TTM owner-FCF,
    0.85 x 3-yr average annual owner-FCF); growth = annual revenue CAGR capped at 25%
    (10% above $200B market cap; None/0 -> 5% default); intrinsic = 3-stage DCF x
    volatility quality factor max(0.7, 1 - 0.5*CV). None when market cap is unusable or
    base FCF <= 0. mos_pct = (intrinsic - market_cap) / market_cap."""
    mcap = _num(bundle.get("market_cap"))
    if mcap is None or mcap <= 0:
        return None
    ttm = assemble_ttm(bundle)
    hist = [v for _, v in reversed(_annual_owner_fcf_points(bundle))]   # newest first
    avg3 = sum(hist[:3]) / min(3, len(hist)) if hist else None
    candidates = [x for x in (ttm["owner_fcf"],
                              0.85 * avg3 if avg3 is not None else None) if x is not None]
    if not candidates:
        return None
    base = max(candidates)
    if base <= 0:
        return None
    growth_pct, _ = _revenue_growth(bundle)
    cap = 0.10 if mcap > 200e9 else 0.25
    growth = min(growth_pct / 100.0, cap) if growth_pct else 0.05
    bal = _latest_balance(bundle)
    ebit, interest = ttm["ebit"], ttm["interest_expense"]
    coverage = ebit / abs(interest) if ebit is not None and interest else None
    wacc = wacc_estimate(market_cap=mcap, total_debt=_row(bal, "total_debt"),
                         cash=_row(bal, "cash"), interest_coverage=coverage)
    quality = max(0.7, 1.0 - 0.5 * _fcf_volatility(hist))
    intrinsic = dcf_intrinsic(base, growth, wacc) * quality
    return {"intrinsic_value": intrinsic, "market_cap": mcap,
            "mos_pct": (intrinsic - mcap) / mcap, "wacc": wacc,
            "growth": growth, "base_fcf": base}


BUFFETT_WINDOW_YEARS = 8        # the reference implementation's `limit=8` on annual data


def buffett_checklist(bundle: dict) -> dict | None:
    """§4.8 13-point Buffett checklist on the annual series (newest first): fundamentals 7
    (ROE>15% +2, D/E<0.5 +2, operating margin>15% +2, current ratio>1.5 +1), consistency 3
    (annual NI non-decreasing +3), moat 3 (ROE>15% in >=80% of periods +2 / >=60% +1;
    avg operating margin>20% with recent >= older +1). None when no annual income exists.

    The window is the most recent BUFFETT_WINDOW_YEARS annual periods, matching the
    `limit=8` the ai-hedge-fund agents pass when they build these same legs. That cap is
    load-bearing, not cosmetic: EDGAR serves ~19 years, and over 19 periods "net income
    non-decreasing every year" and "ROE > 15% in >=80% of years" are all but unreachable —
    Adobe scored 0/3 and 1/2 on them. Two of the three legs, 6 of the 13 points, silently
    became dead, and the §5 consensus lens they feed could never turn green (18 of 1,097
    names on a real run). Judging a decade is the intent; judging two is a different test."""
    inc = (bundle.get("annual") or {}).get("income") or {}
    bal = (bundle.get("annual") or {}).get("balance") or {}
    periods = sorted(inc, reverse=True)[:BUFFETT_WINDOW_YEARS]
    if not periods:
        return None
    window = set(periods)
    items = []

    def add(name, points, mx, detail):
        items.append({"name": name, "points": points, "max": mx,
                      "pass": points == mx, "detail": detail})

    def roe_of(pe):
        ni = _row(inc[pe], "net_income")
        eq = _row(bal.get(pe, {}), "equity")
        return ni / eq if ni is not None and eq is not None and eq > 0 else None

    def om_of(pe):
        oi = _row(inc[pe], "operating_income")
        rev = _row(inc[pe], "revenue")
        return oi / rev if oi is not None and rev is not None and rev > 0 else None

    pe0 = periods[0]
    roe0 = roe_of(pe0)
    add("ROE > 15%", 2 if roe0 is not None and roe0 > 0.15 else 0, 2,
        f"ROE {roe0:.1%}" if roe0 is not None else "not computable")
    b0 = bal.get(pe0, {})
    debt0, eq0 = _row(b0, "total_debt"), _row(b0, "equity")
    de = debt0 / eq0 if debt0 is not None and eq0 is not None and eq0 > 0 else None
    add("Debt/equity < 0.5", 2 if de is not None and de < 0.5 else 0, 2,
        f"D/E {de:.2f}" if de is not None else "not computable")
    om0 = om_of(pe0)
    add("Operating margin > 15%", 2 if om0 is not None and om0 > 0.15 else 0, 2,
        f"operating margin {om0:.1%}" if om0 is not None else "not computable")
    ca, cl = _row(b0, "current_assets"), _row(b0, "current_liabilities")
    cr = ca / cl if ca is not None and cl is not None and cl > 0 else None
    add("Current ratio > 1.5", 1 if cr is not None and cr > 1.5 else 0, 1,
        f"current ratio {cr:.2f}" if cr is not None else "not computable")

    ni_series = [ni for pe in sorted(window)
                 if (ni := _row(inc[pe], "net_income")) is not None]
    consistent = (len(ni_series) >= 2
                  and all(b >= a for a, b in zip(ni_series, ni_series[1:])))
    add("Earnings consistency (NI non-decreasing)", 3 if consistent else 0, 3,
        f"{len(ni_series)} annual NI periods, "
        f"{'non-decreasing' if consistent else 'not non-decreasing or too thin'}")

    roes = [r for pe in periods if (r := roe_of(pe)) is not None]
    pts = 0
    if len(roes) >= 2:
        frac = sum(1 for r in roes if r > 0.15) / len(roes)
        pts = 2 if frac >= 0.8 else 1 if frac >= 0.6 else 0
        detail = f"ROE > 15% in {frac:.0%} of {len(roes)} periods"
    else:
        detail = "insufficient ROE history"
    add("Moat: ROE consistency", pts, 2, detail)

    oms = [o for pe in periods if (o := om_of(pe)) is not None]    # newest first
    pts, detail = 0, "insufficient margin history"
    if oms:
        avg = sum(oms) / len(oms)
        recent = sum(oms[:3]) / len(oms[:3])
        older = sum(oms[-3:]) / len(oms[-3:])
        pts = 1 if avg > 0.20 and recent >= older else 0
        detail = f"avg operating margin {avg:.1%}, recent {recent:.1%} vs older {older:.1%}"
    add("Moat: pricing power (avg margin > 20%, stable)", pts, 1, detail)

    return {"score": sum(i["points"] for i in items), "max": 13, "items": items}


def build_portfolio(scored: list[dict], top_n: int = 15) -> dict:
    """§4.8 proposal portfolio (ai-hedge-fund construction.py + limits.py): candidates =
    top `top_n` by composite (abstention — a name without a composite — is EXCLUDED, never
    a 0-vote); conviction = composite; weights conviction-normalized to gross 1.0; clamps
    max position 10% then max gross 100% (proportional scale); clamped exposure stays cash
    ("conviction requests, risk disposes"); every clamp is an audit dict."""
    cands = sorted((s for s in scored if s.get("composite") is not None),
                   key=lambda s: (-s["composite"], s["symbol"]))
    top = [s for s in cands[:top_n] if s["composite"] > 0]
    total = sum(s["composite"] for s in top)
    if not top or total <= 0:
        return {"positions": [], "cash": 1.0, "clamps": []}
    conviction = {s["symbol"]: float(s["composite"]) for s in top}
    weights = {sym: c / total * GROSS_TARGET for sym, c in conviction.items()}
    clamped, clamps = {}, []
    for sym in sorted(weights):
        w = weights[sym]
        if w > MAX_POSITION_PCT:
            clamps.append({"limit": "max_position_pct", "ticker": sym,
                           "before": w, "after": MAX_POSITION_PCT})
            clamped[sym] = MAX_POSITION_PCT
        else:
            clamped[sym] = w
    gross = sum(clamped.values())
    if gross > MAX_GROSS_EXPOSURE:
        scale = MAX_GROSS_EXPOSURE / gross
        clamped = {sym: w * scale for sym, w in clamped.items()}
        clamps.append({"limit": "max_gross_exposure", "ticker": None,
                       "before": gross, "after": MAX_GROSS_EXPOSURE})
    positions = [{"symbol": sym, "weight": clamped[sym], "conviction": conviction[sym]}
                 for sym in sorted(clamped, key=lambda s: (-clamped[s], s))]
    return {"positions": positions, "cash": max(0.0, 1.0 - sum(clamped.values())),
            "clamps": clamps}
