"""P7.10: free-text pending-ask machine — reply-to, exactly-one, disambiguation, redirect (§4/§3.6)."""
from __future__ import annotations

from agentcy import db
from agentcy.asks import mint
from agentcy.tg import daemon


class _Client:
    def __init__(self):
        self.sent = []
    def send_message(self, chat_id, html, *, reply_markup=None):
        self.sent.append((html, reply_markup)); return {"message_id": 1}
    def answer_callback_query(self, *a, **k): pass
    def edit_message_text(self, *a, **k): return {"message_id": 1}


def _msg(text, *, reply_to=None, owner=555):
    m = {"chat": {"id": owner}, "text": text}
    if reply_to is not None:
        m["reply_to_message"] = {"text": f"Refute evidence [{reply_to}]"}
    return {"update_id": 1, "message": m}


def test_reply_to_binds_to_named_ask(tmp_db, fixed_clock):
    ask = mint(tmp_db, kind="A", prompt="Refute CRWD/T2", options=[], expects_freetext=True,
               clock=fixed_clock)
    db.update_ask_state(tmp_db, ask.ask_id, status="open")
    client = _Client()
    daemon.handle(tmp_db, _msg("the moat still compounds", reply_to=ask.ask_id),
                  client=client, clock=fixed_clock, owner_chat_id=555)
    assert db.fetch_ask(tmp_db, ask.ask_id)["status"] == "answered"
    assert any(ask.ask_id in html for html, _ in client.sent)  # echoed confirmation


def test_exactly_one_open_attributes_without_reply_to(tmp_db, fixed_clock):
    ask = mint(tmp_db, kind="N", prompt="Other note", options=[], expects_freetext=True,
               clock=fixed_clock)
    db.update_ask_state(tmp_db, ask.ask_id, status="open")
    client = _Client()
    daemon.handle(tmp_db, _msg("it was a spin-off"), client=client, clock=fixed_clock,
                  owner_chat_id=555)
    assert db.fetch_ask(tmp_db, ask.ask_id)["status"] == "answered"


def test_several_open_shows_disambiguation_keyboard_no_guess(tmp_db, fixed_clock):
    a1 = mint(tmp_db, kind="A", prompt="Refute CRWD", options=[], expects_freetext=True, clock=fixed_clock)
    a2 = mint(tmp_db, kind="N", prompt="Note VEEV", options=[], expects_freetext=True, clock=fixed_clock)
    db.update_ask_state(tmp_db, a1.ask_id, status="open")
    db.update_ask_state(tmp_db, a2.ask_id, status="open")
    client = _Client()
    daemon.handle(tmp_db, _msg("some evidence"), client=client, clock=fixed_clock, owner_chat_id=555)
    # nothing bound; a keyboard offering both asks is shown
    html, markup = client.sent[-1]
    assert markup is not None
    assert db.fetch_ask(tmp_db, a1.ask_id)["status"] == "open"
    assert db.fetch_ask(tmp_db, a2.ask_id)["status"] == "open"


def test_no_open_ask_gets_gentle_redirect_not_stored(tmp_db, fixed_clock):
    client = _Client()
    daemon.handle(tmp_db, _msg("hello are you there"), client=client, clock=fixed_clock,
                  owner_chat_id=555)
    html, _ = client.sent[-1]
    assert "/status" in html and "only act on" in html.lower()


def test_empty_reply_triggers_single_reprompt(tmp_db, fixed_clock):
    ask = mint(tmp_db, kind="N", prompt="Other note", options=[], expects_freetext=True, clock=fixed_clock)
    db.update_ask_state(tmp_db, ask.ask_id, status="open")
    client = _Client()
    daemon.handle(tmp_db, _msg("   ", reply_to=ask.ask_id), client=client, clock=fixed_clock,
                  owner_chat_id=555)
    assert db.fetch_ask(tmp_db, ask.ask_id)["status"] == "reprompted"


def test_backfill_ratify_freetext_reply_binds_to_edit_and_stays_draft(tmp_db, fixed_clock):
    """RF4: a free-text reply to the backfill ratify N-ask binds to choice='edit', so the owner's
    edit text is journaled verbatim and the thesis stays draft (never a fabricated empty edit,
    never an activation)."""
    from agentcy import backfill, journal
    from agentcy.journal import EntryIn
    je = journal.append(tmp_db, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    held = backfill.HeldWithoutThesis(symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock",
                                      quantity=5.0, opened_at="2024-01-15T00:00:00Z",
                                      invested_eur=3000.0)
    baseline = backfill.Baseline(yf_ticker="ADYEN", revenue_yoy=14.2, owner_fcf_margin=30.0,
                                 net_debt_ebitda=1.5, shares_yoy=1.2, owner_earnings_json="{}")
    tid = backfill.create_backfill_draft(tmp_db, held, baseline, journal_ref=je, clock=fixed_clock)
    ask = backfill.mint_ratify_ask(tmp_db, tid, held, clock=fixed_clock)
    db.update_ask_state(tmp_db, ask.ask_id, status="open")
    client = _Client()
    text = "conviction is high; add an owner-attested CEO-departure trigger"
    daemon.handle(tmp_db, _msg(text, reply_to=ask.ask_id), client=client, clock=fixed_clock,
                  owner_chat_id=555)
    assert (db.fetch_ask(tmp_db, ask.ask_id)["answer_json"] is not None
            and '"choice": "edit"' in db.fetch_ask(tmp_db, ask.ask_id)["answer_json"])
    edits = [e for e in db.fetch_journal_entries(tmp_db, decision_type="config_or_designation")
             if e["thesis_ref"] == tid and e["ask_ref"] == ask.ask_id]
    assert edits and edits[-1]["reasoning_at_the_moment"] == text
    assert db.fetch_current_thesis_status(tmp_db, tid)["status"] == "draft"  # not monitored
