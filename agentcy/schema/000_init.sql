-- schema/000_init.sql — agentcy.db, migration 000.
-- Binding contract per docs/plans/2026-07-08-technology-architecture.md §4.
-- PRAGMAs (WAL, busy_timeout, foreign_keys) are set by agentcy/db.py at open.

------------------------------------------------------------------------------
-- APPEND-ONLY TABLES (tech-arch §4.1 first block; §4.2 trigger pairs below)
------------------------------------------------------------------------------

CREATE TABLE snapshot (
  snapshot_id       INTEGER PRIMARY KEY,
  as_of             TEXT NOT NULL,
  source            TEXT NOT NULL CHECK (source IN ('api_pull','manual_export','manual_entry')),
  cash_balance_eur  REAL NOT NULL,
  created_at        TEXT NOT NULL
);

CREATE TABLE position (
  snapshot_id     INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
  symbol          TEXT NOT NULL,
  yf_ticker       TEXT,                      -- NULL = non-mappable (MA-4)
  instrument_type TEXT NOT NULL CHECK (instrument_type IN ('stock','etf','crypto','copyportfolio','cash')),
  quantity        REAL NOT NULL,
  avg_open_price  REAL,                      -- record-keeping ONLY; absent from positions_advice (invariant 4)
  native_currency TEXT NOT NULL,
  mv_native       REAL NOT NULL,
  mv_eur          REAL NOT NULL,
  weight          REAL NOT NULL,
  leverage        REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (snapshot_id, symbol)
);                                            -- NO framework_status / thesis_id columns (§4.4)

CREATE TABLE designation (
  symbol           TEXT NOT NULL,
  framework_status TEXT NOT NULL CHECK (framework_status IN ('framework','backfill_pending','outside_framework')),
  valid_from       TEXT NOT NULL,
  journal_ref      INTEGER NOT NULL REFERENCES journal_entry(entry_id),
  PRIMARY KEY (symbol, valid_from)            -- latest valid_from wins (E.2)
);

CREATE TABLE external_flow (
  flow_id     INTEGER PRIMARY KEY,
  snapshot_id INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
  date        TEXT NOT NULL,
  amount_eur  REAL NOT NULL,
  direction   TEXT NOT NULL CHECK (direction IN ('deposit','withdrawal','dividend','other')),
  ask_ref     TEXT REFERENCES ask(ask_id)     -- MA-12 owner confirmation
);

CREATE TABLE symbol_map (
  symbol      TEXT NOT NULL,
  yf_ticker   TEXT NOT NULL,
  valid_from  TEXT NOT NULL,
  journal_ref INTEGER NOT NULL REFERENCES journal_entry(entry_id),
  PRIMARY KEY (symbol, valid_from)             -- latest wins
);

CREATE TABLE price_cache (
  yf_ticker  TEXT NOT NULL,                    -- FX pairs ({CUR}EUR=X) live here too
  bar_date   TEXT NOT NULL,
  close      REAL NOT NULL,
  adj_close  REAL NOT NULL,
  dividend   REAL NOT NULL DEFAULT 0.0,        -- feeds weekly receipts line (BUF-2)
  currency   TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  run_id     INTEGER REFERENCES run_log(run_id)
);                                             -- re-fetches APPEND; v_price = latest per (ticker, date)
CREATE INDEX idx_price_cache ON price_cache (yf_ticker, bar_date, fetched_at);

CREATE TABLE fundamentals_period (
  yf_ticker      TEXT NOT NULL,
  statement_type TEXT NOT NULL CHECK (statement_type IN ('income','balance','cashflow')),
  period_end     TEXT NOT NULL,
  payload_json   TEXT NOT NULL,
  fingerprint    TEXT NOT NULL,                -- new row only on unseen fingerprint; drives D.3 detection
  fetched_at     TEXT NOT NULL,
  run_id         INTEGER REFERENCES run_log(run_id),
  UNIQUE (yf_ticker, statement_type, period_end, fingerprint)
);
CREATE INDEX idx_fundamentals ON fundamentals_period (yf_ticker, statement_type, period_end);

