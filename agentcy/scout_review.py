"""Scout Stage-2 (Part A) - the qualitative reviewer's agentcy-side logic (design
2026-07-11-scout-stage2-qualitative-reviewer-design.md). Shortlist selection, the
QualitativeReviewer interface + DeskReviewer adapter, the verdict dataclass + badges,
and the bounded one-band grade adjustment. NO LLM, NO new pip dependency; every function
READS scout_grade.GradedName and NEVER changes Stage-1 grading math. The Scout still only
surfaces; the Gate still decides."""
from __future__ import annotations

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
