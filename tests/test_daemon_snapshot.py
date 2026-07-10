"""P7.12: /snapshot document reception is state-scoped to snap:mode:file (§1.5)."""
from __future__ import annotations

from agentcy import db
from agentcy.tg import daemon


class _Client:
    def __init__(self, csv_bytes=b"Symbol,Units\nMSFT,40\n"):
        self.sent = []
        self.actions = []
        self._csv = csv_bytes
        self.got_file = []
        self.downloaded = []
    def send_message(self, chat_id, html, *, reply_markup=None):
        self.sent.append((html, reply_markup)); return {"message_id": 1}
    def send_chat_action(self, chat_id, action="typing"):
        self.actions.append(action)
    def get_file(self, file_id):
        self.got_file.append(file_id); return {"file_path": "documents/export.csv"}
    def download_file(self, file_path):
        self.downloaded.append(file_path); return self._csv
    def answer_callback_query(self, *a, **k): pass
    def edit_message_text(self, *a, **k): return {"message_id": 1}


def _doc_update(owner=555):
    return {"update_id": 1, "message": {"chat": {"id": owner},
            "document": {"file_id": "FID1", "file_name": "export.csv"}}}


def _tap_file_mode(owner=555):
    return {"update_id": 1, "callback_query": {"id": "CB", "from": {"id": owner},
            "message": {"chat": {"id": owner}, "message_id": 5}, "data": "snap:mode:file"}}


def test_cold_document_is_redirected_not_ingested(tmp_db, fixed_clock, monkeypatch):
    ingested = []
    monkeypatch.setattr("agentcy.mirror.ingest_snapshot",
                        lambda *a, **k: ingested.append(1) or (1, []))
    c = _Client()
    daemon.handle(tmp_db, _doc_update(), client=c, clock=fixed_clock, owner_chat_id=555)
    assert ingested == []  # a stray file must not become portfolio truth
    assert "/snapshot" in c.sent[-1][0]


def test_file_mode_then_document_ingests(tmp_db, fixed_clock, monkeypatch):
    # parse_etoro_csv returns a single SnapshotIn (here a sentinel) that flows into ingest.
    monkeypatch.setattr("agentcy.mirror.parse_etoro_csv", lambda text: "SNAP")
    calls = []
    monkeypatch.setattr("agentcy.mirror.ingest_snapshot",
                        lambda conn, snap, *, clock: calls.append(snap) or (7, []))
    c = _Client()
    # 1) owner taps "Upload export file" -> pending snap:file N-ask minted
    daemon.handle(tmp_db, _tap_file_mode(), client=c, clock=fixed_clock, owner_chat_id=555)
    open_n = [a for a in db.fetch_open_asks(tmp_db, kind="N")]
    assert any('snap:file' in (a["options_json"] or "") for a in open_n)
    # 2) owner sends the document -> getFile/download/parse/ingest
    daemon.handle(tmp_db, _doc_update(), client=c, clock=fixed_clock, owner_chat_id=555)
    assert c.got_file == ["FID1"] and c.downloaded == ["documents/export.csv"]
    assert calls == ["SNAP"]
    assert "typing" in c.actions  # sendChatAction before the parse (§5.5)
    # pending snap:file ask cleared
    remaining = [a for a in db.fetch_open_asks(tmp_db, kind="N")
                 if "snap:file" in (a["options_json"] or "")]
    assert remaining == []
