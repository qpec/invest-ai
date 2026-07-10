"""P7.8: owner-lock — non-owner updates are dropped with zero effect (tech-arch §5.3, tg-spec §5.1)."""
from __future__ import annotations

from agentcy.tg import daemon


class _RecordingClient:
    def __init__(self):
        self.sent = []
        self.answered = []
    def send_message(self, chat_id, html, *, reply_markup=None):
        self.sent.append((chat_id, html)); return {"message_id": 1}
    def answer_callback_query(self, cbq_id, *, text=None):
        self.answered.append((cbq_id, text))
    def send_chat_action(self, chat_id, action="typing"):
        pass


def test_non_owner_message_is_dropped_silently(tmp_db, fixed_clock):
    client = _RecordingClient()
    update = {"update_id": 1, "message": {"chat": {"id": 4040}, "text": "/status"}}
    daemon.handle(tmp_db, update, client=client, clock=fixed_clock, owner_chat_id=555)
    assert client.sent == []  # no reply confirms the bot exists to a stranger


def test_non_owner_callback_is_dropped_silently(tmp_db, fixed_clock):
    client = _RecordingClient()
    update = {"update_id": 2,
              "callback_query": {"id": "CB1", "from": {"id": 4040},
                                 "message": {"chat": {"id": 4040}},
                                 "data": "alert:confirm:A1"}}
    daemon.handle(tmp_db, update, client=client, clock=fixed_clock, owner_chat_id=555)
    assert client.answered == [] and client.sent == []


def test_owner_message_is_processed(tmp_db, fixed_clock):
    client = _RecordingClient()
    update = {"update_id": 3, "message": {"chat": {"id": 555}, "text": "/help"}}
    daemon.handle(tmp_db, update, client=client, clock=fixed_clock, owner_chat_id=555)
    assert client.sent and "advise" in client.sent[0][1].lower()  # /help leaf replied
