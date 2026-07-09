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


_TRIGGER_TYPES = ("growth_floor", "margin_erosion", "balance_sheet_safety",
                  "dilution", "owner_attested_event")
_MOAT_TYPES = ("network_effects", "switching_costs", "cost_advantage",
               "brand_trust", "regulatory_barrier")
_PERSISTENCE = ("single_observation", "2_consecutive_quarters", "ttm")
# B.2: check_method + data_source are COMPUTED from type (testable != automatable)
_TYPE_META = {
    "growth_floor":         ("automated", "yf_quarterly_statements", "weekly"),
    "margin_erosion":       ("automated", "yf_quarterly_statements", "weekly"),
    "balance_sheet_safety": ("automated", "yf_quarterly_statements", "weekly"),
    "dilution":             ("automated", "yf_shares_full",          "weekly"),
    "owner_attested_event": ("prompted",  "owner_attestation",       "event"),
}


def _ask_moat_link(ask: AskOwner) -> str | None:
    raw = ask("moat_link - a moat type this trigger falsifies, or blank for none. "
              f"One of {_MOAT_TYPES} or blank:", ("",) + _MOAT_TYPES).strip().lower()
    return raw or None


def _ask_trigger(ask: AskOwner) -> dict:
    ttype = _ask_enum(ask, f"trigger type - one of {_TRIGGER_TYPES}:", _TRIGGER_TYPES)
    statement = _ask_nonempty(
        ask, "statement - one falsifiable sentence in your words "
             "(\"If X, the reason I own this is gone\"):")
    metric = ask("metric (blank for type-5 / owner-attested):", None).strip() or None
    comparator = ask("comparator (e.g. <, >; blank for type-5):", None).strip() or None
    thr_raw = ask("threshold (number; blank for type-5):", None).strip()
    threshold = float(thr_raw) if thr_raw else None
    moat_link = _ask_moat_link(ask)
    check_method, data_source, cadence = _TYPE_META[ttype]
    persistence = _ask_enum(
        ask, f"persistence - {_PERSISTENCE} (blank = type default):",
        _PERSISTENCE, default=_default_persistence(ttype))
    yes_means = None
    if ttype == "owner_attested_event":
        yes_means = _ask_enum(
            ask, "yes_means - does a YES answer FIRE the trigger or PASS it?",
            ("fire", "pass"))
    return {
        "type": ttype, "statement": statement, "metric": metric,
        "comparator": comparator, "threshold": threshold, "moat_link": moat_link,
        "persistence": persistence, "check_method": check_method,
        "data_source": data_source, "cadence": cadence, "yes_means": yes_means,
    }


def _default_persistence(ttype: str) -> str:
    return {"dilution": "ttm"}.get(ttype, "2_consecutive_quarters")


def step_drafting(state: dict, ask: AskOwner) -> str:
    """C.6 drafting - owner writes moat fields, the fair band, and commits 2-5
    triggers with >=1 moat-linked (BUF-4). Thresholds owner-set; templates only
    proposed. Re-drafts the whole trigger set if the moat-link rule is unmet."""
    moat_types = []
    while not moat_types:
        raw = ask(f"moat_types - one or more of {_MOAT_TYPES}, comma-separated "
                  "(min 1):", None)
        moat_types = [m.strip().lower() for m in raw.split(",")
                      if m.strip().lower() in _MOAT_TYPES]
    state["moat_types"] = moat_types
    state["moat_evidence"] = _ask_nonempty(
        ask, "moat_evidence - >=1 observable fact per selected moat type:")
    state["fair_band_low"] = _ask_float(ask, "fair_band_low (multiple):")
    state["fair_band_high"] = _ask_float(ask, "fair_band_high (multiple):")
    state["denominator_note"] = ask("denominator_note (e.g. 'P/owner-FCF'):",
                                    None).strip() or None
    while True:
        n = 0
        while not (2 <= n <= 5):
            try:
                n = int(ask("How many triggers? (2-5; fewer is unfalsifiable, "
                            "more is noise)", None).strip())
            except ValueError:
                n = 0
        triggers = [_ask_trigger(ask) for _ in range(n)]
        if any(t["moat_link"] for t in triggers):
            state["triggers"] = triggers
            return "verdict"
        # BUF-4: at least one committed trigger must carry a moat_link -> re-draft


