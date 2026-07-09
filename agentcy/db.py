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


_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")   # benchmark_000_init.sql deliberately excluded


def open_db(dir: Path | None = None) -> sqlite3.Connection:
    """Open <state_dir>/agentcy.db with WAL, busy_timeout=30000, foreign_keys=ON, row_factory=Row.

    NEVER opens benchmark.db (invariant 7 wall 1)."""
    base = Path(dir) if dir is not None else state_dir()
    base.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(base / "agentcy.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection, schema_dir: Path | None = None) -> list[int]:
    """Apply pending schema/NNN_*.sql forward-only.

    PRAGMA user_version == number of applied migrations (fresh DB: 0 -> apply 000 -> 1).
    Each applied file is recorded in schema_migration (version, applied_at, sha256)."""
    sd = Path(schema_dir) if schema_dir is not None else Path(__file__).parent / "schema"
    files: dict[int, Path] = {}
    for path in sorted(sd.iterdir()):
        m = _MIGRATION_RE.match(path.name)
        if not m:
            continue
        version = int(m.group(1))
        if version in files:
            raise RuntimeError(f"duplicate migration version {version:03d}")
        files[version] = path
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    applied: list[int] = []
    for version in sorted(files):
        if version < current:
            continue
        if version > current:
            raise RuntimeError(
                f"migration gap: expected {current:03d}, found {version:03d}")
        sql = files[version].read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migration (version, applied_at, sha256) VALUES (?, ?, ?)",
            (version, to_iso(datetime.now(timezone.utc)),
             hashlib.sha256(sql.encode("utf-8")).hexdigest()),
        )
        conn.execute(f"PRAGMA user_version = {version + 1}")
        conn.commit()
        applied.append(version)
        current = version + 1
    return applied
