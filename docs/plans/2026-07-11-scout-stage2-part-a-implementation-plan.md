# Scout Stage-2 Qualitative Reviewer (Part A) - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship Part A of Scout Stage-2 (design `docs/plans/2026-07-11-scout-stage2-qualitative-reviewer-design.md`): the agentcy-side CLI + logic for a bounded, reason-printed, never-silent qualitative review over a small shortlist. Shortlist selection, a `QualitativeReviewer` interface + `DeskReviewer` adapter, a review-artifact table (migration 003), the bounded one-band grade adjustment, badges, three new CLI verbs (`scout shortlist`, `scout badge`, `scout review render`), an annotated render + golden, and a structural gate.

**Architecture:** Pure-Python functions over `scout_grade.GradedName` (READ-only; no change to Stage-1 grading math). One new module `agentcy/scout_review.py` (selection + interface + adapter + verdict dataclass + badges + adjustment), one new render module `agentcy/render/scout_review.py`, one new migration `agentcy/schema/003_scout_shortlist_verdict.sql` + `db.py` helpers, three argparse subcommands in `agentcy/cli.py`. The Scout still only surfaces; the Gate still decides. The reviewer NEVER moves the composite number and NEVER writes a monitoring table.

**Tech Stack:** Python 3.13 (uv-managed CPython), stdlib + existing runtime deps only (yfinance, pandas, scipy, quantstats). No new pip dependency. No LLM / anthropic import anywhere in agentcy. SQLite via the `db.py` door + `schema/NNN_*.sql` forward-only migrations. Tests: `uv run pytest`, byte-exact goldens under `tests/golden/` (record with `UPDATE_GOLDEN=1`).

---

## Review fixes (apply first - from the pre-execution fidelity review)

**RF1 (MAJOR, Task 4) - the promotion pillar-gate must include the Growth pillar.** The design says promote "only if no pillar < 50". The current live model has FIVE pillars (V/Q/G/D/M; `W_V,W_Q,W_G,W_D,W_M = 0.25,0.25,0.20,0.15,0.15`). The gate must therefore be `min(v, q, g, d, m) >= 50`, NOT `min(v, q, d, m)` - include G. Update `adjust_grade` + its docstring, and ADD a test proving a name with **G = 40** and V/Q/D/M all >= 50 and all four axes clear is **NOT promoted** (G blocks it), alongside the existing all->=50 promote case.

**RF2 (MINOR, Task 6 - CLI refactor).** `_cmd_scout` currently branches on `args.recipe`, which only exists on the `run` subparser. When `shortlist`/`badge`/`review` subcommands are added, guard the existing body with `if args.scout_cmd == "run":` BEFORE reading `args.recipe` (else `agentcy scout shortlist` throws AttributeError), and keep `conn = _open()` reachable for every branch (the new branches all use `conn`).

**RF3 (MINOR, Task 8 - plan note).** The per-name adjustment reasons embed owner free text and ride as plain template text (NOT `owner_spans`); the `review render` CLI path is intentionally not lint-gated (matches the Stage-1 `render/scout.py` precedent). The golden asserts `lint(r) == []` on a clean fixture only. This is a conscious choice, not an oversight.

**RF4 (MINOR, Task 4 - anti-drift comment).** Comment the local `_BANDS = ("F","D","C","B","A")` as the letter mirror of `scout_grade._GRADE_BANDS`, so a future band change can't silently diverge (Stage-1 bands are frozen + guarded).

**RF5 (MINOR-optional, Task 3).** Add a `scout_shortlist_verdict` entry to `tests/test_structural_append_only.py::CASES` for idiom consistency (already covered by the dedicated store test, so optional).

Everything else in the review checked out: the adjustment truth table (demote precedence, pending-never-moves, F/A clamp, reason-always, composite-never-touched), shortlist selection (top-per-tier + Outside-A dedup, VETOED/INSUFFICIENT excluded), migration 003 + latest-wins append-only view, the structural-fence relaxation preserving the no-LLM/no-new-dep guards, ASCII badges surviving lint, and the 11-field `GradedName` arity.

---

## Plan notes (assumptions, simplest compliant choice)

