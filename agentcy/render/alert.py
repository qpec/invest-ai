"""G.3 alert (the only unscheduled output). Single card (len==1) or storm bundle
(B.3.5, P5.10). WHAT THIS IS NOT is verbatim; the owner-quoted committed statement +
10-year excerpt land in owner_spans (lint-exempt, so an owner thesis that says "will
outgrow the S&P!" keeps its alert intact) while their HTML-escaped form is what ships.
Keyboard shows [Confirm broken] [Refute] only — Revise materializes on the daemon after
a recorded refute (tg-spec §3.3), never at render."""
from __future__ import annotations

import json

from agentcy.render import common as cm
from agentcy.render.contexts import AlertContext, AlertItemContext, RenderedOutput


def _keyboard(ask_id: str) -> str:
    """Two-button decision surface; Revise is withheld until an explicit refute (goalpost guard)."""
    return json.dumps({"inline_keyboard": [[
        {"text": "Confirm broken", "callback_data": f"alert:confirm:{ask_id}"},
        {"text": "Refute", "callback_data": f"alert:refute:{ask_id}"},
    ]]})


def _body_lines(it: AlertItemContext, *, esc: bool) -> list[str]:
    """G.3 card body, byte-exact from the elaboration. HTML skin escapes dynamic fields;
    markdown (git plain text) escapes nothing. Owner-quoted spans are recorded separately
    in owner_spans — here they ship escaped in the HTML skin (HTML safety ≠ lint)."""
    def e(s: str) -> str:
        return cm.esc(s) if esc else s

    lines = [
        f"WHAT YOU COMMITTED TO (thesis v{it.committed_version}, committed {it.committed_at}, verbatim):",
        f'  "{e(it.committed_statement_owner)}"',
        f"WHAT HAPPENED: {e(it.what_happened)}",
    ]
    if it.baseline_note:
        lines.append(f"  {e(it.baseline_note)}")
    lines += ["", cm.WHAT_THIS_IS_NOT.format(pct=it.price_move_pct), ""]
    lines += [
        f'YOU WROTE (10-year statement, v{it.committed_version}): "{e(it.ten_year_excerpt_owner)}"',
        "The question on the table: does this development invalidate that paragraph?",
        "",
        "YOUR OPTIONS (yours alone):",
        " (a) confirm broken → sell advice for the full position, cost basis ignored",
        " (b) refute → written evidence required; thesis returns to intact",
        " (c) revise → only after an explicit refute (goalpost guard)",
        'No response by the deadline → journaled as "alert ignored" (recorded, not judged',
        "today) and escalated in every daily letter. Status meanwhile: under_review.",
    ]
    return lines


def render_alert(ctx: AlertContext) -> RenderedOutput:
    if len(ctx.items) == 1:
        it = ctx.items[0]
        subject = (f"Trigger fired — {it.ticker} — {it.trigger_label} "
                   f"— decision by {ctx.deadline_label}")
        html = "<b>" + cm.esc(subject) + "</b>\n\n" + "\n".join(_body_lines(it, esc=True))
        md = "# " + subject + "\n\n" + "\n".join(_body_lines(it, esc=False))
        return RenderedOutput(
            telegram_html=html, markdown=md, output_class="alert",
            owner_spans=(it.committed_statement_owner, it.ten_year_excerpt_owner),
            ask_id=it.ask_id, reply_markup_json=_keyboard(it.ask_id))
    return _render_storm(ctx)


def _render_storm(ctx: AlertContext) -> RenderedOutput:   # implemented in P5.10
    raise NotImplementedError
