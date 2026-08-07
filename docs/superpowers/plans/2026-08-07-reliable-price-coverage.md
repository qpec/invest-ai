# Reliable Price Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a resumable local price-evidence pipeline that unlocks at least 2,300 traced owner-FCF-yield values and improves reliable 26-metric coverage by at least 1.5 percentage points.

**Architecture:** Extend the existing append-only SQLite ledger with run-scoped market-price evidence and promotion views. Keep yfinance behind the repository's single fetch boundary, normalize batch results per symbol, resume refreshes from durable attempts, and export only a fully validated successful snapshot into the existing point-in-time Scout adapter. Derivation reuses the current Scout formula and adds exact source lineage instead of implementing a second yield formula.

**Tech Stack:** Python 3.13, SQLite migrations, pandas, yfinance 1.5.1, existing `agentcy.fetch.yf`, existing Stock Scout PIT/registry modules, pytest.

---

## File map

- Create `agentcy/schema/006_market_price_evidence.sql`: refresh runs, attempts, immutable price observations and promoted-current views.
- Create `agentcy/market_prices.py`: normalized price domain, append/read operations, freshness, promotion and resumable orchestration.
- Modify `agentcy/db.py`: exact-column helpers for the new tables.
- Modify `agentcy/fetch/yf.py`: chunked history call and strict per-symbol normalization including split events.
- Modify `agentcy/cli.py`: `market-data prices refresh/status` commands.
- Create `stock-scout/coverage.py`: deterministic full-universe coverage and lineage bridge using existing PIT and registry formulas.
- Modify `agentcy/metric_ledger.py`: reason-coded price metric write and source-lineage helpers.
- Create `tests/test_market_price_schema.py`, `tests/test_market_prices.py`, `tests/test_market_price_cli.py` and `stock-scout/tests/test_coverage.py`.

### Task 1: Append-only market-price evidence schema

**Files:**
- Create: `agentcy/schema/006_market_price_evidence.sql`
- Create: `tests/test_market_price_schema.py`

- [ ] **Step 1: Write failing schema tests**

Test that migration creates `market_price_refresh_run`, `market_price_attempt` and
`market_price_observation`; observation and attempt rows reject update/delete; exact
replay is unique; `v_current_market_price` reads only observations from the newest
successful promoted run.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_market_price_schema.py -q`

Expected: failure because migration 006 and its tables are absent.

- [ ] **Step 3: Implement migration 006**

Use run states `RUNNING`, `SUCCEEDED`, `DEGRADED`, `FAILED`; a `promoted` boolean may be
set only for a succeeded run. Attempt outcomes are `OK`, `NO_DATA`, `FAILED`,
`RATE_LIMITED`, `TERMINAL`. Price observations require positive raw/adjusted close and
positive split ratio when present. Unique replay key is
`(refresh_run_id, security_key, provider, provider_symbol, bar_date, payload_hash)`.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/test_market_price_schema.py tests/test_schema.py -q`

Commit: `feat: add market price evidence schema`

### Task 2: Strict Yahoo batch normalization

**Files:**
- Modify: `agentcy/fetch/yf.py`
- Create: `tests/test_yf_price_batch.py`

- [ ] **Step 1: Write failing adapter tests**

Inject a multi-index yfinance frame for two symbols. Assert each normalized frame has
exact columns `close`, `adj_close`, `dividend`, `split`, `currency`; one malformed ticker
appears in the returned failures without dropping its healthy peer. Cover non-positive
closes, missing currency, empty frames and reported split ratios.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_yf_price_batch.py -q`

Expected: import failure for `fetch_daily_bars_batch`.

- [ ] **Step 3: Implement one paced batch door**

Add `_raw_history_batch(symbols, period)` using `yf.download` with
`auto_adjust=False`, `actions=True`, `threads=False`, `group_by='ticker'` and no progress
output. `fetch_daily_bars_batch` calls it inside `_paced_call`, normalizes each symbol
independently and returns `(frames, failures)`. Do not fall back to a second network door.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/test_yf_price_batch.py tests/test_fetch_yf.py -q`

Commit: `feat: normalize yahoo price batches`

### Task 3: Resumable price refresh and promotion

**Files:**
- Create: `agentcy/market_prices.py`
- Modify: `agentcy/db.py`
- Create: `tests/test_market_prices.py`

- [ ] **Step 1: Write failing domain tests**

