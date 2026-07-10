"""P7.2: TelegramClient core methods against the in-process fake."""
from __future__ import annotations

import pytest

from agentcy.tg.client import TelegramClient
from tests.tgfake import FakeTelegram, allow_loopback


@pytest.fixture()
def fake():
    f = FakeTelegram()
    yield f
    f.close()


@pytest.fixture()
def client(fake, monkeypatch):
    # The no-network guard blocks socket.connect / create_connection; re-permit
    # loopback ONLY so the in-process fake (127.0.0.1) is reachable while any real
    # off-box network stays blocked (§13).
    allow_loopback(monkeypatch)
    return TelegramClient("TESTTOKEN", base_url=fake.base_url, timeout=2.0)


def test_get_updates_sends_offset_limit_timeout_and_returns_result_list(fake, client):
    fake.responses["getUpdates"] = {"ok": True, "result": [{"update_id": 7}, {"update_id": 8}]}
    out = client.get_updates(offset=5, timeout=25, limit=25)
    assert [u["update_id"] for u in out] == [7, 8]
    method, body, _ = fake.calls("getUpdates")[0]
    assert body["offset"] == 5 and body["limit"] == 25 and body["timeout"] == 25


def test_send_message_posts_html_parse_mode_and_returns_message_object(fake, client):
    fake.responses["sendMessage"] = {"ok": True, "result": {"message_id": 42}}
    msg = client.send_message(999, "<b>hi</b>")
    assert msg["message_id"] == 42
    _, body, _ = fake.calls("sendMessage")[0]
    assert body["chat_id"] == 999
    assert body["parse_mode"] == "HTML"
    assert body["text"] == "<b>hi</b>"


def test_send_message_includes_reply_markup_when_given(fake, client):
    fake.responses["sendMessage"] = {"ok": True, "result": {"message_id": 1}}
    client.send_message(1, "x", reply_markup={"inline_keyboard": [[{"text": "A", "callback_data": "a:b:C1"}]]})
    _, body, _ = fake.calls("sendMessage")[0]
    assert body["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "a:b:C1"


def test_unknown_json_fields_are_ignored(fake, client):
    fake.responses["sendMessage"] = {
        "ok": True, "result": {"message_id": 3, "some_future_field": 1}, "extra_top": "x"}
    msg = client.send_message(1, "x")
    assert msg["message_id"] == 3  # extra fields do not break parsing


def test_ok_false_raises_telegram_error(fake, client):
    fake.responses["sendMessage"] = {"ok": False, "description": "Bad Request: chat not found"}
    from agentcy.tg.client import TelegramError
    with pytest.raises(TelegramError):
        client.send_message(1, "x")