CREATE TABLE shares_series (
  yf_ticker  TEXT NOT NULL,
  obs_date   TEXT NOT NULL,
  shares     REAL NOT NULL,
  fetched_at TEXT NOT NULL                     -- raw as-fetched; last-per-date dedup at READ
);
CREATE INDEX idx_shares ON shares_series (yf_ticker, obs_date, fetched_at);

CREATE TABLE officer_snapshot (
  yf_ticker     TEXT NOT NULL,
  officers_json TEXT NOT NULL,
  fingerprint   TEXT NOT NULL,
  fetched_at    TEXT NOT NULL                  -- B.2 tripwire (best-effort per MA-6)
);

CREATE TABLE earnings_calendar (
  yf_ticker     TEXT NOT NULL,
  expected_date TEXT NOT NULL,                 -- always labeled "calendar estimate" (MA-7); never triggers anything
  fetched_at    TEXT NOT NULL,
  run_id        INTEGER REFERENCES run_log(run_id)
);

CREATE TABLE thesis (
  thesis_id  TEXT PRIMARY KEY,                 -- 'TH-{TICKER}-{NNN}', immutable identity
  ticker     TEXT NOT NULL,
  origin     TEXT NOT NULL CHECK (origin IN ('gate','backfill')),
  created_at TEXT NOT NULL
);

CREATE TABLE thesis_version (
  thesis_id           TEXT NOT NULL REFERENCES thesis(thesis_id),
  version             INTEGER NOT NULL,
  business_model_2s   TEXT NOT NULL,           -- hard 2-sentence limit enforced in register.py
  moat_types_json     TEXT NOT NULL,           -- JSON list from {network_effects,switching_costs,cost_advantage,brand_trust,regulatory_barrier}, min 1
  moat_evidence       TEXT NOT NULL,
  owner_earnings_json TEXT NOT NULL,           -- pinned at version time: fcf_ttm, sbc_ttm, owner_fcf_ttm, per_share, margin + fetched_at stamps (MA-11)
  owner_earnings_narrative TEXT NOT NULL,
  anchor_metric       TEXT NOT NULL DEFAULT 'P_FCF_owner' CHECK (anchor_metric = 'P_FCF_owner'),  -- BUF-1: v1's only anchor
  value_at_purchase   REAL,                    -- NULL for origin=backfill (BUF-12)
  fair_band_low       REAL NOT NULL,
  fair_band_high      REAL NOT NULL,
  fair_band_mid       REAL GENERATED ALWAYS AS ((fair_band_low + fair_band_high) / 2.0) VIRTUAL,  -- MA-9
  denominator_note    TEXT,
  conviction          TEXT NOT NULL CHECK (conviction IN ('high','medium','low')),          -- FR9: owner-typed only
  mgmt_trust          TEXT NOT NULL CHECK (mgmt_trust IN ('trusted_owner_operator','trusted_professional','neutral','distrust')),
  mgmt_trust_note     TEXT,
  circle_fit          TEXT NOT NULL CHECK (circle_fit IN ('core','edge')),
  circle_fit_note     TEXT,
  time_horizon        TEXT NOT NULL CHECK (time_horizon = '10y_plus'),
  ten_year_statement  TEXT NOT NULL,
  status_buy_flag     INTEGER NOT NULL DEFAULT 0,
  status_buy_note     TEXT,
  diff_json           TEXT,                    -- per-field diff vs prior version; NULL for v1
  reason              TEXT,
  actor               TEXT NOT NULL,
  journal_ref         INTEGER NOT NULL REFERENCES journal_entry(entry_id),  -- invariant 2 as NOT NULL FK
  created_at          TEXT NOT NULL,
  PRIMARY KEY (thesis_id, version)             -- current = max(version)
);

CREATE TABLE thesis_status_log (
  log_id          INTEGER PRIMARY KEY,
  thesis_id       TEXT NOT NULL REFERENCES thesis(thesis_id),
  status          TEXT NOT NULL CHECK (status IN ('draft','intact','under_review','broken','retired')),
  changed_at      TEXT NOT NULL,
  cause           TEXT NOT NULL,
  cause_ref       TEXT,                        -- alert_id / journal entry_id / ask_id as text
  review_deadline TEXT                         -- set on under_review rows; pause arithmetic applied at READ
);                                             -- current status = latest row; A.2 validated in register.py
CREATE INDEX idx_thesis_status ON thesis_status_log (thesis_id, changed_at);

