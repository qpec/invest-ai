# invest-ai: what a separate low-cap (small/micro-cap) lane would require

Research over `/home/user/invest-ai` (repo `qpec/invest-ai`, working name stock-agentcy).
All references `file:line` relative to repo root; scout code in `stock-scout/`.

---

## 1 · Data reach below $300M

### The universe already contains micro caps

- `data/universe.csv` = **7,033 names** (7,034 lines incl. header). Built in two layers:
  1. FinanceDatabase curated base (`universe.py:135-167`) — default caps Mega/Large/Mid
     (`universe.py:54`), `--broad` adds Small Cap (`universe.py:55`), US+NL, Financials/
     Real Estate excluded in broad mode.
  2. **SEC merge** (`universe.py:205-284`, owner-directed 2026-08-05): appends *every*
     NYSE/Nasdaq/NYSE American filer from `company_tickers_exchange.json`, one canonical
     line per CIK, **regardless of market cap**. New rows get only name+exchange;
     sector/industry/country/market_cap stay EMPTY, "refuse-never-guess applies to
     metadata too" (`universe.py:212-216`).
- Measured: **4,099 of 7,033 rows have an empty market_cap column** (the SEC-merge
  additions), 610 tagged "Small Cap", 449 Mid, 306 Large, 35 Mega. So micro caps are in
  the pipeline today — scored, shown on the site — they just never receive desk work
  orders.
- **OTC/pink sheets are out by design** (`universe.py:198-201`,
  `_SEC_KEEP_EXCHANGES = {"NYSE","Nasdaq","NYSE American"}`). A low-cap lane that wants
  OTC names is a policy change with data consequences (see prices below), not a flag.

### The $300M floor is desk-side only, one constant

- `thesis.py:107-108`: `DESK_MIN_MARKET_CAP = 300e6`, `DESK_MIN_PRICE = 5.0` (V-6,
  2026-08-08 valuation review). Applied in `_clears_desk_floor` (`thesis.py:517-532`)
  inside `top_symbols` (`thesis.py:559-582`) — *after* the Munger gate
  (`_survives_inversion`, `thesis.py:535-556`), and only when the row carries the
  figure ("a missing market cap or price never silently excludes a name").
- A low-cap lane therefore needs **no data-layer change to select sub-$300M names**: a
  second `top_symbols`-style selector with its own band (e.g. $50M–$300M) is ~20 lines.
  The comment at `thesis.py:566-573` warns the docstring reason the floor exists:
  "microcap liquidity, data pathologies, delisting risk" — the lane's philosophy must
  answer those, not delete the guard.

### Fundamentals coverage and missing-data behaviour

- Facts come from (tier 1) the owner's bulk SEC CSV export (`secsv.py`, 3.07M rows /
  418MB, a curated 19-tag selection), (tier 2) live EDGAR companyfacts per CIK, pruned
  and disk-cached (`enrich.fetch_companyfacts`, `enrich.py:122-146`;
  `prune_payload` `enrich.py:194-279`), (tier 3) yfinance vendor aggregates
  **display-only, never scored** (`enrich.py:519-539`).
- Names absent from the export are bootstrapped cache-only from EDGAR
  (`enrich.bootstrap_bundles`, `enrich.py:392-429`); `rolling_refresh`
  (`enrich.py:450-495`, budget 1500/night) makes "a universe expansion converge to full
  coverage over a few nights". Micro-cap filers ARE SEC filers, so fundamentals reach is
  structurally the same as large caps; what is thinner is *tag usage* (small filers tag
  fewer concepts) and split feeds.
