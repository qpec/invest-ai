"""Stage-1 tiered graded render (design §3, §4 Stage-1 output). Tier-sectioned, grade-sorted
within each tier, plus the cross-cutting 'Outside-tier A-grades' list (design §3 star), plus
the honest evidence note (design §9). Human-read only; never persisted (design §6). Two skins
built from ONE context (RF9): the md skin fences the monospace tables, the html skin wraps
them in <pre> — both from the same row lists. output_class 'notice' so lint's calm-register
bans apply; the whole evidence note rides in owner_spans so its 'outperformance' _BENCH token
is exempted (RF1), never run through the template-span checks."""
from __future__ import annotations

from dataclasses import dataclass

from agentcy.render import common as cm
from agentcy.render.contexts import RenderedOutput

_TIER_ORDER = ("Core", "Adjacent", "Outside")
_HEADER = ("Ticker", "Grade", "Comp", "V", "Q", "G", "D", "M")

_GRADE_FRAMING = (
    "This grade is quantitative evidence, not a thesis verdict: moat durability, management "
    "candor, and fad-risk are Stage-2 judgments still pending. A computed A is a strong "
    "lead to investigate, never a decision."
)

# REVIEW FIX B1 (populator design 5, wired-but-dormant currency guard): the statement
# reporting currency has no rule-compliant source, so the guard does not fire and design
# section 5 is NOT enforced. Print the honest cross-currency caveat alongside the grade.
_CURRENCY_CAVEAT = (
    "Cross-currency caveat: cross-currency names (mainly US-listed ADRs of foreign filers) "
    "may mis-rank on p_owner_fcf until a reporting-currency source lands; owner_fcf_yield is "
    "currency-agnostic and unaffected."
)


@dataclass(frozen=True)
class ScoutGradedContext:
    as_of_label: str
    graded: tuple                     # tuple[scout_grade.GradedName, ...]
    evidence_note: str


def _fmt_pillar(x) -> str:
    return "n/a" if x is None else f"{x:.1f}"


def _ranked(rows):
    """Gradable rows sorted by composite desc; suppressed rows (VETOED/INSUFFICIENT) excluded."""
    ok = [g for g in rows if g.composite is not None]
    return sorted(ok, key=lambda g: g.composite, reverse=True)


def _body_rows(ranked):
    """The table body for one tier — one row list, shared by both skins (RF9)."""
    return [(g.symbol, g.grade, f"{g.composite:.0f}",
             _fmt_pillar(g.v), _fmt_pillar(g.q), _fmt_pillar(g.g),
             _fmt_pillar(g.d), _fmt_pillar(g.m))
            for g in ranked]


def _segments(ctx: ScoutGradedContext):
    """Build the ordered document as a list of ('text', str) / ('table', rows) segments —
    the ONE context both skins render from (RF9). The title is emitted separately."""
    segs: list[tuple] = []
    for tier in _TIER_ORDER:
        tier_rows = [g for g in ctx.graded if g.tier == tier]
        ranked = _ranked(tier_rows)
        segs.append(("text", f"{tier} tier"))
        if ranked:
            segs.append(("table", _body_rows(ranked)))
            # A graded row can still carry a note — the -15 dilution penalty reason
            # (design §2: penalty flagged, not a veto). The composite already reflects
            # it; surface the reason so the hit is never silent.
            for g in ranked:
                if g.note:
                    segs.append(("text", f"  flagged - {g.symbol}: {g.note}"))
        else:
            segs.append(("text", "  (no gradable names)"))
        # suppressed names are named with their reason — never silently dropped
        for g in tier_rows:
            if g.grade == "VETOED":
                segs.append(("text", f"  suppressed - {g.symbol}: {g.note}"))
            elif g.grade == "INSUFFICIENT":
                segs.append(("text", f"  not graded - {g.symbol}: {g.note}"))
        segs.append(("text", ""))

    # Cross-cutting Outside-tier A-grades (design §3 star): circle-expansion candidates.
    outside_a = [g for g in ctx.graded if g.tier == "Outside" and g.grade == "A"]
    segs.append(("text", "Outside-tier A-grades (circle-expansion candidates):"))
    if outside_a:
        for g in sorted(outside_a, key=lambda g: g.composite, reverse=True):
            segs.append(("text", f"  * {g.symbol} - composite {g.composite:.0f} (A)"))
    else:
        segs.append(("text", "  (none this run)"))
    segs.append(("text", ""))
    segs.append(("text", _GRADE_FRAMING))
    segs.append(("text", ""))
    segs.append(("text", _CURRENCY_CAVEAT))
    segs.append(("text", ""))
    segs.append(("text", ctx.evidence_note))
    return segs


def render_scout_graded(ctx: ScoutGradedContext) -> RenderedOutput:
    title = f"The Scout - graded screen - {ctx.as_of_label}"
    segs = _segments(ctx)

    md_lines = ["# " + title, ""]
    html_lines = ["<b>" + cm.esc(title) + "</b>", ""]
    for kind, payload in segs:
        if kind == "table":
            md_lines.append(cm.pre_table(payload, header=_HEADER, skin="md"))
            html_lines.append(cm.pre_table(payload, header=_HEADER, skin="html"))
        else:
            md_lines.append(payload)
            html_lines.append(cm.esc(payload))

    return RenderedOutput(
        telegram_html="\n".join(html_lines),
        markdown="\n".join(md_lines),
        output_class="notice",
        owner_spans=(ctx.evidence_note,),  # RF1: whole note is the lint escape hatch
    )
