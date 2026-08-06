# Metric Evidence Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an append-only, source-aware ledger that can prove the current value, lineage, freshness, and operational health of every Scout metric.

**Architecture:** SQLite stores versioned definitions, immutable source observations, derived metric observations, lineage, policies, refresh runs, and parity results. A focused `agentcy.metric_ledger` module owns status and current-observation selection. Existing Scout reads remain unchanged until parity and integration tasks are green.

**Tech Stack:** Python 3.13, stdlib `sqlite3`, SQL migrations, pytest, existing systemd/outbox infrastructure.

---

## File map

- Create `agentcy/schema/004_metric_evidence_ledger.sql`: tables, constraints, append-only guards, and health views.
- Create `agentcy/metric_ledger.py`: typed statuses, append operations, current selection, and decision-readiness queries.
- Create `tests/test_metric_ledger_schema.py`: migration and immutability coverage.
- Create `tests/test_metric_ledger.py`: policy, lineage, current selection, and readiness behavior.
- Modify `agentcy/db.py`: narrow append helpers that delegate ledger writes through the existing SQLite door.
- Create `agentcy/metric_parity.py`: legacy-versus-ledger comparison and persistence.
- Create `tests/test_metric_parity.py`: tolerance, missingness, and state parity tests.
- Modify `stock-scout/webapp.py`: consume ledger health summaries behind a feature flag.
- Modify `deploy/systemd/*`: add daily SEC delta and weekly reconciliation jobs after the ledger foundation is proven.

### Task 1: Ledger schema

**Files:**
- Create: `agentcy/schema/004_metric_evidence_ledger.sql`
- Create: `tests/test_metric_ledger_schema.py`

- [ ] **Step 1: Write failing migration tests**

```python
from agentcy import db

TABLES = {
    "metric_definition", "source_observation", "metric_observation",
    "metric_input", "source_policy", "ledger_refresh_run", "parity_result",
}

def test_ledger_migration_creates_contract(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    found = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= found

def test_source_observation_is_append_only(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    # Insert the minimum valid fixture, then prove UPDATE and DELETE abort.
```

- [ ] **Step 2: Run the tests and confirm migration objects are missing**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_metric_ledger_schema.py -q`

Expected: failure because migration 004 and its tables do not exist.

- [ ] **Step 3: Add migration 004**

Create strict tables with foreign keys, enum `CHECK` constraints, uniqueness for idempotent appends, and `BEFORE UPDATE/DELETE` abort triggers on immutable evidence tables. Add `v_current_metric`, `v_stock_data_health`, and `v_metric_coverage` views. `v_current_metric` must rank admissible observations by status, policy priority, `as_of`, and `calculated_at` without mutating history.

- [ ] **Step 4: Run schema tests**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_metric_ledger_schema.py tests/test_db.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agentcy/schema/004_metric_evidence_ledger.sql tests/test_metric_ledger_schema.py
git commit -m "feat: add metric evidence ledger schema"
```

### Task 2: Append-only ledger API

**Files:**
- Create: `agentcy/metric_ledger.py`
- Modify: `agentcy/db.py`
- Create: `tests/test_metric_ledger.py`

- [ ] **Step 1: Write failing append and lineage tests**

```python
def test_metric_observation_retains_exact_inputs(ledger):
    definition = ledger.define_metric("owner_fcf_margin_pct", "v1", "%", required=True)
    revenue = ledger.append_source(
        ticker="ACME", source="sec", source_key="Revenue", value=100.0,
        unit="USD", period_end="2026-06-30", filed_at="2026-08-01T10:00:00Z",
        fetched_at="2026-08-01T11:00:00Z", payload_hash="revenue-v1")
    owner_fcf = ledger.append_source(
        ticker="ACME", source="sec", source_key="OwnerFCF", value=18.2,
        unit="USD", period_end="2026-06-30", filed_at="2026-08-01T10:00:00Z",
        fetched_at="2026-08-01T11:00:00Z", payload_hash="fcf-v1")
    observation = ledger.append_metric(
        definition_id=definition, ticker="ACME", value=18.2,
        status="FRESH", confidence=1.0, as_of="2026-06-30",
        calculated_at="2026-08-01T11:01:00Z",
        input_ids=[revenue, owner_fcf])
    assert ledger.input_ids(observation) == [revenue, owner_fcf]

def test_duplicate_source_payload_is_idempotent(ledger):
    row = dict(ticker="ACME", source="sec", source_key="Revenue", value=100.0,
               unit="USD", period_end="2026-06-30",
               filed_at="2026-08-01T10:00:00Z",
               fetched_at="2026-08-01T11:00:00Z", payload_hash="abc")
    first = ledger.append_source(**row)
    second = ledger.append_source(**row)
    assert second == first
```

