# Production Scout, thesis and portfolio monitor design

**Status:** approved design

**Date:** 2026-08-07

**Production surface:** GitHub Pages from `bot/site`, `/docs`

**Control plane:** durable local runtime and datastore

## Objective

Turn the existing Scout, thesis generator, portfolio monitor and static website
into one end-to-end production system. Every production run recomputes the
eligible universe and current top 1%, keeps research state current, monitors all
owner-ratified theses and publishes one internally consistent site snapshot.

The public website is the production dashboard. It is not the canonical data
store and cannot mutate portfolio or thesis state.

## Decisions

1. Continue with the current 7,486-security universe and current free data.
2. Preserve the Gate: top-1% membership creates or refreshes a draft thesis;
   only explicit owner ratification creates a monitored portfolio thesis.
3. Keep monitoring ratified theses even after they leave the top 1%.
4. Use a local orchestrator and publish only validated static artifacts to
   `bot/site` for GitHub Pages.
5. Keep quantities, cost basis, account identifiers and current portfolio value
   local. The public projection may contain symbol, public thesis, status,
   monitor evidence and optional target weight.
6. Combine model portfolio and monitor in one site page.
7. Use one short site disclaimer: `Illustratieve modelportefeuille, geen financieel advies.`
8. Record paid data candidates separately; they are not active production dependencies.

## End-to-end production run

A single orchestrator owns the snapshot lifecycle:

1. **Discover and refresh** the security master, SEC facts and market prices.
2. **Score** every eligible security with one formula and data version.
3. **Select** the exact current top 1% and persist its rank history atomically.
4. **Evaluate thesis freshness** for every top-1% candidate.
5. **Refresh draft research** when relevant source data, rank inputs or the
   configured research freshness boundary changed.
6. **Monitor every ratified thesis**, including holdings outside the top 1%.
7. **Build one public projection** for Scout, draft theses and portfolio monitor.
8. **Validate and promote** the snapshot only when every release gate passes.
9. **Publish** the validated `docs/` artifact to `bot/site`.

Every top-1% candidate receives a new `last_evaluated` result on every run.
Identical research is not regenerated merely to change a timestamp; the run
records that the existing research was re-evaluated against unchanged inputs.

## State model

The durable local datastore is authoritative and append-only where evidence or
run history is involved. It holds:

- universe membership, eligibility and identifier history;
- source observations, normalized facts and prices;
- scoring results and top-1% rank history;
- draft thesis versions and their source/freshness fingerprints;
- ratified portfolio theses and owner decisions;
- monitor runs, trigger outcomes and evidence;
- private portfolio fields excluded from publication;
- production runs, validation failures and published snapshot IDs.

The public projection is a deliberately smaller model generated from this
state. A deny-by-default serializer permits only explicitly listed fields.

## Website information architecture

The production site has three primary areas:

### Scout

- current universe and data freshness;
- scores, ranks and the current top 1%;
- evidence and missing-data states already supported by the Scout UI.

### Theses

- current top-1% draft candidates;
- research status and last evaluated time;
- why a draft was refreshed or safely reused;
- clear separation between draft and owner-ratified thesis.

### Model portfolio & monitor

One page groups each chosen stock with its public thesis and monitoring state:

- symbol and optional target weight;
- public thesis summary and version;
- `INTACT`, `REVIEW` or `BROKEN` status;
- last monitored time and next expected check;
- fired, unchecked or satisfied triggers with public evidence;
- the one-sentence model-portfolio disclaimer.

The site does not publish quantity, cost basis, actual position value or account
metadata.

All disclaimer copy across the site is reduced to at most one short sentence.
This is a content rule, independent of snapshot promotion.

Every area displays the same production snapshot ID and update time. Mixed-run
content is invalid.

## Scheduling

All modes call the same orchestrator and release gates.

### Trading-day run

- refresh prices and newly available filings;
- rescore the full eligible universe;
- update the top 1%;
- evaluate and selectively refresh draft theses;
- run the portfolio monitor;
- validate and publish the site.