- **Where shortlist + adjustment + interface live: a NEW module `agentcy/scout_review.py`.** Rationale: `scout_grade.py` is the Stage-1 grading engine and is guarded by `tests/test_scout_stage1_structural.py` / `test_scout_stage1_5_structural.py` (no-LLM, no-new-dep, grade-math-frozen). Adding Stage-2 logic there muddies "Stage-1 is standalone" and risks those byte-level guards. A separate module keeps Stage-1 frozen and makes the structural gate (Task 9) trivial to scope. The module name is `scout_review` (NOT `scout_qualitative`) on purpose - see the next note.
- **The word "qualitative" must NOT appear in any importable module NAME.** `tests/test_scout_stage1_structural.py::test_stage2_and_populator_are_explicit_followons` asserts `not any("qualitative" in m.lower() for m in sys.modules)`. That assertion was the Stage-1 "not built yet" fence; Part A legitimately builds Stage-2, so Task 9 RELAXES that one assertion (Stage-2 is now real) while keeping the no-LLM / no-new-dep guards. Naming the module `scout_review` also keeps `sys.modules` free of a "qualitative" key regardless. (The existing docstring "qualitative half" inside `scout_grade.py` is a comment, not a module name - untouched.)
- **`per_tier = 10` is a MODULE CONSTANT (`SHORTLIST_PER_TIER = 10`), not a config key.** Config is journal-coupled: `config` rows carry a NOT-NULL `journal_ref` FK to `journal_entry` (see `agentcy/config.py::set` and `schema/000_init.sql`). A raw-SQL seed migration for a new default would violate that FK (there is no journal entry to point at). The two compliant ways to introduce a default are (a) a module constant or (b) `agentcy config set scout_shortlist_per_tier 10 --reason ...` at the desk. YAGNI: the design fixes the shortlist at "top 10 per tier"; a constant is the simplest compliant choice and needs no migration. If tuning is ever wanted, promote to a journaled config key then - not now.
- **The verdict table is APPEND-ONLY with a latest-wins VIEW (not overwrite, not per-session).** A verdict can be re-recorded/superseded when the reviewer revises an axis, so we need latest-wins semantics. The repo idiom for that is append rows + a `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY recorded_at DESC, rowid DESC)` view (exactly `v_universe_fetch` in `schema/002`). We key latest-wins on `(ticker, axis)` so re-badging one axis supersedes only that axis, pending axes stay pending, and the four axes are independent rows. This is a REVIEW ARTIFACT, not monitoring state: nothing reads it on a schedule, no trigger/alert/thesis references it, and `scout review render` reads it once for a human. We still attach the standard append-only no-update/no-delete triggers so the artifact obeys invariant 1 like every other table. (No "session" column: the design's shortlist is regenerated deterministically each run from the cached grade; latest-per-(ticker,axis) is the whole state a render needs. Simpler than a session table, and YAGNI-honest.)
- **Badges are display glyphs only.** The four axis verdicts map to glyphs (moat-confirmed `[+]`, moat-not-evident/mgmt-neutral `[~]`, fad-flag/mgmt-red-flag `[x]`, tier-correction `[t]`) for the annotated render. Per the design, badge glyphs are the ONE allowed non-ASCII exception IF a glyph is needed and survives lint. To stay safe and lint-clean we render ASCII-bracket badges `[+] [~] [x] [t]` (see Task 5/8); they are unambiguous, ASCII, and cannot trip the `_RED_GLYPHS` lint ban. The Unicode check/warn/no-entry glyphs are deliberately avoided because `_RED_GLYPHS` bans some of them everywhere. Design tokens `checkmark/warn/stop/pencil` map to these ASCII badges.
- **"Cached" grade:** `scout shortlist` calls `scout.run_graded(conn, ..., as_of=clock.now())`, which grades from the append-only fundamentals archive (no live network - the autouse guard proves it). "Cached" == "from the archive"; there is no separate cache layer to build (that is the populator, an explicit follow-on).
- **Baseline:** Task 0 records the live green baseline. As of this branch it is ~928 passed / 3 skipped, but the executor MUST run it and record the actual numbers, not trust this note. Every subsequent task keeps the suite green.

---

## Task 0 - Confirm the live green baseline

**Files:** none (read-only).

**Run:**
```
uv run pytest -q
```

**Expected:** the suite passes with 3 skips (AF_UNIX/git skips on Windows). Record the exact line, e.g. `928 passed, 3 skipped`. This is the number every later task must hold at or above (later tasks ADD tests; none are removed except the one relaxed assertion in Task 9, which is edited in place, not deleted). If the baseline is NOT green, STOP and report - do not build on a red suite.

**No commit** (nothing changed).

---

## Task 1 - Shortlist selection (pure function)

Pure selection over `list[GradedName]`: within each tier (Core / Adjacent / Outside), take the top `per_tier` (default `SHORTLIST_PER_TIER = 10`) by composite; PLUS every Outside-tier A-grade (the circle-expansion star, design §3); EXCLUDING any name that is VETOED or INSUFFICIENT (grade not in A-F, or `composite is None`). Deterministic order: tier order Core -> Adjacent -> Outside, composite desc within tier, ticker asc as the tiebreak; the extra Outside-A names are unioned in (deduped) and appear once, in that same deterministic order.

**Files:**
- `agentcy/scout_review.py` (NEW)
- `tests/test_scout_review_shortlist.py` (NEW)

**Failing test** (`tests/test_scout_review_shortlist.py`):
```python
"""Stage-2 shortlist selection (design Part A + parent design §4): top-per-tier by composite
+ every Outside-tier A, VETOED/INSUFFICIENT excluded, deterministic order. READ-only over
GradedName - never mutates grading."""
from agentcy import scout_review as sr
from agentcy import scout_grade as sg


def _g(sym, tier, comp, grade):
    # only the fields shortlist reads need real values; the rest are placeholders
    return sg.GradedName(sym, "Technology", tier, 60.0, 60.0, 60.0, 60.0, 60.0, comp, grade, "")


def test_top_per_tier_by_composite_default_ten():
    rows = [_g(f"C{i}", "Core", float(i), "B") for i in range(15)]  # 15 Core names, comp 0..14
    picked = sr.select_shortlist(rows)
    core = [g for g in picked if g.tier == "Core"]
    assert len(core) == 10                                   # capped at SHORTLIST_PER_TIER
    assert [g.symbol for g in core] == [f"C{i}" for i in range(14, 4, -1)]  # top 10 by comp desc


def test_outside_a_always_included_even_beyond_top_ten():
    # 12 Outside names; the two A-grades are ranked #11 and #12 by composite but must STILL surface
    rows = [_g(f"O{i}", "Outside", float(i), "B") for i in range(10)]      # comp 0..9, B
    rows += [_g("OA1", "Outside", 100.0, "A"), _g("OA2", "Outside", 99.0, "A")]  # top A-grades
    # make the A-grades rank OUTSIDE the top-10-by-composite by adding higher-comp B names
    rows += [_g(f"OB{i}", "Outside", 200.0 + i, "B") for i in range(10)]
    picked = sr.select_shortlist(rows, per_tier=10)
    syms = {g.symbol for g in picked}
    assert "OA1" in syms and "OA2" in syms                   # Outside-A star: never dropped
    # no duplicates even though OA* are both top-per-tier-eligible and Outside-A
    assert len([g for g in picked if g.symbol == "OA1"]) == 1


def test_vetoed_and_insufficient_excluded():
    rows = [
        _g("GOOD", "Core", 80.0, "A"),
        sg.GradedName("VETO", "Technology", "Core", None, None, None, None, None, None, "VETOED", "lev"),
        sg.GradedName("THIN", "Technology", "Core", None, None, None, None, None, None, "INSUFFICIENT", "thin"),
    ]
    picked = sr.select_shortlist(rows)
    assert [g.symbol for g in picked] == ["GOOD"]


def test_deterministic_order_tier_then_comp_then_ticker():
    rows = [
        _g("ADJ", "Adjacent", 70.0, "B"),
        _g("COR2", "Core", 70.0, "B"),
        _g("COR1", "Core", 70.0, "B"),   # same comp as COR2 -> ticker asc breaks the tie
        _g("OUT", "Outside", 90.0, "A"),
    ]
    picked = sr.select_shortlist(rows)
    assert [g.symbol for g in picked] == ["COR1", "COR2", "ADJ", "OUT"]
```

**Run (expect fail):**
```
uv run pytest tests/test_scout_review_shortlist.py -q
```
Expected: `ModuleNotFoundError: No module named 'agentcy.scout_review'` (or `AttributeError: ... 'select_shortlist'`).

**Minimal implementation** (`agentcy/scout_review.py`):
```python
"""Scout Stage-2 (Part A) - the qualitative reviewer's agentcy-side logic (design
2026-07-11-scout-stage2-qualitative-reviewer-design.md). Shortlist selection, the
QualitativeReviewer interface + DeskReviewer adapter, the verdict dataclass + badges,
and the bounded one-band grade adjustment. NO LLM, NO new pip dependency; every function
READS scout_grade.GradedName and NEVER changes Stage-1 grading math. The Scout still only
surfaces; the Gate still decides."""
from __future__ import annotations

from agentcy import scout_grade as sg

SHORTLIST_PER_TIER = 10                       # design §4: top 10 per tier (a module constant, Plan note)
_TIER_ORDER = {"Core": 0, "Adjacent": 1, "Outside": 2}
_GRADABLE = frozenset({"A", "B", "C", "D", "F"})


def _gradable(g: sg.GradedName) -> bool:
    """A name is shortlist-eligible only if it graded to a letter (VETOED/INSUFFICIENT out)."""
    return g.grade in _GRADABLE and g.composite is not None


def _order_key(g: sg.GradedName):
    """Deterministic: tier lane, then composite desc, then ticker asc."""
    return (_TIER_ORDER.get(g.tier, 99), -g.composite, g.symbol)


def select_shortlist(graded, *, per_tier: int = SHORTLIST_PER_TIER) -> list[sg.GradedName]:
    """Design §4 shortlist: top `per_tier` by composite within each tier PLUS every
    Outside-tier A-grade, VETOED/INSUFFICIENT excluded, deterministic order. Pure READ over
    GradedName - never mutates grading (Plan note)."""
    eligible = [g for g in graded if _gradable(g)]
    picked: dict[str, sg.GradedName] = {}
    by_tier: dict[str, list[sg.GradedName]] = {}
    for g in eligible:
        by_tier.setdefault(g.tier, []).append(g)
    for tier, rows in by_tier.items():
        rows_sorted = sorted(rows, key=_order_key)
        for g in rows_sorted[:per_tier]:
            picked[g.symbol] = g
    # Outside-tier A star (design §3): included even past the top-per-tier cut.
    for g in eligible:
        if g.tier == "Outside" and g.grade == "A":
            picked[g.symbol] = g
    return sorted(picked.values(), key=_order_key)
```

**Run (expect pass):**
```
uv run pytest tests/test_scout_review_shortlist.py -q
```

**Commit:**
```
feat(scout): Stage-2 shortlist selection (top-per-tier + Outside-A, exclusions)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 2 - Verdict dataclass + QualitativeReviewer interface + DeskReviewer adapter

A frozen `Verdict` dataclass over the four axes (each nullable = pending), a `QualitativeReviewer` ABC with one method `review(ticker) -> Verdict`, and a `DeskReviewer` adapter whose input is a dict of already-recorded verdicts (the desk/claudeclaw path - no LLM). The API adapter is a future slot behind the same interface (NOT built - see Explicit follow-ons).

Axis value vocab (design "four questions"):
- `moat`: `confirmed` | `not-evident` | `None` (pending)
- `mgmt`: `aligned` | `neutral` | `red-flag` | `None`
- `fad`: `clear` | `flag` | `None`
- `tier`: `ok` | `correction:<Core|Adjacent|Outside>` | `None`
- `reason`: free text (always printed), `None` allowed.

**Files:**
- `agentcy/scout_review.py` (extend)
- `tests/test_scout_review_reviewer.py` (NEW)

**Failing test** (`tests/test_scout_review_reviewer.py`):
```python
"""Stage-2 QualitativeReviewer interface + DeskReviewer adapter + Verdict dataclass.
Minimal, no LLM: the DeskReviewer just surfaces already-recorded verdicts (design Part A)."""
import pytest
from agentcy import scout_review as sr


def test_verdict_defaults_all_axes_pending():
    v = sr.Verdict()
    assert v.moat is None and v.mgmt is None and v.fad is None and v.tier is None
    assert v.reason is None


def test_verdict_rejects_unknown_axis_values():
    with pytest.raises(ValueError):
        sr.Verdict(moat="maybe")
    with pytest.raises(ValueError):
        sr.Verdict(mgmt="great")
    with pytest.raises(ValueError):
        sr.Verdict(fad="trend")
    with pytest.raises(ValueError):
        sr.Verdict(tier="Core")            # tier correction must be 'ok' or 'correction:<T>'
    # a valid tier correction is accepted
    assert sr.Verdict(tier="correction:Adjacent").tier == "correction:Adjacent"


def test_desk_reviewer_returns_recorded_verdict_or_pending():
    recorded = {"MSFT": sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok",
                                   reason="switching costs; founder-led; real trend")}
    rv = sr.DeskReviewer(recorded)
    assert isinstance(rv, sr.QualitativeReviewer)
    assert rv.review("MSFT").moat == "confirmed"
    # an unrecorded ticker is all-pending, never faked (FR9)
    assert rv.review("UNKN") == sr.Verdict()
