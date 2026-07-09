"""shared pause/resume path for daemon + CLI: journal-FK then append_absence_event (R3, §6). Lands in P3.

The daemon (P7 `/pause`,`/resume`) and the CLI (P8 `_cmd_absence`) both call these so the
on/off event stream is written the SAME way in both. `absence_event` is append-only: pause
appends an 'on' row, resume appends an 'off' row — windows are DERIVED at read by
`clock.effective_deadline` (P1.11). Resume is idempotent: with no open window it still records
the decision and appends 'off', it never errors and never UPDATEs history (D.6, §4.4)."""
from __future__ import annotations

from agentcy import db, journal
from agentcy.clock import Clock
from agentcy.journal import EntryIn


def _journal_ref(conn, *, reason: str, clock: Clock) -> int:
    """Journal-FK first: append a config_or_designation entry recording the change; return its id."""
    return journal.append(conn, EntryIn(
        decision_type="config_or_designation",
        decision_subtype="config_change",
        reasoning_at_the_moment=reason,
        actor="owner",
    ), clock=clock)


def pause(conn, *, planned_end: str | None, reason: str, clock: Clock) -> None:
    """Journal-FK first (config_or_designation recording `reason`), THEN append_absence_event('on').

    `planned_end` (ISO, owner-supplied) may be None for an open-ended pause ('until I resume')."""
    ref = _journal_ref(conn, reason=reason, clock=clock)
    db.append_absence_event(conn, kind="on", at=db.to_iso(clock.now()),
                            journal_ref=ref, planned_end=planned_end)


def resume(conn, *, reason: str, clock: Clock) -> None:
    """Journal-FK first, THEN append_absence_event('off').

    Idempotent: with no absence window currently open it still records the resume decision and
    appends the 'off' event — a stray 'off' is ignored by clock.absence_windows — never errors."""
    ref = _journal_ref(conn, reason=reason, clock=clock)
    db.append_absence_event(conn, kind="off", at=db.to_iso(clock.now()), journal_ref=ref)
