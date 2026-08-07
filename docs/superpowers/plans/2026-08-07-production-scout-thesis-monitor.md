# Production Scout, Thesis and Portfolio Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one local, atomic production job that refreshes the Scout top 1%, evaluates draft-thesis freshness, monitors every ratified thesis and publishes one privacy-safe GitHub Pages snapshot.

**Architecture:** Add append-only production-run and thesis-evaluation state to the existing SQLite database, then orchestrate the existing price, filing, scoring, thesis, monitor and site components through a small production module. The site remains static and `bot/site` receives only a validated public projection plus a manifest; failed runs leave the last known good snapshot untouched.

**Tech Stack:** Python 3.13, SQLite, pytest, existing Scout CLIs, static HTML/JSON, Bash, GitHub Pages classic branch deployment.

**Execution status (2026-08-07):** Tasks 1–6 are implemented. The real local
dry run proves the 5,763 eligible-security projection, 4,768 scoreable names,
48 top members, atomic artifact creation and the privacy/site gates. Final live
publication is deliberately blocked by `thesis_evaluations_passed`: this
container has no accepted drafts for the 48 current top names and no
owner-approved thesis-writing model is configured. OpenAI's approved-model list
is empty by existing Gate policy and the Claude CLI is absent. The release gate
therefore refuses to label those drafts current or push them to Pages.

---

## File map

- Create `agentcy/schema/010_production_snapshot.sql`: append-only production runs, top-1% membership, thesis evaluations and snapshot promotion.
- Create `agentcy/production.py`: production state writes, release validation and atomic promotion.
- Modify `agentcy/db.py`: checked insert helpers for the new tables.
- Create `tests/test_production_schema.py`: schema, immutability and promotion tests.
- Modify `stock-scout/thesis.py`: deterministic research fingerprints and per-candidate evaluation results.
- Modify `stock-scout/tests/test_thesis_engine.py`: freshness/reuse/refresh tests.
- Create `stock-scout/production.py`: end-to-end orchestrator and CLI.
- Create `stock-scout/tests/test_production.py`: stage ordering, failure and retry tests.
- Modify `stock-scout/webapp.py`: one snapshot identity, combined portfolio-monitor projection and public allowlist.
- Modify `stock-scout/tests/test_webapp.py`: website structure, disclaimer and privacy tests.
- Create `deploy/local/scout-production.sh`: durable local wrapper, lock and Git publisher.
- Create `deploy/local/scout-production.env.example`: explicit local paths and branch settings.
- Create `deploy/systemd/scout-production@.service`: one templated local production service.
- Create `deploy/systemd/scout-production-daily.timer`: trading-day schedule.
- Create `deploy/systemd/scout-production-weekly.timer`: weekly deep schedule.
- Modify `deploy/scout/publish.sh`: mark the box publisher retired after local cutover.
- Modify `README.md`: production run, dry-run, scheduling, rollback and cutover instructions.

### Task 1: Persist immutable production snapshots

**Files:**
- Create: `agentcy/schema/010_production_snapshot.sql`
- Modify: `agentcy/db.py`
- Create: `tests/test_production_schema.py`

- [ ] **Step 1: Write the failing schema test**

```python
def test_production_schema_is_append_only_and_has_one_active_snapshot(tmp_path):
    conn = migrated_db(tmp_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"production_run", "production_top_member",
            "production_thesis_evaluation", "production_snapshot"} <= tables
```

Add tests that insert two snapshots, promote the second, assert only the second
is active, and assert updates/deletes of membership and evaluation rows abort.

- [ ] **Step 2: Run the schema test and verify failure**

Run: `pytest -q tests/test_production_schema.py`

Expected: FAIL because migration 010 and its tables do not exist.

- [ ] **Step 3: Add migration 010**

Define:

```sql
CREATE TABLE production_run (
  run_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL CHECK (mode IN ('daily','weekly','manual')),
  status TEXT NOT NULL CHECK (status IN ('RUNNING','FAILED','VALIDATED','PUBLISHED')),
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
  PRIMARY KEY (run_id, security_key)
);

CREATE TABLE production_thesis_evaluation (
  run_id TEXT NOT NULL REFERENCES production_run(run_id),
  security_key TEXT NOT NULL,
  symbol TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('CREATED','REFRESHED','REUSED','FAILED')),
  evaluated_at TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  thesis_version INTEGER,
  PRIMARY KEY (run_id, security_key)
);

CREATE TABLE production_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE REFERENCES production_run(run_id),
  manifest_hash TEXT NOT NULL,
  artifact_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0,1)),
  published_commit TEXT
);

CREATE UNIQUE INDEX one_active_production_snapshot
ON production_snapshot(active) WHERE active=1;
```

