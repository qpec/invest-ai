"""The fundamentals-archive populator (design 2026-07-10). Ranking is a pure function of
the universe DataFrame; the job (jobs/populate.py) walks the ranking through the single
fetch door and the single store surface. No new pip dependency, no new fetch door."""
from __future__ import annotations

import pandas as pd

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