- Missing data is handled honestly at every layer, all reusable as-is:
  - metric unmeasured ⇒ `None`, never 0 (invariant 5); scorecard shrinks
    `available_max`, bands computed on % of available (`scorecard.py:527-529`);
    evidence tiers full ≥0.85 / partial ≥0.60 / thin (`scorecard.py:125`) sort **before**
    percentage (`rank_key`, `scorecard.py:137-143`).
  - missing REQUIRED scoring legs ⇒ grade `INSUFFICIENT` (`scoring.py:679`).
  - no price ⇒ band `NO PRICE`, "quality profile, not a verdict"
    (`scorecard.py:147`, `secsv.py:22-31`).
  - inversion: thin evidence collapses Robust/Ordinary → `Unknown`
    (`inversion.py:1354-1365`); a named failure mode still stands. Ladder
    `inversion.py:99`: ≥3 severe Ruinous, 2 severe or ≥4 cautions Fragile.
  - **Expect low-cap names to cluster in thin/partial evidence, INSUFFICIENT, and
    Unknown.** A low-cap lane must decide whether "thin evidence" is a rankable state or
    a refusal — today's rank order buries thin names deliberately.
- **Sector cohorts degrade below $300M**: the 4,099 SEC-merge rows have no sector, so
  they fall into the `'None'` percentile cohort (`secsv.py:493-495`,
  `scoring.sector_percentile` `scoring.py:423`). Any low-cap philosophy leaning on
  within-sector percentiles inherits a garbage cohort for most of its universe unless
  sector metadata is backfilled (SIC code from EDGAR submissions is a candidate; not
  currently fetched — honest unknown).

### Share-count / dilution history (serial-diluter detection)

Mostly already built:
- `pit.shares_series` (`pit.py:518-531`): full dei
  `EntityCommonStockSharesOutstanding` history, class rows summed per filed date,
  filed-date discipline; exempt from the pruning horizon (`enrich.py:203-205`), so
  the **whole history is available in every bundle** (`shares_series` key).
- Fallbacks: `shares_fallback` multi-class (`pit.py:550-561`),
  `weighted_shares_point` income-statement weighted average (`pit.py:564-579`).
  Staleness guards: `SHARES_MAX_AGE_DAYS` refusal (`pit.py:898-921`),
  `shares_series_stale` stamp (`pit.py:931,946`).
- Trend: `scoring._share_trend_pct` on the split-adjusted series (`scoring.py:316`);
  split restatement via `adjusted_shares_series` (`scoring.py:263`). **Hard dilution
  veto** at >20%/yr (`scoring.py:28,401-403`), penalty 5–20%/yr (`scoring.py:415-417`),
  both suppressed for multi-class (`SHARE_CLASS`).
- Registry metrics a trigger may already test: `share_count_trend_pct_per_year`,
  `sbc_pct_of_revenue`, `buybacks_pct_of_ocf` (`thesis.py:79-85`).
- Gap for a serial-diluter lens: the trend is one annualized CAGR over the window; a
  "diluted in N of last M years" persistence metric would be a new pure function over
  `bundle["shares_series"]` — data is present, arithmetic is not. **Caveat**: split
  events ride the price fetch; the bulk export has none (`secsv.py:52-56`), so a name
  served only by a splitless grid can read a split as dilution — the docstrings call
  this out explicitly (`pit.py:856-863`).

### Liquidity / average daily volume

- **Not available and not derivable from stored data.** Bars carry only
  `{"close", "adj_close"}` (`pit.py PRICE_FIELDS`, `pricesrc.py:74`). The stockanalysis
  payload *contains* a `"v"` field which `bars_from_history` drops
  (`pricesrc.py:264-293`); the vendored Yahoo weekly fetch returns adj_close+currency
  only (`pricesrc.py:397-403` note). Grep confirms no volume anywhere in the pipeline.
- Options: (a) extend the bar schema to carry weekly volume and refetch the grid —
  touches `pricesrc.bars_from_history`, `bars_from_frame`, `pit` bar readers,
  `prices.refresh`, plus a grid backfill; (b) a tier-3 display-only vendor aggregate
  (`enrich.vendor_metrics` pattern, `enrich.py:519-539`) — but tier 3 "never enters
  scoring" (invariant 6), so it could not gate selection; (c) use price × shares as a
  proxy — insufficient for liquidity. A **mechanical dollar-volume eligibility floor
  for the low-cap lane is real new data work**, and by invariant 7 it may inform
  *eligibility*, never become a *trigger*.