```

**Run (expect fail):**
```
uv run pytest tests/test_scout_review_reviewer.py -q
```
Expected: `AttributeError: module 'agentcy.scout_review' has no attribute 'Verdict'`.

**Minimal implementation** (append to `agentcy/scout_review.py`):
```python
import abc
from dataclasses import dataclass, field

_MOAT_VALUES = frozenset({"confirmed", "not-evident"})
_MGMT_VALUES = frozenset({"aligned", "neutral", "red-flag"})
_FAD_VALUES = frozenset({"clear", "flag"})
_TIER_CORRECTION_TARGETS = frozenset({"Core", "Adjacent", "Outside"})


def _valid_tier(value: str) -> bool:
    if value == "ok":
        return True
    if value.startswith("correction:"):
        return value.split(":", 1)[1] in _TIER_CORRECTION_TARGETS
    return False


@dataclass(frozen=True)
class Verdict:
    """The four Constitution-grounded axes (design 'four questions'); each None = pending,
    never faked (FR9). moat: confirmed|not-evident. mgmt: aligned|neutral|red-flag.
    fad: clear|flag. tier: ok|correction:<Core|Adjacent|Outside>. reason always printed."""
    moat: str | None = None
    mgmt: str | None = None
    fad: str | None = None
    tier: str | None = None
    reason: str | None = None

    def __post_init__(self):
        if self.moat is not None and self.moat not in _MOAT_VALUES:
            raise ValueError(f"moat must be in {sorted(_MOAT_VALUES)} or None: {self.moat!r}")
        if self.mgmt is not None and self.mgmt not in _MGMT_VALUES:
            raise ValueError(f"mgmt must be in {sorted(_MGMT_VALUES)} or None: {self.mgmt!r}")
        if self.fad is not None and self.fad not in _FAD_VALUES:
            raise ValueError(f"fad must be in {sorted(_FAD_VALUES)} or None: {self.fad!r}")
        if self.tier is not None and not _valid_tier(self.tier):
            raise ValueError(f"tier must be 'ok' or 'correction:<Core|Adjacent|Outside>' or None: {self.tier!r}")


class QualitativeReviewer(abc.ABC):
    """The Stage-2 review seam (design Part A). v1 = DeskReviewer (recorded verdicts, no LLM);
    an API adapter is a future slot behind this same interface (NOT built - Explicit follow-ons)."""

    @abc.abstractmethod
    def review(self, ticker: str) -> Verdict:
        ...


class DeskReviewer(QualitativeReviewer):
    """v1 adapter: input is already-recorded verdicts (the desk / claudeclaw path). No LLM.
    An unrecorded ticker returns an all-pending Verdict (never faked, FR9)."""

    def __init__(self, recorded: dict[str, Verdict]):
        self._recorded = dict(recorded)

    def review(self, ticker: str) -> Verdict:
        return self._recorded.get(ticker, Verdict())
```

**Run (expect pass):**
```
uv run pytest tests/test_scout_review_reviewer.py -q
```

**Commit:**
```
feat(scout): Stage-2 Verdict dataclass + QualitativeReviewer/DeskReviewer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 3 - Review-artifact table (migration 003) + verdict recording

A NEW append-only table `scout_shortlist_verdict` (migration 003), a latest-wins view `v_scout_shortlist_verdict` keyed on `(ticker, axis)`, `db.append_scout_verdict(...)`, and `db.fetch_scout_verdicts_current(...)`. Each of the four axes is stored as its own row (`axis`, `value`, `reason`, `recorded_at`) so pending axes are simply absent, a re-badge appends a superseding row, and the view returns the latest per `(ticker, axis)`. This is a REVIEW ARTIFACT, not monitoring (Plan note).

**Files:**
- `agentcy/schema/003_scout_shortlist_verdict.sql` (NEW)
- `agentcy/db.py` (add two helpers)
- `tests/test_scout_verdict_store.py` (NEW)

**Migration** (`agentcy/schema/003_scout_shortlist_verdict.sql`):
```sql
-- schema/003_scout_shortlist_verdict.sql - Scout Stage-2 review artifact (design
-- 2026-07-11-scout-stage2-qualitative-reviewer-design.md, Part A). NOT monitoring state:
-- nothing reads it on a schedule, no trigger/alert/thesis references it; a human reads it once
-- via `agentcy scout review render`. Append-only (invariant 1); one row per (ticker, axis)
-- verdict; a re-badge APPENDS a superseding row; v_scout_shortlist_verdict = latest per
-- (ticker, axis) via the v_universe_fetch idiom (schema/002).

CREATE TABLE scout_shortlist_verdict (
  ticker       TEXT NOT NULL,
  axis         TEXT NOT NULL CHECK (axis IN ('moat','mgmt','fad','tier')),
  value        TEXT NOT NULL,
  reason       TEXT,
  recorded_at  TEXT NOT NULL
);                                          -- re-badges APPEND; view resolves latest per (ticker,axis)
CREATE INDEX idx_scout_verdict ON scout_shortlist_verdict (ticker, axis, recorded_at);

-- Latest verdict per (ticker, axis); rowid breaks same-timestamp ties (the v_price idiom).
CREATE VIEW v_scout_shortlist_verdict AS
SELECT ticker, axis, value, reason, recorded_at
FROM (
  SELECT s.*, ROW_NUMBER() OVER (
    PARTITION BY ticker, axis ORDER BY recorded_at DESC, rowid DESC) AS rn
  FROM scout_shortlist_verdict s
) WHERE rn = 1;

CREATE TRIGGER scout_shortlist_verdict_no_update BEFORE UPDATE ON scout_shortlist_verdict
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER scout_shortlist_verdict_no_delete BEFORE DELETE ON scout_shortlist_verdict
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
```

**db.py helpers** (add near the other `append_*` / `fetch_*` helpers; place `_SCOUT_VERDICT_COLS` + `append_scout_verdict` in the append-helpers block and `fetch_scout_verdicts_current` in the fetch block):
```python
_SCOUT_VERDICT_COLS = frozenset({"ticker", "axis", "value", "reason", "recorded_at"})

def append_scout_verdict(conn, *, ticker: str, axis: str, value: str,
                         reason: str | None, recorded_at: str) -> int:
    """Append one Stage-2 review-artifact verdict row (design 2026-07-11 Part A). Append-only;
    a re-badge appends a superseding row (v_scout_shortlist_verdict resolves latest). NOT
    monitoring state - never read on a schedule."""
    return _insert(conn, "scout_shortlist_verdict", _checked(
        {"ticker": ticker, "axis": axis, "value": value, "reason": reason,
         "recorded_at": recorded_at}, _SCOUT_VERDICT_COLS, "scout_shortlist_verdict"))


def fetch_scout_verdicts_current(conn, ticker: str | None = None) -> list[Row]:
    """Latest verdict per (ticker, axis) from v_scout_shortlist_verdict, optionally one ticker."""
    sql = "SELECT * FROM v_scout_shortlist_verdict"
    params: list = []
    if ticker is not None:
        sql += " WHERE ticker = ?"
        params.append(ticker)
    return conn.execute(sql + " ORDER BY ticker, axis", params).fetchall()
```

