"""THE sqlite door for agentcy.db (contracts §3.1). Never opens benchmark.db."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

Row = sqlite3.Row


def state_dir() -> Path:
    """AGENTCY_STATE_DIR env or /var/lib/stock-agentcy — resolved at call time, never at import."""
    return Path(os.environ.get("AGENTCY_STATE_DIR", "/var/lib/stock-agentcy"))


def to_iso(dt: datetime) -> str:
    """Aware datetime -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC)."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime: all DB timestamps are aware UTC")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(s: str) -> datetime:
    """ISO-8601 Z string -> aware UTC datetime."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