Add no-delete and immutable-row triggers following migrations 004–009. Permit
only explicit run status/failure fields and snapshot `active`/`published_commit`
to change through guarded transitions.

- [ ] **Step 4: Add checked database helpers**

Add `_PRODUCTION_*_COLS` sets and `insert_production_run`,
`insert_production_top_member`, `insert_production_thesis_evaluation` and
`insert_production_snapshot` to `agentcy/db.py`, using the existing `_checked`
and `_insert` helpers.

- [ ] **Step 5: Run focused and migration tests**

Run: `pytest -q tests/test_production_schema.py tests/test_schema.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agentcy/schema/010_production_snapshot.sql agentcy/db.py tests/test_production_schema.py
git commit -m "feat: persist production snapshot runs"
```

### Task 2: Implement production state and release gates

**Files:**
- Create: `agentcy/production.py`
- Create: `tests/test_production.py`

- [ ] **Step 1: Write failing state-machine tests**

Cover these exact behaviours:

```python
def test_validate_requires_exact_top_fraction(): ...
def test_validate_requires_monitor_result_for_every_committed_thesis(): ...
def test_validate_rejects_mixed_snapshot_ids(): ...
def test_validate_rejects_private_public_fields(): ...
def test_failed_run_cannot_promote(): ...
def test_promotion_deactivates_previous_snapshot_atomically(): ...
```

Use the prohibited public fields:

```python
PRIVATE_FIELDS = frozenset({
    "quantity", "shares", "cost_basis", "average_price",
    "market_value", "account_id", "account_name",
})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q tests/test_production.py`

Expected: FAIL because `agentcy.production` does not exist.

- [ ] **Step 3: Implement deterministic validation**

Create dataclasses `ReleaseInput` and `ReleaseResult`. Implement
`validate_release(value)` with checks named:

```python
checks = {
    "top_fraction_exact": actual_top == max(1, math.ceil(eligible * 0.01)),
    "all_committed_monitored": committed_symbols == monitored_symbols,
    "single_snapshot": snapshot_ids == {value.snapshot_id},
    "public_fields_safe": not find_private_fields(value.public_model),
    "site_complete": value.index_exists and value.manifest_exists,
    "data_quality_passed": value.data_quality_passed,
}
```

Return all failed check names and never mutate state during validation.

- [ ] **Step 4: Implement transition and promotion helpers**

Implement `start_run`, `fail_run`, `validate_run`, `stage_snapshot`,
`promote_snapshot` and `record_published_commit`. `promote_snapshot` must use
`BEGIN IMMEDIATE`, reject non-`VALIDATED` runs, clear the previous active flag,
set the candidate active and commit once.

- [ ] **Step 5: Run focused tests**

Run: `pytest -q tests/test_production.py tests/test_production_schema.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agentcy/production.py tests/test_production.py
git commit -m "feat: validate and promote production snapshots"
```

### Task 3: Add top-1% thesis freshness evaluation

**Files:**
- Modify: `stock-scout/thesis.py`
- Modify: `stock-scout/tests/test_thesis_engine.py`

- [ ] **Step 1: Write failing fingerprint tests**

Add tests proving that `research_fingerprint(row, formula_version)` is stable
under dictionary ordering, changes when a scored input/accession/rank changes,
and ignores volatile rendering timestamps.

Add `evaluation_decision(previous, fingerprint, stale)` cases:

```python
assert evaluation_decision(None, "a", False) == ("CREATED", "NEW_TOP_MEMBER")
assert evaluation_decision("a", "a", False) == ("REUSED", "INPUTS_UNCHANGED")
assert evaluation_decision("a", "b", False) == ("REFRESHED", "INPUTS_CHANGED")
assert evaluation_decision("a", "a", True) == ("REFRESHED", "RESEARCH_STALE")
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest -q stock-scout/tests/test_thesis_engine.py -k 'fingerprint or evaluation_decision'`

Expected: FAIL because the functions are absent.

- [ ] **Step 3: Implement canonical fingerprinting**

Hash canonical JSON containing `security_key`, symbol, rank, score, scorecard
formula version, filing accession/hash inputs, price observation ID and metric
evidence IDs. Do not include `generated_at` or prose.

- [ ] **Step 4: Implement evaluation decisions without automatic ratification**

