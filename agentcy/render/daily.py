"""G.1 daily letter + /status card (contract §3.16/§3.17). Pure: DailyContext/StatusContext
in, RenderedOutput out. Two skins from one render; HTML escapes every dynamic field."""
from __future__ import annotations

from agentcy.render import common as cm
from agentcy.render.contexts import (DailyContext, HeaderBlock, OpportunityLine,
                                     RenderedOutput, StatusContext)

_MAX_OPPS = 3   # §2.0: daily caps opportunities at 3 by weight; tail line for the rest


def _fmt_mult(m: float | None) -> str:
    return "n/a" if m is None else f"{m:g}×"


def _header_block(h: HeaderBlock) -> tuple[str, str]:
    """Two header lines, identical text both skins (esc applied for html)."""
    band = f"band {h.cash_band_low:g}–{h.cash_band_high:g}%"
    tick = "✓" if h.cash_in_band else "×"
    line1 = f"Snapshot: {h.snapshot_line} · Prices: {h.prices_line}"
    line2 = (f"Cash {h.cash_pct:g}% ({band} {tick}) · "
             f"{h.n_framework} framework, {h.n_backfill} backfill pending, "
             f"{h.n_outside} outside-framework")
    return line1, line2


def _opp_lines(opps: tuple[OpportunityLine, ...], more: int) -> list[str]:
    out: list[str] = []
    if not opps:
        return out
    out.append("OPPORTUNITIES (held intact theses, cheap vs YOUR anchor — this is what you wait for):")
    for o in opps[:_MAX_OPPS]:
        if o.suspended_note:
            out.append(f"• {o.ticker} — check suspended: {o.suspended_note}")
            continue
        sale = ("ON SALE — ≥20% below your own anchor." if o.kind == "on_sale"
                else "Fair entry reached vs your own anchor.")
        out.append(f"• {o.ticker} — {_fmt_mult(o.multiple)} P/FCF vs your fair band "
                   f"{o.band_low:g}–{o.band_high:g}× (thesis v{o.thesis_version}, intact, "
                   f"{o.triggers_pass}/{o.triggers_total} triggers pass):")
        out.append(f"  {sale}")
        out.append(f"  Re-read the thesis first; {cm.INVITATION_CLOSER}")
    if more > 0:
        out.append(f"+{more} more in the weekly review.")
    return out


def _subject(ctx: DailyContext) -> str:
    label = ctx.header.date_label if ctx.header else cm.ams_date_label(ctx.as_of)
    if ctx.kind == "full":
        tail = "✓ No action needed" if not ctx.open_loops else "decisions waiting"
        return f"Daily letter — {label} — {tail}"
    if ctx.kind == "pulse":
        return f"Daily letter — {label} — markets closed"
    if ctx.kind == "degraded":
        return f"Daily letter — {label} — checks suspended"
    return f"Daily letter — {label} — no checks performed"


def _assemble(subject: str, lines: list[str], *, banner: str | None) -> tuple[str, str]:
    md = "# " + subject + "\n\n" + "\n".join(lines)
    html = f"<b>{cm.esc(subject)}</b>\n\n" + "\n".join(cm.esc(l) for l in lines)
    if banner:
        html = f"{cm.esc(banner)}\n" + html
        md = f"{banner}\n\n" + md
    return html, md


def render_daily(ctx: DailyContext) -> RenderedOutput:
    subject = _subject(ctx)
    lines: list[str] = []

    if ctx.kind == "total_failure":
        lines.append("Data sources unavailable since the last good run; last known state; "
                     "no checks performed.")
        lines.append(cm.DEGRADED_LINE)
        for dl in ctx.data_lines:
            lines.append(dl)
    elif ctx.kind == "degraded":
        # verdict_line names the "stale since" fact; data_lines add specifics
        lines.append(ctx.verdict_line)
        lines.append(cm.DEGRADED_LINE)
        for dl in ctx.data_lines:
            lines.append(dl)
    elif ctx.kind == "pulse":
        # two-line weekend heartbeat: verdict names the closed market; data health tick
        lines.append(ctx.verdict_line)
        lines.append(f"{ctx.open_items_count} open items; "
                     + ("; ".join(ctx.data_lines) if ctx.data_lines else "data health ✓"))
    else:  # full
        if ctx.header is not None:            # header injected by the job; absent on catch-up
            h1, h2 = _header_block(ctx.header)
            lines += [h1, h2, ""]
        lines.append(f"✓ {ctx.verdict_line}")
        # open-loop escalations head the actionable region (alert_ignored first, B.3.3)
        for ol in ctx.open_loops:
            lines.append(f"OPEN LOOP [{ol.ask_id}] — {ol.label} ({ol.age_days}d).")
        opp = _opp_lines(ctx.opportunities, ctx.more_opportunities)
        if opp:
            lines.append("")
            lines += opp
        if ctx.events_line:
            lines += ["", f"EVENTS: {ctx.events_line}"]
        lines += ["", "DATA: " + ("; ".join(ctx.data_lines) if ctx.data_lines else "all sources fresh.")]

    html, md = _assemble(subject, lines, banner=ctx.late_banner)
    # daily letter carries a keyboard ONLY when it escalates an open loop (B.3.3)
    ask_id = ctx.open_loops[0].ask_id if ctx.open_loops else None
    return RenderedOutput(telegram_html=html, markdown=md, output_class="daily", ask_id=ask_id)


def render_status(ctx: StatusContext) -> RenderedOutput:
    h1, h2 = _header_block(ctx.header)
    lines = [f"Status — {ctx.now_label}", "", h1, h2, "", f"✓ {ctx.verdict_line}"]
    for ol in ctx.open_loops:
        lines.append(f"OPEN LOOP [{ol.ask_id}] — {ol.label} ({ol.age_days}d).")
    lines += ["", ctx.next_scheduled_line]
    html = "<b>" + cm.esc(lines[0]) + "</b>\n\n" + "\n".join(cm.esc(l) for l in lines[2:])
    md = "# " + "\n".join(lines)
    ask_id = ctx.open_loops[0].ask_id if ctx.open_loops else None
    return RenderedOutput(telegram_html=html, markdown=md, output_class="status", ask_id=ask_id)
