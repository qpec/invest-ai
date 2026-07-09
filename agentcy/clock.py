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