`CREATED` and `REFRESHED` may write/update only `theses/drafts/<symbol>/`.
`REUSED` records a new production evaluation without rewriting research files.
No path may write `theses/committed/`.

- [ ] **Step 5: Run the thesis suite**

Run: `pytest -q stock-scout/tests/test_thesis_engine.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add stock-scout/thesis.py stock-scout/tests/test_thesis_engine.py
git commit -m "feat: evaluate top thesis freshness"
```

### Task 4: Build the privacy-safe combined website projection

**Files:**
- Modify: `stock-scout/webapp.py`
- Modify: `stock-scout/tests/test_webapp.py`

- [ ] **Step 1: Write failing public-projection tests**

Add tests that construct a committed thesis containing all private fields and
assert none occur anywhere in serialized JSON. Assert the page model exposes
exactly three navigation sections: `scout`, `thesis`, `portfolio_monitor`.

Assert each portfolio row contains public thesis summary, optional target
weight, status, last/next monitoring time and trigger evidence. Assert the page
contains exactly:

```text
Illustratieve modelportefeuille, geen financieel advies.
```

Add a parametrized test that every disclaimer element contains at most one
sentence terminator.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest -q stock-scout/tests/test_webapp.py -k 'portfolio_monitor or disclaimer or private'`

Expected: FAIL against the current separate monitor tab/model.

- [ ] **Step 3: Add an allowlist serializer**

Create `public_portfolio_thesis(doc)` that constructs a fresh dictionary from
an explicit allowlist. Do not redact a copy after serialization. Include only
symbol, thesis version/summary, target weight, status, monitoring dates and
public trigger evidence.

- [ ] **Step 4: Merge the model and UI sections**

Replace separate portfolio/monitor presentation with
`model["portfolio_monitor"]`. Update template navigation and JavaScript to
render thesis and monitor information together per holding. Add `snapshot_id`
and `generated` once at model root and display them consistently in each area.

- [ ] **Step 5: Shorten all disclaimer copy**

Audit current demo/advice/disclaimer blocks and replace each disclaimer with at
most one short sentence. Keep ordinary explanatory UI copy separate from
disclaimer elements.

- [ ] **Step 6: Run webapp tests**

Run: `pytest -q stock-scout/tests/test_webapp.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add stock-scout/webapp.py stock-scout/tests/test_webapp.py
git commit -m "feat: publish combined portfolio monitor view"
```

### Task 5: Implement the end-to-end orchestrator

**Files:**
- Create: `stock-scout/production.py`
- Modify: `stock-scout/tests/test_production.py`

- [ ] **Step 1: Write failing orchestration tests**

Use injected stage callables and assert this order:

```python
[
  "refresh", "score", "select_top", "evaluate_theses", "monitor",
  "build_site", "validate", "promote", "publish",
]
```

Test daily, weekly and manual modes use this same path; weekly passes
`deep=True` to refresh and thesis evaluation. Test a failure at every stage
marks the run failed, skips all later stages and never calls promote/publish.
Test a publish failure leaves the promoted local snapshot retryable and a
second call publishes the identical manifest without recomputation.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q stock-scout/tests/test_production.py`

Expected: FAIL because `stock-scout/production.py` does not exist.

- [ ] **Step 3: Implement the orchestrator interfaces**

Define `ProductionPaths`, `ProductionConfig`, `StageResult` and
`ProductionOrchestrator`. Each stage returns structured counts, snapshot IDs
and artifact paths. Catch stage exceptions only at the orchestration boundary,
record `failure_stage` and `failure_reason`, then return non-zero.

- [ ] **Step 4: Connect existing components**

Adapters must invoke existing Python functions rather than shell parsing for:

- security/data/price refresh;
- scoring and `thesis.top_symbols`;
- Task 3 freshness evaluation;
- `monitor.run` over every committed thesis;
- `webapp.build_model` and `webapp.write_site`;
- Task 2 release validation and promotion.

The top denominator is the eligible screened set from the same run. Persist
each member and thesis evaluation before validation.

- [ ] **Step 5: Add CLI commands**

Support:

```text
python production.py run --mode daily|weekly|manual [paths...]
python production.py retry-publish --run-id <id> [paths...]
python production.py status --run-id <id> --json
```

`run` exits non-zero on any failed release gate. `retry-publish` verifies the
stored manifest hash before pushing.

- [ ] **Step 6: Run production and existing integration tests**

Run: `pytest -q stock-scout/tests/test_production.py stock-scout/tests/test_pipeline.py stock-scout/tests/test_thesis_engine.py stock-scout/tests/test_webapp.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add stock-scout/production.py stock-scout/tests/test_production.py
git commit -m "feat: orchestrate production scout thesis monitor run"
```

