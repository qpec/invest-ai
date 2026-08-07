# Local Data Completeness Design

**Date:** 2026-08-07
**Status:** approved for autonomous implementation

## Goal

Raise reliable coverage of the Scout's 26 stock metrics using a local, resumable,
evidence-led architecture. Coverage may increase only when every value remains
point-in-time correct, fresh, attributable to exact source facts, and economically valid.

## Scope decomposition

The program consists of four independently deployable slices:

1. canonical security master and eligibility;
2. free-first market prices and corporate-action evidence;
3. filed-fact coverage improvements and safe formula chains;
4. durable coverage publication and scheduled operation.

Each slice must deliver measurable value and pass its own parity gate before the next
slice can become authoritative.

## Source hierarchy

### Identity and eligibility

Every traded instrument receives a stable `security_id`. The security master stores CIK,
LEI when available, primary exchange, ticker history, instrument class, active interval,
and an explicit eligibility state. Only primary ordinary shares enter the 26-metric
operating-company screen. Funds, listed debt, warrants, preferred-only lines, trusts,
secondary duplicates, stale tickers, and unsupported issuer classes remain queryable but
are excluded with a durable reason code.

### Filed fundamentals

SEC bulk Company Facts is the fast standard-fact layer. SEC Financial Statement Data
Sets add primary-statement custom tags and segment metadata. Financial Statement and
Notes Data Sets add dimensions and detailed note facts only for unresolved gaps. Exact
Inline XBRL filing packages are the final evidence layer for conflicts and high-value
missing metrics. Dutch primary listings use ESEF/AFM after the US pipeline is stable.

### Market data

The first release is free-first. Yahoo supplies the historical local baseline, including
raw close, adjusted close, and captured split events. The official eToro Public API may
verify current closes and instrument mappings when the user provides dedicated API and
user keys. Account login credentials or browser cookies are never used. A stable provider
interface permits later EODHD or Massive adoption without schema migration.

eToro cannot be the sole production source because its official documentation does not
establish a complete equity splits, dividends, or fundamentals feed. Yahoo is a bootstrap
and fallback source, not a source with a contractual SLA.

### Derived metrics

Metric observations contain formula version, as-of time, calculated-at time, status,
confidence, and exact input observation identifiers. Status values distinguish `FRESH`,
`STALE`, `MISSING`, `CONFLICT`, `NOT_APPLICABLE`, `INELIGIBLE_SECURITY`, and
`UNVERIFIABLE`. Consumers never infer the reason for a null value.

## Data flow

Every job follows `discover -> fetch -> normalize -> validate -> derive -> publish`.

1. Discover compares submissions, exchange metadata, ticker maps, ESEF indexes, and the
   local security master. Changes become immutable identity events.
2. Fetch writes to a temporary artifact, validates the response, calculates SHA-256, and
   atomically promotes it. Cursors make interrupted jobs resumable.
3. Normalize converts provider payloads to source-independent observations while retaining
   the original artifact link.
4. Validate checks units, currencies, periods, filing chronology, dimensions, ticker
   identity, split treatment, freshness, and economic plausibility.
5. Derive recalculates only metrics whose inputs or formula version changed.
6. Publish changes the current coverage snapshot only after the run succeeds. Partial runs
   retain their evidence but cannot replace the last valid snapshot.

## Safe coverage improvements

### Security cleanup

Resolve issuer and security identity before measuring completeness. A US issuer's foreign
secondary listing must map to the same issuer and lose primary-screen eligibility. SEC
404s caused by funds, debt, and trusts become terminal eligibility classifications instead
of recurring fetch failures.

### Price-dependent metrics

Store both raw and adjusted closes, split events, source symbol, exchange, source timestamp,
and payload hash. A price older than 45 days or a share count older than 450 days cannot
produce enterprise value or owner-FCF yield. Cross-source close differences outside the
configured tolerance produce `CONFLICT`.

### D&A chain

When a combined D&A fact for an exact period is absent, derive D&A as `Depreciation +
AmortizationOfIntangibleAssets` for the same start and end dates. The chain must reject
financing-cost amortization and must never sum separate facts alongside a combined fact.

### Tax-gap chain

