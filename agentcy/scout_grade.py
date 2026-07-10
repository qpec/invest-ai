"""Scout v2 Stage-1 — deterministic four-pillar graded screening (design §1-§4, §8 item 1).

Pure math over the append-only fundamentals archive (fetch/store.py) + FinanceDatabase
categoricals. No LLM, no new dependency, no live network. Every metric traces to a
design-doc pillar (V/Q/D/M); veto runs before grading and SUPPRESSES vetoed names;
thin/stale data -> "insufficient data", never a silent 0.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from scipy.stats import percentileofscore

from agentcy.fetch import store
from agentcy.scout import HONEST_EVIDENCE_NOTE  # re-export (design §9: printed every run)


def value_metrics(conn, yf_ticker: str, *, market_cap: float, total_debt: float,
                  cash: float, as_of: datetime) -> dict | None:
    """Pillar V raw metrics (design §1 Pillar V, BUF-1/BUF-5): owner-FCF yield on EV and
    the P/owner-FCF display companion. None when owner-FCF is not computable at all;
    owner_fcf_yield None when EV <= 0 (RF5 — return None cleanly, never raise)."""
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if oe is None:
        return None
    owner_fcf = oe.value.owner_fcf_ttm
    ev = market_cap + total_debt - cash
    return {
        "owner_fcf_ttm": owner_fcf,
        "owner_fcf_yield": (owner_fcf / ev) if ev > 0 else None,
        "p_owner_fcf": (market_cap / owner_fcf) if owner_fcf > 0 else None,
    }


def _latest_payloads(conn, yf_ticker: str, stype: str, as_of: datetime) -> dict:
    """period_end -> decoded payload dict (latest fingerprint per period) from the archive.
    Returns {} when the archive is empty or STALE (thin/stale data handled by the caller —
    integrity-suspend, never a silent 0; design §2 data-integrity rule)."""
    hist = store.statement_history(conn, yf_ticker, stype, as_of=as_of)
    if not hist.usable():
        return {}
    return {r["period_end"]: json.loads(r["payload_json"]) for r in hist.value}


def _roic_pct(inc_pay: dict, bal_pay: dict) -> float | None:
    """Latest-period ROIC on the Greenblatt denominator (design §1 Pillar Q).

    RF7 — the numerator is EBIT DIRECTLY (Greenblatt Magic Formula), NOT an invented
    NOPAT/effective-tax-rate clamp. Denominator = net working capital + net fixed assets
    = Working Capital + (Total Assets - Current Assets - Cash And Cash Equivalents).
    None if any pinned row is absent or the denominator is non-positive (design §2)."""
    if not inc_pay or not bal_pay:
        return None
    pe = max(inc_pay)
    inc, bal = inc_pay[pe], bal_pay.get(pe, {})
    ebit = inc.get("EBIT")
    wc = bal.get("Working Capital")
    ta = bal.get("Total Assets")
    ca = bal.get("Current Assets")
    cash = bal.get("Cash And Cash Equivalents")
    if None in (ebit, wc, ta, ca, cash):
        return None
    denom = wc + (ta - ca - cash)          # net working capital + net fixed assets
    if denom <= 0:
        return None
    return 100.0 * ebit / denom


def _gross_margin_series(inc_pay: dict) -> list[float]:
    """Per-period gross margin ratios (Gross Profit / Total Revenue), oldest -> newest;
    periods with an absent/zero pinned row are dropped (never a silent zero)."""
    out = []
    for pe in sorted(inc_pay):
        gp = inc_pay[pe].get("Gross Profit")
        rev = inc_pay[pe].get("Total Revenue")
        if gp is None or not rev:
            continue
        out.append(gp / rev)
    return out


def quality_metrics(conn, yf_ticker: str, *, as_of: datetime) -> dict | None:
    """Pillar Q raw metrics (design §1 Pillar Q).

    - roic_pct: Greenblatt ROIC, EBIT numerator (RF7).
    - gross_margin_level_pct / gross_margin_cv: the two raw ingredients of ONE Q leg
      (RF8 — level percentile minus a bounded CV penalty is combined at scoring time);
      CV is the coefficient of variation of the gross-margin series (>=0, lower = steadier).
    - owner_fcf_margin_pct: (FCF - SBC) / revenue TTM (BUF-5).

    None when statements or owner-FCF are not computable at all (integrity-suspend)."""
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    bal = _latest_payloads(conn, yf_ticker, "balance", as_of)
    roic = _roic_pct(inc, bal)
    gm = _gross_margin_series(inc)
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if roic is None or not gm or oe is None:
        return None
    mean_gm = sum(gm) / len(gm)
    cv = (statistics.pstdev(gm) / mean_gm) if len(gm) > 1 and mean_gm else 0.0
    return {
        "roic_pct": roic,
        "gross_margin_level_pct": 100.0 * mean_gm,
        "gross_margin_cv": cv,
        "owner_fcf_margin_pct": 100.0 * oe.value.owner_fcf_margin_ttm,
    }


def _owner_fcf_negative_all_periods(cf_pay: dict) -> bool:
    """RF3 — owner-FCF < 0 in EVERY available period (per-period cash-destruction, NOT the
    sign of the TTM sum). Per-period owner-FCF = (OCF - |CapEx|) - SBC, matching the pinned
    construction in store.owner_fcf_ttm (SBC-free filer -> 0, plan note 4). Periods missing a
    required pinned row are dropped (never a silent zero); an empty result is not "all
    negative" -> False."""
    vals = []
    for pe in sorted(cf_pay):
        cell = cf_pay[pe]
        ocf = cell.get("Operating Cash Flow")
        capex = cell.get("Capital Expenditure")
        if ocf is None or capex is None:
            continue
        sbc = float(cell.get("Stock Based Compensation") or 0.0)
        vals.append((float(ocf) - abs(float(capex))) - sbc)
    return bool(vals) and all(v < 0 for v in vals)


