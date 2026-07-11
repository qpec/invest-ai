"""agentcy/asks.py — D.5 first-class ask objects; state machine per tg-spec §3/§7."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from agentcy import db
from agentcy.clock import Clock, effective_deadline, is_paused

KINDS = frozenset({"A", "Q", "R", "F", "V", "N"})


@dataclass(frozen=True)
class Ask:
    ask_id: str
    kind: str
    prompt: str
    options: tuple[str, ...]
    expects_freetext: bool
    thesis_ref: str | None
    trigger_ref: int | None
    alert_ref: int | None
    deadline: datetime | None
    status: str
    answer: Mapping | None
    tg_message_id: int | None
    created_at: datetime


@dataclass(frozen=True)
class AnswerOutcome:
    ask: Ask
    accepted: bool
    already_recorded: bool
    consequence: str


def _row_to_ask(row) -> Ask:
    return Ask(
        ask_id=row["ask_id"], kind=row["kind"], prompt=row["prompt"],
        options=tuple(json.loads(row["options_json"])),
        expects_freetext=bool(row["expects_freetext"]),
        thesis_ref=row["thesis_ref"], trigger_ref=row["trigger_ref"], alert_ref=row["alert_ref"],
        deadline=db.from_iso(row["deadline"]) if row["deadline"] else None,
        status=row["status"],
        answer=json.loads(row["answer_json"]) if row["answer_json"] else None,
        tg_message_id=row["tg_message_id"],
        created_at=db.from_iso(row["created_at"]),
    )


def mint(conn, *, kind: str, prompt: str, options: Sequence[str], expects_freetext: bool = False,
         thesis_ref: str | None = None, trigger_ref: int | None = None,
         alert_ref: int | None = None, deadline: str | None = None,
         run_id: int | None = None, clock: Clock) -> Ask:
    """Create the '<K><seq>' row (K in {A,Q,R,F,V,N}) BEFORE any message exists (tg-spec §3.1)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    seq = db.next_ask_seq(conn, kind)
    ask_id = f"{kind}{seq}"
    db.append_ask(conn, {
        "ask_id": ask_id, "kind": kind, "seq": seq, "created_at": db.to_iso(clock.now()),
        "prompt": prompt, "options_json": json.dumps(list(options)),
        "expects_freetext": 1 if expects_freetext else 0,
        "thesis_ref": thesis_ref, "trigger_ref": trigger_ref, "alert_ref": alert_ref,
        "deadline": deadline, "run_id": run_id,
    })
    return _row_to_ask(db.fetch_ask(conn, ask_id))


def get(conn, ask_id: str) -> Ask | None:
    row = db.fetch_ask(conn, ask_id)
    return _row_to_ask(row) if row else None


def open_asks(conn, *, kind: str | None = None) -> list[Ask]:
    """Open + reprompted asks (the /status open-loops list)."""
    return [_row_to_ask(r) for r in db.fetch_open_asks(conn, kind=kind)
            if r["status"] in ("open", "reprompted")]


_CONSEQUENCE = {
    ("A", "confirm"): "alert.confirm2", ("A", "confirm2"): "alert.confirm2",
    ("A", "refute"): "alert.refute", ("A", "revise"): "alert.revise",
    ("Q", "yes"): "trigger.answer", ("Q", "no"): "trigger.answer",
    ("Q", "cant"): "trigger.unverifiable",
}


def _consequence(kind: str, choice: str | None) -> str:
    if (kind, choice) in _CONSEQUENCE:
        return _CONSEQUENCE[(kind, choice)]
    prefix = {"R": "recon", "F": "reaff", "V": "vfu", "N": "note"}.get(kind, kind.lower())
    return f"{prefix}.{choice}" if choice else f"{prefix}.recorded"


