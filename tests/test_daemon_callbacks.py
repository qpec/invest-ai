"""P7.9: callback routing validates against ask rows, always acks, edits on resolve (§3.1/§3.10/§5.5)."""
from __future__ import annotations

from agentcy import db
from agentcy.asks import mint
from agentcy.tg import daemon


class _Client:
    def __init__(self):
        self.answered = []
        self.edited = []

    def answer_callback_query(self, cbq_id, *, text=None):
        self.answered.append((cbq_id, text))

    def edit_message_text(self, chat_id, message_id, html, *, reply_markup=None):
        self.edited.append((chat_id, message_id, html, reply_markup))
        return {"message_id": message_id}

    def send_message(self, chat_id, html, *, reply_markup=None):
        return {"message_id": 1}


def _cb(ask_id, data, msg_id=77, owner=555):
    return {"id": "CBQ", "from": {"id": owner},
            "message": {"chat": {"id": owner}, "message_id": msg_id},
            "data": data}


def test_valid_prompted_answer_acks_and_edits(tmp_db, fixed_clock):
    ask = mint(tmp_db, kind="Q", prompt="Founder departed?", options=["yes", "no", "cant"],
               clock=fixed_clock)
    db.update_ask_state(tmp_db, ask.ask_id, status="open", tg_message_id=77)
    client = _Client()
    daemon.handle(tmp_db, {"update_id": 1, "callback_query": _cb(ask.ask_id, f"trig:no:{ask.ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    assert client.answered  # always acked (§5.5)
    assert client.edited and client.edited[0][1] == 77  # keyboard stripped on the original msg
    assert db.fetch_ask(tmp_db, ask.ask_id)["status"] == "answered"


def test_double_tap_is_idempotent(tmp_db, fixed_clock):
    ask = mint(tmp_db, kind="Q", prompt="x", options=["yes", "no"], clock=fixed_clock)
    db.update_ask_state(tmp_db, ask.ask_id, status="open", tg_message_id=77)
    client = _Client()
    upd = {"update_id": 1, "callback_query": _cb(ask.ask_id, f"trig:yes:{ask.ask_id}")}
    daemon.handle(tmp_db, upd, client=client, clock=fixed_clock, owner_chat_id=555)
    daemon.handle(tmp_db, {**upd, "update_id": 2}, client=client, clock=fixed_clock, owner_chat_id=555)
    # second tap: acked with "already recorded", no second answered-transition side effect
    assert any("recorded" in (t or "").lower() for _, t in client.answered)


def test_option_not_in_enumerated_set_is_refused(tmp_db, fixed_clock):
    ask = mint(tmp_db, kind="Q", prompt="x", options=["yes", "no"], clock=fixed_clock)
    db.update_ask_state(tmp_db, ask.ask_id, status="open", tg_message_id=77)
    client = _Client()
    daemon.handle(tmp_db, {"update_id": 1,
                           "callback_query": _cb(ask.ask_id, f"trig:maybe:{ask.ask_id}")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    assert any("no longer available" in (t or "").lower() for _, t in client.answered)
    assert db.fetch_ask(tmp_db, ask.ask_id)["status"] == "open"  # unchanged


def test_unknown_ask_id_is_refused_not_crashed(tmp_db, fixed_clock):
    client = _Client()
    daemon.handle(tmp_db, {"update_id": 1, "callback_query": _cb("Q999", "trig:yes:Q999")},
                  client=client, clock=fixed_clock, owner_chat_id=555)
    assert client.answered  # acked, no crash
