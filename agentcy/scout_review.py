"""Scout Stage-2 (Part A) - the qualitative reviewer's agentcy-side logic (design
2026-07-11-scout-stage2-qualitative-reviewer-design.md). Shortlist selection, the
QualitativeReviewer interface + DeskReviewer adapter, the verdict dataclass + badges,
and the bounded one-band grade adjustment. NO LLM, NO new pip dependency; every function
READS scout_grade.GradedName and NEVER changes Stage-1 grading math. The Scout still only
surfaces; the Gate still decides."""
from __future__ import annotations

import abc
from dataclasses import dataclass

from agentcy import scout_grade as sg

SHORTLIST_PER_TIER = 10                       # design §4: top 10 per tier (a module constant, Plan note)
_TIER_ORDER = {"Core": 0, "Adjacent": 1, "Outside": 2}
_GRADABLE = frozenset({"A", "B", "C", "D", "F"})


def _gradable(g: sg.GradedName) -> bool:
    """A name is shortlist-eligible only if it graded to a letter (VETOED/INSUFFICIENT out)."""
    return g.grade in _GRADABLE and g.composite is not None


def _order_key(g: sg.GradedName):
    """Deterministic: tier lane, then composite desc, then ticker asc."""
    return (_TIER_ORDER.get(g.tier, 99), -g.composite, g.symbol)


def select_shortlist(graded, *, per_tier: int = SHORTLIST_PER_TIER) -> list[sg.GradedName]:
    """Design §4 shortlist: top `per_tier` by composite within each tier PLUS every
    Outside-tier A-grade, VETOED/INSUFFICIENT excluded, deterministic order. Pure READ over
    GradedName - never mutates grading (Plan note)."""
    eligible = [g for g in graded if _gradable(g)]
    picked: dict[str, sg.GradedName] = {}
    by_tier: dict[str, list[sg.GradedName]] = {}
    for g in eligible:
        by_tier.setdefault(g.tier, []).append(g)
    for tier, rows in by_tier.items():
        rows_sorted = sorted(rows, key=_order_key)
        for g in rows_sorted[:per_tier]:
            picked[g.symbol] = g
    # Outside-tier A star (design §3): included even past the top-per-tier cut.
    for g in eligible:
        if g.tier == "Outside" and g.grade == "A":
            picked[g.symbol] = g
    return sorted(picked.values(), key=_order_key)


# --- The qualitative review seam (Task 2) --------------------------------------
# The four Constitution-grounded axes (design "four questions"). Each verdict axis is
# nullable = pending; a pending axis is never faked into a call (FR9).
_MOAT_VALUES = frozenset({"confirmed", "not-evident"})
_MGMT_VALUES = frozenset({"aligned", "neutral", "red-flag"})
_FAD_VALUES = frozenset({"clear", "flag"})
_TIER_CORRECTION_TARGETS = frozenset({"Core", "Adjacent", "Outside"})


def _valid_tier(value: str) -> bool:
    if value == "ok":
        return True
    if value.startswith("correction:"):
        return value.split(":", 1)[1] in _TIER_CORRECTION_TARGETS
    return False


@dataclass(frozen=True)
class Verdict:
    """The four Constitution-grounded axes (design 'four questions'); each None = pending,
    never faked (FR9). moat: confirmed|not-evident. mgmt: aligned|neutral|red-flag.
    fad: clear|flag. tier: ok|correction:<Core|Adjacent|Outside>. reason always printed."""
    moat: str | None = None
    mgmt: str | None = None
    fad: str | None = None
    tier: str | None = None
    reason: str | None = None

    def __post_init__(self):
        if self.moat is not None and self.moat not in _MOAT_VALUES:
            raise ValueError(f"moat must be in {sorted(_MOAT_VALUES)} or None: {self.moat!r}")
        if self.mgmt is not None and self.mgmt not in _MGMT_VALUES:
            raise ValueError(f"mgmt must be in {sorted(_MGMT_VALUES)} or None: {self.mgmt!r}")
        if self.fad is not None and self.fad not in _FAD_VALUES:
            raise ValueError(f"fad must be in {sorted(_FAD_VALUES)} or None: {self.fad!r}")
        if self.tier is not None and not _valid_tier(self.tier):
            raise ValueError(f"tier must be 'ok' or 'correction:<Core|Adjacent|Outside>' or None: {self.tier!r}")


class QualitativeReviewer(abc.ABC):
    """The Stage-2 review seam (design Part A). v1 = DeskReviewer (recorded verdicts, no LLM);
    an API adapter is a future slot behind this same interface (NOT built - Explicit follow-ons)."""

    @abc.abstractmethod
    def review(self, ticker: str) -> Verdict:
        ...


class DeskReviewer(QualitativeReviewer):
    """v1 adapter: input is already-recorded verdicts (the desk / claudeclaw path). No LLM.
    An unrecorded ticker returns an all-pending Verdict (never faked, FR9)."""

    def __init__(self, recorded: dict[str, Verdict]):
        self._recorded = dict(recorded)

    def review(self, ticker: str) -> Verdict:
        return self._recorded.get(ticker, Verdict())