### Task 6: Add local publisher, schedules and single-scheduler cutover

**Files:**
- Create: `deploy/local/scout-production.sh`
- Create: `deploy/local/scout-production.env.example`
- Create: `deploy/systemd/scout-production@.service`
- Create: `deploy/systemd/scout-production-daily.timer`
- Create: `deploy/systemd/scout-production-weekly.timer`
- Modify: `deploy/scout/publish.sh`
- Create: `tests/test_production_deploy.py`

- [ ] **Step 1: Write failing deploy-contract tests**

Parse the wrapper and units and assert:

- no `/opt/stock-agentcy` or box state path occurs in local files;
- the wrapper uses `flock` and an explicit durable state path;
- daily and weekly timers call `scout-production@daily.service` and
  `scout-production@weekly.service` respectively;
- publisher only stages `docs/` and `production-manifest.json`;
- no secret appears in a remote URL or command line;
- the legacy publisher exits with a cutover guard when
  `SCOUT_LOCAL_PRODUCTION_ACTIVE=1`.

- [ ] **Step 2: Run test and verify failure**

Run: `pytest -q tests/test_production_deploy.py`

Expected: FAIL because local deployment files are absent.

- [ ] **Step 3: Implement the local wrapper**

Load required paths from an environment file, acquire a non-blocking `flock`,
run `stock-scout/production.py run`, clone/fetch the site repo into the durable
state directory, verify the manifest hash, copy only public artifacts, commit
as `scout-local` and push `bot/site` using `GIT_ASKPASS` or an existing secure
credential helper. Never embed a token in Git config or the remote URL.

- [ ] **Step 4: Add schedules**

The daily timer runs after US market close on weekdays and sets
`Unit=scout-production@daily.service`. The weekly timer runs Saturday and sets
`Unit=scout-production@weekly.service`. The template passes `%i` to the wrapper
as the run mode. It must set `NoNewPrivileges`, an explicit `WorkingDirectory`,
a durable `ReadWritePaths` boundary and terminal failure notification.

- [ ] **Step 5: Guard the legacy box publisher**

At the top of `deploy/scout/publish.sh`, refuse execution when the cutover flag
is enabled. Document that the flag is set only after a successful local dry run
and first validated publication.

- [ ] **Step 6: Run deploy tests**

Run: `pytest -q tests/test_production_deploy.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add deploy/local deploy/systemd/scout-production* deploy/scout/publish.sh tests/test_production_deploy.py
git commit -m "feat: schedule local production publication"
```

### Task 7: Document, dry-run and verify production readiness

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-07-production-scout-thesis-monitor.md`

- [ ] **Step 1: Document operator commands**

Add exact commands for environment setup, manual dry-run, daily/weekly modes,
status inspection, retry-publish, rollback and scheduler cutover. State that
GitHub Pages is read-only, private portfolio state stays local and paid vendors
remain inactive.

- [ ] **Step 2: Run the full automated suite**

Run: `pytest -q`

Expected: all tests PASS.

- [ ] **Step 3: Build a real local dry-run snapshot**

Run the manual production command against the durable local universe, SEC cache,
price database and thesis directory with publication disabled.

Expected evidence:

- exact eligible count and top-1% count;
- one evaluation row for every top member;
- one monitor result for every committed thesis;
- one snapshot ID in Scout, thesis and portfolio-monitor outputs;
- zero prohibited public fields;
- complete generated site and manifest;
- no `bot/site` push.

- [ ] **Step 4: Inspect the static site**

Serve the staged directory locally, verify all three sections on desktop-sized
and phone-sized viewports, then stop the server. Confirm the combined portfolio
monitor view and the one-sentence disclaimer.

- [ ] **Step 5: Run completion checks**

Run:

```bash
git diff --check
git status --short
git log --oneline --decorate -12
```

Expected: no whitespace errors and only intentionally generated local artifacts
outside Git.

- [ ] **Step 6: Mark plan tasks complete and commit documentation**

```bash
git add README.md docs/superpowers/plans/2026-08-07-production-scout-thesis-monitor.md
git commit -m "docs: operate local production scout"
```

- [ ] **Step 7: Stop before live publication if credentials or cutover authority are absent**

Report the dry-run evidence and exact blocker. A live `bot/site` push and timer
activation require an available secure Git credential and explicit confirmation
that the former box publisher has been disabled; never infer either from a
successful local build.
