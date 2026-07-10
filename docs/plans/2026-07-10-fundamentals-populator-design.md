# Fundamentals-Archive Populator — Design (Scout v2 §8 item 2)

**Status:** approved 2026-07-10. Follows `docs/plans/2026-07-10-scout-v2-graded-screening-design.md` §5/§8.

**Goal.** Fill the append-only fundamentals archive for the broad universe on a paced background cadence so `agentcy scout run grade` produces real ranked picks instead of an all-INSUFFICIENT table. This is the data feed the Stage-1 grader was built to read; the grader itself is done and on `main` and is **not** modified by this work.

**Owner-chosen shape.** Bounded high-liquidity **starter set first** (real picks within ~1 evening), then **autonomous nightly rolling expansion** to the whole universe, then keep-fresh refresh. Set-and-forget on the always-on box.

---

## 1. Core architecture

A paced background job walks the universe in liquidity order and, per name, fetches statements + shares + daily price into the **existing** append-only archive (`fundamentals_period`, `shares_series`, `price_cache`). `run_graded` then assembles the `market_data` mapping **from the archive** at grade-time — replacing the current `market_data={}` stub. The graded table fills in as coverage grows.

**No new dependencies** (reuses `yfinance`, `pandas`, `scipy`). **No new fetch door** (all Yahoo access stays inside `agentcy/fetch/yf.py` and its box-wide `yahoo.lock` pacing: ≥2s + 0.5–1.5s jitter per call). **No change to the grading math** (`agentcy/scout_grade.py` pillar/veto/tier/composite functions are untouched).

Chosen over two rejected alternatives:
- **Dedicated `market_cap`/`market_data` cache table** — duplicates `total_debt`/`cash` already on the archived balance sheet, adds a second store to keep fresh, and lets the `market_cap` snapshot go stale independently. More surface, less DRY.
- **Live fetch at grade-time** — ~8,000 names × ~3 paced calls ≈ 15–18h blocking; the Scout design already rejected this for scale.

## 2. Selection & ordering

The universe file (`<state_dir>/universe/equities.bz2`, FinanceDatabase, SHA-pinned, loaded by `scout.load_universe`) carries a categorical `market_cap` **band**, not a number. Rank **mega → large → mid → small** (highest liquidity and most complete yfinance fundamentals first), stable/deterministic within a band (by symbol).

- **Starter set** = the top `populate_starter_size` (default **500**) names by that rank.
- After the starter set, the cursor keeps walking down-band until every universe name has been attempted, then loops to **refresh oldest-fetched first**.
- Circle-of-competence tier does **not** filter selection (the whole point of Scout v2 is broad reach); it only affects how results are *presented* by the already-built grader.

## 3. What is fetched & stored per name

| Fetch (`fetch/yf.py`) | Store (`fetch/store.py`) | Archive table |
|---|---|---|
| `fetch_statements` → income/balance/cashflow | `store_statements` | `fundamentals_period` |
| `fetch_shares_full` → share history | `store_shares` | `shares_series` |
| `fetch_daily_bars` → daily close + currency | `store_price_bars` | `price_cache` |

All append-only, deduped, each row stamped `fetched_at` and the populate `run_id`. `market_cap` is **not** stored — it is computed at grade-time (§5).

## 4. Cadence, resumability & the progress log

- **Schedule.** Nightly `agentcy run populate` via a new `agentcy-populate.timer` (~01:30, after the daily letter), **time-boxed** by `populate_nightly_minutes` (default **90**). At ~7.5s paced/name that is ≈700 names/night → full first pass ≈ **11 nights**; the starter set completes on **night 1**.
- **Manual.** `agentcy run populate [--minutes M | --budget N]` runs a slice on demand from the desk or over SSH.
- **Progress log.** New append-only table `universe_fetch(yf_ticker, attempted_at, outcome, run_id)` — one row per attempt; latest/aggregate via a `v_universe_fetch` view (same append-only-then-view pattern as `shares_series`/`price_cache`; UPDATE/DELETE blocked by trigger). Drives the cursor and records `ok | no_data | failed | rate_limited`.
- **Cursor rule.** Next name = highest-liquidity name that is (a) never attempted, else (b) least-recently refreshed and STALE — skipping dead-listed names (§6). Coverage/"is this name cached" is derived from the archive (≥4 quarterly periods across all three statements + a shares obs + a recent price).

