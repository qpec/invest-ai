# SEC Statement Coverage Plan

**Goal:** Raise reliable Scout metric coverage toward the hard 80% gate using locally
cached, filed SEC Financial Statement Data Sets, without imputation or relaxed guards.

## Constraints

- Preserve filing date, accession, source archive, statement, unit and period metadata.
- Never overwrite Company Facts values; statement facts only fill an absent canonical row.
- Use qtrs=0 for instants, qtrs=1 for discrete quarters and qtrs=4 for annual flows.
- Custom tags require an allowlisted normalized presentation label and matching statement.
- Unknown labels, dimensions and conflicting facts remain explicit gaps.

## Tasks

1. Add append-only statement fact/run schema and streaming ZIP importer.
2. Map standard tags plus conservative presentation-label aliases to Scout row labels.
3. Build a PIT supplement that fills absent annual/quarterly bundle rows and retains
   exact source fact IDs.
4. Import local 2022Q1 through 2026Q1 SEC archives and rerun every stock × 26 metrics.
5. Publish per-stock counts, total coverage, source lineage and remaining gap families.
6. Release only if total reliable value coverage is at least 80%; otherwise report the
   exact shortfall and continue to Notes/Inline XBRL for the missing source families.
