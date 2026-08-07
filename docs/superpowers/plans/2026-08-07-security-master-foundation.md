# Security Master Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an append-only local security master that produces a trustworthy eligible-universe denominator and durable exclusion reasons before further metric coverage work.

**Architecture:** A new SQLite migration stores immutable security observations and source aliases, while `agentcy.security_master` owns deterministic classification and current-state reads. A focused CLI imports the existing universe CSV plus the SEC exchange map, writes a run-scoped snapshot, and emits a JSON audit report without changing Scout scoring.

**Tech Stack:** Python 3.13, stdlib `sqlite3`, `csv`, `json`, SQL migrations, pytest, existing `agentcy.db` migration door.

---

## File map

- Create `agentcy/schema/005_security_master.sql`: append-only observations, aliases, snapshots, and current/eligible views.
- Create `agentcy/security_master.py`: enums, conservative classification, stable keys, import and audit reads.
- Modify `agentcy/db.py`: narrow append helpers for the new tables.
- Modify `agentcy/cli.py`: add `security-master import` and `security-master audit` commands.
- Create `tests/test_security_master_schema.py`: migration, constraints, immutability, and view tests.
- Create `tests/test_security_master.py`: classification, identity, idempotency, and audit tests.
- Create `tests/test_security_master_cli.py`: CLI import/audit integration.

### Task 1: Append-only security-master schema

**Files:**
- Create: `agentcy/schema/005_security_master.sql`
- Create: `tests/test_security_master_schema.py`

- [ ] **Step 1: Write the failing migration contract**

```python
import pytest
from agentcy import db


def test_security_master_migration_creates_contract(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    found = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"security_master_run", "security_observation", "security_alias"} <= found


def test_security_observation_is_append_only(tmp_db):
    tmp_db.execute(
        "INSERT INTO security_master_run"
        " (source_vintage, started_at, finished_at, status, input_rows)"
        " VALUES ('2026-08-07', '2026-08-07T08:00:00Z',"
        " '2026-08-07T08:01:00Z', 'SUCCEEDED', 1)")
    run_id = tmp_db.execute("SELECT last_insert_rowid()").fetchone()[0]
    tmp_db.execute(
        "INSERT INTO security_observation"
        " (run_id, security_key, symbol, name, country, exchange, instrument_type,"
        "  eligibility, reason_code, source, source_hash, observed_at)"
        " VALUES (?, 'cik:1', 'AAA', 'Acme Inc', 'US', 'Nasdaq', 'ORDINARY_SHARE',"
        " 'ELIGIBLE', 'PRIMARY_ORDINARY_SHARE', 'sec', 'abc', '2026-08-07T08:00:00Z')",
        (run_id,),
    )
    with pytest.raises(Exception):
        tmp_db.execute("UPDATE security_observation SET symbol='BBB'")
    with pytest.raises(Exception):
        tmp_db.execute("DELETE FROM security_observation")
```

- [ ] **Step 2: Verify RED**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master_schema.py -q`

Expected: failure because migration 005 and its tables do not exist.

- [ ] **Step 3: Add migration 005**

Create strict tables with checks for run status, instrument type, eligibility, and reason
codes. `security_observation` is unique on `(run_id, source, symbol, exchange)` and
contains `security_key`, optional `cik`, identity fields, classification, source hash, and
observation time. `security_alias` stores provider symbol validity for a `security_key`.
Add no-update/no-delete triggers. Add `v_current_security` ranked by successful run and
observation ID, plus `v_eligible_security` filtering `eligibility='ELIGIBLE'`.

- [ ] **Step 4: Verify GREEN**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master_schema.py tests/test_schema.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agentcy/schema/005_security_master.sql tests/test_security_master_schema.py
git commit -m "feat: add append-only security master schema"
```

### Task 2: Conservative classification and stable identity

**Files:**
- Create: `agentcy/security_master.py`
- Create: `tests/test_security_master.py`

- [ ] **Step 1: Write failing pure-classification tests**

```python
from agentcy.security_master import Eligibility, InstrumentType, classify


def test_primary_sec_ordinary_share_is_eligible():
    result = classify(symbol="ACME", name="Acme Corporation", country="United States",
                      exchange="Nasdaq", cik="0000000001", sec_primary=True)
    assert result.instrument_type is InstrumentType.ORDINARY_SHARE
    assert result.eligibility is Eligibility.ELIGIBLE
    assert result.reason_code == "PRIMARY_ORDINARY_SHARE"


def test_closed_end_fund_is_ineligible():
    result = classify(symbol="FUND", name="Example Municipal Income Fund",
                      country="United States", exchange="NYSE", cik="0000000002",
                      sec_primary=True)
    assert result.instrument_type is InstrumentType.FUND
    assert result.eligibility is Eligibility.INELIGIBLE
    assert result.reason_code == "FUND"


def test_foreign_secondary_for_us_issuer_requires_review():
    result = classify(symbol="0AAA.L", name="Acme Corporation", country="United States",
                      exchange="LSE", cik=None, sec_primary=False)
    assert result.eligibility is Eligibility.REVIEW
    assert result.reason_code == "UNRESOLVED_SECONDARY_LISTING"
```

