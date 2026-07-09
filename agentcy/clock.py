"""Injected time + D.6 absence arithmetic (contracts §3.2). Pause = arithmetic, never mutation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from agentcy import db


class Clock(Protocol):
    def now(self) -> datetime:
        """Aware UTC now."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FixedClock:
    at: datetime

    def now(self) -> datetime:
        """Returns .at — the tests' injectable as_of."""
        return self.at


def absence_windows(conn, *, until: datetime) -> list[tuple[datetime, datetime | None]]:
    """Derive pause windows from the absence_event on/off stream (+planned_end).

    Window = [on.at, min(next off.at, planned_end)); open-ended supported; never mutates
    (§4.4/D.6 — a start/end row could never record /resume; the stream can)."""
    windows: list[tuple[datetime, datetime | None]] = []
    open_start: datetime | None = None
    open_planned: datetime | None = None
    for ev in db.fetch_absence_events(conn):
        at = db.from_iso(ev["at"])
        if at > until:
            break
        if ev["kind"] == "on":
            if open_start is not None:
                if open_planned is not None and open_planned <= at:
                    windows.append((open_start, open_planned))   # prior window lapsed
                    open_start = open_planned = None
                else:
                    continue                                     # duplicate 'on': ignored
            open_start = at
            open_planned = db.from_iso(ev["planned_end"]) if ev["planned_end"] else None
        else:  # 'off'
            if open_start is None:
                continue                                         # stray 'off': ignored
            end = at if open_planned is None else min(at, open_planned)
            if end > open_start:
                windows.append((open_start, end))
            open_start = open_planned = None
    if open_start is not None:
        windows.append((open_start, open_planned))               # None end = open-ended
    return windows


def _paused_overlap(conn, lo: datetime, hi: datetime) -> timedelta:
    total = timedelta(0)
    for ws, we in absence_windows(conn, until=hi):
        end = we if we is not None else hi
        s, e = max(ws, lo), min(end, hi)
        if e > s:
            total += e - s
    return total


def effective_deadline(conn, base: datetime, *, start: datetime,
                       as_of: datetime) -> datetime:
    """base extended by the overlap of absence windows with [start, as_of] —
    the ONE function every counter goes through (D.6)."""
    return base + _paused_overlap(conn, start, as_of)


def effective_elapsed(conn, start: datetime, end: datetime) -> timedelta:
    """Elapsed time minus paused overlap — skip counters, UNVERIFIABLE weeks, lapses."""
    return (end - start) - _paused_overlap(conn, start, end)


def is_paused(conn, at: datetime) -> bool:
    """True when a derived absence window covers `at`."""
    for ws, we in absence_windows(conn, until=at):
        if ws <= at and (we is None or at < we):
            return True
    return False
