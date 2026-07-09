"""Quarantined benchmark store (tech-arch §4.6; contracts §3.8).

The ONLY module that knows benchmark.db's path or applies its schema. The daily/
weekly/event code path can never reach this file (invariant 7 wall 2). Import-graph
contract: series_eur importable only from jobs.quarterly; backup_to/integrity_check
importable additionally from jobs.backup (data-free, return no rows)."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from agentcy import db

_SCHEMA = "benchmark_000_init.sql"


def _benchmark_path() -> Path:
    """<state_dir>/benchmark.db — resolved at call time, never at import (contracts §3.8)."""
    return db.state_dir() / "benchmark.db"


def _schema_path() -> Path:
    return Path(__file__).with_name("schema") / _SCHEMA


def _connect() -> sqlite3.Connection:
    """A direct connection to the SEPARATE benchmark.db file — never db.open_db (which opens
    agentcy.db and must never open this one). Same PRAGMAs as the main door."""
    conn = sqlite3.connect(_benchmark_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate() -> None:
    """Open/create benchmark.db and apply schema/benchmark_000_init.sql once (idempotent)."""
    _benchmark_path().parent.mkdir(parents=True, exist_ok=True)
    sql = _schema_path().read_text(encoding="utf-8")
    sha = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
        ).fetchone()
        applied = bool(row) and conn.execute(
            "SELECT 1 FROM schema_migration WHERE version=0"
        ).fetchone()
        if applied:
            return
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migration (version, applied_at, sha256) VALUES (0, ?, ?)",
            (_now_iso(), sha),
        )
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return db.to_iso(datetime.now(timezone.utc))


def append_bars(rows: Sequence[Mapping], *, run_id: int | None) -> int:
    """INSERT OR IGNORE per bar_date PK (append-only); the quarterly job's write path.
    Returns the number of NEW rows inserted."""
    conn = _connect()
    try:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO benchmark_series "
            "(bar_date, sp500tr_usd, usdeur, tr_eur, fetched_at, run_id) "
            "VALUES (:bar_date, :sp500tr_usd, :usdeur, :tr_eur, :fetched_at, :run_id)",
            [{**r, "run_id": run_id} for r in rows],
        )
        conn.commit()
        return conn.total_changes - before
    finally:
        conn.close()


def series_eur(start: str, end: str) -> pd.Series:
    """tr_eur indexed by bar_date within [start, end] — the quarantined read (jobs.quarterly ONLY)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT bar_date, tr_eur FROM benchmark_series "
            "WHERE bar_date >= ? AND bar_date <= ? ORDER BY bar_date",
            (start, end),
        ).fetchall()
    finally:
        conn.close()
    return pd.Series(
        [r["tr_eur"] for r in rows], index=[r["bar_date"] for r in rows], dtype=float
    )


def backup_to(dest: Path) -> None:
    """Data-free maintenance handle for jobs.backup: online Connection.backup(); returns no rows."""
    src = _connect()
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def integrity_check() -> bool:
    """Data-free PRAGMA integrity_check for jobs.backup; True on 'ok'."""
    conn = _connect()
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    return bool(result) and result[0] == "ok"
