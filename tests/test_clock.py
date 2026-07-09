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


from datetime import timedelta

from agentcy import clock, db


def d(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def _on(conn, at, planned_end=None):
    db.append_absence_event(conn, kind="on", at=db.to_iso(at), journal_ref=1,
                            planned_end=db.to_iso(planned_end) if planned_end else None)


def _off(conn, at):
    db.append_absence_event(conn, kind="off", at=db.to_iso(at), journal_ref=1)


def test_no_events_no_extension(tmp_db):
    assert clock.effective_deadline(tmp_db, d(15), start=d(8), as_of=d(10)) == d(15)
    assert clock.absence_windows(tmp_db, until=d(30)) == []
    assert not clock.is_paused(tmp_db, d(10))


def test_closed_window_extends_deadline(tmp_db):
    _on(tmp_db, d(9)); _off(tmp_db, d(11))
    assert clock.effective_deadline(tmp_db, d(15), start=d(8), as_of=d(12)) == d(17)


def test_open_ended_pause_freeze_grows_with_as_of(tmp_db):
    _on(tmp_db, d(9))                                    # 'until I resume' (D.6)
    assert clock.effective_deadline(tmp_db, d(15), start=d(8), as_of=d(10)) == d(16)
    assert clock.effective_deadline(tmp_db, d(15), start=d(8), as_of=d(12)) == d(18)
    assert clock.is_paused(tmp_db, d(11))


def test_planned_end_closes_window_without_off(tmp_db):
    _on(tmp_db, d(9), planned_end=d(11))
    assert clock.effective_deadline(tmp_db, d(15), start=d(8), as_of=d(13)) == d(17)
    assert not clock.is_paused(tmp_db, d(12))


def test_off_before_planned_end_wins(tmp_db):
    _on(tmp_db, d(9), planned_end=d(13)); _off(tmp_db, d(10))
    assert clock.effective_deadline(tmp_db, d(15), start=d(8), as_of=d(14)) == d(16)


def test_overlap_clipped_to_start_and_as_of(tmp_db):
    _on(tmp_db, d(5)); _off(tmp_db, d(9))
    # only the [d8, d9) day of the pause overlaps the counter's life
    assert clock.effective_deadline(tmp_db, d(15), start=d(8), as_of=d(12)) == d(16)


def test_effective_elapsed_subtracts_pause(tmp_db):
    _on(tmp_db, d(9)); _off(tmp_db, d(11))
    assert clock.effective_elapsed(tmp_db, d(8), d(12)) == timedelta(days=2)


def test_windows_from_on_off_stream(tmp_db):
    _on(tmp_db, d(2)); _off(tmp_db, d(4)); _on(tmp_db, d(6), planned_end=d(9))
    assert clock.absence_windows(tmp_db, until=d(20)) == [(d(2), d(4)), (d(6), d(9))]


def test_stray_off_and_duplicate_on_are_ignored(tmp_db):
    _off(tmp_db, d(1))                    # off with nothing open: no-op
    _on(tmp_db, d(2)); _on(tmp_db, d(3))  # duplicate on inside open window: no-op
    _off(tmp_db, d(5))
    assert clock.absence_windows(tmp_db, until=d(20)) == [(d(2), d(5))]
