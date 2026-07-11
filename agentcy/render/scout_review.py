"""Stage-2 annotated shortlist render (design 2026-07-11 Part A): per name, the deterministic
grade -> badges -> one-band-adjusted final grade + reason, plus the honest evidence note. Two
skins from ONE context; lint-clean (output_class 'notice'); the whole evidence note rides in
owner_spans (RF1) so its benchmark token is exempt. Review artifact only - NEVER a monitoring
write. A name with no verdicts renders unchanged with 'qualitative: pending'."""
from __future__ import annotations

from dataclasses import dataclass

from agentcy import scout_review as sr
from agentcy.render import common as cm
from agentcy.render.contexts import RenderedOutput

_HEADER = ("Ticker", "Tier", "Det", "Final", "Qualitative")


@dataclass(frozen=True)
class ScoutReviewContext:
    as_of_label: str
    shortlist: tuple                     # tuple[scout_grade.GradedName, ...] (already selected + ordered)
    verdicts: dict                       # {ticker: scout_review.Verdict}
    evidence_note: str


def _badge_str(verdict: sr.Verdict) -> str:
    """ASCII badge summary for a name's four axes; 'pending' when no axis is recorded yet.
    Each present axis renders as `axis<glyph>` (glyphs are the ASCII brackets [+]/[~]/[x]/[t]
    from scout_review.badges, so the string never trips the render lint's red-glyph ban)."""
    b = sr.badges(verdict)
    if not b:
        return "pending"
    return " ".join(f"{axis}{glyph}" for axis, glyph in b.items())


def _rows(ctx: ScoutReviewContext):
    """One table body + one per-name reason line list, shared by both skins (RF9). Per name:
    the deterministic grade, the one-band-adjusted final grade, and the badge summary; the
    reason (template text, NOT owner_spans per RF3) rides below as a plain line."""
    body = []
    reasons = []
    for g in ctx.shortlist:
        verdict = ctx.verdicts.get(g.symbol, sr.Verdict())
        final, reason = sr.adjust_grade(g, verdict)
        body.append((g.symbol, g.tier, g.grade, final, _badge_str(verdict)))
        reasons.append(f"  {g.symbol}: {reason}")
    return body, reasons


def render_scout_review(ctx: ScoutReviewContext) -> RenderedOutput:
    title = f"The Scout - Stage-2 annotated shortlist - {ctx.as_of_label}"
    body, reasons = _rows(ctx)
    segs: list[tuple] = [("table", body)]
    for r in reasons:
        segs.append(("text", r))
    segs.append(("text", ""))
    segs.append(("text", ctx.evidence_note))

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
        owner_spans=(ctx.evidence_note,),   # RF1: the whole note is the lint escape hatch
    )
