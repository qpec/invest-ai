# Fundamentals-Archive Populator - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fill the append-only fundamentals archive (`fundamentals_period` / `shares_series` / `price_cache`) for the broad universe on a paced background cadence, so `agentcy scout run grade` grades real cached names instead of an all-INSUFFICIENT table. Serves `docs/plans/2026-07-10-fundamentals-populator-design.md` (the binding design) and `docs/plans/2026-07-10-scout-v2-graded-screening-design.md` section 5/section 8.

**Architecture:** A new pure-ranking module (`agentcy/populate.py`), a new append-only progress table + view (`universe_fetch` / `v_universe_fetch`) via schema migration `002`, a new time-boxed job (`agentcy/jobs/populate.py`) that walks the universe in liquidity order through the single fetch door (`fetch/yf.py`) and the single store surface (`fetch/store.py`), a grade-time `market_data` assembler wired into `scout.run_graded`, sparse Telegram milestone notes, four journaled config keys, a `agentcy run populate` CLI verb, and the `agentcy-populate` systemd timer/service. The Stage-1 grading math in `agentcy/scout_grade.py` is NOT modified - only the assembler is added and `run_graded` re-wired.

**Tech Stack:** Python 3.13 (uv-managed CPython), stdlib + the four locked runtime pip packages (yfinance, pandas, scipy, quantstats). SQLite (append-only + trigger-guarded + view idiom). systemd oneshot job + timer. `uv run pytest` test runner.

---

## Review fixes (apply first - from the pre-execution fidelity review + live probes)

**Baseline is now 877 passed, 3 skipped** (Stage-1.5 landed on `main` after this plan was authored). Use 877 as the green baseline everywhere, NOT 856. Confirm with `uv run pytest -q` before Task 1 and reconcile every per-task running total to 877 + your new tests.

**B1 - the currency guard is wired-but-DORMANT; do NOT claim design section 5 is enforced.** Two live yfinance probes (2026-07-11) confirmed: `fast_info` exposes ONLY the price/trading currency (`currency`); the statement *reporting* currency (`financialCurrency`) is available only via the banned `.info` accessor. So under the fast_info-only rule there is NO rule-compliant source for the reporting currency. Therefore the assembler's `statement_currency` map stays default-`None` and the guard is DORMANT. Keep the guard MECHANISM (optional `statement_currency` map -> a mismatch omits that ticker -> INSUFFICIENT via the existing `market_data.get(sym) is None` path), but the plan/output must NOT state section 5 is satisfied. Add a one-line honest caveat where the graded output is framed: "cross-currency names (mainly US-listed ADRs of foreign filers) may mis-rank on p_owner_fcf until a reporting-currency source lands; owner_fcf_yield is currency-agnostic and unaffected." Plan note 2 is corrected below to match.

**M1 - the coverage predicate is FETCH coverage, not gradability.** `is_cached` (>=4 periods x3 statements + shares + recent price) counts whether the SOURCES were archived - looser than whether the pinned ROWS needed to grade are present (a cached name can still grade INSUFFICIENT if EBIT / Working Capital / etc. are absent within those periods). So the milestone notes and any cursor "done" wording must say "N names CACHED", never "N gradable".

**M3 - add a dedicated `'populate'` run_type.** In migration `002` (Task 2), also add `'populate'` to the `run_log.run_type` CHECK constraint (re-create the CHECK in the same migration that adds the new table, per the schema migration mechanism) so the populate job logs under its own run_type instead of reusing `'scout'`. Cleaner and future-proof.

**M4 - install.sh: match the real line.** Task 10 must READ the current `systemctl enable --now ... .timer` line in `install.sh` and append `agentcy-populate.timer` surgically, not replace a guessed literal.

---

## Plan notes (deferred details, simplest compliant choice)

These are assumptions made where the ground truth was ambiguous. Each is the simplest reading that stays design-compliant; a task that touches one restates it inline.

1. **market_cap band label strings.** The FinanceDatabase `market_cap` categorical vocabulary is not enumerated in `tests/fixtures/financedatabase_categoricals.json` (that fixture only lists sectors/industries). Existing tests (`tests/test_scout_grade_batch.py`, `tests/test_scout.py`) use `"large_cap"` and `"small_cap"`. **Choice:** rank on the four canonical bands `("mega_cap", "large_cap", "mid_cap", "small_cap")` (highest -> lowest liquidity), matched **case-insensitively after `.strip().lower()`**. **Any band string not in that set (including `None`, `""`, `"micro_cap"`, `"nano_cap"`) sorts to lowest priority** (design section 2 "unknown/missing band -> lowest priority"). Ties within a band and across unknown bands break by symbol ascending (deterministic).

2. **Price currency read from the archive (currency guard is wired-but-dormant - see Review fix B1).** `price_cache.currency` is written per bar by `store.store_price_bars` (from `fetch_daily_bars`, which reads `history_metadata` currency). The assembler (Task 7) reads the price currency off the **latest `v_price` row** via `store.latest_close(...).value.currency`. The statement reporting currency is **not** archived and (per the B1 live probes) has NO rule-compliant source under the fast_info-only rule. **Choice:** the assembler accepts an optional `statement_currency: dict[str, str] | None` (default `None` -> guard DORMANT, existing behavior preserved); when a ticker's entry is present AND differs from the price currency, that ticker's `market_data` entry is omitted (-> `grade_universe` emits INSUFFICIENT via the existing `market_data.get(sym) is None` path, RF5). `run_graded` passes `statement_currency=None` for now, so **the guard does not fire and design section 5 is NOT enforced by this build** - the mechanism is present, tested, and ready for the FX follow-on. Do NOT infer a statement currency from the universe row's `country` (fragile: a US-listed ADR of a EUR filer keeps home-country metadata). The honest caveat from B1 is printed alongside the graded output.

3. **Coverage "recent price" threshold.** Design section 4 cursor rule: cached = ">=4 quarterly periods across all three statements + a shares obs + a recent price bar." **Choice:** "recent price" reuses the existing price staleness ladder - `store.price_state(conn, ticker, as_of=as_of) is DataState.FRESH` (i.e. a bar within `PRICE_STALE_WEEKDAYS`=2 trading days). ">=4 quarterly periods across all three statements" = `len(db.fetch_statement_periods(conn, t, stype)) >= 4` for **each** of income/balance/cashflow. "a shares obs" = `db.fetch_shares_raw(conn, t)` non-empty.

4. **STALE-for-refresh signal in the cursor.** Design section 4: after never-attempted names, refresh "least-recently refreshed and STALE." **Choice:** a name is refresh-eligible when it is already covered (Task 3 `is_cached`) BUT its statements are STALE (`store.statement_history(conn, t, "income", as_of).state is not FRESH`) OR its price is STALE. Ordering among refresh candidates is by the `v_universe_fetch.last_attempt` timestamp ascending (oldest first); never-attempted-but-STALE cannot occur (uncovered names are already first-priority). Refresh candidates come strictly after all never-attempted names in `next_targets`.

5. **Dead-list re-eligibility backstop.** Design section 6: >=`populate_dead_after_failures` consecutive-ish failures deprioritizes; retried after a 90-day backstop. **Choice for this build (simplest compliant):** dead = failure_count >= threshold where failure_count = count of `v_universe_fetch`-latest-per-ticker rows... no - failures accumulate, so count is over the **raw** `universe_fetch` rows with `outcome IN ('failed','no_data')` since the ticker's last `ok`. A dead-listed ticker is **excluded from `next_targets`** unless its most recent attempt is older than 90 days (`db.from_iso(last_attempt) < as_of - 90d`), in which case it is re-eligible (appended after never-attempted, before/among refresh by last_attempt). This keeps delisted names from burning the budget while still retrying transient gaps.

6. **Telegram milestone note is a `notice`-class rendered output.** Milestones ride the existing outbox as `kind="notice"` (the schema's outbox `kind` CHECK already allows `'notice'`), output_class `"notice"` (lint's calm-register bans apply - no `!`, no red glyphs). Sparse: at most one starter-complete note and one first-full-pass note ever, detection is derived (Task 6), and the note is only enqueued on the transition run.

7. **Milestone state is derived, not stored.** "Starter set complete" = every name in the ranked starter set is `is_cached`. "First full pass complete" = every universe name has a `v_universe_fetch` row (attempted at least once). To make "enqueue only on the transition" idempotent without a new state column, the milestone enqueue uses a **fixed dedupe_key** (`"populate:milestone:starter"` / `"populate:milestone:full_pass"`); the outbox UNIQUE(dedupe_key) + `enqueue`'s sent-key guard means a second attempt to enqueue the same milestone is a no-op (queued -> superseded in place with identical text; sent -> the enqueue is skipped by catching the `ValueError`). Task 6 wraps the milestone enqueue in a try/except ValueError so a re-fire after delivery never raises.

8. **`populate` run_type + run_log.** `run_log.run_type` CHECK does NOT include `'populate'`; adding a value to a CHECK constraint requires a table rebuild. **Choice:** the populate job logs under the existing **`'scout'`** run_type (design section 1 frames the populator as Scout infrastructure; `run_log.run_type` already allows `'scout'`, and `runlog.due_keys` returns `[]` for `'scout'` so it is never swept by the daily/weekly/quarterly sweepers). The job does NOT use `runner.sweep_and_run` (that is for calendar-swept types); it opens its own run_log row directly via `runlog.start(conn, "scout", scheduled_for=<as_of date>, clock=clock)` and finishes it. The scheduled_for key is the Amsterdam date string (one populate run per night; a same-day manual re-run reclaims the key, which is the desired resumable behavior).

9. **No real sleeping / no network in tests.** The populate loop's wall-clock time-box uses `clock.now()` deltas (injected `FixedClock`/a fake advancing clock), never `time.sleep`. All fetches go through `yf.fetch_*`, which tests monkeypatch at the `agentcy.jobs.populate` import site (`populate.yf.fetch_statements` etc.) so the autouse no-network guard is never tripped. Pacing (the >=2s + jitter) lives inside `fetch/yf.py`'s lock and is bypassed entirely when `yf.*` is monkeypatched.

---

## Task ordering and the running invariant

Baseline before Task 1: **784 passed, 3 skipped** (`uv run pytest -q`). Every task ends with a full-suite run that MUST stay **0 failures** (pass count rises as tests are added; the 3 Windows skips persist). Run one test file/case with `uv run pytest tests/<file>::<name> -v`; the full suite with `uv run pytest -q`.

Tasks build strictly in order: ranking (1) -> progress table (2) -> coverage+cursor (3, needs 2) -> fetch-store unit (4) -> the job (5, needs 2/3/4) -> milestones (6, needs 3/5) -> assembler+wiring (7, independent of the job but needs nothing from 2-6) -> CLI (8, needs 5) -> config keys (9, needed by 5/6 at runtime but defaults can land last since tests inject values) -> systemd/install/runbook (10, needs 8) -> structural gate (11, last).

