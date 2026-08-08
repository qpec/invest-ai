"""Registry v2 — the richer trigger vocabulary (REGISTRY-DESIGN.md, ratified 2026-08-03:
"maintain within the philosophy, use metrics for a richer overview").

This module computes every registry metric the frozen decision layer does not already
expose. The philosophy constraints it exists to honour:

- **The decision layer stays frozen.** `scoring.evaluate` is untouched; this module reads
  its output plus the Bundle's `supplements` stream (pit.py), which by construction never
  enters the statement sections the grader sums. A full-universe baseline diff (2026-08-03,
  1,904 names) confirmed the ten original metrics bit-identical after the v2 wiring.
- **Same windows, not similar windows.** Supplement flows are summed over the EXACT
  per-statement periods `assemble_ttm` selected (`inc_periods` / `cf_periods`), so a
  registry metric and a scorecard metric always describe the same twelve months.
- **Refuse, never guess.** A metric whose input is unmeasured is None — and the monitor
  reports a trigger on it UNCHECKED. The only default-to-zero inputs are the three
  capital-allocation outflows (dividends, buybacks, acquisitions), where an untagged
  concept overwhelmingly means "none paid"; each is marked below.
- **No price triggers.** Nothing here derives from the quote. (The one existing
  quote-adjacent registry metric, owner-FCF yield on EV, predates v2 and stays for
  packets and display — but `thesis.validate` refuses it as a trigger metric since the
  2026-08-08 valuation review, so this contract now holds at the trigger layer too.)
- **Composites never fire.** Piotroski F and Altman Z are computed for the packet and the
  site — display-only. They are level scores; letting one fire a sell rule would be the
  two-judgements merge the constitution forbids. They live in `composites()`, which the
  monitor never calls.
"""
from __future__ import annotations

import scoring

NOPAT_TAX_RATE = 0.25          # scoring's own WACC convention (§4.8) — reused, not invented
MAD_MIN_YEARS = 3              # a stability claim needs at least three annual points
POINT_STALENESS_DAYS = 400     # a balance-point supplement older than ~13 months vs the
                               # balance date is a different balance sheet — refused

# Default-to-zero flows: an untagged outflow overwhelmingly means "none paid", and a None
# here would mark every dividend-free compounder UNCHECKED on its capital-return metrics.
_ZERO_DEFAULT_FLOWS = ("Cash Dividends Paid", "Repurchase Of Capital Stock",
                       "Acquisitions")


def _sum_flow(supplement: dict, label: str, periods: list, scope_key: str) -> float | None:
    """One supplement flow summed over the TTM's own periods for that statement side.
    None when any needed period is missing (never a partial TTM).

    The zero-default outflows get 0 ONLY when the concept is completely untagged in BOTH
    scopes — a filer that never tagged a dividend has genuinely paid none. A concept that
    IS tagged somewhere but cannot cover this window (the 10-K-only dividend filer under
    a quarterly TTM — the 2026-08-03 review's case, which the per-period default silently
    read as 0% capital return) is UNMEASURED, never zero: summing its annual figure over
    a quarterly OCF would mix windows, and inventing quarters would be guessing."""
    flows = ((supplement.get("flows") or {}).get(label) or {})
    scope = flows.get(scope_key) or {}
    if not periods:
        return None
    if label in _ZERO_DEFAULT_FLOWS and not flows.get("annual")             and not flows.get("quarterly"):
        return 0.0
    total = 0.0
    for period in periods:
        value = scope.get(period)
        if value is None:
            return None
        total += value
    return total


def _point(supplement: dict, label: str, *, balance_end: str | None) -> float | None:
    """One balance-point supplement, refused when stale relative to the balance date the
    other side of the ratio comes from — a 2019 goodwill over a 2026 asset base is not a
    ratio, it is two unrelated numbers."""
    point = (supplement.get("points") or {}).get(label)
    if not point:
        return None
    if balance_end and point.get("end"):
        import datetime as _dt
        try:
            gap = abs((_dt.date.fromisoformat(balance_end)
                       - _dt.date.fromisoformat(point["end"])).days)
        except ValueError:
            return None
        if gap > POINT_STALENESS_DAYS:
            return None
    return point.get("value")


def _mad(values: list[float]) -> float | None:
    if len(values) < MAD_MIN_YEARS:
        return None
    mean = sum(values) / len(values)
    return sum(abs(v - mean) for v in values) / len(values)


