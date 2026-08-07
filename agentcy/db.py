"""THE sqlite door for agentcy.db (contracts §3.1). Never opens the benchmark database."""
from __future__ import annotations

import contextlib
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

    NEVER opens the benchmark database (invariant 7 wall 1)."""
    base = Path(dir) if dir is not None else state_dir()
    base.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(base / "agentcy.db")
    # Born group-only, not fixed up later: the box hosts a judgement-lane user
    # (distributed-desk §4 "no access to the SQLite files"), and an installer-time
    # chmod cannot cover a DB file first created by a later timer run. The WAL/SHM
    # sidecars inherit this mode.
    with contextlib.suppress(OSError):
        os.chmod(base / "agentcy.db", 0o640)
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


_POSITION_DETAIL_COLS = frozenset({"symbol", "opened_at", "invested_native",
                                   "invested_eur", "unrealized_pnl_native",
                                   "unrealized_pnl_pct", "current_rate", "direction",
                                   "lot_count", "raw_json"})

def append_position_details(conn, snapshot_id: int, details: Sequence[Mapping]) -> None:
    """Insert position_detail rows for a snapshot (append-only companion, invariant 1)."""
    for row in details:
        vals = _checked(row, _POSITION_DETAIL_COLS, "position_detail")
        vals["snapshot_id"] = snapshot_id
        _insert(conn, "position_detail", vals)


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


_UNIVERSE_FETCH_COLS = frozenset({"yf_ticker", "attempted_at", "outcome", "run_id"})

def append_universe_fetch(conn, *, yf_ticker: str, outcome: str, attempted_at: str,
                          run_id: int | None) -> int:
    """Append one populator fetch-attempt row (design 4); returns rowid. Append-only."""
    return _insert(conn, "universe_fetch", _checked(
        {"yf_ticker": yf_ticker, "attempted_at": attempted_at, "outcome": outcome,
         "run_id": run_id}, _UNIVERSE_FETCH_COLS, "universe_fetch"))


# --- Local security master ------------------------------------------------------------

_SECURITY_RUN_COLS = frozenset({"source_vintage", "input_hash", "started_at", "status",
                                 "input_rows"})
_SECURITY_OBSERVATION_COLS = frozenset({
    "run_id", "security_key", "cik", "symbol", "name", "country", "exchange",
    "currency", "instrument_type", "eligibility", "reason_code", "source", "source_hash",
    "observed_at",
})
_SECURITY_ALIAS_COLS = frozenset({
    "run_id", "security_key", "provider", "symbol", "exchange", "valid_from",
    "valid_until", "observed_at",
})


def append_security_master_run(conn, row: Mapping) -> int:
    """Start one immutable-input security-master run."""
    return _insert(conn, "security_master_run", _checked(
        row, _SECURITY_RUN_COLS, "security_master_run"))


def finish_security_master_run(conn, run_id: int, *, finished_at: str, status: str,
                               eligible_rows: int, ineligible_rows: int,
                               review_rows: int, failure_summary: str | None = None) -> None:
    """Finish the mutable run envelope; evidence rows themselves remain immutable."""
    conn.execute(
        "UPDATE security_master_run SET finished_at=?, status=?, eligible_rows=?,"
        " ineligible_rows=?, review_rows=?, failure_summary=? WHERE run_id=?",
        (finished_at, status, eligible_rows, ineligible_rows, review_rows,
         failure_summary, run_id),
    )


def append_security_observation(conn, row: Mapping) -> int:
    """Append one classified listing observation."""
    return _insert(conn, "security_observation", _checked(
        row, _SECURITY_OBSERVATION_COLS, "security_observation"))


def append_security_alias(conn, row: Mapping) -> int:
    """Append one provider-symbol alias for a stable security key."""
    return _insert(conn, "security_alias", _checked(
        row, _SECURITY_ALIAS_COLS, "security_alias"))


_SCOUT_VERDICT_COLS = frozenset({"ticker", "axis", "value", "reason", "recorded_at"})

def append_scout_verdict(conn, *, ticker: str, axis: str, value: str,
                         reason: str | None, recorded_at: str) -> int:
    """Append one Stage-2 review-artifact verdict row (design 2026-07-11 Part A). Append-only;
    a re-badge appends a superseding row (v_scout_shortlist_verdict resolves latest). NOT
    monitoring state - never read on a schedule."""
    return _insert(conn, "scout_shortlist_verdict", _checked(
        {"ticker": ticker, "axis": axis, "value": value, "reason": reason,
         "recorded_at": recorded_at}, _SCOUT_VERDICT_COLS, "scout_shortlist_verdict"))


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


# --- Metric Evidence Ledger -------------------------------------------------------------

def append_metric_definition(conn, row: Mapping) -> int:
    """Append a versioned metric definition, returning the existing id on exact replay."""
    allowed = frozenset({"metric_key", "formula_version", "unit", "requirement",
                         "freshness_policy", "active_from", "active_until", "created_at"})
    values = _checked(row, allowed, "metric_definition")
    conn.execute(
        "INSERT OR IGNORE INTO metric_definition"
        " (metric_key, formula_version, unit, requirement, freshness_policy, active_from,"
        "  active_until, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(values.get(name) for name in (
            "metric_key", "formula_version", "unit", "requirement", "freshness_policy",
            "active_from", "active_until", "created_at")),
    )
    found = conn.execute(
        "SELECT definition_id FROM metric_definition"
        " WHERE metric_key=? AND formula_version=?",
        (values["metric_key"], values["formula_version"]),
    ).fetchone()
    return int(found[0])


def append_source_observation(conn, row: Mapping) -> int:
    """Append an immutable source fact, returning the id on payload replay."""
    allowed = frozenset({"ticker", "source", "source_key", "accession", "value", "unit",
                         "currency", "period_start", "period_end", "filed_at", "fetched_at",
                         "payload_hash", "refresh_run_id"})
    values = _checked(row, allowed, "source_observation")
    names = ("ticker", "source", "source_key", "accession", "value", "unit", "currency",
             "period_start", "period_end", "filed_at", "fetched_at", "payload_hash",
             "refresh_run_id")
    conn.execute(
        "INSERT OR IGNORE INTO source_observation"
        " (ticker, source, source_key, accession, value, unit, currency, period_start,"
        "  period_end, filed_at, fetched_at, payload_hash, refresh_run_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(values.get(name) for name in names),
    )
    found = conn.execute(
        "SELECT observation_id FROM source_observation"
        " WHERE ticker=? AND source=? AND source_key=? AND period_end=? AND payload_hash=?",
        (values["ticker"], values["source"], values["source_key"], values["period_end"],
         values["payload_hash"]),
    ).fetchone()
    return int(found[0])


def append_metric_observation(conn, row: Mapping) -> int:
    """Append one derived metric observation."""
    allowed = frozenset({"metric_definition_id", "ticker", "value", "status", "confidence",
                         "as_of", "calculated_at", "refresh_run_id", "source_policy_id"})
    return _insert(conn, "metric_observation",
                   _checked(row, allowed, "metric_observation"))


def append_metric_inputs(conn, metric_observation_id: int,
                         source_observation_ids: Sequence[int]) -> None:
    """Link exact source lineage to one derived observation."""
    for source_observation_id in source_observation_ids:
        _insert(conn, "metric_input", {
            "metric_observation_id": metric_observation_id,
            "source_observation_id": source_observation_id,
            "input_role": "input",
        })


def append_source_policy(conn, row: Mapping) -> int:
    """Append a versioned metric/source policy, returning its id on exact replay."""
    allowed = frozenset({"metric_definition_id", "source", "source_role", "priority",
                         "certified", "tolerance_abs", "tolerance_rel", "max_age_seconds",
                         "active_from", "active_until", "created_at"})
    values = _checked(row, allowed, "source_policy")
    names = ("metric_definition_id", "source", "source_role", "priority", "certified",
             "tolerance_abs", "tolerance_rel", "max_age_seconds", "active_from",
             "active_until", "created_at")
    conn.execute(
        "INSERT OR IGNORE INTO source_policy"
        " (metric_definition_id, source, source_role, priority, certified, tolerance_abs,"
        "  tolerance_rel, max_age_seconds, active_from, active_until, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(values.get(name) for name in names),
    )
    found = conn.execute(
        "SELECT policy_id FROM source_policy"
        " WHERE metric_definition_id=? AND source=? AND active_from=?",
        (values["metric_definition_id"], values["source"], values["active_from"]),
    ).fetchone()
    return int(found[0])


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


def append_gate_session(conn, *, ticker: str, mode: str, started_at: str) -> int:
    """Insert a gate_session row (step/state_json/status take DDL defaults); returns session_id."""
    cur = conn.execute(
        "INSERT INTO gate_session (ticker, mode, started_at, updated_at) VALUES (?, ?, ?, ?)",
        (ticker, mode, started_at, started_at),
    )
    return cur.lastrowid


def append_watchlist_item(conn, *, ticker: str, added_at: str, idea_source: str,
                          one_line_why: str) -> int:
    """Insert a C.1 watchlist_item row (stage defaults to 'raw'); returns item_id."""
    cur = conn.execute(
        "INSERT INTO watchlist_item (ticker, added_at, idea_source, one_line_why, stage_changed_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (ticker, added_at, idea_source, one_line_why, added_at),
    )
    return cur.lastrowid


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


def fetch_scout_verdicts_current(conn, ticker: str | None = None) -> list[Row]:
    """Latest verdict per (ticker, axis) from v_scout_shortlist_verdict, optionally one ticker."""
    sql = "SELECT * FROM v_scout_shortlist_verdict"
    params: list = []
    if ticker is not None:
        sql += " WHERE ticker = ?"
        params.append(ticker)
    return conn.execute(sql + " ORDER BY ticker, axis", params).fetchall()


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


def fetch_snapshot(conn, snapshot_id: int) -> Row | None:
    """One snapshot row by id (cash_balance_eur lives here, not on positions)."""
    return conn.execute(
        "SELECT * FROM snapshot WHERE snapshot_id=?", (snapshot_id,)).fetchone()


def fetch_recent_snapshots(conn, limit: int) -> list[Row]:
    """The newest `limit` snapshots, newest first (E.1 reconciliation reads the last two to
    recover the cash delta for an MA-12 external-flow confirmation)."""
    return conn.execute(
        "SELECT * FROM snapshot ORDER BY as_of DESC, snapshot_id DESC LIMIT ?",
        (limit,)).fetchall()


def fetch_snapshots_between(conn, start: str, end: str) -> list[Row]:
    """Snapshot rows with start <= as_of <= end, oldest first (quarterly return series)."""
    return conn.execute(
        "SELECT * FROM snapshot WHERE as_of >= ? AND as_of <= ? "
        "ORDER BY as_of ASC, snapshot_id ASC", (start, end)).fetchall()


def fetch_first_snapshot_as_of(conn) -> str | None:
    """Earliest snapshot as_of (quarterly since-inception series start); None if empty."""
    return conn.execute("SELECT MIN(as_of) AS a FROM snapshot").fetchone()["a"]


def fetch_external_flows_for_snapshot(conn, snapshot_id: int) -> list[Row]:
    """MA-12 external flows attributed to the period ending at this snapshot."""
    return conn.execute(
        "SELECT * FROM external_flow WHERE snapshot_id=? ORDER BY flow_id ASC",
        (snapshot_id,)).fetchall()


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


def fetch_position_details(conn, snapshot_id: int) -> list[Row]:
    """position_detail rows for a snapshot, ordered by symbol (thesis/journal/reporting only)."""
    return conn.execute(
        "SELECT * FROM position_detail WHERE snapshot_id=? ORDER BY symbol",
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


def fetch_universe_fetch_latest(conn) -> dict[str, Row]:
    """Latest attempt row per ticker from v_universe_fetch (cursor + milestone feed)."""
    return {r["yf_ticker"]: r for r in conn.execute(
        "SELECT * FROM v_universe_fetch").fetchall()}


def fetch_universe_fetch_failure_counts(conn) -> dict[str, int]:
    """Per ticker: count of 'failed'/'no_data' attempts SINCE the last 'ok' (design 6
    dead-list feed). A ticker that never recorded an 'ok' counts all its failures."""
    counts: dict[str, int] = {}
    rows = conn.execute(
        "SELECT yf_ticker, attempted_at, outcome FROM universe_fetch"
        " ORDER BY yf_ticker, attempted_at, rowid").fetchall()
    for r in rows:
        t = r["yf_ticker"]
        if r["outcome"] == "ok":
            counts[t] = 0
        elif r["outcome"] in ("failed", "no_data"):
            counts[t] = counts.get(t, 0) + 1
        # 'rate_limited' is transient upstream throttling, NOT a dead-list failure (design 6)
    return counts


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


def fetch_unanswered_asks(conn, *, kind: str | None = None) -> list[Row]:
    """Counted-unanswered asks (past effective deadline); the daily letter escalates these."""
    sql = "SELECT * FROM ask WHERE status='unanswered'"
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


def fetch_ontime_finished_keys(conn, run_type: str) -> set[str]:
    """scheduled_for of every run of run_type that finished ON TIME (late=0). The daily
    gap line names due days NOT in this set — days no letter was ever sent for (§1.3).
    Newest-first sweep means late keys are not yet started when the on-time letter is built,
    so 'was a letter sent on schedule?' is the only reliable gap signal at that moment."""
    rows = conn.execute(
        "SELECT scheduled_for FROM run_log"
        " WHERE run_type=? AND late=0 AND finished_at IS NOT NULL", (run_type,)).fetchall()
    return {r["scheduled_for"] for r in rows}


def fetch_last_finished_run(conn) -> Row | None:
    """Most recently finished run (the /status card reports this state, never runs checks)."""
    return conn.execute(
        "SELECT * FROM run_log WHERE finished_at IS NOT NULL"
        " ORDER BY finished_at DESC, run_id DESC LIMIT 1").fetchone()


def fetch_watchlist(conn, *, stage: str | None = None) -> list[Row]:
    sql = "SELECT * FROM watchlist_item"
    params: list = []
    if stage is not None:
        sql += " WHERE stage=?"
        params.append(stage)
    return conn.execute(sql + " ORDER BY added_at, item_id", params).fetchall()


def fetch_watchlist_item(conn, item_id: int) -> Row | None:
    return conn.execute(
        "SELECT * FROM watchlist_item WHERE item_id=?", (item_id,)).fetchone()


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


def fetch_gate_session(conn, session_id: int) -> Row | None:
    return conn.execute(
        "SELECT * FROM gate_session WHERE session_id=?", (session_id,)).fetchone()


def fetch_study_state(conn) -> Row:
    return conn.execute("SELECT * FROM study_state WHERE id=1").fetchone()


def fetch_events_for(conn, yf_ticker: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM event WHERE yf_ticker=?"
        " ORDER BY detected_at, event_id", (yf_ticker,)).fetchall()


# --- column-guard update helpers (the ONLY mutation path; guarded columns only) ---

def _update(conn, table: str, key_col: str, key, changes: Mapping) -> None:
    sets = ", ".join(f"{c} = ?" for c in changes)
    cur = conn.execute(f'UPDATE "{table}" SET {sets} WHERE {key_col} = ?',
                       (*changes.values(), key))
    if cur.rowcount != 1:
        raise LookupError(f"{table}.{key_col}={key!r}: no such row")


def update_ask_state(conn, ask_id: str, *, status: str, answer_json: str | None = None,
                     answered_at: str | None = None,
                     tg_message_id: int | None = None) -> None:
    """Update exactly the four guarded ask columns."""
    changes: dict = {"status": status}
    if answer_json is not None:
        changes["answer_json"] = answer_json
    if answered_at is not None:
        changes["answered_at"] = answered_at
    if tg_message_id is not None:
        changes["tg_message_id"] = tg_message_id
    _update(conn, "ask", "ask_id", ask_id, changes)


def update_outbox_state(conn, outbox_id: int, *, status: str | None = None,
                        attempts: int | None = None,
                        next_attempt_at: str | None = None,
                        tg_message_id: int | None = None) -> None:
    """Update delivery-state columns (each non-None kwarg)."""
    changes: dict = {}
    if status is not None:
        changes["status"] = status
    if attempts is not None:
        changes["attempts"] = attempts
    if next_attempt_at is not None:
        changes["next_attempt_at"] = next_attempt_at
    if tg_message_id is not None:
        changes["tg_message_id"] = tg_message_id
    _update(conn, "outbox", "outbox_id", outbox_id, changes)


def supersede_outbox_payload(conn, outbox_id: int, *, payload_html: str,
                             document_path: str | None = None,
                             reply_markup_json: str | None = None) -> None:
    """Replace payload of a QUEUED row wholesale (§5.4); the DB trigger aborts if already sent."""
    _update(conn, "outbox", "outbox_id", outbox_id,
            {"payload_html": payload_html, "document_path": document_path,
             "reply_markup_json": reply_markup_json})


def update_alert_resolution(conn, alert_id: int, *, status: str, resolved_at: str,
                            resolution_journal_ref: int) -> None:
    """Record alert resolution (confirmed_broken/refuted/ignored)."""
    _update(conn, "alert", "alert_id", alert_id,
            {"status": status, "resolved_at": resolved_at,
             "resolution_journal_ref": resolution_journal_ref})


def update_watchlist_stage(conn, item_id: int, *, stage: str, stage_changed_at: str,
                           thesis_ref: str | None = None) -> None:
    """Advance watchlist stage (C.1/C.6 sweeps, Gate verdicts)."""
    changes: dict = {"stage": stage, "stage_changed_at": stage_changed_at}
    if thesis_ref is not None:
        changes["thesis_ref"] = thesis_ref
    _update(conn, "watchlist_item", "item_id", item_id, changes)


def update_run_start(conn, run_id: int, *, started_at: str, attempt: int,
                     late: bool) -> None:
    """Sweep re-claim of a crashed logical key (§1.3): a fresh attempt, so clear any FAILED
    finish stamp (a never-finished key already carries NULL — this is a no-op there). The
    re-run's update_run_finish restamps finished_at/status on success (FIX.3)."""
    _update(conn, "run_log", "run_id", run_id,
            {"started_at": started_at, "attempt": attempt, "late": int(late),
             "finished_at": None, "status": None})