def _sizing_pct(conviction: str, config_map: dict) -> float:
    key = {"high": "initial_weight_high_pct", "medium": "initial_weight_medium_pct",
           "low": "initial_weight_low_pct"}[conviction]
    return float(config_map[key])


def classify_verdict(*, tmp_db_unused, state: dict, dossier: dict | None,
                     config_map: dict) -> dict:
    """C.6 verdict — PASS if a pending_pass was set upstream; else BUY_READY when
    the current multiple is inside/below the fair band, WATCH when above it (or
    when no price exists but the business passed — backfill has no price verdict,
    handled by the caller). Sizing from the E.3 conviction table."""
    if "pending_pass" in state:
        return {"verdict": "PASS", "reason_class": state["pending_pass"]["reason_class"],
                "note": state["pending_pass"]["note"], "standing_questions": (),
                "suggested_max_weight_pct": None, "requires_status_rebuttal": False}

    multiple = (dossier or {}).get("current_multiple")
    band_high = state["fair_band_high"]
    # price inside or below band => BUY_READY; above => WATCH (E.4 fair-price line)
    is_buy_ready = multiple is not None and multiple <= band_high
    verdict = "BUY_READY" if is_buy_ready else "WATCH"

    standing = []
    if state["conviction"] == "low" or state["circle_fit"] == "edge":
        standing.append(
            "the mandate is 10-15 high-conviction positions - why does this belong "
            "in a concentrated book?")

    return {
        "verdict": verdict,
        "reason_class": None,
        "note": None,
        "standing_questions": tuple(standing),
        "suggested_max_weight_pct": (_sizing_pct(state["conviction"], config_map)
                                     if verdict == "BUY_READY" else None),
        "requires_status_rebuttal": verdict == "BUY_READY" and state["status_buy_flag"],
    }


from agentcy import mirror


def _framework_count(conn, as_of) -> int:
    """Count current framework-designated positions in the latest snapshot."""
    snap = db.fetch_latest_snapshot(conn)
    if snap is None:
        return 0
    positions = mirror.advice_positions(conn, snap["snapshot_id"])
    return sum(1 for p in positions
               if mirror.framework_status(conn, p.symbol, as_of=as_of) == "framework")


def _displacement_note(conn, ask: AskOwner, *, as_of) -> str | None:
    """C.6 displacement rule — at >=15 framework positions a BUY_READY must name
    which existing holding this candidate beats, and why (opportunity cost made
    mechanical)."""
    if _framework_count(conn, as_of) < 15:
        return None
    return _ask_nonempty(
        ask, "Displacement rule (>=15 framework positions): name the existing "
             "holding this candidate beats, and why. A BUY_READY may not stand "
             "without it.")


def _status_rebuttal(ask: AskOwner) -> str:
    """C.6 status-buy friction — a set status_buy_flag requires the owner's written
    rebuttal before BUY_READY stands."""
    return _ask_nonempty(
        ask, "status_buy_flag is set (you hesitated on the status question). Write "
             "the rebuttal for why this belongs in the book anyway. Required before "
             "BUY_READY stands.")


from dataclasses import dataclass

from agentcy import journal, register
from agentcy.clock import Clock
from agentcy.journal import EntryIn
from agentcy.register import ThesisFields, TriggerSpec


@dataclass(frozen=True)
class GateOutcome:
    """The public result of a completed Gate run (C.6). Consumed by P5 render/gate
    and P8 cli."""
    ticker: str
    mode: str                       # 'gate' | 'backfill'
    verdict: str                    # BUY_READY | WATCH | PASS | activate_backfill | no_thesis_exists
    thesis_id: str | None
    reason_class: str | None
    suggested_max_weight_pct: float | None
    standing_questions: tuple[str, ...]
    journal_entry_id: int
    dossier: dict | None


_VERDICT_SUBTYPE = {"BUY_READY": "buy_ready", "WATCH": "watch", "PASS": "pass",
                    "activate_backfill": "activate_backfill",
                    "no_thesis_exists": "no_thesis_exists"}