- [ ] **Step 2: Verify the tests fail**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_metric_ledger.py -q`

Expected: import or attribute failure for `agentcy.metric_ledger`.

- [ ] **Step 3: Implement narrow typed operations**

Implement `MetricStatus`, `define_metric`, `append_source_observation`, `append_metric_observation`, `append_source_policy`, `metric_inputs`, and transaction-safe refresh-run helpers. Validate aware UTC timestamps, finite numeric values, active metric definitions, and exact input ownership before inserting.

- [ ] **Step 4: Run focused tests**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_metric_ledger.py tests/test_db_append.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agentcy/metric_ledger.py agentcy/db.py tests/test_metric_ledger.py
git commit -m "feat: add append-only metric ledger API"
```

### Task 3: Freshness, source policy, and decision readiness

**Files:**
- Modify: `agentcy/metric_ledger.py`
- Modify: `tests/test_metric_ledger.py`

- [ ] **Step 1: Write failing policy tests**

```python
def test_required_conflict_blocks_decision_ready(ledger):
    ledger.seed_required_metric(status="CONFLICT")
    assert ledger.stock_health("ACME").decision_ready is False

def test_certified_vendor_fallback_is_selected(ledger):
    ledger.seed_missing_sec_and_valid_vendor_fallback(tolerance=0.02)
    current = ledger.current_metric("ACME", "owner_fcf_margin_pct")
    assert current.source_role == "fallback"
    assert current.status == "FRESH"

def test_expired_vendor_fallback_is_unverifiable(ledger):
    ledger.seed_expired_vendor_fallback()
    assert ledger.current_metric("ACME", "owner_fcf_margin_pct").status == "UNVERIFIABLE"
```

- [ ] **Step 2: Verify failures**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_metric_ledger.py -q`

Expected: selection/readiness assertions fail.

- [ ] **Step 3: Implement selection and readiness**

Add `current_metric`, `stock_health`, and `metric_coverage`. Required metric states other than `FRESH` block readiness. Optional gaps reduce `confidence` but do not block. Vendor observations are admissible only under an active certified policy and remain labelled `fallback`.

- [ ] **Step 4: Run focused and schema tests**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_metric_ledger.py tests/test_metric_ledger_schema.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agentcy/metric_ledger.py tests/test_metric_ledger.py
git commit -m "feat: enforce metric freshness and source policy"
```

### Task 4: Legacy parity recorder

**Files:**
- Create: `agentcy/metric_parity.py`
- Create: `tests/test_metric_parity.py`

- [ ] **Step 1: Write failing parity tests**

```python
def test_numeric_values_within_tolerance_pass():
    result = compare(legacy_value=10.0, ledger_value=10.00001,
                     legacy_state="FRESH", ledger_state="FRESH", tolerance=1e-4)
    assert result.verdict == "PASS"

def test_missingness_or_state_mismatch_fails():
    assert compare(None, 10.0, "MISSING", "FRESH", 1e-4).verdict == "FAIL"
    assert compare(10.0, 10.0, "FRESH", "STALE", 1e-4).verdict == "FAIL"
```

- [ ] **Step 2: Run and confirm import failure**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_metric_parity.py -q`

- [ ] **Step 3: Implement deterministic comparison and persistence**

Create an immutable `ParityResult` dataclass, explicit missingness/state rules, absolute-plus-relative numeric tolerance, and `record_parity` using the ledger run and definition identifiers.

- [ ] **Step 4: Run tests and commit**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_metric_parity.py -q`

```bash
git add agentcy/metric_parity.py tests/test_metric_parity.py
git commit -m "feat: record legacy ledger parity"
```

### Task 5: Full verification for the foundation slice

**Files:**
- Modify: `docs/superpowers/specs/2026-08-06-metric-evidence-ledger-design.md` only if verified implementation constraints require clarification.

- [ ] **Step 1: Run the root suite**

Run: `/home/openclaw/.local/bin/uv run pytest -q`

Expected: all tests pass, with the baseline 1003 tests plus the new ledger tests.

- [ ] **Step 2: Run the scout suite**

Run: `cd stock-scout && /home/openclaw/.local/bin/uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Inspect migration and branch state**

Run: `git diff main HEAD --check && git status --short`

Expected: no whitespace errors and only intentional changes.

- [ ] **Step 4: Commit any verification-only documentation correction**

```bash
git add docs/superpowers/specs/2026-08-06-metric-evidence-ledger-design.md
git commit -m "docs: align metric ledger design with verified foundation"
```

## Subsequent independently testable plans

After this foundation is green, create separate execution plans for:

1. SEC delta ingestion, cursor atomicity, weekly full reconciliation, and certified vendor adapters.
2. Dual-write integration with current Scout bundles and the full-universe parity gate.
3. Feature-flagged scoring/monitor cutover.
4. Data-health dashboard, Telegram exception alerts, and systemd deployment units.
