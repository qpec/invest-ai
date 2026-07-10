# eToro holdings ingestion — design

**Date:** 2026-07-10
**Branch:** `feat/etoro-ingest`
**Status:** approved (owner, 2026-07-10)

## Goal

Eliminate manual portfolio data entry by fetching holdings directly from eToro
and feeding them through the existing Portfolio Mirror pipeline. Capture **as
much per-position data as eToro exposes** — quantity, invested amount, average
open price, **time invested (open date)**, unrealized P&L, leverage — not just
current market value. The system continues to *advise and monitor, never
execute*.

## Feasibility (why this is safe and dependency-free)

eToro shipped an official public API in 2026 with a **personal, read-only key**
created by the owner in *Settings → Trading → API Key Management* (environment =
Real, scope = **Read**, SMS-confirmed). It exposes the authenticated user's own
real-account data: portfolio breakdown, open positions, balances, P&L, and
trading history. Auth is three HTTP headers (`x-request-id`, `x-api-key`,
`x-user-key`); shared quota ≈ 60 requests / 60 s.

- **No APK reverse-engineering** — the official Read key is the ToS-compliant,
  KYC-gated, read-only path. Reverse-engineering is strictly worse (fragile,
  ToS-violating, no read-only guardrail) and is rejected.
- **No new pip dependency** — the API is REST + 3 headers, hand-rolled with
  stdlib `urllib` exactly like `agentcy/tg/client.py`. This preserves NFR7 (four
  runtime packages only) and the license gate. The unofficial `etoropy` library
  is rejected: unofficial, unaudited license, breaks the dependency budget.

## Architecture — one new source, downstream unchanged

The feature slots in *before* `mirror.ingest_snapshot()`. The eToro API becomes
a third snapshot source alongside the CSV export and manual text paste,
producing the same canonical `SnapshotIn`. Reconciliation, R-ask minting, the
leverage tripwire, and the balance report are untouched.

```
eToro Read API ──▶ agentcy/fetch/etoro.py ──▶ SnapshotIn ──▶ mirror.ingest_snapshot()
  (3 headers,        EtoroClient (transport)   (canonical      (existing pipeline:
   HTTPS, Read)      + fetch_etoro_snapshot     contract)        deltas, R-asks,
                       adapter + FX + detail)                     leverage, balance)
```

The snapshot `source` value is **`api_pull`**, which the `snapshot.source` CHECK
constraint in `schema/000_init.sql` already permits — the schema anticipated
this.

## Components

### `agentcy/fetch/etoro.py`
- **`EtoroClient`** — modeled precisely on `tg/client.py`: `urllib.request` +
  `ssl.create_default_context()` (system CA, **no certifi in authored code**),
  per-call timeout, 429/`retry_after` honored, unknown JSON fields ignored.
  Read-only method set: `get_portfolio()`, `get_positions()`, `get_balances()`.
  **No trade methods exist on the client** — the "never executes" charter is
  enforced structurally, not by convention.
- **`fetch_etoro_snapshot(client, fx) -> SnapshotIn`** — the adapter:
  1. Pull positions + balances.
  2. **Aggregate lots**: eToro may hold several open positions in one instrument;
     the canonical `position` PK is `(snapshot_id, symbol)`. Collapse lots per
     symbol — sum units → `quantity`, sum invested → cost basis, MV-weighted
     average → `avg_open_price`, **earliest open date → `opened_at`** (holding
     period), sum market value.
  3. **Map instrument types** eToro → taxonomy
     (`stock`/`etf`/`crypto`/`copyportfolio`/`cash`); unknown types raise (see
     error handling), never silently mis-map.
  4. **FX to EUR** via the existing yfinance path; compute `mv_eur`. Fold cash
     into `cash_balance_eur`.
  5. Stamp `source="api_pull"`, `as_of` = fetch date.

### Secrets
`ETORO_API_KEY` + `ETORO_USER_KEY` as environment variables (systemd
`EnvironmentFile`, `chmod 600`, git-ignored), read at job start exactly like the
Telegram token. **Never in the DB, never committed, never logged.**

