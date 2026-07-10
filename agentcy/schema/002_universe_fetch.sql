-- schema/002_universe_fetch.sql — the populator progress log (design 2026-07-10 section 4).
-- Append-only, trigger-guarded; v_universe_fetch = latest attempt per ticker (the
-- price_cache/v_price idiom). One row per fetch attempt; drives the nightly cursor.

CREATE TABLE universe_fetch (
  yf_ticker    TEXT NOT NULL,
  attempted_at TEXT NOT NULL,
  outcome      TEXT NOT NULL CHECK (outcome IN ('ok','no_data','failed','rate_limited')),
  run_id       INTEGER REFERENCES run_log(run_id)
);                                             -- re-attempts APPEND; v_universe_fetch = latest per ticker
CREATE INDEX idx_universe_fetch ON universe_fetch (yf_ticker, attempted_at);

-- Latest attempt per ticker; rowid breaks same-timestamp ties (the v_price idiom).
CREATE VIEW v_universe_fetch AS
SELECT yf_ticker, attempted_at AS last_attempt, outcome, run_id
FROM (
  SELECT u.*, ROW_NUMBER() OVER (
    PARTITION BY yf_ticker ORDER BY attempted_at DESC, rowid DESC) AS rn
  FROM universe_fetch u
) WHERE rn = 1;

CREATE TRIGGER universe_fetch_no_update BEFORE UPDATE ON universe_fetch
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER universe_fetch_no_delete BEFORE DELETE ON universe_fetch
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;

-- REVIEW FIX M3 — admit a dedicated 'populate' run_type. Adding a value to a CHECK
-- constraint requires a table rebuild (SQLite has no ALTER … CHECK). Rebuild run_log in
-- place under foreign_keys=OFF (so the temporary drop does not trip the ~10 child FKs) +
-- legacy_alter_table=ON (so RENAME does NOT rewrite those child references to run_log__old).
-- Identity/history column guard + no-delete guard are re-created afterwards, unchanged.
PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;

DROP TRIGGER run_log_guard;
DROP TRIGGER run_log_no_delete;

ALTER TABLE run_log RENAME TO run_log__old;

CREATE TABLE run_log (
  run_id        INTEGER PRIMARY KEY,
  run_type      TEXT NOT NULL CHECK (run_type IN ('daily','weekly','quarterly','event','backup','gate','scout','snapshot','desk','populate')),
  scheduled_for TEXT NOT NULL,                 -- logical key; for event runs: '{yf_ticker}:{detected_at}' (§1.3)
  created_at    TEXT NOT NULL,
  -- updatable operational state:
  started_at    TEXT NOT NULL,                 -- re-claimed by the sweep on a crashed key
  attempt       INTEGER NOT NULL DEFAULT 1,
  late          INTEGER NOT NULL DEFAULT 0,
  finished_at   TEXT,
  status        TEXT CHECK (status IN ('ok','degraded','failed')),
  inputs_json   TEXT,                          -- embeds effective config (§9)
  outputs_json  TEXT,
  UNIQUE (run_type, scheduled_for)
);

INSERT INTO run_log (run_id, run_type, scheduled_for, created_at, started_at,
                     attempt, late, finished_at, status, inputs_json, outputs_json)
  SELECT run_id, run_type, scheduled_for, created_at, started_at,
         attempt, late, finished_at, status, inputs_json, outputs_json
  FROM run_log__old;

DROP TABLE run_log__old;

CREATE TRIGGER run_log_guard BEFORE UPDATE OF run_id, run_type, scheduled_for, created_at ON run_log
  BEGIN SELECT RAISE(ABORT, 'column guard: run_log identity immutable'); END;
CREATE TRIGGER run_log_no_delete BEFORE DELETE ON run_log BEGIN SELECT RAISE(ABORT, 'no delete (NFR4)'); END;

PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;