> **Config-key ordering note:** Tasks 5 and 6 read config keys (`populate_nightly_minutes`, `populate_starter_size`, `populate_dead_after_failures`) at runtime. To keep the suite green throughout, Tasks 5/6 tests **pass these values explicitly** as function arguments (the job's `main` reads config, but the inner pure functions take plain ints), and Task 9 lands the seeded defaults + the `main`-reads-config wiring test. If you prefer, do Task 9 before Task 5 - it is dependency-light. The plan orders it at 9 to group it with the other "surface" tasks; either order keeps the suite green.

---

## Task 1 - Universe ranking + starter set (`agentcy/populate.py`)

A pure function ranking universe rows mega->large->mid->small (stable by symbol), and a starter-set cut. No DB, no network.

**Files:**
- Create: `agentcy/populate.py`
- Create: `tests/test_populate_ranking.py`

### 1a. Write the failing test

`tests/test_populate_ranking.py`:

```python
"""Universe liquidity ranking + starter-set cut (populator design 2, plan note 1).
Pure functions over the universe DataFrame - no DB, no network."""
import pandas as pd

from agentcy import populate


def _uni(rows):
    return pd.DataFrame(rows, columns=["symbol", "market_cap"])


def test_ranks_bands_mega_large_mid_small_then_symbol():
    uni = _uni([
        ("DELTA", "small_cap"),
        ("BRAVO", "mega_cap"),
        ("CHARLIE", "large_cap"),
        ("ALPHA", "mega_cap"),
        ("ECHO", "mid_cap"),
    ])
    assert populate.rank_universe(uni) == ["ALPHA", "BRAVO", "CHARLIE", "ECHO", "DELTA"]


def test_band_match_is_case_and_whitespace_insensitive():
    uni = _uni([("A", " Mega_Cap "), ("B", "LARGE_CAP")])
    assert populate.rank_universe(uni) == ["A", "B"]


def test_unknown_or_missing_band_sorts_last_stable_by_symbol():
    uni = _uni([
        ("Z", "mega_cap"),
        ("M", None),
        ("K", "micro_cap"), # not a canonical band -> lowest priority
        ("A", ""), # empty -> lowest priority
    ])
    # mega first; the three unknown/missing share the lowest priority, tie-broken by symbol
    assert populate.rank_universe(uni) == ["Z", "A", "K", "M"]


def test_starter_set_cuts_top_n_of_the_ranking():
    uni = _uni([(s, "large_cap") for s in ["D", "C", "B", "A", "E"]])
    assert populate.starter_set(uni, size=3) == ["A", "B", "C"]


def test_starter_set_size_larger_than_universe_returns_all_ranked():
    uni = _uni([("B", "mega_cap"), ("A", "small_cap")])
    assert populate.starter_set(uni, size=99) == ["B", "A"]
```

### 1b. Run and see it fail

`uv run pytest tests/test_populate_ranking.py -v` - expected: `ModuleNotFoundError: No module named 'agentcy.populate'` (collection error / all fail).

### 1c. Minimal implementation

Create `agentcy/populate.py`:

```python
"""The fundamentals-archive populator (design 2026-07-10). Ranking is a pure function of
the universe DataFrame; the job (jobs/populate.py) walks the ranking through the single
fetch door and the single store surface. No new pip dependency, no new fetch door."""
from __future__ import annotations

import pandas as pd

# Highest-liquidity -> lowest; unknown/missing bands sort AFTER these (plan note 1).
_BAND_ORDER = ("mega_cap", "large_cap", "mid_cap", "small_cap")
_BAND_RANK = {b: i for i, b in enumerate(_BAND_ORDER)}
_UNKNOWN_RANK = len(_BAND_ORDER) # every non-canonical/missing band shares this bucket


def _band_key(value) -> int:
    """Canonical band -> its liquidity rank; anything else (None/''/unknown) -> lowest."""
    if value is None:
        return _UNKNOWN_RANK
    return _BAND_RANK.get(str(value).strip().lower(), _UNKNOWN_RANK)


def rank_universe(universe: pd.DataFrame) -> list[str]:
    """Symbols ranked mega -> large -> mid -> small, unknown/missing band last, stable by
    symbol within a bucket (design 2). Deterministic: the SAME universe always yields the
    SAME order, so the nightly cursor is reproducible."""
    rows = universe.to_dict("records")
    ordered = sorted(rows, key=lambda r: (_band_key(r.get("market_cap")), str(r["symbol"])))
    return [str(r["symbol"]) for r in ordered]


def starter_set(universe: pd.DataFrame, *, size: int) -> list[str]:
    """The top ``size`` names by liquidity rank (design 2 starter set). size >= len ->
    the whole ranked universe."""
    return rank_universe(universe)[:size]
```

### 1d. Run and see it pass

`uv run pytest tests/test_populate_ranking.py -v` - expected: 5 passed.

### 1e. Full suite

`uv run pytest -q` - expected: **789 passed, 3 skipped** (784 + 5), 0 failures.

### 1f. Commit

```
git add agentcy/populate.py tests/test_populate_ranking.py
git commit -m "$(cat <<'EOF'
feat(populate): universe liquidity ranking + starter-set cut

Pure functions: rank mega->large->mid->small stable by symbol, unknown/
missing band last; starter_set cuts the top N. Design 2026-07-10 section 2.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 2 - `universe_fetch` progress table + `v_universe_fetch` view (migration 002)

New append-only, trigger-guarded table matching the `price_cache`/`v_price` idiom, its latest-per-ticker view, a `db.append_universe_fetch` writer, and two read helpers.

**Files:**
- Create: `agentcy/schema/002_universe_fetch.sql`
- Modify: `agentcy/db.py` (add writer + `_UNIVERSE_FETCH_COLS` after the `append_price_rows`/`_PRICE_COLS` block ~line 168; add read helpers in the fetch-helpers section ~line 476, after `fetch_earnings_calendar`)
- Create: `tests/test_universe_fetch_store.py`

### 2a. Write the failing test

`tests/test_universe_fetch_store.py`:

```python
"""universe_fetch progress log + v_universe_fetch view (populator design 4).
Append-only, trigger-guarded, latest-per-ticker view - the price_cache/v_price idiom."""
import pytest


def _append(conn, ticker, outcome, at, run_id=None):
    from agentcy import db
    return db.append_universe_fetch(conn, yf_ticker=ticker, outcome=outcome,
                                    attempted_at=at, run_id=run_id)


def test_append_and_view_returns_latest_per_ticker(tmp_db):
    from agentcy import db
    _append(tmp_db, "AAA", "failed", "2026-07-01T00:00:00Z")
    _append(tmp_db, "AAA", "ok", "2026-07-02T00:00:00Z") # newer wins in the view
    _append(tmp_db, "BBB", "no_data", "2026-07-01T00:00:00Z")
    latest = db.fetch_universe_fetch_latest(tmp_db)
    assert latest["AAA"]["outcome"] == "ok"
    assert latest["AAA"]["last_attempt"] == "2026-07-02T00:00:00Z"
    assert latest["BBB"]["outcome"] == "no_data"


def test_failure_count_since_last_ok(tmp_db):
    from agentcy import db
    _append(tmp_db, "AAA", "failed", "2026-07-01T00:00:00Z")
    _append(tmp_db, "AAA", "no_data", "2026-07-02T00:00:00Z")
    _append(tmp_db, "AAA", "ok", "2026-07-03T00:00:00Z") # resets the streak
    _append(tmp_db, "AAA", "failed", "2026-07-04T00:00:00Z")
    _append(tmp_db, "AAA", "rate_limited", "2026-07-05T00:00:00Z") # not a dead-list failure
    counts = db.fetch_universe_fetch_failure_counts(tmp_db)
    # only 'failed'/'no_data' after the last 'ok' count toward the dead list (design 6)
    assert counts["AAA"] == 1


def test_table_is_append_only(tmp_db):
    _append(tmp_db, "AAA", "ok", "2026-07-01T00:00:00Z")
    with pytest.raises(Exception):
        tmp_db.execute("UPDATE universe_fetch SET outcome='failed'")
    with pytest.raises(Exception):
        tmp_db.execute("DELETE FROM universe_fetch")


def test_unknown_outcome_rejected_by_check(tmp_db):
    with pytest.raises(Exception):
        _append(tmp_db, "AAA", "bogus", "2026-07-01T00:00:00Z")
```

### 2b. Run and see it fail

`uv run pytest tests/test_universe_fetch_store.py -v` - expected fail: `AttributeError: module 'agentcy.db' has no attribute 'append_universe_fetch'` (and the migration/table does not exist).

### 2c. Minimal implementation

Create `agentcy/schema/002_universe_fetch.sql` (mirror the `price_cache`/`v_price` idiom exactly - append-only table, index, view, two guard triggers):

```sql
-- schema/002_universe_fetch.sql - the populator progress log (design 2026-07-10 section 4).
-- Append-only, trigger-guarded; v_universe_fetch = latest attempt per ticker (the
-- price_cache/v_price idiom). One row per fetch attempt; drives the nightly cursor.

CREATE TABLE universe_fetch (
  yf_ticker TEXT NOT NULL,
  attempted_at TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('ok','no_data','failed','rate_limited')),
  run_id INTEGER REFERENCES run_log(run_id)
); -- re-attempts APPEND; v_universe_fetch = latest per ticker
CREATE INDEX idx_universe_fetch ON universe_fetch (yf_ticker, attempted_at);

CREATE VIEW v_universe_fetch AS
SELECT yf_ticker, attempted_at AS last_attempt, outcome, run_id
FROM (
  SELECT u.*, ROW_NUMBER() OVER (
    PARTITION BY yf_ticker ORDER BY attempted_at DESC, rowid DESC) AS rn
  FROM universe_fetch u
) WHERE rn = 1;

CREATE TRIGGER universe_fetch_no_update BEFORE UPDATE ON universe_fetch
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER universe_fetch_no_delete BEFORE DELETE ON universe_fetch
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
```

In `agentcy/db.py`, after the `append_price_rows` block (~line 168), add the writer + column guard:

```python
_UNIVERSE_FETCH_COLS = frozenset({"yf_ticker", "attempted_at", "outcome", "run_id"})

def append_universe_fetch(conn, *, yf_ticker: str, outcome: str, attempted_at: str,
                          run_id: int | None) -> int:
    """Append one populator fetch-attempt row (design 4); returns rowid. Append-only."""
    return _insert(conn, "universe_fetch", _checked(
        {"yf_ticker": yf_ticker, "attempted_at": attempted_at, "outcome": outcome,
         "run_id": run_id}, _UNIVERSE_FETCH_COLS, "universe_fetch"))
```

In `agentcy/db.py`, in the fetch-helpers section (after `fetch_earnings_calendar`, ~line 476), add the two reads:

```python
def fetch_universe_fetch_latest(conn) -> dict[str, Row]:
    """Latest attempt row per ticker from v_universe_fetch (cursor + milestone feed)."""
    return {r["yf_ticker"]: r for r in conn.execute(
        "SELECT * FROM v_universe_fetch").fetchall()}