def _annual_rows(bundle: dict, statement: str) -> dict:
    return (bundle.get("annual") or {}).get(statement) or {}


def _op_margin_series(bundle: dict) -> list[float]:
    """Annual operating margin (%), oldest to newest, only years where both legs exist."""
    out = []
    income = _annual_rows(bundle, "income")
    for period in sorted(income):
        ebit = scoring._row(income[period], "ebit")
        revenue = scoring._row(income[period], "revenue")
        if ebit is not None and revenue is not None and revenue > 0:
            out.append(100.0 * ebit / revenue)
    return out


def _invested_capital(balance_row: dict) -> float | None:
    """Equity + debt − cash: the registry's IC convention for incremental ROIC. Simpler
    than Greenblatt's NWC+FA (which scoring's point-in-time roic uses) because the DELTA
    is the object here and this form needs only rows every balance carries."""
    equity = scoring._row(balance_row, "equity")
    debt = scoring._row(balance_row, "total_debt")
    cash = scoring._row(balance_row, "cash")
    if None in (equity, debt, cash):
        return None
    return equity + debt - cash


def extras(bundle: dict, evaluated: dict | None = None) -> dict[str, float | None]:
    """The v2 metrics the decision layer does not expose. Keys are the values side of
    thesis.METRICS; every value is None unless its inputs were measured."""
    e = evaluated if evaluated is not None else scoring.evaluate(bundle)
    ttm = e.get("ttm") or {}
    supplement = bundle.get("supplements") or {}
    revenue, ebit, ebitda = ttm.get("revenue"), ttm.get("ebit"), ttm.get("ebitda")
    ocf, owner_fcf = ttm.get("ocf"), ttm.get("owner_fcf")
    ni = ttm.get("ni_incl_nci")
    inc_periods = ttm.get("inc_periods") or []
    cf_periods = ttm.get("cf_periods") or []
    scope = "quarterly" if ttm.get("basis") == "quarterly" else "annual"
    balance = scoring._latest_balance(bundle)
    balance_end = None
    for scope_name in ("quarterly", "annual"):
        section = (bundle.get(scope_name) or {}).get("balance") or {}
        if section:
            balance_end = max(section)
            break

    def pct(numerator, denominator):
        return (100.0 * numerator / denominator
                if numerator is not None and denominator is not None and denominator > 0
                else None)

    # --- pricing power ---------------------------------------------------------------
    op_margin = pct(ebit, revenue)
    op_series = _op_margin_series(bundle)[-5:]      # the design's 5y stability window
    op_margin_mad = _mad(op_series)

    # --- the engine, per share and in quality terms ----------------------------------
    shares = scoring.adjusted_shares_series(bundle)
    latest_shares = shares[-1][1] if shares else None
    fcf_per_share = (owner_fcf / latest_shares
                     if owner_fcf is not None and latest_shares else None)
    fcf_conversion = pct(owner_fcf, ni)           # None when NI <= 0: the ratio is
    cash_conversion = pct(ocf, ebitda)            # meaningless against a loss, not "great"
    capex_intensity = pct(ttm.get("capex"), revenue)

    # --- reinvestment ----------------------------------------------------------------
    incremental_roic = None
    income_rows = _annual_rows(bundle, "income")
    balance_rows = _annual_rows(bundle, "balance")
    years = sorted(set(income_rows) & set(balance_rows))
    assets_now = scoring._row(balance, "total_assets")
    if len(years) >= 4:                      # a true 3-year span, as the unit promises
        first, last = years[-4], years[-1]
        ebit_first = scoring._row(income_rows[first], "ebit")
        ebit_last = scoring._row(income_rows[last], "ebit")
        ic_first = _invested_capital(balance_rows[first])
        ic_last = _invested_capital(balance_rows[last])
        if None not in (ebit_first, ebit_last, ic_first, ic_last):
            delta_nopat = (ebit_last - ebit_first) * (1.0 - NOPAT_TAX_RATE)
            delta_ic = ic_last - ic_first
            average_ic = (ic_first + ic_last) / 2.0
            # Refused unless the capital base is MATERIAL to the business and actually
            # grew: the first guard (delta vs ic_last alone) let a cash-rich name with
            # IC near zero publish a five-digit percentage — divide-by-noise wearing a
            # precise number. A capital-light business has no meaningful incremental
            # ROIC, and saying so beats inventing one.
            if (assets_now is not None and average_ic > 0.10 * assets_now
                    and delta_ic > 0.05 * average_ic):
                incremental_roic = 100.0 * delta_nopat / delta_ic

    # --- balance sheet ---------------------------------------------------------------
    interest = _sum_flow(supplement, "Interest Expense", inc_periods, scope)
    interest_coverage = (ebit / abs(interest)
                         if ebit is not None and interest not in (None, 0) else None)
    current_assets = scoring._row(balance, "current_assets")
    current_liabilities = scoring._row(balance, "current_liabilities")
    current_ratio = (current_assets / current_liabilities
                     if current_assets is not None and current_liabilities else None)
    assets = scoring._row(balance, "total_assets")
    goodwill = _point(supplement, "Goodwill", balance_end=balance_end)
    # Intangibles: absent -> 0 (many filers fold them into goodwill or carry none);
    # PRESENT BUT STALE -> the combined metric is refused, because silently dropping a
    # tagged component would understate the acquired share while looking precise.
    intangibles_point = (supplement.get("points") or {}).get("Intangible Assets")
    intangibles = _point(supplement, "Intangible Assets", balance_end=balance_end)
    goodwill_pct = None
    if goodwill is not None and assets and not (intangibles_point and intangibles is None):
        goodwill_pct = pct(goodwill + (intangibles or 0.0), assets)

    # --- stewardship & integrity -----------------------------------------------------
    rd = _sum_flow(supplement, "Research And Development", inc_periods, scope)
    rd_intensity = pct(rd, revenue)
    tax_expense = _sum_flow(supplement, "Income Tax Expense", inc_periods, scope)
    pretax = _sum_flow(supplement, "Pretax Income", inc_periods, scope)
    taxes_paid = _sum_flow(supplement, "Income Taxes Paid", cf_periods, scope)
    tax_gap = None
    # The one v2 formula straddling both statement windows: computed only when the two
    # sides describe the same span, else two fiscal years would masquerade as one rate.
    windows_agree = (inc_periods and cf_periods
                     and max(inc_periods) == max(cf_periods))
    if windows_agree and None not in (tax_expense, pretax, taxes_paid) and pretax > 0:
        tax_gap = 100.0 * (tax_expense - taxes_paid) / pretax
    dividends = _sum_flow(supplement, "Cash Dividends Paid", cf_periods, scope)
    buybacks = _sum_flow(supplement, "Repurchase Of Capital Stock", cf_periods, scope)
    acquisitions = _sum_flow(supplement, "Acquisitions", cf_periods, scope)

    return {
        "op_margin": op_margin,
        "op_margin_mad": op_margin_mad,
        "fcf_per_share": fcf_per_share,
        "fcf_conversion": fcf_conversion,
        "cash_conversion": cash_conversion,
        "capex_intensity": capex_intensity,
        "incremental_roic": incremental_roic,
        "interest_coverage": interest_coverage,
        "current_ratio": current_ratio,
        "goodwill_pct": goodwill_pct,
        "rd_intensity": rd_intensity,
        "tax_gap": tax_gap,
        "dividends_pct_ocf": pct(abs(dividends) if dividends is not None else None, ocf),
        "buybacks_pct_ocf": pct(abs(buybacks) if buybacks is not None else None, ocf),
        "acquisitions_pct_ocf": pct(abs(acquisitions) if acquisitions is not None
                                    else None, ocf),
    }


