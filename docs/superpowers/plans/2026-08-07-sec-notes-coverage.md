# SEC Notes Coverage Plan

**Goal:** raise reliable Scout metric coverage with as-filed numerical facts from official SEC Financial Statement and Notes Data Sets, while preserving the existing Company Facts preference, point-in-time boundaries, and formula guards.

## Release gates

- Import is append-only, idempotent, accession-linked, and restricted to eligible CIKs.
- Only whole-entity numeric facts (`dimh=0x00000000`, no `coreg`) are eligible for automatic derivation.
- Every accepted custom concept must match an exact allowlisted label and an allowed note role; unknown concepts remain excluded.
- Company Facts and face-statement facts always win. Notes only fill a completely absent canonical series on an already-existing reporting period.
- A source conflict blocks the candidate value. A failed import cannot replace a previously valid snapshot.
- No existing metric count may decrease. Every added value must retain accession, filed date, taxonomy tag, unit, period, and source hash.
- Coverage is measured against the unchanged 4,768-bundle, 123,968-cell baseline.

## Tasks

1. Add schema for Notes import runs and immutable numerical facts.
2. Build a streaming archive importer using `sub.tsv`, `ren.tsv`, `pre.tsv`, `tag.tsv`, and `num.tsv`.
3. Add conservative report-category, dimension, form, period, unit, and label filters.
4. Add a period-safe supplement resolver that fills only fully absent canonical series.
5. Import the smallest current archive, measure incremental yield, then expand only to annual-filing months when the lift is positive.
6. Recompute all 26 metrics per stock and publish coverage distribution, missing families, regressions, and source lineage.
7. If the 80% value gate remains unmet, quantify the irreducible disclosure/applicability gap and evaluate the next source using the same gates.
