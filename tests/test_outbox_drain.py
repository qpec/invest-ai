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