**Failing test** (`tests/test_scout_verdict_store.py`):
```python
"""Stage-2 review-artifact round-trip: append-only table + latest-per-(ticker,axis) view
(design 2026-07-11 Part A). NOT monitoring state."""
import pytest
from agentcy import db


def test_migration_003_applied_and_append_only(tmp_db):
    # the table + view + guards exist after migrate()
    tables = {r["name"] for r in tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}
    assert "scout_shortlist_verdict" in tables
    assert "v_scout_shortlist_verdict" in tables
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="moat", value="confirmed",
                            reason="switching costs", recorded_at="2026-07-11T10:00:00Z")
    # append-only: UPDATE and DELETE both abort (invariant 1)
    with pytest.raises(Exception):
        tmp_db.execute("UPDATE scout_shortlist_verdict SET value='not-evident'")
    with pytest.raises(Exception):
        tmp_db.execute("DELETE FROM scout_shortlist_verdict")


def test_latest_wins_per_ticker_axis(tmp_db):
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="moat", value="not-evident",
                            reason="first pass", recorded_at="2026-07-11T10:00:00Z")
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="moat", value="confirmed",
                            reason="revised", recorded_at="2026-07-11T11:00:00Z")
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="fad", value="clear",
                            reason=None, recorded_at="2026-07-11T11:00:00Z")
    rows = {r["axis"]: r for r in db.fetch_scout_verdicts_current(tmp_db, "MSFT")}
    assert rows["moat"]["value"] == "confirmed"       # latest supersedes
    assert rows["moat"]["reason"] == "revised"
    assert rows["fad"]["value"] == "clear"
    # a pending axis (mgmt/tier never recorded) is simply absent, never faked
    assert set(rows) == {"moat", "fad"}
```

**Run (expect fail):**
```
uv run pytest tests/test_scout_verdict_store.py -q
```
Expected: `KeyError`/`AttributeError` on `append_scout_verdict`, or the table-existence assert fails (migration not present yet).

Apply the migration + db helpers, then:

**Run (expect pass):**
```
uv run pytest tests/test_scout_verdict_store.py -q
```

Also confirm the whole suite still migrates cleanly (the new migration is picked up by `db.migrate`):
```
uv run pytest tests/test_scout_verdict_store.py tests/test_structural_append_only.py -q
```

**Commit:**
```
feat(scout): Stage-2 review-artifact table (migration 003) + verdict store

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 4 - The bounded one-band adjustment (truth table)

Pure function `adjust_grade(graded, verdict) -> (final_grade, reason)`. Rules (design Part A / parent §4):
- **Demote one band** if `verdict.fad == "flag"` OR `verdict.mgmt == "red-flag"`.
- **Promote one band** ONLY if all four are the good value (`moat == "confirmed"` AND `mgmt == "aligned"` AND `fad == "clear"` AND `tier == "ok"`) AND `min(v, q, d, m) >= 50` (Growth `g` is NOT part of the design's "no pillar < 50" gate - the parent design predates the G pillar and names V/Q/D/M; see the note in the code).
- **Otherwise unchanged** (including any pending axis, which can never trigger a promotion; a pending axis only demotes if that axis is explicitly the flag value - and pending is never the flag value, so pending never demotes).
- Demotion takes precedence over promotion (a red-flag is never promoted).
- Bands are `["F","D","C","B","A"]`; demote = one step toward F (clamped at F), promote = one step toward A (clamped at A). The COMPOSITE NUMBER is never changed - only the letter (design: math stays deterministic).
- The reason string is ALWAYS returned (never silent): it states the move and why, or "no qualitative adjustment (...)".

**Files:**
- `agentcy/scout_review.py` (extend)
- `tests/test_scout_review_adjust.py` (NEW)

**Failing test** (`tests/test_scout_review_adjust.py`):
```python
"""Stage-2 bounded one-band adjustment truth table (design Part A / parent §4). READS
GradedName + Verdict; NEVER moves the composite number - only the letter, one band, reasoned."""
from agentcy import scout_review as sr
from agentcy import scout_grade as sg


def g(grade, *, v=60.0, q=60.0, g_=60.0, d=60.0, m=60.0, comp=60.0):
    # GradedName field order: symbol, sector, tier, v, q, g, d, m, composite, grade, note
    return sg.GradedName("X", "Technology", "Core", v, q, g_, d, m, comp, grade, "")


def test_fad_flag_demotes_one_band():
    final, reason = sr.adjust_grade(g("B"), sr.Verdict(fad="flag", reason="AI-branded"))
    assert final == "C"
    assert "demote" in reason.lower() and "fad" in reason.lower()


def test_mgmt_red_flag_demotes_one_band():
    final, reason = sr.adjust_grade(g("A"), sr.Verdict(mgmt="red-flag", reason="related-party"))
    assert final == "B"
    assert "demote" in reason.lower()


def test_demote_clamps_at_f():
    final, reason = sr.adjust_grade(g("F", comp=10.0), sr.Verdict(fad="flag"))
    assert final == "F"                                   # cannot go below F


def test_promote_all_four_good_and_no_pillar_below_50():
    v = sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok")
    final, reason = sr.adjust_grade(g("B", v=55.0, q=80.0, d=70.0, m=65.0), v)
    assert final == "A"
    assert "promote" in reason.lower()


def test_promote_clamps_at_a():
    v = sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok")
    final, _ = sr.adjust_grade(g("A", v=90.0, q=90.0, d=90.0, m=90.0, comp=90.0), v)
    assert final == "A"


def test_no_promote_when_a_pillar_below_50():
    v = sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok")
    final, reason = sr.adjust_grade(g("B", v=49.0, q=80.0, d=80.0, m=80.0), v)
    assert final == "B"                                   # gated: a pillar < 50 blocks promotion
    assert "no qualitative adjustment" in reason.lower() or "not promoted" in reason.lower()


def test_pending_axes_never_promote_and_never_demote():
    final, reason = sr.adjust_grade(g("B"), sr.Verdict(moat="confirmed"))  # other three pending
    assert final == "B"
    assert "no qualitative adjustment" in reason.lower()


def test_demote_beats_promote_when_both_would_apply():
    # all four "good" EXCEPT mgmt is a red-flag -> demotion wins, never promoted
    v = sr.Verdict(moat="confirmed", mgmt="red-flag", fad="clear", tier="ok")
    final, reason = sr.adjust_grade(g("B", v=80.0, q=80.0, d=80.0, m=80.0), v)
    assert final == "C"
    assert "demote" in reason.lower()


def test_reason_always_returned_even_when_unchanged():
    final, reason = sr.adjust_grade(g("C"), sr.Verdict())   # all pending
    assert final == "C"
    assert reason                                            # never empty / never silent
```

**Run (expect fail):**
```
uv run pytest tests/test_scout_review_adjust.py -q
```
Expected: `AttributeError: module 'agentcy.scout_review' has no attribute 'adjust_grade'`.

**Minimal implementation** (append to `agentcy/scout_review.py`):
```python
_BANDS = ("F", "D", "C", "B", "A")            # low -> high; one band = one index step


def _shift_band(grade: str, step: int) -> str:
    """Move `grade` `step` bands (negative = toward F, positive = toward A), clamped."""
    i = _BANDS.index(grade)
    return _BANDS[max(0, min(len(_BANDS) - 1, i + step))]


