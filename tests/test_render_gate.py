"""P5.15 — render_gate: C.6 Gate verdict document.

Sizing advice arrives pre-computed (suggested_max_weight_pct) from the E.3 conviction
table and is framed as an invitation, never an instruction. The context carries NO
benchmark and NO cost-basis field (quarantine by absence); the gate class is not in the
lint's no-bang set but still gets the benchmark/red-glyph/imperative checks. A `pass`
verdict shows no sizing line at all.
"""
from datetime import datetime, timezone

from agentcy.render.gate import render_gate
from agentcy.render.lint import lint
from agentcy.render.contexts import GateContext

GEN = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def _ctx(verdict="buy_ready"):
    return GateContext(ticker="ASML", verdict=verdict, reason_class="passed all gates",
        dossier_summary={"circle": "core (cloud infra)", "moat": "switching costs + cost advantage",
                         "owner_earnings": "owner-FCF margin 28%, growing"},
        suggested_max_weight_pct=6.0,
        standing_questions=("Is the litho monopoly durable for a decade?",), generated_at=GEN)


def test_gate_verdict_document(golden):
    r = render_gate(_ctx())
    assert r.output_class == "gate"
    assert "ASML" in r.telegram_html and "buy_ready" in r.telegram_html.lower() or "BUY_READY" in r.telegram_html
    assert "6%" in r.telegram_html
    assert "circle: core (cloud infra)" in r.telegram_html
    assert lint(r) == []
    golden("gate_verdict.html.txt", r.telegram_html)
    golden("gate_verdict.md.txt", r.markdown)


def test_gate_pass_has_no_weight():
    r2 = render_gate(GateContext("ASML", "pass", "failed hell-no filter", {"circle": "edge"},
                                 None, (), GEN))
    assert "suggested max weight" not in r2.telegram_html.lower()