def durability_metrics(conn, yf_ticker: str, *, as_of: datetime) -> dict | None:
    """Pillar D raw metrics (design §1 Pillar D). net debt uses the LATEST balance period;
    EBITDA + revenue + SBC are TTM (sum of available quarters, up to 4). None when a pinned
    input is absent.

    RF2 — ALSO returns the raw TTM ``ebitda`` and raw ``net_debt`` (= total_debt - cash) so
    Task 9's veto_check feeds REAL values, never a fabricated placeholder.
    RF3 — ALSO returns ``owner_fcf_negative_all_periods`` (per-period cash-destruction from
    the archive), which Task 9's cash-destruction veto uses instead of the TTM sum sign."""
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    bal = _latest_payloads(conn, yf_ticker, "balance", as_of)
    cf = _latest_payloads(conn, yf_ticker, "cashflow", as_of)
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if not inc or not bal or not cf or oe is None:
        return None
    periods = sorted(inc, reverse=True)[:4]
    ebitda = revenue = 0.0
    for pe in periods:
        cell = inc[pe]
        e = cell.get("EBITDA")
        r = cell.get("Total Revenue")
        if e is None or r is None:
            return None
        ebitda += float(e)
        revenue += float(r)
    sbc = oe.value.sbc_ttm
    latest_bal = bal[max(bal)]
    debt = latest_bal.get("Total Debt")
    cash = latest_bal.get("Cash And Cash Equivalents")
    if debt is None or cash is None or ebitda == 0 or revenue <= 0:
        return None
    net_debt = debt - cash                                   # RF2 — raw net debt
    return {
        "ebitda": ebitda,                                    # RF2 — raw TTM EBITDA
        "net_debt": net_debt,                                # RF2 — raw net debt
        "net_debt_to_ebitda": net_debt / ebitda,
        "owner_fcf_positive": oe.value.owner_fcf_ttm > 0,
        "owner_fcf_negative_all_periods": _owner_fcf_negative_all_periods(cf),  # RF3
        "sbc_to_revenue_pct": 100.0 * sbc / revenue,
    }