def adjust_grade(graded: sg.GradedName, verdict: Verdict) -> tuple[str, str]:
    """Design Part A bounded one-band adjustment, from the badges. Demote one band on a fad
    flag OR a management red-flag; promote one band ONLY if all four axes are the good value
    AND min(V,Q,D,M) >= 50; otherwise unchanged. Demotion beats promotion. The COMPOSITE is
    never moved - only the letter, one band, always reason-printed (never silent). Pending
    axes never promote and (being never a flag value) never demote.

    Pillar gate note: the design's 'no pillar < 50' predates the Stage-1.5 Growth pillar and
    names V/Q/D/M; the gate here is min(V,Q,D,M) >= 50 (G excluded, faithful to the design)."""
    grade = graded.grade
    # Demotion (takes precedence): a fad flag or a management red-flag.
    if verdict.fad == "flag" or verdict.mgmt == "red-flag":
        cause = "fad flag" if verdict.fad == "flag" else "management red-flag"
        final = _shift_band(grade, -1)
        why = f" ({verdict.reason})" if verdict.reason else ""
        return final, f"demote one band ({grade} -> {final}): {cause}{why}"
    # Promotion: all four good AND no scored pillar (V/Q/D/M) below 50.
    all_good = (verdict.moat == "confirmed" and verdict.mgmt == "aligned"
                and verdict.fad == "clear" and verdict.tier == "ok")
    if all_good:
        pillars = [graded.v, graded.q, graded.d, graded.m]
        worst = min(p for p in pillars if p is not None) if any(p is not None for p in pillars) else 0.0
        if worst >= 50.0:
            final = _shift_band(grade, +1)
            why = f" ({verdict.reason})" if verdict.reason else ""
            return final, f"promote one band ({grade} -> {final}): all four axes clear, no pillar < 50{why}"
        return grade, (f"no qualitative adjustment: all four axes clear but a pillar is "
                       f"below 50 ({worst:.0f}) - promotion gated")
    return grade, "no qualitative adjustment (axes pending or mixed; grade unchanged)"
```

**Run (expect pass):**
```
uv run pytest tests/test_scout_review_adjust.py -q
```

**Commit:**
```
feat(scout): Stage-2 bounded one-band grade adjustment (truth table)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 5 - Badges (axis -> display glyph)

A pure `badges(verdict) -> dict[str, str]` mapping each present axis to an ASCII badge for display: moat-confirmed `[+]`, moat-not-evident `[~]`, mgmt-aligned `[+]`, mgmt-neutral `[~]`, mgmt-red-flag `[x]`, fad-clear `[+]`, fad-flag `[x]`, tier-ok `[+]`, tier-correction `[t]`. Pending axes are omitted (no badge). ASCII-only so they can never trip the render lint's `_RED_GLYPHS` ban (Plan note).

**Files:**
- `agentcy/scout_review.py` (extend)
- `tests/test_scout_review_badges.py` (NEW)

**Failing test** (`tests/test_scout_review_badges.py`):
```python
"""Stage-2 badges: the four axes -> ASCII display glyphs (design Part A). ASCII-only, so a
badge can never trip the render lint's red-glyph ban."""
from agentcy import scout_review as sr


def test_badges_map_present_axes():
    v = sr.Verdict(moat="confirmed", mgmt="red-flag", fad="clear", tier="correction:Adjacent")
    b = sr.badges(v)
    assert b["moat"] == "[+]"
    assert b["mgmt"] == "[x]"
    assert b["fad"] == "[+]"
    assert b["tier"] == "[t]"


def test_pending_axes_have_no_badge():
    b = sr.badges(sr.Verdict(moat="confirmed"))
    assert set(b) == {"moat"}                       # the other three are pending -> no badge


def test_badges_are_ascii_only():
    b = sr.badges(sr.Verdict(moat="not-evident", mgmt="neutral", fad="flag", tier="ok"))
    for glyph in b.values():
        assert glyph.isascii()
```

**Run (expect fail):**
```
uv run pytest tests/test_scout_review_badges.py -q
```

**Minimal implementation** (append to `agentcy/scout_review.py`):
```python
# ASCII badges (Plan note): [+] good, [~] soft, [x] flag, [t] tier-correction. ASCII-only so a
# badge never trips the render lint's red-glyph ban. Design glyph names map here.
_BADGE = {
    ("moat", "confirmed"): "[+]", ("moat", "not-evident"): "[~]",
    ("mgmt", "aligned"): "[+]", ("mgmt", "neutral"): "[~]", ("mgmt", "red-flag"): "[x]",
    ("fad", "clear"): "[+]", ("fad", "flag"): "[x]",
    ("tier", "ok"): "[+]",
}


def badges(verdict: Verdict) -> dict[str, str]:
    """Map each PRESENT axis to its ASCII badge; pending axes are omitted. A tier correction
    (any 'correction:*') badges as '[t]' (design ✎ tier-correction)."""
    out: dict[str, str] = {}
    for axis in ("moat", "mgmt", "fad", "tier"):
        value = getattr(verdict, axis)
        if value is None:
            continue
        if axis == "tier" and value.startswith("correction:"):
            out[axis] = "[t]"
        else:
            out[axis] = _BADGE[(axis, value)]
    return out
```

**Run (expect pass):**
```
uv run pytest tests/test_scout_review_badges.py -q
```

**Commit:**
```
feat(scout): Stage-2 axis badges (ASCII, lint-safe)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 6 - `agentcy scout shortlist` CLI (dossier emission)

Add a `scout shortlist` subcommand: run the cached graded screen, select the shortlist, and print a per-name review DOSSIER - the deterministic grade + pillar scores + tier, the four Constitution questions, and doc pointers ("read the latest 10-K MD&A + business description + earnings-call transcript"). Human-readable AND parseable by the claudeclaw skill (a stable `TICKER | grade | tier | V/Q/G/D/M` header line per name). Prints the honest evidence note. NO DB write.

**Files:**
- `agentcy/cli.py` (extend the `scout` subparser + `_cmd_scout`)
- `agentcy/scout_review.py` (add `dossier_text(shortlist) -> str`)
- `tests/test_scout_review_shortlist_cli.py` (NEW)

**Wiring in `agentcy/cli.py`** - extend the existing `scout` subparser block (currently only `run`):
```python
    scout = sub.add_parser("scout", help="The Scout (H) - human-run only")
    ssub = scout.add_subparsers(dest="scout_cmd", required=True)
    srun = ssub.add_parser("run")
    srun.add_argument("recipe", choices=["qv", "grade"])
    srun.set_defaults(handler="scout")
    ssub.add_parser("shortlist", help="Stage-2 review dossier for the shortlist").set_defaults(handler="scout")
    sbadge = ssub.add_parser("badge", help="record one Stage-2 verdict axis")
    sbadge.add_argument("ticker")
    sbadge.add_argument("--moat", choices=["confirmed", "not-evident"])
    sbadge.add_argument("--mgmt", choices=["aligned", "neutral", "red-flag"])
    sbadge.add_argument("--fad", choices=["clear", "flag"])
    sbadge.add_argument("--tier", help="ok | correction:<Core|Adjacent|Outside>")
    sbadge.add_argument("--reason", default=None)
    sbadge.set_defaults(handler="scout")
    srev = ssub.add_parser("review")
    rsub = srev.add_subparsers(dest="scout_review_cmd", required=True)
    rsub.add_parser("render", help="annotated Stage-2 shortlist").set_defaults(handler="scout")
```
Then branch in `_cmd_scout` on `args.scout_cmd` (`run` keeps its current body; add `shortlist`, `badge`, `review`). The `shortlist` branch:
```python
    if args.scout_cmd == "shortlist":
        from agentcy import scout_review
        as_of = _clock().now()
        result = scout.run_graded(conn, universe_path=None, market_data=None, as_of=as_of)
        shortlist = scout_review.select_shortlist(result.graded)
        print(scout_review.dossier_text(shortlist))
        print()
        print(scout.HONEST_EVIDENCE_NOTE)
        return 0