# --- Composites: display-only, by constitutional rule ------------------------------------

def composites(bundle: dict, evaluated: dict | None = None) -> dict:
    """Piotroski F and Altman Z for the packet and the site. NEVER trigger-capable: they
    are level scores, and a composite firing a sell rule would be the two-judgements
    merge the constitution forbids. Each reports how much of itself could actually be
    measured — an F of 5/5-measured and an F of 5/9-measured are different facts."""
    e = evaluated if evaluated is not None else scoring.evaluate(bundle)
    ttm = e.get("ttm") or {}
    supplement = bundle.get("supplements") or {}
    income_rows = _annual_rows(bundle, "income")
    balance_rows = _annual_rows(bundle, "balance")
    cash_rows = _annual_rows(bundle, "cashflow")
    years = sorted(set(income_rows) & set(balance_rows))

    # -- Piotroski F: nine one-bit tests, each None-tolerant --------------------------
    # Documented deviations from Piotroski (2000), all deliberate proxies over the data
    # this pipeline actually carries: the first three tests run on the TTM rather than
    # the annual year; ROA uses same-year-end assets (the paper uses beginning assets);
    # leverage uses total debt / total assets (paper: LT debt / average assets);
    # "no equity issuance" is proxied by the split-adjusted share-count trend <= 0.
    checks: dict[str, bool | None] = {}
    ni, ocf = ttm.get("ni_incl_nci"), ttm.get("ocf")
    checks["positive_net_income"] = ni > 0 if ni is not None else None
    checks["positive_ocf"] = ocf > 0 if ocf is not None else None
    checks["ocf_exceeds_net_income"] = (ocf > ni if None not in (ni, ocf) else None)

    def year_value(rows, period, key):
        return scoring._row(rows.get(period) or {}, key)

    if len(years) >= 2:
        prev, last = years[-2], years[-1]

        def yoy(fn):
            now, before = fn(last), fn(prev)
            return (now, before) if None not in (now, before) else (None, None)

        roa_now, roa_prev = yoy(lambda y: (
            (n / a) if (n := year_value(income_rows, y, "net_income")) is not None
            and (a := year_value(balance_rows, y, "total_assets")) else None))
        checks["roa_improving"] = roa_now > roa_prev if roa_now is not None else None
        lev_now, lev_prev = yoy(lambda y: (
            (d / a) if (d := year_value(balance_rows, y, "total_debt")) is not None
            and (a := year_value(balance_rows, y, "total_assets")) else None))
        checks["leverage_falling"] = lev_now < lev_prev if lev_now is not None else None
        cr_now, cr_prev = yoy(lambda y: (
            (ca / cl) if (ca := year_value(balance_rows, y, "current_assets")) is not None
            and (cl := year_value(balance_rows, y, "current_liabilities")) else None))
        checks["current_ratio_improving"] = (cr_now > cr_prev
                                             if cr_now is not None else None)
        gm_now, gm_prev = yoy(lambda y: (
            (g / r) if (g := year_value(income_rows, y, "gross_profit")) is not None
            and (r := year_value(income_rows, y, "revenue")) else None))
        checks["gross_margin_improving"] = (gm_now > gm_prev
                                            if gm_now is not None else None)
        at_now, at_prev = yoy(lambda y: (
            (r / a) if (r := year_value(income_rows, y, "revenue")) is not None
            and (a := year_value(balance_rows, y, "total_assets")) else None))
        checks["asset_turnover_improving"] = (at_now > at_prev
                                              if at_now is not None else None)
    else:
        for name in ("roa_improving", "leverage_falling", "current_ratio_improving",
                     "gross_margin_improving", "asset_turnover_improving"):
            checks[name] = None
    share_trend = e.get("share_trend")
    checks["no_net_dilution"] = share_trend <= 0 if share_trend is not None else None

    measured = [v for v in checks.values() if v is not None]
    piotroski = {"score": sum(measured), "measured": len(measured), "of": len(checks),
                 "checks": checks}

    # -- Altman Z (original manufacturing form) — None unless every component measured -
    balance = scoring._latest_balance(bundle)
    balance_end = None
    for scope_name in ("quarterly", "annual"):
        section = (bundle.get(scope_name) or {}).get("balance") or {}
        if section:
            balance_end = max(section)
            break
    assets = scoring._row(balance, "total_assets")
    wc = scoring._row(balance, "working_capital")
    retained = _point(supplement, "Retained Earnings", balance_end=balance_end)
    liabilities = _point(supplement, "Total Liabilities", balance_end=balance_end)
    mcap = bundle.get("market_cap")
    ebit, revenue = ttm.get("ebit"), ttm.get("revenue")
    z = None
    if None not in (assets, wc, retained, liabilities, mcap, ebit, revenue) \
            and assets > 0 and liabilities > 0:
        z = (1.2 * wc / assets + 1.4 * retained / assets + 3.3 * ebit / assets
             + 0.6 * mcap / liabilities + 1.0 * revenue / assets)
    zone = None if z is None else ("distress" if z < 1.81 else
                                   "grey" if z < 2.99 else "safe")
    altman = {"z": None if z is None else round(z, 2), "zone": zone}

    return {"piotroski": piotroski, "altman": altman,
            "note": "display-only — composites never fire a trigger (two judgements "
                    "are never merged)"}
