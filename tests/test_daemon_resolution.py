"""FIX.1 end-to-end: the fire -> resolve loop. A real fired alert, resolved ONLY through
production entry points (daemon.handle / cli ask-answer), must journal a trigger_resolution,
transition the thesis, resolve the alert row, and re-arm the trigger on refute (B.3, §3.3).

These tests drive the PRODUCTION callback/free-text path, never hand-stitched side effects."""
from __future__ import annotations

from agentcy import db, runlog, triggers
from agentcy.tg import daemon


class _Client:
    def __init__(self):
        self.answered = []
        self.edited = []
        self.sent = []

    def answer_callback_query(self, cbq_id, *, text=None):
        self.answered.append((cbq_id, text))

    def edit_message_text(self, chat_id, message_id, html, *, reply_markup=None):
        self.edited.append((chat_id, message_id, html, reply_markup))
        return {"message_id": message_id}

    def send_message(self, chat_id, html, *, reply_markup=None):
        self.sent.append((html, reply_markup))
        return {"message_id": 900}


def _fire_alert(conn, seeded, clock):
    """Fire the seeded thesis's automated (margin_erosion) trigger through triggers.fire —
    the real B.3.1 entry point. Returns (alert_id, ask_id, trigger_id)."""
    tid = seeded["thesis_id"]
    run_id = runlog.start(conn, "weekly", "2026-07-11", clock=clock).run_id
    trig = next(t for t in db.fetch_armed_triggers(conn, tid) if t["type"] == "margin_erosion")
    outcome = triggers.CheckOutcome(trigger_id=trig["trigger_id"], result="FIRE",
                                    observed_value=18.0, headroom=-2.0, evaluable_from=None, note=None)
    alert_id = triggers.fire(conn, outcome, clock=clock, run_id=run_id)
    conn.commit()
    ask = next(a for a in db.fetch_open_asks(conn, kind="A") if a["alert_ref"] == alert_id)
    return alert_id, ask["ask_id"], trig["trigger_id"]


def _cb(data, msg_id=77, owner=555):
    return {"id": "CBQ", "from": {"id": owner},
            "message": {"chat": {"id": owner}, "message_id": msg_id},
            "data": data}


