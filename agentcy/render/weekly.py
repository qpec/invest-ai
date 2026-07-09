"""G.2 weekly review. render_weekly -> (numbered message series 1..4, full document).
Headline first (§2.2). Msg 2 is the ONLY weekly message carrying decision keyboards.
Value lives weekly (§15 A3); NO benchmark, NO cost basis anywhere here."""
from __future__ import annotations

from agentcy.render import common as cm
from agentcy.render.study import render_study
from agentcy.render.contexts import RenderedOutput, WeeklyContext

_N = 4   # fixed 4-message series (§2.2)


def _eur(x: float) -> str:
    return f"€{x:,.0f}"


def _owner_spans(decisions) -> tuple[str, ...]:
    """The owner-verbatim substrings carried by these decision blocks (committed questions
    in the owner's own words); recorded in RenderedOutput.owner_spans so the register lint
    exempts them (§8 scoping)."""
    return tuple(d.body_owner_span for d in decisions if d.body_owner_span)


def _msg(n: int, date_label: str, body_lines: list[str], *, ask_id=None, reply=None,
         owner_spans: tuple[str, ...] = ()) -> RenderedOutput:
    subject = f"Weekly review — {date_label} — {n}/{_N}"
    html = "<b>" + cm.esc(subject) + "</b>\n\n" + "\n".join(cm.esc(l) for l in body_lines)
    md = "# " + subject + "\n\n" + "\n".join(body_lines)
    return RenderedOutput(telegram_html=html, markdown=md, output_class="weekly_msg",
                          owner_spans=owner_spans, ask_id=ask_id, reply_markup_json=reply)


def render_weekly(ctx: WeeklyContext) -> tuple[tuple[RenderedOutput, ...], RenderedOutput]:
    date_label = cm.ams_date_label(ctx.as_of)

    # --- Msg 1/4 — headline verdict (celebrated if calm) ---
    m1_lines = [
        ("✓ " if ctx.celebrated else "") + ctx.headline_verdict,
        "You'll find full detail in the document that follows.",
    ]
    m1 = _msg(1, date_label, m1_lines)

    # --- Msg 2/4 — decisions waiting (the only keyboard-bearing weekly message) ---
    # d0.body carries the owner-verbatim committed question; its body_owner_span rides in
    # owner_spans so the lint exempts it (an owner committed question saying "will outgrow
    # the S&P!" keeps its keyboard-bearing message intact instead of being stripped, §8).
    if ctx.decisions:
        d0 = ctx.decisions[0]
        m2_lines = [d0.heading, d0.body]
        if len(ctx.decisions) > 1:
            m2_lines.append(f"(+{len(ctx.decisions) - 1} more decisions in the document.)")
        m2 = _msg(2, date_label, m2_lines, ask_id=d0.ask_id, reply=d0.reply_markup_json,
                  owner_spans=_owner_spans((d0,)))
    else:
        m2 = _msg(2, date_label, ["✓ No decisions waiting. The document has the full picture when you want it."])

    # --- Msg 3/4 — balance & concentration snapshot ---
    b = ctx.balance
    m3_lines = [
        f"Cash {b.cash_pct:g}% ({'✓' if b.cash_in_band else '×'}) · "
        f"position count {'✓' if b.position_count_in_band else '×'} · "
        f"N_eff {b.n_eff:g} vs floor 4.0 {'✓' if b.n_eff_ok else '×'}",
    ]
    for br in (b.soft_cap_breaches + b.hard_cap_breaches + b.cluster_weight_breaches):
        m3_lines.append(f"Band breach: {br}.")
    if ctx.reinvest_reminder:
        m3_lines.append("Dividends idle — consider reinvesting (a plan working quietly).")
    m3 = _msg(3, date_label, m3_lines)

    # --- Msg 4/4 — The Study (reuses render_study body; Msg 2 is the ONLY weekly
    # message carrying a keyboard, so the study's circle-note ForceReply is dropped here
    # and the invitation stays as plain informational text). ---
    study_body = render_study(ctx.study).markdown.split("\n", 1)[1].lstrip("\n")  # drop the '# The Study' header
    m4 = _msg(4, date_label, study_body.split("\n"))

    doc = _document(ctx, date_label)
    return (m1, m2, m3, m4), doc


def _document(ctx: WeeklyContext, date_label: str) -> RenderedOutput:
    L: list[str] = [f"# Weekly review — {date_label}", "",
                    "## 1. Verdict", ("✓ " if ctx.celebrated else "") + ctx.headline_verdict, ""]
    # 2. Portfolio table (weight, EUR value, status, conviction, sector, anchor vs band, scorecard)
    L += ["## 2. Portfolio", ""]
    header = ["Ticker", "Wt%", "EUR", "Fw", "Status", "v", "Conv", "Sector", "Anchor", "Band", "Triggers"]
    rows = [[r.ticker, f"{r.weight_pct:g}", _eur(r.mv_eur), r.framework_status,
             r.thesis_status or "-", str(r.thesis_version or "-"), r.conviction or "-",
             r.sector_label or "-",
             (f"{r.anchor_multiple:g}×" if r.anchor_multiple is not None else "-"),
             (f"{r.band_low:g}–{r.band_high:g}×" if r.band_low is not None else "-"),
             r.trigger_scorecard] for r in ctx.portfolio]
    L.append(cm.pre_table(rows, header=header, skin="md"))
    L += ["", f"Total portfolio value: {_eur(ctx.total_eur)}.", ""]
    # 3. Thesis re-validation
    L += ["## 3. Thesis re-validation", *ctx.revalidations]
    if ctx.backfill_queue_line:
        L.append(ctx.backfill_queue_line)
    L += list(ctx.broken_but_held) + list(ctx.reaffirmations_due) + [""]
    # 4. Balance & concentration
    L += ["## 4. Balance & concentration",
          f"Cash {ctx.balance.cash_pct:g}% · N_eff {ctx.clusters.n_eff:g} vs floor 4.0 · "
          f"unpriced weight {ctx.balance.unpriced_weight_pct:g}%.",
          *ctx.dividend_lines, *ctx.loosening_echoes, ""]
    # 5. Outside framework
    L += ["## 5. Outside framework", ctx.outside_framework_line, ""]
    # 6. Watchlist
    L += ["## 6. Watchlist", *ctx.watchlist_lines, ""]
    # 7. Prompted questions (text only in doc; keyboards ride Msg 2)
    L += ["## 7. Prompted questions", *[f"[{d.ask_id}] {d.heading}: {d.body}" for d in ctx.prompted_questions], ""]
    # 8. The Study
    L += ["## 8. The Study", render_study(ctx.study).markdown.split("\n", 1)[1], ""]
    # 9. Data health
    L += ["## 9. Data health appendix", *ctx.data_health, ""]
    md = "\n".join(L)
    html = "\n".join(cm.esc(l) for l in L)   # doc html skin is a plain escaped mirror (sent as document)
    # §7 reproduces the owner-verbatim committed questions; exempt them from the lint too,
    # so a doc carrying an owner question with a bang/benchmark token is not stripped (§8).
    return RenderedOutput(telegram_html=html, markdown=md, output_class="weekly_doc",
                          owner_spans=_owner_spans(ctx.prompted_questions))