- Price coverage is thinner at the bottom: `prices.py:121-127` records that **~760–814
  of the 7,033 symbols are permanently unfetchable** (delisted, foreign listings, pink
  sheets) against a nightly budget of 800; `.miss` tombstones park them 30 days.
  `PRICE_MAX_AGE_DAYS = 45` (`pit.py:119`) refuses a stale close → NO PRICE. A low-cap
  lane concentrates exactly where these failures live.

---

## 2 · The site generator (`webapp.py`, 2,864 lines)

### Build shape

- `assemble()` (`webapp.py:505-747`) produces **one model dict**: `rows` (compact
  per-symbol records incl. `mc`, `band`, `verdict`, `reg`), `details` (full per-symbol
  drill-down: card, inversion probes, provenance-labelled registry, DCF `mos`, implied
  growth `ig`), `charts`, `thesis` (top list + drafts + public readers),
  `portfolio_monitor`, `counts`, `snapshot_id`.
- `write_site()` (`webapp.py:2411-2468`) writes `docs/index.html` plus lazy per-letter
  shards `docs/data/d-<letter>.json` (`webapp.py:2439-2455`); details for picks + top-1%
  are embedded inline; all writes atomic (tmp + `os.replace`). Entirely
  self-contained: inline CSS (`webapp.py:757`) and JS (`webapp.py:1174`), no CDN.
- `render()` (`webapp.py:2389`) does string-replacement into `TEMPLATE`
  (`webapp.py:2210-2386`): a 3-step **stepper nav** (`data-tab` buttons,
  `webapp.py:2231-2240`) over three `<section class="tabpane">` panes — `tab-scout`,
  `tab-thesis`, `tab-portfolio_monitor` — toggled by JS. The Scout pane is a
  virtual-scrolled sortable table with filter dropdowns; the top-1% list partitions
  Fragile/Ruinous entries visually **without merging judgements** (`webapp.py:695-707`).

### Adding a low-cap surface — two viable shapes

