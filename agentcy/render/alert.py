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


def _render_storm(ctx: AlertContext) -> RenderedOutput:
    """B.3.5 storm bundle: several theses fire on one market-wide day → ONE alert,
    items ranked by position weight, one shared deadline. The bundle quotes only the
    trigger label + the template-authored `what_happened` fact; the owner's verbatim
    committed statement and 10-year words surface only when an item is expanded into its
    own single card (the daemon re-renders via render_alert with a one-item context), so
    owner_spans=() here.

    Subject and intro are byte-exact from the elaboration storm variant
    (tg-spec §B.3.5, lines 302-305) — no invented copy. The alert-class lint recognizes
    this variant's own verbatim price-disownership ('A market-wide move can fire several
    theses at once', the storm's structural stand-in for the single card's WHAT-THIS-IS-NOT
    block) and its deadline framing ('one decision window, by …'), so the sacred copy ships
    unaltered and the fail-closed lint still passes (see lint._ALERT_PRICE_DISOWNED /
    _ALERT_DEADLINE_FRAMED)."""
    n = len(ctx.items)
    subject = f"Triggers fired — {n} theses — one decision window, by {ctx.deadline_label}"
    intro = ("A market-wide move can fire several theses at once. Take them in order of weight;\n"
             "there is no rush beyond the shared deadline. Each is a separate decision.")
    ranked = sorted(ctx.items, key=lambda i: i.weight_pct, reverse=True)
    body_lines = []
    for idx, it in enumerate(ranked, 1):
        wt = f"({it.weight_pct:g}% of book)" if idx == 1 else f"({it.weight_pct:g}%)"
        body_lines.append(f"{idx}. {it.ticker} {wt} — {it.trigger_label}: {it.what_happened}")
    tail = ("Cost basis is not shown for any of these and will not be considered.\n"
            "Open each below to see its committed statement and your 10-year words.")
    plain = [intro, ""] + body_lines + ["", tail]
    html = "<b>" + cm.esc(subject) + "</b>\n\n" + "\n".join(cm.esc(line) for line in plain)
    md = "# " + subject + "\n\n" + "\n".join(plain)
    kb = [[{"text": f"{idx}. {it.ticker}", "callback_data": f"alert:open:{it.ask_id}"}]
          for idx, it in enumerate(ranked, 1)]
    return RenderedOutput(telegram_html=html, markdown=md, output_class="alert",
                          owner_spans=(), ask_id=ranked[0].ask_id,
                          reply_markup_json=json.dumps({"inline_keyboard": kb}))
