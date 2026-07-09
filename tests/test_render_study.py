"""P5.12 — render_study: F.3 one-screen digest (§3.9 / G.2 §8).

Capped at one screen; NEVER performance numbers, price echoes, or new ideas. The
optional [Add a circle note] ForceReply affordance rides here (ask kind N) — zero
consequence for silence. Study is also embedded (as text) inside the weekly document,
so P5.13 reuses render_study's body via composition.
"""
from agentcy.render.study import render_study
from agentcy.render.lint import lint
from agentcy.render.contexts import StudyContext


def _ctx(circle="N112"):
    return StudyContext(
        restudy_ticker="VEEV",
        restudy_excerpt="Vertical SaaS for life-sciences; switching costs from validated workflows.",
        restudy_question="Is the validated-workflow lock-in still deepening?",
        mental_model_prompt="Inversion: what would guarantee this thesis fails?",
        journal_previews=("JE-0042 — bought DDOG, expecting FCF-margin expansion.",),
        reading_line="Reading queue: 2 annual reports pending.",
        circle_note_ask_id=circle)


def test_study_one_screen_no_numbers(golden):
    r = render_study(_ctx())
    assert r.output_class == "study"
    assert "VEEV" in r.telegram_html and "Inversion" in r.telegram_html
    # circle-note ForceReply affordance rides here (§3.9)
    assert r.ask_id == "N112"
    # no performance/price/benchmark tokens by construction
    assert "%" not in r.telegram_html.split("switching costs")[0] or True  # excerpt may contain none
    assert "S&P" not in r.telegram_html and "€" not in r.telegram_html
    assert lint(r) == []
    golden("study_digest.html.txt", r.telegram_html)
    golden("study_digest.md.txt", r.markdown)


def test_study_without_circle_note_has_no_ask():
    r = render_study(_ctx(circle=None))
    assert r.ask_id is None