```

**`dossier_text` in `agentcy/scout_review.py`:**
```python
_FOUR_QUESTIONS = (
    "1. Moat + 10-year test (Buffett): durable advantage (network effects / switching costs / "
    "cost advantage / brand-trust / regulatory) that plausibly survives a decade? "
    "-> moat: confirmed <name it> | not-evident <name the disruption risk>",
    "2. Management (Munger): owner-operator alignment, candid capital allocation, no "
    "promotional/evasive tone or related-party red flags? -> mgmt: aligned | neutral | red-flag",
    "3. Fad-vs-trend (Munger): durable trend or a fad dressed as one (esp. AI-branded)? "
    "-> fad: clear | flag",
    "4. Tier / circle (Naval): is the deterministic Core/Adjacent/Outside tier right for what "
    "the business actually does? -> tier: ok | correction:<Core|Adjacent|Outside>",
)
_DOC_POINTER = ("Read the latest 10-K MD&A + business description + earnings-call transcript "
                "(prose only - the deterministic layer owns all numbers).")


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.1f}"


def dossier_text(shortlist) -> str:
    """Human-readable AND claudeclaw-parseable Stage-2 dossier. Per name: a stable header line
    `TICKER | grade G | tier T | V.. Q.. G.. D.. M..`, the four Constitution questions, and the
    doc pointer. No numbers beyond the grade context (design Part A)."""
    lines = [f"Scout Stage-2 shortlist - {len(shortlist)} name(s) for qualitative review", ""]
    for g in shortlist:
        lines.append(
            f"{g.symbol} | grade {g.grade} | tier {g.tier} | "
            f"V {_fmt(g.v)} Q {_fmt(g.q)} G {_fmt(g.g)} D {_fmt(g.d)} M {_fmt(g.m)}")
        lines.append(f"  {_DOC_POINTER}")
        for q in _FOUR_QUESTIONS:
            lines.append(f"  {q}")
        lines.append("  Record verdicts with: agentcy scout badge "
                     f"{g.symbol} --moat ... --mgmt ... --fad ... --tier ... --reason \"...\"")
        lines.append("")
    return "\n".join(lines).rstrip()
```

**Failing test** (`tests/test_scout_review_shortlist_cli.py`) - reuse the graded-run seeding idiom from `tests/test_scout_graded_run.py`:
```python
"""`agentcy scout shortlist` prints a claudeclaw-parseable dossier + the honest note; no DB write."""
import bz2
import hashlib
from datetime import datetime, timezone

from agentcy import cli, config, clock as ck, db
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
CSV = ("symbol,name,sector,industry,country,market_cap\n"
       "MSFT,Microsoft,Technology,Software,United States,large_cap\n"
       "VEEV,Veeva,Technology,Health Care Technology,United States,large_cap\n")


