"""The Gate (C.1-C.6) + watchlist ops.

Resumable state machine over gate_session. FR9: every owner field enters through
the injected ask_owner callable (interactive-prompt-only); no flag, no stdin-JSON,
no import path can supply them. The CLI injects real prompts; tests inject
ScriptedAsker answers.
"""
from __future__ import annotations

import re
from typing import Callable

AskOwner = Callable[[str, "tuple[str, ...] | None"], str]

# Plan note: naive sentence splitter (runs of .!? end a sentence). The 2-sentence
# limit is a discipline device, not NLP; abbreviation miscounts are acceptable and
# the owner is re-asked, never silently truncated.
_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")


def sentence_count(text: str) -> int:
    return len([s for s in _SENTENCE_RE.findall(text.strip()) if s.strip()])


def _ask_enum(ask: AskOwner, prompt: str, options: tuple, *, default: str | None = None) -> str:
    while True:
        raw = ask(prompt, options).strip().lower()
        if not raw and default is not None:
            return default
        if raw in options:
            return raw


def _ask_nonempty(ask: AskOwner, prompt: str) -> str:
    while True:
        raw = ask(prompt, None).strip()
        if raw:
            return raw


def _ask_float(ask: AskOwner, prompt: str) -> float:
    while True:
        try:
            return float(ask(prompt, None).strip())
        except ValueError:
            continue


def step_circle(state: dict, ask: AskOwner) -> str:
    """C.2 - owner writes the 2-sentence business model and names the moat from
    memory, without research; circle_fit outside or can't-write-it = PASS."""
    while True:
        bm = ask(
            "C.2 circle of competence - in two sentences, from memory, without "
            "research: what does this business do and how does it make money? "
            "(Blank = can't write it, which is a PASS.)",
            None,
        ).strip()
        if not bm:
            state["pending_pass"] = {
                "reason_class": "outside_circle",
                "note": "owner could not write the two-sentence business model from memory (C.2)",
            }
            return "verdict"
        if sentence_count(bm) <= 2:
            break
        # hard 2-sentence limit: the system rejects longer and re-asks (A.1)
    state["business_model_2s"] = bm
    moat_phrase = ask("Name the moat in one phrase, from memory.", None).strip()
    if not moat_phrase:
        state["pending_pass"] = {
            "reason_class": "outside_circle",
            "note": "owner could not name the moat from memory (C.2)",
        }
        return "verdict"
    state["moat_phrase"] = moat_phrase
    fit = _ask_enum(ask, "circle_fit - core, edge, or outside your circle of competence?",
                    ("core", "edge", "outside"))
    if fit == "outside":
        state["pending_pass"] = {
            "reason_class": "outside_circle",
            "note": "owner answered circle_fit=outside (C.2); no exceptions for upside",
        }
        return "verdict"
    state["circle_fit_initial"] = fit
    return "hell_no"


# C.3 - five binary tests; "yes" = FAIL on every question (phrased so the
# dangerous answer is always yes). One FAIL = REJECT, no override path.
HELL_NO_QUESTIONS = (
    ("HN1", "Leverage - does the instrument embed leverage (CFD, leveraged ETF, "
            "margin), or would the purchase require borrowing? (yes = FAIL)"),
    ("HN2", "Understandability - does valuing it need more than ~5 core "
            "assumptions? (yes = FAIL)"),
    ("HN3", "Management - is there any reason to distrust management? "
            "(yes = FAIL; prefer owner-operators with skin in the game)"),
    ("HN4", "Fad - is it narrative rather than real present-day revenue and FCF? "
            "(yes = FAIL)"),
    ("HN5", "Fees - fee structure, 2-and-20, expense ratio, or a structure "
            "requiring frequent trading? (yes = FAIL)"),
)


def step_hell_no(state: dict, ask: AskOwner) -> str:
    """C.3 - one FAIL = REJECT, no override path; remaining tests still recorded."""
    results: dict[str, str] = {}
    for code, question in HELL_NO_QUESTIONS:
        results[code] = _ask_enum(ask, f"{code} - {question}", ("yes", "no"))
    state["hell_no"] = results
    failed = [code for code, _ in HELL_NO_QUESTIONS if results[code] == "yes"]
    if failed:
        state["pending_pass"] = {
            "reason_class": f"hell_no_{failed[0]}",
            "note": ("Hell-No veto: one FAIL = automatic rejection, regardless of "
                     f"upside (FR3). All five answers recorded: {results}"),
        }
        return "verdict"
    return "dossier"
