# Reliable Price Coverage Design

**Date:** 2026-08-07
**Status:** approved for autonomous implementation
**Parent design:** `2026-08-07-local-data-completeness-design.md`

## Goal

Increase reliable Scout metric coverage by adding a local, resumable and fully traced
market-price layer. This slice must unlock at least 2,300 trustworthy
`owner_fcf_yield_pct` values and improve total 26-metric coverage by at least 1.5
percentage points without changing any pre-existing fundamental value.

## Release gates

The slice becomes authoritative only when all of these gates pass:

1. At least 95% of the 5,763 currently eligible securities has a fresh validated price or
   an explicit terminal reason.
2. Raw close, adjusted close and reported split events are retained as immutable source
   evidence. Missing corporate actions are never inferred.
3. At least 2,300 `owner_fcf_yield_pct` observations are `FRESH` and link to both the price
   observation and the exact owner-FCF/share inputs used by the filing adapter.
4. Full-universe reliable coverage improves by at least 1.5 percentage points from the
   50.382% eligible-universe baseline.
5. Every old non-price metric with unchanged inputs remains exactly equal.
6. Interrupted and failed refreshes cannot replace the last successful price snapshot.

## Source decision

Yahoo is the free bootstrap source because the repository already has one paced,
fail-loud yfinance boundary. It supplies raw close, adjusted close, dividends, currency
and split events. The Public APIs catalog did not identify a more suitable free,
maintained market-price API with the required historical and corporate-action shape.

The official eToro Public API is an optional verifier after dedicated API and user keys
are supplied. It may verify current prices and symbol identity, but it cannot promote a
Yahoo value without an explicit tolerance policy. Account credentials and browser
cookies are outside the design. A paid provider is deferred until the existing vendor
gate fails.

## Components

### Provider-neutral evidence schema

Migration `006_market_price_evidence.sql` adds:

- `market_price_refresh_run`: immutable logical run identity plus a mutable completion
  envelope and promotion state;
- `market_price_attempt`: one append-only outcome per security and attempt;
- `market_price_observation`: immutable provider observations with `security_key`,
  provider symbol, bar date, raw close, adjusted close, dividend, split ratio, currency,
  fetch time and payload hash;
- `v_current_market_price`: newest observation from the last successful promoted run;
- append-only triggers and uniqueness constraints for idempotent replay.

The migration also adds an immutable reason code to metric observations. Existing rows
retain a neutral legacy reason; new null observations must name why no numeric value was
admitted.

No bulk bars enter Git. SQLite holds normalized evidence; original batch artifacts and
coverage reports live under ignored `var/scout/` paths.

### Yahoo batch adapter

`agentcy.fetch.yf` remains the only yfinance import boundary. It gains a chunked history
operation that requests a small group of provider symbols with `auto_adjust=False`,
`actions=True`, threads disabled and the existing process-wide pacing lock. The adapter
normalizes each ticker independently and rejects empty frames, non-positive closes,
missing currency, malformed dates and non-finite actions.

A failed ticker does not fail its peers. A failed batch is retried through the existing
bounded rate-limit policy and then decomposed into smaller batches so one malformed symbol
cannot block the run. No value is zero-filled.

### Refresh orchestration

`agentcy.market_prices` selects only `v_eligible_security` rows. The queue order is:

1. securities with no successful observation;
2. stale observations, oldest first;
3. current observations due for refresh.

Each chunk is written inside one transaction. The persisted cursor is the set of terminal
attempt rows, so replay skips completed securities and resumes failures according to their
retry class. Rate limits stop the run as degraded; unknown/delisted symbols get a bounded
terminal status. A run promotes only after every selected security has an outcome and the
release validation succeeds.

### Price validation and conflicts

A positive finite raw close and currency are required. Adjusted close must also be
positive. Split ratios must be positive and are stored only when the provider reports
them. Prices older than 45 calendar days cannot create a metric; the operational daily
freshness report separately targets two trading days.

When eToro verification is configured, the latest close is compared using both an
absolute and relative tolerance. Values outside tolerance remain as two observations and
produce `CONFLICT`; neither is selected silently.

### Metric derivation and lineage

The existing point-in-time bundle adapter calculates market capitalization from a raw
close and a share count expressed in the same split basis. `owner_fcf_yield_pct` is
calculated only when all of the following hold:

- security status is `ELIGIBLE`;
- price status is `FRESH`;
- a valid share count exists at or before the price date and is no older than 450 days;
- split evidence is sufficient for the chosen price/share basis;
- owner FCF is available for an aligned period.

The metric observation stores formula version, status, confidence, calculation time and
the exact price and filing observation IDs. A missing prerequisite produces a specific
reason (`MISSING_PRICE`, `STALE_PRICE`, `MISSING_SHARES`, `STALE_SHARES`,
`UNRESOLVED_SPLIT`, `MISSING_OWNER_FCF` or `CONFLICT`) and no numeric value.

The current Company Facts cache predates the ledger. During derivation, the slice
materializes only the owner-FCF and share facts actually selected by the point-in-time
adapter into `source_observation`, retaining concept, period, filed date, payload hash and
CIK. This narrow bridge provides exact lineage without bulk-copying every cached XBRL fact
or creating a second formula implementation.

## CLI and artifacts

The local CLI adds:

```text
agentcy market-data prices refresh --budget N [--resume RUN_ID]
agentcy market-data prices status --out PATH
agentcy coverage compare --baseline PATH --out PATH
```

`refresh` prints and records run counts. `status` atomically writes freshness, terminal
reasons, source distribution and conflict counts. `coverage compare` rebuilds the same
26-metric measurement used for the 50.382% baseline and emits per-metric gained, lost and
unchanged counts. Generated artifacts never become authoritative input.

## Failure semantics

- Rate limit: bounded backoff, run marked degraded, cursor retained.
- Transport or malformed payload: retryable attempt with diagnostic class; last good
  snapshot remains current.
- Unknown/delisted symbol: bounded retry followed by a terminal reason.
- Stale price or shares: explicit stale metric status and no value.
- Missing split evidence: explicit unresolved status when the chosen price basis requires
  adjustment.
- Cross-source disagreement: conflict with both observations retained.
- Process interruption: uncommitted chunk rolls back and is retried on resume.

## Tests and verification

Behavior is built with TDD. Unit tests cover batch normalization, partial failures,
actions, payload hashes, freshness and tolerance. Schema tests cover immutability,
idempotency and promotion. Integration tests interrupt and resume a multi-chunk run,
prove failed runs cannot become current, and verify lineage for a known split and a
non-split issuer.

The final full-universe run produces:

- price coverage and failure summary;
- per-metric coverage delta against `metric-coverage-eligible-v2.json`;
- parity output proving existing values did not change;
- release-gate verdicts with exact numerators and denominators.

If any release gate fails, the evidence remains available for diagnosis while the new
snapshot stays non-authoritative.