def management_metrics(conn, yf_ticker: str, *, as_of: datetime) -> dict | None:
    """Pillar M deterministic raw metrics (design §1 Pillar M): share-count trend, per-share
    owner-FCF growth, accrual/cash divergence. The qualitative half (candor, alignment,
    related-party dealings) is DEFERRED to the Stage-2 shortlist and NEVER faked here (FR9).
    None when the underlying statements/shares are absent (integrity-suspend, never a silent 0).

    - shares_yoy_pct: trailing-12m share-count growth % (B.2 type 4). None (leg SUSPENDED,
      not scored 0) when no ~1y-ago share observation exists (RF6 graceful degradation).
    - accrual_divergence_pct: 100·(net-income TTM − owner-FCF TTM) / revenue TTM. >0 =
      reported profit with no cash behind it (a Munger earnings-quality red flag).
    - per_share_ofcf_growth_pct / per_share_ofcf_growth_label: annualized per-share owner-FCF
      growth over the AVAILABLE share window, labelled honestly (RF11 — the archive holds only
      a <3yr window, so it is never presented as a true 3yr CAGR)."""
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if not inc or oe is None:
        return None
    periods = sorted(inc, reverse=True)[:4]                  # newest 4 quarters (TTM)
    ni = rev = 0.0
    for pe in periods:
        n = inc[pe].get("Net Income")
        r = inc[pe].get("Total Revenue")
        if n is None or r is None:
            return None                                      # a required pinned row missing
        ni += float(n)
        rev += float(r)
    if rev <= 0:
        return None
    owner_fcf = oe.value.owner_fcf_ttm
    accrual_div = 100.0 * (ni - owner_fcf) / rev

    sh = store.shares_yoy(conn, yf_ticker, as_of=as_of)      # Stamped[float | None]
    shares_yoy_pct = sh.value if sh.usable() and sh.value is not None else None

    growth_pct, growth_label = _per_share_ofcf_growth(conn, yf_ticker, oe, as_of)
    return {
        "shares_yoy_pct": shares_yoy_pct,
        "accrual_divergence_pct": accrual_div,
        "per_share_ofcf_growth_pct": growth_pct,
        "per_share_ofcf_growth_label": growth_label,
    }


def _per_share_ofcf_growth(conn, yf_ticker, oe, as_of) -> tuple[float | None, str | None]:
    """Annualized per-share owner-FCF growth over the deduped share window (oldest usable ->
    newest at/before as_of); returns (value, honest-label). None with < 2 observations or a
    non-positive base (integrity-suspend, never 0).

    RF11 — the archive holds only a <3yr window, so the returned label is explicit that this
    is the annualized available-window growth and that a true 3yr CAGR is not computable."""
    sh = store.shares_history(conn, yf_ticker, as_of=as_of)
    if not sh.usable():
        return None, None
    series = sh.value[sh.value.index <= pd.Timestamp(as_of.date())]
    if len(series) < 2:
        return None, None
    newest_ps = oe.value.owner_fcf_per_share_ttm
    oldest_shares = float(series.iloc[0])
    if oldest_shares <= 0 or newest_ps <= 0:
        return None, None
    base_ps = oe.value.owner_fcf_ttm / oldest_shares        # owner-FCF at the older share base
    if base_ps <= 0:
        return None, None
    oldest_d = series.index[0].date().isoformat()
    newest_d = series.index[-1].date().isoformat()
    years = max((series.index[-1] - series.index[0]).days / 365.25, 1e-9)
    growth = 100.0 * ((newest_ps / base_ps) ** (1.0 / years) - 1.0)
    label = (f"per-share owner-FCF growth, {oldest_d}->{newest_d} annualized "
             f"— 3yr CAGR not computable from archive")
    return growth, label


# --- Veto / penalty layer (design §2) -------------------------------------------------
# Absolute reference lines inherited from v1 / design §2 (the ONLY fixed numbers here).
NET_DEBT_EBITDA_VETO = 4.0        # net debt/EBITDA above this = leverage wreck (§2)
DILUTION_PENALTY_PCT = 5.0        # share count growing faster than this = serial dilution
DILUTION_PENALTY = -15           # subtracted from the composite, flagged (not a veto)


