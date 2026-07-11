"""Invariant 1 / NFR4: history can never be mutated — every append-only table ABORTs raw UPDATE/DELETE.

Seeds run with foreign_keys=OFF (this file tests triggers, not FKs)."""
from __future__ import annotations

import sqlite3

import pytest

T = "2026-07-08T00:00:00Z"

# (table, seed_sql or None when migration 000 already seeded rows, update_sql)
CASES = [
    ("snapshot",
     f"INSERT INTO snapshot (snapshot_id, as_of, source, cash_balance_eur, created_at)"
     f" VALUES (1, '{T}', 'api_pull', 100.0, '{T}')",
     "UPDATE snapshot SET cash_balance_eur = 0"),
    ("position",
     "INSERT INTO position (snapshot_id, symbol, instrument_type, quantity,"
     " native_currency, mv_native, mv_eur, weight)"
     " VALUES (1, 'MSFT', 'stock', 1.0, 'USD', 100.0, 90.0, 0.5)",
     "UPDATE position SET weight = 0.9"),
    ("designation",
     f"INSERT INTO designation (symbol, framework_status, valid_from, journal_ref)"
     f" VALUES ('MSFT', 'framework', '{T}', 1)",
     "UPDATE designation SET framework_status = 'outside_framework'"),
    ("external_flow",
     "INSERT INTO external_flow (snapshot_id, date, amount_eur, direction)"
     " VALUES (1, '2026-07-08', 10.0, 'deposit')",
     "UPDATE external_flow SET amount_eur = 11.0"),
    ("symbol_map",
     f"INSERT INTO symbol_map (symbol, yf_ticker, valid_from, journal_ref)"
     f" VALUES ('MSFT', 'MSFT', '{T}', 1)",
     "UPDATE symbol_map SET yf_ticker = 'X'"),
    ("price_cache",
     f"INSERT INTO price_cache (yf_ticker, bar_date, close, adj_close, currency, fetched_at)"
     f" VALUES ('MSFT', '2026-07-07', 1.0, 1.0, 'USD', '{T}')",
     "UPDATE price_cache SET close = 2.0"),
    ("fundamentals_period",
     f"INSERT INTO fundamentals_period (yf_ticker, statement_type, period_end,"
     f" payload_json, fingerprint, fetched_at)"
     f" VALUES ('MSFT', 'income', '2026-03-31', '{{}}', 'fp', '{T}')",
     "UPDATE fundamentals_period SET payload_json = '{\"x\":1}'"),
    ("shares_series",
     f"INSERT INTO shares_series (yf_ticker, obs_date, shares, fetched_at)"
     f" VALUES ('MSFT', '2026-07-07', 1.0, '{T}')",
     "UPDATE shares_series SET shares = 2.0"),
    ("officer_snapshot",
     f"INSERT INTO officer_snapshot (yf_ticker, officers_json, fingerprint, fetched_at)"
     f" VALUES ('MSFT', '[]', 'fp', '{T}')",
     "UPDATE officer_snapshot SET officers_json = '[1]'"),
    ("earnings_calendar",
     f"INSERT INTO earnings_calendar (yf_ticker, expected_date, fetched_at)"
     f" VALUES ('MSFT', '2026-07-30', '{T}')",
     "UPDATE earnings_calendar SET expected_date = '2026-08-01'"),
    ("thesis",
     f"INSERT INTO thesis (thesis_id, ticker, origin, created_at)"
     f" VALUES ('TH-MSFT-001', 'MSFT', 'gate', '{T}')",
     "UPDATE thesis SET ticker = 'X'"),
    ("thesis_version",
     f"INSERT INTO thesis_version (thesis_id, version, business_model_2s, moat_types_json,"
     f" moat_evidence, owner_earnings_json, owner_earnings_narrative, fair_band_low,"
     f" fair_band_high, conviction, mgmt_trust, circle_fit, time_horizon,"
     f" ten_year_statement, actor, journal_ref, created_at)"
     f" VALUES ('TH-MSFT-001', 1, 'x', '[\"switching_costs\"]', 'x', '{{}}', 'x',"
     f" 20.0, 30.0, 'high', 'neutral', 'core', '10y_plus', 'x', 'owner', 1, '{T}')",
     "UPDATE thesis_version SET moat_evidence = 'y'"),
    ("thesis_status_log",
     f"INSERT INTO thesis_status_log (thesis_id, status, changed_at, cause)"
     f" VALUES ('TH-MSFT-001', 'draft', '{T}', 'gate')",
     "UPDATE thesis_status_log SET status = 'intact'"),
    ("trigger",
     "INSERT INTO \"trigger\" (thesis_id, introduced_version, type, statement,"
     " persistence, check_method, data_source, cadence)"
     " VALUES ('TH-MSFT-001', 1, 'growth_floor', 'Revenue growth stays above 10%',"
     " 'ttm', 'automated', 'yf_quarterly_statements', 'weekly')",
     "UPDATE \"trigger\" SET statement = 'looser'"),
    ("trigger_check",
     f"INSERT INTO trigger_check (trigger_id, run_id, checked_at, result)"
     f" VALUES (1, 1, '{T}', 'PASS')",
     "UPDATE trigger_check SET result = 'FIRE'"),
    ("journal_entry", None, "UPDATE journal_entry SET actor = 'x'"),
    ("journal_grade",
     f"INSERT INTO journal_grade (entry_id, graded_at, outcome_grade)"
     f" VALUES (1, '{T}', 'good')",
     "UPDATE journal_grade SET outcome_grade = 'bad'"),
    ("report",
     f"INSERT INTO report (run_id, type, generated_at, period, freshness_json,"
     f" content_md, archive_path)"
     f" VALUES (1, 'daily', '{T}', '2026-07-08', '{{}}', 'x', 'letters/2026-07-08.md')",
     "UPDATE report SET content_md = 'y'"),
    ("config", None, "UPDATE config SET value = '999'"),
    ("absence_event",
     f"INSERT INTO absence_event (kind, at, journal_ref) VALUES ('on', '{T}', 1)",
     "UPDATE absence_event SET kind = 'off'"),
    ("study_note",
     f"INSERT INTO study_note (ts, kind, text) VALUES ('{T}', 'circle_note', 'x')",
     "UPDATE study_note SET text = 'y'"),
    ("event",
     f"INSERT INTO event (yf_ticker, source, kind, detected_at)"
     f" VALUES ('MSFT', 'owner', 'earnings', '{T}')",
     "UPDATE event SET note = 'x'"),
    ("schema_migration", None, "UPDATE schema_migration SET sha256 = 'x'"),
    ("scout_shortlist_verdict",
     f"INSERT INTO scout_shortlist_verdict (ticker, axis, value, reason, recorded_at)"
     f" VALUES ('MSFT', 'moat', 'confirmed', 'switching costs', '{T}')",
     "UPDATE scout_shortlist_verdict SET value = 'not-evident'"),
]


@pytest.mark.parametrize("table,seed,update_sql", CASES, ids=[c[0] for c in CASES])
def test_append_only_update_and_delete_abort(tmp_db, table, seed, update_sql):
    tmp_db.execute("PRAGMA foreign_keys=OFF")
    if seed is not None:
        tmp_db.execute(seed)
    assert tmp_db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] >= 1
    with pytest.raises(sqlite3.IntegrityError, match="append-only|immutable"):
        tmp_db.execute(update_sql)
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute(f'DELETE FROM "{table}"')
