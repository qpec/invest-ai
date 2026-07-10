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
