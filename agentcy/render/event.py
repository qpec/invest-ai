"""D.3 event report (§2.4). Quiet outcome -> calm ack (owner-initiated only) + folds into
the next daily letter as one line; data-lag -> retry note + a statement that the owner's
prompted questions do not wait for the data. A FIRE is an Alert (§2.5), not an event
report — a fired trigger always escalates to the alert path and is never rendered here."""
from __future__ import annotations

from agentcy.render import common as cm
from agentcy.render.contexts import EventContext, RenderedOutput


def render_event(ctx: EventContext) -> RenderedOutput:
    if ctx.data_lag:
        lines = [
            f"{ctx.ticker} — {ctx.retry_note}",
            "Your prompted questions (below) do not wait for the data.",
        ]
    else:
        lines = [
            f"{ctx.ticker} — {ctx.event_kind} checked against your committed triggers.",
            f"{ctx.triggers_pass}/{ctx.triggers_total} pass. Thesis intact. No action needed.",
            "Full check archived. This also appears as one line in tomorrow's letter.",
        ]
    html = "\n".join(cm.esc(line) for line in lines)
    md = "\n".join(lines)
    return RenderedOutput(telegram_html=html, markdown=md, output_class="event")
