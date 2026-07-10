"""P7.5-7.7: outbox drain half (tech-arch §5.4/§5.3/§1.3)."""
from __future__ import annotations

from datetime import timedelta

from agentcy.tg import outbox


def test_next_backoff_ladder():
    assert outbox.next_backoff(0) == timedelta(seconds=30)
    assert outbox.next_backoff(1) == timedelta(minutes=2)
    assert outbox.next_backoff(2) == timedelta(minutes=10)
    assert outbox.next_backoff(3) == timedelta(minutes=30)
    assert outbox.next_backoff(4) == timedelta(hours=1)
    assert outbox.next_backoff(9) == timedelta(hours=1)  # then hourly, clamped


def test_collapse_marks_all_but_newest_daily_letter(tmp_db, fixed_clock):
    from agentcy import db
    base = fixed_clock.now()
    ids = []
    for i in range(3):
        oid = outbox.enqueue(
            tmp_db, dedupe_key=f"daily:2026-07-0{i+6}:letter", kind="daily",
            payload_html=f"letter {i}", clock=_ClockAt(base + timedelta(days=i)))
        ids.append(oid)
    n = outbox.collapse_stale_letters(tmp_db, as_of=base + timedelta(days=5))
    assert n == 2
    rows = {r["outbox_id"]: r["status"] for r in db.fetch_outbox_queued(tmp_db)}
    # only the newest (ids[2]) remains queued; the two older are collapsed (not queued)
    assert ids[2] in rows and rows[ids[2]] == "queued"
    assert ids[0] not in rows and ids[1] not in rows


def test_collapse_never_touches_non_daily(tmp_db, fixed_clock):
    from agentcy import db
    outbox.enqueue(tmp_db, dedupe_key="alert:1", kind="alert", payload_html="a", clock=fixed_clock)
    outbox.enqueue(tmp_db, dedupe_key="weekly:2026-07-11:headline", kind="weekly_msg",
                   payload_html="w", clock=fixed_clock)
    assert outbox.collapse_stale_letters(tmp_db, as_of=fixed_clock.now()) == 0
    assert len(db.fetch_outbox_queued(tmp_db)) == 2


class _ClockAt:
    def __init__(self, at):
        self.at = at
    def now(self):
        return self.at


class _StubClient:
    def __init__(self):
        self.sent = []
        self.docs = []
        self.fail_next = None  # exception instance to raise once
    def send_message(self, chat_id, html, *, reply_markup=None):
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc
        self.sent.append((chat_id, html, reply_markup))
        return {"message_id": 100 + len(self.sent)}
    def send_document(self, chat_id, filename, content, *, caption=None):
        self.docs.append((chat_id, filename, caption))
        return {"message_id": 900 + len(self.docs)}


def _drain(tmp_db, client, clock, chat_id=555):
    return outbox.drain(tmp_db, client, clock=clock, chat_id=chat_id, sleep=lambda _s: None)


def test_drain_sends_queued_and_marks_sent_with_message_id(tmp_db, fixed_clock):
    from agentcy import db
    oid = outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter", kind="daily",
                         payload_html="hello", clock=fixed_clock)
    client = _StubClient()
    _drain(tmp_db, client, fixed_clock)
    assert client.sent and client.sent[0][1] == "hello"
    row = db.fetch_outbox_by_key(tmp_db, "daily:2026-07-08:letter")
    assert row["status"] == "sent" and row["tg_message_id"] == 101


def test_drain_alerts_go_first_on_flush(tmp_db, fixed_clock):
    # daily enqueued earlier than the alert; alert must still deliver first.
    outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter", kind="daily",
                   payload_html="LETTER", clock=fixed_clock)
    outbox.enqueue(tmp_db, dedupe_key="alert:9", kind="alert",
                   payload_html="ALERT", clock=fixed_clock)
    client = _StubClient()
    _drain(tmp_db, client, fixed_clock)
    assert client.sent[0][1] == "ALERT"


def test_drain_retry_after_defers_without_marking_sent(tmp_db, fixed_clock):
    from agentcy import db
    from agentcy.tg.client import TelegramRetryAfter
    outbox.enqueue(tmp_db, dedupe_key="alert:1", kind="alert", payload_html="A", clock=fixed_clock)
    client = _StubClient(); client.fail_next = TelegramRetryAfter(12)
    out = _drain(tmp_db, client, fixed_clock)
    row = db.fetch_outbox_by_key(tmp_db, "alert:1")
    assert row["status"] == "queued"          # never lost
    assert row["next_attempt_at"] is not None  # deferred
    assert out["retry_after"] == 12.0


def test_drain_error_applies_backoff_and_keeps_alert_queued(tmp_db, fixed_clock):
    from agentcy import db
    from agentcy.tg.client import TelegramError
    outbox.enqueue(tmp_db, dedupe_key="alert:2", kind="alert", payload_html="A", clock=fixed_clock)
    client = _StubClient(); client.fail_next = TelegramError("boom")
    _drain(tmp_db, client, fixed_clock)
    row = db.fetch_outbox_by_key(tmp_db, "alert:2")
    assert row["status"] == "queued" and row["attempts"] == 1


def test_drain_skips_rows_not_yet_due(tmp_db, fixed_clock):
    from agentcy import db
    oid = outbox.enqueue(tmp_db, dedupe_key="alert:3", kind="alert", payload_html="A", clock=fixed_clock)
    future = db.to_iso(fixed_clock.now() + timedelta(minutes=5))
    db.update_outbox_state(tmp_db, oid, next_attempt_at=future)
    client = _StubClient()
    _drain(tmp_db, client, fixed_clock)
    assert client.sent == []  # not yet due


def test_drain_sends_document_rows(tmp_db, fixed_clock, tmp_path):
    doc = tmp_path / "weekly-review-2026-07-11.md"
    doc.write_text("# weekly\n", encoding="utf-8")
    outbox.enqueue(tmp_db, dedupe_key="weekly:2026-07-11:doc", kind="weekly_doc",
                   payload_html="Weekly review attached", document_path=str(doc), clock=fixed_clock)
    client = _StubClient()
    _drain(tmp_db, client, fixed_clock)
    assert client.docs and client.docs[0][1] == "weekly-review-2026-07-11.md"