@dataclass(frozen=True)
class Veto:
    """Design §2 outcome. ``vetoed`` -> grade SUPPRESSED (cap, never rank); ``penalty`` ->
    subtracted from the composite; ``reason`` is the printed explanation ("" when clean)."""
    vetoed: bool
    penalty: int
    reason: str


def veto_check(*, net_debt_to_ebitda, ebitda, net_debt, owner_fcf_positive_any,
               shares_yoy_pct) -> Veto:
    """Design §2 veto/penalty layer — runs BEFORE grading. Leverage & cash-destruction
    SUPPRESS (a vetoed name is removed from the shortlist, never sorted to the bottom
    where it could still surface); dilution is a -15 penalty, flagged, not a veto.

    RF2 — ``ebitda`` and ``net_debt`` are the REAL raw figures from ``durability_metrics``
    (never fabricated placeholders); the EBITDA<=0-with-net-debt branch reads them directly.
    RF3 — ``owner_fcf_positive_any`` must be fed the PER-PERIOD cash-destruction signal
    (True iff owner-FCF was positive in at least one available period, i.e.
    ``not durability_metrics()["owner_fcf_negative_all_periods"]``) — NOT the sign of the
    TTM sum. The cash-destruction veto fires only when owner-FCF is negative every period.
    """
    # Leverage veto (§2): net debt/EBITDA > 4, OR EBITDA <= 0 while still carrying net debt.
    if (net_debt_to_ebitda is not None and net_debt_to_ebitda > NET_DEBT_EBITDA_VETO) or \
       (ebitda is not None and ebitda <= 0 and net_debt is not None and net_debt > 0):
        return Veto(True, 0, "leverage veto: net debt/EBITDA above the §2 floor")
    # Cash-destruction veto (§2, RF3): owner-FCF negative across ALL available periods.
    if not owner_fcf_positive_any:
        return Veto(True, 0, "cash-destruction veto: owner-FCF negative every period")
    # Dilution penalty (§2): serial issuance > 5%/yr — a -15 hit, flagged, not a veto.
    if shares_yoy_pct is not None and shares_yoy_pct > DILUTION_PENALTY_PCT:
        return Veto(False, DILUTION_PENALTY,
                    f"dilution penalty: shares +{shares_yoy_pct:.1f}%/yr")
    return Veto(False, 0, "")


# --- Sector-percentile scoring (design §1 scoring convention) --------------------------
# ROIC>15% is one of only two fixed reference lines in the whole model (design §1); it is
# inherited from v1 (scout.QV_ROIC_MIN, there a percentage). Here ROIC is scored as a
# RATIO floor, so QV_ROIC_MIN is the fraction 0.15 (== 15%) — RF4.
QV_ROIC_MIN = 0.15


