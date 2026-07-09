"""C.6 Gate verdict document. Sizing advice from the E.3 conviction table (computed
upstream, arrives as suggested_max_weight_pct). No benchmark/cost-basis fields exist;
the invitation closer keeps the sizing line non-imperative so the register lint passes."""
from __future__ import annotations

from agentcy.render import common as cm
from agentcy.render.contexts import GateContext, RenderedOutput


def render_gate(ctx: GateContext) -> RenderedOutput:
    title = f"Gate verdict — {ctx.ticker} — {ctx.verdict}"
    body: list[str] = []
    if ctx.reason_class:
        body.append(f"Reason: {ctx.reason_class}.")
    body += ["", "Dossier:"]
    for k, v in ctx.dossier_summary.items():
        body.append(f"  {k}: {v}")
    if ctx.suggested_max_weight_pct is not None:
        body += ["", f"Suggested max weight: {ctx.suggested_max_weight_pct:g}% "
                     f"(from your conviction table; {cm.INVITATION_CLOSER})"]
    if ctx.standing_questions:
        body += ["", "Standing questions:"]
        body += [f"  • {q}" for q in ctx.standing_questions]
    html = "<b>" + cm.esc(title) + "</b>\n\n" + "\n".join(cm.esc(l) for l in body)
    md = "# " + title + "\n" + "\n".join(body)
    return RenderedOutput(telegram_html=html, markdown=md, output_class="gate")