def fetch_universe_fetch_failure_counts(conn) -> dict[str, int]:
    """Per ticker: count of 'failed'/'no_data' attempts SINCE the last 'ok' (design 6
    dead-list feed). A ticker that never recorded an 'ok' counts all its failures."""
    counts: dict[str, int] = {}
    rows = conn.execute(
        "SELECT yf_ticker, attempted_at, outcome FROM universe_fetch"
        " ORDER BY yf_ticker, attempted_at, rowid").fetchall()
    for r in rows:
        t = r["yf_ticker"]
        if r["outcome"] == "ok":
            counts[t] = 0
        elif r["outcome"] in ("failed", "no_data"):
            counts[t] = counts.get(t, 0) + 1
        # 'rate_limited' is transient upstream throttling, NOT a dead-list failure (design 6)
    return counts
```

### 2d. Run and see it pass

`uv run pytest tests/test_universe_fetch_store.py -v` - expected: 4 passed.

### 2e. Full suite

`uv run pytest -q` - expected: **793 passed, 3 skipped**, 0 failures. (Confirms migration `002` applies cleanly under `tmp_db`'s `db.migrate` and no other table/view/trigger name collides.)

### 2f. Commit

```
git add agentcy/schema/002_universe_fetch.sql agentcy/db.py tests/test_universe_fetch_store.py
git commit -m "$(cat <<'EOF'
feat(populate): universe_fetch progress log + v_universe_fetch view

Migration 002: append-only trigger-guarded table, latest-per-ticker view
(price_cache/v_price idiom), append_universe_fetch writer, latest + failure-
count-since-last-ok reads. Design 2026-07-10 section 4/6.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 3 - Coverage + cursor (`agentcy/populate.py`)

Derive "is this name cached" from the archive, and build the ordered work list: never-attempted first, then STALE (oldest-first), minus dead-listed names.

**Files:**
- Modify: `agentcy/populate.py` (add `is_cached` + `next_targets`)
- Create: `tests/test_populate_cursor.py`

### 3a. Write the failing test

`tests/test_populate_cursor.py`:

```python
"""Coverage derivation + nightly cursor (populator design 4/6, plan notes 3/4/5)."""
from datetime import datetime, timezone

import pandas as pd

from agentcy import db, populate
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed_full(conn, sym, yf_statements, yf_series, *, price_date="2026-07-07"):
    """A fully-cached name: >=4 periods x3 statements + a shares obs + a fresh price bar."""
    store.store_statements(conn, sym, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"),
                       fetched_at="2026-07-07T00:00:00Z")
    frame = pd.DataFrame(
        {"close": [500.0], "adj_close": [500.0], "dividend": [0.0], "currency": ["USD"]},
        index=pd.to_datetime([price_date]))
    store.store_price_bars(conn, sym, frame, run_id=None, fetched_at="2026-07-07T00:00:00Z")


def test_is_cached_true_only_when_all_coverage_present(tmp_db, yf_statements, yf_series):
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    assert populate.is_cached(tmp_db, "MSFT", as_of=AS_OF) is True
    # a name with only income statements is NOT cached
    store.store_statements(tmp_db, "THIN",
                           {"income": yf_statements("msft_statements")["income"]},
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    assert populate.is_cached(tmp_db, "THIN", as_of=AS_OF) is False
    assert populate.is_cached(tmp_db, "NONE", as_of=AS_OF) is False


def test_next_targets_never_attempted_first_in_rank_order(tmp_db, yf_statements, yf_series):
    ranked = ["MSFT", "VEEV", "AAPL"]
    # none attempted, none cached -> all three, in rank order, cut to budget
    targets = populate.next_targets(tmp_db, ranked, budget=2, as_of=AS_OF)
    assert targets == ["MSFT", "VEEV"]


def test_next_targets_skips_cached_fresh_names(tmp_db, yf_statements, yf_series):
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    db.append_universe_fetch(tmp_db, yf_ticker="MSFT", outcome="ok",
                             attempted_at="2026-07-07T00:00:00Z", run_id=None)
    ranked = ["MSFT", "VEEV"]
    # MSFT is cached + fresh -> not a target; VEEV never attempted -> the only target
    assert populate.next_targets(tmp_db, ranked, budget=10, as_of=AS_OF) == ["VEEV"]


def test_next_targets_excludes_dead_listed_names(tmp_db):
    ranked = ["DEAD", "LIVE"]
    for _ in range(3):
        db.append_universe_fetch(tmp_db, yf_ticker="DEAD", outcome="failed",
                                 attempted_at="2026-07-01T00:00:00Z", run_id=None)
    # DEAD has 3 failures (>= threshold) and its last attempt is recent -> excluded.
    targets = populate.next_targets(tmp_db, ranked, budget=10, as_of=AS_OF,
                                    dead_after_failures=3)
    assert targets == ["LIVE"]


def test_dead_listed_name_reeligible_after_90_days(tmp_db):
    ranked = ["DEAD"]
    for _ in range(3):
        db.append_universe_fetch(tmp_db, yf_ticker="DEAD", outcome="failed",
                                 attempted_at="2026-01-01T00:00:00Z", run_id=None)
    # last attempt 2026-01-01 is > 90 days before AS_OF (2026-07-08) -> re-eligible.
    targets = populate.next_targets(tmp_db, ranked, budget=10, as_of=AS_OF,
                                    dead_after_failures=3)
    assert targets == ["DEAD"]
```

### 3b. Run and see it fail

`uv run pytest tests/test_populate_cursor.py -v` - expected fail: `AttributeError: module 'agentcy.populate' has no attribute 'is_cached'`.

### 3c. Minimal implementation

Append to `agentcy/populate.py`:

```python
from datetime import datetime, timedelta

from agentcy import db
from agentcy.fetch import store
from agentcy.freshness import DataState

_STATEMENT_TYPES = ("income", "balance", "cashflow")
_MIN_PERIODS = 4 # >=4 quarterly periods per statement (design 4)
_DEAD_RETRY_DAYS = 90 # dead-list backstop (design 6, plan note 5)


def is_cached(conn, yf_ticker: str, *, as_of: datetime) -> bool:
    """Design 4 coverage: >=4 quarterly periods across ALL three statements + a shares obs +
    a FRESH price bar (plan note 3). Anything missing -> not cached (a populate target)."""
    for stype in _STATEMENT_TYPES:
        if len(db.fetch_statement_periods(conn, yf_ticker, stype)) < _MIN_PERIODS:
            return False
    if not db.fetch_shares_raw(conn, yf_ticker):
        return False
    return store.price_state(conn, yf_ticker, as_of=as_of) is DataState.FRESH


def _is_stale_covered(conn, yf_ticker: str, *, as_of: datetime) -> bool:
    """A covered name whose statements or price are STALE -> refresh-eligible (plan note 4)."""
    if store.price_state(conn, yf_ticker, as_of=as_of) is not DataState.FRESH:
        return True
    st = store.statement_history(conn, yf_ticker, "income", as_of=as_of)
    return st.state is not DataState.FRESH


def next_targets(conn, ranked, *, budget: int, as_of: datetime,
                 dead_after_failures: int = 3) -> list[str]:
    """The ordered nightly work list (design 4 cursor rule, cut to ``budget``):
      1. never-attempted names, in liquidity rank order;
      2. then STALE covered names, least-recently-refreshed first;
    minus dead-listed names (>= dead_after_failures failures since last ok) UNLESS their
    last attempt is older than the 90-day backstop (design 6, plan note 5)."""
    latest = db.fetch_universe_fetch_latest(conn)
    fails = db.fetch_universe_fetch_failure_counts(conn)

    def dead(t: str) -> bool:
        if fails.get(t, 0) < dead_after_failures:
            return False
        row = latest.get(t)
        if row is None:
            return True
        age = as_of - db.from_iso(row["last_attempt"])
        return age <= timedelta(days=_DEAD_RETRY_DAYS) # still dead until the backstop

    never: list[str] = []
    refresh: list[tuple[str, str]] = [] # (ticker, last_attempt) for oldest-first sort
    for t in ranked:
        if dead(t):
            continue
        if t not in latest:
            never.append(t)
            continue
        if is_cached(conn, t, as_of=as_of):
            if _is_stale_covered(conn, t, as_of=as_of):
                refresh.append((t, latest[t]["last_attempt"]))
            continue
        # attempted before but not (yet) fully covered -> retry, treat as work
        never.append(t)
    refresh.sort(key=lambda pair: pair[1]) # oldest last_attempt first
    ordered = never + [t for t, _ in refresh]
    return ordered[:budget]
```

> Note the `datetime`/`timedelta` import is added once at the top of the file's second block - if Task 1 already imported `pandas as pd` only, add `from datetime import datetime, timedelta` near the top of the module to avoid a duplicate import inside the function body.

### 3d. Run and see it pass

`uv run pytest tests/test_populate_cursor.py -v` - expected: 5 passed.

### 3e. Full suite

`uv run pytest -q` - expected: **798 passed, 3 skipped**, 0 failures.

### 3f. Commit