Tax expense, pretax income, and cash taxes must share exactly the same start and end date.
Quarterly TTM is preferred when all periods exist. An annual observation is permitted only
when all three inputs describe that annual span. Different fiscal windows cannot be mixed.

### Acquisition-spend chain

Use `PaymentsToAcquireBusinessesNetOfCashAcquired` first. Permit
`PaymentsToAcquireBusinessesGross` only when the net concept is absent for the exact span.
Goodwill, consideration transferred, stock consideration, and pro-forma facts are never
cash-acquisition substitutes.

### Metrics that may remain unavailable

R&D remains missing without an operating R&D expense fact. Incremental ROIC remains
unavailable without four aligned annual periods or when invested-capital materiality guards
fail. Owner-FCF yield remains unavailable with stale price, stale shares, unresolved
corporate actions, or uncertain security mapping. Higher coverage obtained through silent
imputation is a regression.

## Local persistence

Raw artifacts live under ignored `var/scout/` directories. SQLite stores normalized
identity events, observations, lineage, job runs, current coverage, and immutable history.
Git stores schema, ingestion code, formula code, tests, small fixtures, systemd units, and
documentation. Bulk filings and price histories never enter Git.

## Failure semantics

- An operational-company 404 receives bounded retry and identity/submissions review.
- An ineligible security receives a terminal `INELIGIBLE_SECURITY` classification.
- Rate limiting uses exponential backoff with jitter and a persisted cursor.
- A stale price or share count produces `STALE`, without a numeric metric.
- Source differences outside tolerance retain both facts and produce `CONFLICT`.
- Missing facts, formula guards, and parser failures have distinct reason codes.
- Every scheduled run records schedule time, start, finish, counts, failures, and coverage
  delta. The wrapper sends a success or failure notification after completion.

## Schedule

- Daily: security-master delta, EOD prices, corporate-action refresh, price metrics.
- Nightly: SEC submissions/companyfacts bulk delta and monitored-name fast path.
- Weekly: full-universe coverage reconciliation, retry review, source conflicts.
- Monthly: Financial Statement and Notes gap-fill batch.
- Quarterly: complete Financial Statement Data Set reconciliation.
- Event-driven: new 10-K, 10-Q, 20-F, or 40-F accession and amendments.

## Quality gates

The current baseline is 4,836 usable bundles and 63,201 of 125,736 fundamental metric
cells populated. Gates are evaluated first on a 300-issuer stratified gold set and then on
the full eligible universe.

1. Identity gate: every included row has one primary eligible security; every excluded row
   has a reason code; no duplicate issuer enters coverage denominators.
2. Price gate: at least 95% of eligible, currently traded securities have a fresh price;
   split-adjusted history matches a second source on the gold set within tolerance.
3. Direct-fact gate: at least 99% exact agreement with human-reviewed filing facts on the
   gold set, with complete accession and context lineage.
4. Derived-metric gate: no change in legacy values where inputs and formula version are
   unchanged; every new value identifies the rule that unlocked it.
5. Reliability gate: interrupted jobs resume without duplicate evidence; a failed run
   cannot replace the last valid snapshot; completion notification is verified.
6. Vendor gate: a paid provider is considered only if free-first price freshness falls
   below 95%, corporate-action conflicts exceed 0.5%, or manual remediation exceeds two
   hours per month. Price and licensing are reviewed before activation.

## Testing strategy

All behavioral changes use test-driven development. Unit tests cover identity decisions,
provider normalization, tag-chain precedence, period alignment, freshness, conflict
selection, and status reasons. Contract fixtures capture small redacted provider payloads.
Integration tests exercise migration, checkpoint restart, immutable evidence, snapshot
promotion, and notification. A full-universe dry run produces a coverage-diff artifact and
cannot alter production reads until parity gates pass.

## Delivery order

1. Security master and eligibility report.
2. Provider-neutral price observations, Yahoo baseline, optional eToro verifier.
3. Metric coverage snapshot persisted to SQLite.
4. Safe D&A, tax, and acquisition chains with full-universe coverage diff.
5. SEC Statement Data Set ingestion.
6. Notes and Inline XBRL targeted gap filler.
7. ESEF connector for Dutch primaries.
8. Local schedules, health reports, and terminal notifications.
