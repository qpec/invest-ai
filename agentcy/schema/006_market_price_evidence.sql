-- Immutable provider-neutral market-price evidence and resumable refresh state.

CREATE TABLE market_price_refresh_run (
    refresh_run_id INTEGER PRIMARY KEY,
    scheduled_for TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('RUNNING', 'SUCCEEDED', 'DEGRADED', 'FAILED')
    ),
    selected_count INTEGER NOT NULL CHECK (selected_count >= 0),
    ok_count INTEGER CHECK (ok_count IS NULL OR ok_count >= 0),
    terminal_count INTEGER CHECK (terminal_count IS NULL OR terminal_count >= 0),
    failed_count INTEGER CHECK (failed_count IS NULL OR failed_count >= 0),
    failure_summary TEXT,
    promoted INTEGER NOT NULL DEFAULT 0 CHECK (promoted IN (0, 1)),
    CHECK (promoted = 0 OR status = 'SUCCEEDED'),
    UNIQUE (scheduled_for, attempt)
);

CREATE TABLE market_price_attempt (
    price_attempt_id INTEGER PRIMARY KEY,
    refresh_run_id INTEGER NOT NULL
        REFERENCES market_price_refresh_run(refresh_run_id),
    security_key TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    attempted_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('OK', 'NO_DATA', 'FAILED', 'RATE_LIMITED', 'TERMINAL')
    ),
    reason_code TEXT,
    detail TEXT,
    UNIQUE (refresh_run_id, security_key, attempt_no)
);

CREATE TABLE market_price_observation (
    price_observation_id INTEGER PRIMARY KEY,
    refresh_run_id INTEGER NOT NULL
        REFERENCES market_price_refresh_run(refresh_run_id),
    security_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    bar_date TEXT NOT NULL,
    raw_close REAL NOT NULL CHECK (raw_close > 0),
    adjusted_close REAL NOT NULL CHECK (adjusted_close > 0),
    dividend REAL NOT NULL DEFAULT 0 CHECK (dividend >= 0),
    split_ratio REAL CHECK (split_ratio IS NULL OR split_ratio > 0),
    currency TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    UNIQUE (
        refresh_run_id, security_key, provider, provider_symbol, bar_date, payload_hash
    )
);

CREATE INDEX idx_market_price_attempt_run
    ON market_price_attempt(refresh_run_id, security_key, attempt_no DESC);
CREATE INDEX idx_market_price_observation_security
    ON market_price_observation(security_key, bar_date DESC, fetched_at DESC);

CREATE VIEW v_current_market_price AS
WITH promoted_run AS (
    SELECT refresh_run_id
      FROM market_price_refresh_run
     WHERE status = 'SUCCEEDED' AND promoted = 1
     ORDER BY scheduled_for DESC, attempt DESC, refresh_run_id DESC
     LIMIT 1
), ranked AS (
    SELECT observation.*,
           ROW_NUMBER() OVER (
               PARTITION BY observation.security_key
               ORDER BY observation.bar_date DESC, observation.fetched_at DESC,
                        observation.price_observation_id DESC
           ) AS recency_rank
      FROM market_price_observation observation
      JOIN promoted_run ON promoted_run.refresh_run_id = observation.refresh_run_id
)
SELECT * FROM ranked WHERE recency_rank = 1;

CREATE TRIGGER market_price_attempt_no_update
BEFORE UPDATE ON market_price_attempt
BEGIN SELECT RAISE(ABORT, 'market_price_attempt is append-only'); END;

CREATE TRIGGER market_price_attempt_no_delete
BEFORE DELETE ON market_price_attempt
BEGIN SELECT RAISE(ABORT, 'market_price_attempt is append-only'); END;

CREATE TRIGGER market_price_observation_no_update
BEFORE UPDATE ON market_price_observation
BEGIN SELECT RAISE(ABORT, 'market_price_observation is append-only'); END;

CREATE TRIGGER market_price_observation_no_delete
BEFORE DELETE ON market_price_observation
BEGIN SELECT RAISE(ABORT, 'market_price_observation is append-only'); END;

CREATE TRIGGER market_price_refresh_run_identity_guard
BEFORE UPDATE OF refresh_run_id, scheduled_for, attempt, started_at, selected_count
ON market_price_refresh_run
BEGIN SELECT RAISE(ABORT, 'market_price_refresh_run identity is immutable'); END;

CREATE TRIGGER market_price_refresh_run_no_delete
BEFORE DELETE ON market_price_refresh_run
BEGIN SELECT RAISE(ABORT, 'market_price_refresh_run cannot be deleted'); END;