### Weekly deep run

- refresh universe identity and eligibility;
- perform full filing-freshness validation;
- re-evaluate all current top-1% research;
- then execute the normal monitor, validation and publication path.

### Manual run

Manual execution invokes the identical end-to-end path. There is no shortcut
that can publish a partial site.

## Release gates

Publication is blocked unless:

1. the eligible universe and top 1% are internally consistent;
2. every ratified thesis has a monitor result in this run;
3. Scout, thesis and portfolio models share one snapshot ID;
4. data freshness and existing quality rules pass;
5. the public serializer contains no private portfolio fields;
6. generated HTML/data artifacts are complete and technically valid;
7. the production manifest matches the site artifact and source commit.

The disclaimer is a fixed website requirement, not a runtime release gate.

## Failure and promotion semantics

- A run writes to staging and cannot mutate the active snapshot incrementally.
- Any failed stage records a structured reason and leaves the last known good
  GitHub Pages version live.
- Promotion atomically marks one local snapshot active before publication.
- The publisher writes only generated public artifacts to `bot/site`.
- A push failure leaves the local active snapshot ready for idempotent retry.
- Rollback republishes a previously validated site commit; it does not recompute data.
- Concurrent runs are serialized with one local production lock.

## GitHub Pages boundary

GitHub Pages is a static production dashboard. It cannot securely ratify a
thesis, change portfolio state or start jobs. Those actions stay in the local
control plane and become public only through the next validated snapshot.

`bot/site` contains:

- the generated `docs/` site;
- public detail shards and assets;
- a manifest with snapshot ID, run time, source freshness and source commit SHA.

It contains no raw filing bulk, local databases, secrets or private portfolio state.

## Observability

Every production run records:

- mode, run ID, start/end and source commit;
- universe, eligible and top-1% counts;
- drafts created, refreshed, reused and failed;
- monitored thesis count and status distribution;
- release-gate results;
- active and published snapshot IDs;
- push commit or a retryable publication failure.

Success and failure notifications are emitted after the terminal state so a
detached run cannot end silently.

## Compatibility and migration

The design extends the existing `thesis.py`, `monitor.py`, `webapp.py`, deploy
scripts and classic branch-mode Pages configuration. It does not create a
parallel GitHub Actions computation path.

The current `/opt/stock-agentcy` box scripts are migration input, not a retained
runtime dependency. Their ordering, redaction and `bot/site` publication logic
must move to the durable local repository and datastore. Once the local
orchestrator has produced and published a validated snapshot, the corresponding
box timers are disabled so two schedulers cannot publish competing versions.

Existing ratified theses remain authoritative. Existing draft directories are
versioned or migrated in place with freshness metadata. Before scheduled
publication is enabled, a manual dry run must build and validate the complete
candidate snapshot without pushing it.

## Out of scope

- trade execution or broker automation;
- authenticated writes from GitHub Pages;
- publishing quantities, cost basis or account data;
- activating a paid fundamentals vendor;
- weakening thesis validation or automatic ratification;
- treating top-1% membership as a portfolio decision.

## Acceptance criteria

1. One command runs the complete trading-day production path.
2. Every run records an exact top 1% and evaluation state for every candidate.
3. Changed or stale top-1% research is refreshed; unchanged research is
   demonstrably re-evaluated without wasteful regeneration.
4. Every ratified thesis is monitored on each production run regardless of rank.
5. The site has Scout, Theses and combined Model portfolio & monitor areas.
6. All public areas share one snapshot ID and update time.
7. A failed stage cannot change the live Pages snapshot.
8. The public artifact contains none of the prohibited private fields.
9. The site uses the approved one-sentence disclaimer.
10. A validated snapshot can be published and rolled back through `bot/site`.
11. Existing Scout, thesis, monitor and site tests remain green, with new tests
    for orchestration, privacy, snapshot consistency and failure promotion.
12. Production has one active scheduler and no dependency on the former box.
