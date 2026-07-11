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


# --- Axis badges (Task 5) ------------------------------------------------------
# ASCII badges (Plan note): [+] good, [~] soft, [x] flag, [t] tier-correction. ASCII-only so a
# badge never trips the render lint's red-glyph ban. Design glyph names map here.
_BADGE = {
    ("moat", "confirmed"): "[+]", ("moat", "not-evident"): "[~]",
    ("mgmt", "aligned"): "[+]", ("mgmt", "neutral"): "[~]", ("mgmt", "red-flag"): "[x]",
    ("fad", "clear"): "[+]", ("fad", "flag"): "[x]",
    ("tier", "ok"): "[+]",
}


def badges(verdict: Verdict) -> dict[str, str]:
    """Map each PRESENT axis to its ASCII badge; pending axes are omitted. A tier correction
    (any 'correction:*') badges as '[t]' (design tier-correction)."""
    out: dict[str, str] = {}
    for axis in ("moat", "mgmt", "fad", "tier"):
        value = getattr(verdict, axis)
        if value is None:
            continue
        if axis == "tier" and value.startswith("correction:"):
            out[axis] = "[t]"
        else:
            out[axis] = _BADGE[(axis, value)]
    return out


# --- The bounded one-band adjustment (Task 4) ----------------------------------
# Letter mirror of scout_grade._GRADE_BANDS (frozen + guarded Stage-1 grade table:
# ((80,"A"),(65,"B"),(50,"C"),(35,"D")), F implicit below 35), ordered low -> high so
# one band = one index step. Kept in sync deliberately: if the Stage-1 bands ever change,
# this tuple must change with them (RF4 anti-drift note).
_BANDS = ("F", "D", "C", "B", "A")            # low -> high; one band = one index step


def _shift_band(grade: str, step: int) -> str:
    """Move `grade` `step` bands (negative = toward F, positive = toward A), clamped."""
    i = _BANDS.index(grade)
    return _BANDS[max(0, min(len(_BANDS) - 1, i + step))]


def adjust_grade(graded: sg.GradedName, verdict: Verdict) -> tuple[str, str]:
    """Design Part A bounded one-band adjustment, from the badges. Demote one band on a fad
    flag OR a management red-flag; promote one band ONLY if all four axes are the good value
    AND min(V,Q,G,D,M) >= 50; otherwise unchanged. Demotion beats promotion. The COMPOSITE is
    never moved - only the letter, one band, always reason-printed (never silent). Pending
    axes never promote and (being never a flag value) never demote.

    Pillar gate note: the live model has FIVE scored pillars (V/Q/G/D/M; weights
    0.25/0.25/0.20/0.15/0.15). The design's 'no pillar < 50' rule predates the Stage-1.5
    Growth pillar and named only V/Q/D/M; RF1 corrects the gate to the full 5-pillar
    min(V,Q,G,D,M) >= 50 so a weak Growth pillar can block a promotion."""
    grade = graded.grade
    # Demotion (takes precedence): a fad flag or a management red-flag.
    if verdict.fad == "flag" or verdict.mgmt == "red-flag":
        cause = "fad flag" if verdict.fad == "flag" else "management red-flag"
        final = _shift_band(grade, -1)
        why = f" ({verdict.reason})" if verdict.reason else ""
        return final, f"demote one band ({grade} -> {final}): {cause}{why}"
    # Promotion: all four good AND no scored pillar (V/Q/G/D/M) below 50.
    all_good = (verdict.moat == "confirmed" and verdict.mgmt == "aligned"
                and verdict.fad == "clear" and verdict.tier == "ok")
    if all_good:
        pillars = [graded.v, graded.q, graded.g, graded.d, graded.m]
        scored = [p for p in pillars if p is not None]
        worst = min(scored) if scored else 0.0
        if worst >= 50.0:
            final = _shift_band(grade, +1)
            why = f" ({verdict.reason})" if verdict.reason else ""
            return final, f"promote one band ({grade} -> {final}): all four axes clear, no pillar < 50{why}"
        return grade, (f"no qualitative adjustment: all four axes clear but a pillar is "
                       f"below 50 ({worst:.0f}) - promotion gated")
    return grade, "no qualitative adjustment (axes pending or mixed; grade unchanged)"
