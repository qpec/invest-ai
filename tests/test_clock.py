"""Clock primitives: injected time (contracts §3.2)."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from agentcy.clock import Clock, FixedClock, SystemClock


def test_fixed_clock_returns_pinned_instant(fixed_clock):
    assert fixed_clock.now() == datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def test_fixed_clock_is_frozen():
    c = FixedClock(datetime(2026, 7, 8, tzinfo=timezone.utc))
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.at = datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_system_clock_is_aware_utc():
    now = SystemClock().now()
    assert now.tzinfo is timezone.utc


def test_both_satisfy_protocol():
    def takes_clock(c: Clock) -> datetime:
        return c.now()
    assert takes_clock(SystemClock()).tzinfo is timezone.utc
    assert takes_clock(FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))).year == 2026
