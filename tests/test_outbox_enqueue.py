"""P6.1: tg/outbox.py enqueue side — dedupe/supersession semantics (tech-arch §5.4/§1.3)."""
import pytest

from agentcy import db


def test_key_builders():
    from agentcy.tg import outbox
    assert outbox.scheduled_key("daily", "2026-07-08", "letter") == "daily:2026-07-08:letter"
    assert outbox.scheduled_key("daily", "2026-07-08", "letter", attempt=2) == "daily:2026-07-08:letter#a2"
    assert outbox.event_key("MSFT", "2026-07-08T05:00:00Z", "report") == "event:MSFT:2026-07-08T05:00:00Z:report"
    assert outbox.alert_key(7) == "alert:7"


def test_enqueue_inserts_queued_row(tmp_db, fixed_clock):
    from agentcy.tg import outbox
    oid = outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter", kind="daily",
                         payload_html="<b>v1</b>", clock=fixed_clock)
    row = db.fetch_outbox_by_key(tmp_db, "daily:2026-07-08:letter")
    assert row["outbox_id"] == oid
    assert row["status"] == "queued" and row["attempts"] == 0
    assert row["payload_html"] == "<b>v1</b>"


def test_enqueue_supersedes_queued_row_in_place(tmp_db, fixed_clock):
    from agentcy.tg import outbox
    oid = outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter", kind="daily",
                         payload_html="<b>v1</b>", clock=fixed_clock)
    oid2 = outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter", kind="daily",
                          payload_html="<b>v2</b>", clock=fixed_clock)
    assert oid2 == oid                                   # same row, payload replaced (§5.4)
    assert db.fetch_outbox_by_key(tmp_db, "daily:2026-07-08:letter")["payload_html"] == "<b>v2</b>"
    assert len(db.fetch_outbox_queued(tmp_db)) == 1


def test_enqueue_after_sent_requires_attempt_qualified_key(tmp_db, fixed_clock):
    from agentcy.tg import outbox
    oid = outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter", kind="daily",
                         payload_html="x", clock=fixed_clock)
    db.update_outbox_state(tmp_db, oid, status="sent", tg_message_id=11)
    with pytest.raises(ValueError):
        outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter", kind="daily",
                       payload_html="y", clock=fixed_clock)
    # the attempt-qualified key is a fresh row:
    oid2 = outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter#a2", kind="daily",
                          payload_html="y", clock=fixed_clock)
    assert oid2 != oid