def update_run_finish(conn, run_id: int, *, finished_at: str, status: str,
                      inputs_json: str | None = None,
                      outputs_json: str | None = None) -> None:
    """Finish a run; finished keys exit 0 on re-fire."""
    changes: dict = {"finished_at": finished_at, "status": status}
    if inputs_json is not None:
        changes["inputs_json"] = inputs_json
    if outputs_json is not None:
        changes["outputs_json"] = outputs_json
    _update(conn, "run_log", "run_id", run_id, changes)


def update_bot_state(conn, *, last_update_id: int) -> None:
    """Persist offset — caller wraps in the SAME transaction as handle() writes (§5.2)."""
    _update(conn, "bot_state", "id", 1, {"last_update_id": last_update_id})


def update_gate_session(conn, session_id: int, *, step: str, state_json: str,
                        status: str, updated_at: str) -> None:
    """Persist resumable Gate progress."""
    _update(conn, "gate_session", "session_id", session_id,
            {"step": step, "state_json": state_json, "status": status,
             "updated_at": updated_at})


def update_study_state(conn, *, last_restudied_thesis_id: str,
                       mental_model_index: int, updated_at: str) -> None:
    """Advance F.3 rotation pointer."""
    _update(conn, "study_state", "id", 1,
            {"last_restudied_thesis_id": last_restudied_thesis_id,
             "mental_model_index": mental_model_index, "updated_at": updated_at})


