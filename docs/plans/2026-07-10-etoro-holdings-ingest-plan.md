# eToro Holdings Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fetch the owner's eToro holdings via the official Read-scope API and feed them through the existing Portfolio Mirror pipeline, capturing rich per-position data (time invested, invested amount, unrealized P&L) with zero manual entry.

**Architecture:** A hand-rolled stdlib `EtoroClient` (modeled on `agentcy/tg/client.py`) pulls positions + balances; a `fetch_etoro_snapshot` adapter aggregates lots per symbol, maps instrument types, converts to EUR via an injectable FX seam, and returns the canonical `SnapshotIn` (extended with an optional `details` tuple). `mirror.ingest_snapshot` persists the details to a new append-only `position_detail` table. Downstream reconciliation/balance is unchanged. Triggered on-demand (`agentcy snapshot etoro`) and weekly (Saturday Watchdog).

**Tech Stack:** Python 3.13 stdlib only (`urllib`, `ssl`, `json`) — no new pip dependency. SQLite (forward-only `schema/NNN_*.sql` migrations). pytest.

**Design doc:** `docs/plans/2026-07-10-etoro-holdings-ingest-design.md`

**Conventions to match:**
- Secrets are `AGENTCY_*` env vars read via `os.environ` (see `agentcy/tg/daemon.py:495`). New: `AGENTCY_ETORO_API_KEY`, `AGENTCY_ETORO_USER_KEY`.
- Transport pattern: `urllib.request` + `ssl.create_default_context()`, per-call timeout, 429/`retry_after`, unknown JSON fields ignored (see `agentcy/tg/client.py`).
- Snapshot `source="api_pull"` — already allowed by the `snapshot.source` CHECK in `schema/000_init.sql`.
- Append-only tables get a trigger pair (see `schema/000_init.sql:408-429`).
- CLI uses subparsers under `snapshot` (`import`/`enter`); add `etoro` (see `agentcy/cli.py:62-67`, `agentcy/cli.py:269`).
- Run the suite with `uv run pytest` from the repo root.

---

### Task 1: `position_detail` migration + append-only enforcement

**Files:**
- Create: `agentcy/schema/001_position_detail.sql`
- Test: `tests/test_etoro_migration.py`

**Step 1: Write the failing test**

```python
# tests/test_etoro_migration.py
import sqlite3
from agentcy import db

def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    conn = db.connect()          # applies all schema/NNN_*.sql forward-only
    return conn

def test_position_detail_table_exists_and_is_append_only(tmp_path, monkeypatch):
    conn = _fresh(tmp_path, monkeypatch)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(position_detail)")}
    assert {"snapshot_id", "symbol", "opened_at", "invested_native", "invested_eur",
            "unrealized_pnl_native", "unrealized_pnl_pct", "current_rate", "direction",
            "lot_count", "raw_json"} <= cols
    # append-only: UPDATE and DELETE both abort
    conn.execute("INSERT INTO snapshot (as_of, source, cash_balance_eur, created_at) "
                 "VALUES ('2026-07-10','api_pull',0,'2026-07-10T00:00:00Z')")
    sid = conn.execute("SELECT snapshot_id FROM snapshot").fetchone()[0]
    conn.execute("INSERT INTO position_detail (snapshot_id, symbol) VALUES (?, 'AAPL')", (sid,))
    for stmt in ("UPDATE position_detail SET direction='buy'",
                 "DELETE FROM position_detail"):
        try:
            conn.execute(stmt); assert False, f"{stmt} should abort"
        except sqlite3.IntegrityError:
            pass
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_etoro_migration.py -v`
Expected: FAIL — `no such table: position_detail`.

**Step 3: Write the migration**

```sql
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
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_etoro_migration.py -v` → PASS.
Also run `uv run pytest tests/test_schema.py -v` to confirm the schema-pinning tests still pass (they count applied migrations via `PRAGMA user_version`; update any hard-coded migration count there if it asserts one).

**Step 5: Commit**

```bash
git add agentcy/schema/001_position_detail.sql tests/test_etoro_migration.py
git commit -m "feat(etoro): add append-only position_detail table (migration 001)"
```

