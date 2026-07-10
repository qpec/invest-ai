"""Scout v2 Stage-1 — deterministic four-pillar graded screening (design §1-§4, §8 item 1).

Pure math over the append-only fundamentals archive (fetch/store.py) + FinanceDatabase
categoricals. No LLM, no new dependency, no live network. Every metric traces to a
design-doc pillar (V/Q/D/M); veto runs before grading and SUPPRESSES vetoed names;
thin/stale data -> "insufficient data", never a silent 0.
"""
from __future__ import annotations

from datetime import datetime

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