def retire_trigger(conn, trigger_id: int, *, retired_at: str) -> None:
    """The sole "trigger" UPDATE: set retired_at (write-once; DB trigger enforces)."""
    _update(conn, "trigger", "trigger_id", trigger_id, {"retired_at": retired_at})


# --- P3 additions (CONTRACT ISSUE resolution): ask/alert inserts + domain reads ---

def next_ask_seq(conn, kind: str) -> int:
    """Next monotonic seq for a kind (asks.mint uses this to form '<K><seq>')."""
    row = conn.execute("SELECT MAX(seq) AS m FROM ask WHERE kind = ?", (kind,)).fetchone()
    return (row["m"] or 0) + 1


def append_ask(conn, row: Mapping) -> None:
    """Insert a D.5 ask identity+initial-state row (asks.mint validates before calling)."""
    conn.execute(
        "INSERT INTO ask (ask_id, kind, seq, created_at, prompt, options_json, "
        "expects_freetext, thesis_ref, trigger_ref, alert_ref, deadline, run_id) "
        "VALUES (:ask_id, :kind, :seq, :created_at, :prompt, :options_json, "
        ":expects_freetext, :thesis_ref, :trigger_ref, :alert_ref, :deadline, :run_id)",
        {"thesis_ref": None, "trigger_ref": None, "alert_ref": None, "deadline": None,
         "run_id": None, **row})


