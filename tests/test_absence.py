"""tests/test_absence.py — R3 shared pause/resume path (journal-FK first, then absence_event).

The daemon (P7) and CLI (P8) both call absence.pause/absence.resume so the on/off event
stream is written the same way in both. absence_event is append-only; windows are DERIVED at
read by clock.effective_deadline (P1.11) — resume appends an 'off' row, it never UPDATEs.
"""
from datetime import datetime, timedelta, timezone

from agentcy import absence, clock as clockmod, db
from agentcy.clock import FixedClock


def _at(y, mo, d, h=0):
    return datetime(y, mo, d, h, tzinfo=timezone.utc)


def test_pause_writes_journal_entry_then_absence_on_with_matching_ref(tmp_db):
    clock = FixedClock(_at(2026, 7, 9, 5))
    absence.pause(tmp_db, planned_end="2026-08-01T00:00:00Z",
                  reason="Owner travelling — freeze counters.", clock=clock)

    events = db.fetch_absence_events(tmp_db)
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "on"
    assert ev["at"] == "2026-07-09T05:00:00Z"
    assert ev["planned_end"] == "2026-08-01T00:00:00Z"

    # journal-FK first: exactly one config_or_designation entry, and the event points at it
    entry = db.fetch_journal_entry(tmp_db, ev["journal_ref"])
    assert entry is not None
    assert entry["decision_type"] == "config_or_designation"
    assert "freeze" in (entry["reasoning_at_the_moment"] or "").lower()


def test_pause_open_ended_when_planned_end_none(tmp_db):
    clock = FixedClock(_at(2026, 7, 9, 5))
    absence.pause(tmp_db, planned_end=None, reason="until I resume", clock=clock)
    ev = db.fetch_absence_events(tmp_db)[0]
    assert ev["kind"] == "on"
    assert ev["planned_end"] is None


def test_resume_writes_off_event_with_journal_ref(tmp_db):
    absence.pause(tmp_db, planned_end=None, reason="pause",
                  clock=FixedClock(_at(2026, 7, 9, 5)))
    absence.resume(tmp_db, reason="back at the desk",
                   clock=FixedClock(_at(2026, 7, 11, 5)))

    events = db.fetch_absence_events(tmp_db)
    assert [e["kind"] for e in events] == ["on", "off"]
    off = events[1]
    assert off["at"] == "2026-07-11T05:00:00Z"
    entry = db.fetch_journal_entry(tmp_db, off["journal_ref"])
    assert entry is not None and entry["decision_type"] == "config_or_designation"


def test_effective_deadline_freezes_then_unfreezes_over_the_stream(tmp_db):
    # A counter starts at 09:00 on the 9th with a base deadline 5 days out (the 14th 09:00).
    start = _at(2026, 7, 9, 9)
    base = start + timedelta(days=5)

    # Pause the whole of the 10th (24h), then resume.
    absence.pause(tmp_db, planned_end=None, reason="pause",
                  clock=FixedClock(_at(2026, 7, 10, 9)))

    # While paused, the effective deadline has slid out by the paused overlap so far.
    # effective_deadline (P1.11) reads the on/off stream absence.pause/resume produced.
    dl_mid = clockmod.effective_deadline(tmp_db, base, start=start, as_of=_at(2026, 7, 11, 9))
    assert dl_mid == base + timedelta(days=1)  # one full day counted while frozen

    absence.resume(tmp_db, reason="resume",
                   clock=FixedClock(_at(2026, 7, 11, 9)))

    # After resume the paused window is closed at 24h; further wall-clock does not extend it.
    dl_after = clockmod.effective_deadline(tmp_db, base, start=start, as_of=_at(2026, 7, 13, 9))
    assert dl_after == base + timedelta(days=1)


def test_resume_with_no_open_window_does_not_raise_and_records_decision(tmp_db):
    # No pause has ever been recorded — resume must still journal the decision, append an
    # 'off' event, and NOT error (idempotent per R3).
    absence.resume(tmp_db, reason="nothing to resume",
                   clock=FixedClock(_at(2026, 7, 9, 5)))
    events = db.fetch_absence_events(tmp_db)
    assert [e["kind"] for e in events] == ["off"]
    entry = db.fetch_journal_entry(tmp_db, events[0]["journal_ref"])
    assert entry is not None and entry["decision_type"] == "config_or_designation"
