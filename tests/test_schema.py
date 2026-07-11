"""Schema files apply cleanly and contain exactly the contract objects + bootstrap seeds."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "agentcy" / "schema"

AGENTCY_TABLES = {
    "snapshot", "position", "designation", "external_flow", "symbol_map",
    "price_cache", "fundamentals_period", "shares_series", "officer_snapshot",
    "earnings_calendar", "thesis", "thesis_version", "thesis_status_log",
    "trigger", "trigger_check", "journal_entry", "journal_grade", "report",
    "config", "absence_event", "study_note", "event", "schema_migration",
    "run_log", "ask", "alert", "outbox", "watchlist_item", "bot_state",
    "gate_session", "study_state",
}
AGENTCY_VIEWS = {"v_price", "positions_advice"}

CONFIG_SEED_KEYS = {
    "cash_band_low_pct", "cash_band_high_pct", "max_position_soft_pct",
    "max_position_hard_pct", "max_cluster_weight_pct", "min_effective_bets",
    "position_count_low", "position_count_high", "outside_framework_cap_pct",
    "buy_opportunity_discount_pct", "alert_decision_days",
    "initial_weight_high_pct", "initial_weight_medium_pct", "initial_weight_low_pct",
    "correlation_threshold", "daily_letter_mode", "benchmark",
    "universe_pin_sha", "screen_recipe", "license_exceptions", "deadman_ping_url",
    "populate_enabled", "populate_starter_size", "populate_nightly_minutes",
    "populate_dead_after_failures",
}


def _apply(name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    return conn


def test_agentcy_schema_applies_with_all_objects():
    conn = _apply("000_init.sql")
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    views = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view'")}
    assert tables == AGENTCY_TABLES
    assert views == AGENTCY_VIEWS
    # every append-only table has its RAISE(ABORT) pair; spot-check counts
    n_triggers = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
    # 22 append-only pairs (44) + trigger table 3 + 8 operational tables' guard/no_delete
    # (bot_state/study_state 2 each, outbox 3, others 2 each) = 44+3+17 = 64
    assert n_triggers == 64


def test_bootstrap_seeds_present():
    conn = _apply("000_init.sql")
    assert conn.execute("SELECT COUNT(*) FROM journal_entry").fetchone()[0] == 5
    keys = {r["key"] for r in conn.execute("SELECT key FROM config")}
    assert keys == CONFIG_SEED_KEYS
    assert conn.execute("SELECT last_update_id FROM bot_state WHERE id=1").fetchone()[0] == 0
    ss = conn.execute("SELECT * FROM study_state WHERE id=1").fetchone()
    assert ss["mental_model_index"] == 0 and ss["last_restudied_thesis_id"] is None
    # journal-FK seeds: license exception journaled against S1 entry (entry_id 2)
    lic = conn.execute(
        "SELECT value, journal_ref FROM config WHERE key='license_exceptions'").fetchone()
    assert lic["value"] == "certifi:MPL-2.0" and lic["journal_ref"] == 2


def test_positions_advice_has_no_avg_open_price_column():
    conn = _apply("000_init.sql")
    cols = [d[0] for d in conn.execute("SELECT * FROM positions_advice").description]
    assert "avg_open_price" not in cols
    assert cols == ["snapshot_id", "symbol", "yf_ticker", "instrument_type",
                    "quantity", "native_currency", "mv_native", "mv_eur",
                    "weight", "leverage"]


def test_benchmark_schema_applies_and_is_minimal():
    conn = _apply("benchmark_000_init.sql")
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"benchmark_series", "schema_migration"}
    n_triggers = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
    assert n_triggers == 4


def test_no_benchmark_objects_in_agentcy_schema():
    conn = _apply("000_init.sql")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE '%benchmark%'").fetchall()
    assert rows == []
