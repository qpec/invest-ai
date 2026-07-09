"""P5.9 — render_alert single card (G.3 verbatim, WHAT-THIS-IS-NOT, 2-button keyboard).

The alert is the ONLY unscheduled output. The card is reproduced byte-exact from the
elaboration G.3 block; owner-quoted spans (committed trigger statement, 10-year excerpt)
land in owner_spans so the register lint exempts them but the escaped form still ships.
Keyboard shows [Confirm broken] [Refute] only — Revise materializes on the daemon after
a recorded refute (tg-spec §3.3), never at render.
"""
import json
from datetime import datetime, timezone

from agentcy.render.alert import render_alert
from agentcy.render.lint import lint
from agentcy.render.contexts import AlertContext, AlertItemContext

GEN = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def _item():
    return AlertItemContext(
        ticker="CRWD", weight_pct=9.2, trigger_label="T2 (owner-FCF margin)",
        committed_statement_owner="T2: owner-FCF margin < 20% for 2 consecutive quarters.",
        committed_version=2, committed_at="2026-03-14",
        what_happened="Q1 18.4%, Q2 17.1% (statements archive, fresh, both non-empty).",
        baseline_note="Baseline at purchase: 23%.",
        price_move_pct="−9%",
        ten_year_excerpt_owner="…the security-platform consolidation trend runs a "
                               "decade and the data moat compounds with scale.",
        ask_id="A238")


def _single():
    return AlertContext(deadline_label="Tue 14 Jul (7 days)", items=(_item(),), generated_at=GEN)


def test_single_alert_maps_g3_verbatim(golden):
    r = render_alert(_single())
    assert r.output_class == "alert" and r.ask_id == "A238"
    # header framing
    assert r.telegram_html.startswith(
        "<b>Trigger fired — CRWD — T2 (owner-FCF margin) "
        "— decision by Tue 14 Jul (7 days)</b>")
    # mandatory verbatim block, only {pct} substituted
    assert "not a price alarm. The stock is −9% this month" in r.telegram_html
    assert "Cost basis is\nnot shown and will not be considered." in r.telegram_html
    # owner-quoted spans recorded for lint exemption (verbatim, pre-escape)
    assert "T2: owner-FCF margin < 20% for 2 consecutive quarters." in r.owner_spans
    assert any("security-platform consolidation" in s for s in r.owner_spans)
    # committed statement escaped in html but present
    assert "owner-FCF margin &lt; 20%" in r.telegram_html
    # two-button keyboard, Revise NOT present at first presentation
    km = json.loads(r.reply_markup_json)
    labels = [b["text"] for row in km["inline_keyboard"] for b in row]
    assert labels == ["Confirm broken", "Refute"]
    assert lint(r) == []
    golden("alert_single.html.txt", r.telegram_html)
    golden("alert_single.md.txt", r.markdown)


def test_alert_has_no_exclamation_and_no_benchmark():
    r = render_alert(_single())
    # lint already asserts, but be explicit: the −9% is stated flatly, not alarmed
    assert "URGENT" not in r.telegram_html and "!" not in r.telegram_html.replace(
        "".join(r.owner_spans), "")
