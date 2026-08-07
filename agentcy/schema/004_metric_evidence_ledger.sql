-- Metric Evidence Ledger: immutable facts, derived observations, lineage and run health.

CREATE TABLE metric_definition (
    definition_id INTEGER PRIMARY KEY,
    metric_key TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    unit TEXT NOT NULL,
    requirement TEXT NOT NULL CHECK (requirement IN ('REQUIRED', 'OPTIONAL')),
    freshness_policy TEXT NOT NULL CHECK (freshness_policy IN ('filing_aware', 'trading_day')),
    active_from TEXT NOT NULL,
    active_until TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (metric_key, formula_version)
);

CREATE TABLE ledger_refresh_run (
    refresh_run_id INTEGER PRIMARY KEY,
    run_type TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    catch_up INTEGER NOT NULL DEFAULT 0 CHECK (catch_up IN (0, 1)),
    universe_size INTEGER CHECK (universe_size >= 0),
    covered_metrics INTEGER CHECK (covered_metrics >= 0),
    failure_summary TEXT,
    UNIQUE (run_type, scheduled_for, attempt)
);

CREATE TABLE source_policy (
    policy_id INTEGER PRIMARY KEY,
    metric_definition_id INTEGER NOT NULL REFERENCES metric_definition(definition_id),
    source TEXT NOT NULL,
    source_role TEXT NOT NULL CHECK (source_role IN ('PRIMARY', 'FALLBACK')),
    priority INTEGER NOT NULL CHECK (priority >= 0),
    certified INTEGER NOT NULL DEFAULT 0 CHECK (certified IN (0, 1)),
    tolerance_abs REAL CHECK (tolerance_abs IS NULL OR tolerance_abs >= 0),
    tolerance_rel REAL CHECK (tolerance_rel IS NULL OR tolerance_rel >= 0),
    max_age_seconds INTEGER CHECK (max_age_seconds IS NULL OR max_age_seconds > 0),
    active_from TEXT NOT NULL,
    active_until TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (metric_definition_id, source, active_from)
);

CREATE TABLE source_observation (
    observation_id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    source_key TEXT NOT NULL,
    accession TEXT,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    currency TEXT,
    period_start TEXT,
    period_end TEXT NOT NULL,
    filed_at TEXT,
    fetched_at TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    refresh_run_id INTEGER REFERENCES ledger_refresh_run(refresh_run_id),
    UNIQUE (ticker, source, source_key, period_end, payload_hash)
);

CREATE TABLE metric_observation (
    metric_observation_id INTEGER PRIMARY KEY,
    metric_definition_id INTEGER NOT NULL REFERENCES metric_definition(definition_id),
    ticker TEXT NOT NULL,
    value REAL,
    status TEXT NOT NULL CHECK (
        status IN ('FRESH', 'STALE', 'MISSING', 'CONFLICT', 'UNVERIFIABLE')
    ),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    as_of TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    refresh_run_id INTEGER REFERENCES ledger_refresh_run(refresh_run_id),
    source_policy_id INTEGER REFERENCES source_policy(policy_id),
    UNIQUE (metric_definition_id, ticker, as_of, calculated_at)
);

CREATE TABLE metric_input (
    metric_observation_id INTEGER NOT NULL
        REFERENCES metric_observation(metric_observation_id),
    source_observation_id INTEGER NOT NULL REFERENCES source_observation(observation_id),
    input_role TEXT NOT NULL DEFAULT 'input',
    PRIMARY KEY (metric_observation_id, source_observation_id, input_role)
);

CREATE TABLE parity_result (
    parity_result_id INTEGER PRIMARY KEY,
    refresh_run_id INTEGER NOT NULL REFERENCES ledger_refresh_run(refresh_run_id),
    metric_definition_id INTEGER NOT NULL REFERENCES metric_definition(definition_id),
    ticker TEXT NOT NULL,
    legacy_value REAL,
    ledger_value REAL,
    legacy_status TEXT NOT NULL,
    ledger_status TEXT NOT NULL,
    tolerance_abs REAL NOT NULL CHECK (tolerance_abs >= 0),
    tolerance_rel REAL NOT NULL CHECK (tolerance_rel >= 0),
    verdict TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL')),
    compared_at TEXT NOT NULL,
    UNIQUE (refresh_run_id, metric_definition_id, ticker)
);

CREATE INDEX idx_source_observation_ticker_key
    ON source_observation(ticker, source_key, period_end DESC, fetched_at DESC);
CREATE INDEX idx_metric_observation_current
    ON metric_observation(ticker, metric_definition_id, as_of DESC, calculated_at DESC);
CREATE INDEX idx_metric_observation_status ON metric_observation(status);
CREATE INDEX idx_refresh_run_health
    ON ledger_refresh_run(run_type, scheduled_for DESC, status);

