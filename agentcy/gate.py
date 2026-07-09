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


from agentcy import db
from agentcy.fetch import store as _store_default


class DossierPaused(Exception):
    """C.4 - the Gate cannot verdict on absent/stale owner-earnings data."""


def _yf_ticker(conn, ticker: str) -> str:
    """Map symbol->yfinance ticker; default to the symbol itself (Gate candidates
    are entered as yfinance-compatible tickers, H.1)."""
    return db.fetch_current_symbol_map(conn).get(ticker, ticker)


def build_dossier(conn, ticker: str, *, as_of, store=_store_default) -> dict:
    """C.4 Buffett dossier: owner-earnings picture + statement-period counts +
    current anchor multiple, every number from the hardened data layer. Missing/
    empty/stale fundamentals -> DossierPaused (no verdict on absent data)."""
    yf = _yf_ticker(conn, ticker)
    oe = store.owner_fcf_ttm(conn, yf, as_of=as_of)
    if oe is None or not oe.usable():
        raise DossierPaused(
            f"{ticker}: owner-earnings unavailable/stale - the Gate pauses; "
            "no verdict on absent owner-earnings data (C.4)."
        )
    income = store.statement_history(conn, yf, "income", as_of=as_of)
    income_periods = [r["period_end"] for r in income.value]

    # current anchor multiple = close / owner-FCF-per-share; None if price absent
    current_multiple = None
    close = store.latest_close(conn, yf, as_of=as_of)
    denom = store.denominator_per_share(conn, yf, as_of=as_of)
    if close is not None and denom is not None and denom.usable() and denom.value > 0:
        current_multiple = close.value.close / denom.value

    return {
        "ticker": ticker,
        "yf_ticker": yf,
        "fcf_ttm": oe.value.fcf_ttm,
        "sbc_ttm": oe.value.sbc_ttm,
        "owner_fcf_ttm": oe.value.owner_fcf_ttm,
        "owner_fcf_per_share_ttm": oe.value.owner_fcf_per_share_ttm,
        "owner_fcf_margin_ttm": oe.value.owner_fcf_margin_ttm,
        "owner_earnings_json": _oe_json(oe),
        "owner_earnings_periods": list(oe.value.periods_used),
        "income_period_count": len(income_periods),
        "income_periods": income_periods,
        "current_multiple": current_multiple,
        "fetched_at": oe.fetched_at.isoformat().replace("+00:00", "Z"),
    }


def _oe_json(oe: "Stamped") -> str:
    import json
    v = oe.value
    return json.dumps({
        "fcf_ttm": v.fcf_ttm, "sbc_ttm": v.sbc_ttm, "owner_fcf_ttm": v.owner_fcf_ttm,
        "owner_fcf_per_share_ttm": v.owner_fcf_per_share_ttm,
        "owner_fcf_margin_ttm": v.owner_fcf_margin_ttm,
        "periods_used": list(v.periods_used),
        "fetched_at": oe.fetched_at.isoformat().replace("+00:00", "Z"),
    })


STATUS_QUESTION = "Would you still buy this if you could never tell anyone you owned it?"


def step_judgment(state: dict, ask: AskOwner) -> str:
    """C.5 (FR9, sacred) - the system asks; only the owner answers; no defaults,
    no suggestions. Verbatim status question; hesitant/negative answer is the sole
    source of status_buy_flag (F11)."""
    state["conviction"] = _ask_enum(
        ask, "conviction - high, medium, or low? (never system-set or system-capped)",
        ("high", "medium", "low"))
    state["mgmt_trust"] = _ask_enum(
        ask, "mgmt_trust - trusted_owner_operator, trusted_professional, neutral, "
             "or distrust?",
        ("trusted_owner_operator", "trusted_professional", "neutral", "distrust"))
    state["mgmt_trust_note"] = ask("mgmt_trust note (one line):", None).strip() or None
    state["circle_fit"] = _ask_enum(
        ask, f"circle_fit - confirm core or edge? (you said "
             f"{state.get('circle_fit_initial', 'core')} at C.2)",
        ("core", "edge"))
    state["circle_fit_note"] = ask("circle_fit note - which competence domain?",
                                   None).strip() or None
    state["ten_year_statement"] = _ask_nonempty(
        ask, "ten_year_statement - first person: would you hold if the market closed "
             "for a decade, and why?")
    # the status question, verbatim (C.5); yes = clean, anything else = flag (F11)
    status_ans = _ask_enum(
        ask, f"{STATUS_QUESTION} (yes / hesitant / no)",
        ("yes", "hesitant", "no"))
    state["status_buy_flag"] = status_ans != "yes"
    if state["status_buy_flag"]:
        state["status_buy_note"] = ask(
            "You hesitated on the status question. One line on why "
            "(this becomes the status-buy note):", None).strip() or None
    return "drafting"
