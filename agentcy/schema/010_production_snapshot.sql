CREATE TABLE production_run (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('daily', 'weekly', 'manual')),
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'FAILED', 'VALIDATED', 'PUBLISHED')),
    source_commit TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    failure_stage TEXT,
    failure_reason TEXT
);

CREATE TABLE production_top_member (
    run_id TEXT NOT NULL REFERENCES production_run(run_id),
    security_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    score REAL NOT NULL,
    PRIMARY KEY (run_id, security_key),
    UNIQUE (run_id, rank)
);

CREATE TABLE production_thesis_evaluation (
    run_id TEXT NOT NULL REFERENCES production_run(run_id),
    security_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('CREATED', 'REFRESHED', 'REUSED', 'FAILED')),
    evaluated_at TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    thesis_version INTEGER CHECK (thesis_version IS NULL OR thesis_version > 0),
    PRIMARY KEY (run_id, security_key)
);

CREATE TABLE production_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE REFERENCES production_run(run_id),
    manifest_hash TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
    published_commit TEXT
);

CREATE UNIQUE INDEX one_active_production_snapshot
    ON production_snapshot(active) WHERE active = 1;

CREATE TRIGGER production_top_member_no_update
BEFORE UPDATE ON production_top_member
BEGIN SELECT RAISE(ABORT, 'production_top_member is append-only'); END;

CREATE TRIGGER production_top_member_no_delete
BEFORE DELETE ON production_top_member
BEGIN SELECT RAISE(ABORT, 'production_top_member is append-only'); END;

CREATE TRIGGER production_thesis_evaluation_no_update
BEFORE UPDATE ON production_thesis_evaluation
BEGIN SELECT RAISE(ABORT, 'production_thesis_evaluation is append-only'); END;

CREATE TRIGGER production_thesis_evaluation_no_delete
BEFORE DELETE ON production_thesis_evaluation
BEGIN SELECT RAISE(ABORT, 'production_thesis_evaluation is append-only'); END;

CREATE TRIGGER production_run_identity_guard
BEFORE UPDATE OF run_id, mode, source_commit, started_at ON production_run
BEGIN SELECT RAISE(ABORT, 'production_run identity is immutable'); END;

CREATE TRIGGER production_run_no_delete
BEFORE DELETE ON production_run
BEGIN SELECT RAISE(ABORT, 'production_run cannot be deleted'); END;

CREATE TRIGGER production_snapshot_identity_guard
BEFORE UPDATE OF snapshot_id, run_id, manifest_hash, artifact_path, created_at
ON production_snapshot
BEGIN SELECT RAISE(ABORT, 'production_snapshot identity is immutable'); END;

CREATE TRIGGER production_snapshot_no_delete
BEFORE DELETE ON production_snapshot
BEGIN SELECT RAISE(ABORT, 'production_snapshot cannot be deleted'); END;