CREATE TABLE "trigger" (                       -- keyword table name: always quoted in SQL
  trigger_id         INTEGER PRIMARY KEY,
  thesis_id          TEXT NOT NULL REFERENCES thesis(thesis_id),
  introduced_version INTEGER NOT NULL,
  type               TEXT NOT NULL CHECK (type IN ('growth_floor','margin_erosion','balance_sheet_safety','dilution','owner_attested_event')),
  statement          TEXT NOT NULL,            -- owner's words, quoted verbatim in alerts (lint-exempt span)
  metric             TEXT,
  comparator         TEXT,
  threshold          REAL,
  moat_link          TEXT,                     -- moat_type or NULL; >=1 per thesis carries one (BUF-4)
  persistence        TEXT NOT NULL CHECK (persistence IN ('single_observation','2_consecutive_quarters','ttm')),
  check_method       TEXT NOT NULL CHECK (check_method IN ('automated','prompted')),
  data_source        TEXT NOT NULL CHECK (data_source IN ('yf_quarterly_statements','yf_shares_full','yf_officers','yf_calendar','owner_attestation')),
  cadence            TEXT NOT NULL CHECK (cadence IN ('weekly','event')),
  yes_means          TEXT CHECK (yes_means IN ('fire','pass')),  -- type-5 only: yes/no -> FIRE/PASS mapping stored at commit (tg-spec §3.2)
  retired_at         TEXT                      -- the SOLE column-guarded UPDATE; loosening = retire + new row
);                                             -- NO last_checked/last_result/fired_at: state derived from trigger_check (§4.4)
CREATE INDEX idx_trigger_thesis ON "trigger" (thesis_id);

CREATE TABLE trigger_check (
  check_id       INTEGER PRIMARY KEY,
  trigger_id     INTEGER NOT NULL REFERENCES "trigger"(trigger_id),
  run_id         INTEGER NOT NULL REFERENCES run_log(run_id),
  checked_at     TEXT NOT NULL,
  result         TEXT NOT NULL CHECK (result IN ('PASS','FIRE','STALE','BOOTSTRAPPING','UNVERIFIABLE')),
  observed_value REAL,
  headroom       REAL,
  evaluable_from TEXT                          -- BOOTSTRAPPING: date the trigger becomes evaluable (MA-1)
);
CREATE INDEX idx_trigger_check ON trigger_check (trigger_id, checked_at);

CREATE TABLE journal_entry (                   -- full F.1 schema; NO grade columns
  entry_id               INTEGER PRIMARY KEY,
  ts                     TEXT NOT NULL,
  decision_type          TEXT NOT NULL CHECK (decision_type IN
    ('buy','add_to_position','trim','sell','hold_after_review','advice_rejected','alert_ignored',
     'gate_verdict','trigger_resolution','thesis_revision','config_or_designation')),
  decision_subtype       TEXT,                 -- gate_verdict: pass|watch|buy_ready · trigger_resolution: confirmed_broken|refuted|revised · config_or_designation: config_change|outside_framework
  ticker                 TEXT,
  thesis_ref             TEXT,                 -- 'thesis_id@version'
  system_recommendation  TEXT,                 -- verbatim at that moment
  owner_action           TEXT CHECK (owner_action IN ('followed','overridden','no_action')),
  reasoning_at_the_moment TEXT,                -- mandatory for owner-initiated types (journal.py enforces)
  expectation_and_falsifier TEXT,              -- buy/add default: thesis_id@version reference (F5)
  review_horizon         TEXT,                 -- default +1y; 'too_early' re-queues one horizon
  inputs_ref             INTEGER REFERENCES run_log(run_id),  -- RunLog pin
  process                TEXT CHECK (process IN ('followed','deviated')),
  process_deviation_note TEXT,
  emotional_note         TEXT,
  ask_ref                TEXT REFERENCES ask(ask_id),
  actor                  TEXT NOT NULL,
  CHECK (process IS NOT 'deviated' OR process_deviation_note IS NOT NULL)
);

CREATE TABLE journal_grade (                   -- grading appends, never mutates (F.1)
  grade_id      INTEGER PRIMARY KEY,
  entry_id      INTEGER NOT NULL REFERENCES journal_entry(entry_id),
  graded_at     TEXT NOT NULL,
  outcome_grade TEXT NOT NULL CHECK (outcome_grade IN ('good','neutral','bad','too_early')),
  note          TEXT
);