1. **Fourth tab**: add a stepper button + `tab-lowcap` section in `TEMPLATE`, a
   `model["lowcap"]` key in `assemble()` (its own selection + intro prose stating the
   lane's philosophy), and a render function in the JS blob. One generator, both
   surfaces (public demo and served desk) get it at once — that is the stated design
   goal (`CLAUDE.md` §10: "One generator, two surfaces, so a UI change lands on both").
2. **Separate page** (`docs/lowcap/index.html`): a second TEMPLATE/render pass in
   `write_site`, sharing the `docs/data/` shards (details are keyed by symbol, lane-
   agnostic). More isolation, but the publisher/verification path
   (`deploy/local/scout-production.sh`) and release gate only check `docs/index.html`
   exists (`local_production.py:334`) — the gate would need a second `index_exists`.
- Either way the public projections must stay **allowlists**: `strip_owner_fields`
  (`webapp.py:228`), `PUBLIC_THESIS_FIELDS` (`webapp.py:234`),
  `public_thesis_reader/public_valuation_lens/public_portfolio_thesis`
  (`webapp.py:326,365,385`). A low-cap thesis reader reuses these unchanged.

### `--demo` vs `--serve` (`webapp.py:2807-2860`)

- Static build (default): `model["desk"] = {"enabled": False}` — actions render
  disabled; output to `../docs`.
- `--demo`: same read-only build + persistent banner + desk actions that **replay**
  recorded output from `sample-data/demo-playback.json` (`webapp.py:2840-2853`).
- `--serve PORT`: identical HTML plus a per-run capability token, bound to
  127.0.0.1, driving the real CLIs via `DESK_ACTIONS` (`webapp.py:2482-2509`:
  refresh / thesis / thesis-batch / monitor-brief / monitor-run / in-process rebuild).
  Deliberately **cannot ratify** (`webapp.py:2478-2480`, FR9/invariant 11). A served
  build must never be written into published `docs/` (guarded; `webapp.py:2815-2818`).
  A low-cap lane adding desk actions (e.g. `lowcap-brief`) extends `DESK_ACTIONS` +
  `desk_command` validation (`webapp.py:2512-2527`).

---

## 3 · Production (`production.py`, `local_production.py`, `agentcy/schema/010_production_snapshot.sql`)

### The pipeline

- `ProductionOrchestrator.STAGES = ("refresh","score","select_top","evaluate_theses",
  "monitor","build_site")` (`production.py:65-67`), then `validate` →
  `stage_snapshot` → `promote_snapshot` → `publish`, one exception boundary recording
  the exact failed stage (`production.py:147-155`). `ProductionStages` is a **frozen
  dataclass of 8 callables** (`production.py:21-30`); concrete local adapters in
  `local_production.make_local_stages` (`local_production.py:153-349`).
- What each stage does locally: `refresh` promotes DB prices into the grid
  (merge-never-replace, `export_price_grid` `local_production.py:38-83`) + rolling
  filings refresh; `score` writes an eligible-universe projection and runs
  `webapp.assemble`; `select_top` reads `model["thesis"]["top"]` into members;
  `evaluate_theses` fingerprints research inputs (`thesis.research_fingerprint`
  `thesis.py:585`) and runs the thesis runner for CREATED/REFRESHED names;
  `monitor` runs `monitor.py run`; `build_site` writes the artifact +
  `production-manifest.json`; `validate` calls `agentcy.production.validate_release`
  (`local_production.py:323-343`); publish is deferred to the shell wrapper, which
  **reads the live page back and fails if it does not serve the new snapshot_id**
  (invariant 13, `CLAUDE.md` "Shipping a change").

### State (append-only, SQLite)

- `010_production_snapshot.sql`: `production_run` (status RUNNING/FAILED/VALIDATED/
  PUBLISHED, identity-immutable, undeletable), `production_top_member`
  (**PK (run_id, security_key), UNIQUE (run_id, rank)**, no-update/no-delete triggers,
  lines 12-20, 47-53), `production_thesis_evaluation` (outcome CREATED/REFRESHED/
  REUSED/FAILED, append-only, lines 22-32), `production_snapshot` with partial unique
  index `one_active_production_snapshot` enforcing exactly one active row (lines 44-45).

### How a parallel low-cap lane fits without breaking append-only

- **Do not reuse `production_top_member` for a second selection**: `UNIQUE(run_id,
  rank)` makes two lanes' rank sequences collide within one run, and the append-only
  triggers forbid any retrofit. The clean move is a **new migration** (next-numbered
  file in `agentcy/schema/`) adding e.g. `production_lowcap_member` with the same
  trigger pattern — append-only is achieved by adding tables, never altering existing
  ones. (Alternative: add a `lane` column in a new table keyed
  (run_id, lane, security_key) with UNIQUE(run_id, lane, rank).)
- Stage-wise, two options:
  1. **Same run, extra stage(s)**: extend the `ProductionStages` dataclass and the
     `STAGES` tuple (e.g. `select_lowcap` after `select_top`) and
     `_record_domain_results` (`production.py:77-95`). Small, but every existing test
     constructing `ProductionStages` must supply the new field (frozen dataclass,
     positional).
  2. **Second orchestrator run** with its own run_id/snapshot_id — but
     `one_active_production_snapshot` means two active snapshots cannot coexist; a
     second lane publishing its own page would need either to ride the same snapshot
     (preferred: one build, one manifest, low-cap section inside it) or a schema change
     to scope `active` per lane. **Riding the same snapshot is the low-friction
     answer**: low-cap selection happens inside `score`/`select_top`/`build_site`
     against the same assembled model, lands in its own append-only table, and appears
     on the same verified page.
- The release gate (`release.validate_release`) would gain lane checks (e.g.
  "lowcap selection non-empty or explicitly empty-with-reason") — it already blocks
  publication on its own terms; a failed run leaves the last good snapshot untouched
  (invariant 10).

---

## 4 · The agent seam (`thesis.py`, `deskwork.py`, `.claude/skills/thesis-desk/SKILL.md`)

### The three beats

1. `brief` (`thesis.py:386-458`): writes `theses/drafts/<SYM>/WORK-ORDER.md` — the
   research packet (both judgements **unmerged** + all 26 registry values with units,
   `packet()` `thesis.py:329-357`), optional 10-K text via guarded edgartools import
   (`_grounding` `thesis.py:360-381`), the Constitution (`FRAMEWORK` `thesis.py:178`),
   trigger rules (`thesis.py:194`), and the JSON schema rendered as prose
   (`deskwork.schema_block`). Plus `packet.json` snapshot of metric values.
2. The agent (subscription CLI harness — Claude Code/OpenClaw/Codex, **no API client**)
   researches and writes `report.md`, `summary.md`, `thesis.json`.
3. `record` (`thesis.py:461-514`): mechanical re-validation, non-zero exit on refusal —
   artifacts exist/non-empty, summary heading, `validate()` (`thesis.py:243-320`: moat
   evidence rule, ≥3 triggers with ≥1 metric, registry-only metrics, no quote-derived
   trigger (`QUOTE_DERIVED_METRICS` `thesis.py:100`), narrative→review only, no
   owner-only fields), trigger-on-n/a-metric refusal against the packet snapshot
   (`thesis.py:492-498`), and the **approved-model rule**: model read from the harness
   transcript, not the agent's word (`deskwork.observed_model` `deskwork.py:105-135`;
   `APPROVED_MODELS` per provider `deskwork.py:52-55`; mismatch with `--model` is
   itself a refusal).