def append_alert(conn, row: Mapping) -> int:
    """Insert one alert row (one per fired trigger); returns alert_id."""
    cur = conn.execute(
        "INSERT INTO alert (thesis_id, trigger_id, run_id, storm_key, created_at, deadline) "
        "VALUES (:thesis_id, :trigger_id, :run_id, :storm_key, :created_at, :deadline)",
        {"storm_key": None, **row})
    return cur.lastrowid


def append_outbox(conn, *, dedupe_key: str, kind: str, created_at: str, payload_html: str,
                  run_id: int | None = None, artifact_ref: int | None = None,
                  ask_ref: str | None = None, document_path: str | None = None,
                  reply_markup_json: str | None = None) -> int:
    """Insert a fresh queued outbox row (status/attempts fall to schema DEFAULTs); returns outbox_id."""
    return _insert(conn, "outbox", {
        "dedupe_key": dedupe_key, "kind": kind, "created_at": created_at,
        "run_id": run_id, "artifact_ref": artifact_ref, "ask_ref": ask_ref,
        "payload_html": payload_html, "document_path": document_path,
        "reply_markup_json": reply_markup_json})


def fetch_theses(conn) -> list:
    """All thesis identity rows."""
    return conn.execute("SELECT * FROM thesis ORDER BY created_at, thesis_id").fetchall()


def fetch_thesis_versions(conn, thesis_id: str) -> list:
    """All versions for a thesis, ascending."""
    return conn.execute(
        "SELECT * FROM thesis_version WHERE thesis_id = ? ORDER BY version",
        (thesis_id,)).fetchall()


def fetch_asks_for(conn, *, kind=None, thesis_ref=None, trigger_ref=None) -> list:
    """Asks filtered by any combination of kind / thesis_ref / trigger_ref."""
    clauses, params = [], []
    if kind is not None:
        clauses.append("kind = ?"); params.append(kind)
    if thesis_ref is not None:
        clauses.append("thesis_ref = ?"); params.append(thesis_ref)
    if trigger_ref is not None:
        clauses.append("trigger_ref = ?"); params.append(trigger_ref)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute("SELECT * FROM ask" + where + " ORDER BY created_at, ask_id",
                        params).fetchall()