---

### Task 2: db helpers — append/fetch `position_detail`

**Files:**
- Modify: `agentcy/db.py` (add `append_position_details`, `fetch_position_details`)
- Test: `tests/test_etoro_db.py`

**Step 1: Failing test**

```python
# tests/test_etoro_db.py
from agentcy import db

def test_append_and_fetch_position_details(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    conn = db.connect()
    sid = db.append_snapshot(conn, as_of="2026-07-10", source="api_pull",
                             cash_balance_eur=0.0, created_at="2026-07-10T00:00:00Z")
    db.append_position_details(conn, sid, [{
        "symbol": "AAPL", "opened_at": "2024-01-02", "invested_native": 1000.0,
        "invested_eur": 920.0, "unrealized_pnl_native": 150.0, "unrealized_pnl_pct": 15.0,
        "current_rate": 230.0, "direction": "buy", "lot_count": 2, "raw_json": "[]"}])
    rows = db.fetch_position_details(conn, sid)
    assert rows[0]["symbol"] == "AAPL" and rows[0]["lot_count"] == 2
    assert rows[0]["opened_at"] == "2024-01-02"
```

**Step 2: Run → FAIL** (`module 'agentcy.db' has no attribute 'append_position_details'`).

**Step 3: Implement** (mirror the style of `append_positions` / `fetch_positions_records` already in `db.py`):

```python
def append_position_details(conn, snapshot_id, details):
    conn.executemany(
        "INSERT INTO position_detail (snapshot_id, symbol, opened_at, invested_native, "
        "invested_eur, unrealized_pnl_native, unrealized_pnl_pct, current_rate, direction, "
        "lot_count, raw_json) VALUES (:snapshot_id, :symbol, :opened_at, :invested_native, "
        ":invested_eur, :unrealized_pnl_native, :unrealized_pnl_pct, :current_rate, "
        ":direction, :lot_count, :raw_json)",
        [{"snapshot_id": snapshot_id, **d} for d in details])

def fetch_position_details(conn, snapshot_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM position_detail WHERE snapshot_id = ? ORDER BY symbol", (snapshot_id,))]
```

**Step 4: Run → PASS.**

**Step 5: Commit** `feat(etoro): db helpers for position_detail`.

---

### Task 3: `EtoroClient` transport + error classes

**Files:**
- Create: `agentcy/fetch/etoro.py`
- Test: `tests/test_etoro_client.py`

**Step 1: Failing test** — drive transport with a fake opener (no network), mirroring the Telegram client tests:

```python
# tests/test_etoro_client.py
import json, pytest
from agentcy.fetch import etoro

class _Resp:
    def __init__(self, body): self._b = json.dumps(body).encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False

def test_get_positions_sends_read_headers(monkeypatch):
    seen = {}
    def fake_urlopen(req, timeout=None, context=None):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["url"] = req.full_url
        return _Resp([{"InstrumentID": 1001, "Units": 3.0}])
    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    c = etoro.EtoroClient(api_key="PUB", user_key="USR")
    out = c.get_positions()
    assert out[0]["InstrumentID"] == 1001
    assert seen["headers"]["x-api-key"] == "PUB"
    assert seen["headers"]["x-user-key"] == "USR"
    assert "x-request-id" in seen["headers"]

def test_429_raises_retry_after(monkeypatch):
    import urllib.error, io
    def fake_urlopen(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {},
                                     io.BytesIO(b'{"retryAfter": 7}'))
    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    c = etoro.EtoroClient(api_key="PUB", user_key="USR")
    with pytest.raises(etoro.EtoroRetryAfter) as e:
        c.get_positions()
    assert e.value.retry_after == 7
```

**Step 2: Run → FAIL** (module missing).

**Step 3: Implement transport** — copy the shape of `agentcy/tg/client.py` (`_do`, `ssl.create_default_context`, timeout, 429). Read-only method set; **no trade methods**:

```python
"""Hand-rolled eToro public-API client (design 2026-07-10) — READ scope only.

urllib.request + json + ssl.create_default_context() (system CA; NO certifi in
authored code). Unknown JSON fields ignored. 429 honors retryAfter. Read-only:
this client has NO order/trade methods by construction — the "never executes"
charter is enforced structurally.
"""
from __future__ import annotations
import json, ssl, urllib.error, urllib.request, uuid
from typing import Any

_DEFAULT_HOST = "https://api.etoro.com"   # confirm exact base path against api-portal docs at impl time

class EtoroError(Exception): ...
class EtoroRetryAfter(EtoroError):
    def __init__(self, retry_after: float):
        super().__init__(f"429; retry_after={retry_after}")
        self.retry_after = retry_after

class EtoroClient:
    def __init__(self, *, api_key: str, user_key: str, timeout: float = 20.0,
                 base_url: str = _DEFAULT_HOST) -> None:
        self._api_key, self._user_key = api_key, user_key
        self._timeout, self._base = timeout, base_url.rstrip("/")
        self._ctx = ssl.create_default_context()

    def _get(self, path: str) -> Any:
        req = urllib.request.Request(f"{self._base}/{path.lstrip('/')}", method="GET", headers={
            "x-request-id": str(uuid.uuid4()), "x-api-key": self._api_key,
            "x-user-key": self._user_key, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=self._ctx) as r:
                return _loads(r.read())
        except urllib.error.HTTPError as e:
            data = _loads(e.read())
            if e.code == 429:
                raise EtoroRetryAfter(float(data.get("retryAfter", 1))) from e
            raise EtoroError(f"HTTP {e.code}: {data.get('message', e.reason)}") from e

    # READ methods only — exact paths confirmed against api-portal.etoro.com at impl time
    def get_positions(self) -> list[dict]: return list(self._get("api/v1/user/positions") or [])
    def get_portfolio(self) -> dict: return self._get("api/v1/user/portfolio") or {}
    def get_balances(self) -> dict: return self._get("api/v1/user/balances") or {}

def _loads(raw: bytes) -> Any:
    if not raw: return {}
    try: return json.loads(raw)
    except (ValueError, TypeError): return {}
```

> **Impl note:** the exact base URL and endpoint paths must be confirmed against `https://api-portal.etoro.com/` reference during implementation (the shapes above are placeholders). Keep the transport/tests stable; only the path strings change.

**Step 4: Run → PASS.**

**Step 5: Commit** `feat(etoro): read-only stdlib EtoroClient with 429 handling`.

---

### Task 4: instrument-type mapping + lot aggregation (pure functions)

**Files:**
- Modify: `agentcy/fetch/etoro.py` (add `map_instrument_type`, `aggregate_lots`)
- Test: `tests/test_etoro_adapter.py`

**Step 1: Failing test**

```python
# tests/test_etoro_adapter.py
import pytest
from agentcy.fetch import etoro

def test_map_instrument_type_known_and_unknown():
    assert etoro.map_instrument_type("Stocks") == "stock"
    assert etoro.map_instrument_type("ETF") == "etf"
    assert etoro.map_instrument_type("Crypto") == "crypto"
    assert etoro.map_instrument_type("CopyPortfolio") == "copyportfolio"
    with pytest.raises(etoro.EtoroError):
        etoro.map_instrument_type("SomethingNew")   # never silently mis-map

def test_aggregate_lots_collapses_symbol():
    lots = [
        {"symbol": "AAPL", "units": 2.0, "invested": 400.0, "open_rate": 200.0,
         "open_date": "2024-06-01", "mv_native": 500.0, "pnl_native": 100.0, "leverage": 1.0},
        {"symbol": "AAPL", "units": 1.0, "invested": 210.0, "open_rate": 210.0,
         "open_date": "2023-01-15", "mv_native": 250.0, "pnl_native": 40.0, "leverage": 1.0},
    ]
    agg = etoro.aggregate_lots("AAPL", lots)
    assert agg["quantity"] == 3.0
    assert agg["invested_native"] == 610.0
    assert agg["opened_at"] == "2023-01-15"          # earliest = time invested
    assert agg["lot_count"] == 2
    assert round(agg["avg_open_price"], 4) == round(610.0 / 3.0, 4)  # MV-weighted by invested/units
    assert agg["mv_native"] == 750.0
```