4. `ratify` (`thesis.py:627-697`): human CLI Gate — asks conviction + circle
   (FR9), re-derives model approval, no-moat requires typed `override`, goalpost guard
   versions and archives prior theses and refuses silent re-arming of a broken one
   (`thesis.py:730-767`).

### Reusing the seam for persona-style / multi-lens low-cap analysis

- The seam is deliberately generic: `deskwork.order(title, why, steps, artifacts,
  rules, body, finish)` (`deskwork.py:232-252`) + `write_atomic/read_json/
  schema_block` + `resolve_model`. `monitor.py` already reuses it for a second task
  type. A low-cap desk module (e.g. `lowcap_thesis.py`) can:
  - define its **own schema and FRAMEWORK text** — this is where a different analysis
    philosophy lives (e.g. a Graham net-net lens, a serial-diluter lens, an
    owner-operator lens as separate persona sections). Personas are *prompt content in
    the work order*, executed by the one harness — invariant 8 forbids calling a second
    model per persona over HTTP.
  - demand **one artifact per lens** (`artifacts` list) so each lens is separately
    mechanically validated in its `record`; the schema can require each lens's verdict
    field. Crucially, invariant 2 generalizes: lenses may sit side by side, **never
    averaged into a composite** — the existing scorecard/inversion split is the
    template.
  - keep its own METRICS subset or extend the registry (registry extras can never
    shadow scoring keys — `registry_evaluate` merge order, `thesis.py:217-224`; new
    metrics must be computed in the pure layer, and supplements never enter scoring
    sums, invariant 6).
  - the eligibility floor inverts: `_clears_desk_floor` becomes a band check
    (min *and* max cap), and the Munger gate (`_survives_inversion`) stays in front —
    invariant 12 says Hell-No runs BEFORE the dossier, and a low-cap lane is exactly
    where Fragile/Ruinous/veto density will be highest. If the lane's philosophy wants
    to *research* fragile names anyway, that is a constitutional change to journal in
    `docs/plans/`, not a code tweak.
  - `record`-time model enforcement, FR9 ratify, and the monitor's trigger mechanics
    (persistence streaks, sticky broken, narrative→review) are reusable unchanged if
    low-cap theses live in the same `theses/` tree (or a parallel `theses-lowcap/`
    tree passed via `--theses-dir` — every CLI already parameterizes it).

---

## 5 · Constraints — every CLAUDE.md invariant that binds a new low-cap lane

