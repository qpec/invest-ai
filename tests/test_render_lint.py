import json
from agentcy.render.lint import lint, fallback, lint_or_fallback, LintViolation
from agentcy.render.contexts import RenderedOutput
from agentcy.render import common as cm


def _alert(html, owner_spans=(), ask_id="A238", km=None):
    return RenderedOutput(telegram_html=html, markdown=html, output_class="alert",
                          owner_spans=owner_spans, ask_id=ask_id,
                          reply_markup_json=json.dumps(km) if km else None)


VALID_ALERT_TAIL = (
    cm.WHAT_THIS_IS_NOT.format(pct="-9%") + "\n"
    + cm.DEADLINE_FRAMING.format(date="Tue 14 Jul", n=7)
)


# --- the three MUST-PASS owner-text cases (§8 scoping, tech-arch §13) ---------------
def test_owner_bang_passes():
    owner = 'T1: "will outgrow the S&P!"'
    html = ("Trigger fired — CRWD\n" + owner + "\n" + VALID_ALERT_TAIL)
    assert lint(_alert(html, owner_spans=(owner,))) == []


def test_owner_euro_amount_passes():
    owner = "You wrote: the position is worth €4,200 to me."
    html = ("Prompted check — VEEV\n" + owner + "\n" + VALID_ALERT_TAIL)
    r = RenderedOutput(telegram_html=html, markdown=html, output_class="alert",
                       owner_spans=(owner,), ask_id="A1")
    assert lint(r) == []


def test_owner_sp_token_passes_in_alert():
    owner = "S&P will not save this company."
    html = ("Trigger fired — X\n" + owner + "\n" + VALID_ALERT_TAIL)
    assert lint(_alert(html, owner_spans=(owner,))) == []


# --- template-span violations still caught ------------------------------------------
def test_template_bang_in_alert_flagged():
    html = "Trigger fired — CRWD act now!\n" + VALID_ALERT_TAIL
    v = lint(_alert(html))
    assert any(x.rule == "no_exclamation" for x in v)


def test_benchmark_token_outside_quarterly_flagged():
    html = "Daily letter — beat the S&P today\nDATA: fresh."
    r = RenderedOutput(telegram_html=html, markdown=html, output_class="daily")
    assert any(x.rule == "no_benchmark_token" for x in lint(r))


def test_euro_digits_in_daily_flagged():
    r = RenderedOutput(telegram_html="Daily letter\nCash worth €3,000 today.",
                       markdown="x", output_class="daily")
    assert any(x.rule == "no_euro_in_daily" for x in lint(r))


def test_red_glyph_anywhere_flagged():
    r = RenderedOutput(telegram_html="Daily letter 🔴 stale", markdown="x", output_class="daily")
    assert any(x.rule == "no_red_glyph" for x in lint(r))


def test_missing_what_this_is_not_in_alert_flagged():
    html = "Trigger fired — CRWD\n" + cm.DEADLINE_FRAMING.format(date="Tue 14 Jul", n=7)
    assert any(x.rule == "missing_verbatim" for x in lint(_alert(html)))


def test_quarterly_doc_may_carry_benchmark_and_euro():
    html = "Portfolio (EUR) vs S&P 500 TR (EUR): €120,000 since inception."
    r = RenderedOutput(telegram_html=html, markdown=html, output_class="quarterly_doc")
    assert lint(r) == []


# --- fail-closed fallback preserves the decision surface ----------------------------
def test_fallback_preserves_ask_id_keyboard_and_verbatim():
    km = {"inline_keyboard": [[{"text": "Confirm broken", "callback_data": "alert:confirm:A238"}]]}
    bad = _alert("Trigger fired!! act now", km=km)     # violates, and lacks verbatim block
    v = lint(bad)
    safe = fallback(bad, v)
    assert safe.ask_id == "A238"
    assert safe.reply_markup_json == bad.reply_markup_json
    assert "not a price alarm" in safe.telegram_html          # verbatim block restored
    assert lint(safe) == []                                    # the fallback itself is clean


def test_lint_or_fallback_never_returns_a_violating_output():
    bad = _alert("Trigger fired!! ", km=None)
    out, viols = lint_or_fallback(bad)
    assert viols != [] and lint(out) == []