- [ ] **Step 2: Verify RED**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master.py -q`

Expected: import failure for `agentcy.security_master`.

- [ ] **Step 3: Implement the minimal classifier**

Add `InstrumentType`, `Eligibility`, and frozen `Classification`. Apply ordered,
conservative rules for debt, fund, warrant/unit, preferred-only, royalty trust,
SEC-primary ordinary shares, Amsterdam ordinary shares, unresolved US foreign listings,
and unknown instruments. Implement `security_key(cik, normalized_name, primary_symbol)`
using CIK first and a SHA-256 name key only when CIK is absent. Do not fuzzy-match names.

- [ ] **Step 4: Add boundary tests**

Cover `First Mortgage Bonds`, `Municipal Income Fund`, `Warrants`, `Units`, preferred
suffixes, operating-company names containing the word `Trust`, and Amsterdam ordinary
shares. Confirm uncertain cases become `REVIEW`, never silently eligible.

- [ ] **Step 5: Verify and commit**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master.py -q`

```bash
git add agentcy/security_master.py tests/test_security_master.py
git commit -m "feat: classify scout security eligibility"
```

### Task 3: Transactional import and audit reads

**Files:**
- Modify: `agentcy/db.py`
- Modify: `agentcy/security_master.py`
- Modify: `tests/test_security_master.py`

- [ ] **Step 1: Write failing import tests**

```python
def test_import_promotes_only_complete_run(tmp_db, universe_csv, sec_exchange_json):
    from agentcy.security_master import import_snapshot
    summary = import_snapshot(tmp_db, universe_csv, sec_exchange_json,
                              source_vintage="2026-08-07",
                              observed_at="2026-08-07T08:00:00Z")
    assert summary.input_rows == 4
    assert summary.eligible == 2
    assert summary.ineligible == 1
    assert summary.review == 1
    assert tmp_db.execute("SELECT COUNT(*) FROM v_current_security").fetchone()[0] == 4


def test_exact_snapshot_replay_is_idempotent(tmp_db, universe_csv, sec_exchange_json):
    from agentcy.security_master import import_snapshot
    first = import_snapshot(tmp_db, universe_csv, sec_exchange_json,
                            source_vintage="2026-08-07",
                            observed_at="2026-08-07T08:00:00Z")
    second = import_snapshot(tmp_db, universe_csv, sec_exchange_json,
                             source_vintage="2026-08-07",
                             observed_at="2026-08-07T08:00:00Z")
    assert second.run_id == first.run_id
```

- [ ] **Step 2: Verify RED**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master.py -q`

Expected: missing import API.

- [ ] **Step 3: Add narrow database helpers**

Add `append_security_master_run`, `finish_security_master_run`,
`append_security_observation`, and `append_security_alias`. Each helper validates an exact
column allowlist. Run replay resolves by `(source_vintage, input_hash)`.

- [ ] **Step 4: Implement import and audit summary**

Read CSV/JSON without network. Hash both inputs. Build SEC ticker-to-CIK and CIK-primary
maps. Classify each universe row, append aliases, and finish the run inside one
transaction. On failure, roll back observations and record no successful current state.
Return counts by eligibility, reason, exchange, and source.

- [ ] **Step 5: Verify and commit**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master.py tests/test_db.py -q`

```bash
git add agentcy/db.py agentcy/security_master.py tests/test_security_master.py
git commit -m "feat: import and audit security master snapshots"
```

### Task 4: Local CLI and machine-readable audit artifact

**Files:**
- Modify: `agentcy/cli.py`
- Create: `tests/test_security_master_cli.py`

- [ ] **Step 1: Write failing CLI integration tests**

```python
def test_security_master_import_prints_json(cli, state_dir, universe_csv,
                                            sec_exchange_json, capsys):
    rc = cli([
        "security-master", "import", "--universe", str(universe_csv),
        "--sec-exchange", str(sec_exchange_json), "--vintage", "2026-08-07",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["eligible"] == 2


def test_security_master_audit_writes_atomic_json(cli, state_dir, tmp_path):
    output = tmp_path / "security-master-audit.json"
    assert cli(["security-master", "audit", "--out", str(output)]) == 0
    assert json.loads(output.read_text())["schema_version"] == 1
```

- [ ] **Step 2: Verify RED**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master_cli.py -q`

Expected: parser rejects `security-master`.

- [ ] **Step 3: Add commands**

Wire nested import/audit parsers into the existing CLI style. Open and migrate the local
database through `agentcy.db`. Audit output includes schema version, run ID, input rows,
counts, reason distribution, exchange distribution, and generated timestamp. Write via a
temporary sibling and `os.replace`.

- [ ] **Step 4: Verify and commit**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master_cli.py tests/test_cli.py -q`

```bash
git add agentcy/cli.py tests/test_security_master_cli.py
git commit -m "feat: expose security master audit CLI"
```

### Task 5: Foundation verification and local full-universe audit

**Files:**
- Create local ignored artifacts only under `var/scout/audit/`.

- [ ] **Step 1: Run focused suites**

Run: `/home/openclaw/.local/bin/uv run pytest tests/test_security_master_schema.py tests/test_security_master.py tests/test_security_master_cli.py -q`

Expected: all pass.

- [ ] **Step 2: Run the root suite**

Run: `/home/openclaw/.local/bin/uv run pytest -q`

Expected: baseline 1,016 tests plus all new tests pass.

- [ ] **Step 3: Import the real local universe**

Run the CLI against `var/scout/universe/all.csv` and the cached SEC exchange payload,
using an isolated local state directory. If the worktree cannot see those ignored files,
reference their explicit durable paths under `/home/openclaw/projects/invest-ai/var/`.

- [ ] **Step 4: Inspect the audit gate**

Confirm total input rows equal 7,486, every row has one eligibility state and reason code,
no duplicate `(security_key, symbol, exchange)` appears in the current view, and uncertain
identity cases remain `REVIEW`.

- [ ] **Step 5: Check branch state**

Run: `git diff 4ec6d89 HEAD --check && git status --short`

Expected: no whitespace errors and no untracked bulk artifacts.
