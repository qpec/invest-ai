-- schema/001_position_detail.sql — record-keeping companion to position (design 2026-07-10).
-- Rich per-position data from the eToro api_pull source. NEVER read by positions_advice /
-- the balance path (invariant 4 stays clean) — thesis/journal/reporting only.

CREATE TABLE position_detail (
  snapshot_id           INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
  symbol                TEXT NOT NULL,
  opened_at             TEXT,     -- earliest lot open date = "time invested"
  invested_native       REAL,     -- cost basis, native ccy
  invested_eur          REAL,
  unrealized_pnl_native REAL,
  unrealized_pnl_pct    REAL,
  current_rate          REAL,
  direction             TEXT,     -- buy | sell
  lot_count             INTEGER,  -- eToro lots collapsed into this row
  raw_json              TEXT,     -- full eToro payload for the symbol (all lots)
  PRIMARY KEY (snapshot_id, symbol)
);

CREATE TRIGGER position_detail_no_update BEFORE UPDATE ON position_detail
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER position_detail_no_delete BEFORE DELETE ON position_detail
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
