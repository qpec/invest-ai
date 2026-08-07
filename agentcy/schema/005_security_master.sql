-- Local security master: immutable source snapshots and eligibility decisions.

CREATE TABLE security_master_run (
    run_id INTEGER PRIMARY KEY,
    source_vintage TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    input_rows INTEGER NOT NULL CHECK (input_rows >= 0),
    eligible_rows INTEGER CHECK (eligible_rows IS NULL OR eligible_rows >= 0),
    ineligible_rows INTEGER CHECK (ineligible_rows IS NULL OR ineligible_rows >= 0),
    review_rows INTEGER CHECK (review_rows IS NULL OR review_rows >= 0),
    failure_summary TEXT,
    UNIQUE (source_vintage, input_hash)
);

CREATE TABLE security_observation (
    observation_id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES security_master_run(run_id),
    security_key TEXT NOT NULL,
    cik TEXT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    country TEXT,
    exchange TEXT,
    instrument_type TEXT NOT NULL CHECK (instrument_type IN (
        'ORDINARY_SHARE', 'FUND', 'LISTED_DEBT', 'WARRANT_OR_UNIT',
        'PREFERRED_SHARE', 'ROYALTY_TRUST', 'UNKNOWN'
    )),
    eligibility TEXT NOT NULL CHECK (eligibility IN (
        'ELIGIBLE', 'INELIGIBLE', 'REVIEW'
    )),
    reason_code TEXT NOT NULL CHECK (reason_code IN (
        'PRIMARY_ORDINARY_SHARE', 'DUTCH_PRIMARY_ORDINARY_SHARE', 'FUND',
        'LISTED_DEBT', 'WARRANT_OR_UNIT', 'PREFERRED_SHARE', 'ROYALTY_TRUST',
        'UNRESOLVED_SECONDARY_LISTING', 'UNKNOWN_INSTRUMENT'
    )),
    source TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE (run_id, source, symbol, exchange)
);

CREATE TABLE security_alias (
    alias_id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES security_master_run(run_id),
    security_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    observed_at TEXT NOT NULL,
    UNIQUE (run_id, provider, symbol, exchange)
);

CREATE INDEX idx_security_observation_run ON security_observation(run_id);
CREATE INDEX idx_security_observation_key ON security_observation(security_key);
CREATE INDEX idx_security_observation_symbol ON security_observation(symbol, exchange);
CREATE INDEX idx_security_alias_key ON security_alias(security_key, provider);

CREATE VIEW v_current_security AS
SELECT observation.*
  FROM security_observation observation
  JOIN (
      SELECT MAX(run_id) AS run_id
        FROM security_master_run
       WHERE status = 'SUCCEEDED'
  ) current_run ON current_run.run_id = observation.run_id;

CREATE VIEW v_eligible_security AS
SELECT * FROM v_current_security WHERE eligibility = 'ELIGIBLE';

CREATE TRIGGER security_observation_no_update
BEFORE UPDATE ON security_observation
BEGIN SELECT RAISE(ABORT, 'security_observation is append-only'); END;

CREATE TRIGGER security_observation_no_delete
BEFORE DELETE ON security_observation
BEGIN SELECT RAISE(ABORT, 'security_observation is append-only'); END;

CREATE TRIGGER security_alias_no_update
BEFORE UPDATE ON security_alias
BEGIN SELECT RAISE(ABORT, 'security_alias is append-only'); END;

CREATE TRIGGER security_alias_no_delete
BEFORE DELETE ON security_alias
BEGIN SELECT RAISE(ABORT, 'security_alias is append-only'); END;
