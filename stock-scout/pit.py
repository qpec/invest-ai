"""Point-in-time fundamentals adapter over EDGAR companyfacts (RECONSTRUCTION.md §5.9).

as_of_bundle() turns one raw bt_cache/facts/<SYM>.json payload (§3.6) into the exact §4.1
Bundle that scoring.py consumes live — EDGAR tags mapped to Yahoo-style row labels, the
§4.1 decoupling seam — under STRICT filed-date discipline: only facts filed <= as_of
exist, and the value used for a period is the latest-filed one (restatements honored,
lookahead impossible). Flow quarters: durations <= 100 days pass through as true
quarters; longer cumulatives (YTD / FY / broken-fiscal-year stubs) are differenced
against a prior CUMULATIVE only — same period-start, or a genuine cumulative (span >
100 days) whose start matches within +/-365 days for broken fiscal years (msg 44) —
and accepted only when the derived span is itself a quarter (<= 100 days), so neither a
prior-year YTD nor a DISCRETE sibling quarter can masquerade as the subtrahend; Q4 falls
out of FY minus the 9-month YTD through the same rule (no separate FY-minus-3-quarters
pass). Multi-class dei share counts are summed per filed date; an inconsistent filing
empties the SERIES so the M share-trend leg stays neutral in scoring (msg 44) while
shares_fallback() still yields a share count for the market cap, so the name grades
instead of vanishing as INSUFFICIENT (`shares_basis` records which path was used).

Prices: the §3.6 weekly grid carries BOTH the raw close and the adjusted close per bar.
Anything multiplied by a share count (market cap, own EV, MoS, WACC) MUST use the raw
close — adjusted closes are retroactively rescaled by every later split and dividend, so
building a historical market cap out of them silently imports the future. Total-return
math (NAV, forward returns, the benchmark track) uses adj_close. A legacy grid of plain
floats loads DEGRADED: the one value stands for both fields (grid_is_degraded() flags it).
No I/O, no network, no clock.
"""
from __future__ import annotations

from datetime import date

QUARTER_MAX_DAYS = 100         # §5.9: a duration this short IS a quarter (53-week-year safe)
YTD_START_WINDOW_DAYS = 365    # §5.9: prior-YTD start-match tolerance (broken fiscal years)
SAME_START_TOLERANCE_DAYS = 7  # 52/53-week fiscal wobble still counts as the same start
ANNUAL_MIN_DAYS, ANNUAL_MAX_DAYS = 330, 400   # 52-week (364d) .. sloppy calendar annual
MULTICLASS_SPREAD_DAYS = 45    # cover-page class rows this close still sum to one count

PRICE_FIELDS = ("close", "adj_close")   # raw (share-count math) / adjusted (total return)
DEFAULT_PRICE_FIELD = "close"
BARS_KEY, SYMBOL_KEY = "bars", "symbol"  # §3.6 price-file envelope (true symbol inside)
SPLITS_KEY = "splits"                    # §3.6 split events, captured on the same bar fetch

# §5.9 tag fallback chains (msg 44 adversarial fixes pinned; first present wins per period).
_INCOME_CONCEPTS = {
    "Total Revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax",
                      "Revenues", "SalesRevenueNet"),        # ADBE reports Revenues
    "EBIT": ("OperatingIncomeLoss",),
    "Operating Income": ("OperatingIncomeLoss",),            # §4.1 Buffett-checklist chain head
    "Gross Profit": ("GrossProfit",),                        # absent -> derived from cost of revenue
    "Cost Of Revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold",   # gross-profit fallback
                        "CostOfServices", "CostOfGoodsSold", "CostOfSales"),
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


def _is_prior_cumulative(start: str, start2: str, end2: str) -> bool:
    """§5.9 subtrahend test: may the period (start2, end2) be subtracted from a cumulative
    starting at `start`? Only a prior CUMULATIVE qualifies — either it starts on the same
    day (within SAME_START_TOLERANCE_DAYS for 52/53-week wobble), in which case it IS this
    fiscal period's shorter YTD whatever its length (the 3-month YTD doubles as Q1), or it
    is itself materially longer than a quarter and its start matches within the +/-365d
    broken-fiscal-year window (msg 44). A DISCRETE sibling quarter with a different start
    is refused: 9M-YTD minus a discrete Q2 would book Q1+Q3 as Q3. The tolerance is orders
    of magnitude below a quarter, so it can never re-admit one."""
    if abs(_days(start, start2)) <= SAME_START_TOLERANCE_DAYS:
        return True
    return (_days(start2, end2) > QUARTER_MAX_DAYS
            and abs(_days(start, start2)) <= YTD_START_WINDOW_DAYS)