def test_confirm_broken_journals_transitions_resolves(seeded_portfolio, fixed_clock):
    conn = seeded_portfolio["conn"]
    tid = seeded_portfolio["thesis_id"]
    alert_id, ask_id, _trig = _fire_alert(conn, seeded_portfolio, fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "under_review"
    client = _Client()

    # first tap: the confirm shows the confirm2 gate, does NOT resolve yet (§3.3 two-step)
    daemon.handle(conn, {"update_id": 1, "callback_query": _cb(f"alert:confirm:{ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "under_review"
    assert db.fetch_alert(conn, alert_id)["status"] == "open"

    # second explicit tap: the terminal confirm applies all consequences
    daemon.handle(conn, {"update_id": 2, "callback_query": _cb(f"alert:confirm2:{ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)

    assert db.fetch_current_thesis_status(conn, tid)["status"] == "broken"
    assert db.fetch_alert(conn, alert_id)["status"] == "confirmed_broken"
    assert not db.fetch_open_alerts(conn)
    res = [e for e in db.fetch_journal_entries(conn, decision_type="trigger_resolution")
           if e["decision_subtype"] == "confirmed_broken"]
    assert len(res) == 1
    # sell advice was enqueued (cost basis ignored)
    assert any(r["kind"] == "alert" or "sell" in (r["payload_html"] or "").lower()
               for r in db.fetch_outbox_queued(conn))


def test_refute_requires_evidence_then_rearms(seeded_portfolio, fixed_clock):
    conn = seeded_portfolio["conn"]
    tid = seeded_portfolio["thesis_id"]
    alert_id, ask_id, trig_id = _fire_alert(conn, seeded_portfolio, fixed_clock)
    client = _Client()

    # tap Refute: opens the ForceReply for evidence, does NOT resolve yet (B.3.2)
    daemon.handle(conn, {"update_id": 1, "callback_query": _cb(f"alert:refute:{ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "under_review"
    assert db.fetch_alert(conn, alert_id)["status"] == "open"

    # the owner replies to the ForceReply prompt with the written evidence
    evidence = "The margin dip is a one-time cloud migration charge; recurring FCF is intact."
    reply = {"update_id": 2, "message": {"chat": {"id": 555}, "text": evidence,
             "reply_to_message": {"text": f"Refuting for MSFT. Write the evidence. [{ask_id}]"}}}
    daemon.handle(conn, reply, client=client, clock=fixed_clock, owner_chat_id=555)

    assert db.fetch_current_thesis_status(conn, tid)["status"] == "intact"
    assert db.fetch_alert(conn, alert_id)["status"] == "refuted"
    assert not db.fetch_open_alerts(conn)
    res = [e for e in db.fetch_journal_entries(conn, decision_type="trigger_resolution")
           if e["decision_subtype"] == "refuted"]
    assert len(res) == 1 and evidence in (res[0]["reasoning_at_the_moment"] or "")
    # trigger re-armed: still armed (retired_at NULL) and no open alert blocks a future fire
    assert any(t["trigger_id"] == trig_id for t in db.fetch_armed_triggers(conn, tid))


def test_revise_only_after_refute_journals_intent(seeded_portfolio, fixed_clock):
    """Goalpost guard A.3: revise is not reachable until a refute is recorded; once it is,
    tapping [Revise] journals the intent (routed to the desk), never a phone-typed threshold."""
    conn = seeded_portfolio["conn"]
    _alert_id, ask_id, _trig = _fire_alert(conn, seeded_portfolio, fixed_clock)
    client = _Client()

    # revise BEFORE a refute is refused (guard A.3): nothing journaled
    daemon.handle(conn, {"update_id": 1, "callback_query": _cb(f"alert:revise:{ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    assert not db.fetch_journal_entries(conn, decision_type="thesis_revision")

    # record a refute through the production path (tap + evidence reply)
    daemon.handle(conn, {"update_id": 2, "callback_query": _cb(f"alert:refute:{ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    daemon.handle(conn, {"update_id": 3, "message": {"chat": {"id": 555}, "text": "moat intact",
                  "reply_to_message": {"text": f"Refuting [{ask_id}]"}}},
                  client=client, clock=fixed_clock, owner_chat_id=555)

    # now revise journals the intent (desk-routed)
    daemon.handle(conn, {"update_id": 4, "callback_query": _cb(f"alert:revise:{ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    intents = db.fetch_journal_entries(conn, decision_type="thesis_revision")
    assert len(intents) == 1 and intents[0]["ask_ref"] == ask_id


def test_confirm_then_back_leaves_alert_open(seeded_portfolio, fixed_clock):
    """The two-step gate is a real interstitial: [Confirm broken] then [Go back] resolves
    nothing — thesis stays under_review, alert stays open."""
    conn = seeded_portfolio["conn"]
    tid = seeded_portfolio["thesis_id"]
    alert_id, ask_id, _trig = _fire_alert(conn, seeded_portfolio, fixed_clock)
    client = _Client()

    daemon.handle(conn, {"update_id": 1, "callback_query": _cb(f"alert:confirm:{ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    daemon.handle(conn, {"update_id": 2, "callback_query": _cb(f"alert:back:{ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)

    assert db.fetch_current_thesis_status(conn, tid)["status"] == "under_review"
    assert db.fetch_alert(conn, alert_id)["status"] == "open"
    assert not db.fetch_journal_entries(conn, decision_type="trigger_resolution")


def _mint_v_ask(conn, clock, thesis_ref):
    from agentcy import asks
    return asks.mint(conn, kind="V",
                     prompt="BUY_READY >=30d with no position. Reject or move to WATCH?",
                     options=("reject", "watch"), thesis_ref=thesis_ref, clock=clock)


def test_vfu_reject_journals_advice_rejected(seeded_portfolio, fixed_clock):
    conn = seeded_portfolio["conn"]
    tid = seeded_portfolio["thesis_id"]              # a real thesis id -> ticker MSFT
    item_id = db.append_watchlist_item(conn, ticker="MSFT", added_at=db.to_iso(fixed_clock.now()),
                                       idea_source="own_research", one_line_why="watch it")
    db.update_watchlist_stage(conn, item_id, stage="buy_ready_waiting",
                              stage_changed_at=db.to_iso(fixed_clock.now()), thesis_ref=tid)
    ask = _mint_v_ask(conn, fixed_clock, tid)
    db.update_ask_state(conn, ask.ask_id, status="open")
    conn.commit()
    client = _Client()

    daemon.handle(conn, {"update_id": 1, "callback_query": _cb(f"vfu:reject:{ask.ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)

    rej = db.fetch_journal_entries(conn, decision_type="advice_rejected")
    assert len(rej) == 1 and rej[0]["ask_ref"] == ask.ask_id
    assert db.fetch_watchlist(conn)[0]["stage"] == "rejected"


def test_vfu_watch_arms_fair_entry(seeded_portfolio, fixed_clock):
    conn = seeded_portfolio["conn"]
    tid = seeded_portfolio["thesis_id"]
    item_id = db.append_watchlist_item(conn, ticker="MSFT", added_at=db.to_iso(fixed_clock.now()),
                                       idea_source="own_research", one_line_why="watch it")
    db.update_watchlist_stage(conn, item_id, stage="buy_ready_waiting",
                              stage_changed_at=db.to_iso(fixed_clock.now()), thesis_ref=tid)
    ask = _mint_v_ask(conn, fixed_clock, tid)
    db.update_ask_state(conn, ask.ask_id, status="open")
    conn.commit()
    client = _Client()

    daemon.handle(conn, {"update_id": 1, "callback_query": _cb(f"vfu:watch:{ask.ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)

    assert db.fetch_watchlist(conn)[0]["stage"] == "gate_approved_waiting"
