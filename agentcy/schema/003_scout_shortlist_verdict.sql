-- schema/003_scout_shortlist_verdict.sql - Scout Stage-2 review artifact (design
-- 2026-07-11-scout-stage2-qualitative-reviewer-design.md, Part A). NOT monitoring state:
-- nothing reads it on a schedule, no trigger/alert/thesis references it; a human reads it once
-- via `agentcy scout review render`. Append-only (invariant 1); one row per (ticker, axis)
-- verdict; a re-badge APPENDS a superseding row; v_scout_shortlist_verdict = latest per
-- (ticker, axis) via the v_universe_fetch idiom (schema/002).

CREATE TABLE scout_shortlist_verdict (
  ticker       TEXT NOT NULL,
  axis         TEXT NOT NULL CHECK (axis IN ('moat','mgmt','fad','tier')),
  value        TEXT NOT NULL,
  reason       TEXT,
  recorded_at  TEXT NOT NULL
);                                          -- re-badges APPEND; view resolves latest per (ticker,axis)
CREATE INDEX idx_scout_verdict ON scout_shortlist_verdict (ticker, axis, recorded_at);

-- Latest verdict per (ticker, axis); rowid breaks same-timestamp ties (the v_price idiom).
CREATE VIEW v_scout_shortlist_verdict AS
SELECT ticker, axis, value, reason, recorded_at
FROM (
  SELECT s.*, ROW_NUMBER() OVER (
    PARTITION BY ticker, axis ORDER BY recorded_at DESC, rowid DESC) AS rn
  FROM scout_shortlist_verdict s
) WHERE rn = 1;

CREATE TRIGGER scout_shortlist_verdict_no_update BEFORE UPDATE ON scout_shortlist_verdict
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER scout_shortlist_verdict_no_delete BEFORE DELETE ON scout_shortlist_verdict
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
