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


def test_edit_message_text_posts_message_id(fake, client):
    fake.responses["editMessageText"] = {"ok": True, "result": {"message_id": 42}}
    client.edit_message_text(5, 42, "<i>recorded</i>", reply_markup=None)
    _, body, _ = fake.calls("editMessageText")[0]
    assert body["chat_id"] == 5 and body["message_id"] == 42
    assert body["parse_mode"] == "HTML" and body["text"] == "<i>recorded</i>"


def test_answer_callback_query_sends_id_and_text(fake, client):
    fake.responses["answerCallbackQuery"] = {"ok": True, "result": True}
    client.answer_callback_query("CBQ1", text="Already recorded")
    _, body, _ = fake.calls("answerCallbackQuery")[0]
    assert body["callback_query_id"] == "CBQ1" and body["text"] == "Already recorded"


def test_send_chat_action_defaults_to_typing(fake, client):
    fake.responses["sendChatAction"] = {"ok": True, "result": True}
    client.send_chat_action(7)
    _, body, _ = fake.calls("sendChatAction")[0]
    assert body["chat_id"] == 7 and body["action"] == "typing"


def test_set_my_commands_posts_command_list(fake, client):
    fake.responses["setMyCommands"] = {"ok": True, "result": True}
    cmds = [{"command": "status", "description": "current calm state"}]
    client.set_my_commands(cmds)
    _, body, _ = fake.calls("setMyCommands")[0]
    assert body["commands"][0]["command"] == "status"


def test_429_raises_retry_after(fake, client):
    from agentcy.tg.client import TelegramRetryAfter
    fake.responses["sendMessage"] = {
        "ok": False, "error_code": 429, "description": "Too Many Requests",
        "parameters": {"retry_after": 7}}
    with pytest.raises(TelegramRetryAfter) as ei:
        client.send_message(1, "x")
    assert ei.value.retry_after == 7.0


def test_send_document_builds_multipart_with_file_and_caption(fake, client):
    fake.responses["sendDocument"] = {"ok": True, "result": {"message_id": 88}}
    msg = client.send_document(3, "weekly-review-2026-07-11.md", b"# heading\nbody\n",
                               caption="Weekly review")
    assert msg["message_id"] == 88
    method, raw, headers = fake.calls("sendDocument")[0]
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=")
    body = raw if isinstance(raw, (bytes, bytearray)) else raw.encode()
    assert b'name="chat_id"' in body and b"3" in body
    assert b'name="caption"' in body and b"Weekly review" in body
    assert b'name="document"; filename="weekly-review-2026-07-11.md"' in body
    assert b"# heading" in body


def test_get_file_returns_file_path(fake, client):
    fake.responses["getFile"] = {"ok": True, "result": {"file_id": "F1", "file_path": "documents/x.csv"}}
    info = client.get_file("F1")
    assert info["file_path"] == "documents/x.csv"


def test_download_file_gets_raw_bytes(fake, client):
    fake.files["documents/x.csv"] = b"Symbol,Units\nMSFT,40\n"
    data = client.download_file("documents/x.csv")
    assert data == b"Symbol,Units\nMSFT,40\n"
