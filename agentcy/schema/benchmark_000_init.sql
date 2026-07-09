-- schema/benchmark_000_init.sql — benchmark.db, migration 000.
-- Applied ONLY by agentcy/benchmark.py (the sole module knowing this file's path).

CREATE TABLE benchmark_series (
  bar_date    TEXT PRIMARY KEY,
  sp500tr_usd REAL NOT NULL,
  usdeur      REAL NOT NULL,
  tr_eur      REAL NOT NULL,
  fetched_at  TEXT NOT NULL,
  run_id      INTEGER
);
CREATE TRIGGER benchmark_series_no_update BEFORE UPDATE ON benchmark_series BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER benchmark_series_no_delete BEFORE DELETE ON benchmark_series BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;

CREATE TABLE schema_migration (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  sha256     TEXT NOT NULL
);
CREATE TRIGGER bm_schema_migration_no_update BEFORE UPDATE ON schema_migration BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER bm_schema_migration_no_delete BEFORE DELETE ON schema_migration BEGIN SELECT RAISE(ABORT, 'append-only'); END;
