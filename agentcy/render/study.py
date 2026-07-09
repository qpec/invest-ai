"""F.3 Study digest (§3.9 / G.2 §8). Capped at one screen; NEVER performance numbers,
price echoes, or new ideas. The optional [Add a circle note] ForceReply affordance rides
here (ask kind N) — zero consequence for silence."""
from __future__ import annotations

import json

from agentcy.render import common as cm
from agentcy.render.contexts import RenderedOutput, StudyContext


def render_study(ctx: StudyContext) -> RenderedOutput:
    lines = [
        "The Study",
        "",
        f"Re-study — {ctx.restudy_ticker}: {ctx.restudy_excerpt}",
        f"  {ctx.restudy_question}",
        "",
        f"Mental model — {ctx.mental_model_prompt}",
    ]
    if ctx.journal_previews:
        lines.append("")
        lines.append("From the journal:")
        for p in ctx.journal_previews:
            lines.append(f"  • {p}")
    lines += ["", ctx.reading_line]
    if ctx.circle_note_ask_id:
        lines.append("Did anything expand or shrink the circle this week? (optional)")
    html = "<b>" + cm.esc(lines[0]) + "</b>\n\n" + "\n".join(cm.esc(l) for l in lines[2:])
    md = "# " + "\n".join(lines)
    reply = None
    if ctx.circle_note_ask_id:
        reply = json.dumps({"force_reply": True, "selective": True})
    return RenderedOutput(telegram_html=html, markdown=md, output_class="study",
                          ask_id=ctx.circle_note_ask_id, reply_markup_json=reply)