| # | Invariant | Bite on the low-cap lane |
|---|---|---|
| 1 | Never executes trades (FR11) | Lane advises/monitors only; no broker/order path, no position sizing. |
| 2 | Two judgements never merged | Scorecard vs inversion stay separate on every low-cap surface; extends to persona lenses — display side by side, never sum/average/reconcile. |
| 3 | Owner-only fields (FR9) never public | `conviction`/`circle_of_competence` only at ratify; low-cap page must reuse `strip_owner_fields` + allowlist projections (`webapp.py:228,234`). |
| 4 | Decision layer pure | Any new low-cap scoring/lens arithmetic goes in no-I/O modules: same Bundle in ⇒ same numbers out. No clock, no network. |
| 5 | Refuse, never guess | Thin micro-cap data ⇒ `None`, shrunken denominators, `Unknown` verdicts said out loud — never defaults. Sector metadata for SEC-merge rows stays empty rather than guessed. |
| 6 | Supplements never enter the decision | A vendor-sourced liquidity/ADV number (tier 3) is display-only; it cannot gate scoring or fire triggers. A *filed*-data or stored-bar liquidity metric could gate eligibility but composites stay display-only. |
| 7 | No price triggers | Low-cap volatility is not an invalidation; quote-derived metrics refused as triggers (`thesis.py:100,302-305`). A liquidity floor is eligibility, never a trigger. |
| 8 | No LLM API client | Personas run as work-order prose through the one subscription harness; re-adding a transport would have to re-implement `record`. |
| 9 | Four runtime pip packages, licence policy | `yfinance, pandas, scipy, quantstats`; GPL-family (incl. LGPL) banned, `certifi` MPL-2.0 the journaled exception; `tools/license_gate.py` enforces (NFR7). No new runtime dep for the lane without journaling. |
| 10 | Append-only production state | New lane state = new tables via new numbered migration with the same no-update/no-delete trigger pattern; exactly one active snapshot; failed run leaves last good untouched. |
| 11 | Ratification human + CLI-only | No browser ratify for low-cap theses either; `--serve` deliberately lacks the door. |
| 12 | Munger gates the desk feed | Hell-No before the dossier in the lane's `top_symbols` equivalent; `Unknown` is not a veto. |
| 13 | Published site tracks code; publication verified | The lane's page ships inside the verified snapshot; a change that alters the page is not done until `SCOUT_SITE_URL` serves the new `snapshot_id`. Container agents cannot run the full cycle (no real data) and must say so in hand-off. |

Also binding: tests are load-bearing (888 scout + 1110 agentcy, both required); the
decision journal (`docs/plans/`, `docs/superpowers/plans/`) records policy changes like
a new eligibility band — `top_symbols`' docstring (`thesis.py:566-573`) notes that
widening/narrowing the feed re-fingerprints drafts as INPUTS_CHANGED, "the intended
cost of a ratified policy change".

---

## Honest unknowns

- **Actual coverage rates below $300M are unmeasurable here**: the SEC export, enrich
  cache, price grid and theses live only on the owner's machine; this container has
  `sample-data/` only. The ~760–814 unfetchable-price figure and the 4,099
  metadata-empty rows are the only measured lower-bound signals in-repo.
- Whether EDGAR companyfacts tag coverage for true micro caps supports the 14-metric
  scorecard at "partial" evidence or collapses most names to INSUFFICIENT/thin —
  needs a measurement run on real data.
- Sector backfill for SEC-merge rows (e.g. SIC from EDGAR submissions endpoint) is not
  built; percentile-based lenses for the low-cap lane depend on solving it or on
  choosing absolute (scorecard-style) anchors instead — the latter fits the existing
  design better.
- I did not fully read `monitor.py`, `agentcy/production.py`'s release-gate check list,
  or the 1,000-line JS blob's tab router; conclusions about extending them are from
  their call sites and docstrings.
- `quantstats` appears in CLAUDE.md's four-package list but not in
  `stock-scout/requirements.txt` (which lists yfinance/pandas/scipy) — likely an
  agentcy-side dep; not verified.