```
git add agentcy/populate.py tests/test_populate_cursor.py
git commit -m "$(cat <<'EOF'
feat(populate): archive coverage derivation + nightly cursor

is_cached (>=4 periods x3 statements + shares + fresh price) and next_targets
(never-attempted first, then STALE oldest-first, minus dead-listed names with
a 90-day backstop). Design 2026-07-10 section 4/6.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 4 - Fetch-and-store-fundamentals unit (`agentcy/populate.py`)

One function that fetches statements + shares + price for a ticker through `yf.*` and persists via `store.*`, catches `FetchFailed`/`RateLimited`, and returns an outcome enum. The loop (Task 5) owns pacing/budget - this unit fetches exactly once per source.

**Files:**
- Modify: `agentcy/populate.py` (add `Outcome` + `fetch_one`)
- Create: `tests/test_populate_fetch_one.py`

### 4a. Write the failing test

`tests/test_populate_fetch_one.py`:

```python
"""Per-ticker fetch+store unit (populator design 3/6). Fake fetch layer, no network."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from agentcy import db, populate
from agentcy.fetch import store
from agentcy.fetch.yf import FetchFailed, RateLimited

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
FETCHED_AT = "2026-07-08T00:00:00Z"


class _FakeYf:
    """Stand-in for the fetch/yf.py door; the populate loop calls populate.yf.*"""
    def __init__(self, statements=None, shares=None, bars=None, raises=None):
        self._statements, self._shares, self._bars, self._raises = statements, shares, bars, raises

    def fetch_statements(self, t, *, state_dir):
        if isinstance(self._raises, dict) and "statements" in self._raises:
            raise self._raises["statements"]
        return self._statements

    def fetch_shares_full(self, t, *, state_dir):
        return self._shares

    def fetch_daily_bars(self, t, *, state_dir):
        return self._bars


def _bars():
    return pd.DataFrame(
        {"close": [500.0], "adj_close": [500.0], "dividend": [0.0], "currency": ["USD"]},
        index=pd.to_datetime(["2026-07-07"]))


def test_fetch_one_ok_persists_all_three_sources(tmp_db, monkeypatch, yf_statements, yf_series, tmp_path):
    fake = _FakeYf(statements=yf_statements("msft_statements"),
                   shares=yf_series("msft_shares_full"), bars=_bars())
    monkeypatch.setattr(populate, "yf", fake)
    outcome = populate.fetch_one(tmp_db, "MSFT", run_id=None, fetched_at=FETCHED_AT,
                                 state_dir=tmp_path)
    assert outcome == populate.Outcome.OK
    assert len(db.fetch_statement_periods(tmp_db, "MSFT", "income")) >= 4
    assert db.fetch_shares_raw(tmp_db, "MSFT")
    assert db.fetch_v_price(tmp_db, "MSFT")


def test_fetch_one_maps_fetchfailed_to_failed(tmp_db, monkeypatch, tmp_path):
    fake = _FakeYf(raises={"statements": FetchFailed("empty")})
    monkeypatch.setattr(populate, "yf", fake)
    outcome = populate.fetch_one(tmp_db, "X", run_id=None, fetched_at=FETCHED_AT, state_dir=tmp_path)
    assert outcome == populate.Outcome.FAILED


def test_fetch_one_maps_ratelimited_to_rate_limited(tmp_db, monkeypatch, tmp_path):
    fake = _FakeYf(raises={"statements": RateLimited("throttled")})
    monkeypatch.setattr(populate, "yf", fake)
    outcome = populate.fetch_one(tmp_db, "X", run_id=None, fetched_at=FETCHED_AT, state_dir=tmp_path)
    assert outcome == populate.Outcome.RATE_LIMITED
```

### 4b. Run and see it fail

`uv run pytest tests/test_populate_fetch_one.py -v` - expected fail: `AttributeError: module 'agentcy.populate' has no attribute 'yf'` / `no attribute 'Outcome'`.

### 4c. Minimal implementation

At the **top** of `agentcy/populate.py`, add the single-fetch-door import (kept as a module attribute so tests monkeypatch `populate.yf`):

```python
from enum import Enum

from agentcy.fetch import store, yf # yf = the ONE fetch door (design 1)
from agentcy.fetch.yf import FetchFailed, RateLimited
```

> `RateLimited` subclasses `FetchFailed` (see `fetch/yf.py`), so the except order must catch `RateLimited` first.

Append the unit:

```python
class Outcome(str, Enum):
    """One populator fetch-attempt result (design 6). Logged to universe_fetch."""
    OK = "ok"
    NO_DATA = "no_data"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


def fetch_one(conn, yf_ticker: str, *, run_id: int | None, fetched_at: str,
              state_dir) -> Outcome:
    """Fetch statements + shares + daily price for ONE ticker via the single yf door and
    persist via store.* (design 3). Returns an Outcome; RateLimited surfaces so the loop
    stops the night (design 6). This unit does NOT pace or budget - the loop owns that."""
    try:
        statements = yf.fetch_statements(yf_ticker, state_dir=state_dir)
        store.store_statements(conn, yf_ticker, statements, run_id=run_id, fetched_at=fetched_at)
        shares = yf.fetch_shares_full(yf_ticker, state_dir=state_dir)
        store.store_shares(conn, yf_ticker, shares, fetched_at=fetched_at)
        bars = yf.fetch_daily_bars(yf_ticker, state_dir=state_dir)
        store.store_price_bars(conn, yf_ticker, bars, run_id=run_id, fetched_at=fetched_at)
    except RateLimited:
        return Outcome.RATE_LIMITED # RateLimited subclasses FetchFailed: catch first
    except FetchFailed:
        return Outcome.FAILED # empty/None/zero-row/NaN -> failed (design 6)
    return Outcome.OK
```

> `Outcome.NO_DATA` exists for parity with the `universe_fetch` CHECK and future use; the current `fetch/yf.py` collapses empty-data into `FetchFailed`, so this build maps that to `FAILED`. Do not invent a separate no-data path - `NO_DATA` stays a valid, unused-for-now enum member (documented; the CHECK constraint accepts it).

### 4d. Run and see it pass

`uv run pytest tests/test_populate_fetch_one.py -v` - expected: 3 passed.

### 4e. Full suite

`uv run pytest -q` - expected: **801 passed, 3 skipped**, 0 failures.

### 4f. Commit

```
git add agentcy/populate.py tests/test_populate_fetch_one.py
git commit -m "$(cat <<'EOF'
feat(populate): per-ticker fetch+store unit through the single yf door

fetch_one fetches statements+shares+price via fetch/yf.py and persists via
fetch/store.py; Outcome enum {ok,no_data,failed,rate_limited}; RateLimited
caught before FetchFailed. The loop owns pacing/budget. Design section 3/6.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 5 - The populate job (`agentcy/jobs/populate.py`)

`main(*, clock, state_dir) -> int`: open db, run_log entry (`scout` run_type, plan note 8), load the SHA-pinned universe, compute targets, loop under a wall-clock time-box (or `--budget`), append outcomes, stop early + emit DEGRADED on sustained `rate_limited`, return exit code. Deterministic with a monkeypatched fetch layer + a fake advancing clock (no sleep, no network).

**Files:**
- Create: `agentcy/jobs/populate.py`
- Create: `tests/test_jobs_populate.py`

### 5a. Write the failing test

`tests/test_jobs_populate.py`:

```python
"""The populate job (populator design 4/6/7). Fake fetch layer + advancing clock; no sleep,
no network. Time-box and rate-limit early-stop are deterministic."""
import bz2
import hashlib
from datetime import datetime, timedelta, timezone

import pandas as pd

from agentcy import config, db, populate
from agentcy.clock import Clock
from agentcy.jobs import populate as job

START = datetime(2026, 7, 8, 1, 30, tzinfo=timezone.utc)

CSV = (
    "symbol,name,sector,industry,country,market_cap\n"
    "MSFT,Microsoft,Information Technology,Software,United States,mega_cap\n"
    "VEEV,Veeva,Information Technology,Software,United States,large_cap\n"
    "SAP,SAP,Information Technology,Software,Germany,large_cap\n"
)


class AdvancingClock(Clock):
    """Each now() advances by `step` - a wall-clock time-box exercised with no real sleep."""
    def __init__(self, start, step_seconds):
        self._t = start
        self._step = timedelta(seconds=step_seconds)
    def now(self):
        t = self._t
        self._t = self._t + self._step
        return t


class _FakeYf:
    def __init__(self, *, rate_limit_from=None):
        self.calls = []
        self._rl_from = rate_limit_from
    def _maybe_rl(self, t):
        from agentcy.fetch.yf import RateLimited
        if self._rl_from is not None and t in self._rl_from:
            raise RateLimited("throttled")
    def fetch_statements(self, t, *, state_dir):
        self.calls.append(t); self._maybe_rl(t)
        import tests.test_populate_fetch_one as helpers # reuse the recorded pack loader
        # build 4-period frames inline to avoid fixture plumbing:
        return _pack()
    def fetch_shares_full(self, t, *, state_dir):
        return pd.Series([7.4e9], index=pd.to_datetime(["2026-07-01"]))
    def fetch_daily_bars(self, t, *, state_dir):
        return pd.DataFrame(
            {"close": [500.0], "adj_close": [500.0], "dividend": [0.0], "currency": ["USD"]},
            index=pd.to_datetime(["2026-07-07"]))


def _pack():
    cols = pd.to_datetime(["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])
    inc = pd.DataFrame({c: {"Total Revenue": 1e11, "EBITDA": 4e10, "EBIT": 3.5e10,
                            "Gross Profit": 7e10, "Net Income": 3e10} for c in cols})
    bal = pd.DataFrame({c: {"Total Debt": 5e10, "Cash And Cash Equivalents": 8e10,
                            "Total Assets": 4e11, "Current Assets": 3e11,
                            "Working Capital": 2e10} for c in cols})
    cf = pd.DataFrame({c: {"Operating Cash Flow": 4e10, "Capital Expenditure": -5e9,
                           "Stock Based Compensation": 2e9} for c in cols})
    return {"income": inc, "balance": bal, "cashflow": cf}


def _seed_universe(tmp_path, conn):
    path = tmp_path / "universe" / "equities.bz2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bz2.compress(CSV.encode()))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    from agentcy.clock import FixedClock
    config.set(conn, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=FixedClock(START))
    return path


def test_populate_fetches_targets_within_budget(tmp_db, tmp_path, monkeypatch):
    _seed_universe(tmp_path, tmp_db)
    fake = _FakeYf()
    monkeypatch.setattr(populate, "yf", fake)
    monkeypatch.setattr(job, "_open_db", lambda state_dir: tmp_db)
    rc = job.main(clock=AdvancingClock(START, step_seconds=1), state_dir=tmp_path,
                  budget=2, minutes=None)
    assert rc == 0
    # two highest-liquidity names fetched (MSFT mega, then a large_cap), SAP left for later
    latest = db.fetch_universe_fetch_latest(tmp_db)
    assert latest["MSFT"]["outcome"] == "ok"
    assert len(latest) == 2


def test_populate_time_box_stops_the_loop(tmp_db, tmp_path, monkeypatch):
    _seed_universe(tmp_path, tmp_db)
    monkeypatch.setattr(populate, "yf", _FakeYf())
    monkeypatch.setattr(job, "_open_db", lambda state_dir: tmp_db)
    # step 60s/now-call, minutes=1: the box is exhausted after ~1 name.
    rc = job.main(clock=AdvancingClock(START, step_seconds=60), state_dir=tmp_path,
                  budget=None, minutes=1)
    assert rc == 0
    assert len(db.fetch_universe_fetch_latest(tmp_db)) <= 1


def test_populate_rate_limit_stops_early_and_reports_degraded(tmp_db, tmp_path, monkeypatch):
    _seed_universe(tmp_path, tmp_db)
    monkeypatch.setattr(populate, "yf", _FakeYf(rate_limit_from={"MSFT"}))
    monkeypatch.setattr(job, "_open_db", lambda state_dir: tmp_db)
    rc = job.main(clock=AdvancingClock(START, step_seconds=1), state_dir=tmp_path,
                  budget=10, minutes=None)
    assert rc == 1 # DEGRADED -> nonzero exit
    latest = db.fetch_universe_fetch_latest(tmp_db)
    assert latest["MSFT"]["outcome"] == "rate_limited"
    run = db.fetch_run(tmp_db, "scout", START.astimezone(timezone.utc).date().isoformat())
    assert run is not None and run["status"] == "degraded"
```

> **Note:** the test seeds a fresh price bar with obs date `2026-07-07`; the AdvancingClock's first `now()` is `START` (2026-07-08 01:30 UTC). `is_cached` needs a FRESH bar (within 2 trading days) - `2026-07-07` -> `2026-07-08` is 0 weekdays behind, FRESH. After `fetch_one` stores MSFT, it becomes cached, so a re-run would skip it. That is the intended resumable behavior.

### 5b. Run and see it fail

`uv run pytest tests/test_jobs_populate.py -v` - expected fail: `ModuleNotFoundError: No module named 'agentcy.jobs.populate'`.

### 5c. Minimal implementation

Create `agentcy/jobs/populate.py`:

```python
"""The fundamentals-archive populate job (design 2026-07-10 section 4/6/7).

