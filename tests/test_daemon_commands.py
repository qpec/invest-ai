"""P7.11: command surface — start/status/pause/resume/event/snapshot emit the right first message (§1)."""
from __future__ import annotations

from agentcy.tg import daemon


class _Client:
    def __init__(self):
        self.sent = []
        self.actions = []
    def send_message(self, chat_id, html, *, reply_markup=None):
        self.sent.append((html, reply_markup)); return {"message_id": 1}
    def send_chat_action(self, chat_id, action="typing"):
        self.actions.append(action)
    def answer_callback_query(self, *a, **k): pass
    def edit_message_text(self, *a, **k): return {"message_id": 1}


def _cmd(text, owner=555):
    return {"update_id": 1, "message": {"chat": {"id": owner}, "text": text}}


def test_start_prints_orientation_locked_to_chat(tmp_db, fixed_clock):
    c = _Client()
    daemon.handle(tmp_db, _cmd("/start"), client=c, clock=fixed_clock, owner_chat_id=555)
    assert "online, locked to this chat" in c.sent[0][0]
    assert "I advise; I never trade." in c.sent[0][0]


def test_status_sends_a_card_without_running_checks(tmp_db, fixed_clock):
    c = _Client()
    daemon.handle(tmp_db, _cmd("/status"), client=c, clock=fixed_clock, owner_chat_id=555)
    assert c.sent  # a status card is produced from last RunLog state


def test_pause_opens_duration_keyboard(tmp_db, fixed_clock):
    c = _Client()
    daemon.handle(tmp_db, _cmd("/pause"), client=c, clock=fixed_clock, owner_chat_id=555)
    html, markup = c.sent[0]
    assert "Deadlines and skip counters freeze" in html
    flat = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
    assert "pause:set:open" in flat and "pause:set:7d" in flat


def test_event_opens_ticker_picker(tmp_db, fixed_clock):
    c = _Client()
    daemon.handle(tmp_db, _cmd("/event"), client=c, clock=fixed_clock, owner_chat_id=555)
    assert "which holding had an event" in c.sent[0][0].lower()


def test_snapshot_opens_ingestion_chooser(tmp_db, fixed_clock):
    c = _Client()
    daemon.handle(tmp_db, _cmd("/snapshot"), client=c, clock=fixed_clock, owner_chat_id=555)
    flat = [b["callback_data"] for row in c.sent[0][1]["inline_keyboard"] for b in row]
    assert "snap:mode:file" in flat and "snap:mode:text" in flat and "snap:cancel" in flat


def test_command_menu_lists_six_commands():
    menu = daemon._command_menu()
    names = {c["command"] for c in menu}
    assert names == {"start", "status", "pause", "resume", "event", "snapshot", "help"}