def _universe(tmp_path):
    path = tmp_path / "universe" / "equities.bz2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bz2.compress(CSV.encode()))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(conn, sym, yf_statements, yf_series):
    store.store_statements(conn, sym, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"), fetched_at="2026-07-01T00:00:00Z")


def test_scout_shortlist_prints_dossier(tmp_db, tmp_path, monkeypatch, capsys,
                                        yf_statements, yf_series):
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner", clock=ck.SystemClock())
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    _seed(tmp_db, "VEEV", yf_statements, yf_series)
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    import agentcy.scout as sc
    real = sc.run_graded
    monkeypatch.setattr(sc, "run_graded", lambda conn, **kw: real(
        conn, market_data={"MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
                           "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9}},
        **{k: v for k, v in kw.items() if k != "market_data"}))

    rc = cli.main(["scout", "shortlist"])
    out = capsys.readouterr().out
    assert rc == 0
    # claudeclaw-parseable header line + the four questions + doc pointer + honest note
    assert "| grade " in out and "| tier " in out
    assert "moat:" in out and "mgmt:" in out and "fad:" in out and "tier:" in out
    assert "10-K MD&A" in out
    assert "promises nothing" in out.lower()
    # H: no monitoring state written
    assert db.fetch_watchlist(tmp_db) == []
    assert db.fetch_reports(tmp_db) == []
    assert db.fetch_scout_verdicts_current(tmp_db) == []
```

**Run (expect fail then pass):**
```
uv run pytest tests/test_scout_review_shortlist_cli.py -q
```

**Commit:**
```
feat(scout): agentcy scout shortlist - Stage-2 review dossier

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 7 - `agentcy scout badge <ticker>` CLI (record a verdict)

The `badge` branch of `_cmd_scout`: validate flags via a `Verdict` (constructing it re-uses the axis vocab guards from Task 2), then append one row per PROVIDED axis (omitted axis = pending = no row written, never faked FR9). `--tier` accepts `ok` or `correction:<T>` (validated by `Verdict.__post_init__`). Commit the connection. Print a one-line confirmation naming the recorded axes.

**Files:**
- `agentcy/cli.py` (add the `badge` branch)
- `tests/test_scout_review_badge_cli.py` (NEW)

**`badge` branch in `_cmd_scout`:**
```python
    if args.scout_cmd == "badge":
        from agentcy import scout_review
        verdict = scout_review.Verdict(moat=args.moat, mgmt=args.mgmt, fad=args.fad,
                                       tier=args.tier, reason=args.reason)  # validates axis vocab
        recorded_at = db.to_iso(_clock().now())
        axes = {"moat": verdict.moat, "mgmt": verdict.mgmt,
                "fad": verdict.fad, "tier": verdict.tier}
        written = []
        for axis, value in axes.items():
            if value is None:
                continue                                  # omitted = pending, never faked (FR9)
            db.append_scout_verdict(conn, ticker=args.ticker, axis=axis, value=value,
                                    reason=verdict.reason, recorded_at=recorded_at)
            written.append(axis)
        conn.commit()
        if not written:
            print(f"{args.ticker}: no axes given; nothing recorded (all pending).")
            return 0
        print(f"{args.ticker}: recorded {', '.join(written)} (Stage-2 review artifact).")
        return 0
```
(Requires `from agentcy import db` at the top of `_cmd_scout`, or a local import; `db` is already imported inside several handlers - add a local `from agentcy import db` in the badge branch to match the module's lazy-import idiom.)

**Failing test** (`tests/test_scout_review_badge_cli.py`):
```python
"""`agentcy scout badge` records provided axes as review artifacts; omitted axes stay pending."""
from datetime import datetime, timezone
from agentcy import cli, clock as ck, db

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def test_badge_records_provided_axes_only(tmp_db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    rc = cli.main(["scout", "badge", "MSFT", "--moat", "confirmed", "--fad", "clear",
                   "--reason", "switching costs; real trend"])
    out = capsys.readouterr().out
    assert rc == 0 and "recorded" in out
    rows = {r["axis"]: r for r in db.fetch_scout_verdicts_current(tmp_db, "MSFT")}
    assert set(rows) == {"moat", "fad"}                   # mgmt/tier omitted -> pending, no row
    assert rows["moat"]["value"] == "confirmed"
    assert rows["moat"]["reason"] == "switching costs; real trend"


def test_badge_tier_correction_accepted(tmp_db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    rc = cli.main(["scout", "badge", "ACME", "--tier", "correction:Adjacent"])
    assert rc == 0
    rows = {r["axis"]: r for r in db.fetch_scout_verdicts_current(tmp_db, "ACME")}
    assert rows["tier"]["value"] == "correction:Adjacent"


def test_badge_rejects_bad_tier(tmp_db, monkeypatch):
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    import pytest
    with pytest.raises(ValueError):
        cli.main(["scout", "badge", "ACME", "--tier", "Core"])   # must be ok|correction:<T>
```

**Run (expect fail then pass):**
```
uv run pytest tests/test_scout_review_badge_cli.py -q
```

**Commit:**
```
feat(scout): agentcy scout badge - record a Stage-2 verdict axis

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 8 - `agentcy scout review render` + annotated render (+ golden)

A new render module `agentcy/render/scout_review.py` parallel to `render/scout.py`: an annotated shortlist showing, per name, `deterministic grade -> badges -> one-band-adjusted final grade + reason`, plus the honest evidence note. Two skins from ONE context, `output_class="notice"`, the evidence note rides in `owner_spans` (RF1). `lint(r) == []`. A name with no verdicts renders with its deterministic grade unchanged and "qualitative: pending". Golden files. The `review render` CLI branch runs the cached grade, selects the shortlist, loads current verdicts from the review artifact, renders, and prints markdown. It NEVER writes a monitoring table (no `append_report`, no `append_alert`, etc.).

**Files:**
- `agentcy/render/scout_review.py` (NEW)
- `agentcy/cli.py` (add the `review render` branch)
- `tests/test_render_scout_review.py` (NEW)
- `tests/golden/scout_review.md.txt` + `tests/golden/scout_review.html.txt` (NEW, via `UPDATE_GOLDEN=1`)

**Render module** (`agentcy/render/scout_review.py`):
```python
"""Stage-2 annotated shortlist render (design 2026-07-11 Part A): per name, the deterministic
grade -> badges -> one-band-adjusted final grade + reason, plus the honest evidence note. Two
skins from ONE context; lint-clean (output_class 'notice'); the whole evidence note rides in
owner_spans (RF1) so its benchmark token is exempt. Review artifact only - NEVER a monitoring
write. A name with no verdicts renders unchanged with 'qualitative: pending'."""
from __future__ import annotations

from dataclasses import dataclass

from agentcy import scout_review as sr
from agentcy.render import common as cm
from agentcy.render.contexts import RenderedOutput

_HEADER = ("Ticker", "Tier", "Det", "Final", "Qualitative")


@dataclass(frozen=True)
class ScoutReviewContext:
    as_of_label: str
    shortlist: tuple                     # tuple[scout_grade.GradedName, ...] (already selected + ordered)
    verdicts: dict                       # {ticker: scout_review.Verdict}
    evidence_note: str


def _badge_str(verdict: sr.Verdict) -> str:
    b = sr.badges(verdict)
    if not b:
        return "pending"
    return " ".join(f"{axis}{glyph}" for axis, glyph in b.items())


def _rows(ctx: ScoutReviewContext):
    body = []
    reasons = []
    for g in ctx.shortlist:
        verdict = ctx.verdicts.get(g.symbol, sr.Verdict())
        final, reason = sr.adjust_grade(g, verdict)
        body.append((g.symbol, g.tier, g.grade, final, _badge_str(verdict)))
        reasons.append(f"  {g.symbol}: {reason}")
    return body, reasons


def render_scout_review(ctx: ScoutReviewContext) -> RenderedOutput:
    title = f"The Scout - Stage-2 annotated shortlist - {ctx.as_of_label}"
    body, reasons = _rows(ctx)
    segs: list[tuple] = [("table", body)]
    for r in reasons:
        segs.append(("text", r))
    segs.append(("text", ""))
    segs.append(("text", ctx.evidence_note))

    md_lines = ["# " + title, ""]
    html_lines = ["<b>" + cm.esc(title) + "</b>", ""]
    for kind, payload in segs:
        if kind == "table":
            md_lines.append(cm.pre_table(payload, header=_HEADER, skin="md"))
            html_lines.append(cm.pre_table(payload, header=_HEADER, skin="html"))
        else:
            md_lines.append(payload)
            html_lines.append(cm.esc(payload))

    return RenderedOutput(
        telegram_html="\n".join(html_lines),
        markdown="\n".join(md_lines),
        output_class="notice",
        owner_spans=(ctx.evidence_note,),   # RF1: the whole note is the lint escape hatch
    )
```

**`review render` branch in `_cmd_scout`:**
```python
    if args.scout_cmd == "review" and args.scout_review_cmd == "render":
        from agentcy import scout_review
        from agentcy.render.scout_review import ScoutReviewContext, render_scout_review
        from agentcy.render import common as cm
        as_of = _clock().now()
        result = scout.run_graded(conn, universe_path=None, market_data=None, as_of=as_of)
        shortlist = scout_review.select_shortlist(result.graded)
        verdicts: dict = {}
        for g in shortlist:
            axes = {r["axis"]: r for r in db.fetch_scout_verdicts_current(conn, g.symbol)}
            verdicts[g.symbol] = scout_review.Verdict(
                moat=axes["moat"]["value"] if "moat" in axes else None,
                mgmt=axes["mgmt"]["value"] if "mgmt" in axes else None,
                fad=axes["fad"]["value"] if "fad" in axes else None,
                tier=axes["tier"]["value"] if "tier" in axes else None,
                reason=next((axes[a]["reason"] for a in ("moat", "mgmt", "fad", "tier")
                             if a in axes and axes[a]["reason"]), None))
            ctx = ScoutReviewContext(as_of_label=cm.ams_date_label(as_of),
                                     shortlist=tuple(shortlist), verdicts=verdicts,
                                     evidence_note=result.evidence_note)
        print(render_scout_review(ctx).markdown)
        return 0
```
(Add `from agentcy import db` local import in this branch, matching the lazy-import idiom. Note: build `ctx` after the loop; the snippet above builds it inside for brevity - the executor should hoist the `ctx = ...` construction to AFTER the loop so all verdicts are collected first.)

**Failing test** (`tests/test_render_scout_review.py`):
```python
"""Stage-2 annotated render: det grade -> badges -> one-band-adjusted final + reasons + honest
note; two skins from one context; lint-clean; pending name renders unchanged. Golden-backed."""
from agentcy.render.scout_review import ScoutReviewContext, render_scout_review
from agentcy.render.lint import lint, _BENCH
from agentcy import scout_review as sr
from agentcy import scout_grade as sg


def _ctx():
    shortlist = (
        sg.GradedName("MSFT", "Technology", "Core", 55.0, 80.0, 60.0, 70.0, 65.0, 72.0, "B", ""),
        sg.GradedName("FADS", "Technology", "Adjacent", 60.0, 60.0, 60.0, 60.0, 60.0, 66.0, "B", ""),
        sg.GradedName("PEND", "Technology", "Outside", 60.0, 60.0, 60.0, 60.0, 60.0, 55.0, "C", ""),
    )
    verdicts = {
        "MSFT": sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok",
                           reason="switching costs; founder-led; real trend"),
        "FADS": sr.Verdict(fad="flag", reason="AI-branded rollup"),
        # PEND: no verdict -> pending, grade unchanged
    }
    return ScoutReviewContext(as_of_label="Fri 10 Jul 2026", shortlist=shortlist,
                              verdicts=verdicts, evidence_note=sg.HONEST_EVIDENCE_NOTE)


def test_annotated_render_promote_demote_pending(golden):
    r = render_scout_review(_ctx())
    assert r.output_class == "notice"
    md = r.markdown
    # MSFT: all four clear + no pillar < 50 -> promoted B -> A, reason printed
    assert "promote one band (B -> A)" in md
    # FADS: fad flag -> demoted B -> C, reason printed
    assert "demote one band (B -> C)" in md and "fad" in md.lower()
    # PEND: no verdict -> unchanged, qualitative pending
    assert "pending" in md.lower()
    # honest evidence note present
    assert "promises nothing" in md.lower()
    # lint-clean with the benchmark-token note exempt via owner_spans (RF1)
    assert sg.HONEST_EVIDENCE_NOTE in r.owner_spans
    assert _BENCH.search(sg.HONEST_EVIDENCE_NOTE) is not None
    assert lint(r) == []
    golden("scout_review.md.txt", r.markdown)
    golden("scout_review.html.txt", r.telegram_html)


def test_both_skins_carry_every_symbol():
    r = render_scout_review(_ctx())
    for sym in ("MSFT", "FADS", "PEND"):
        assert sym in r.markdown and sym in r.telegram_html
    assert "```" in r.markdown and "<pre>" in r.telegram_html
```

**Run (record golden, then verify):**
```
UPDATE_GOLDEN=1 uv run pytest tests/test_render_scout_review.py -q
uv run pytest tests/test_render_scout_review.py -q
```
Expected: first records the two goldens; second passes byte-exact. INSPECT the recorded goldens by eye before committing (confirm the promote/demote/pending lines read correctly and no smart quotes / non-ASCII leaked in - badges are ASCII `[+]/[~]/[x]/[t]` and appear only in the annotated glyph column via `_badge_str`... note this render uses `axis<glyph>` badge strings; confirm they are ASCII).

Then add the CLI branch and a CLI smoke test (append to `tests/test_render_scout_review.py` or a small `tests/test_scout_review_render_cli.py` reusing the Task 6 seeding idiom) asserting `cli.main(["scout", "review", "render"])` returns 0, prints the annotated table, and writes NO report row:
```python
def test_review_render_cli_writes_no_monitoring(tmp_db, tmp_path, monkeypatch, capsys,
                                                yf_statements, yf_series):
    # reuse the Task 6 universe/seed helpers (copy them into this file)
    ...  # seed MSFT+VEEV, monkeypatch _open/_clock/run_graded market_data as in Task 6
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="fad", value="flag",
                            reason="test", recorded_at="2026-07-08T05:00:00Z")
    rc = cli.main(["scout", "review", "render"])
    out = capsys.readouterr().out
    assert rc == 0 and "Stage-2 annotated shortlist" in out
    assert db.fetch_reports(tmp_db) == []            # NEVER a monitoring write
```

**Run (expect pass):**
```
uv run pytest tests/test_render_scout_review.py -q
```

**Commit:**
```
feat(scout): agentcy scout review render - annotated Stage-2 shortlist + golden

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 9 - Structural gate (no new dep, no LLM, Stage-1 math frozen, review-artifact-only writes)

One structural test file asserting Part A's constitution boundaries, PLUS a one-line edit to the existing Stage-1 fence (relax the "Stage-2 not built" assertion now that Stage-2 legitimately exists). Assert: (a) no new pip dependency and no new optional-extra; (b) no LLM/anthropic import from the Stage-2 modules; (c) Stage-1 grade math is byte-unchanged (the shortlist/adjustment READ `GradedName`, they do not touch grading); (d) Stage-2 writes ONLY the review-artifact table - the `scout_review` module and the render module contain NO monitoring-table writers.

**Files:**
- `tests/test_scout_stage2_structural.py` (NEW)
- `tests/test_scout_stage1_structural.py` (EDIT - relax the one `qualitative` assertion)

**Edit `tests/test_scout_stage1_structural.py`** - the module `test_stage2_and_populator_are_explicit_followons` currently asserts `not any("qualitative" in m.lower() for m in sys.modules)`. Stage-2 Part A is now built (as `scout_review`, no "qualitative" in the name), so replace that assertion's Stage-2 clause while keeping the populator clause honest:
```python
def test_populator_is_an_explicit_followon():
    # The archive batch populator is NOT built by Stage-1 or Stage-2 Part A (Explicit follow-on).
    # Stage-2's *interface + desk path* IS built (agentcy.scout_review); the API adapter and the
    # claudeclaw droplet install are Part B / follow-ons, not in this import graph.
    import sys
    assert not any("populate_batch" in m.lower() for m in sys.modules)
```
(Rename the test as shown so its name no longer over-claims; do NOT delete the file. If the executor prefers, keep the original test name and simply drop the `qualitative` line - the requirement is only that the false "Stage-2 unbuilt" assertion no longer fails once `scout_review` is imported by the suite.)

**New structural test** (`tests/test_scout_stage2_structural.py`):
```python
"""Scout Stage-2 (Part A) phase gate (design 2026-07-11 + constitution NFR3/NFR7/FR9):
no new pip dependency, no LLM import, Stage-1 grade math frozen, and Stage-2 writes ONLY the
review-artifact table (no monitoring-table writes)."""
import importlib
import inspect
import sys
import tomllib
from pathlib import Path

import agentcy.scout_review  # noqa: F401
import agentcy.render.scout_review  # noqa: F401
from agentcy import scout_grade as sg


def test_no_new_pip_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {d.split("==")[0].split(">")[0].split("[")[0].strip().lower() for d in deps}
    assert names == {"yfinance", "pandas", "scipy", "quantstats"}
    extras = data["project"]["optional-dependencies"]
    assert set(extras) == {"scout"}


def test_stage2_imports_no_llm():
    for mod in ("agentcy.scout_review", "agentcy.render.scout_review"):
        importlib.reload(importlib.import_module(mod))
    banned = ("anthropic", "openai", "langchain", "llama", "cohere", "google.generativeai")
    loaded = set(sys.modules)
    assert not any(b in m for b in banned for m in loaded), (
        "Stage-2 Part A is deterministic/desk-only: no LLM client may be imported")


def test_stage1_grade_math_unchanged():
    # the tunable surface (weights + bands) is byte-identical to Stage-1; Stage-2 never edits it
    assert (sg.W_V, sg.W_Q, sg.W_G, sg.W_D, sg.W_M) == (0.25, 0.25, 0.20, 0.15, 0.15)
    assert sg._GRADE_BANDS == ((80.0, "A"), (65.0, "B"), (50.0, "C"), (35.0, "D"))
    # scout_review imports scout_grade but defines NO grading function of its own
    import agentcy.scout_review as srv
    for name in ("composite", "grade_universe", "grade_letter", "sector_percentile"):
        assert not hasattr(srv, name), f"scout_review must not redefine Stage-1 {name}"


def test_stage2_writes_only_the_review_artifact_table():
    # the Stage-2 modules touch NO monitoring-table writer: only append_scout_verdict is allowed
    banned_writers = ("append_report", "append_alert", "append_trigger", "append_trigger_check",
                      "append_thesis", "append_positions", "append_journal_entry",
                      "update_alert_resolution", "append_watchlist_item")
    src = inspect.getsource(agentcy.scout_review) + inspect.getsource(agentcy.render.scout_review)
    for w in banned_writers:
        assert w not in src, f"Stage-2 must not call monitoring writer {w}"
```

**Run (expect pass; also run the two edited/adjacent Stage-1 fences):**
```
uv run pytest tests/test_scout_stage2_structural.py tests/test_scout_stage1_structural.py tests/test_scout_stage1_5_structural.py -q
```

**Commit:**
```
test(scout): Stage-2 Part A structural gate + relax Stage-1 followon fence

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 10 - Full-suite green + license gate

**Files:** none.

**Run:**
```
uv run pytest -q
uv run python tools/license_gate.py
```

**Expected:** the suite passes with the SAME skip count as Task 0 (3 skipped) and a strictly higher pass count (Task 0 baseline + all the new tests). The license gate prints `LICENSE GATE: clean` (Part A added no dependency). If either fails, use superpowers:systematic-debugging - do not paper over a red result.

**Commit** (only if any incidental cleanup was needed; otherwise the Task 9 commit already closed the work):
```
chore(scout): Stage-2 Part A - full suite green, license gate clean

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Explicit follow-ons (NOT built here)

- **Part B - claudeclaw on the droplet.** Install `claude` (Claude Code CLI) + `moazbuilds/claudeclaw` on the Ubuntu box (authed to the owner's Claude Code subscription, runtime is Node/Bun entirely outside the agentcy venv - NFR7 stays clean), author the **`scout-review` skill** (a markdown skill whose prompt IS the Buffett/Munger/Naval rubric: run `agentcy scout shortlist`, read each name's 10-K MD&A / annual report / earnings-call transcript from the web, answer the four questions, record each via `agentcy scout badge ...`, run `agentcy scout review render`, deliver to the owner), wire the **human trigger** (owner messages claudeclaw; never cron), and give claudeclaw a **separate bot/channel** so it never collides with the `agentcy-bot` Telegram daemon. Validated by a live owner-triggered shakedown on the box, like the initial deploy.
- **The hand-rolled Anthropic API adapter** - a second `QualitativeReviewer` implementation behind the Task 2 interface (automated, needs a key + a few cents/run, journaled config choice of active adapter). Deliberately NOT built: the DeskReviewer + claudeclaw path covers v2.1 with no API key and no new dependency. When built, it must respect NFR7 (a hand-rolled client, not the `anthropic` SDK if that pulls a banned transitive license) and must still run ONLY inside a human-triggered session (never the scheduled runtime).
- **Grade-render-at-scale / the archive batch populator** - Stage-1 grading over the full ~22.5k US+EU universe reads the cached fundamentals archive; the populator that fills that archive on a paced background cadence is a separate build (parent design §8 item 2). Until it lands, `run_graded` grades only names already in the archive - a triggered session over a partial archive returns fast but a "not-cached-count" of un-graded names should eventually be surfaced (an honest "N of the universe not yet in cache" line on the graded/shortlist output). That surfacing line is a small follow-on, out of Part A scope.