Paced background walk of the universe in liquidity order, filling the append-only archive
so `agentcy scout run grade` grades from cache. Time-boxed by populate_nightly_minutes (or
--budget). Logs one run_log row (run_type 'scout', plan note 8) and one universe_fetch row
per attempt. Sustained rate-limiting stops the night early and returns DEGRADED (NFR6).

No LLM, no new dependency, no new fetch door: every Yahoo call goes through populate.fetch_one
-> fetch/yf.py, which paces box-wide (>=2s + jitter). The loop owns budget/time-box; fetch_one
owns nothing but one fetch per source.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agentcy import config as config_mod, db, populate, runlog
from agentcy.clock import Clock, SystemClock
from agentcy.render import populate as render_populate # milestone note (Task 6)
from agentcy.scout import load_universe

RUN_TYPE = "scout" # plan note 8: run_log CHECK already allows 'scout'
AMS = ZoneInfo("Europe/Amsterdam")
RATE_LIMIT_STOP_AFTER = 1 # a single RateLimited stops the night (design 6)


def _open_db(state_dir: Path):
    """Seam: tests monkeypatch this to inject the tmp_db connection."""
    return db.open_db(state_dir)


def main(*, clock: Clock | None = None, state_dir: Path | None = None,
         budget: int | None = None, minutes: int | None = None) -> int:
    """Systemd/CLI entry (design 7). Returns 0 ok, 1 degraded (sustained rate-limit)."""
    clock = clock or SystemClock()
    state_dir = state_dir or db.state_dir()
    conn = _open_db(state_dir)
    try:
        return _run(conn, clock=clock, state_dir=state_dir, budget=budget, minutes=minutes)
    finally:
        conn.close()


def _run(conn, *, clock, state_dir, budget, minutes) -> int:
    start = clock.now()
    scheduled_for = start.astimezone(timezone.utc).date().isoformat()
    handle = runlog.start(conn, RUN_TYPE, scheduled_for, clock=clock)

    if minutes is None and budget is None:
        minutes = config_mod.get_int(conn, "populate_nightly_minutes")
    starter_size = config_mod.get_int(conn, "populate_starter_size")
    dead_after = config_mod.get_int(conn, "populate_dead_after_failures")

    pin = config_mod.get(conn, "universe_pin_sha")
    universe = load_universe(Path(state_dir) / "universe" / "equities.bz2", expect_sha=pin)
    ranked = populate.rank_universe(universe)

    # A generous budget cap so the time-box is the real limiter when minutes is set.
    work_budget = budget if budget is not None else len(ranked)
    targets = populate.next_targets(conn, ranked, budget=work_budget, as_of=start,
                                    dead_after_failures=dead_after)

    deadline = None if minutes is None else start + timedelta(minutes=minutes)
    counts = {o: 0 for o in populate.Outcome}
    degraded = False
    for t in targets:
        now = clock.now()
        if deadline is not None and now >= deadline:
            break # wall-clock time-box (design 4)
        fetched_at = db.to_iso(now)
        outcome = populate.fetch_one(conn, t, run_id=handle.run_id,
                                     fetched_at=fetched_at, state_dir=state_dir)
        db.append_universe_fetch(conn, yf_ticker=t, outcome=outcome.value,
                                 attempted_at=fetched_at, run_id=handle.run_id)
        conn.commit()
        counts[outcome] += 1
        if outcome is populate.Outcome.RATE_LIMITED:
            degraded = True
            break # stop the night; resume tomorrow (design 6)

    render_populate.maybe_emit_milestones(conn, ranked, starter_size=starter_size,
                                          run_id=handle.run_id, as_of=start, clock=clock)
    conn.commit()

    status = "degraded" if degraded else "ok"
    outputs = {"targets": len(targets), "counts": {o.value: counts[o] for o in counts}}
    runlog.finish(conn, handle.run_id, status=status, outputs=outputs, clock=clock)
    return 1 if degraded else 0
```

> **Important:** Task 5 references `agentcy.render.populate.maybe_emit_milestones`, which is built in Task 6. To keep the suite green when running Tasks in order, **create a stub first**: add a minimal `agentcy/render/populate.py` with `def maybe_emit_milestones(conn, ranked, *, starter_size, run_id, as_of, clock): return None` BEFORE running Task 5's tests, then flesh it out in Task 6. (Alternatively, reorder: do Task 6's module scaffold first.) The plan calls this out explicitly so a fresh implementer does not hit an ImportError. Commit the stub as part of Task 5.

Create the stub `agentcy/render/populate.py`:

```python
"""Sparse populator milestone notes (design 7). Fleshed out in Task 6."""
from __future__ import annotations


def maybe_emit_milestones(conn, ranked, *, starter_size, run_id, as_of, clock) -> None:
    """No-op stub; Task 6 implements the starter-complete / first-full-pass detection."""
    return None
```

### 5d. Run and see it pass

`uv run pytest tests/test_jobs_populate.py -v` - expected: 3 passed.

### 5e. Full suite

`uv run pytest -q` - expected: **804 passed, 3 skipped**, 0 failures.

> This task's tests read `populate_nightly_minutes`/`populate_starter_size`/`populate_dead_after_failures` only on the `minutes is None and budget is None` branch and the `starter_size`/`dead_after` lines. The rate-limit and budget tests pass `budget`/`minutes` explicitly, but `starter_size` and `dead_after` are still read unconditionally - so **Task 9's config defaults must exist for these tests to pass**. Two options: (a) do Task 9 before Task 5, or (b) in Task 5's tests, `config.set` the three keys in `_seed_universe`. The plan's `_seed_universe` above does NOT set them, so **you must land Task 9 first OR add the three `config.set` calls to `_seed_universe`.** Recommended: land Task 9's three seeded defaults first (it is a pure migration+test), then Task 5. If you keep this ordering, add these lines to `_seed_universe` before returning:
> ```python
> for k, v in [("populate_starter_size", "500"),
> ("populate_nightly_minutes", "90"),
> ("populate_dead_after_failures", "3"),
> ("populate_enabled", "true")]:
> config.set(conn, k, v, reason="t", actor="owner", clock=FixedClock(START))
> ```
> Pick one approach and keep the suite green.

### 5f. Commit

```
git add agentcy/jobs/populate.py agentcy/render/populate.py tests/test_jobs_populate.py
git commit -m "$(cat <<'EOF'
feat(populate): time-boxed populate job with rate-limit early-stop

jobs/populate.main(*, clock, state_dir, budget, minutes): SHA-pinned universe
-> ranked cursor -> fetch_one loop under a wall-clock time-box; one run_log
row (run_type 'scout') + one universe_fetch row per attempt; sustained
RateLimited stops the night and returns DEGRADED. Milestone hook stubbed.
Design 2026-07-10 section 4/6/7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 6 - Milestone detection + Telegram note (`agentcy/render/populate.py`)

Detect the starter-set-complete and first-full-pass-complete transitions (derived from coverage + attempts), render a sparse `notice`-class note, enqueue via the outbox with a fixed dedupe_key (idempotent). No nightly spam.

**Files:**
- Modify: `agentcy/render/populate.py` (replace the stub with the real detector + renderer)
- Create: `tests/test_render_populate.py`
- Golden: `tests/golden/populate_starter.md`, `tests/golden/populate_full_pass.md` (generated via `UPDATE_GOLDEN=1`)

### 6a. Write the failing test

`tests/test_render_populate.py`:

```python
"""Sparse populator milestones (populator design 7). Derived transitions, notice-class
render (golden), idempotent outbox enqueue. No nightly spam."""
import bz2
import hashlib
from datetime import datetime, timezone

import pandas as pd

from agentcy import config, db
from agentcy.clock import FixedClock
from agentcy.fetch import store
from agentcy.render import populate as rp

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
CLOCK = FixedClock(AS_OF)


def _cache(conn, sym):
    cols = pd.to_datetime(["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])
    for stype, rows in (("income", {"Total Revenue": 1e11, "EBITDA": 4e10}),
                        ("balance", {"Total Debt": 5e10, "Cash And Cash Equivalents": 8e10}),
                        ("cashflow", {"Operating Cash Flow": 4e10, "Capital Expenditure": -5e9})):
        frame = pd.DataFrame({c: rows for c in cols})
        store.store_statements(conn, sym, {stype: frame}, run_id=None,
                               fetched_at="2026-07-07T00:00:00Z")
    store.store_shares(conn, sym, pd.Series([7.4e9], index=pd.to_datetime(["2026-07-01"])),
                       fetched_at="2026-07-07T00:00:00Z")
    frame = pd.DataFrame({"close": [500.0], "adj_close": [500.0], "dividend": [0.0],
                          "currency": ["USD"]}, index=pd.to_datetime(["2026-07-07"]))
    store.store_price_bars(conn, sym, frame, run_id=None, fetched_at="2026-07-07T00:00:00Z")


def test_render_starter_note_golden(golden):
    out = rp.render_starter_note(gradable=2)
    assert out.output_class == "notice"
    golden("populate_starter.md", out.markdown)


def test_render_full_pass_note_golden(golden):
    out = rp.render_full_pass_note(gradable=2, skipped=1)
    golden("populate_full_pass.md", out.markdown)


def test_starter_milestone_enqueues_once(tmp_db):
    ranked = ["MSFT", "VEEV"]
    _cache(tmp_db, "MSFT")
    _cache(tmp_db, "VEEV")
    rp.maybe_emit_milestones(tmp_db, ranked, starter_size=2, run_id=None,
                             as_of=AS_OF, clock=CLOCK)
    tmp_db.commit()
    queued = [r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"]
    assert len(queued) == 1
    assert "starter set ready" in queued[0]["payload_html"].lower()
    # a second run does not enqueue a duplicate (idempotent by fixed dedupe_key)
    rp.maybe_emit_milestones(tmp_db, ranked, starter_size=2, run_id=None,
                             as_of=AS_OF, clock=CLOCK)
    tmp_db.commit()
    assert len([r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"]) == 1


def test_no_milestone_before_starter_complete(tmp_db):
    ranked = ["MSFT", "VEEV"]
    _cache(tmp_db, "MSFT") # only 1 of 2 cached
    rp.maybe_emit_milestones(tmp_db, ranked, starter_size=2, run_id=None,
                             as_of=AS_OF, clock=CLOCK)
    tmp_db.commit()
    assert [r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"] == []
```

### 6b. Run and see it fail

`uv run pytest tests/test_render_populate.py -v` - expected fail: `AttributeError: module 'agentcy.render.populate' has no attribute 'render_starter_note'`.

### 6c. Minimal implementation

Replace `agentcy/render/populate.py` with:

