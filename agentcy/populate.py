"""The fundamentals-archive populator (design 2026-07-10). Ranking is a pure function of
the universe DataFrame; the job (jobs/populate.py) walks the ranking through the single
fetch door and the single store surface. No new pip dependency, no new fetch door."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from agentcy import db
from agentcy.fetch import store
from agentcy.freshness import DataState

# Highest-liquidity -> lowest; unknown/missing bands sort AFTER these (plan note 1).
_BAND_ORDER = ("mega_cap", "large_cap", "mid_cap", "small_cap")
_BAND_RANK = {b: i for i, b in enumerate(_BAND_ORDER)}
_UNKNOWN_RANK = len(_BAND_ORDER)  # every non-canonical/missing band shares this bucket


def _band_key(value) -> int:
    """Canonical band -> its liquidity rank; anything else (None/''/unknown) -> lowest."""
    if value is None:
        return _UNKNOWN_RANK
    return _BAND_RANK.get(str(value).strip().lower(), _UNKNOWN_RANK)


def rank_universe(universe: pd.DataFrame) -> list[str]:
    """Symbols ranked mega -> large -> mid -> small, unknown/missing band last, stable by
    symbol within a bucket (design 2). Deterministic: the SAME universe always yields the
    SAME order, so the nightly cursor is reproducible."""
    rows = universe.to_dict("records")
    ordered = sorted(rows, key=lambda r: (_band_key(r.get("market_cap")), str(r["symbol"])))
    return [str(r["symbol"]) for r in ordered]


def starter_set(universe: pd.DataFrame, *, size: int) -> list[str]:
    """The top ``size`` names by liquidity rank (design 2 starter set). size >= len ->
    the whole ranked universe."""
    return rank_universe(universe)[:size]


_STATEMENT_TYPES = ("income", "balance", "cashflow")
_MIN_PERIODS = 4         # >=4 quarterly periods per statement (design 4)
_DEAD_RETRY_DAYS = 90    # dead-list backstop (design 6, plan note 5)


def is_cached(conn, yf_ticker: str, *, as_of: datetime) -> bool:
    """Design 4 FETCH coverage (review fix M1: coverage, NOT gradability): >=4 quarterly
    periods across ALL three statements + a shares obs + a FRESH price bar (plan note 3).
    Anything missing -> not cached (a populate target). A cached name can still grade
    INSUFFICIENT if the pinned rows within those periods are absent."""
    for stype in _STATEMENT_TYPES:
        if len(db.fetch_statement_periods(conn, yf_ticker, stype)) < _MIN_PERIODS:
            return False
    if not db.fetch_shares_raw(conn, yf_ticker):
        return False
    return store.price_state(conn, yf_ticker, as_of=as_of) is DataState.FRESH


def _is_stale_covered(conn, yf_ticker: str, *, as_of: datetime) -> bool:
    """A covered name whose statements or price are STALE -> refresh-eligible (plan note 4)."""
    if store.price_state(conn, yf_ticker, as_of=as_of) is not DataState.FRESH:
        return True
    st = store.statement_history(conn, yf_ticker, "income", as_of=as_of)
    return st.state is not DataState.FRESH


def next_targets(conn, ranked, *, budget: int, as_of: datetime,
                 dead_after_failures: int = 3) -> list[str]:
    """The ordered nightly work list (design 4 cursor rule, cut to ``budget``):
      1. never-attempted names, in liquidity rank order;
      2. then STALE covered names, least-recently-refreshed first;
    minus dead-listed names (>= dead_after_failures failures since last ok) UNLESS their
    last attempt is older than the 90-day backstop (design 6, plan note 5)."""
    latest = db.fetch_universe_fetch_latest(conn)
    fails = db.fetch_universe_fetch_failure_counts(conn)

    def dead(t: str) -> bool:
        if fails.get(t, 0) < dead_after_failures:
            return False
        row = latest.get(t)
        if row is None:
            return True
        age = as_of - db.from_iso(row["last_attempt"])
        return age <= timedelta(days=_DEAD_RETRY_DAYS)  # still dead until the backstop

    never: list[str] = []
    refresh: list[tuple[str, str]] = []  # (ticker, last_attempt) for oldest-first sort
    for t in ranked:
        if dead(t):
            continue
        if t not in latest:
            never.append(t)
            continue
        if is_cached(conn, t, as_of=as_of):
            if _is_stale_covered(conn, t, as_of=as_of):
                refresh.append((t, latest[t]["last_attempt"]))
            continue
        # attempted before but not (yet) fully covered -> retry, treat as work
        never.append(t)
    refresh.sort(key=lambda pair: pair[1])  # oldest last_attempt first
    ordered = never + [t for t, _ in refresh]
    return ordered[:budget]
