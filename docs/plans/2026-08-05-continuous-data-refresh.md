# Continuous data refresh + universe beyond the export

**Status:** implemented 2026-08-05. Owner-directed same day: *"upgrade it further
with additional stocks and better data fetching … the box should also get data
more frequently … monitored stocks should always be most recently updated before
monitor check."*

## What changes

**1. The universe outgrows the export.** `universe.py --sec-merge` extends
universe.csv with every NYSE / Nasdaq / NYSE American filer from the SEC's own
ticker+exchange map — stdlib fetch, no new dependency, one row per CIK (share
classes are the same business twice), sector/market-cap left EMPTY rather than
guessed. Existing curated rows pass through untouched.

**2. Cache bootstrap (`enrich.bootstrap_payloads`).** A symbol the frozen bulk
export never carried joins from its cached EDGAR companyfacts: the payload is
already the shape the whole pipeline reads (secsv.load_facts documents the
equivalence), every tag is stamped `edgar-live` in the provenance ledger, and PIT
survives because companyfacts entries carry their own `filed` dates. **Additive
only** — a symbol the export knows is never touched, so the frozen decision layer
stays bit-identical for the original universe. Offline consumers (site build,
weekly monitor, picks) bootstrap `cache_only`: no cache entry yet ⇒ the name stays
absent and is counted, never guessed.

**3. Pruned payloads (`enrich.prune_payload` / `consumed_tags`).** Full
companyfacts run 2–8 MB; thousands would out-grow the box's memory and its backup
volume for tags nothing can read. `consumed_tags()` introspects pit's own concept
tables (all six chains + secsv's documented inline extras + the dei share tag) —
introspected, not copied, so a new concept chain widens the selection
automatically. The cache stores the selection, exactly what the export always was.
Consequence: `enrich_cache` leaves the backup-volume mirror (refetchable in
minutes; the volume keeps the irreplaceable theses + reports).

**4. The freshness cadence.** One engine (`enrich.py --rolling BUDGET`): thesis
names — committed first, then drafts — are ALWAYS refetched at the head of the
plan and never cut by the budget; the remainder goes to the stalest cache entries
(no file = infinitely stale, which is what makes an expansion converge in nights).

| When | Unit | What |
|---|---|---|
| nightly 02:15 | `scout-refresh` (new) | rolling sweep, `SCOUT_REFRESH_BUDGET` (default 1500 ≈ 10 min at EDGAR pacing) |
| Sat 06:00 | `scout-scrape` (rewired) | same engine, final pre-sweep pass, `SCOUT_SCRAPE_BUDGET` |
| Sat 12:00 | `scout-monitor-run` (pre-step) | `--force-refresh` of exactly the monitored names, minutes before their triggers are tested; failure is loud, never blocking (run stays cache-first) |

## What deliberately does not change

- **No price triggers exist**, so prices stay a desk-side concern; new names
  without a price grid lose only the pricing pillar, labelled (R7).
- The export regen and universe merge remain **desk rituals**, not box jobs.
- Tier discipline: export > edgar-live fill-only-missing > vendor display-only,
  unchanged; bootstrap adds a fourth *case* (no export at all), not a fourth tier.
