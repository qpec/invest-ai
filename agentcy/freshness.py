"""Stamped values and check states (contracts §3.3). A value never sheds provenance (§7.6)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class DataState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"                  # never PASS/FIRE on this (invariant 6)
    BOOTSTRAPPING = "bootstrapping"  # MA-1: archive too short; carries evaluable_from


class CheckResult(StrEnum):
    PASS = "PASS"
    FIRE = "FIRE"
    STALE = "STALE"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True)
class Stamped(Generic[T]):
    """A value that never sheds provenance: every derived figure carries its inputs' fetched_at."""
    value: T
    fetched_at: datetime
    state: DataState = DataState.FRESH
    note: str | None = None

    def usable(self) -> bool:
        """True only when FRESH — stale/bootstrapping inputs suspend, never compute."""
        return self.state is DataState.FRESH