### Richer-data storage — `schema/001_position_detail.sql`
A new append-only companion table keeps the canonical `position` /
`positions_advice` contract (and its invariant tests) untouched while capturing
everything eToro exposes:

```sql
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
  lot_count             INTEGER,  -- how many eToro lots collapsed into this row
  raw_json              TEXT,     -- full eToro payload for the symbol (all lots)
  PRIMARY KEY (snapshot_id, symbol)
);
-- append-only trigger pair, mirroring the §4.2 convention
```

Like `avg_open_price`, `position_detail` is **record-keeping only** — it is
never read by the balance/advice path (invariant 4 stays clean). It exists for
thesis tracking, the decision journal, and future reporting.

## Triggers

- **Weekly-auto** — `jobs/weekly.py` (Saturday Watchdog) fetches, ingests, and
  lets the existing machinery mint reconciliation asks and the balance report.
  One batch of prompts per week.
- **On-demand** — `agentcy snapshot --etoro` (with `--dry-run` and an opt-in
  `--live` smoke) for first-run, testing, and ad-hoc refresh. Built first; the
  weekly wiring is a thin call into the same code.

## Error handling — the weekly letter must never break

On any failure (eToro unreachable, key invalid/expired, unknown instrument type,
FX gap): **do not ingest a partial snapshot.** Emit a notice ("eToro fetch
failed: <reason> — holdings unchanged since <date>"), fall back to the last good
snapshot, and let the rest of the weekly review proceed on stale-but-flagged
data (the existing staleness ladder already handles an old snapshot). `--dry-run`
resolves and prints the `SnapshotIn` without writing to the DB.

## Testing

- **Adapter unit** — against recorded JSON fixtures (captured once, scrubbed of
  account IDs) → asserts the exact `SnapshotIn` and `position_detail` rows.
  Covers the instrument-type mapping table, lot aggregation, FX conversion, cash
  folding, and unknown-type rejection.
- **Client transport unit** — 429/`retry_after`, HTTP error, timeout, via a stub
  (mirrors the Telegram client tests). No live network.
- **Integration** — fixture-driven `fetch → ingest_snapshot` produces the right
  deltas / R-asks vs. a prior snapshot, and `001` migration applies cleanly on a
  fresh DB and preserves invariants.
- **No live API calls in the suite** (no secrets in CI, deterministic). A
  manual, opt-in `--live` smoke run confirms the mapping matches reality once.

## Out of scope (YAGNI)

Trade execution (charter-forbidden), the Agent-Portfolio sub-account API,
historical backfill of past snapshots, and demo-account support.

## Constraint checklist

- NFR7 four-package budget: **kept** (stdlib only).
- License gate: **kept** (no new dependency; no authored certifi use).
- Append-only invariants: **kept** (`position_detail` gets its own trigger pair;
  `positions_advice` untouched).
- "Never executes": **kept** (client has no trade methods; Read scope only).
- Secrets: env-only, `chmod 600`, git-ignored.

## Implementation notes (2026-07-10)

- **FX two tiers.** `default_fx` is built directly on the canonical `store.fx_rate_eur`
  (no bespoke FX path); the weekly/production `production_fx` wraps it and **self-primes**
  `{CUR}EUR=X` on a cache-miss, so a first run or a newly held currency needs no manual
  pre-seed.
- **Fail-loud fallback never crashes the letter.** On any eToro/FX failure `etoro_refresh`
  enqueues a `notice` and returns, leaving the last good snapshot in place. Its dedupe key
  routes through `runner.qualified_key`, so a same-day re-sweep promotes an already-sent
  per-date key to an attempt-qualified revision instead of raising `ValueError` out of the
  except block (§5.4).
- **Secrets are OPTIONAL.** The env template ships both eToro keys **blank**; the weekly
  guard requires BOTH truthy, so an unconfigured box stays in manual-snapshot mode and the
  manual `agentcy snapshot etoro` path still works.
- **Zero new runtime dependencies** — the whole feature stays within the four-package
  budget (stdlib `urllib`/`ssl` client), and the license gate remains clean.