**Step 2: Run → FAIL.**

**Step 3: Implement** the two pure functions in `etoro.py`:

```python
_TYPE_MAP = {"stocks": "stock", "stock": "stock", "etf": "etf", "etfs": "etf",
             "crypto": "crypto", "cryptocurrencies": "crypto",
             "copyportfolio": "copyportfolio", "copyportfolios": "copyportfolio"}

def map_instrument_type(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key not in _TYPE_MAP:
        raise EtoroError(f"unknown eToro instrument type: {raw!r}")
    return _TYPE_MAP[key]

def aggregate_lots(symbol: str, lots: list[dict]) -> dict:
    units = sum(l["units"] for l in lots)
    invested = sum(l["invested"] for l in lots)
    return {
        "symbol": symbol, "quantity": units, "invested_native": invested,
        "avg_open_price": (invested / units) if units else None,
        "opened_at": min(l["open_date"] for l in lots),
        "mv_native": sum(l["mv_native"] for l in lots),
        "pnl_native": sum(l["pnl_native"] for l in lots),
        "leverage": max(l.get("leverage", 1.0) for l in lots),
        "lot_count": len(lots),
    }
```

**Step 4: Run → PASS.** **Step 5: Commit** `feat(etoro): instrument-type mapping + lot aggregation`.

---

### Task 5: `SnapshotIn.details` + `fetch_etoro_snapshot` adapter (FX seam)

**Files:**
- Modify: `agentcy/mirror.py` (add `details: tuple[PositionDetailIn, ...] = ()` to `SnapshotIn`; new frozen `PositionDetailIn`)
- Modify: `agentcy/fetch/etoro.py` (add `fetch_etoro_snapshot`)
- Test: `tests/test_etoro_adapter.py` (extend)

**Step 1: Failing test** — drive the adapter from a fake client + fake FX (deterministic, no network):

```python
def test_fetch_etoro_snapshot_builds_snapshotin_and_details():
    class FakeClient:
        def get_positions(self):
            return [{"symbol": "AAPL", "type": "Stocks", "units": 3.0, "invested": 600.0,
                     "open_rate": 200.0, "open_date": "2023-01-15", "mv_native": 750.0,
                     "pnl_native": 150.0, "leverage": 1.0, "currency": "USD"}]
        def get_balances(self): return {"cash": 100.0, "currency": "USD"}
    fx = lambda amount, ccy: amount * 0.9 if ccy == "USD" else amount   # USD->EUR at 0.9
    snap = etoro.fetch_etoro_snapshot(FakeClient(), fx=fx, as_of="2026-07-10")
    assert snap.source == "api_pull"
    assert snap.cash_balance_eur == 90.0
    (p,) = snap.positions
    assert p.symbol == "AAPL" and p.instrument_type == "stock" and p.quantity == 3.0
    assert p.mv_eur == 675.0 and p.native_currency == "USD"
    (d,) = snap.details
    assert d.symbol == "AAPL" and d.opened_at == "2023-01-15" and d.lot_count == 1
    assert d.invested_eur == 540.0
```

**Step 2: Run → FAIL.**

**Step 3: Implement.** In `mirror.py` add `PositionDetailIn` and the `details` field on `SnapshotIn`:

```python
@dataclass(frozen=True)
class PositionDetailIn:
    symbol: str
    opened_at: str | None = None
    invested_native: float | None = None
    invested_eur: float | None = None
    unrealized_pnl_native: float | None = None
    unrealized_pnl_pct: float | None = None
    current_rate: float | None = None
    direction: str | None = None
    lot_count: int | None = None
    raw_json: str | None = None
# SnapshotIn: add ->   details: tuple[PositionDetailIn, ...] = ()
```

In `etoro.py`, `fetch_etoro_snapshot(client, *, fx, as_of)`: group positions by symbol, `aggregate_lots`, `map_instrument_type`, `fx(mv_native, ccy) -> mv_eur`, build `PositionIn` + `PositionDetailIn`, fold `cash` type into `cash_balance_eur`, compute `weight` from EUR MV, `raw_json=json.dumps(lots)`. Reuse `mirror._yf_for` for `yf_ticker`.

