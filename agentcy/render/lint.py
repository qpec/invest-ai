"""Pre-send register lint (tech-arch §8, review-fixed scoping): token checks apply to
TEMPLATE-AUTHORED SPANS ONLY — owner-quoted dynamic fields (RenderedOutput.owner_spans)
are cut out before checking. Fail-closed: a violating output is never sent as-is and
never silently dropped; fallback() ships a safe minimal template PRESERVING ask_id,
keyboard, and the mandatory verbatim blocks."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from agentcy.render import common as cm
from agentcy.render.contexts import RenderedOutput

# Output classes on which the calm-register token bans apply (§6.2).
_NO_BANG_CLASSES = {"alert", "event", "weekly_msg", "weekly_doc", "daily", "status", "notice"}
_DAILY_LIKE = {"daily", "status"}
_QUARTERLY_CLASSES = {"quarterly_msg", "quarterly_doc"}

# Red-alarm typography banned as state emphasis anywhere in scheduled output (§6.2);
# calm/data-check glyphs (✓, ×, ✗) are deliberately NOT here.
_RED_GLYPHS = ("\U0001f534", "\U0001f6a8", "⚠️", "❗", "❌")
# benchmark identifiers banned outside the quarterly class (§6.2)
_BENCH = re.compile(r"S&P|\^SP500TR|vs\s+index|outperform|underperform|benchmark", re.IGNORECASE)
_EURO_DIGITS = re.compile(r"€\s*\d")
_IMPERATIVE = re.compile(r"\b(buy now|sell now|you must)\b", re.IGNORECASE)


@dataclass(frozen=True)
class LintViolation:
    rule: str
    output_class: str
    excerpt: str


def _template_text(r: RenderedOutput) -> str:
    """The linted surface: telegram_html with every owner_span removed (verbatim, once each)."""
    t = r.telegram_html
    for span in r.owner_spans:
        # remove both raw and HTML-escaped forms of the owner span
        t = t.replace(span, " ").replace(cm.esc(span), " ")
    return t


def _hit(text: str, needle: str) -> str:
    i = text.find(needle)
    return text[max(0, i - 20): i + 20] if i >= 0 else needle


def lint(r: RenderedOutput) -> list[LintViolation]:
    cls = r.output_class
    t = _template_text(r)
    v: list[LintViolation] = []

    if cls in _NO_BANG_CLASSES and "!" in t:
        v.append(LintViolation("no_exclamation", cls, _hit(t, "!")))

    for g in _RED_GLYPHS:
        if g in r.telegram_html:                       # red glyphs banned everywhere, even in owner text
            v.append(LintViolation("no_red_glyph", cls, g))

    if cls not in _QUARTERLY_CLASSES:
        m = _BENCH.search(t)
        if m:
            v.append(LintViolation("no_benchmark_token", cls, _hit(t, m.group(0))))

    if cls in _DAILY_LIKE and _EURO_DIGITS.search(t):
        v.append(LintViolation("no_euro_in_daily", cls, _hit(t, "€")))

    m = _IMPERATIVE.search(t)
    if m:
        v.append(LintViolation("no_imperative", cls, _hit(t, m.group(0))))

    if cls == "alert":
        if "not a price alarm" not in r.telegram_html:
            v.append(LintViolation("missing_verbatim", cls, "WHAT THIS IS NOT"))
        if "decision by" not in r.telegram_html:
            v.append(LintViolation("missing_verbatim", cls, "deadline framing"))

    return v


def fallback(r: RenderedOutput, violations: Sequence[LintViolation]) -> RenderedOutput:
    """Safe minimal template that PRESERVES ask_id, reply_markup_json, and — for alerts —
    the mandatory verbatim blocks. A decision surface is never stripped (§8)."""
    if r.output_class == "alert":
        # Fallback copy is purpose-written, not a shoehorn of the {pct}/{n} template
        # slots (there is no live price move or day count to substitute here). It keeps
        # the load-bearing verbatim phrases — "not a price alarm" and "decision by" —
        # so the safe template still self-cleans under lint (§8).
        body = (
            "Trigger fired — a thesis needs your decision.\n\n"
            "WHAT THIS IS NOT: not a price alarm. The price is not why you are reading\n"
            "this and it plays no part in what follows. Cost basis is not shown and will\n"
            "not be considered.\n\n"
            "A decision by the committed deadline is required.\n"
            "Open the archived alert for the full committed statement and the exact date."
        )
    else:
        body = ("This report could not be rendered in full and was replaced with a safe "
                "summary. The complete version is in the archive.")
    return RenderedOutput(
        telegram_html=body, markdown=body, output_class=r.output_class,
        owner_spans=(), ask_id=r.ask_id, reply_markup_json=r.reply_markup_json,
    )


def lint_or_fallback(r: RenderedOutput) -> tuple[RenderedOutput, list[LintViolation]]:
    """Never returns a violating output; violations surface (caller logs to data-health)."""
    v = lint(r)
    if not v:
        return r, []
    return fallback(r, v), v
