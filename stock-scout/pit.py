"""Point-in-time fundamentals adapter over EDGAR companyfacts (RECONSTRUCTION.md §5.9).

as_of_bundle() turns one raw bt_cache/facts/<SYM>.json payload (§3.6) into the exact §4.1
Bundle that scoring.py consumes live — EDGAR tags mapped to Yahoo-style row labels, the
§4.1 decoupling seam — under STRICT filed-date discipline: only facts filed <= as_of
exist, and the value used for a period is the latest-filed one (restatements honored,
lookahead impossible). Flow quarters: durations <= 100 days pass through as true
quarters; longer cumulatives (YTD / FY / broken-fiscal-year stubs) are differenced
against the prior YTD whose period-start matches within +/-365 days (msg 44), accepted
only when the derived span is itself a quarter (<= 100 days) so a prior-year YTD can
never masquerade as one; Q4 falls out of FY minus the 9-month YTD through the same rule
(no separate FY-minus-3-quarters pass). Multi-class dei share counts are summed per
filed date; an inconsistent filing empties the series so the M share-trend leg stays
neutral in scoring (msg 44). No I/O, no network, no clock.
"""
from __future__ import annotations

from datetime import date

QUARTER_MAX_DAYS = 100         # §5.9: a duration this short IS a quarter (53-week-year safe)
YTD_START_WINDOW_DAYS = 365    # §5.9: prior-YTD start-match tolerance (broken fiscal years)
ANNUAL_MIN_DAYS, ANNUAL_MAX_DAYS = 330, 400   # 52-week (364d) .. sloppy calendar annual

# §5.9 tag fallback chains (msg 44 adversarial fixes pinned; first present wins per period).
_INCOME_CONCEPTS = {
    "Total Revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax",
                      "Revenues", "SalesRevenueNet"),        # ADBE reports Revenues
    "EBIT": ("OperatingIncomeLoss",),
    "Operating Income": ("OperatingIncomeLoss",),            # §4.1 Buffett-checklist chain head
    "Gross Profit": ("GrossProfit",),                        # absent -> the Q gm leg degrades
    "Net Income": ("NetIncomeLoss",),
    "Net Income Including Noncontrolling Interests": ("ProfitLoss", "NetIncomeLoss"),
}
_CASHFLOW_CONCEPTS = {
    "Operating Cash Flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "Capital Expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),  # sign-flipped below
    "Stock Based Compensation": ("ShareBasedCompensation",),
    "Depreciation And Amortization": ("DepreciationDepletionAndAmortization",
                                      "DepreciationAndAmortization"),
}
_BALANCE_CONCEPTS = {
    "Cash And Cash Equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    "Stockholders Equity": ("StockholdersEquity",),
    "Total Assets": ("Assets",),
    "Current Assets": ("AssetsCurrent",),
    "Current Liabilities": ("LiabilitiesCurrent",),
}
_SHARES_TAG = "EntityCommonStockSharesOutstanding"


def _iso(d) -> str:
    """ISO-string normalization for date-or-str inputs (all §5.9 comparisons are ISO)."""
    return d if isinstance(d, str) else d.isoformat()


def _days(d0: str, d1: str) -> int:
    """Calendar days from d0 to d1."""
    return (date.fromisoformat(d1) - date.fromisoformat(d0)).days


def _unit_entries(facts: dict, taxonomy: str, tag: str) -> list:
    """Raw unit entries for one concept; USD (then shares) preferred, else the first unit."""
    units = (((facts.get("facts") or {}).get(taxonomy) or {}).get(tag) or {}).get("units") or {}
    for preferred in ("USD", "shares"):
        if preferred in units:
            return units[preferred]
    return units[sorted(units)[0]] if units else []


def _latest_filed(entries: list, as_of: str, *, instant: bool) -> dict:
    """§5.9 filed-date discipline: only facts filed <= as_of survive; the latest-filed
    value wins per period ((start, end) key for flows, end key for instants)."""
    best = {}
    for entry in entries:
        filed, end, val = entry.get("filed"), entry.get("end"), entry.get("val")
        if filed is None or end is None or val is None or filed > as_of:
            continue
        key = end if instant else (entry.get("start"), end)
        if not instant and key[0] is None:
            continue
        if key not in best or filed >= best[key][0]:
            best[key] = (filed, float(val))
    return {key: val for key, (_, val) in best.items()}