def answer(conn, ask_id: str, *, choice: str | None = None, text: str | None = None,
           clock: Clock, tg_message_id: int | None = None) -> AnswerOutcome:
    """Server-side validation (exists, open, option in set); already answered -> already_recorded."""
    row = db.fetch_ask(conn, ask_id)
    if row is None:
        raise KeyError(ask_id)
    ask = _row_to_ask(row)
    if ask.status in ("answered", "unanswered"):
        return AnswerOutcome(ask=ask, accepted=True, already_recorded=True,
                             consequence=_consequence(ask.kind, (ask.answer or {}).get("choice")))
    options = set(ask.options)
    if choice is not None and options and choice not in options:
        return AnswerOutcome(ask=ask, accepted=False, already_recorded=False, consequence="rejected")
    if choice is None and not (ask.expects_freetext and (text or "").strip()):
        return AnswerOutcome(ask=ask, accepted=False, already_recorded=False, consequence="rejected")
    payload: dict = {}
    if choice is not None:
        payload["choice"] = choice
    if text is not None and text.strip():
        payload["text"] = text
    db.update_ask_state(conn, ask_id, status="answered", answer_json=json.dumps(payload),
                        answered_at=db.to_iso(clock.now()), tg_message_id=tg_message_id)
    return AnswerOutcome(ask=_row_to_ask(db.fetch_ask(conn, ask_id)), accepted=True,
                         already_recorded=False, consequence=_consequence(ask.kind, choice))


def apply_consequence(conn, outcome: AnswerOutcome, *, clock: Clock,
                      evidence: str | None = None, run_id: int | None = None) -> str | None:
    """The shared fire->resolve dispatcher (B.3, tg-spec §3.3/§3.10a). Called by BOTH
    daemon._handle_callback and cli._cmd_ask after asks.answer accepts an owner decision.
    Dispatches on outcome.consequence; every owner-decision branch writes a JournalEntry
    (global invariant 2). Returns a short owner-facing note, or None when nothing to say.

    Function-level imports keep asks.py free of the register/triggers/gate cycle (triggers
    imports asks)."""
    if not outcome.accepted or outcome.already_recorded:
        return None
    cons = outcome.consequence
    if cons == "alert.confirm2":
        return _apply_confirm_broken(conn, outcome.ask, clock=clock, run_id=run_id)
    if cons == "alert.refute":
        return _apply_refute(conn, outcome.ask, clock=clock, evidence=evidence, run_id=run_id)
    if cons == "alert.revise":
        return _apply_revise(conn, outcome.ask, clock=clock, run_id=run_id)
    if cons == "vfu.reject":
        return _apply_vfu_reject(conn, outcome.ask, clock=clock, evidence=evidence, run_id=run_id)
    if cons == "vfu.watch":
        return _apply_vfu_watch(conn, outcome.ask, clock=clock, run_id=run_id)
    if cons in ("trigger.answer", "trigger.unverifiable"):
        return _apply_trigger_check(conn, outcome.ask, clock=clock, run_id=run_id)
    if cons.startswith("recon."):
        return _apply_reconciliation(conn, outcome.ask, cons[len("recon."):],
                                     clock=clock, evidence=evidence, run_id=run_id)
    if cons == "note.approve":
        return _apply_backfill_approve(conn, outcome.ask, clock=clock, run_id=run_id)
    if cons == "note.edit":
        return _apply_backfill_edit(conn, outcome.ask, clock=clock, evidence=evidence,
                                    run_id=run_id)
    return None                                            # F/N notes: the answered row IS the record


def _alert_for(conn, ask: Ask):
    """The open alert this A-ask resolves (alert_ref pinned at fire); None if already closed."""
    if ask.alert_ref is None:
        return None
    return db.fetch_alert(conn, ask.alert_ref)


def _sell_advice_line(conn, thesis_id: str) -> str:
    """Deterministic B.3 sell-advice resolution line — advisory mood, cost basis disowned
    (§3.3; the lint forbids imperative 'sell' and '!' in this class, so this is phrased as
    advice with cost basis explicitly not shown)."""
    from agentcy.render.common import esc
    ticker = (db.fetch_thesis(conn, thesis_id) or {"ticker": thesis_id})["ticker"]
    return esc(
        f"{ticker}: the thesis is now broken. The plan is to exit the full position — "
        "cost basis is not shown and plays no part. A new position later needs a fresh Gate run.")