CREATE VIEW v_current_metric AS
WITH ranked AS (
    SELECT mo.*,
           md.metric_key,
           md.formula_version,
           md.unit,
           md.requirement,
           COALESCE(sp.source_role, 'PRIMARY') AS source_role,
           COALESCE(sp.source, 'ledger-primary') AS source,
           ROW_NUMBER() OVER (
               PARTITION BY mo.ticker, md.metric_key
               ORDER BY mo.as_of DESC, mo.calculated_at DESC,
                        mo.metric_observation_id DESC
           ) AS recency_rank
      FROM metric_observation mo
      JOIN metric_definition md ON md.definition_id = mo.metric_definition_id
      LEFT JOIN source_policy sp ON sp.policy_id = mo.source_policy_id
     WHERE (md.active_until IS NULL OR md.active_until >= mo.as_of)
       AND (sp.policy_id IS NULL OR sp.source_role = 'PRIMARY' OR sp.certified = 1)
       AND (sp.active_from IS NULL OR sp.active_from <= mo.as_of)
       AND (sp.active_until IS NULL OR sp.active_until >= mo.as_of)
)
SELECT * FROM ranked WHERE recency_rank = 1;

CREATE VIEW v_stock_data_health AS
SELECT ticker,
       SUM(CASE WHEN requirement = 'REQUIRED' AND status <> 'FRESH' THEN 1 ELSE 0 END)
           AS required_unusable,
       SUM(CASE WHEN requirement = 'OPTIONAL' AND status <> 'FRESH' THEN 1 ELSE 0 END)
           AS optional_unusable,
       SUM(CASE WHEN status = 'CONFLICT' THEN 1 ELSE 0 END) AS conflicts,
       MIN(confidence) AS minimum_confidence,
       CASE WHEN SUM(CASE WHEN requirement = 'REQUIRED' AND status <> 'FRESH'
                          THEN 1 ELSE 0 END) = 0 THEN 1 ELSE 0 END
           AS decision_ready
  FROM v_current_metric
 GROUP BY ticker;

CREATE VIEW v_metric_coverage AS
SELECT metric_key,
       COUNT(*) AS observed_stocks,
       SUM(CASE WHEN status = 'FRESH' THEN 1 ELSE 0 END) AS fresh_stocks,
       SUM(CASE WHEN status = 'STALE' THEN 1 ELSE 0 END) AS stale_stocks,
       SUM(CASE WHEN status = 'MISSING' THEN 1 ELSE 0 END) AS missing_stocks,
       SUM(CASE WHEN status = 'CONFLICT' THEN 1 ELSE 0 END) AS conflict_stocks,
       SUM(CASE WHEN status = 'UNVERIFIABLE' THEN 1 ELSE 0 END)
           AS unverifiable_stocks
  FROM v_current_metric
 GROUP BY metric_key;

-- Evidence and definitions are immutable. New knowledge appends a new row/version.
CREATE TRIGGER metric_definition_no_update BEFORE UPDATE ON metric_definition
BEGIN SELECT RAISE(ABORT, 'metric_definition is append-only'); END;
CREATE TRIGGER metric_definition_no_delete BEFORE DELETE ON metric_definition
BEGIN SELECT RAISE(ABORT, 'metric_definition is append-only'); END;
CREATE TRIGGER source_policy_no_update BEFORE UPDATE ON source_policy
BEGIN SELECT RAISE(ABORT, 'source_policy is append-only'); END;
CREATE TRIGGER source_policy_no_delete BEFORE DELETE ON source_policy
BEGIN SELECT RAISE(ABORT, 'source_policy is append-only'); END;
CREATE TRIGGER source_observation_no_update BEFORE UPDATE ON source_observation
BEGIN SELECT RAISE(ABORT, 'source_observation is append-only'); END;
CREATE TRIGGER source_observation_no_delete BEFORE DELETE ON source_observation
BEGIN SELECT RAISE(ABORT, 'source_observation is append-only'); END;
CREATE TRIGGER metric_observation_no_update BEFORE UPDATE ON metric_observation
BEGIN SELECT RAISE(ABORT, 'metric_observation is append-only'); END;
CREATE TRIGGER metric_observation_no_delete BEFORE DELETE ON metric_observation
BEGIN SELECT RAISE(ABORT, 'metric_observation is append-only'); END;
CREATE TRIGGER metric_input_no_update BEFORE UPDATE ON metric_input
BEGIN SELECT RAISE(ABORT, 'metric_input is append-only'); END;
CREATE TRIGGER metric_input_no_delete BEFORE DELETE ON metric_input
BEGIN SELECT RAISE(ABORT, 'metric_input is append-only'); END;
CREATE TRIGGER parity_result_no_update BEFORE UPDATE ON parity_result
BEGIN SELECT RAISE(ABORT, 'parity_result is append-only'); END;
CREATE TRIGGER parity_result_no_delete BEFORE DELETE ON parity_result
BEGIN SELECT RAISE(ABORT, 'parity_result is append-only'); END;
