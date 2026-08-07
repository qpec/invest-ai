CREATE TABLE sec_statement_import_run (
    import_run_id INTEGER PRIMARY KEY,
    archive_name TEXT NOT NULL,
    archive_hash TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    fact_count INTEGER CHECK (fact_count IS NULL OR fact_count >= 0),
    failure_summary TEXT,
    UNIQUE (archive_name, archive_hash)
);

CREATE TABLE sec_statement_fact (
    fact_id INTEGER PRIMARY KEY,
    import_run_id INTEGER NOT NULL REFERENCES sec_statement_import_run(import_run_id),
    accession TEXT NOT NULL,
    cik TEXT NOT NULL,
    filed_at TEXT NOT NULL,
    form TEXT NOT NULL,
    report_period TEXT NOT NULL,
    statement TEXT NOT NULL CHECK (statement IN ('BS', 'IS', 'CF', 'EQ', 'CI', 'CP')),
    taxonomy_tag TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    canonical_label TEXT NOT NULL,
    period_end TEXT NOT NULL,
    quarters INTEGER NOT NULL CHECK (quarters IN (0, 1, 4)),
    unit TEXT NOT NULL,
    value REAL NOT NULL,
    source_hash TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (import_run_id, accession, taxonomy_tag, taxonomy_version, canonical_label,
            period_end, quarters, unit, value)
);

CREATE INDEX idx_sec_statement_fact_lookup
    ON sec_statement_fact(cik, filed_at, canonical_label, period_end, quarters);

CREATE TRIGGER sec_statement_fact_no_update
BEFORE UPDATE ON sec_statement_fact
BEGIN SELECT RAISE(ABORT, 'sec_statement_fact is append-only'); END;

CREATE TRIGGER sec_statement_fact_no_delete
BEFORE DELETE ON sec_statement_fact
BEGIN SELECT RAISE(ABORT, 'sec_statement_fact is append-only'); END;

CREATE TRIGGER sec_statement_import_run_no_delete
BEFORE DELETE ON sec_statement_import_run
BEGIN SELECT RAISE(ABORT, 'sec_statement_import_run cannot be deleted'); END;
