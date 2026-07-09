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


# --- fetch helpers (named reads only) ---

def _now_iso() -> str:
    return to_iso(datetime.now(timezone.utc))


def fetch_config_current(conn, *, as_of: str | None = None) -> dict[str, str]:
    """Latest value per key at as_of (default: now)."""
    ts = as_of if as_of is not None else _now_iso()
    rows = conn.execute(
        "SELECT key, value FROM config c"
        " WHERE valid_from <= ?"
        "   AND valid_from = (SELECT MAX(valid_from) FROM config c2"
        "                     WHERE c2.key = c.key AND c2.valid_from <= ?)",
        (ts, ts)).fetchall()
    return {r["key"]: r["value"] for r in rows}


def fetch_latest_designations(conn) -> dict[str, Row]:
    """Latest designation row per symbol (E.2 latest-wins)."""
    rows = conn.execute(
        "SELECT * FROM designation d"
        " WHERE valid_from = (SELECT MAX(valid_from) FROM designation d2"
        "                     WHERE d2.symbol = d.symbol)").fetchall()
    return {r["symbol"]: r for r in rows}


def fetch_v_price(conn, yf_ticker: str, *, start: str | None = None,
                  end: str | None = None) -> list[Row]:
    """Rows from v_price (latest fetch per bar), ascending bar_date."""
    sql = "SELECT * FROM v_price WHERE yf_ticker = ?"
    params: list = [yf_ticker]
    if start is not None:
        sql += " AND bar_date >= ?"
        params.append(start)
    if end is not None:
        sql += " AND bar_date <= ?"
        params.append(end)
    return conn.execute(sql + " ORDER BY bar_date", params).fetchall()


def fetch_statement_periods(conn, yf_ticker: str, statement_type: str) -> list[Row]:
    """Accumulated archive, latest fingerprint per period_end, ascending."""
    return conn.execute(
        "SELECT * FROM ("
        "  SELECT f.*, ROW_NUMBER() OVER (PARTITION BY period_end"
        "         ORDER BY fetched_at DESC, rowid DESC) AS rn"
        "  FROM fundamentals_period f"
        "  WHERE yf_ticker = ? AND statement_type = ?)"
        " WHERE rn = 1 ORDER BY period_end",
        (yf_ticker, statement_type)).fetchall()


def fetch_latest_snapshot(conn) -> Row | None:
    """Newest snapshot row by as_of."""
    return conn.execute(
        "SELECT * FROM snapshot ORDER BY as_of DESC, snapshot_id DESC LIMIT 1"
    ).fetchone()


def fetch_positions_advice(conn, snapshot_id: int) -> list[Row]:
    """SELECT from positions_advice view ONLY (invariant 4)."""
    return conn.execute(
        "SELECT * FROM positions_advice WHERE snapshot_id=? ORDER BY symbol",
        (snapshot_id,)).fetchall()


def fetch_positions_records(conn, snapshot_id: int) -> list[Row]:
    """Raw position rows incl. avg_open_price (AST-enforced caller restrictions, P5)."""
    return conn.execute(
        "SELECT * FROM position WHERE snapshot_id=? ORDER BY symbol",
        (snapshot_id,)).fetchall()


def fetch_current_symbol_map(conn) -> dict[str, str]:
    """Latest yf_ticker per symbol (latest-wins)."""
    rows = conn.execute(
        "SELECT * FROM symbol_map s"
        " WHERE valid_from = (SELECT MAX(valid_from) FROM symbol_map s2"
        "                     WHERE s2.symbol = s.symbol)").fetchall()
    return {r["symbol"]: r["yf_ticker"] for r in rows}


def fetch_shares_raw(conn, yf_ticker: str) -> list[Row]:
    """Raw shares rows (store.py dedups last-per-date at read)."""
    return conn.execute(
        "SELECT * FROM shares_series WHERE yf_ticker=?"
        " ORDER BY obs_date, fetched_at, rowid", (yf_ticker,)).fetchall()


def fetch_latest_officers(conn, yf_ticker: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM officer_snapshot WHERE yf_ticker=?"
        " ORDER BY fetched_at DESC, rowid DESC LIMIT 1", (yf_ticker,)).fetchone()


def fetch_earnings_calendar(conn, yf_ticker: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM earnings_calendar WHERE yf_ticker=?"
        " ORDER BY fetched_at DESC, rowid DESC LIMIT 1", (yf_ticker,)).fetchone()