## 5. Grade-time `market_data` assembly

New helper `_market_data_from_archive(conn, tickers, *, as_of) -> dict[str, dict]`:
- `market_cap = latest v_price close × latest shares` (native price currency).
- `total_debt`, `cash` = latest archived balance-sheet rows.
- Missing price/shares/balance → that key `None` → the name is already handled as **INSUFFICIENT** by `grade_universe` (RF5), never a silent grade.

`run_graded` calls this instead of accepting `{}`. The CLI `scout run grade` then grades every cached name and lists uncached names as INSUFFICIENT.

**Currency guard.** `owner_fcf_yield` (owner-FCF / EV) is currency-agnostic (numerator and denominator share the statement currency once debt/cash are archive-sourced), but `p_owner_fcf` (market_cap / owner-FCF) mixes price currency with statement currency. If a name's **price currency ≠ statement reporting currency**, mark it INSUFFICIENT rather than mis-rank it. FX conversion is a deliberately-deferred refinement (would reuse the existing FX path), not in this build.

## 6. Error handling

- Empty/None/zero-row/NaN fetches are failures (existing `yf.py` "empty-is-failure"); recorded as `no_data`/`failed` outcomes.
- **Dead list.** A name with ≥3 recorded failures is deprioritized so delisted/hopeless names don't burn the nightly budget; still retried on a long backstop (e.g. re-eligible after 90 days) in case of transient upstream gaps.
- **Rate limiting.** Existing 30s→5min→30min backoff applies; sustained `RateLimited` stops the night early, emits the NFR6 DEGRADED banner, and the cursor resumes next night where it left off.
- **Freshness.** STALE archive data flows through the existing freshness gate → INSUFFICIENT at grade-time; the populator never bypasses it.

## 7. Interface & notifications

- **Job:** `agentcy run populate` (joins the `run daily|weekly|quarterly|event` family; `jobs/populate.py` exposing `main(*, clock, state_dir) -> int`).
- **Timer/units:** `agentcy-populate.service` (oneshot) + `agentcy-populate.timer`; wired into `install.sh` and the runbook.
- **Config keys:** `populate_enabled` (default true), `populate_starter_size` (500), `populate_nightly_minutes` (90), `populate_dead_after_failures` (3). All via the existing journaled `config set`.
- **Telegram milestones (sparse).** One note when the **starter set** first completes ("starter set ready — N names gradable"); one when the **first full pass** completes ("universe cached — N gradable, M skipped"); plus the standard DEGRADED banner on sustained rate-limiting. Routed through the existing outbox. No nightly spam.

## 8. Testing (all offline, no network)

- Selection/ordering over a tiny in-memory universe `DataFrame` (band ranking, starter-set cut, stable order).
- Populate loop against a **fake fetch layer** (monkeypatched `yf.fetch_*`): asserts the store calls, `universe_fetch` outcome logging, time-box/budget stop, dead-list skip, and rate-limit early-stop.
- `_market_data_from_archive` from seeded archive rows; the currency guard (price-vs-statement mismatch → INSUFFICIENT); the `run_graded` end-to-end producing a real grade for a fully-seeded name.
- Milestone Telegram render golden; a structural check that no new pip dependency and no new fetch door were introduced.
- Autouse no-network guard remains in force; timestamps via `db.to_iso(clock.now())`.

## 9. Scope boundaries (YAGNI)

**In:** the populate job + timer/CLI, the `universe_fetch` log + view, the grade-time archive→`market_data` assembler with currency guard, sparse Telegram milestones, config keys, install/runbook wiring.

**Not in this build:** the Stage-2 `QualitativeReviewer` (LLM shortlist — separate §8 item 3 follow-on); any paid data feed (NFR3 free-first); FX conversion for cross-currency names (guarded to INSUFFICIENT instead); and any change to the Stage-1 grading math.