```python
"""Sparse populator milestone notes (design 2026-07-10 section 7). Two derived transitions,
each enqueued at most once via a fixed dedupe_key (plan notes 6/7): starter-set-complete and
first-full-pass-complete. notice-class output -> lint's calm-register bans apply (no '!',
no red glyphs). No nightly spam."""
from __future__ import annotations

from agentcy import db, populate
from agentcy.render.contexts import RenderedOutput
from agentcy.tg import outbox

_STARTER_KEY = "populate:milestone:starter"
_FULL_PASS_KEY = "populate:milestone:full_pass"


def render_starter_note(*, gradable: int) -> RenderedOutput:
    """One-liner: the starter set is cached and gradable (design 7)."""
    body = (f"Populator: starter set ready - {gradable} names now gradable. "
            f"Run `agentcy scout run grade` to see the first ranked picks.")
    return RenderedOutput(telegram_html=body, markdown=body, output_class="notice")


def render_full_pass_note(*, gradable: int, skipped: int) -> RenderedOutput:
    """One-liner: the whole universe has been attempted at least once (design 7)."""
    body = (f"Populator: universe cached - {gradable} names gradable, "
            f"{skipped} skipped (delisted or data-thin). First full pass complete.")
    return RenderedOutput(telegram_html=body, markdown=body, output_class="notice")


def _starter_complete(conn, ranked, *, starter_size, as_of) -> bool:
    starter = ranked[:starter_size]
    return bool(starter) and all(populate.is_cached(conn, t, as_of=as_of) for t in starter)


def _full_pass_complete(conn, ranked) -> bool:
    latest = db.fetch_universe_fetch_latest(conn)
    return bool(ranked) and all(t in latest for t in ranked)


def _gradable_count(conn, ranked, *, as_of) -> int:
    return sum(1 for t in ranked if populate.is_cached(conn, t, as_of=as_of))


def _enqueue_once(conn, key, rendered, *, run_id, clock) -> None:
    """Enqueue idempotently: a queued row supersedes in place; a SENT row raises ValueError
    (caught) so a re-fire after delivery never re-notifies (plan note 7)."""
    from agentcy.render import lint
    linted, _ = lint.lint_or_fallback(rendered)
    try:
        outbox.enqueue(conn, dedupe_key=key, kind="notice",
                       payload_html=linted.telegram_html, run_id=run_id, clock=clock)
    except ValueError:
        pass # already sent under this key - no re-notify


def maybe_emit_milestones(conn, ranked, *, starter_size, run_id, as_of, clock) -> None:
    """Enqueue the starter and/or first-full-pass note when the derived transition holds;
    each fires at most once (fixed dedupe_key). Called at the tail of every populate run."""
    if _starter_complete(conn, ranked, starter_size=starter_size, as_of=as_of):
        _enqueue_once(conn, _STARTER_KEY,
                      render_starter_note(gradable=_gradable_count(conn, ranked, as_of=as_of)),
                      run_id=run_id, clock=clock)
    if _full_pass_complete(conn, ranked):
        gradable = _gradable_count(conn, ranked, as_of=as_of)
        _enqueue_once(conn, _FULL_PASS_KEY,
                      render_full_pass_note(gradable=gradable, skipped=len(ranked) - gradable),
                      run_id=run_id, clock=clock)
```

### 6d. Generate goldens, then run and see pass

Generate the two goldens first:

`UPDATE_GOLDEN=1 uv run pytest tests/test_render_populate.py -v`

Then verify without the env var:

`uv run pytest tests/test_render_populate.py -v` - expected: 4 passed.

> Confirm `tests/golden/populate_starter.md` contains exactly `Populator: starter set ready - 2 names now gradable. Run \`agentcy scout run grade\` to see the first ranked picks.` and no trailing newline drift (the `golden` fixture writes with `newline=""`).

### 6e. Full suite

`uv run pytest -q` - expected: **808 passed, 3 skipped**, 0 failures.

### 6f. Commit

```
git add agentcy/render/populate.py tests/test_render_populate.py tests/golden/populate_starter.md tests/golden/populate_full_pass.md
git commit -m "$(cat <<'EOF'
feat(populate): sparse starter/full-pass Telegram milestones

Two derived transitions rendered as notice-class notes, each enqueued at most
once via a fixed dedupe_key (idempotent, no nightly spam). Goldens locked.
Design 2026-07-10 section 7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 7 - Grade-time `market_data` assembler + currency guard (`agentcy/scout_grade.py`)

Add `_market_data_from_archive(conn, tickers, *, as_of, statement_currency=None)` building `{market_cap: close x shares, total_debt, cash}` from the archive; the price-currency-vs-statement-currency guard drops the ticker (-> INSUFFICIENT). Wire `run_graded` to build it instead of accepting `{}`. Do NOT change the Stage-1 math.

**Files:**
- Modify: `agentcy/scout_grade.py` (add the assembler function; the pillar/veto/tier/composite functions stay byte-identical)
- Modify: `agentcy/scout.py` (`run_graded` builds `market_data` from the archive when the caller passes `market_data=None`)
- Modify: `agentcy/cli.py` (`_cmd_scout` grade path: pass `market_data=None` instead of `{}`)
- Create: `tests/test_scout_market_data_assembler.py`
- Modify: `tests/test_scout_graded_run.py` (the CLI test currently monkeypatches `run_graded` to inject inline `market_data`; extend/keep it working - see 7a)

### 7a. Write the failing test

`tests/test_scout_market_data_assembler.py`:

```python
"""Grade-time market_data assembly from the archive (populator design 5, plan note 2).
market_cap = latest v_price close x latest shares; total_debt/cash from the latest balance
row; currency mismatch -> ticker omitted -> grade_universe emits INSUFFICIENT (no FX)."""
from datetime import datetime, timezone

import pandas as pd

from agentcy import scout_grade as sg
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed(conn, sym, yf_statements, yf_series, *, currency="USD", close=500.0):
    store.store_statements(conn, sym, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"),
                       fetched_at="2026-07-07T00:00:00Z")
    frame = pd.DataFrame({"close": [close], "adj_close": [close], "dividend": [0.0],
                          "currency": [currency]}, index=pd.to_datetime(["2026-07-07"]))
    store.store_price_bars(conn, sym, frame, run_id=None, fetched_at="2026-07-07T00:00:00Z")


def test_assembler_builds_market_cap_debt_cash_from_archive(tmp_db, yf_statements, yf_series):
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    md = sg._market_data_from_archive(tmp_db, ["MSFT"], as_of=AS_OF)
    entry = md["MSFT"]
    # latest shares from the recorded series; market_cap = close x shares
    shares = store.shares_history(tmp_db, "MSFT", as_of=AS_OF)
    latest_shares = float(shares.value[shares.value.index <= pd.Timestamp(AS_OF.date())].iloc[-1])
    assert entry["market_cap"] == 500.0 * latest_shares
    assert entry["total_debt"] is not None
    assert entry["cash"] is not None


def test_missing_price_or_shares_yields_none_market_cap(tmp_db, yf_statements, yf_series):
    # statements only, no price/shares -> market_cap None -> the name is uncomputable (RF5).
    store.store_statements(tmp_db, "NOPX", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    md = sg._market_data_from_archive(tmp_db, ["NOPX"], as_of=AS_OF)
    assert md["NOPX"]["market_cap"] is None


def test_currency_mismatch_omits_the_ticker(tmp_db, yf_statements, yf_series):
    # price in EUR, statement currency declared USD -> mismatch -> omitted (no FX, design 9).
    _seed(tmp_db, "SAP", yf_statements, yf_series, currency="EUR")
    md = sg._market_data_from_archive(tmp_db, ["SAP"], as_of=AS_OF,
                                      statement_currency={"SAP": "USD"})
    assert "SAP" not in md
```

Add to `tests/test_scout_graded_run.py` a case proving `run_graded(market_data=None)` assembles from the archive (append after the existing tests):

```python
def test_run_graded_assembles_market_data_from_archive_when_none(
        tmp_db, tmp_path, yf_statements, yf_series):
    """market_data=None -> run_graded assembles it from the archive (populator design 5).
    A fully-seeded name (statements+shares+price) grades to a real letter, not INSUFFICIENT."""
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=ck.SystemClock())
    for sym in ("MSFT", "VEEV"):
        _seed(tmp_db, sym, yf_statements, yf_series)
        pf = pd.DataFrame({"close": [500.0], "adj_close": [500.0], "dividend": [0.0],
                           "currency": ["USD"]}, index=pd.to_datetime(["2026-07-07"]))
        store.store_price_bars(tmp_db, sym, pf, run_id=None, fetched_at="2026-07-07T00:00:00Z")
    result = scout.run_graded(tmp_db, universe_path=path, market_data=None, as_of=AS_OF)
    by_sym = {g.symbol: g for g in result.graded}
    assert by_sym["MSFT"].grade in ("A", "B", "C", "D", "F")
    assert by_sym["MSFT"].composite is not None
```

> The `test_cli_scout_run_grade_prints` test in `tests/test_scout_graded_run.py` currently seeds no price bars and monkeypatches `run_graded` to inject inline `market_data`. That monkeypatch stays valid after this task (the CLI passes `market_data=None`, but the test replaces `run_graded` wholesale). Leave it as-is; do NOT weaken it. If you prefer to exercise the real path, add price bars in `_seed` and drop the monkeypatch - optional, not required.

### 7b. Run and see it fail

`uv run pytest tests/test_scout_market_data_assembler.py -v` - expected fail: `AttributeError: module 'agentcy.scout_grade' has no attribute '_market_data_from_archive'`.

### 7c. Minimal implementation

In `agentcy/scout_grade.py`, add the assembler (place it just above `grade_universe`, after `_dig`). It uses only the existing store reads - no new fetch, no math change:

```python
def _market_data_from_archive(conn, tickers, *, as_of, statement_currency=None) -> dict:
    """Design 5 grade-time market_data: {market_cap, total_debt, cash} per ticker from the
    APPEND-ONLY archive (never a live fetch, never a market_cap table - design 1/9).

    market_cap = latest v_price close x latest shares observation (native price currency).
    total_debt/cash = latest archived balance-sheet period. Any missing input -> that key
    None -> grade_universe emits INSUFFICIENT (RF5), never a silent grade.

    Currency guard (design 5/9, plan note 2): when ``statement_currency`` gives a ticker's
    reporting currency AND it differs from the latest price bar's currency, the ticker is
    OMITTED (-> grade_universe's `market_data.get(sym) is None` path -> INSUFFICIENT). No FX
    conversion is performed here (deliberately deferred, design 9)."""
    out: dict[str, dict] = {}
    stmt_ccy = statement_currency or {}
    for t in tickers:
        price = store.latest_close(conn, t, as_of=as_of)
        shares = store.shares_history(conn, t, as_of=as_of)
        # currency guard: price currency vs declared statement currency (when known)
        if price is not None and t in stmt_ccy:
            if str(price.value.currency).upper() != str(stmt_ccy[t]).upper():
                continue # mismatch -> omit -> INSUFFICIENT (no FX)
        market_cap = None
        if price is not None and len(shares.value):
            at_or_before = shares.value[shares.value.index <= pd.Timestamp(as_of.date())]
            if len(at_or_before):
                market_cap = float(price.value.close) * float(at_or_before.iloc[-1])
        bal = _latest_payloads(conn, t, "balance", as_of)
        total_debt = cash = None
        if bal:
            latest_bal = bal[max(bal)]
            total_debt = latest_bal.get("Total Debt")
            cash = latest_bal.get("Cash And Cash Equivalents")
        out[t] = {"market_cap": market_cap, "total_debt": total_debt, "cash": cash}
    return out