**Step 4: Run → PASS.** **Step 5: Commit** `feat(etoro): fetch_etoro_snapshot adapter with FX seam`.

---

### Task 6: persist details in `ingest_snapshot`

**Files:**
- Modify: `agentcy/mirror.py:110` (`ingest_snapshot` — after `append_positions`, write details if present)
- Test: `tests/test_etoro_adapter.py` (extend — fixture `fetch → ingest` writes `position_detail`)

**Step 1: Failing test**

```python
def test_ingest_persists_details(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    from agentcy import db, mirror
    from agentcy.clock import SystemClock
    conn = db.connect()
    class FakeClient: ...        # same as prior test
    fx = lambda a, c: a * 0.9 if c == "USD" else a
    snap = etoro.fetch_etoro_snapshot(FakeClient(), fx=fx, as_of="2026-07-10")
    sid, _ = mirror.ingest_snapshot(conn, snap, clock=SystemClock())
    rows = db.fetch_position_details(conn, sid)
    assert rows and rows[0]["opened_at"] == "2023-01-15"
```

**Step 2: Run → FAIL** (no rows).

**Step 3: Implement** — in `ingest_snapshot`, after `db.append_positions(...)`:

```python
if snap.details:
    db.append_position_details(conn, snapshot_id, [{
        "symbol": d.symbol, "opened_at": d.opened_at, "invested_native": d.invested_native,
        "invested_eur": d.invested_eur, "unrealized_pnl_native": d.unrealized_pnl_native,
        "unrealized_pnl_pct": d.unrealized_pnl_pct, "current_rate": d.current_rate,
        "direction": d.direction, "lot_count": d.lot_count, "raw_json": d.raw_json}
        for d in snap.details])
```

**Step 4: Run → PASS** (also re-run `tests/test_db_append.py`, `tests/test_recon_asks_e2e.py` to confirm the CSV/manual paths — which pass no details — still work).

**Step 5: Commit** `feat(etoro): persist position_detail during ingest`.

---

### Task 7: FX default backed by yfinance (injectable)

**Files:**
- Modify: `agentcy/fetch/etoro.py` (add `default_fx(state_dir)` returning a `fx(amount, ccy)` callable)
- Test: `tests/test_etoro_adapter.py` (extend — EUR passes through as identity; cache within a run)

**Step 1: Failing test** — verify `default_fx` treats EUR as identity and calls the rate source once per currency (monkeypatch the rate lookup; **no network**).

**Step 3: Implement** `default_fx` using the existing paced yfinance path (`agentcy/fetch/yf.py`, e.g. `EURUSD=X`), memoizing per currency so one fetch covers all USD positions. EUR → identity. Unknown/failed rate → raise `EtoroError` (feeds the Task 9 fail-loud fallback).

**Step 5: Commit** `feat(etoro): yfinance-backed default FX with per-currency memoization`.

---

### Task 8: CLI `agentcy snapshot etoro [--dry-run] [--live]`

**Files:**
- Modify: `agentcy/cli.py:62-67` (add the `etoro` subparser), `agentcy/cli.py:269` (`_cmd_snapshot` branch)
- Test: `tests/test_cli_snapshot_etoro.py`

**Step 1: Failing test** — monkeypatch a fake client factory + fake FX; assert `--dry-run` prints the resolved `SnapshotIn` and writes **no** snapshot row; the non-dry path ingests + mints reconciliation asks (reuse the existing `ingest_snapshot`/`mint_reconciliation_asks` calls already in `_cmd_snapshot`).

**Step 3: Implement.** Add parser:

```python
setoro = snsub.add_parser("etoro", help="pull holdings from the eToro Read API")
setoro.add_argument("--dry-run", action="store_true")
setoro.add_argument("--live", action="store_true", help="opt-in real API smoke")
setoro.set_defaults(handler="snapshot")
```

In `_cmd_snapshot`, add `elif args.snap_cmd == "etoro":` — read `AGENTCY_ETORO_API_KEY`/`AGENTCY_ETORO_USER_KEY` from `os.environ` (fail-loud if missing), build `EtoroClient` + `default_fx`, `snap = fetch_etoro_snapshot(...)`. If `--dry-run`: print and `return 0` before any DB write. Else fall through to the shared `ingest_snapshot` + `mint_reconciliation_asks` + print block.