CREATE TABLE report (                          -- G.5 archive index
  report_id      INTEGER PRIMARY KEY,
  run_id         INTEGER NOT NULL REFERENCES run_log(run_id),
  type           TEXT NOT NULL CHECK (type IN ('daily','weekly','quarterly','alert','event','gate')),
  generated_at   TEXT NOT NULL,
  period         TEXT NOT NULL,
  freshness_json TEXT NOT NULL,
  content_md     TEXT NOT NULL,
  archive_path   TEXT NOT NULL,
  git_sha        TEXT                          -- NULL when commit failed/pending; write-once at insert (commit precedes insert)
);

CREATE TABLE config (
  key         TEXT NOT NULL,
  value       TEXT NOT NULL,
  valid_from  TEXT NOT NULL,
  journal_ref INTEGER NOT NULL REFERENCES journal_entry(entry_id),  -- unjournaled change = FK violation (§9)
  PRIMARY KEY (key, valid_from)                -- current = latest per key
);

CREATE TABLE absence_event (                   -- D.6 pause windows DERIVED at read (§4.4 pattern)
  event_id    INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('on','off')),
  at          TEXT NOT NULL,
  planned_end TEXT,                            -- NULL = open-ended ('until I resume'); window = [at, min(next off.at, planned_end))
  journal_ref INTEGER NOT NULL REFERENCES journal_entry(entry_id)
);

CREATE TABLE study_note (                      -- F.3 free-text destinations
  note_id INTEGER PRIMARY KEY,
  ts      TEXT NOT NULL,
  kind    TEXT NOT NULL CHECK (kind IN ('circle_note','restudy_response')),
  text    TEXT NOT NULL,
  ask_ref TEXT REFERENCES ask(ask_id)
);

CREATE TABLE event (                           -- D.3 event identity; RunLog key = yf_ticker + detected_at
  event_id      INTEGER PRIMARY KEY,
  yf_ticker     TEXT NOT NULL,
  source        TEXT NOT NULL CHECK (source IN ('fingerprint','owner','officer_diff')),
  kind          TEXT NOT NULL CHECK (kind IN ('earnings','filing','mgmt','other')),
  note          TEXT,
  detected_at   TEXT NOT NULL,
  detected_late INTEGER NOT NULL DEFAULT 0,
  run_id        INTEGER REFERENCES run_log(run_id)
);

CREATE TABLE schema_migration (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  sha256     TEXT NOT NULL
);

------------------------------------------------------------------------------
-- OPERATIONAL TABLES (column-guarded; identity/history immutable)
------------------------------------------------------------------------------