def _merge_chain(facts: dict, tags: tuple, as_of: str, *, instant: bool) -> dict:
    """§5.9 tag fallback chain, first present wins PER PERIOD — a filer that switched
    tags keeps its older periods from the lower-priority tag."""
    merged = {}
    for tag in tags:
        for key, val in _latest_filed(_unit_entries(facts, "us-gaap", tag), as_of,
                                      instant=instant).items():
            merged.setdefault(key, val)
    return merged


def annual_flows(periods: dict) -> dict:
    """Annual series from {(start, end): value}: durations of 330-400 days (52/53-week and
    calendar fiscal years; stubs and >12-month transition years are quarterly-only)."""
    out = {}
    for (start, end), val in sorted(periods.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if ANNUAL_MIN_DAYS <= _days(start, end) <= ANNUAL_MAX_DAYS:
            out[end] = val
    return out


def quarterly_flows(periods: dict) -> dict:
    """§5.9 flow-quarter derivation over {(start, end): value}: durations <= 100 days pass
    through as true quarters; a longer cumulative becomes the quarter ending at its end by
    subtracting the prior YTD — period-start within +/-365 days (exact match preferred,
    then the latest prior end), and only a derived span <= 100 days is accepted, so a
    prior-year YTD (span ~365d) can never masquerade as a quarter (msg 44)."""
    quarters = {}
    ordered = sorted(periods.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    for (start, end), val in ordered:
        if _days(start, end) <= QUARTER_MAX_DAYS:
            quarters[end] = val
    for (start, end), val in ordered:
        if _days(start, end) <= QUARTER_MAX_DAYS or end in quarters:
            continue
        best = None
        for (start2, end2), val2 in periods.items():
            if end2 >= end or not 0 < _days(end2, end) <= QUARTER_MAX_DAYS:
                continue
            drift = abs(_days(start, start2))
            if drift > YTD_START_WINDOW_DAYS:
                continue
            rank = (drift, -date.fromisoformat(end2).toordinal())
            if best is None or rank < best[0]:
                best = (rank, val - val2)
        if best is not None:
            quarters[end] = best[1]
    return quarters


def _flow_maps(facts: dict, concepts: dict, as_of: str) -> tuple[dict, dict]:
    """Per-label annual and quarterly {end: value} maps for one statement's concepts."""
    annual, quarterly = {}, {}
    for label, tags in concepts.items():
        periods = _merge_chain(facts, tags, as_of, instant=False)
        annual[label] = annual_flows(periods)
        quarterly[label] = quarterly_flows(periods)
    return annual, quarterly


def _balance_maps(facts: dict, as_of: str) -> dict:
    """§5.9 instant composition per balance date: the simple chains plus Total Debt
    (LongTermDebt, else the noncurrent+current pieces with ShortTermBorrowings, missing
    legs 0 only when a long-term piece exists, else absent), Minority Interest
    (incl-NCI equity minus equity) and Working Capital (AssetsCurrent - LiabilitiesCurrent)."""
    maps = {label: _merge_chain(facts, tags, as_of, instant=True)
            for label, tags in _BALANCE_CONCEPTS.items()}
    ltd = _merge_chain(facts, ("LongTermDebt",), as_of, instant=True)
    noncur = _merge_chain(facts, ("LongTermDebtNoncurrent",), as_of, instant=True)
    cur = _merge_chain(facts, ("LongTermDebtCurrent",), as_of, instant=True)
    short = _merge_chain(facts, ("ShortTermBorrowings",), as_of, instant=True)
    incl_nci = _merge_chain(
        facts, ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",),
        as_of, instant=True)
    debt = {}
    for end in sorted(set(ltd) | set(noncur) | set(cur)):
        debt[end] = ltd[end] if end in ltd else (
            noncur.get(end, 0.0) + cur.get(end, 0.0) + short.get(end, 0.0))
    maps["Total Debt"] = debt
    equity = maps["Stockholders Equity"]
    maps["Minority Interest"] = {end: incl_nci[end] - equity[end]
                                 for end in incl_nci if end in equity}
    current_a, current_l = maps["Current Assets"], maps["Current Liabilities"]
    maps["Working Capital"] = {end: current_a[end] - current_l[end]
                               for end in current_a if end in current_l}
    return maps


def _section(maps: dict) -> dict:
    """Invert per-label {end: value} maps into the §3.2 statement shape {end: {label: value}}."""
    ends = sorted({end for m in maps.values() for end in m})
    return {end: {label: m[end] for label, m in maps.items() if end in m} for end in ends}


def shares_series(facts: dict, as_of) -> list:
    """§5.9 dei EntityCommonStockSharesOutstanding -> ascending [[date, count], ...]:
    class rows summed per filed date, latest filed wins per measurement date; a filing
    reporting more than one measurement date is inconsistent -> [] (empty series, so the
    M share-trend leg suspends to neutral in scoring, msg 44)."""
    as_of = _iso(as_of)
    by_filed = {}
    for entry in _unit_entries(facts, "dei", _SHARES_TAG):
        filed, end, val = entry.get("filed"), entry.get("end"), entry.get("val")
        if filed is None or end is None or val is None or filed > as_of:
            continue
        by_filed.setdefault(filed, []).append((end, float(val)))
    series = {}
    for filed in sorted(by_filed):                 # ascending: the latest filed wins per end
        observations = by_filed[filed]
        if len({end for end, _ in observations}) != 1:
            return []
        series[observations[0][0]] = sum(val for _, val in observations)
    return [[end, series[end]] for end in sorted(series)]


def shares_at(series: list, as_of) -> float | None:
    """Last share observation dated at or before as_of from an ascending §5.9 series."""
    as_of = _iso(as_of)
    best = None
    for day, val in series:
        if day <= as_of:
            best = val
    return best


def price_at(prices: dict, symbol: str, day) -> float | None:
    """Last weekly close at or before `day` from the §3.6 grid ({symbol: {date: adj_close}});
    None when the symbol has no bar at or before it."""
    grid = prices.get(symbol) or {}
    day = _iso(day)
    best = None
    for bar in grid:
        if bar <= day and (best is None or bar > best):
            best = bar
    return grid[best] if best is not None else None


def quarter_ends(spy_prices: dict, start, end) -> list:
    """§5.10 rebalance grid: the last weekly bar date per calendar quarter within
    [start, end], from the benchmark's {date: adj_close} price grid."""
    start, end = _iso(start), _iso(end)
    by_quarter = {}
    for day in spy_prices:
        if start <= day <= end:
            d = date.fromisoformat(day)
            key = (d.year, (d.month - 1) // 3)
            if key not in by_quarter or day > by_quarter[key]:
                by_quarter[key] = day
    return [by_quarter[key] for key in sorted(by_quarter)]


def as_of_bundle(facts: dict, symbol: str, meta: dict, as_of, prices: dict) -> dict | None:
    """§5.9: EDGAR companyfacts -> the §4.1 Bundle as it was knowable on as_of, or None
    when no annual income period is visible yet (a pre-first-10-K name is not scoreable).
    market_cap = shares_at(as_of) x price_at(as_of) on the §3.6 weekly grid; yahoo_ev is
    None by construction (no Yahoo in the PIT world — the EV_GAP flag never fires)."""
    as_of = _iso(as_of)
    if not facts or not (facts.get("facts") or {}):
        return None
    income_a, income_q = _flow_maps(facts, _INCOME_CONCEPTS, as_of)
    cashflow_a, cashflow_q = _flow_maps(facts, _CASHFLOW_CONCEPTS, as_of)
    for cf in (cashflow_a, cashflow_q):   # EDGAR payments are outflow-positive; Yahoo is negative
        cf["Capital Expenditure"] = {end: -val
                                     for end, val in cf["Capital Expenditure"].items()}
    for income, cf in ((income_a, cashflow_a), (income_q, cashflow_q)):  # §5.9 EBITDA = EBIT + D&A
        da = cf["Depreciation And Amortization"]
        income["EBITDA"] = {end: val + da[end]
                           for end, val in income["EBIT"].items() if end in da}
    annual_income = _section(income_a)
    if not annual_income:
        return None
    balance = _section(_balance_maps(facts, as_of))
    series = shares_series(facts, as_of)
    px = price_at(prices, symbol, as_of)
    shares = shares_at(series, as_of)
    meta = meta or {}
    return {
        "symbol": symbol,
        "name": meta.get("name"), "sector": meta.get("sector"),
        "industry": meta.get("industry"),
        "market_cap": shares * px if shares is not None and px is not None else None,
        "yahoo_ev": None, "price": px,
        "shares_series": series,
        "annual": {"income": annual_income,
                   "balance": {end: payload for end, payload in balance.items()
                               if end in annual_income},
                   "cashflow": _section(cashflow_a)},
        "quarterly": {"income": _section(income_q), "balance": balance,
                      "cashflow": _section(cashflow_q)},
    }