def _finalize(conn, *, mode: str, state: dict, dossier: dict | None,
              verdict: dict, clock: Clock) -> GateOutcome:
    """Turn the assembled state + verdict into durable objects (C.6), one
    transaction. PASS journals only; BUY_READY/WATCH create a draft thesis +
    triggers + verdict journal."""
    v = verdict["verdict"]
    system_rec = _verdict_text(v, verdict, dossier)

    if v in ("PASS", "no_thesis_exists"):
        entry_id = journal.append(conn, EntryIn(
            decision_type="gate_verdict", decision_subtype=_VERDICT_SUBTYPE[v],
            ticker=state["ticker"], system_recommendation=system_rec,
            owner_action="no_action", reasoning_at_the_moment=verdict.get("note"),
            actor="owner"), clock=clock)
        return GateOutcome(ticker=state["ticker"], mode=mode, verdict=v,
                           thesis_id=None, reason_class=verdict.get("reason_class"),
                           suggested_max_weight_pct=None, standing_questions=(),
                           journal_entry_id=entry_id, dossier=dossier)

    # BUY_READY / WATCH / activate_backfill -> a draft thesis and its triggers.
    # journal-FK order: the verdict entry first, then the thesis references it.
    entry_id = journal.append(conn, EntryIn(
        decision_type="gate_verdict", decision_subtype=_VERDICT_SUBTYPE[v],
        ticker=state["ticker"], system_recommendation=system_rec,
        owner_action="no_action",
        reasoning_at_the_moment=state.get("status_buy_rebuttal")
        or state.get("displacement_note"),
        actor="owner"), clock=clock)

    fields = ThesisFields(
        business_model_2s=state["business_model_2s"],
        moat_types=tuple(state["moat_types"]),
        moat_evidence=state["moat_evidence"],
        owner_earnings_json=(dossier or {}).get("owner_earnings_json", "{}"),
        owner_earnings_narrative=state.get("owner_earnings_narrative", ""),
        value_at_purchase=None,                 # filled at true activation (contract)
        fair_band_low=state["fair_band_low"], fair_band_high=state["fair_band_high"],
        denominator_note=state.get("denominator_note"),
        conviction=state["conviction"], mgmt_trust=state["mgmt_trust"],
        mgmt_trust_note=state.get("mgmt_trust_note"), circle_fit=state["circle_fit"],
        circle_fit_note=state.get("circle_fit_note"),
        ten_year_statement=state["ten_year_statement"],
        status_buy_flag=state["status_buy_flag"],
        status_buy_note=state.get("status_buy_note"))
    specs = [TriggerSpec(
        type=t["type"], statement=t["statement"], metric=t.get("metric"),
        comparator=t.get("comparator"), threshold=t.get("threshold"),
        moat_link=t.get("moat_link"), persistence=t["persistence"],
        yes_means=t.get("yes_means")) for t in state["triggers"]]
    origin = "backfill" if mode == "backfill" else "gate"
    thesis_id = register.create_thesis(conn, ticker=state["ticker"], origin=origin,
                                       fields=fields, triggers=specs,
                                       journal_ref=entry_id, clock=clock)
    return GateOutcome(
        ticker=state["ticker"], mode=mode, verdict=v, thesis_id=thesis_id,
        reason_class=None,
        suggested_max_weight_pct=verdict.get("suggested_max_weight_pct"),
        standing_questions=tuple(verdict.get("standing_questions", ())),
        journal_entry_id=entry_id, dossier=dossier)


def _verdict_text(v: str, verdict: dict, dossier: dict | None) -> str:
    if v == "PASS":
        return f"Gate verdict PASS ({verdict.get('reason_class')})."
    if v == "no_thesis_exists":
        return ("Backfill: no thesis exists -> treated as broken -> sell advice, "
                "cost basis ignored.")
    if v == "activate_backfill":
        return "Backfill: thesis activated for an existing holding."
    m = (dossier or {}).get("current_multiple")
    tail = f" Current multiple {m}x." if m is not None else ""
    if v == "BUY_READY":
        return (f"Gate verdict BUY_READY. Suggested max initial weight "
                f"{verdict.get('suggested_max_weight_pct')}%.{tail} "
                "This is an invitation, not an instruction.")
    return f"Gate verdict WATCH. Business passes; price above the fair band.{tail}"


import json

from agentcy import config


def start(conn, *, ticker: str, mode: str, ask_owner: AskOwner, clock: Clock,
          store=_store_default) -> GateOutcome:
    """Open a gate_session and run C.2-C.6 to a verdict. mode in {'gate','backfill'}.
    Re-pitch confrontation (C.1) is enforced by the CLI before calling start."""
    started = db.to_iso(clock.now())
    session_id = db.append_gate_session(conn, ticker=ticker, mode=mode,
                                        started_at=started)
    state = {"ticker": ticker}
    db.update_gate_session(conn, session_id, step="circle",
                           state_json=json.dumps(state), status="active",
                           updated_at=started)
    return _drive(conn, session_id, ticker=ticker, mode=mode, state=state,
                  step="circle", ask_owner=ask_owner, clock=clock, store=store)