def sector_percentile(value: float, cohort, *, higher_better: bool) -> float:
    """Cross-sectional percentile of `value` within its sector cohort (design §1). None/NaN
    cohort members dropped; a singleton (or all-missing) cohort scores 50.0 (neutral).
    lower-better metrics (net debt, SBC, CV) invert to keep 'high score = good'."""
    clean = [float(x) for x in cohort
             if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(clean) <= 1:
        return 50.0
    p = float(percentileofscore(clean, float(value), kind="mean"))
    return p if higher_better else 100.0 - p


def roic_leg_score(roic_pct: float, cohort) -> float:
    """The Q-pillar ROIC leg (design §1 Pillar Q, RF4): the sector percentile of ROIC BLENDED
    with the absolute >15% reference line. A ROIC below 15% discounts the leg by
    ``min(1, ROIC/15%)`` — so a great sector rank on a sub-floor ROIC cannot masquerade as a
    capital-productivity moat. ``roic_pct`` and the cohort are ROIC as PERCENTAGES; the floor
    is QV_ROIC_MIN (0.15 == 15%). At/above 15% the factor is 1.0 (leg == raw percentile)."""
    pct = sector_percentile(roic_pct, cohort, higher_better=True)
    floor_factor = max(0.0, min(1.0, roic_pct / (100.0 * QV_ROIC_MIN)))
    return round(pct * floor_factor, 6)


# --- Pillar aggregation -> composite -> grade (design §1 composite table) ---------------
# Composite weights (design §1): wonderful business (Q) at a fair price (V) dominant; the
# avoid-ruin (D) and trust-management (M) guardrails co-equal. The entire tunable surface.
W_V, W_Q, W_D, W_M = 0.30, 0.30, 0.20, 0.20

_GRADE_BANDS = ((80.0, "A"), (65.0, "B"), (50.0, "C"), (35.0, "D"))


def pillar_score(legs) -> float | None:
    """Equal-weighted mean of a pillar's present metric percentiles; None when all missing
    (integrity-suspend, never a silent 0)."""
    present = [x for x in legs if x is not None]
    if not present:
        return None
    return sum(present) / len(present)


def composite(*, v: float, q: float, d: float, m: float, penalty: int) -> float:
    """Design §1 composite, penalty applied, floored at 0 (and capped at 100)."""
    raw = W_V * v + W_Q * q + W_D * d + W_M * m + penalty
    return max(0.0, min(100.0, round(raw, 4)))


def grade_letter(comp: float) -> str:
    """A/B/C/D/F per the design §1 grade table."""
    for lo, letter in _GRADE_BANDS:
        if comp >= lo:
            return letter
    return "F"


# --- Circle-of-competence tiering (design §3) — orthogonal to grade, never blended ------
# Tier is a priority LANE assigned purely from the FinanceDatabase sector/industry
# categoricals — deterministic, no LLM. Core = the owner's edge (design §3: cloud/SaaS
# infra, healthcare & insurance tech, AI tooling); Adjacent = one hop out (broader IT
# services, med-devices, semis, fintech data/analytics, interactive media); Outside = rest.
#
# RF10 — these are EXACT-match against the ACTUAL FinanceDatabase `industry` categoricals,
# not invented sub-splits. Ground truth is the pinned `compression/equities.bz2` that
# `scout.py:load_universe` reads (design §5): a flat GICS-style set of 68 industries — e.g.
# 'Software', 'Health Care Technology', 'IT Services', 'Semiconductors & Semiconductor
# Equipment' — with sectors like 'Information Technology' (NOT 'Technology'). The taxonomy
# has NO 'Software - Infrastructure'/'- Application' split and NO 'Health Information
# Services'/'Medical Devices'/'Financial Data & Stock Exchanges' — the previous keyword
# lists matched none of these and left the Core lane unreachable (the RF10 failure).
# A checked-in sample of the real categoricals guards this in tests/test_scout_grade_tier.py
# (tests/fixtures/financedatabase_categoricals.json).
#
# Core software lane: the flat 'Software' industry is the owner's cloud/SaaS/AI-tooling
# edge (MSFT/CRM/NOW/SNOW all file here) — the taxonomy cannot split infra from
# application, so the whole industry is Core. 'Health Care Technology' is healthtech
# proper. Insurtech has NO distinct industry: it surfaces via 'Software' (or 'Insurance'
# + name filtering), so the bare 'Insurance' industry — underwriting/distribution, the
# "Insurance Brokers" trap RF10 names — is deliberately NOT Core.
_CORE_INDUSTRIES = frozenset({
    "software",                 # cloud/SaaS infrastructure + application + AI tooling
    "health care technology",   # healthcare tech proper
})
_ADJACENT_INDUSTRIES = frozenset({
    "it services",                              # IT services — one hop out
    "semiconductors & semiconductor equipment",  # data/compute plumbing
    "health care equipment & supplies",         # med-devices / instruments
    "life sciences tools & services",           # health-tech-adjacent tooling
    "interactive media & services",             # platform/software-adjacent
    "capital markets",                          # fintech data/analytics & exchanges
})


def tier_of(*, sector, industry) -> str:
    """Core / Adjacent / Outside (design §3). Exact-match on the FinanceDatabase `industry`
    categorical: Core (owner's edge) before Adjacent (one hop out), then Outside default.
    Case-insensitive; None/unknown industry -> Outside. Orthogonal to grade — never blended."""
    ind = (industry or "").strip().lower()
    if ind in _CORE_INDUSTRIES:
        return "Core"
    if ind in _ADJACENT_INDUSTRIES:
        return "Adjacent"
    return "Outside"


# --- Batch grading over the universe (design §4 Stage-1 pass) --------------------------
# The "required" metrics whose absence is an integrity-suspend (RF5): each is a pillar leg
# that MUST feed a percentile call. When any is None (e.g. owner_fcf_yield when EV <= 0, or
# owner-FCF not computable) the name is emitted as INSUFFICIENT with a printed reason BEFORE
# any sector_percentile call — None is never handed to percentileofscore.


@dataclass(frozen=True)
class GradedName:
    """One Stage-1 graded row (design §4). grade in {A,B,C,D,F,VETOED,INSUFFICIENT}."""
    symbol: str
    sector: str | None
    tier: str
    v: float | None
    q: float | None
    d: float | None
    m: float | None
    composite: float | None
    grade: str
    note: str


def _required_metric_gap(bundle) -> str | None:
    """RF5 — name the first REQUIRED pillar metric that is None (would otherwise be fed into
    percentileofscore). Returns a printed reason, or None when every required metric is present.
    ``owner_fcf_yield`` is None precisely when EV <= 0 (value_metrics, RF5); the ROIC /
    gross-margin / owner-FCF-margin / net-debt / SBC / accrual legs are required too."""
    required = (
        ("v", "owner_fcf_yield", "owner-FCF yield (EV <= 0 or not computable)"),
        ("q", "roic_pct", "ROIC"),
        ("q", "gross_margin_level_pct", "gross-margin level"),
        ("q", "owner_fcf_margin_pct", "owner-FCF margin"),
        ("d", "net_debt_to_ebitda", "net debt/EBITDA"),
        ("d", "sbc_to_revenue_pct", "SBC/revenue"),
        ("m", "accrual_divergence_pct", "accrual divergence"),
    )
    for pillar, key, label in required:
        if bundle[pillar].get(key) is None:
            return label
    return None


def _raw_bundle(conn, symbol, md, as_of):
    """All four pillars' raw metric dicts for one ticker; None -> insufficient (a pillar is
    not computable at all: thin/stale archive or missing pinned rows, design §2)."""
    val = value_metrics(conn, symbol, market_cap=md["market_cap"],
                        total_debt=md["total_debt"], cash=md["cash"], as_of=as_of)
    qual = quality_metrics(conn, symbol, as_of=as_of)
    dur = durability_metrics(conn, symbol, as_of=as_of)
    mgmt = management_metrics(conn, symbol, as_of=as_of)
    if None in (val, qual, dur, mgmt):
        return None
    return {"v": val, "q": qual, "d": dur, "m": mgmt}


def _dig(d, path):
    for k in path:
        d = d[k]
    return d


def grade_universe(conn, universe, *, market_data, as_of) -> list[GradedName]:
    """Design §4 Stage-1 deterministic pass. Two-phase: (1) collect raw metrics per name,
    integrity-suspend any name with a None REQUIRED metric (RF5 — never a None into
    percentileofscore), and run the veto layer wired with the REAL durability figures
    (RF2/RF3); (2) sector-percentile-score the survivors and compose. Vetoed names keep a
    row with grade='VETOED' (suppressed downstream, not ranked); thin/None-metric names get
    grade='INSUFFICIENT' with a printed note (never a silent 0). Output order == universe order."""
    rows = universe.to_dict("records")
    raw: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    results: dict[str, GradedName] = {}
    _insufficient = ("insufficient data: <2 usable periods, missing pinned rows, "
                     "or a None required metric (design §2)")

    # Phase 1 — raw metrics, tier, integrity-suspend, veto.
    for r in rows:
        sym = r["symbol"]
        sector = r.get("sector")
        tier = tier_of(sector=sector, industry=r.get("industry"))
        meta[sym] = {"sector": sector, "tier": tier}
        md = market_data.get(sym)
        bundle = _raw_bundle(conn, sym, md, as_of) if md else None
        if bundle is None:
            results[sym] = GradedName(sym, sector, tier, None, None, None, None, None,
                                      "INSUFFICIENT", _insufficient)
            continue
        # RF5 — a None REQUIRED metric is an integrity-suspend, emitted BEFORE any percentile.
        gap = _required_metric_gap(bundle)
        if gap is not None:
            results[sym] = GradedName(sym, sector, tier, None, None, None, None, None,
                                      "INSUFFICIENT", f"{_insufficient}: {gap}")
            continue
        d = bundle["d"]
        # RF2 — REAL raw ebitda + net_debt; RF3 — per-period cash-destruction flag (owner-FCF
        # positive in SOME period == not negative in EVERY period), NOT the TTM-sum sign.
        veto = veto_check(
            net_debt_to_ebitda=d["net_debt_to_ebitda"],
            ebitda=d["ebitda"],
            net_debt=d["net_debt"],
            owner_fcf_positive_any=not d["owner_fcf_negative_all_periods"],
            shares_yoy_pct=bundle["m"]["shares_yoy_pct"])
        if veto.vetoed:
            results[sym] = GradedName(sym, sector, tier, None, None, None, None, None,
                                      "VETOED", veto.reason)
            continue
        raw[sym] = {"bundle": bundle, "penalty": veto.penalty, "reason": veto.reason}

    # Phase 2 — sector cohorts, percentiles, composite (survivors only).
    def cohort(sym, path):
        sec = meta[sym]["sector"]
        return [_dig(raw[o]["bundle"], path) for o in raw if meta[o]["sector"] == sec]

    for sym, entry in raw.items():
        b = entry["bundle"]
        v = pillar_score([sector_percentile(
            b["v"]["owner_fcf_yield"], cohort(sym, ("v", "owner_fcf_yield")), higher_better=True)])
        # RF4 — the ROIC leg BLENDS the sector percentile with the absolute >15% floor.
        # RF8 — gross margin is ONE leg: the level percentile discounted by the CV percentile
        # (a steadier margin, i.e. a higher lower-better CV percentile, keeps more of the level).
        gm_level = sector_percentile(b["q"]["gross_margin_level_pct"],
                                     cohort(sym, ("q", "gross_margin_level_pct")), higher_better=True)
        gm_stability = sector_percentile(b["q"]["gross_margin_cv"],
                                         cohort(sym, ("q", "gross_margin_cv")), higher_better=False)
        gm_leg = gm_level * (gm_stability / 100.0)
        q = pillar_score([
            roic_leg_score(b["q"]["roic_pct"], cohort(sym, ("q", "roic_pct"))),
            gm_leg,
            sector_percentile(b["q"]["owner_fcf_margin_pct"],
                              cohort(sym, ("q", "owner_fcf_margin_pct")), higher_better=True),
        ])
        d = pillar_score([
            sector_percentile(b["d"]["net_debt_to_ebitda"],
                              cohort(sym, ("d", "net_debt_to_ebitda")), higher_better=False),
            100.0 if b["d"]["owner_fcf_positive"] else 0.0,
            sector_percentile(b["d"]["sbc_to_revenue_pct"],
                              cohort(sym, ("d", "sbc_to_revenue_pct")), higher_better=False),
        ])
        m_legs = [sector_percentile(b["m"]["accrual_divergence_pct"],
                                    cohort(sym, ("m", "accrual_divergence_pct")), higher_better=False)]
        if b["m"]["shares_yoy_pct"] is not None:
            m_legs.append(sector_percentile(b["m"]["shares_yoy_pct"],
                                            cohort(sym, ("m", "shares_yoy_pct")), higher_better=False))
        if b["m"]["per_share_ofcf_growth_pct"] is not None:
            m_legs.append(sector_percentile(b["m"]["per_share_ofcf_growth_pct"],
                                            cohort(sym, ("m", "per_share_ofcf_growth_pct")), higher_better=True))
        m = pillar_score(m_legs)
        comp = composite(v=v, q=q, d=d, m=m, penalty=entry["penalty"])
        results[sym] = GradedName(sym, meta[sym]["sector"], meta[sym]["tier"],
                                  round(v, 1), round(q, 1), round(d, 1), round(m, 1),
                                  comp, grade_letter(comp), entry["reason"])
    # stable order: universe order
    return [results[r["symbol"]] for r in rows]