CREATE TABLE run_log (
  run_id        INTEGER PRIMARY KEY,
  run_type      TEXT NOT NULL CHECK (run_type IN ('daily','weekly','quarterly','event','backup','gate','scout','snapshot','desk')),
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

CREATE TABLE ask (                             -- D.5 first-class ask objects
  ask_id           TEXT PRIMARY KEY,           -- '<K><seq>', e.g. 'A238'
  kind             TEXT NOT NULL CHECK (kind IN ('A','Q','R','F','V','N')),
  seq              INTEGER NOT NULL,
  created_at       TEXT NOT NULL,
  prompt           TEXT NOT NULL,
  options_json     TEXT NOT NULL,              -- enumerated option set; '[]' for pure free-text asks
  expects_freetext INTEGER NOT NULL DEFAULT 0,
  thesis_ref       TEXT,
  trigger_ref      INTEGER REFERENCES "trigger"(trigger_id),
  alert_ref        INTEGER REFERENCES alert(alert_id),
  deadline         TEXT,                       -- base deadline; 'frozen' is DERIVED via clock.effective_deadline
  run_id           INTEGER REFERENCES run_log(run_id),
  -- updatable state (exactly these four, tech-arch §4.1):
  status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','reprompted','answered','unanswered')),
  answer_json      TEXT,
  answered_at      TEXT,
  tg_message_id    INTEGER,
  UNIQUE (kind, seq)
);

CREATE TABLE alert (                           -- one row per fired trigger; storm = shared storm_key + shared deadline (B.3.5)
  alert_id               INTEGER PRIMARY KEY,
  thesis_id              TEXT NOT NULL REFERENCES thesis(thesis_id),
  trigger_id             INTEGER NOT NULL REFERENCES "trigger"(trigger_id),
  run_id                 INTEGER NOT NULL REFERENCES run_log(run_id),
  storm_key              TEXT,
  created_at             TEXT NOT NULL,
  deadline               TEXT NOT NULL,        -- created_at + alert_decision_days; pause arithmetic at READ
  -- updatable resolution state:
  status                 TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','confirmed_broken','refuted','ignored')),
  resolved_at            TEXT,
  resolution_journal_ref INTEGER REFERENCES journal_entry(entry_id)
);

CREATE TABLE outbox (                          -- durable queue (§5.4); jobs enqueue, only the daemon delivers
  outbox_id         INTEGER PRIMARY KEY,
  dedupe_key        TEXT NOT NULL UNIQUE,      -- scheduled: '{run_type}:{scheduled_for}:{section}[#a{n}]' · event: 'event:{ticker}:{detected_at}:{section}' · alert: 'alert:{alert_id}'
  kind              TEXT NOT NULL CHECK (kind IN ('daily','weekly_msg','weekly_doc','quarterly_msg','quarterly_doc','alert','event','ask','notice')),
  created_at        TEXT NOT NULL,
  run_id            INTEGER REFERENCES run_log(run_id),
  artifact_ref      INTEGER REFERENCES report(report_id),
  ask_ref           TEXT REFERENCES ask(ask_id),
  -- payload: supersedable ONLY while status='queued' (conditional guard below):
  payload_html      TEXT NOT NULL,
  document_path     TEXT,
  reply_markup_json TEXT,
  -- updatable delivery state:
  status            TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','collapsed')),
  attempts          INTEGER NOT NULL DEFAULT 0,
  next_attempt_at   TEXT,
  tg_message_id     INTEGER
);                                             -- alerts have NO dead-letter state: they retry until delivered
CREATE INDEX idx_outbox_status ON outbox (status, created_at);

CREATE TABLE watchlist_item (
  item_id      INTEGER PRIMARY KEY,
  ticker       TEXT NOT NULL,
  added_at     TEXT NOT NULL,
  idea_source  TEXT NOT NULL CHECK (idea_source IN ('own_research','scout_screen','reading','referral')),
  one_line_why TEXT NOT NULL,
  -- updatable stage state:
  stage        TEXT NOT NULL DEFAULT 'raw' CHECK (stage IN
    ('raw',                    -- C.1: zero automation; cap 10; 90-day expiry
     'gate_approved_waiting',  -- WATCH: one armed daily fair-entry check (C.6)
     'buy_ready_waiting',      -- BUY_READY awaiting execution; 30-day V-ask sweep (C.6)
     'expired',                -- 90-day raw expiry (RunLog, not journaled)
     'lapsed',                 -- 12-month approval expiry (C.6)
     'activated',              -- position appeared in a Snapshot
     'rejected')),             -- Gate PASS or advice_rejected
  stage_changed_at TEXT,
  thesis_ref   TEXT REFERENCES thesis(thesis_id)   -- set when the Gate creates the draft thesis
);

CREATE TABLE bot_state (
  id             INTEGER PRIMARY KEY CHECK (id = 1),
  last_update_id INTEGER NOT NULL DEFAULT 0    -- persisted in the SAME transaction as handle() (§5.2)
);

CREATE TABLE gate_session (                    -- resumable C.2-C.6 state
  session_id INTEGER PRIMARY KEY,
  ticker     TEXT NOT NULL,
  mode       TEXT NOT NULL CHECK (mode IN ('gate','backfill')),
  started_at TEXT NOT NULL,
  -- updatable state:
  step       TEXT NOT NULL DEFAULT 'circle',   -- circle|hell_no|dossier|judgment|drafting|verdict
  state_json TEXT NOT NULL DEFAULT '{}',
  status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','done','abandoned')),
  updated_at TEXT
);

CREATE TABLE study_state (                     -- single row: F.3 rotation pointer
  id                       INTEGER PRIMARY KEY CHECK (id = 1),
  last_restudied_thesis_id TEXT,
  mental_model_index       INTEGER NOT NULL DEFAULT 0,
  updated_at               TEXT
);

------------------------------------------------------------------------------
-- VIEWS
------------------------------------------------------------------------------

-- Latest fetch per (ticker, bar_date); rowid breaks same-timestamp ties.
CREATE VIEW v_price AS
SELECT yf_ticker, bar_date, close, adj_close, dividend, currency, fetched_at, run_id
FROM (
  SELECT p.*, ROW_NUMBER() OVER (
    PARTITION BY yf_ticker, bar_date ORDER BY fetched_at DESC, rowid DESC) AS rn
  FROM price_cache p
) WHERE rn = 1;

-- Invariant 4: the ONLY position read surface for mirror balance, jobs/daily|weekly|event, render/*.
CREATE VIEW positions_advice AS
SELECT snapshot_id, symbol, yf_ticker, instrument_type,
       quantity, native_currency, mv_native, mv_eur, weight, leverage
FROM position;                                 -- avg_open_price deliberately absent

------------------------------------------------------------------------------
-- APPEND-ONLY ENFORCEMENT (§4.2) — one pair per append-only table
------------------------------------------------------------------------------

CREATE TRIGGER snapshot_no_update BEFORE UPDATE ON snapshot BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER snapshot_no_delete BEFORE DELETE ON snapshot BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER position_no_update BEFORE UPDATE ON position BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER position_no_delete BEFORE DELETE ON position BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER designation_no_update BEFORE UPDATE ON designation BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER designation_no_delete BEFORE DELETE ON designation BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER external_flow_no_update BEFORE UPDATE ON external_flow BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER external_flow_no_delete BEFORE DELETE ON external_flow BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER symbol_map_no_update BEFORE UPDATE ON symbol_map BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER symbol_map_no_delete BEFORE DELETE ON symbol_map BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER price_cache_no_update BEFORE UPDATE ON price_cache BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER price_cache_no_delete BEFORE DELETE ON price_cache BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER fundamentals_period_no_update BEFORE UPDATE ON fundamentals_period BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER fundamentals_period_no_delete BEFORE DELETE ON fundamentals_period BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER shares_series_no_update BEFORE UPDATE ON shares_series BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER shares_series_no_delete BEFORE DELETE ON shares_series BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER officer_snapshot_no_update BEFORE UPDATE ON officer_snapshot BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER officer_snapshot_no_delete BEFORE DELETE ON officer_snapshot BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER earnings_calendar_no_update BEFORE UPDATE ON earnings_calendar BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER earnings_calendar_no_delete BEFORE DELETE ON earnings_calendar BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER thesis_no_update BEFORE UPDATE ON thesis BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER thesis_no_delete BEFORE DELETE ON thesis BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER thesis_version_no_update BEFORE UPDATE ON thesis_version BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER thesis_version_no_delete BEFORE DELETE ON thesis_version BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER thesis_status_log_no_update BEFORE UPDATE ON thesis_status_log BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER thesis_status_log_no_delete BEFORE DELETE ON thesis_status_log BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER trigger_check_no_update BEFORE UPDATE ON trigger_check BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER trigger_check_no_delete BEFORE DELETE ON trigger_check BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER journal_entry_no_update BEFORE UPDATE ON journal_entry BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER journal_entry_no_delete BEFORE DELETE ON journal_entry BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER journal_grade_no_update BEFORE UPDATE ON journal_grade BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER journal_grade_no_delete BEFORE DELETE ON journal_grade BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER report_no_update BEFORE UPDATE ON report BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER report_no_delete BEFORE DELETE ON report BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER config_no_update BEFORE UPDATE ON config BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER config_no_delete BEFORE DELETE ON config BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER absence_event_no_update BEFORE UPDATE ON absence_event BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER absence_event_no_delete BEFORE DELETE ON absence_event BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER study_note_no_update BEFORE UPDATE ON study_note BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER study_note_no_delete BEFORE DELETE ON study_note BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER event_no_update BEFORE UPDATE ON event BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER event_no_delete BEFORE DELETE ON event BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER schema_migration_no_update BEFORE UPDATE ON schema_migration BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER schema_migration_no_delete BEFORE DELETE ON schema_migration BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;

-- "trigger" table: definitions immutable, retired_at is the sole write-once UPDATE.
CREATE TRIGGER trigger_def_guard BEFORE UPDATE OF trigger_id, thesis_id, introduced_version, type, statement,
  metric, comparator, threshold, moat_link, persistence, check_method, data_source, cadence, yes_means
  ON "trigger" BEGIN SELECT RAISE(ABORT, 'trigger definitions immutable; loosening = retire + new row (A.3)'); END;
CREATE TRIGGER trigger_retire_once BEFORE UPDATE OF retired_at ON "trigger" WHEN OLD.retired_at IS NOT NULL
  BEGIN SELECT RAISE(ABORT, 'retired_at is write-once'); END;
CREATE TRIGGER trigger_no_delete BEFORE DELETE ON "trigger" BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;

------------------------------------------------------------------------------
-- COLUMN GUARDS on operational tables (identity/history immutable; no deletes)
------------------------------------------------------------------------------

CREATE TRIGGER run_log_guard BEFORE UPDATE OF run_id, run_type, scheduled_for, created_at ON run_log
  BEGIN SELECT RAISE(ABORT, 'column guard: run_log identity immutable'); END;
CREATE TRIGGER run_log_no_delete BEFORE DELETE ON run_log BEGIN SELECT RAISE(ABORT, 'no delete (NFR4)'); END;

CREATE TRIGGER ask_guard BEFORE UPDATE OF ask_id, kind, seq, created_at, prompt, options_json,
  expects_freetext, thesis_ref, trigger_ref, alert_ref, deadline, run_id ON ask
  BEGIN SELECT RAISE(ABORT, 'column guard: ask identity immutable'); END;
CREATE TRIGGER ask_no_delete BEFORE DELETE ON ask BEGIN SELECT RAISE(ABORT, 'no delete (NFR4)'); END;

CREATE TRIGGER alert_guard BEFORE UPDATE OF alert_id, thesis_id, trigger_id, run_id, storm_key, created_at, deadline ON alert
  BEGIN SELECT RAISE(ABORT, 'column guard: alert identity immutable'); END;
CREATE TRIGGER alert_no_delete BEFORE DELETE ON alert BEGIN SELECT RAISE(ABORT, 'no delete (NFR4)'); END;

CREATE TRIGGER outbox_guard BEFORE UPDATE OF outbox_id, dedupe_key, kind, created_at, run_id, artifact_ref, ask_ref ON outbox
  BEGIN SELECT RAISE(ABORT, 'column guard: outbox identity immutable'); END;
CREATE TRIGGER outbox_payload_guard BEFORE UPDATE OF payload_html, document_path, reply_markup_json ON outbox
  WHEN OLD.status <> 'queued'
  BEGIN SELECT RAISE(ABORT, 'outbox payload supersedable only while queued (§5.4)'); END;
CREATE TRIGGER outbox_no_delete BEFORE DELETE ON outbox BEGIN SELECT RAISE(ABORT, 'no delete (NFR4)'); END;

CREATE TRIGGER watchlist_item_guard BEFORE UPDATE OF item_id, ticker, added_at, idea_source, one_line_why ON watchlist_item
  BEGIN SELECT RAISE(ABORT, 'column guard: watchlist identity immutable'); END;
CREATE TRIGGER watchlist_item_no_delete BEFORE DELETE ON watchlist_item BEGIN SELECT RAISE(ABORT, 'no delete (NFR4)'); END;

CREATE TRIGGER bot_state_guard BEFORE UPDATE OF id ON bot_state
  BEGIN SELECT RAISE(ABORT, 'column guard: bot_state id immutable'); END;
CREATE TRIGGER bot_state_no_delete BEFORE DELETE ON bot_state BEGIN SELECT RAISE(ABORT, 'no delete'); END;

CREATE TRIGGER gate_session_guard BEFORE UPDATE OF session_id, ticker, mode, started_at ON gate_session
  BEGIN SELECT RAISE(ABORT, 'column guard: gate_session identity immutable'); END;
CREATE TRIGGER gate_session_no_delete BEFORE DELETE ON gate_session BEGIN SELECT RAISE(ABORT, 'no delete (NFR4)'); END;

CREATE TRIGGER study_state_guard BEFORE UPDATE OF id ON study_state
  BEGIN SELECT RAISE(ABORT, 'column guard: study_state id immutable'); END;
CREATE TRIGGER study_state_no_delete BEFORE DELETE ON study_state BEGIN SELECT RAISE(ABORT, 'no delete'); END;

------------------------------------------------------------------------------
-- BOOTSTRAP SEEDS (journal-FK pattern: journal entry FIRST, then referencing rows)
------------------------------------------------------------------------------

INSERT INTO journal_entry (entry_id, ts, decision_type, decision_subtype, reasoning_at_the_moment, actor) VALUES
 (1, '2026-07-08T00:00:00Z', 'config_or_designation', 'config_change',
  'Bootstrap 2026-07-08: E.3 balance defaults and operational config seeded as owner-approved.', 'owner'),
 (2, '2026-07-09T00:00:00Z', 'config_or_designation', 'config_change',
  'S1: certifi (MPL-2.0) standing license exception, owner-signed, covering the whole venv (tech-arch §2.2) — named-exception list entry one.', 'owner'),
 (3, '2026-07-09T00:00:00Z', 'config_or_designation', 'config_change',
  'S0: 7-day daily cadence accepted — full G.1 letter per US market day, two-line pulse Sun/Mon (tech-arch §1.4/§15).', 'owner'),
 (4, '2026-07-09T00:00:00Z', 'config_or_designation', 'config_change',
  'S2: external content-free dead-man ping ENABLED from day one — the system''s sole third-party touchpoint (tech-arch §11.5/§15); service chosen at install.', 'owner'),
 (5, '2026-07-09T00:00:00Z', 'config_or_designation', 'config_change',
  'S3: second-disk backup target /mnt/agentcy-backup confirmed (tech-arch §11.6/§15).', 'owner');

INSERT INTO config (key, value, valid_from, journal_ref) VALUES
 ('cash_band_low_pct',           '5',           '2026-07-08T00:00:00Z', 1),
 ('cash_band_high_pct',          '15',          '2026-07-08T00:00:00Z', 1),
 ('max_position_soft_pct',       '15',          '2026-07-08T00:00:00Z', 1),
 ('max_position_hard_pct',       '20',          '2026-07-08T00:00:00Z', 1),
 ('max_cluster_weight_pct',      '40',          '2026-07-08T00:00:00Z', 1),
 ('min_effective_bets',          '4.0',         '2026-07-08T00:00:00Z', 1),
 ('position_count_low',          '10',          '2026-07-08T00:00:00Z', 1),
 ('position_count_high',         '15',          '2026-07-08T00:00:00Z', 1),
 ('outside_framework_cap_pct',   '10',          '2026-07-08T00:00:00Z', 1),
 ('buy_opportunity_discount_pct','20',          '2026-07-08T00:00:00Z', 1),
 ('alert_decision_days',         '7',           '2026-07-08T00:00:00Z', 1),
 ('initial_weight_high_pct',     '10',          '2026-07-08T00:00:00Z', 1),
 ('initial_weight_medium_pct',   '6',           '2026-07-08T00:00:00Z', 1),
 ('initial_weight_low_pct',      '3',           '2026-07-08T00:00:00Z', 1),
 ('correlation_threshold',       '0.7',         '2026-07-08T00:00:00Z', 1),
 ('daily_letter_mode',           'always',      '2026-07-08T00:00:00Z', 1),
 ('benchmark',                   'SP500TR_EUR', '2026-07-08T00:00:00Z', 1),
 ('universe_pin_sha',            '',            '2026-07-08T00:00:00Z', 1),
 ('screen_recipe',               'qv',          '2026-07-08T00:00:00Z', 1),
 ('license_exceptions',          'certifi:MPL-2.0', '2026-07-09T00:00:00Z', 2),
 ('deadman_ping_url',            '',            '2026-07-09T00:00:00Z', 4);

INSERT INTO bot_state (id, last_update_id) VALUES (1, 0);
INSERT INTO study_state (id, last_restudied_thesis_id, mental_model_index, updated_at)
VALUES (1, NULL, 0, '2026-07-09T00:00:00Z');
