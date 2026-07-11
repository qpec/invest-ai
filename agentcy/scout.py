"""The Scout (H) — idea generation, strictly human-triggered (FR14).

Universe: direct bz2 read of FinanceDatabase's equities file (pinned-SHA, ~3 lines
of pandas — NOT the pip package, NFR7). Screen: QV recipe via a lazy `[scout]`
import. Results are human-read and NEVER persisted as monitoring state (H).
"""
from __future__ import annotations

import bz2
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from agentcy import config, db


class UniverseSHAError(Exception):
    """H.1 — the universe file's SHA-256 does not match the pinned config value;
    an unpinned or tampered file is never trusted."""


def load_universe(path: Path, *, expect_sha: str) -> pd.DataFrame:
    """H.1 — read equities.bz2 directly, verifying SHA-256 against the pin first.
    Empty pin or mismatch raises UniverseSHAError (never a silent pass)."""
    path = Path(path)
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if not expect_sha or actual != expect_sha:
        raise UniverseSHAError(
            f"universe SHA mismatch: file {actual}, pinned '{expect_sha}'. "
            "Set config universe_pin_sha to the verified commit's file hash (H.1).")
    return pd.read_csv(io.BytesIO(bz2.decompress(raw)))


HONEST_EVIDENCE_NOTE = (
    "Honest evidence note: independent replications put quality-value screening at "
    "roughly 3-6%/yr gross outperformance with multi-year losing stretches - not the "
    "book's 30%. This screen surfaces cheap, capital-productive businesses; it "
    "promises nothing. Every candidate still passes the full Gate, and second-"
    "guessing the screen's valuation call destroys the edge - the Gate judges the "
    "framework, not price timing."
)

QV_TOP_N = 20
QV_ROIC_MIN = 15.0
QV_DEBT_TO_EQUITY_MAX = 1.0


@dataclass(frozen=True)
class Candidate:
    symbol: str
    ev_ebitda: float
    roic: float
    debt_to_equity: float


@dataclass(frozen=True)
class ScreenResult:
    """Human-read only; never persisted (H)."""
    recipe: str
    candidates: tuple[Candidate, ...]
    evidence_note: str


def _run_screener(recipe: str) -> pd.DataFrame:
    """The ONE lazy [scout]-extra import (FR14; keeps tradingview-screener off the
    runtime import graph). Monkeypatched in tests."""
    from tradingview_screener import Query, col  # noqa: F401  (lazy, [scout] extra)
    # QV recipe (H.2): cheapness leg + quality cut + guards. The concrete Query
    # column names track the screener's API; the recipe is documented, human-run,
    # delayed-data. Returns a DataFrame with the four columns run_qv reads.
    raise NotImplementedError("desk-only; monkeypatched in tests")


def run_qv(conn, *, universe_path=None) -> ScreenResult:
    """H.2 - QV screen: cheapness-leg-ranked top-20, intersected with the H.1
    universe, guards applied. Results are returned for human reading and NEVER
    persisted as monitoring state."""
    pin = config.get(conn, "universe_pin_sha")
    if universe_path is None:
        universe_path = Path(db.state_dir()) / "universe" / "equities.bz2"
    universe = load_universe(universe_path, expect_sha=pin)
    universe_symbols = set(universe["symbol"])

    raw = _run_screener("qv")
    df = raw[
        (raw["return_on_invested_capital"] > QV_ROIC_MIN)
        & (raw["debt_to_equity"] < QV_DEBT_TO_EQUITY_MAX)
        & (raw["symbol"].isin(universe_symbols))
    ].copy()
    # cheapness leg is load-bearing: ascending EV/EBITDA (MA-8), top 20
    df = df.sort_values("enterprise_value_ebitda_ttm", ascending=True).head(QV_TOP_N)
    candidates = tuple(
        Candidate(symbol=r["symbol"], ev_ebitda=float(r["enterprise_value_ebitda_ttm"]),
                  roic=float(r["return_on_invested_capital"]),
                  debt_to_equity=float(r["debt_to_equity"]))
        for _, r in df.iterrows())
    return ScreenResult(recipe="qv", candidates=candidates,
                        evidence_note=HONEST_EVIDENCE_NOTE)


@dataclass(frozen=True)
class GradedScreenResult:
    """Stage-1 graded screen output (design §4). Human-read only; never persisted (§6)."""
    recipe: str
    graded: tuple
    evidence_note: str


def run_graded(conn, *, universe_path=None, market_data=None, as_of) -> GradedScreenResult:
    """H/design §4 Stage-1: load the pinned universe, grade every name deterministically from
    cached fundamentals, return for human reading. NEVER persists monitoring state (§6).

    market_data=None (the CLI default) -> assemble it from the append-only archive (populator
    design 5): market_cap = latest price close x latest shares, total_debt/cash from the latest
    balance sheet. An explicit dict is still honored (tests/injection)."""
    from agentcy import scout_grade
    pin = config.get(conn, "universe_pin_sha")
    if universe_path is None:
        universe_path = Path(db.state_dir()) / "universe" / "equities.bz2"
    universe = load_universe(universe_path, expect_sha=pin)
    if market_data is None:
        market_data = scout_grade._market_data_from_archive(
            conn, [str(s) for s in universe["symbol"]], as_of=as_of)
    graded = scout_grade.grade_universe(conn, universe, market_data=market_data, as_of=as_of)
    return GradedScreenResult(recipe="grade", graded=tuple(graded),
                              evidence_note=HONEST_EVIDENCE_NOTE)