Cover deterministic payload hashing, idempotent append, queue order, chunk rollback,
resume skipping `OK`/`TERMINAL`, rate-limit degradation, freshness at 45 days, and failed
run non-promotion. Include a successful two-chunk run whose promoted view contains both
symbols.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_market_prices.py -q`

Expected: import failure for `agentcy.market_prices`.

- [ ] **Step 3: Add exact database helpers**

Add narrow append/start/finish/promote helpers with fixed allowlists. Promotion runs in a
transaction and rejects a run unless it is `SUCCEEDED` and every selected security has a
terminal attempt outcome.

- [ ] **Step 4: Implement the domain module**

Define `PriceObservation`, `RefreshSummary`, `normalize_frame`, `refresh`,
`latest_prices`, `freshness_status` and `export_grid`. Select `v_eligible_security`, use
aliases as provider symbols, process deterministic chunks, and retain last-good current
state when a run degrades or fails.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/test_market_prices.py tests/test_db.py -q`

Commit: `feat: refresh and promote local market prices`

### Task 4: CLI, status artifact and detached-safe completion

**Files:**
- Modify: `agentcy/cli.py`
- Create: `tests/test_market_price_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Test `market-data prices refresh --budget 20 --chunk-size 10`, explicit `--resume`, and
`market-data prices status --out report.json`. Verify atomic JSON output, exit 1 on a
degraded run, and a printed terminal summary for success and failure.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_market_price_cli.py -q`

Expected: parser rejects `market-data`.

- [ ] **Step 3: Wire the CLI**

Use the existing state directory and clock seams. Refresh opens/migrates the database and
passes only explicit parameters to `market_prices.refresh`. Status reports total eligible,
fresh, stale, missing, terminal, conflict, provider distribution and latest promoted run.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/test_market_price_cli.py tests/test_cli.py -q`

Commit: `feat: expose local market price refresh CLI`

### Task 5: Owner-FCF-yield lineage and coverage comparison

**Files:**
- Create: `stock-scout/coverage.py`
- Modify: `agentcy/metric_ledger.py`
- Create: `stock-scout/tests/test_coverage.py`
- Modify: `tests/test_metric_ledger.py`

- [ ] **Step 1: Write failing lineage tests**

With a small Company Facts payload and a raw price observation, assert the existing PIT
adapter produces the same yield as the coverage bridge; the ledger observation links the
price, owner-FCF and share observations. Cover `STALE_PRICE`, `MISSING_SHARES`,
`STALE_SHARES`, `UNRESOLVED_SPLIT`, `MISSING_OWNER_FCF` and `CONFLICT` with null values.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest stock-scout/tests/test_coverage.py tests/test_metric_ledger.py -q`

Expected: missing coverage bridge and reason-coded write API.

- [ ] **Step 3: Implement the narrow Company Facts bridge**

Reuse `pit.as_of_bundle` and `enrich.registry_metrics`. Materialize only the exact selected
owner-FCF and share facts into `source_observation`; append the selected price evidence;
write `owner_fcf_yield_pct` with formula version and all source IDs. Do not duplicate the
formula in agentcy.

- [ ] **Step 4: Implement deterministic coverage comparison**

Read eligible securities, cached Company Facts and the promoted price grid. Emit old/new
counts for all 26 metrics, gained/lost symbols, parity mismatches and release-gate
verdicts. Write JSON atomically under `var/scout/audit/`.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/pytest stock-scout/tests/test_coverage.py tests/test_metric_ledger.py -q`

Commit: `feat: derive traced owner fcf yield coverage`

### Task 6: Local full-universe run and release gates

**Files:**
- Local ignored artifacts under `/home/openclaw/projects/invest-ai/var/scout/` only.

- [ ] **Step 1: Run focused suites**

Run: `.venv/bin/pytest tests/test_market_price_schema.py tests/test_yf_price_batch.py tests/test_market_prices.py tests/test_market_price_cli.py stock-scout/tests/test_coverage.py -q`

- [ ] **Step 2: Run the complete suite**

Run: `.venv/bin/pytest -q`

- [ ] **Step 3: Run the resumable local refresh**

Use the durable state directory `/home/openclaw/projects/invest-ai/var/scout/agentcy-local-v2`
and the eligible security master. Persist the run ID and resume until every selected
security has an outcome. Never commit downloaded data.

- [ ] **Step 4: Generate and inspect release artifacts**

Write price status and coverage comparison JSON under
`/home/openclaw/projects/invest-ai/var/scout/audit/`. Verify ≥95% resolved prices, ≥2,300
fresh yields, ≥1.5 percentage-point total coverage gain, zero legacy parity mismatches and
complete source lineage.

- [ ] **Step 5: Check branch state**

Run: `git diff 765ad79 HEAD --check && git status --short`

Expected: no whitespace errors and no bulk artifacts in Git.