**Step 5: Commit** `feat(etoro): agentcy snapshot etoro CLI command`.

---

### Task 9: weekly-auto wiring + fail-loud fallback

**Files:**
- Modify: `agentcy/jobs/weekly.py` (fetch+ingest eToro at the top of the weekly run, guarded)
- Test: `tests/test_weekly_etoro.py`

**Step 1: Failing tests** — (a) happy path: fake client → weekly ingests an `api_pull` snapshot and mints asks; (b) failure path: client raises → **no partial snapshot**, an outbox notice "eToro fetch failed: … — holdings unchanged since <date>" is enqueued, and the rest of the weekly run proceeds on the prior snapshot.

**Step 3: Implement** a guarded `_etoro_refresh(conn, *, clock, state_dir)` called early in the weekly entrypoint:

```python
try:
    if os.environ.get("AGENTCY_ETORO_API_KEY"):
        client = EtoroClient(api_key=os.environ["AGENTCY_ETORO_API_KEY"],
                             user_key=os.environ["AGENTCY_ETORO_USER_KEY"])
        snap = fetch_etoro_snapshot(client, fx=default_fx(state_dir),
                                    as_of=clock.now().date().isoformat())
        sid, deltas = mirror.ingest_snapshot(conn, snap, clock=clock)
        mirror.mint_reconciliation_asks(conn, sid, deltas, clock=clock)
except (EtoroError, FetchFailed) as e:
    last = db.fetch_latest_snapshot(conn)
    since = last["as_of"] if last else "never"
    outbox.enqueue(conn, dedupe_key=f"etoro-fail:{clock.now().date()}", kind="notice",
                   payload_html=f"eToro fetch failed: {e} — holdings unchanged since {since}.",
                   clock=clock)
```

Only enable auto-fetch when the env keys are present (so existing weekly tests without keys are unaffected).

**Step 4: Run → PASS.** Run the full weekly test module to confirm no regression.
**Step 5: Commit** `feat(etoro): weekly-auto eToro refresh with fail-loud fallback`.

---

### Task 10: secrets, deploy wiring, docs, full-suite + license gate

**Files:**
- Modify: `install.sh:42` area (add `AGENTCY_ETORO_API_KEY=` / `AGENTCY_ETORO_USER_KEY=` placeholders to the env template), the weekly systemd unit's `EnvironmentFile` (already inherited), `docs/plans/2026-07-08-technology-architecture.md` secrets note, `deploy/digitalocean/README.md`.
- Test: `tests/test_install_runbook.py` (extend the env-key assertion list at `:28`).

**Steps:**
1. Add the two env placeholders to the secrets template; confirm mode 0600 and `.gitignore` cover it. Update the "exactly two entries" note to four.
2. Document in the design/runbook: how the owner creates the Read key (*Settings → Trading → API Key Management*, env=Real, scope=Read), and that rotation = edit env + restart.
3. Run the **license gate**: `uv run python tools/license_gate.py` → clean (no new dependency).
4. Run the **whole suite**: `uv run pytest -q` → green (Windows skips the 3 known AF_UNIX/git tests).
5. Update `CLAUDE.md` Architecture section with a one-line note that eToro `api_pull` ingestion is implemented.
6. Commit `feat(etoro): secrets/deploy wiring + docs + suite green`.

---

## Verification checklist (before opening the PR)

- [ ] `uv run pytest -q` green.
- [ ] `uv run python tools/license_gate.py` clean — no new runtime dependency.
- [ ] `EtoroClient` has **no** trade/order method (grep confirms Read-only).
- [ ] `positions_advice` / balance path untouched — `position_detail` is record-keeping only.
- [ ] Secrets only in env (0600, git-ignored); never logged or committed.
- [ ] `--dry-run` writes nothing to the DB; failure path ingests no partial snapshot.
- [ ] Endpoint base URL + paths reconciled against `api-portal.etoro.com` reference.
