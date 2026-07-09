"""G.4 quarterly honesty report — the ONLY renderer that prints a benchmark or cost basis
(FR13, invariant-7 quarantine lands here by data, not by suppression). render_quarterly
-> (summary message, full document). Benchmark/cost basis appear ONLY in the document,
except the summary's single 'honest question' line which the quarantine permits in
quarterly classes."""
from __future__ import annotations

from agentcy.render import common as cm
from agentcy.render.contexts import QuarterlyContext, RenderedOutput


def _pct(x) -> str:
    return f"{x:+.1f}%"


def _summary(ctx: QuarterlyContext) -> RenderedOutput:
    q = ctx.honest_question
    lines = [
        f"Quarterly honesty report — {ctx.period}",
        "",
        "The honest question — would an index fund have beaten my process?",
        f"Portfolio (EUR) vs S&P 500 TR (EUR): since inception "
        f"{_pct(q['since_inception_portfolio_pct'])} vs {_pct(q['since_inception_benchmark_pct'])}; "
        f"trailing 12m {_pct(q['ttm_portfolio_pct'])} vs {_pct(q['ttm_benchmark_pct'])}.",
        f"(This quarter alone {_pct(q['quarter_portfolio_pct'])} vs {_pct(q['quarter_benchmark_pct'])} — "
        f"do not extrapolate 13 weeks.)",
        "",
        f"The honest answer — {ctx.honest_answer_sentence}",
        "The 10-year answer is the real one.",
    ]
    html = "<b>" + cm.esc(lines[0]) + "</b>\n\n" + "\n".join(cm.esc(l) for l in lines[2:])
    md = "# " + "\n".join(lines)
    return RenderedOutput(telegram_html=html, markdown=md, output_class="quarterly_msg")


def _document(ctx: QuarterlyContext) -> RenderedOutput:
    q, pr, fa, ra = ctx.honest_question, ctx.process_review, ctx.framework_audit, ctx.records_appendix
    L = [f"# Quarterly honesty report — {ctx.period}", ""]
    # 1
    L += ["## 1. The honest question",
          f"Portfolio (EUR) vs S&P 500 TR (EUR): since inception "
          f"{_pct(q['since_inception_portfolio_pct'])} vs {_pct(q['since_inception_benchmark_pct'])}; "
          f"trailing 12m {_pct(q['ttm_portfolio_pct'])} vs {_pct(q['ttm_benchmark_pct'])}; "
          f"this quarter {_pct(q['quarter_portfolio_pct'])} vs {_pct(q['quarter_benchmark_pct'])} "
          "(do not extrapolate 13 weeks).", *[f"Caveat: {c}" for c in ctx.caveats], ""]
    # 2
    L += ["## 2. The honest answer", ctx.honest_answer_sentence, "The 10-year answer is the real one.", ""]
    # 3
    L += ["## 3. Drawdown context", *ctx.drawdown_context, ""]
    # 4
    L += ["## 4. Process review",
          f"Followed process: {pr['followed_pct']:g}% · override hit-rate {pr['override_hit_rate']} · "
          f"no-action ratio {pr['no_action_ratio']}.",
          "Followed & good: " + "; ".join(pr["followed_good"] or ["—"]),
          "Deviated & bad: " + "; ".join(pr["deviated_bad"] or ["—"]),
          "Alert-ignored ledger: " + "; ".join(pr["alert_ignored"] or ["—"]), ""]
    # 5
    L += ["## 5. Framework audit", *fa["gate_throughput"], *fa["trigger_relaxations"], *fa["config_changes"], ""]
    # 6 — the ONE place cost basis is printed
    L += ["## 6. Records appendix (for the accountant, not for decisions — the one place cost basis is printed)"]
    header = ["Ticker", "Cost basis (EUR)", "Realized gain (EUR)", "Trade-date FX"]
    rows = [[r["ticker"], f"{r['cost_basis_eur']:,.0f}", f"{r['realized_gain_eur']:,.0f}", r["trade_fx_note"]]
            for r in ra["rows"]]
    L += [cm.pre_table(rows, header=header, skin="md"), ""]
    # 7
    L += ["## 7. Verdict", ctx.verdict_and_exit_clause, cm.INDEXING_EXIT_CLAUSE, ""]
    md = "\n".join(L)
    html = "\n".join(cm.esc(l) for l in L)
    return RenderedOutput(telegram_html=html, markdown=md, output_class="quarterly_doc")


def render_quarterly(ctx: QuarterlyContext) -> tuple[RenderedOutput, RenderedOutput]:
    return _summary(ctx), _document(ctx)