def _apply_confirm_broken(conn, ask: Ask, *, clock: Clock, run_id: int | None) -> str:
    """confirm-broken terminal (B.3.2): journal trigger_resolution[confirmed_broken],
    thesis -> broken, resolve the alert, enqueue the sell-advice line (cost basis ignored)."""
    from agentcy import journal, register
    from agentcy.journal import EntryIn
    from agentcy.tg import outbox
    thesis_id = ask.thesis_ref
    je = journal.append(conn, EntryIn(
        decision_type="trigger_resolution", decision_subtype="confirmed_broken",
        ticker=None, thesis_ref=thesis_id,
        system_recommendation="sell advice for the full position, cost basis ignored (B.3.2)",
        owner_action="followed", reasoning_at_the_moment="Owner confirmed the thesis is broken.",
        inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
    status = db.fetch_current_thesis_status(conn, thesis_id)["status"]
    if status == "under_review":
        register.transition(conn, thesis_id, "broken", cause="owner confirmed broken",
                            cause_ref=str(je), clock=clock)
    if ask.alert_ref is not None:
        alert = _alert_for(conn, ask)
        if alert is not None and alert["status"] == "open":
            db.update_alert_resolution(conn, ask.alert_ref, status="confirmed_broken",
                                       resolved_at=db.to_iso(clock.now()), resolution_journal_ref=je)
        outbox.enqueue(conn, dedupe_key=f"alert:{ask.alert_ref}:resolution", kind="alert",
                       payload_html=_sell_advice_line(conn, thesis_id), ask_ref=ask.ask_id,
                       run_id=run_id, clock=clock)
    return "Thesis marked broken. Sell advice issued for the full position; cost basis ignored."


def _apply_refute(conn, ask: Ask, *, clock: Clock, evidence: str | None, run_id: int | None) -> str:
    """refute (B.3.2): journal trigger_resolution[refuted] with the evidence VERBATIM,
    thesis -> intact, resolve the alert, re-arm the trigger (resolving the alert clears the
    fire idempotence block, so the armed trigger can fire again)."""
    from agentcy import journal, register
    from agentcy.journal import EntryIn
    thesis_id = ask.thesis_ref
    je = journal.append(conn, EntryIn(
        decision_type="trigger_resolution", decision_subtype="refuted",
        ticker=None, thesis_ref=thesis_id,
        system_recommendation="written evidence recorded; trigger re-arms, thesis returns to intact (B.3.2)",
        owner_action="overridden", reasoning_at_the_moment=(evidence or "").strip(),
        inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
    status = db.fetch_current_thesis_status(conn, thesis_id)["status"]
    if status == "under_review":
        register.transition(conn, thesis_id, "intact", cause="owner refuted with evidence",
                            cause_ref=str(je), clock=clock)
    alert = _alert_for(conn, ask)
    if alert is not None and alert["status"] == "open":
        db.update_alert_resolution(conn, ask.alert_ref, status="refuted",
                                   resolved_at=db.to_iso(clock.now()), resolution_journal_ref=je)
    return "Refute recorded. Trigger re-armed; thesis intact."


def _apply_revise(conn, ask: Ask, *, clock: Clock, run_id: int | None) -> str:
    """revise (goalpost guard A.3): journal the INTENT to revise, routed to the desk — never
    a phone-typed threshold. Only reachable after a recorded refute (the daemon gates the
    affordance)."""
    from agentcy import journal
    from agentcy.journal import EntryIn
    journal.append(conn, EntryIn(
        decision_type="thesis_revision", ticker=None, thesis_ref=ask.thesis_ref,
        reasoning_at_the_moment="Owner intends to revise the trigger; make it at the desk (A.3).",
        owner_action="no_action", inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
    return ("Trigger revision is a versioned change — make it at the desk. I've journaled your "
            "intent and will echo the loosening with its headroom for 4 weeks (A.3).")


def _apply_vfu_reject(conn, ask: Ask, *, clock: Clock, evidence: str | None,
                      run_id: int | None) -> str:
    """V-ask reject (C.6 / §3.10a): journal advice_rejected, advance the watchlist item."""
    from agentcy import gate, journal
    from agentcy.journal import EntryIn
    ticker = _vfu_ticker(conn, ask)
    journal.append(conn, EntryIn(
        decision_type="advice_rejected", ticker=ticker, thesis_ref=ask.thesis_ref,
        reasoning_at_the_moment=((evidence or "").strip()
                                 or "Owner rejected the standing BUY_READY advice (C.6)."),
        owner_action="followed", inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
    if ticker is not None:
        gate.advance_watchlist_for_verdict(conn, ticker=ticker, verdict="PASS",
                                           thesis_id=ask.thesis_ref, clock=clock)
    return "Recorded: advice rejected."


def _apply_vfu_watch(conn, ask: Ask, *, clock: Clock, run_id: int | None) -> str:
    """V-ask watch (C.6 / §3.10a): move the item to gate_approved_waiting (arm fair-entry)."""
    from agentcy import gate
    ticker = _vfu_ticker(conn, ask)
    if ticker is not None:
        gate.advance_watchlist_for_verdict(conn, ticker=ticker, verdict="WATCH",
                                           thesis_id=ask.thesis_ref, clock=clock)
    return "Moved to WATCH; the daily fair-entry check now arms."


def _vfu_ticker(conn, ask: Ask) -> str | None:
    if ask.thesis_ref is None:
        return None
    th = db.fetch_thesis(conn, ask.thesis_ref)
    return th["ticker"] if th is not None else None


def _apply_trigger_check(conn, ask: Ask, *, clock: Clock, run_id: int | None) -> str | None:
    """Q-ask (prompted trigger question, B.3.4): record a trigger_check so the prompted
    trigger actually resolves. yes/no is scored against the committed yes_means (mirroring
    triggers._eval_prompted); can't-verify -> UNVERIFIABLE (never green)."""
    if ask.trigger_ref is None:
        return None
    choice = (ask.answer or {}).get("choice")
    trig = next((t for t in db.fetch_armed_triggers(conn)
                 if t["trigger_id"] == ask.trigger_ref), None)
    if choice == "cant" or trig is None:
        result = "UNVERIFIABLE"
    else:
        yes_fires = trig["yes_means"] == "fire"
        result = "FIRE" if (choice == "yes") == yes_fires else "PASS"
    db.append_trigger_check(conn, dict(
        trigger_id=ask.trigger_ref, run_id=run_id, checked_at=db.to_iso(clock.now()),
        result=result, observed_value=None, headroom=None, evaluable_from=None))
    return None


# Reconciliation choices carried by an R-ask (E.1/§3.4). Each maps to a journal
# decision_type so answering closes the FR8 off-system-trade loop (global invariant 2:
# every owner decision produces a JournalEntry). The R-ask's thesis_ref carries the symbol.
_FLOW_DIRECTIONS = {"deposit": "deposit", "withdrawal": "withdrawal",
                    "dividend": "dividend", "other": "other"}


def _apply_reconciliation(conn, ask: Ask, choice: str, *, clock: Clock,
                          evidence: str | None, run_id: int | None) -> str | None:
    """Dispatch a reconciliation R-ask choice (§3.4) to its journal (+ external_flow for the
    MA-12 cash-flow set). The snapshot the delta was reconciled against is the latest one at
    answer time (the R-ask is minted right after ingest and answered before the next snapshot).
    'ignore' is stored as a no-action journal note, not as portfolio truth."""
    from agentcy import journal, mirror
    from agentcy.journal import EntryIn
    symbol = ask.thesis_ref
    reason = (evidence or "").strip()

    if choice in _FLOW_DIRECTIONS:                          # unexplained_cash → MA-12 flow
        journal.append(conn, EntryIn(
            decision_type="config_or_designation", decision_subtype="external_flow",
            reasoning_at_the_moment=(reason or f"Owner confirmed the unexplained cash move was a {choice} (MA-12)."),
            owner_action="followed", inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"),
            clock=clock)
        recent = db.fetch_recent_snapshots(conn, 2)
        if recent:
            latest = recent[0]
            cash_delta = latest["cash_balance_eur"] - (recent[1]["cash_balance_eur"]
                                                       if len(recent) > 1 else 0.0)
            db.append_external_flow(
                conn, snapshot_id=latest["snapshot_id"], date=latest["as_of"],
                amount_eur=cash_delta, direction=_FLOW_DIRECTIONS[choice], ask_ref=ask.ask_id)
        return f"Recorded external flow: {choice}. It will not masquerade as alpha (MA-12)."

    if choice in ("backfill", "outside", "ignore", "gap"):
        subtype = "outside_framework" if choice == "outside" else "config_change"
        note = {
            "backfill": f"{symbol} enters the backfill queue by weight; a Gate run resolves the thesis (C.6).",
            "outside": f"{symbol} designated outside-framework (once-only designation, E.2).",
            "ignore": f"{symbol} flagged for re-check — not stored as portfolio truth (§3.4).",
            "gap": f"{symbol} carried at last-snapshot value; flagged in data-health (§3.4).",
        }[choice]
        je = journal.append(conn, EntryIn(
            decision_type="config_or_designation", decision_subtype=subtype, ticker=symbol,
            reasoning_at_the_moment=(reason or note), owner_action="followed",
            inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
        if choice == "backfill" and symbol is not None:
            mirror.designate(conn, symbol, "backfill_pending",
                             journal_ref=je, valid_from=db.to_iso(clock.now()))
        elif choice == "outside" and symbol is not None:
            mirror.designate(conn, symbol, "outside_framework",
                             journal_ref=je, valid_from=db.to_iso(clock.now()))
        return note

    if choice in ("add", "trim", "close"):                 # quantity_change / disappeared
        dtype = {"add": "add_to_position", "trim": "trim", "close": "sell"}[choice]
        default = {
            "add": f"Owner added to {symbol} off-system; the thesis is the falsifier (F.1).",
            "trim": f"Owner trimmed {symbol} off-system.",
            "close": f"Owner closed {symbol} off-system; advice was not the driver.",
        }[choice]
        journal.append(conn, EntryIn(
            decision_type=dtype, ticker=symbol, thesis_ref=None,
            reasoning_at_the_moment=(reason or default), owner_action="followed",
            inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
        return f"Recorded: {choice} on {symbol}."
    return None


def _apply_backfill_approve(conn, ask: Ask, *, clock: Clock, run_id: int | None) -> str | None:
    """Ratify a backfill DRAFT thesis: draft -> intact (arms the auto-derived triggers for the
    Watchdog). A no-op unless thesis_ref names a draft origin='backfill' thesis (so an ordinary
    N-note approve never activates anything).

    RF1 (BLOCKING, FR9): NEVER activate a thesis whose qualitative fields are still the
    deterministic placeholders. If approve is attempted while conviction is still 'medium' and
    the business-model / ten-year statement are still the draft placeholders (i.e. the owner +
    Claude never supplied real values via register.revise at the desk / Part B), REFUSE — the
    thesis stays draft and UNmonitored. Only real, owner-supplied judgment goes intact."""
    from agentcy import backfill, journal, register
    from agentcy.journal import EntryIn
    thesis_id = ask.thesis_ref
    if thesis_id is None:
        return None
    th = db.fetch_thesis(conn, thesis_id)
    st = db.fetch_current_thesis_status(conn, thesis_id)
    if th is None or th["origin"] != "backfill" or st is None or st["status"] != "draft":
        return None
    version = db.fetch_current_thesis_version(conn, thesis_id)
    if backfill.is_placeholder_draft(version):             # RF1: no owner judgment yet -> refuse
        journal.append(conn, EntryIn(
            decision_type="config_or_designation", decision_subtype="config_change",
            ticker=th["ticker"], thesis_ref=thesis_id,
            system_recommendation="approve refused: qualitative fields are still placeholders (FR9)",
            owner_action="no_action",
            reasoning_at_the_moment=("Owner tapped approve while the backfill thesis still carried "
                                     "system-chosen placeholder judgment (conviction/business-model/"
                                     "ten-year). Not activated (FR9); it stays draft until the real "
                                     "conviction and rationale are drafted."),
            inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
        return (f"{th['ticker']}: not ratified. The conviction and rationale are still "
                "placeholders — the backfill thesis stays draft (unmonitored) until you draft the "
                "real judgment. Reply with your edits, or draft it at the desk, then approve.")
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        ticker=th["ticker"], thesis_ref=thesis_id,
        system_recommendation="backfill thesis ratified -> intact + triggers armed",
        owner_action="followed",
        reasoning_at_the_moment="Owner ratified the backfill thesis (FR9 owner judgment).",
        inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
    register.activate(conn, thesis_id, cause="owner ratified backfill thesis", clock=clock)
    return f"{th['ticker']}: backfill thesis {thesis_id} ratified. Intact and monitored."


def _apply_backfill_edit(conn, ask: Ask, *, clock: Clock, evidence: str | None,
                         run_id: int | None) -> str | None:
    """Owner replied edits instead of approving: journal the text verbatim; the thesis stays
    draft (UNmonitored). The text feeds the Part-B drafting round; no field is mutated here."""
    from agentcy import journal
    from agentcy.journal import EntryIn
    thesis_id = ask.thesis_ref
    th = db.fetch_thesis(conn, thesis_id) if thesis_id else None
    if th is None or th["origin"] != "backfill":
        return None
    text = (evidence or (ask.answer or {}).get("text") or "").strip()
    journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        ticker=th["ticker"], thesis_ref=thesis_id,
        reasoning_at_the_moment=(text or "Owner requested edits to the backfill draft."),
        owner_action="no_action", inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"),
        clock=clock)
    return (f"{th['ticker']}: edits recorded; the backfill thesis stays draft (unmonitored) "
            "until you approve.")


def reprompt(conn, ask_id: str, *, clock: Clock) -> Ask:
    """Exactly ONE re-prompt (D.5): open -> reprompted; any other state raises."""
    row = db.fetch_ask(conn, ask_id)
    if row is None:
        raise KeyError(ask_id)
    if row["status"] != "open":
        raise ValueError(f"cannot reprompt {ask_id}: status is {row['status']!r}, not 'open'")
    db.update_ask_state(conn, ask_id, status="reprompted")
    return _row_to_ask(db.fetch_ask(conn, ask_id))


_UNANSWERED_CONSEQUENCE = {
    "A": "alert.ignored", "Q": "trigger.unverifiable", "F": "reaff.skip", "V": "vfu.unanswered",
}


def sweep_deadlines(conn, *, as_of: datetime) -> list[AnswerOutcome]:
    """Mark counted-unanswered past effective_deadline (pause-aware; frozen never fires).
    Returns one AnswerOutcome per newly-unanswered ask; the caller applies the per-kind side effect."""
    out: list[AnswerOutcome] = []
    for row in db.fetch_open_asks(conn):
        if row["status"] not in ("open", "reprompted") or not row["deadline"]:
            continue
        base = db.from_iso(row["deadline"])
        start = db.from_iso(row["created_at"])
        eff = effective_deadline(conn, base, start=start, as_of=as_of)
        if eff > as_of:
            continue                                          # not due (or frozen by a pause window)
        db.update_ask_state(conn, row["ask_id"], status="unanswered")
        ask = _row_to_ask(db.fetch_ask(conn, row["ask_id"]))
        cons = _UNANSWERED_CONSEQUENCE.get(
            ask.kind, f"{ {'R':'recon','N':'note'}.get(ask.kind, ask.kind.lower()) }.unanswered")
        out.append(AnswerOutcome(ask=ask, accepted=False, already_recorded=False, consequence=cons))
    return out


def resolve_freetext(conn, *, reply_to_ask_id: str | None):
    """tg-spec §4: reply-to authoritative; else one-open -> that ask; several -> list;
    none -> None (never parsed, never stored)."""
    open_ft = [_row_to_ask(r) for r in db.fetch_open_asks(conn)
               if r["status"] in ("open", "reprompted") and r["expects_freetext"]]
    if reply_to_ask_id is not None:
        for a in open_ft:
            if a.ask_id == reply_to_ask_id:
                return a
        # reply-to to a closed/absent ask falls through to the open-set rules
    if len(open_ft) == 1:
        return open_ft[0]
    if len(open_ft) > 1:
        return open_ft
    return None
