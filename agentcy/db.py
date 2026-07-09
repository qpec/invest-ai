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


# --- append helpers (the ONLY write path; no generic execute() escapes this module) ---

def _insert(conn: sqlite3.Connection, table: str, values: Mapping) -> int:
    cols = ", ".join(values)
    ph = ", ".join("?" for _ in values)
    cur = conn.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({ph})',
                       tuple(values.values()))
    return cur.lastrowid


def _checked(row: Mapping, allowed: frozenset[str], table: str) -> dict:
    unknown = set(row) - allowed
    if unknown:
        raise ValueError(f"unknown {table} columns: {sorted(unknown)}")
    return dict(row)


def append_snapshot(conn, *, as_of: str, source: str, cash_balance_eur: float,
                    created_at: str) -> int:
    """Insert snapshot row; returns snapshot_id."""
    return _insert(conn, "snapshot", {"as_of": as_of, "source": source,
                                      "cash_balance_eur": cash_balance_eur,
                                      "created_at": created_at})


_POSITION_COLS = frozenset({"symbol", "yf_ticker", "instrument_type", "quantity",
                            "avg_open_price", "native_currency", "mv_native",
                            "mv_eur", "weight", "leverage"})

def append_positions(conn, snapshot_id: int, rows: Sequence[Mapping]) -> None:
    """Insert position rows for a snapshot (the only writer of avg_open_price)."""
    for row in rows:
        vals = _checked(row, _POSITION_COLS, "position")
        vals["snapshot_id"] = snapshot_id
        _insert(conn, "position", vals)


def append_designation(conn, *, symbol: str, framework_status: str,
                       valid_from: str, journal_ref: int) -> None:
    """Append designation row (latest wins, E.2)."""
    _insert(conn, "designation", {"symbol": symbol,
                                  "framework_status": framework_status,
                                  "valid_from": valid_from,
                                  "journal_ref": journal_ref})


def append_external_flow(conn, *, snapshot_id: int, date: str, amount_eur: float,
                         direction: str, ask_ref: str | None = None) -> int:
    """Append MA-12 flow row; returns flow_id."""
    return _insert(conn, "external_flow", {"snapshot_id": snapshot_id, "date": date,
                                           "amount_eur": amount_eur,
                                           "direction": direction, "ask_ref": ask_ref})


def append_symbol_map(conn, *, symbol: str, yf_ticker: str, valid_from: str,
                      journal_ref: int) -> None:
    """Append symbol->yfinance mapping (latest wins)."""
    _insert(conn, "symbol_map", {"symbol": symbol, "yf_ticker": yf_ticker,
                                 "valid_from": valid_from, "journal_ref": journal_ref})


_PRICE_COLS = frozenset({"yf_ticker", "bar_date", "close", "adj_close", "dividend",
                         "currency", "fetched_at", "run_id"})

def append_price_rows(conn, rows: Sequence[Mapping]) -> int:
    """Append price_cache bars (re-fetches append, never overwrite); returns count."""
    for row in rows:
        _insert(conn, "price_cache", _checked(row, _PRICE_COLS, "price_cache"))
    return len(rows)