def fetch_thesis(conn, thesis_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM thesis WHERE thesis_id=?", (thesis_id,)).fetchone()


def fetch_current_thesis_version(conn, thesis_id: str) -> Row | None:
    """Row with version = max(version)."""
    return conn.execute(
        "SELECT * FROM thesis_version WHERE thesis_id=?"
        " ORDER BY version DESC LIMIT 1", (thesis_id,)).fetchone()


def fetch_current_thesis_status(conn, thesis_id: str) -> Row | None:
    """Latest thesis_status_log row."""
    return conn.execute(
        "SELECT * FROM thesis_status_log WHERE thesis_id=?"
        " ORDER BY changed_at DESC, log_id DESC LIMIT 1", (thesis_id,)).fetchone()


def fetch_armed_triggers(conn, thesis_id: str | None = None) -> list[Row]:
    """"trigger" rows with retired_at IS NULL, optionally per thesis."""
    sql = 'SELECT * FROM "trigger" WHERE retired_at IS NULL'
    params: list = []
    if thesis_id is not None:
        sql += " AND thesis_id=?"
        params.append(thesis_id)
    return conn.execute(sql + " ORDER BY trigger_id", params).fetchall()


def fetch_latest_trigger_check(conn, trigger_id: int) -> Row | None:
    """Current trigger state = latest trigger_check (§4.4)."""
    return conn.execute(
        "SELECT * FROM trigger_check WHERE trigger_id=?"
        " ORDER BY checked_at DESC, check_id DESC LIMIT 1", (trigger_id,)).fetchone()


def fetch_trigger_checks_since(conn, trigger_id: int, since: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM trigger_check WHERE trigger_id=? AND checked_at>=?"
        " ORDER BY checked_at, check_id", (trigger_id, since)).fetchall()


def fetch_journal_entry(conn, entry_id: int) -> Row | None:
    return conn.execute(
        "SELECT * FROM journal_entry WHERE entry_id=?", (entry_id,)).fetchone()


def fetch_journal_entries(conn, *, decision_type: str | None = None,
                          since: str | None = None) -> list[Row]:
    clauses: list[str] = []
    params: list = []
    if decision_type is not None:
        clauses.append("decision_type=?")
        params.append(decision_type)
    if since is not None:
        clauses.append("ts>=?")
        params.append(since)
    sql = "SELECT * FROM journal_entry"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return conn.execute(sql + " ORDER BY ts, entry_id", params).fetchall()


def fetch_grades_for(conn, entry_id: int) -> list[Row]:
    return conn.execute(
        "SELECT * FROM journal_grade WHERE entry_id=?"
        " ORDER BY graded_at, grade_id", (entry_id,)).fetchall()


def fetch_report(conn, report_id: int) -> Row | None:
    return conn.execute(
        "SELECT * FROM report WHERE report_id=?", (report_id,)).fetchone()


def fetch_reports(conn, *, type: str | None = None) -> list[Row]:
    """All report rows (render --rebuild walks this)."""
    sql = "SELECT * FROM report"
    params: list = []
    if type is not None:
        sql += " WHERE type=?"
        params.append(type)
    return conn.execute(sql + " ORDER BY generated_at, report_id", params).fetchall()


def fetch_absence_events(conn) -> list[Row]:
    """Full on/off stream, ascending (clock.py derives windows)."""
    return conn.execute(
        "SELECT * FROM absence_event ORDER BY at, event_id").fetchall()


def fetch_open_alerts(conn) -> list[Row]:
    return conn.execute(
        "SELECT * FROM alert WHERE status='open'"
        " ORDER BY created_at, alert_id").fetchall()


def fetch_alert(conn, alert_id: int) -> Row | None:
    return conn.execute(
        "SELECT * FROM alert WHERE alert_id=?", (alert_id,)).fetchone()


def fetch_ask(conn, ask_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM ask WHERE ask_id=?", (ask_id,)).fetchone()


def fetch_open_asks(conn, *, kind: str | None = None) -> list[Row]:
    sql = "SELECT * FROM ask WHERE status IN ('open','reprompted')"
    params: list = []
    if kind is not None:
        sql += " AND kind=?"
        params.append(kind)
    return conn.execute(sql + " ORDER BY created_at, ask_id", params).fetchall()


def fetch_outbox_queued(conn) -> list[Row]:
    """status='queued' ordered FIFO by created_at (drain applies alerts-first)."""
    return conn.execute(
        "SELECT * FROM outbox WHERE status='queued'"
        " ORDER BY created_at, outbox_id").fetchall()


def fetch_outbox_by_key(conn, dedupe_key: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM outbox WHERE dedupe_key=?", (dedupe_key,)).fetchone()


def fetch_run(conn, run_type: str, scheduled_for: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM run_log WHERE run_type=? AND scheduled_for=?",
        (run_type, scheduled_for)).fetchone()


def fetch_watchlist(conn, *, stage: str | None = None) -> list[Row]:
    sql = "SELECT * FROM watchlist_item"
    params: list = []
    if stage is not None:
        sql += " WHERE stage=?"
        params.append(stage)
    return conn.execute(sql + " ORDER BY added_at, item_id", params).fetchall()


def fetch_bot_state(conn) -> Row:
    """Seeded singleton, never None."""
    return conn.execute("SELECT * FROM bot_state WHERE id=1").fetchone()


def fetch_active_gate_session(conn, ticker: str | None = None) -> Row | None:
    sql = "SELECT * FROM gate_session WHERE status='active'"
    params: list = []
    if ticker is not None:
        sql += " AND ticker=?"
        params.append(ticker)
    return conn.execute(
        sql + " ORDER BY started_at DESC, session_id DESC LIMIT 1", params).fetchone()


def fetch_study_state(conn) -> Row:
    return conn.execute("SELECT * FROM study_state WHERE id=1").fetchone()


def fetch_events_for(conn, yf_ticker: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM event WHERE yf_ticker=?"
        " ORDER BY detected_at, event_id", (yf_ticker,)).fetchall()
