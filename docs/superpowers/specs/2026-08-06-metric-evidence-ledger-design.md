# Metric Evidence Ledger Design

**Status:** Approved by owner on 2026-08-06

## Goal

Make every Scout metric for the full universe of roughly 1,900 US filers
traceable, freshness-aware, and operationally dependable. A score must be backed
by current observations and a completed refresh run. Required metrics block a
decision when their evidence is stale, missing, conflicting, or unverifiable.

## Decisions

- Cover the complete Scout universe from the first production release.
- Use filing-aware freshness for fundamentals and trading-day-aware freshness
  for prices.
- Required metrics block scoring and ranking when unusable. Optional metrics
  remain visible with their degraded state and reduce data confidence.
- A certified vendor fallback may temporarily drive a metric when its
  definition, period, provenance, tolerance, and validity window satisfy an
  explicit source policy.
- Show universe and per-metric health on the desk site. Send Telegram alerts
  only for missed jobs, SLA breaches, source conflicts, and material coverage
  regressions.
- Keep SQLite as the source of truth and preserve append-only history.

## Architecture

Add a Metric Evidence Ledger between fetchers and scoring. Fetchers append raw
source observations. Deterministic metric calculators append derived metric
observations and exact links to their inputs. A current-metric view applies
source policy, freshness, and formula versioning. During migration, the legacy
bundle path and ledger path run side by side and parity differences are stored.
The Scout, monitor, and site switch to the ledger only after the parity gate is
green.

## Data model

### `metric_definition`

Versioned definition of a metric: identifier, formula version, unit,
required/optional classification, freshness policy, and activation dates.
Definitions are immutable; a formula change creates a new version.

### `source_observation`

One immutable source fact for one security and reporting period. It stores the
source, filing accession or vendor identity, taxonomy/tag, numeric value,
currency/unit, period boundaries, filing time, fetch time, payload hash, and
refresh run. Restatements append observations and never overwrite history.

### `metric_observation`

One derived value for one security, metric definition, and as-of point. It
stores value, status (`FRESH`, `STALE`, `MISSING`, `CONFLICT`, or
`UNVERIFIABLE`), confidence, calculation time, and refresh run.

### `metric_input`

Many-to-many lineage from a metric observation to the exact source
observations used by the formula.

### `source_policy`

Versioned policy per metric and source: priority, primary/fallback role,
definition equivalence, maximum age, comparison tolerance, and active window.
Only an active certified fallback may produce a decision-grade observation.

### `refresh_run`

Logical job identity and operational evidence: run type, scheduled time,
start/end, status, catch-up flag, universe size, coverage counts, and failure
summary. A run becomes successful only after its observations and coverage
checks commit atomically.

### `parity_result`

Comparison between the legacy bundle result and ledger result for one security
and metric: values, states, tolerance, and verdict.

### Current views

`v_current_metric` selects the newest admissible observation for every security
and active metric definition. `v_stock_data_health` summarizes required gaps,
optional gaps, conflicts, oldest evidence, and decision readiness per security.
`v_metric_coverage` summarizes universe coverage and state counts per metric.

## Refresh flow

1. A daily price run appends the latest trading-day observations and checks
   universe coverage.
2. A daily SEC delta run reads filings after the last committed cursor and
   rebuilds only affected securities. The cursor advances in the same
   transaction as observations and metrics.
3. A weekly full reconciliation rebuilds the complete universe from the newest
   bulk SEC dataset, catches missed delta events, detects restatements, and
   compares coverage with the previous successful run.
4. Certified vendor fallbacks run only for missing decision-critical inputs.
   Policy violations create `CONFLICT` or `UNVERIFIABLE`; they never silently
   replace SEC facts.
5. Metrics rematerialize only when inputs, formula version, or source policy
   changes. Their state is no stronger than their weakest required input.

All jobs remain systemd oneshots with `Persistent=true`, unique logical run
keys, locks, timeouts, catch-up semantics, and existing failure notification.

## Decision semantics

- Every required metric must resolve to `FRESH` for a security to be
  decision-ready.
- Missing or degraded optional metrics remain visible and reduce a separate
  confidence indicator.
- A vendor-backed metric is labelled as fallback everywhere and retains the
  vendor observation in its lineage.
- A source disagreement outside tolerance is `CONFLICT`, blocks the affected
  required metric, and creates an alert.
- No stale value is carried forward as if it were current.

## Product surface

The Scout drill-down shows each metric's value, status, source, period end,
filing/fetch time, formula version, and lineage. The data-health dashboard shows
coverage by metric, decision-ready securities, freshness distribution, vendor
fallback use, conflicts, and the last successful run for each job.

Telegram stays exception-driven: missed or failed runs, SLA breaches, material
coverage regressions, and source conflicts. Healthy runs are visible on the
dashboard and do not create routine chat noise.

## Migration

1. Add the ledger schema and repository APIs without changing scoring.
2. Backfill source observations and metric observations from existing bundles.
3. Dual-write new fetches and persist parity results.
4. Require full-universe parity for values, missingness, and freshness over
   consecutive scheduled runs.
5. Switch scoring, monitor, and site reads to current ledger views behind a
   reversible feature flag.
6. Retire legacy reads only after production evidence confirms the new path.

## Failure handling

Transactions prevent partial runs from appearing successful. Reruns use the
existing logical run key and append a new attempt where required. Source and
calculation failures retain the last observation as historical evidence while
the current state becomes stale or unverifiable. Coverage regression and source
conflict alerts deduplicate through the existing outbox.

## Verification

- Schema constraints and append-only guards.
- Unit tests for freshness, source-policy admission, vendor tolerances, lineage,
  and current-observation selection.
- Integration tests for atomic cursor advancement and failed/catch-up runs.
- Full-universe legacy-versus-ledger parity tests.
- Timer and deployment tests for daily delta and weekly reconciliation jobs.
- Dashboard and Telegram tests for health summaries and alert deduplication.

## Public API assessment

The existing SEC EDGAR and DERA datasets remain the correct public primary
sources: keyless, filing-aware, and aligned with point-in-time requirements.
The public-apis catalog adds no stronger fundamentals source for decision-grade
US filing data. Vendor APIs are eligible only through explicit certified source
policies and environment-managed credentials.
