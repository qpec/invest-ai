"""Scout v2 Stage-1 — deterministic four-pillar graded screening (design §1-§4, §8 item 1).

Pure math over the append-only fundamentals archive (fetch/store.py) + FinanceDatabase
categoricals. No LLM, no new dependency, no live network. Every metric traces to a
design-doc pillar (V/Q/D/M); veto runs before grading and SUPPRESSES vetoed names;
thin/stale data -> "insufficient data", never a silent 0.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from agentcy.fetch import store


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