```

In `agentcy/scout.py`, update `run_graded` so `market_data=None` triggers archive assembly (keep the explicit-dict path for the existing tests):

```python
def run_graded(conn, *, universe_path=None, market_data=None, as_of) -> GradedScreenResult:
    """H/design section 4 Stage-1: load the pinned universe, grade every name deterministically
    from cached fundamentals, return for human reading. NEVER persists monitoring state (section 6).

    market_data=None (the CLI default) -> assemble it from the append-only archive
    (populator design 5). An explicit dict is still honored (tests/injection)."""
    from agentcy import scout_grade
    pin = config.get(conn, "universe_pin_sha")
    if universe_path is None:
        universe_path = Path(db.state_dir()) / "universe" / "equities.bz2"
    universe = load_universe(universe_path, expect_sha=pin)
    if market_data is None:
        market_data = scout_grade._market_data_from_archive(
            conn, [str(s) for s in universe["symbol"]], as_of=as_of)
    graded = scout_grade.grade_universe(conn, universe, market_data=market_data, as_of=as_of)
    return GradedScreenResult(recipe="grade", graded=tuple(graded),
                              evidence_note=HONEST_EVIDENCE_NOTE)
```

In `agentcy/cli.py`, `_cmd_scout` grade branch, change the `run_graded` call:

```python
        result = scout.run_graded(conn, universe_path=None, market_data=None, as_of=as_of)
```

### 7d. Run and see it pass

- `uv run pytest tests/test_scout_market_data_assembler.py -v` - expected: 3 passed.
- `uv run pytest tests/test_scout_graded_run.py -v` - expected: all prior + the new case pass (the existing `market_data`-dict tests still pass unchanged; `run_graded`'s signature default moved from required to `None`, which is backward-compatible).

### 7e. Full suite

`uv run pytest -q` - expected: **812 passed, 3 skipped**, 0 failures. (Confirms the Stage-1 grading tests in `tests/test_scout_grade_*.py` are untouched - the math functions were not modified.)

### 7f. Commit

```
git add agentcy/scout_grade.py agentcy/scout.py agentcy/cli.py tests/test_scout_market_data_assembler.py tests/test_scout_graded_run.py
git commit -m "$(cat <<'EOF'
feat(scout): assemble grade-time market_data from the archive + currency guard

_market_data_from_archive builds {market_cap=close x shares, total_debt, cash}
from the append-only archive; price-vs-statement currency mismatch omits the
ticker (-> INSUFFICIENT, no FX). run_graded(market_data=None) uses it; CLI grade
path passes None. Stage-1 grading math unchanged. Design 2026-07-10 section 5/9.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 8 - CLI: `agentcy run populate [--minutes M | --budget N]`

Wire the new verb consistently with the existing argparse structure. `run` currently only accepts `{daily,weekly,quarterly,event}`; add `populate` and forward `--minutes`/`--budget` to the job's `main`.

**Files:**
- Modify: `agentcy/cli.py` (`build_parser` - the `run` subparser ~line 33; `_cmd_run` ~line 135)
- Create: `tests/test_cli_populate.py`

### 8a. Write the failing test

`tests/test_cli_populate.py`:

```python
"""agentcy run populate CLI wiring (populator design 7). Forwards clock/state_dir + the
optional --minutes/--budget to jobs.populate.main; returns its int verbatim."""
from agentcy import cli


def test_run_populate_forwards_budget(monkeypatch):
    seen = {}
    class _Fake:
        def main(self, **kw):
            seen.update(kw); return 0
    monkeypatch.setattr(cli, "_job_module", lambda name: _Fake() if name == "populate" else None)
    rc = cli.main(["run", "populate", "--budget", "50"])
    assert rc == 0
    assert seen["budget"] == 50 and seen["minutes"] is None


def test_run_populate_forwards_minutes(monkeypatch):
    seen = {}
    class _Fake:
        def main(self, **kw):
            seen.update(kw); return 1
    monkeypatch.setattr(cli, "_job_module", lambda name: _Fake())
    rc = cli.main(["run", "populate", "--minutes", "30"])
    assert rc == 1
    assert seen["minutes"] == 30 and seen["budget"] is None


def test_run_populate_defaults_both_none(monkeypatch):
    seen = {}
    class _Fake:
        def main(self, **kw):
            seen.update(kw); return 0
    monkeypatch.setattr(cli, "_job_module", lambda name: _Fake())
    cli.main(["run", "populate"])
    assert seen["budget"] is None and seen["minutes"] is None


def test_run_daily_still_works(monkeypatch):
    """The existing run jobs must not regress: daily takes no budget/minutes kwargs."""
    seen = {}
    class _Fake:
        def main(self, **kw):
            seen.update(kw); return 0
    monkeypatch.setattr(cli, "_job_module", lambda name: _Fake())
    cli.main(["run", "daily"])
    assert "budget" not in seen and "minutes" not in seen
```

### 8b. Run and see it fail

`uv run pytest tests/test_cli_populate.py -v` - expected fail: argparse rejects `populate` as an invalid `run` choice (SystemExit / non-zero) - the test asserting `run populate` will error.

### 8c. Minimal implementation

In `agentcy/cli.py` `build_parser`, replace the `run` subparser block:

```python
    run = sub.add_parser("run", help="scheduled jobs (systemd ExecStart surface)")
    run.add_argument("job", choices=["daily", "weekly", "quarterly", "event", "populate"])
    run.add_argument("--minutes", type=int, default=None,
                     help="populate only: wall-clock time-box in minutes (default: config)")
    run.add_argument("--budget", type=int, default=None,
                     help="populate only: fetch at most N names this slice")
    run.set_defaults(handler="run")
```

Update `_cmd_run` to forward the populate-only kwargs (other jobs keep the two-arg call):

```python
def _cmd_run(args) -> int:
    """systemd ExecStart surface (section 10). The job's main() owns the connection, the
    due-run sweep and (for daily) the S2 dead-man ping; the CLI forwards clock/state_dir and
    returns main()'s int verbatim. `populate` additionally forwards --minutes/--budget
    (manual slices from the desk/SSH, design 7). Job exceptions propagate uncaught."""
    from agentcy import db
    mod = _job_module(args.job)
    if args.job == "populate":
        return mod.main(clock=_clock(), state_dir=db.state_dir(),
                        minutes=args.minutes, budget=args.budget)
    return mod.main(clock=_clock(), state_dir=db.state_dir())
```

### 8d. Run and see it pass

`uv run pytest tests/test_cli_populate.py -v` - expected: 4 passed.

### 8e. Full suite

`uv run pytest -q` - expected: **816 passed, 3 skipped**, 0 failures. (Check `tests/test_cli.py`-style tests that assert the `run` choices set - if one pins `choices == ["daily","weekly","quarterly","event"]`, update it to include `populate` and note it in the commit.)

### 8f. Commit

```
git add agentcy/cli.py tests/test_cli_populate.py
git commit -m "$(cat <<'EOF'
feat(populate): agentcy run populate [--minutes M | --budget N] CLI verb

Adds 'populate' to run choices; forwards --minutes/--budget to jobs.populate.main
(manual desk/SSH slices); other run jobs keep the two-arg call. Design section 7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 9 - Config keys (four journaled defaults)

Add the four defaults to migration `000`'s bootstrap config seeds AND a test that `agentcy config get`/`config.get` resolves them. Because the config seeds live in `000_init.sql`, adding keys there is applied to every freshly-migrated `tmp_db` (the tests use fresh DBs, so no data migration is needed).

> **If you did Task 9 before Task 5 (recommended per the Task 5 note), run it here as written; the suite counts below assume Task 9 lands here at position 9. If it landed earlier, just skip to verifying the wiring test.**

**Files:**
- Modify: `agentcy/schema/000_init.sql` (append four rows to the `INSERT INTO config` block ~line 538, before the closing `;`)
- Create: `tests/test_populate_config.py`

### 9a. Write the failing test

`tests/test_populate_config.py`:

```python
"""The four journaled populator config defaults (populator design 7)."""
from agentcy import config


def test_populate_defaults_are_seeded(tmp_db):
    assert config.get(tmp_db, "populate_enabled") == "true"
    assert config.get_int(tmp_db, "populate_starter_size") == 500
    assert config.get_int(tmp_db, "populate_nightly_minutes") == 90
    assert config.get_int(tmp_db, "populate_dead_after_failures") == 3


def test_populate_keys_are_journaled_and_overridable(tmp_db):
    from agentcy.clock import FixedClock
    from datetime import datetime, timezone
    clk = FixedClock(datetime(2026, 7, 10, tzinfo=timezone.utc))
    config.set(tmp_db, "populate_starter_size", "250", reason="tune", actor="owner", clock=clk)
    assert config.get_int(tmp_db, "populate_starter_size") == 250
```

### 9b. Run and see it fail

`uv run pytest tests/test_populate_config.py -v` - expected fail: `KeyError: "unknown config key at now: 'populate_enabled'"`.

### 9c. Minimal implementation

In `agentcy/schema/000_init.sql`, extend the `INSERT INTO config (...) VALUES` block (add before the final `;` on the `deadman_ping_url` line; keep `journal_ref` = 1, the bootstrap entry):

```sql
 ('deadman_ping_url', '', '2026-07-09T00:00:00Z', 4),
 ('populate_enabled', 'true', '2026-07-08T00:00:00Z', 1),
 ('populate_starter_size', '500', '2026-07-08T00:00:00Z', 1),
 ('populate_nightly_minutes', '90', '2026-07-08T00:00:00Z', 1),
 ('populate_dead_after_failures','3', '2026-07-08T00:00:00Z', 1);