def quarterly_flows(periods: dict) -> dict:
    """§5.9 flow-quarter derivation over {(start, end): value}: durations <= 100 days pass
    through as true quarters; a longer cumulative becomes the quarter ending at its end by
    subtracting a prior CUMULATIVE per _is_prior_cumulative (start drift preferred smallest,
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
            if not _is_prior_cumulative(start, start2, end2):
                continue
            rank = (abs(_days(start, start2)), -date.fromisoformat(end2).toordinal())
            if best is None or rank < best[0]:
                best = (rank, val - val2)
        if best is not None:
            quarters[end] = best[1]
    return quarters


def _gross_profit(income: dict) -> dict:
    """Gross profit per period: the tagged GrossProfit, else revenue minus cost of revenue.

    Filers are not required to present a gross-profit line, and many tag only the cost
    side (Exelixis: CostOfGoodsAndServicesSold, no recent GrossProfit). Because the Q
    gross-margin leg is a REQUIRED metric (§4.6), an untagged line suspended the whole
    name as INSUFFICIENT on real filings — so the derivation is what keeps EDGAR-fed names
    scoreable. A filer that tags neither (Medpace, a CRO reporting direct costs under a
    custom tag) genuinely has no gross margin and still suspends — honest, not silent."""
    tagged = income.get("Gross Profit") or {}
    revenue = income.get("Total Revenue") or {}
    cost = income.get("Cost Of Revenue") or {}
    out = dict(tagged)
    for end, rev in revenue.items():
        if end not in out and end in cost:
            out[end] = rev - cost[end]
    return out


DEBT_CARRY_FORWARD_DAYS = 400   # a debt balance is assumed to persist about a year


def _debt_with_unlevered_dates(debt: dict, maps: dict) -> dict:
    """Fill Total Debt on properly-tagged balance dates that carry no debt tag at all.

    EDGAR simply stops carrying LongTermDebt* once a filer has repaid its borrowings, so a
    net-cash company (Exelixis, Medpace — both verified on real filings) had NO Total Debt
    at its recent balance dates. That made EV incomputable and the name INSUFFICIENT at
    every tick: the fortress balance sheets this framework prizes most were the ones
    silently dropped from the backtest.

    A date is treated as unlevered ONLY when the filing is otherwise properly tagged (total
    assets AND cash present) — an untagged filing stays absent rather than being called
    debt-free. The most recent earlier debt observation within DEBT_CARRY_FORWARD_DAYS is
    carried forward first, so the error always leans toward MORE leverage, never less: a
    tagging gap can therefore never sneak a levered company past the §4.4 leverage veto."""
    assets, cash = maps.get("Total Assets") or {}, maps.get("Cash And Cash Equivalents") or {}
    observed = sorted(debt)
    out = dict(debt)
    for end in sorted(set(assets) & set(cash)):
        if end in out:
            continue
        prior = [d for d in observed if d < end]
        if prior and _days(prior[-1], end) <= DEBT_CARRY_FORWARD_DAYS:
            out[end] = debt[prior[-1]]          # conservative: assume the debt persists
        else:
            out[end] = 0.0                      # properly tagged and no debt in sight
    return out


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
    maps["Total Debt"] = _debt_with_unlevered_dates(debt, maps)
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


def _shares_by_filed(facts: dict, as_of: str) -> dict:
    """Visible dei share rows grouped per filed date: {filed: [(measurement date, count)]},
    filed-date discipline applied (filed > as_of does not exist)."""
    by_filed = {}
    for entry in _unit_entries(facts, "dei", _SHARES_TAG):
        filed, end, val = entry.get("filed"), entry.get("end"), entry.get("val")
        if filed is None or end is None or val is None or filed > as_of:
            continue
        by_filed.setdefault(filed, []).append((end, float(val)))
    return by_filed


def shares_series(facts: dict, as_of) -> list:
    """§5.9 dei EntityCommonStockSharesOutstanding -> ascending [[date, count], ...]:
    class rows summed per filed date, latest filed wins per measurement date; a filing
    reporting more than one measurement date is inconsistent -> [] (empty series, so the
    M share-trend leg suspends to neutral in scoring, msg 44 — the market cap then comes
    from shares_fallback, so the name still grades)."""
    by_filed = _shares_by_filed(facts, _iso(as_of))
    series = {}
    for filed in sorted(by_filed):                 # ascending: the latest filed wins per end
        observations = by_filed[filed]
        if len({end for end, _ in observations}) != 1:
            return []
        series[observations[0][0]] = sum(val for _, val in observations)
    return [[end, series[end]] for end in sorted(series)]


def shares_fallback(facts: dict, as_of) -> tuple[float | None, str | None]:
    """§5.9 multi-class fallback (the reachable half of msg 44's "multi-class-shares-
    fallback met neutrale M-leg"): the best share count knowable at as_of when
    shares_series() refuses to build a trend series. The latest filed date <= as_of wins;
    its class rows are summed when they were all measured within MULTICLASS_SPREAD_DAYS of
    each other (an ordinary cover page counts its classes days apart -> "fallback-sum"),
    otherwise they cannot be one company-wide count and the largest single class stands in
    ("fallback-largest"). Returns (count, basis), (None, None) when nothing is knowable.
    The SERIES stays empty either way — the M share-trend leg stays neutral — but the name
    keeps a market cap and therefore GRADES instead of silently suspending."""
    by_filed = _shares_by_filed(facts, _iso(as_of))
    if not by_filed:
        return None, None
    observations = by_filed[max(by_filed)]
    ends = [end for end, _ in observations]
    if _days(min(ends), max(ends)) <= MULTICLASS_SPREAD_DAYS:
        return sum(val for _, val in observations), "fallback-sum"
    return max(val for _, val in observations), "fallback-largest"


def shares_at(series: list, as_of) -> float | None:
    """Last share observation dated at or before as_of from an ascending §5.9 series."""
    as_of = _iso(as_of)
    best = None
    for day, val in series:
        if day <= as_of:
            best = val
    return best


def bar_value(bar, field: str = DEFAULT_PRICE_FIELD) -> float | None:
    """One §3.6 price bar -> the requested field. A current bar is
    {"close": raw, "adj_close": adjusted}; a bar missing the asked-for field falls back to
    the other one, and a LEGACY plain-float bar (grids written before the split-safe
    format) stands for both fields — degraded, because that single value was an adjusted
    close, so market caps built from it carry every later split/dividend rescaling."""
    if isinstance(bar, dict):
        val = bar.get(field)
        if val is None:
            val = bar.get("adj_close" if field == "close" else "close")
        return None if val is None else float(val)
    return None if bar is None else float(bar)


def grid_is_degraded(grid: dict) -> bool:
    """True when any bar in a §3.6 grid has no raw close of its own — a legacy float bar,
    or an adjusted-only bar written when Yahoo would not hand over the raw column. The
    caller must disclose that market caps built on it are split/dividend-contaminated."""
    return any(not isinstance(bar, dict) or bar.get("close") is None
               for bar in (grid or {}).values())


def price_at(prices: dict, symbol: str, day, field: str = DEFAULT_PRICE_FIELD) -> float | None:
    """Last weekly bar at or before `day` from the §3.6 grid ({symbol: {date: bar}}), read
    on `field`: "close" (RAW, the only price that may multiply a share count) or
    "adj_close" (total return: NAV, forward returns, benchmark). None when the symbol has
    no bar at or before `day`."""
    grid = prices.get(symbol) or {}
    day = _iso(day)
    best = None
    for bar in grid:
        if bar <= day and (best is None or bar > best):
            best = bar
    return bar_value(grid[best], field) if best is not None else None


# ----------------------------------------------- §3.6 cache-file shapes (writer + reader)

def price_file(symbol: str, bars: dict, splits: dict | None = None) -> dict:
    """The §3.6 prices/<SYM>.json payload: the TRUE symbol next to the date-keyed bars, so
    a sanitized filename ("BRK/B" -> BRK-B.json) round-trips back to its universe symbol,
    plus the split events Yahoo returned on the same actions=True bar fetch (§3.6 splits)."""
    return {SYMBOL_KEY: symbol, BARS_KEY: bars, SPLITS_KEY: dict(splits or {})}


def load_price_file(payload: dict) -> tuple[str | None, dict, dict]:
    """A prices/<SYM>.json payload -> (symbol or None, {date: bar}, {date: split ratio}).
    Accepts the current envelope and both legacy shapes (a bare date-keyed map of floats or
    of bars), where the symbol is unknown (the caller falls back to the filename stem) and
    no splits were recorded."""
    if not isinstance(payload, dict):
        return None, {}, {}
    if BARS_KEY in payload:
        return (payload.get(SYMBOL_KEY), payload.get(BARS_KEY) or {},
                payload.get(SPLITS_KEY) or {})
    return (payload.get(SYMBOL_KEY),
            {key: val for key, val in payload.items()
             if key not in (SYMBOL_KEY, SPLITS_KEY)},
            payload.get(SPLITS_KEY) or {})


def splits_as_of(splits: dict, as_of) -> dict:
    """§5.9 point-in-time split history: only events ON OR BEFORE as_of. A split after
    as_of was unknowable then and must never restate a share count at that tick; scoring's
    `adjusted_shares_series` then rescales each observation into as_of's share terms
    (it counts only splits strictly after each observation's own date)."""
    day = _iso(as_of)
    out = {}
    for event, raw in (splits or {}).items():
        try:
            ratio = float(raw)
        except (TypeError, ValueError):
            continue
        if ratio > 0 and str(event) <= day:
            out[str(event)] = ratio
    return out


def cache_stem(symbol: str) -> str:
    """The §3.2/§3.6 cache filename stem for a symbol ('/' -> '-', dots kept) — a pure
    mirror of populate.cache_filename so the offline loader can REVERSE the sanitization
    (map BRK-B.json back to the universe's "BRK/B") without importing the yfinance-backed
    writer. tests/test_pit.py pins the two rules identical."""
    return symbol.replace("/", "-")


def facts_symbol(payload: dict) -> str | None:
    """The true symbol annotated onto a facts/<SYM>.json payload by bt_fetch (companyfacts
    itself carries only cik/entityName), or None for a file written before the annotation."""
    return (payload or {}).get(SYMBOL_KEY)


def quarter_ends(spy_prices: dict, start, end) -> list:
    """§5.10 rebalance grid: the last weekly bar date per calendar quarter within
    [start, end], from the benchmark's {date: bar} price grid (dates only, no values)."""
    start, end = _iso(start), _iso(end)
    by_quarter = {}
    for day in spy_prices:
        if start <= day <= end:
            d = date.fromisoformat(day)
            key = (d.year, (d.month - 1) // 3)
            if key not in by_quarter or day > by_quarter[key]:
                by_quarter[key] = day
    return [by_quarter[key] for key in sorted(by_quarter)]


def as_of_bundle(facts: dict, symbol: str, meta: dict, as_of, prices: dict,
                 splits: dict | None = None) -> dict | None:
    """§5.9: EDGAR companyfacts -> the §4.1 Bundle as it was knowable on as_of, or None
    when no annual income period is visible yet (a pre-first-10-K name is not scoreable).
    market_cap = share count at as_of x the RAW weekly close at as_of — as-reported dei
    shares against an as-traded price, never the adjusted close (that one is rewritten by
    every later split/dividend and would import the future into every historical tick).
    The share count comes from the trend series, else from shares_fallback; `shares_basis`
    ("series" | "fallback-sum" | "fallback-largest" | None) records which, so the multi-
    class path is auditable. yahoo_ev is None by construction (no Yahoo in the PIT world —
    the EV_GAP flag never fires).

    `splits` ({symbol: {date: ratio}}, §3.6) carries the split events Yahoo returned on the
    same bar fetch; only those ON OR BEFORE as_of reach the bundle, so scoring restates the
    as-reported dei share counts into as_of's share terms. Without it a 2:1 split reads as
    +100%/yr dilution at every tick and trips the §4.4 hard dilution veto (§6.14)."""
    as_of = _iso(as_of)
    if not facts or not (facts.get("facts") or {}):
        return None
    income_a, income_q = _flow_maps(facts, _INCOME_CONCEPTS, as_of)
    cashflow_a, cashflow_q = _flow_maps(facts, _CASHFLOW_CONCEPTS, as_of)
    for cf in (cashflow_a, cashflow_q):   # EDGAR payments are outflow-positive; Yahoo is negative
        cf["Capital Expenditure"] = {end: -val
                                     for end, val in cf["Capital Expenditure"].items()}
    for income in (income_a, income_q):   # gross profit: tagged, else revenue - cost of revenue
        income["Gross Profit"] = _gross_profit(income)
        income.pop("Cost Of Revenue", None)
    for income, cf in ((income_a, cashflow_a), (income_q, cashflow_q)):  # §5.9 EBITDA = EBIT + D&A
        da = cf["Depreciation And Amortization"]
        income["EBITDA"] = {end: val + da[end]
                           for end, val in income["EBIT"].items() if end in da}
    annual_income = _section(income_a)
    if not annual_income:
        return None
    balance = _section(_balance_maps(facts, as_of))
    series = shares_series(facts, as_of)
    px = price_at(prices, symbol, as_of, DEFAULT_PRICE_FIELD)   # RAW close, never adjusted
    shares, shares_basis = shares_at(series, as_of), "series"
    if shares is None:                    # empty/inconsistent series -> best count at as_of
        shares, shares_basis = shares_fallback(facts, as_of)
    meta = meta or {}
    return {
        "symbol": symbol,
        "name": meta.get("name"), "sector": meta.get("sector"),
        "industry": meta.get("industry"),
        "market_cap": shares * px if shares is not None and px is not None else None,
        "yahoo_ev": None, "price": px,
        "shares_series": series, "shares_basis": shares_basis,
        "splits": splits_as_of((splits or {}).get(symbol) or {}, as_of),
        "annual": {"income": annual_income,
                   "balance": {end: payload for end, payload in balance.items()
                               if end in annual_income},
                   "cashflow": _section(cashflow_a)},
        "quarterly": {"income": _section(income_q), "balance": balance,
                      "cashflow": _section(cashflow_q)},
    }