def resume(conn, *, session_id: int, ask_owner: AskOwner, clock: Clock,
           store=_store_default) -> GateOutcome:
    """Continue an active session from its persisted step (resumability)."""
    row = db.fetch_gate_session(conn, session_id)
    if row is None or row["status"] != "active":
        raise ValueError(f"gate_session {session_id} is not active")
    state = json.loads(row["state_json"])
    return _drive(conn, session_id, ticker=row["ticker"], mode=row["mode"],
                  state=state, step=row["step"], ask_owner=ask_owner, clock=clock,
                  store=store)


def abandon(conn, session_id: int, *, clock: Clock) -> None:
    row = db.fetch_gate_session(conn, session_id)
    if row is None:
        return
    db.update_gate_session(conn, session_id, step=row["step"],
                           state_json=row["state_json"], status="abandoned",
                           updated_at=db.to_iso(clock.now()))


def _drive(conn, session_id, *, ticker, mode, state, step, ask_owner, clock,
           store) -> GateOutcome:
    """Run the machine from `step` to verdict, persisting after every completed step."""
    as_of = clock.now()
    dossier = state.get("_dossier")
    while step != "verdict":
        if step == "circle":
            step = step_circle(state, ask_owner)
        elif step == "hell_no":
            step = step_hell_no(state, ask_owner)
        elif step == "dossier":
            if mode == "backfill":
                # backfill still runs the full dossier (C.6); pause propagates up
                dossier = build_dossier(conn, ticker, as_of=as_of, store=store)
                state["_dossier"] = dossier
                step = "judgment"
            else:
                try:
                    dossier = build_dossier(conn, ticker, as_of=as_of, store=store)
                except DossierPaused:
                    _persist(conn, session_id, step="dossier", state=state, clock=clock,
                             status="active")
                    raise
                state["_dossier"] = dossier
                step = "judgment"
        elif step == "judgment":
            step = step_judgment(state, ask_owner)
        elif step == "drafting":
            step = step_drafting(state, ask_owner)
        _persist(conn, session_id, step=step, state=state, clock=clock, status="active")

    dossier = state.get("_dossier")
    verdict = _run_verdict(conn, mode=mode, state=state, dossier=dossier,
                           ask_owner=ask_owner, clock=clock)
    outcome = _finalize(conn, mode=mode, state=state, dossier=dossier,
                        verdict=verdict, clock=clock)
    _persist(conn, session_id, step="verdict", state=state, clock=clock, status="done")
    return outcome


def _run_verdict(conn, *, mode, state, dossier, ask_owner, clock) -> dict:
    """Classify, then apply the two BUY_READY frictions (displacement, status
    rebuttal) which need the owner and live DB state."""
    if mode == "backfill":
        # backfill has no price verdict (BUF-12): a pending PASS means the owner
        # could not affirm a thesis for a held position -> no_thesis_exists (FR1,
        # honest admission -> broken -> sell advice); otherwise the business
        # passed -> activate_backfill.
        if "pending_pass" in state:
            return {"verdict": "no_thesis_exists",
                    "reason_class": state["pending_pass"]["reason_class"],
                    "note": state["pending_pass"]["note"], "standing_questions": (),
                    "suggested_max_weight_pct": None, "requires_status_rebuttal": False}
        return {"verdict": "activate_backfill", "reason_class": None, "note": None,
                "standing_questions": (), "suggested_max_weight_pct": None,
                "requires_status_rebuttal": False}
    config_map = config.effective(conn)
    verdict = classify_verdict(tmp_db_unused=None, state=state, dossier=dossier,
                               config_map=config_map)
    if verdict["verdict"] == "BUY_READY":
        note = _displacement_note(conn, ask_owner, as_of=clock.now())
        if note:
            state["displacement_note"] = note
        if verdict["requires_status_rebuttal"]:
            state["status_buy_rebuttal"] = _status_rebuttal(ask_owner)
    return verdict


def _persist(conn, session_id, *, step, state, clock, status) -> None:
    db.update_gate_session(conn, session_id, step=step, state_json=json.dumps(state),
                           status=status, updated_at=db.to_iso(clock.now()))