```

> Change the previous last line's trailing `;` to `,` and put the `;` after the new final row. The four values match design 7.

### 9d. Run and see it pass

`uv run pytest tests/test_populate_config.py -v` - expected: 2 passed.

### 9e. Full suite

`uv run pytest -q` - expected: **818 passed, 3 skipped**, 0 failures.

> If any existing test asserts the EXACT set/count of seeded config keys (grep `fetch_config_current`/`len(` in `tests/test_config.py`), update it to include the four new keys and note it in the commit.

### 9f. Commit

```
git add agentcy/schema/000_init.sql tests/test_populate_config.py
git commit -m "$(cat <<'EOF'
feat(populate): four journaled config defaults

populate_enabled=true, populate_starter_size=500, populate_nightly_minutes=90,
populate_dead_after_failures=3 seeded in migration 000 (journal_ref=1). Design 7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 10 - systemd units + install.sh + runbook

Add `agentcy-populate.service` (oneshot) + `agentcy-populate.timer` (~01:30, after the daily letter), the `install.sh` enable line, `tests/test_deploy_units.py` coverage, and a runbook entry.

**Files:**
- Create: `deploy/systemd/agentcy-populate.service`
- Create: `deploy/systemd/agentcy-populate.timer`
- Modify: `install.sh` (the `systemctl enable --now` timers line ~step 9)
- Modify: `tests/test_deploy_units.py` (UNITS list + two new assertions)
- Modify: `docs/runbook.md` (a short populator paragraph)

### 10a. Write the failing test

Extend `tests/test_deploy_units.py`:

```python
# add to the UNITS list:
    "agentcy-populate.service", "agentcy-populate.timer",

# add two new test functions:
def test_populate_service_is_oneshot_timeboxed_and_calls_run_populate():
    s = _read("agentcy-populate.service")
    assert "Type=oneshot" in s
    assert "TimeoutStartSec=" in s # time-boxed job
    assert "OnFailure=agentcy-fail@%n.service" in s
    assert "ExecStart=/opt/stock-agentcy/.venv/bin/agentcy run populate" in s
    assert "ProtectSystem=strict" in s and "ReadWritePaths=/var/lib/stock-agentcy" in s


def test_populate_timer_runs_after_the_daily_letter():
    t = _read("agentcy-populate.timer")
    assert "OnCalendar=*-*-* 01:30:00 Europe/Amsterdam" in t
    assert "Persistent=true" in t
```

> The existing `test_all_units_exist` will now also require the two new files (it iterates the UNITS list), so adding them to UNITS makes it assert their presence too.

### 10b. Run and see it fail

`uv run pytest tests/test_deploy_units.py -v` - expected fail: `test_all_units_exist` and the two new tests fail (`agentcy-populate.service` does not exist).

### 10c. Minimal implementation

Create `deploy/systemd/agentcy-populate.service` (mirror `agentcy-daily.service`; note the populate job's own time-box is `populate_nightly_minutes`=90, so `TimeoutStartSec` must exceed it - use 120min):

```ini
[Unit]
Description=stock-agentcy fundamentals-archive populator (paced background fetch -> archive)
Wants=network-online.target
After=network-online.target
OnFailure=agentcy-fail@%n.service

[Service]
Type=oneshot
User=agentcy
TimeoutStartSec=120min
EnvironmentFile=/etc/stock-agentcy/agentcy.env
Environment=MPLBACKEND=Agg
ExecStart=/opt/stock-agentcy/.venv/bin/agentcy run populate
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/stock-agentcy
PrivateTmp=true
```

Create `deploy/systemd/agentcy-populate.timer` (~01:30, after the 07:00... no - 01:30 is BEFORE 07:00; the design says "~01:30, after the daily letter" meaning the daily 07:00 letter of the PRIOR day has long shipped; 01:30 is a quiet slot. Match the design's stated time exactly):

```ini
[Unit]
Description=stock-agentcy nightly fundamentals populator (01:30 Amsterdam)

[Timer]
OnCalendar=*-*-* 01:30:00 Europe/Amsterdam
Persistent=true

[Install]
WantedBy=timers.target
```

In `install.sh`, add `agentcy-populate.timer` to the timers enable line (step 9):

```bash
systemctl enable --now agentcy-daily.timer agentcy-weekly.timer agentcy-quarterly.timer agentcy-backup.timer agentcy-populate.timer
```

In `docs/runbook.md`, add a short section (after section 6, before the LTS obligation line):

```markdown
## 7. Fundamentals populator (background, set-and-forget)
The `agentcy-populate.timer` fires nightly at 01:30 Amsterdam and time-boxes a paced walk of
the universe (`populate_nightly_minutes`, default 90), filling the append-only archive so
`agentcy scout run grade` grades from cache. The starter set (top `populate_starter_size`
liquidity names, default 500) completes on night 1; the first full pass takes ~11 nights.
One Telegram note marks starter-set-ready and one marks first-full-pass-complete; sustained
rate-limiting stops the night early (DEGRADED) and the cursor resumes the next night.

- **Manual slice:** `agentcy run populate --minutes 30` or `--budget 100` (desk/SSH).
- **Progress:** the `universe_fetch` table logs one row per attempt; `v_universe_fetch` is the
  latest outcome per ticker. Delisted/data-thin names dead-list after
  `populate_dead_after_failures` (default 3) failures, retried after a 90-day backstop.
- **Disable:** `agentcy config set populate_enabled false --reason "..."` (advisory flag) and
  `systemctl disable --now agentcy-populate.timer`.
```

> Note: `populate_enabled` is a journaled advisory flag; the timer is the real on/off. If you want the job itself to honor it, that is a follow-on - this build seeds the flag and documents both switches (design 7 lists the flag; the timer is the operational control).

### 10d. Run and see it pass

`uv run pytest tests/test_deploy_units.py -v` - expected: all pass including the two new.

### 10e. Full suite

`uv run pytest -q` - expected: **818 passed, 3 skipped**, 0 failures (deploy-unit tests are pure file reads; no new pass count beyond the two new test functions, which were counted in the file's run - recompute: 818 + 2 = **820 passed, 3 skipped**).

### 10f. Commit

```
git add deploy/systemd/agentcy-populate.service deploy/systemd/agentcy-populate.timer install.sh tests/test_deploy_units.py docs/runbook.md
git commit -m "$(cat <<'EOF'
feat(populate): agentcy-populate systemd timer/service + install + runbook

Oneshot time-boxed populate unit (01:30 Amsterdam, TimeoutStartSec=120min),
enabled by install.sh, pinned by test_deploy_units, documented in the runbook
(manual slices, progress log, dead-list, disable). Design section 7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 11 - Structural phase-gate

A test asserting the populator added NO new pip dependency (deps stay `{yfinance,pandas,scipy,quantstats}`) and NO new fetch door (yfinance still imported ONLY in `fetch/yf.py`), plus a final full-suite green.

**Files:**
- Create: `tests/test_populate_structural.py`

### 11a. Write the failing test

`tests/test_populate_structural.py`:

```python
"""Populator phase gate (populator design 1/9, constitution NFR3/NFR7): no new pip
dependency, no new fetch door, no LLM in the scheduled runtime."""
import ast
import tomllib
from pathlib import Path

import agentcy.populate # noqa: F401
import agentcy.jobs.populate # noqa: F401
import agentcy.render.populate # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_no_new_pip_dependency():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {d.split("==")[0].split(">")[0].split("[")[0].strip().lower() for d in deps}
    assert names == {"yfinance", "pandas", "scipy", "quantstats"}
    assert set(data["project"]["optional-dependencies"]) == {"scout"}


def test_yfinance_imported_only_in_fetch_yf():
    """The single fetch door (design 1): `import yfinance` appears in exactly one module."""
    offenders = []
    for path in (ROOT / "agentcy").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "yfinance"
                                                    for a in node.names):
                offenders.append(path)
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "yfinance":
                offenders.append(path)
    rel = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in set(offenders))
    assert rel == ["agentcy/fetch/yf.py"], f"yfinance imported outside the one door: {rel}"


def test_populator_imports_no_llm():
    import sys
    banned = ("anthropic", "openai", "langchain", "llama", "cohere", "google.generativeai")
    loaded = set(sys.modules)
    assert not any(b in m for b in banned for m in loaded)
```

### 11b. Run and see it fail

`uv run pytest tests/test_populate_structural.py -v` - expected: initially PASSES if the implementation was disciplined. To honor TDD, first confirm it would catch a regression: temporarily add `import yfinance` to `agentcy/populate.py`, run, see `test_yfinance_imported_only_in_fetch_yf` fail, then remove it. (Document this in the commit; do not leave the temporary import.) The lasting purpose of this test is the phase gate, not a red-then-green cycle on new code.

### 11c. Minimal implementation

No implementation code - this is a gate. If any assertion fails for real (e.g. `populate.py` imported `yfinance` directly instead of using the `fetch.yf` facade), fix the offending module to route through `agentcy.fetch.yf` (as Task 4 already does: `from agentcy.fetch import store, yf`). `import yfinance` (the raw package) must appear only in `agentcy/fetch/yf.py`; importing the `agentcy.fetch.yf` facade elsewhere is fine and is NOT flagged (the AST check matches the top-level package name `yfinance`, not the `agentcy.fetch.yf` module).

### 11d. Run and see it pass

`uv run pytest tests/test_populate_structural.py -v` - expected: 3 passed.

### 11e. Full suite (final gate)

`uv run pytest -q` - expected: **823 passed, 3 skipped**, 0 failures. Also run the license gate to confirm the wall is still clean:

`uv run python tools/license_gate.py` - expected: exit 0, clean.

### 11f. Commit

```
git add tests/test_populate_structural.py
git commit -m "$(cat <<'EOF'
test(populate): structural phase gate - no new dep, no new fetch door, no LLM

Asserts deps stay {yfinance,pandas,scipy,quantstats}, yfinance is imported only
in fetch/yf.py (AST scan), and no LLM client loads. Design 2026-07-10 section 1/9.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Final verification checklist

- [ ] `uv run pytest -q` -> **823 passed, 3 skipped**, 0 failures (final count; intermediate counts per task above).
- [ ] `uv run python tools/license_gate.py` -> exit 0.
- [ ] `agentcy run populate --budget 1` on a seeded desk DB fetches one name and logs a `universe_fetch` row (smoke; requires a real universe file + network - desk-only, not a test).
- [ ] `agentcy scout run grade` grades cached names to real letters (no longer all-INSUFFICIENT) once the archive is populated.
- [ ] Migration `002` applies forward-only (PRAGMA user_version advances 2->3 on an existing DB); the `v_universe_fetch` view + guard triggers exist.
- [ ] No new pip dependency; `import yfinance` only in `agentcy/fetch/yf.py`.
- [ ] Stage-1 grading math (`scout_grade.py` pillar/veto/tier/composite functions) byte-unchanged - only `_market_data_from_archive` added.

---

## Explicit follow-ons (NOT built here)

Per design section 9 YAGNI boundaries, these are deliberately out of scope:

1. **Stage-2 `QualitativeReviewer` (Scout v2 section 8 item 3 / v2.1).** The LLM shortlist review (Anthropic API adapter + manual/desk adapter, the four questions, the bounded one-band badge/adjustment). No LLM is imported or invoked by this build (Task 11 enforces it). This is the next section 8 item.
2. **FX conversion for cross-currency names.** The currency guard here marks a price-currency-vs-statement-currency mismatch as INSUFFICIENT (Task 7, plan note 2) rather than converting. A future refinement would reuse the existing `store.fx_rate_eur` path to convert `market_cap` into the statement currency before computing `p_owner_fcf`, moving those names from INSUFFICIENT to graded. The assembler already accepts a `statement_currency` mapping, so the guard is wired and ready; only the conversion + a per-ticker statement-currency source are deferred.
3. **A dedicated `market_cap` / `market_data` cache table.** Rejected in design section 1 (duplicates archived `total_debt`/`cash`, adds a second store to keep fresh). `market_cap` is derived at grade-time from the archive; do not add a table.
4. **A distinct `no_data` fetch path.** The `universe_fetch.outcome` CHECK includes `'no_data'` and the `Outcome` enum defines it, but the current `fetch/yf.py` collapses empty/thin data into `FetchFailed` -> `failed`. Splitting genuine "ticker exists but has no statements" from transport failure is a future refinement inside `fetch/yf.py`, not this build.