def append_fundamentals_period(conn, *, yf_ticker: str, statement_type: str,
                               period_end: str, payload_json: str, fingerprint: str,
                               fetched_at: str, run_id: int | None) -> bool:
    """Append only on unseen (ticker,type,period,fingerprint); True if a new row was written."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO fundamentals_period"
        " (yf_ticker, statement_type, period_end, payload_json, fingerprint,"
        "  fetched_at, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (yf_ticker, statement_type, period_end, payload_json, fingerprint,
         fetched_at, run_id))
    return cur.rowcount == 1


_SHARES_COLS = frozenset({"yf_ticker", "obs_date", "shares", "fetched_at"})

def append_shares_rows(conn, rows: Sequence[Mapping]) -> int:
    """Append raw shares_series observations."""
    for row in rows:
        _insert(conn, "shares_series", _checked(row, _SHARES_COLS, "shares_series"))
    return len(rows)


def append_officer_snapshot(conn, *, yf_ticker: str, officers_json: str,
                            fingerprint: str, fetched_at: str) -> None:
    """Append officers snapshot (B.2 tripwire feed)."""
    _insert(conn, "officer_snapshot", {"yf_ticker": yf_ticker,
                                       "officers_json": officers_json,
                                       "fingerprint": fingerprint,
                                       "fetched_at": fetched_at})


def append_earnings_calendar(conn, *, yf_ticker: str, expected_date: str,
                             fetched_at: str, run_id: int | None) -> None:
    """Append calendar-estimate row (MA-7; preview only)."""
    _insert(conn, "earnings_calendar", {"yf_ticker": yf_ticker,
                                        "expected_date": expected_date,
                                        "fetched_at": fetched_at, "run_id": run_id})


def append_thesis(conn, *, thesis_id: str, ticker: str, origin: str,
                  created_at: str) -> None:
    """Insert immutable thesis identity."""
    _insert(conn, "thesis", {"thesis_id": thesis_id, "ticker": ticker,
                             "origin": origin, "created_at": created_at})


_THESIS_VERSION_COLS = frozenset({
    "thesis_id", "version", "business_model_2s", "moat_types_json", "moat_evidence",
    "owner_earnings_json", "owner_earnings_narrative", "anchor_metric",
    "value_at_purchase", "fair_band_low", "fair_band_high", "denominator_note",
    "conviction", "mgmt_trust", "mgmt_trust_note", "circle_fit", "circle_fit_note",
    "time_horizon", "ten_year_statement", "status_buy_flag", "status_buy_note",
    "diff_json", "reason", "actor", "journal_ref", "created_at"})   # fair_band_mid is generated

def append_thesis_version(conn, row: Mapping) -> None:
    """Insert thesis_version row (register.py validates BEFORE calling; journal_ref NOT NULL)."""
    _insert(conn, "thesis_version",
            _checked(row, _THESIS_VERSION_COLS, "thesis_version"))


def append_thesis_status(conn, *, thesis_id: str, status: str, changed_at: str,
                         cause: str, cause_ref: str | None = None,
                         review_deadline: str | None = None) -> int:
    """Append status-log row; returns log_id."""
    return _insert(conn, "thesis_status_log",
                   {"thesis_id": thesis_id, "status": status, "changed_at": changed_at,
                    "cause": cause, "cause_ref": cause_ref,
                    "review_deadline": review_deadline})


_TRIGGER_COLS = frozenset({"thesis_id", "introduced_version", "type", "statement",
                           "metric", "comparator", "threshold", "moat_link",
                           "persistence", "check_method", "data_source", "cadence",
                           "yes_means"})

def append_trigger(conn, row: Mapping) -> int:
    """Insert "trigger" definition row (keyword quoting hidden here); returns trigger_id."""
    return _insert(conn, "trigger", _checked(row, _TRIGGER_COLS, "trigger"))


_TRIGGER_CHECK_COLS = frozenset({"trigger_id", "run_id", "checked_at", "result",
                                 "observed_value", "headroom", "evaluable_from"})

def append_trigger_check(conn, row: Mapping) -> int:
    """Insert trigger_check result row; returns check_id."""
    return _insert(conn, "trigger_check",
                   _checked(row, _TRIGGER_CHECK_COLS, "trigger_check"))


_JOURNAL_ENTRY_COLS = frozenset({
    "ts", "decision_type", "decision_subtype", "ticker", "thesis_ref",
    "system_recommendation", "owner_action", "reasoning_at_the_moment",
    "expectation_and_falsifier", "review_horizon", "inputs_ref", "process",
    "process_deviation_note", "emotional_note", "ask_ref", "actor"})

def append_journal_entry(conn, row: Mapping) -> int:
    """Insert F.1 entry (journal.py validates BEFORE calling); returns entry_id."""
    return _insert(conn, "journal_entry",
                   _checked(row, _JOURNAL_ENTRY_COLS, "journal_entry"))


def append_journal_grade(conn, *, entry_id: int, graded_at: str, outcome_grade: str,
                         note: str | None = None) -> None:
    """Append grade row — grading never mutates the entry."""
    _insert(conn, "journal_grade", {"entry_id": entry_id, "graded_at": graded_at,
                                    "outcome_grade": outcome_grade, "note": note})


_REPORT_COLS = frozenset({"run_id", "type", "generated_at", "period",
                          "freshness_json", "content_md", "archive_path", "git_sha"})

def append_report(conn, row: Mapping) -> int:
    """Insert report archive row (git_sha nullable, write-once); returns report_id."""
    return _insert(conn, "report", _checked(row, _REPORT_COLS, "report"))


def append_config(conn, *, key: str, value: str, valid_from: str,
                  journal_ref: int) -> None:
    """Append config row — FK makes an unjournaled change impossible (§9)."""
    _insert(conn, "config", {"key": key, "value": value, "valid_from": valid_from,
                             "journal_ref": journal_ref})


def append_absence_event(conn, *, kind: str, at: str, journal_ref: int,
                         planned_end: str | None = None) -> int:
    """Append pause on/off event (D.6); returns event_id."""
    return _insert(conn, "absence_event", {"kind": kind, "at": at,
                                           "journal_ref": journal_ref,
                                           "planned_end": planned_end})


def append_study_note(conn, *, ts: str, kind: str, text: str,
                      ask_ref: str | None = None) -> int:
    """Append F.3 free-text note; returns note_id."""
    return _insert(conn, "study_note", {"ts": ts, "kind": kind, "text": text,
                                        "ask_ref": ask_ref})


_EVENT_COLS = frozenset({"yf_ticker", "source", "kind", "note", "detected_at",
                         "detected_late", "run_id"})

def append_event(conn, row: Mapping) -> int:
    """Insert event identity row (D.3); returns event_id."""
    return _insert(conn, "event", _checked(row, _EVENT_COLS, "event"))
