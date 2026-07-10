# Scout Stage-1.5 Grader De-bias - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** De-bias the Stage-1 Scout grader so reinvesting compounders are no longer penalized or vetoed relative to mature cash cows - by adding a normalized owner-earnings figure, a Sloan accrual fix, a new ROIC-gated Growth pillar (G), a re-weighted composite, a cash-destruction veto carve-out, and an honest grade-vs-thesis framing line. Discovery path only; the live monitoring path is untouched.

**Architecture:** Pure deterministic math over the append-only fundamentals archive (`agentcy/fetch/store.py`) plus FinanceDatabase categoricals. No LLM, no new pip dependency, no live network. All five changes land in `agentcy/scout_grade.py` and `agentcy/render/scout.py`; a screening-scoped normalized-earnings helper lives in `agentcy/scout_grade.py` (rationale in Plan notes). The binding design is `docs/plans/2026-07-10-scout-stage1.5-debias-design.md`.

**Tech Stack:** Python 3.13 (uv-managed CPython), pandas, scipy, stdlib. Test runner is `uv run pytest`. Branch: `implementation`.

---

## Review fixes (apply first - from the pre-execution fidelity review)

1. **Task 0:** before trusting ANY downstream count, run `uv run pytest -q` and confirm the live baseline is exactly **856 passed / 3 skipped**. If it differs, STOP and reconcile every task's running total against the true baseline before proceeding.
2. **Task 3 (the restored `oe` binding):** keep it on `store.owner_fcf_ttm` for this one commit - Task 4 deletes the call entirely, so the source is irrelevant here. Ignore any "from the normalized figure" prose in Task 3; normalization of the per-share growth leg happens in Task 4.
3. **Task 5 Step 5 (goldens):** regenerate BOTH `scout_graded.md.txt` AND `scout_graded.html.txt` via `UPDATE_GOLDEN=1`; never hand-edit column spacing. Then re-run without `UPDATE_GOLDEN` to prove they pin.

The review found no blocking or major issues; it independently verified the G-pillar neutral-50 degrade (never INSUFFICIENT), the composite re-weight updates every moving assertion, the veto carve-out ROIC units are consistent (percentage vs percentage) and not a hype loophole, normalized earnings de-biases V/Q/D + the G growth leg while `store.owner_fcf_ttm` stays byte-unchanged, and the Sloan accrual uses OCF with per-share growth genuinely moved M->G.

---

## Plan notes (assumptions, simplest compliant choice)

1. **D&A row label.** The design names the cashflow row `Depreciation And Amortization`. That row is **NOT** a pinned row (`agentcy/fetch/yf.py` `PINNED_ROWS["cashflow"] = ("Operating Cash Flow", "Capital Expenditure")`) and is **absent** from the recorded fixture `tests/fixtures/yf/msft_statements.json` (its cashflow index is `["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow", "Stock Based Compensation", "End Cash Position", "Changes In Cash", "Repurchase Of Capital Stock", "Cash Dividends Paid"]`). Therefore: (a) the exact string the code reads from a period payload is `"Depreciation And Amortization"`; (b) for the existing MSFT fixture the D&A-absent fallback is the DEFAULT path, so `normalized_owner_fcf == conservative owner_fcf` for MSFT unless a test explicitly injects a D&A row. Every existing MSFT-fixture-based expected number that moves does so ONLY because of re-weighting / new pillars / the accrual fix - **not** because normalized differs from conservative for MSFT (they are equal). New tests that exercise the maintenance-CapEx discount inject a `Depreciation And Amortization` row explicitly.

2. **Where normalized owner earnings lives.** In `agentcy/scout_grade.py`, as a new module-level function `normalized_owner_fcf_ttm(conn, yf_ticker, *, as_of)` returning a plain dataclass `NormalizedOwnerEarnings` (NOT a `Stamped`). Rationale: the design says "Scout discovery only" and forbids touching `store.owner_fcf_ttm` or the store's monitoring surface; keeping the new figure in the Scout layer makes the discovery-only boundary structural (nothing in `store.py`/monitoring can import it by accident) and keeps `store.py` byte-stable except that we reuse its existing read helpers (`store.statement_history`, `store._period_payloads`, `store.shares_history`) without modification. The function mirrors the exact per-period construction of `store.owner_fcf_ttm` (newest 4 quarters, all-or-None, per-share via `shares_history` at/before `as_of`) so its degradation semantics match.

3. **Normalized formula, per period.** `normalized_owner_fcf(period) = OCF - min(|CapEx|, D&A) - SBC`, where `OCF = "Operating Cash Flow"`, `CapEx = "Capital Expenditure"` (stored negative; use `abs()`), `SBC = "Stock Based Compensation"` (absent -> 0.0, matching `store.owner_fcf_ttm`), `D&A = "Depreciation And Amortization"`. **D&A-absent fallback:** when the D&A row is missing/None for a period, use `abs(|CapEx|)` as the maintenance proxy so `min(|CapEx|, D&A) == |CapEx|` and the period's normalized value collapses to the conservative `(OCF - |CapEx|) - SBC`. This is applied per period (a name can have D&A in some periods and not others). TTM = sum over the newest 4 quarters (all-or-None: any period missing OCF or CapEx -> None). Per-share and margin computed exactly as in `store.owner_fcf_ttm` (share count at/before `as_of` from `store.shares_history`; margin = TTM normalized / TTM revenue when revenue > 0 else 0.0).

4. **Revenue-growth window construction.** Annualized revenue growth over the archive window = take the income "Total Revenue" per period (drop periods with an absent/zero value), sort ascending by `period_end`, use the OLDEST usable and NEWEST usable revenue, annualize by the actual calendar span: `growth_pct = 100 * ((newest_rev / oldest_rev) ** (1/years) - 1)` where `years = max((newest_date - oldest_date).days / 365.25, 1e-9)`. Requires >= 2 usable periods and `oldest_rev > 0`; else the leg is None. The honest label reuses the same `<3yr window` caveat wording pattern as `_per_share_ofcf_growth` (`"... annualized - 3yr CAGR not computable from archive"`). This mirrors the robust, gap-tolerant intent without needing same-quarter-prior-year matching (Stage-1.5 only needs one annualized figure, not a per-quarter series).

5. **G pillar leg scoring.** Each G leg is `sector_percentile(raw, cohort, higher_better=True) * min(1, ROIC / 15%)` via a small reused helper `growth_leg_score(pct, cohort, roic_pct)` that mirrors `roic_leg_score`'s floor factor `max(0.0, min(1.0, roic_pct / (100.0 * QV_ROIC_MIN)))`. G is the equal-weighted `pillar_score` of the present legs. If BOTH legs are None (thin data), G degrades to the neutral constant `NEUTRAL_G = 50.0` (unknown != punished) - NOT None - so the name still grades on V/Q/D/M.

6. **Veto carve-out signature.** `veto_check(...)` gains two keyword-only params `roic_pct` and `revenue_growth_pct` (both may be None). The cash-destruction branch is spared ONLY when `roic_pct is not None and roic_pct > 15.0 and revenue_growth_pct is not None and revenue_growth_pct > 10.0`; sparing returns `Veto(vetoed=False, penalty=0, reason="<flagged note>")` (a flagged non-veto, printed downstream via the existing `g.note` render path). The leverage branch is unchanged and still runs first. `grade_universe` passes the real `roic_pct` (from `bundle["q"]`) and the real `revenue_growth_pct` (from the new G raw metric).

7. **Baseline test count.** The prompt cited `784 passed, 3 skipped`. The ACTUAL current `implementation` branch baseline (verified `uv run pytest -q`) is **856 passed, 3 skipped**. Use 856/3 as the green target: every task's full-suite run must end `<N> passed, 3 skipped` with 0 failures, where `<N>` grows only by the net new tests this plan adds. The 3 skips are the Windows AF_UNIX/git skips (they run on the Linux target).

8. **Composite/render skin.** The render table header `_HEADER` in `agentcy/render/scout.py` gains a `"G"` column and `_body_rows` emits `_fmt_pillar(g.g)`; `GradedName` gains a `g: float | None` field placed between `d` and `m` is NOT chosen - to minimize churn we append `g` AFTER `m` in the dataclass field order but render it in V/Q/G/D/M column order. See Task 5 for the exact field order decision (g appended last-but-one, see code). Goldens `tests/golden/scout_graded.{md,html}.txt` regenerate via `UPDATE_GOLDEN=1`.

9. **Offline discipline.** All new tests use the autouse `no_network` guard, seed via `store.store_statements`/`store.store_shares` (which call `db.append_fundamentals_period`/`db.append_shares_rows`), and pin `as_of` explicitly. No test performs network I/O.

---

## Task 0 - Branch and baseline

**Files:** none (git only).

Confirm you are on branch `implementation` and the suite is green before touching code.

```
git rev-parse --abbrev-ref HEAD          # must print: implementation
uv run pytest -q
```

**Expected:** `856 passed, 3 skipped`. If the count differs, STOP and report - do not proceed against a red or drifted baseline.

No commit for this task.

---

## Task 1 - Normalized owner earnings (Scout-layer figure + D&A-absent fallback)

Add a new normalized owner-earnings computation to `agentcy/scout_grade.py`. Do NOT modify `store.owner_fcf_ttm`.

### Files
- **Create:** `tests/test_scout_grade_normalized.py`
- **Modify:** `agentcy/scout_grade.py` (add dataclass + function near the top, after the imports block, before `value_metrics`)

### Step 1 - write the failing test

Create `tests/test_scout_grade_normalized.py`:

```python
"""Stage-1.5 normalized owner earnings (design change 1): OCF - min(|CapEx|, D&A) - SBC,
per-period + TTM + per-share + margin, Scout discovery only. store.owner_fcf_ttm is
UNCHANGED and remains the conservative figure.

D&A source is the cashflow 'Depreciation And Amortization' row; when it is ABSENT for a
period the maintenance proxy falls back to |CapEx| so normalized collapses to conservative
(a safe degradation, never an error). The recorded msft_statements fixture has NO D&A row,
so for MSFT normalized == conservative; the discount is exercised by injecting a D&A row.
"""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed_msft(conn, yf_statements, yf_series):
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_normalized_equals_conservative_when_no_da_row(tmp_db, yf_statements, yf_series):
    """The fixture has no 'Depreciation And Amortization' row, so min(|CapEx|, D&A) falls
    back to |CapEx| and normalized owner-FCF == store.owner_fcf_ttm's conservative figure."""
    _seed_msft(tmp_db, yf_statements, yf_series)
    norm = sg.normalized_owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF)
    cons = store.owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF)
    assert norm is not None and cons is not None
    # conservative TTM owner_fcf = 75.4e9 (see test_scout_grade_value)
    assert round(norm.owner_fcf_ttm / 1e9, 1) == 75.4
    assert round(norm.owner_fcf_ttm, 2) == round(cons.value.owner_fcf_ttm, 2)
    # margin + per-share also match the conservative figure in the D&A-absent case
    assert round(norm.owner_fcf_margin_ttm, 8) == round(cons.value.owner_fcf_margin_ttm, 8)
    assert round(norm.owner_fcf_per_share_ttm, 6) == round(cons.value.owner_fcf_per_share_ttm, 6)


def test_normalized_discounts_capex_to_da_when_da_present(tmp_db, yf_statements, yf_series):
    """With a D&A row SMALLER than |CapEx|, maintenance CapEx = D&A, so normalized owner-FCF
    is HIGHER than conservative (growth CapEx is no longer fully subtracted)."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    # |CapEx| per period = 13,12,11,10 e9. Add D&A = 5e9 each < |CapEx|, so min = 5e9.
    cf.loc["Depreciation And Amortization"] = [5e9, 5e9, 5e9, 5e9]
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    norm = sg.normalized_owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF)
    # conservative TTM = sum(OCF) - sum(|CapEx|) - sum(SBC)
    #   = (36+34+32+30) - (13+12+11+10) - (2.8+2.7+2.6+2.5) = 132 - 46 - 10.6 = 75.4e9
    # normalized TTM = sum(OCF) - sum(min(|CapEx|,D&A)) - sum(SBC)
    #   = 132 - (5*4) - 10.6 = 132 - 20 - 10.6 = 101.4e9
    assert round(norm.owner_fcf_ttm / 1e9, 1) == 101.4


def test_normalized_per_period_fallback_is_per_period(tmp_db, yf_statements, yf_series):
    """A D&A row present in SOME periods and absent (NaN) in others: each period uses its own
    maintenance proxy - D&A where present, |CapEx| where absent."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    cols = list(cf.columns)                       # newest first: 2026-03-31 ... 2025-06-30
    # D&A present only in the two newest periods (5e9), NaN in the two oldest.
    cf.loc["Depreciation And Amortization"] = [5e9, 5e9, float("nan"), float("nan")]
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    norm = sg.normalized_owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF)
    # newest two: min(13,5)=5 and min(12,5)=5 ; oldest two fall back to |CapEx| 11 and 10.
    # maintenance sum = 5+5+11+10 = 31e9 ; OCF sum 132e9 ; SBC 10.6e9
    #   normalized = 132 - 31 - 10.6 = 90.4e9
    assert round(norm.owner_fcf_ttm / 1e9, 1) == 90.4


def test_normalized_none_when_not_computable(tmp_db, yf_series):
    # no statements -> not computable -> None (matches store.owner_fcf_ttm's contract)
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    assert sg.normalized_owner_fcf_ttm(tmp_db, "MSFT", as_of=AS_OF) is None
```

### Step 2 - run, see it fail

```
uv run pytest tests/test_scout_grade_normalized.py -v
```

**Expected:** all four tests FAIL with `AttributeError: module 'agentcy.scout_grade' has no attribute 'normalized_owner_fcf_ttm'`.

### Step 3 - implement

In `agentcy/scout_grade.py`, add the following AFTER the module imports (after the `from agentcy.scout import HONEST_EVIDENCE_NOTE` line) and BEFORE `def value_metrics`:

```python
@dataclass(frozen=True)
class NormalizedOwnerEarnings:
    """Stage-1.5 discovery-only owner earnings (design change 1): maintenance-CapEx proxy is
    min(|CapEx|, D&A) so high-return GROWTH CapEx is not treated as a cost. Distinct from
    store.OwnerEarnings (the conservative figure that guards held positions, left unchanged)."""
    owner_fcf_ttm: float
    owner_fcf_per_share_ttm: float
    owner_fcf_margin_ttm: float
    periods_used: tuple[str, ...]


def normalized_owner_fcf_ttm(conn, yf_ticker: str, *, as_of: datetime
                             ) -> NormalizedOwnerEarnings | None:
    """Scout discovery-only normalized owner earnings: sum over the newest 4 quarters of
    (OCF - min(|CapEx|, D&A) - SBC). D&A is the cashflow 'Depreciation And Amortization'
    pinned row; ABSENT (missing/NaN) for a period -> maintenance proxy = |CapEx| so that
    period's normalized value equals the conservative (OCF - |CapEx|) - SBC (a safe
    degradation, never an error - plan note 1/3). ANY period missing OCF or CapEx, or fewer
    than 4 quarters, or no share count at/before as_of -> None (matches
    store.owner_fcf_ttm's not-computable contract). store.owner_fcf_ttm is NOT modified."""
    cf = store.statement_history(conn, yf_ticker, "cashflow", as_of=as_of)
    inc = store.statement_history(conn, yf_ticker, "income", as_of=as_of)
    cf_pay = store._period_payloads(cf.value)
    inc_pay = store._period_payloads(inc.value)
    periods = sorted(cf_pay, reverse=True)[:4]               # newest 4 quarters
    if len(periods) < 4:
        return None
    normalized = revenue = 0.0
    for p in periods:
        cell = cf_pay[p]
        ocf = cell.get("Operating Cash Flow")
        capex = cell.get("Capital Expenditure")
        if ocf is None or capex is None:
            return None
        capex_abs = abs(float(capex))
        da = cell.get("Depreciation And Amortization")       # absent/NaN -> fall back to |CapEx|
        maint = min(capex_abs, float(da)) if da is not None else capex_abs
        sbc = float(cell.get("Stock Based Compensation") or 0.0)
        normalized += float(ocf) - maint - sbc
        rev = inc_pay.get(p, {}).get("Total Revenue")
        revenue += float(rev) if rev is not None else 0.0

    shares = store.shares_history(conn, yf_ticker, as_of=as_of)
    if len(shares.value) == 0:
        return None
    at_or_before = shares.value[shares.value.index <= pd.Timestamp(as_of.date())]
    if len(at_or_before) == 0:
        return None
    share_count = float(at_or_before.iloc[-1])
    if share_count <= 0:
        return None
    per_share = normalized / share_count
    margin = (normalized / revenue) if revenue > 0 else 0.0
    return NormalizedOwnerEarnings(normalized, per_share, margin, tuple(sorted(periods)))
```

Note: `store._period_payloads` decodes a payload with `float()`, and JSON `NaN` is stored as `null` (see `store.store_statements`: `None if pd.isna(v) else float(v)`), so an injected `float("nan")` D&A cell round-trips to `None` in the payload and correctly triggers the fallback. Verify by running the per-period test.

### Step 4 - run, see it pass

```
uv run pytest tests/test_scout_grade_normalized.py -v
uv run pytest -q
```

**Expected:** the 4 new tests pass; full suite `860 passed, 3 skipped` (856 + 4 new; nothing else changed - `store.owner_fcf_ttm` and every existing formula are untouched this task).

### Step 5 - commit

```
git add agentcy/scout_grade.py tests/test_scout_grade_normalized.py
git commit -m "$(cat <<'EOF'
feat(scout): normalized owner earnings for Stage-1.5 de-bias (OCF - min(CapEx, D&A) - SBC)

Scout discovery-only figure; store.owner_fcf_ttm unchanged. D&A-absent -> |CapEx| fallback
so normalized collapses to conservative (safe degradation). Per-period maintenance proxy.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 2 - Rewire V / Q / D to the normalized figure

Point `value_metrics`, `quality_metrics`, and `durability_metrics` (self-funding leg + the cash-destruction per-period input) at the normalized owner-earnings figure. For the MSFT fixture normalized == conservative (plan note 1), so most existing MSFT expected numbers do NOT move; the change is that the source is now `normalized_owner_fcf_ttm`. We add tests proving the normalized figure is the one consumed (via an injected D&A row).

### Files
- **Modify:** `agentcy/scout_grade.py` (`value_metrics`, `quality_metrics`, `durability_metrics`, `_owner_fcf_negative_all_periods`)
- **Modify:** `tests/test_scout_grade_value.py` (add one normalized-source test)
- **Modify:** `tests/test_scout_grade_quality.py` (add one normalized-source test)
- **Modify:** `tests/test_scout_grade_durability.py` (add one normalized-source test)

### Step 1 - write the failing tests

Append to `tests/test_scout_grade_value.py`:

```python
def test_value_uses_normalized_owner_fcf(tmp_db, yf_statements, yf_series):
    """Stage-1.5: V consumes the NORMALIZED owner-FCF. Inject a small D&A row so normalized
    (101.4e9) > conservative (75.4e9); the yield/p_owner_fcf must reflect 101.4e9."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    cf.loc["Depreciation And Amortization"] = [5e9, 5e9, 5e9, 5e9]
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    m = sg.value_metrics(tmp_db, "MSFT", market_cap=2.8e12, total_debt=59e9,
                         cash=84e9, as_of=AS_OF)
    assert round(m["owner_fcf_ttm"] / 1e9, 1) == 101.4       # normalized, not 75.4
    assert round(m["owner_fcf_yield"], 4) == round(101.4e9 / 2.775e12, 4)
```

Append to `tests/test_scout_grade_quality.py`:

```python
def test_quality_owner_fcf_margin_uses_normalized(tmp_db, yf_statements, yf_series):
    """Stage-1.5: Q's owner-FCF margin uses the NORMALIZED figure. With D&A injected,
    margin% = 100 * 101.4e9 / 252e9, not 100 * 75.4e9 / 252e9."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    cf.loc["Depreciation And Amortization"] = [5e9, 5e9, 5e9, 5e9]
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    q = sg.quality_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert round(q["owner_fcf_margin_pct"], 6) == round(100.0 * 101.4e9 / 252e9, 6)
```

Append to `tests/test_scout_grade_durability.py`:

```python
def test_durability_self_funding_uses_normalized(tmp_db, yf_statements, yf_series):
    """Stage-1.5: D's self-funding leg + the per-period cash-destruction flag are computed
    from the NORMALIZED per-period figure. A name that is conservative-negative but
    normalized-positive in a period is NOT flagged as destroying cash."""
    pack = yf_statements("msft_statements")
    cf = pack["cashflow"].copy()
    # Heavy growth CapEx makes conservative owner-FCF negative every period, but modest D&A
    # makes NORMALIZED owner-FCF positive every period.
    for c in list(cf.columns):
        cf.loc["Operating Cash Flow", c] = 20e9
        cf.loc["Capital Expenditure", c] = -30e9            # conservative: 20-30-sbc < 0
        cf.loc["Stock Based Compensation", c] = 1e9
        cf.loc["Depreciation And Amortization", c] = 4e9    # normalized: 20-4-1 = +15e9 > 0
    store.store_statements(tmp_db, "MSFT",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    d = sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert d["owner_fcf_positive"] is True                   # normalized TTM > 0
    assert d["owner_fcf_negative_all_periods"] is False      # normalized positive every period
```

### Step 2 - run, see it fail

```
uv run pytest tests/test_scout_grade_value.py::test_value_uses_normalized_owner_fcf tests/test_scout_grade_quality.py::test_quality_owner_fcf_margin_uses_normalized tests/test_scout_grade_durability.py::test_durability_self_funding_uses_normalized -v
```

**Expected:** all three FAIL (V/Q still read `store.owner_fcf_ttm` -> 75.4e9; D's flag still uses the conservative per-period construction and reports the name as cash-destructive).

### Step 3 - implement

In `agentcy/scout_grade.py`:

**(a) `value_metrics`** - replace the `store.owner_fcf_ttm` call and the `owner_fcf` extraction:

```python
def value_metrics(conn, yf_ticker: str, *, market_cap: float, total_debt: float,
                  cash: float, as_of: datetime) -> dict | None:
    """Pillar V raw metrics (design Pillar V + Stage-1.5 change 1): owner-FCF yield on EV and
    the P/owner-FCF display companion, both on the NORMALIZED owner-FCF figure. None when
    normalized owner-FCF is not computable at all; owner_fcf_yield None when EV <= 0 (RF5)."""
    oe = normalized_owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if oe is None:
        return None
    owner_fcf = oe.owner_fcf_ttm
    ev = market_cap + total_debt - cash
    return {
        "owner_fcf_ttm": owner_fcf,
        "owner_fcf_yield": (owner_fcf / ev) if ev > 0 else None,
        "p_owner_fcf": (market_cap / owner_fcf) if owner_fcf > 0 else None,
    }
```

**(b) `quality_metrics`** - swap only the owner-FCF margin source. Change the two lines:

```python
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
```
to
```python
    oe = normalized_owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
```
and the margin line
```python
        "owner_fcf_margin_pct": 100.0 * oe.value.owner_fcf_margin_ttm,
```
to
```python
        "owner_fcf_margin_pct": 100.0 * oe.owner_fcf_margin_ttm,
```
(the `if roic is None or not gm or oe is None` guard is unchanged; `NormalizedOwnerEarnings` has no `.value` wrapper, hence the `.value` removal.)

**(c) `_owner_fcf_negative_all_periods`** - recompute per-period on the normalized construction. Replace the body:

```python
def _owner_fcf_negative_all_periods(cf_pay: dict) -> bool:
    """Stage-1.5 change 1 + RF3 - NORMALIZED owner-FCF < 0 in EVERY available period
    (per-period cash-destruction, NOT the sign of the TTM sum). Per-period normalized owner-FCF
    = OCF - min(|CapEx|, D&A) - SBC, D&A absent -> |CapEx| (plan note 3). Periods missing a
    required pinned row are dropped; an empty result is not 'all negative' -> False."""
    vals = []
    for pe in sorted(cf_pay):
        cell = cf_pay[pe]
        ocf = cell.get("Operating Cash Flow")
        capex = cell.get("Capital Expenditure")
        if ocf is None or capex is None:
            continue
        capex_abs = abs(float(capex))
        da = cell.get("Depreciation And Amortization")
        maint = min(capex_abs, float(da)) if da is not None else capex_abs
        sbc = float(cell.get("Stock Based Compensation") or 0.0)
        vals.append(float(ocf) - maint - sbc)
    return bool(vals) and all(v < 0 for v in vals)
```

**(d) `durability_metrics`** - swap the self-funding source to normalized. Change:

```python
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
```
to
```python
    oe = normalized_owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
```
Then change the `sbc = oe.value.sbc_ttm` line - `NormalizedOwnerEarnings` has NO `sbc_ttm`. SBC/revenue is a Munger dilution-of-owners signal that should remain on the RAW SBC, so read SBC directly from the archive instead. Replace:

```python
    sbc = oe.value.sbc_ttm
```
with
```python
    # SBC/revenue stays on RAW SBC (owner-dilution signal, unrelated to CapEx normalization).
    sbc = 0.0
    for pe in sorted(cf, reverse=True)[:4]:
        sbc += float(cf[pe].get("Stock Based Compensation") or 0.0)
```
And change the self-funding line:
```python
        "owner_fcf_positive": oe.value.owner_fcf_ttm > 0,
```
to
```python
        "owner_fcf_positive": oe.owner_fcf_ttm > 0,
```
(The `if not inc or not bal or not cf or oe is None: return None` guard is unchanged.)

### Step 4 - run, see it pass

```
uv run pytest tests/test_scout_grade_value.py tests/test_scout_grade_quality.py tests/test_scout_grade_durability.py -v
uv run pytest -q
```

**Expected:** the three new tests pass. The EXISTING MSFT-fixture tests in these three files still pass UNCHANGED because for the fixture normalized == conservative (no D&A row -> fallback to |CapEx|, plan note 1). Full suite `863 passed, 3 skipped` (860 + 3 new). If any existing MSFT expected number moved, STOP - it means normalized diverged from conservative for the D&A-absent fixture, which is a bug in the fallback.

### Step 5 - commit

```
git add agentcy/scout_grade.py tests/test_scout_grade_value.py tests/test_scout_grade_quality.py tests/test_scout_grade_durability.py
git commit -m "$(cat <<'EOF'
feat(scout): rewire V/Q/D pillars to normalized owner earnings (Stage-1.5 change 2)

Value yield, Quality owner-FCF margin, Durability self-funding + per-period cash-destruction
input now consume the normalized figure. SBC/revenue stays on raw SBC. MSFT fixture
unchanged (normalized == conservative when D&A absent).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 3 - Sloan accrual fix (NI - Operating Cash Flow, capex-independent)

Change `management_metrics`' accrual metric from `NI - owner-FCF` to classic Sloan accruals `NI - Operating Cash Flow`, still TTM, still normalized by revenue, still lower-better.

### Files
- **Modify:** `agentcy/scout_grade.py` (`management_metrics`)
- **Modify:** `tests/test_scout_grade_management.py` (update the accrual expected value)

### Step 1 - update the failing assertion (TDD: change the assertion, watch it drive the code)

In `tests/test_scout_grade_management.py`, in `test_management_metrics_shrinking_shares`, replace the accrual assertion block:

```python
    # accrual/cash divergence = (net_income_ttm - owner_fcf_ttm), normalized by revenue TTM.
    #   NI_ttm = 25+24+23+22 = 94e9 ; owner_fcf = 75.4e9 ; revenue = 252e9 ; >0 = accruals
    assert round(m["accrual_divergence_pct"], 3) == round(100.0 * (94e9 - 75.4e9) / 252e9, 3)
```

with:

```python
    # Stage-1.5 change 3: Sloan accruals = (net_income_ttm - Operating Cash Flow TTM),
    # normalized by revenue TTM (capex-independent earnings quality).
    #   NI_ttm = 25+24+23+22 = 94e9 ; OCF_ttm = 36+34+32+30 = 132e9 ; revenue = 252e9
    #   accrual% = 100 * (94 - 132) / 252 = negative (cash exceeds reported profit = clean)
    assert round(m["accrual_divergence_pct"], 3) == round(100.0 * (94e9 - 132e9) / 252e9, 3)
```

### Step 2 - run, see it fail

```
uv run pytest tests/test_scout_grade_management.py::test_management_metrics_shrinking_shares -v
```

**Expected:** FAIL - the current code still computes `NI - owner_fcf` (94e9 - 75.4e9), so the assertion against `94e9 - 132e9` fails.

### Step 3 - implement

In `agentcy/scout_grade.py` `management_metrics`, the TTM loop currently sums `ni` and `rev`. Add an `ocf` sum from the cashflow archive and change the accrual formula. Replace this block:

```python
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if not inc or oe is None:
        return None
    periods = sorted(inc, reverse=True)[:4]                  # newest 4 quarters (TTM)
    ni = rev = 0.0
    for pe in periods:
        n = inc[pe].get("Net Income")
        r = inc[pe].get("Total Revenue")
        if n is None or r is None:
            return None                                      # a required pinned row missing
        ni += float(n)
        rev += float(r)
    if rev <= 0:
        return None
    owner_fcf = oe.value.owner_fcf_ttm
    accrual_div = 100.0 * (ni - owner_fcf) / rev
```

with:

```python
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    cf = _latest_payloads(conn, yf_ticker, "cashflow", as_of)
    if not inc or not cf:
        return None
    periods = sorted(inc, reverse=True)[:4]                  # newest 4 quarters (TTM)
    ni = rev = 0.0
    for pe in periods:
        n = inc[pe].get("Net Income")
        r = inc[pe].get("Total Revenue")
        if n is None or r is None:
            return None                                      # a required pinned row missing
        ni += float(n)
        rev += float(r)
    if rev <= 0:
        return None
    # Stage-1.5 change 3 - classic Sloan accruals: NI TTM - Operating Cash Flow TTM,
    # normalized by revenue (capex-independent; earnings quality must not depend on capital
    # intensity). Still lower-better; >0 = reported profit with no cash behind it.
    ocf = 0.0
    for pe in periods:
        o = cf.get(pe, {}).get("Operating Cash Flow")
        if o is None:
            return None
        ocf += float(o)
    accrual_div = 100.0 * (ni - ocf) / rev
```

Note: the per-share growth call below this block still needs `oe`. The next task (Task 4) MOVES per-share growth out of `management_metrics` entirely, so in THIS task keep the existing `_per_share_ofcf_growth` call working. Immediately after the `accrual_div = ...` line, RESTORE the `oe` binding that the growth call depends on, but from the normalized figure (per-share growth becomes normalized in Task 4; here keep it computable):

```python
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if oe is None:
        return None
```

(Place this right after `accrual_div = ...` and before the existing `sh = store.shares_yoy(...)` line. Task 4 removes the growth call and this restored binding.)

### Step 4 - run, see it pass

```
uv run pytest tests/test_scout_grade_management.py -v
uv run pytest -q
```

**Expected:** `test_management_metrics_shrinking_shares` passes with the new negative accrual; the other management tests still pass (they assert `accrual_divergence_pct is not None`, not a specific value). Full suite `863 passed, 3 skipped` (no new tests; count unchanged from Task 2). Note: `test_scout_grade_batch.py::test_same_sector_cohort_reaches_top_band_A` and other composite-sensitive tests may shift internally but must still pass their band assertions - if any FAIL here, STOP and inspect (the accrual sign flip changes the M percentile; the batch A-band test is engineered with a strict leader so it should still hold).

### Step 5 - commit

```
git add agentcy/scout_grade.py tests/test_scout_grade_management.py
git commit -m "$(cat <<'EOF'
fix(scout): Sloan accruals = NI - Operating Cash Flow (Stage-1.5 change 3)

Earnings quality is now capital-intensity-independent; the old NI - owner-FCF form flagged
capital-intensive compounders as accounting red flags. Still lower-better, still revenue-
normalized.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 4 - New Growth pillar (G): revenue growth + normalized per-share growth, ROIC-gated

Add `growth_metrics` (two raw legs) and `growth_leg_score` (ROIC-gated leg). Move per-share owner-FCF growth OUT of `management_metrics`/M into G, and switch it to the NORMALIZED per-share figure. G is not yet wired into the composite (Task 5 does that); this task builds and tests the raw metrics + leg scoring in isolation.

### Files
- **Create:** `tests/test_scout_grade_growth.py`
- **Modify:** `agentcy/scout_grade.py` (add `NEUTRAL_G`, `growth_metrics`, `_revenue_growth`, `_per_share_normalized_growth`, `growth_leg_score`; remove per-share growth from `management_metrics`)
- **Modify:** `tests/test_scout_grade_management.py` (drop the two per-share-growth assertions that no longer belong to M)

### Step 1 - write the failing tests

Create `tests/test_scout_grade_growth.py`:

```python
"""Stage-1.5 Growth pillar G (design change 3): annualized revenue growth + per-share
NORMALIZED owner-earnings growth, EACH leg ROIC-gated (leg * min(1, ROIC/15%)); thin data
degrades to neutral 50.0 (unknown != punished). Per-share growth moved here from M.
"""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
SHARE_INDEX = pd.to_datetime(["2025-06-20", "2025-12-20", "2026-06-20"])


def test_growth_leg_score_gates_on_roic():
    """A leg at/above 15% ROIC keeps its full percentile; below 15% it is discounted by
    min(1, ROIC/15). Mirrors roic_leg_score's floor factor."""
    pop = [10.0, 20.0, 30.0, 40.0]
    pct = sg.sector_percentile(30.0, pop, higher_better=True)
    assert sg.growth_leg_score(30.0, pop, roic_pct=20.0) == pct           # ROIC>=15 -> full
    assert sg.growth_leg_score(30.0, pop, roic_pct=7.5) == round(pct * 0.5, 6)  # 7.5/15
    assert sg.growth_leg_score(30.0, pop, roic_pct=0.0) == 0.0            # non-positive ROIC


def test_growth_metrics_revenue_and_per_share_present(tmp_db, yf_statements):
    """Revenue growth annualized over the archive window; per-share NORMALIZED owner-FCF
    growth over the share window; both labelled with the <3yr caveat."""
    store.store_statements(tmp_db, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT",
                       pd.Series([7.60e9, 7.50e9, 7.434e9], index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")
    g = sg.growth_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert g is not None
    # revenue rose oldest->newest (60 -> 66 e9) so annualized revenue growth is positive
    assert g["revenue_growth_pct"] is not None and g["revenue_growth_pct"] > 0
    assert "3yr CAGR not computable" in g["revenue_growth_label"]
    # per-share normalized owner-FCF growth present (shrinking shares -> positive)
    assert g["per_share_ofcf_growth_pct"] is not None and g["per_share_ofcf_growth_pct"] > 0
    assert "3yr CAGR not computable" in g["per_share_ofcf_growth_label"]


def test_growth_metrics_thin_returns_none_legs(tmp_db, yf_statements):
    """One income period + one share observation -> neither leg computable -> both None
    (the pillar-scoring layer degrades G to neutral 50; Task 5)."""
    store.store_statements(tmp_db, "MSFT",
                           {"income": yf_statements("msft_statements")["income"].iloc[:, :1]},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT",
                       pd.Series([7.5e9], index=pd.to_datetime(["2026-06-20"])),
                       fetched_at="2026-07-01T00:00:00Z")
    g = sg.growth_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert g is not None
    assert g["revenue_growth_pct"] is None
    assert g["per_share_ofcf_growth_pct"] is None


def test_management_no_longer_carries_per_share_growth(tmp_db, yf_statements):
    """Stage-1.5: per-share owner-FCF growth is MOVED to G; M no longer exposes it."""
    store.store_statements(tmp_db, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT",
                       pd.Series([7.60e9, 7.50e9, 7.434e9], index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")
    m = sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert m is not None
    assert "per_share_ofcf_growth_pct" not in m
    assert "shares_yoy_pct" in m and "accrual_divergence_pct" in m
```

In `tests/test_scout_grade_management.py`, DELETE the two per-share-growth assertions that no longer belong to M:

- In `test_management_metrics_shrinking_shares`, remove:
  ```python
    # per-share owner-FCF growth is present (>= 2 share observations)
    assert m["per_share_ofcf_growth_pct"] is not None
    # shrinking shares on a constant owner-FCF base => per-share growth is POSITIVE
    assert m["per_share_ofcf_growth_pct"] > 0
  ```
- Delete the whole test `test_management_per_share_growth_labelled_honestly` (that behavior is now covered by `test_growth_metrics_revenue_and_per_share_present` in the growth file; move nothing - the growth file asserts the label).
- In `test_management_metrics_rising_shares_flags_dilution`, remove:
  ```python
    # per-share owner-FCF growth on a rising share base (constant owner-FCF) is NEGATIVE
    assert m["per_share_ofcf_growth_pct"] < 0
  ```
- In `test_management_shares_leg_degrades_gracefully_without_baseline`, remove:
  ```python
    assert m["per_share_ofcf_growth_pct"] is not None
  ```

### Step 2 - run, see it fail

```
uv run pytest tests/test_scout_grade_growth.py -v
```

**Expected:** FAIL - `growth_metrics`, `growth_leg_score` do not exist, and `management_metrics` still returns `per_share_ofcf_growth_pct`.

### Step 3 - implement

In `agentcy/scout_grade.py`:

**(a)** Add the neutral constant near `QV_ROIC_MIN` (after the `QV_ROIC_MIN = 0.15` definition):

```python
NEUTRAL_G = 50.0        # Stage-1.5: G degrades to neutral 50 when growth data is too thin
```

**(b)** Add `growth_leg_score` right after `roic_leg_score`:

```python
def growth_leg_score(pct: float, cohort, *, roic_pct: float) -> float:
    """A Growth-pillar leg (Stage-1.5 change 3): the sector percentile of a growth metric
    DISCOUNTED by the absolute >15% ROIC floor (leg * min(1, ROIC/15%)), mirroring
    roic_leg_score. The ROIC gate rewards only PROFITABLE growth ('growth at any cost'
    scores ~0 - a lightweight Munger fad-guard). ``roic_pct`` is a percentage; the floor is
    QV_ROIC_MIN (0.15 == 15%)."""
    p = sector_percentile(pct, cohort, higher_better=True)
    floor_factor = max(0.0, min(1.0, roic_pct / (100.0 * QV_ROIC_MIN)))
    return round(p * floor_factor, 6)
```

**(c)** Add the two raw-leg helpers and `growth_metrics`. Place them right after `management_metrics` / `_per_share_ofcf_growth` (keep `_per_share_ofcf_growth` but repurpose via a normalized variant). Add:

```python
def _revenue_growth(conn, yf_ticker, as_of) -> tuple[float | None, str | None]:
    """Annualized revenue growth over the available archive window (oldest usable -> newest
    usable 'Total Revenue', annualized by the actual calendar span; plan note 4). None with
    < 2 usable periods or a non-positive base. Honest <3yr-window label."""
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    pts = []
    for pe in sorted(inc):
        rev = inc[pe].get("Total Revenue")
        if rev is not None and float(rev) > 0:
            pts.append((pe, float(rev)))
    if len(pts) < 2:
        return None, None
    (oldest_d, oldest_rev), (newest_d, newest_rev) = pts[0], pts[-1]
    years = max((pd.Timestamp(newest_d) - pd.Timestamp(oldest_d)).days / 365.25, 1e-9)
    growth = 100.0 * ((newest_rev / oldest_rev) ** (1.0 / years) - 1.0)
    label = (f"revenue growth, {oldest_d}->{newest_d} annualized "
             f"- 3yr CAGR not computable from archive")
    return growth, label


def _per_share_normalized_growth(conn, yf_ticker, as_of) -> tuple[float | None, str | None]:
    """Annualized per-share NORMALIZED owner-earnings growth over the deduped share window
    (Stage-1.5: normalized figure, moved here from M). None with < 2 share observations or a
    non-positive base. Honest <3yr-window label (RF11)."""
    oe = normalized_owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if oe is None:
        return None, None
    sh = store.shares_history(conn, yf_ticker, as_of=as_of)
    if not sh.usable():
        return None, None
    series = sh.value[sh.value.index <= pd.Timestamp(as_of.date())]
    if len(series) < 2:
        return None, None
    newest_ps = oe.owner_fcf_per_share_ttm
    oldest_shares = float(series.iloc[0])
    if oldest_shares <= 0 or newest_ps <= 0:
        return None, None
    base_ps = oe.owner_fcf_ttm / oldest_shares
    if base_ps <= 0:
        return None, None
    oldest_d = series.index[0].date().isoformat()
    newest_d = series.index[-1].date().isoformat()
    years = max((series.index[-1] - series.index[0]).days / 365.25, 1e-9)
    growth = 100.0 * ((newest_ps / base_ps) ** (1.0 / years) - 1.0)
    label = (f"per-share normalized owner-FCF growth, {oldest_d}->{newest_d} annualized "
             f"- 3yr CAGR not computable from archive")
    return growth, label


def growth_metrics(conn, yf_ticker: str, *, as_of: datetime) -> dict | None:
    """Pillar G raw metrics (design change 3): annualized revenue growth + per-share
    NORMALIZED owner-earnings growth, each with an honest <3yr-window label. Returns a dict
    with None legs when a leg is not computable (the scoring layer degrades G to neutral 50
    when BOTH are None). None only when the income archive is absent entirely."""
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    if not inc:
        return None
    rev_pct, rev_label = _revenue_growth(conn, yf_ticker, as_of)
    ps_pct, ps_label = _per_share_normalized_growth(conn, yf_ticker, as_of)
    return {
        "revenue_growth_pct": rev_pct,
        "revenue_growth_label": rev_label,
        "per_share_ofcf_growth_pct": ps_pct,
        "per_share_ofcf_growth_label": ps_label,
    }
```

**(d)** Remove per-share growth from `management_metrics`. Delete the `growth_pct, growth_label = _per_share_ofcf_growth(conn, yf_ticker, oe, as_of)` line and the two `per_share_ofcf_growth_*` keys from the returned dict, and delete the now-unused `oe` restoration you added in Task 3 (the `oe = store.owner_fcf_ttm(...)` block). The returned dict becomes:

```python
    sh = store.shares_yoy(conn, yf_ticker, as_of=as_of)      # Stamped[float | None]
    shares_yoy_pct = sh.value if sh.usable() and sh.value is not None else None

    return {
        "shares_yoy_pct": shares_yoy_pct,
        "accrual_divergence_pct": accrual_div,
    }
```

Also delete the old `_per_share_ofcf_growth` function ENTIRELY if nothing else references it (grep first: `uv run python -c "import agentcy.scout_grade"` then `grep -rn _per_share_ofcf_growth agentcy tests`). If only the old management test referenced it, it is safe to delete; `_per_share_normalized_growth` replaces it.

Update the `management_metrics` docstring to drop the per-share growth bullet (M now carries dilution + Sloan accrual only).

### Step 4 - run, see it pass

```
uv run pytest tests/test_scout_grade_growth.py tests/test_scout_grade_management.py -v
uv run pytest -q
```

**Expected:** growth tests pass; management tests pass (with per-share assertions removed). Full suite: `863 - 1 (deleted management test) + 4 (new growth tests) = 866 passed, 3 skipped`.

### Step 5 - commit

```
git add agentcy/scout_grade.py tests/test_scout_grade_growth.py tests/test_scout_grade_management.py
git commit -m "$(cat <<'EOF'
feat(scout): Growth pillar G raw legs + ROIC-gated leg scoring (Stage-1.5 change 3)

Annualized revenue growth + per-share normalized owner-earnings growth (moved from M), each
gated by min(1, ROIC/15%). Thin data -> both legs None (scoring degrades G to neutral 50).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 5 - Composite re-weight + G integration (V25 Q25 G20 D15 M15)

Re-weight the composite, add `g` to `GradedName`, and wire G scoring into `grade_universe` phase 2. Update the composite-formula tests and regenerate the render goldens.

### Files
- **Modify:** `agentcy/scout_grade.py` (`W_*` constants, `composite`, `GradedName`, `grade_universe`, `_raw_bundle`)
- **Modify:** `tests/test_scout_grade_composite.py` (new weights)
- **Modify:** `tests/test_render_scout.py` (GradedName gains a `g` positional field; header/body gain a G column)
- **Regenerate:** `tests/golden/scout_graded.md.txt`, `tests/golden/scout_graded.html.txt`

### Step 1 - update composite tests (drive the weights)

In `tests/test_scout_grade_composite.py`, replace the module docstring line `0.30V+0.30Q+0.20D+0.20M` with `0.25V+0.25Q+0.20G+0.15D+0.15M`, and replace `test_composite_weights`:

```python
def test_composite_weights():
    # Stage-1.5 weights: 0.25 V + 0.25 Q + 0.20 G + 0.15 D + 0.15 M
    c = sg.composite(v=80.0, q=80.0, g=80.0, d=80.0, m=80.0, penalty=0)
    assert c == 80.0
    # all-weight sanity: V+Q only (100 each), rest 0 -> 0.25*100 + 0.25*100 = 50
    c2 = sg.composite(v=100.0, q=100.0, g=0.0, d=0.0, m=0.0, penalty=0)
    assert c2 == 50.0
    # G alone at 100, rest 0 -> 0.20*100 = 20
    c3 = sg.composite(v=0.0, q=0.0, g=100.0, d=0.0, m=0.0, penalty=0)
    assert c3 == 20.0
```

And update `test_penalty_subtracts_and_floors_at_zero` to pass `g=`:

```python
def test_penalty_subtracts_and_floors_at_zero():
    assert sg.composite(v=50.0, q=50.0, g=50.0, d=50.0, m=50.0, penalty=-15) == 35.0
    assert sg.composite(v=5.0, q=5.0, g=5.0, d=5.0, m=5.0, penalty=-15) == 0.0  # floored
```

### Step 2 - update the render test constructors (GradedName gains `g`)

In `tests/test_render_scout.py`, every `sg.GradedName(...)` call gains a `g` value. The chosen field order (Step 3) appends `g` AFTER `m` and BEFORE `composite` is NOT used; instead `g` is inserted between `d` and `m` so column order V/Q/G/D/M reads naturally. Update the six constructors in `_ctx()` and the two in the dilution test to insert a G value between the D and M positions. New `_ctx()`:

```python
def _ctx():
    graded = (
        sg.GradedName("VEEV", "Technology", "Core", 58.0, 92.0, 70.0, 84.0, 80.0, 78.0, "B", ""),
        sg.GradedName("MSFT", "Technology", "Core", 40.0, 88.0, 60.0, 90.0, 71.0, 71.0, "B", ""),
        sg.GradedName("DIST", "Industrials", "Outside", 90.0, 74.0, 65.0, 82.0, 83.0, 83.0, "A", ""),
        sg.GradedName("SWX", "Technology", "Adjacent", 55.0, 60.0, 55.0, 65.0, 60.0, 60.0, "C", ""),
        sg.GradedName("LEVR", "Technology", "Adjacent", None, None, None, None, None, None,
                      "VETOED", "leverage veto: net debt/EBITDA above the §2 floor"),
        sg.GradedName("THIN", "Technology", "Outside", None, None, None, None, None, None,
                      "INSUFFICIENT", "insufficient data: <2 usable periods"),
    )
    return ScoutGradedContext(as_of_label="Fri 10 Jul 2026", graded=graded,
                              evidence_note=sg.HONEST_EVIDENCE_NOTE)
```

The `GradedName` field order is: `symbol, sector, tier, v, q, g, d, m, composite, grade, note`. So each gradable row is `(sym, sector, tier, V, Q, G, D, M, composite, grade, note)` and each suppressed row is `(sym, sector, tier, None, None, None, None, None, None, grade, note)` (six Nones: v,q,g,d,m,composite).

In `test_dilution_penalty_note_is_flagged_on_a_graded_row`, update the two `GradedName` constructions similarly (insert a G value between D and M, e.g. `65.0`):

```python
        sg.GradedName("DILUT", "Technology", "Core", 60.0, 55.0, 65.0, 70.0, 30.0, 62.0,
                      "C", "dilution penalty: shares +14.0%/yr"),
```
```python
        graded=(sg.GradedName("CLEAN", "Technology", "Core", 60.0, 55.0, 65.0, 70.0, 55.0, 62.0, "C", ""),),
```

### Step 3 - run, see it fail

```
uv run pytest tests/test_scout_grade_composite.py tests/test_render_scout.py -v
```

**Expected:** FAIL - `composite()` has no `g` param (TypeError), `GradedName` has no `g` field (positional-arg mismatch), and the render header has no G column.

### Step 4 - implement

In `agentcy/scout_grade.py`:

**(a)** Weights:

```python
W_V, W_Q, W_G, W_D, W_M = 0.25, 0.25, 0.20, 0.15, 0.15
```

**(b)** `composite`:

```python
def composite(*, v: float, q: float, g: float, d: float, m: float, penalty: int) -> float:
    """Stage-1.5 composite (design change 3), penalty applied, floored at 0 and capped at 100."""
    raw = W_V * v + W_Q * q + W_G * g + W_D * d + W_M * m + penalty
    return max(0.0, min(100.0, round(raw, 4)))
```

**(c)** `GradedName` - insert `g` between `d`... actually between `q` and `d` per column order V/Q/G/D/M. Final dataclass:

```python
@dataclass(frozen=True)
class GradedName:
    """One Stage-1 graded row (design §4). grade in {A,B,C,D,F,VETOED,INSUFFICIENT}.
    Field order matches the V/Q/G/D/M column order (Stage-1.5: g added)."""
    symbol: str
    sector: str | None
    tier: str
    v: float | None
    q: float | None
    g: float | None
    d: float | None
    m: float | None
    composite: float | None
    grade: str
    note: str
```

**(d)** `_raw_bundle` - add growth to the bundle:

```python
def _raw_bundle(conn, symbol, md, as_of):
    """All pillars' raw metric dicts for one ticker; None -> insufficient (a pillar is not
    computable at all: thin/stale archive or missing pinned rows). G returns a dict with
    None legs when thin (never suspends the name - it degrades to neutral 50 at scoring)."""
    val = value_metrics(conn, symbol, market_cap=md["market_cap"],
                        total_debt=md["total_debt"], cash=md["cash"], as_of=as_of)
    qual = quality_metrics(conn, symbol, as_of=as_of)
    dur = durability_metrics(conn, symbol, as_of=as_of)
    mgmt = management_metrics(conn, symbol, as_of=as_of)
    grow = growth_metrics(conn, symbol, as_of=as_of)
    if None in (val, qual, dur, mgmt, grow):
        return None
    return {"v": val, "q": qual, "g": grow, "d": dur, "m": mgmt}
```

**(e)** `grade_universe` - two changes. First, in phase 1, pass the veto carve-out inputs (this task wires them as `None`/current values; Task 6 implements the sparing). To keep Task 5 self-contained, pass the real values now so Task 6 only edits `veto_check`:

Replace the veto call:

```python
        veto = veto_check(
            net_debt_to_ebitda=d["net_debt_to_ebitda"],
            ebitda=d["ebitda"],
            net_debt=d["net_debt"],
            owner_fcf_positive_any=not d["owner_fcf_negative_all_periods"],
            shares_yoy_pct=bundle["m"]["shares_yoy_pct"],
            roic_pct=bundle["q"]["roic_pct"],
            revenue_growth_pct=bundle["g"]["revenue_growth_pct"])
```

(Task 6 adds `roic_pct`/`revenue_growth_pct` params to `veto_check`; until then this call raises TypeError. To keep Task 5 green, add the two params to `veto_check` as accepted-but-unused keyword-only args in THIS task - see the note below - then Task 6 implements the sparing logic. This keeps the suite green each task.)

In `veto_check`, add the two keyword-only params now (unused this task):

```python
def veto_check(*, net_debt_to_ebitda, ebitda, net_debt, owner_fcf_positive_any,
               shares_yoy_pct, roic_pct=None, revenue_growth_pct=None) -> Veto:
```

(Do not change the body yet; the existing veto tests pass without supplying the new params because they default to None. Task 6 adds the sparing branch + tests.)

Second, phase 2 - score G and pass it into `composite` and `GradedName`. Replace the phase-2 body (the `for sym, entry in raw.items():` loop) so it computes `g`:

```python
    for sym, entry in raw.items():
        b = entry["bundle"]
        v = pillar_score([sector_percentile(
            b["v"]["owner_fcf_yield"], cohort(sym, ("v", "owner_fcf_yield")), higher_better=True)])
        gm_level = sector_percentile(b["q"]["gross_margin_level_pct"],
                                     cohort(sym, ("q", "gross_margin_level_pct")), higher_better=True)
        gm_stability = sector_percentile(b["q"]["gross_margin_cv"],
                                         cohort(sym, ("q", "gross_margin_cv")), higher_better=False)
        gm_leg = gm_level * (gm_stability / 100.0)
        q = pillar_score([
            roic_leg_score(b["q"]["roic_pct"], cohort(sym, ("q", "roic_pct"))),
            gm_leg,
            sector_percentile(b["q"]["owner_fcf_margin_pct"],
                              cohort(sym, ("q", "owner_fcf_margin_pct")), higher_better=True),
        ])
        # Growth pillar G (Stage-1.5): each present leg is ROIC-gated; both absent -> neutral 50.
        roic_pct = b["q"]["roic_pct"]
        g_legs = []
        if b["g"]["revenue_growth_pct"] is not None:
            g_legs.append(growth_leg_score(
                b["g"]["revenue_growth_pct"],
                [c for c in cohort(sym, ("g", "revenue_growth_pct")) if c is not None],
                roic_pct=roic_pct))
        if b["g"]["per_share_ofcf_growth_pct"] is not None:
            g_legs.append(growth_leg_score(
                b["g"]["per_share_ofcf_growth_pct"],
                [c for c in cohort(sym, ("g", "per_share_ofcf_growth_pct")) if c is not None],
                roic_pct=roic_pct))
        g = pillar_score(g_legs)
        if g is None:
            g = NEUTRAL_G                                   # thin growth data -> neutral, not punished
        d = pillar_score([
            sector_percentile(b["d"]["net_debt_to_ebitda"],
                              cohort(sym, ("d", "net_debt_to_ebitda")), higher_better=False),
            100.0 if b["d"]["owner_fcf_positive"] else 0.0,
            sector_percentile(b["d"]["sbc_to_revenue_pct"],
                              cohort(sym, ("d", "sbc_to_revenue_pct")), higher_better=False),
        ])
        m_legs = [sector_percentile(b["m"]["accrual_divergence_pct"],
                                    cohort(sym, ("m", "accrual_divergence_pct")), higher_better=False)]
        if b["m"]["shares_yoy_pct"] is not None:
            m_legs.append(sector_percentile(b["m"]["shares_yoy_pct"],
                                            cohort(sym, ("m", "shares_yoy_pct")), higher_better=False))
        m = pillar_score(m_legs)
        comp = composite(v=v, q=q, g=g, d=d, m=m, penalty=entry["penalty"])
        results[sym] = GradedName(sym, meta[sym]["sector"], meta[sym]["tier"],
                                  round(v, 1), round(q, 1), round(g, 1), round(d, 1), round(m, 1),
                                  comp, grade_letter(comp), entry["reason"])
```

Note: the per-share growth leg cohort could contain `None` for peers whose growth is not computable; `sector_percentile` already drops `None`/NaN, so the explicit `[c for c in ... if c is not None]` filter is belt-and-suspenders and keeps the cohort clean. The `growth_leg_score` for a singleton/empty cohort returns `50.0 * floor_factor` (neutral percentile, gated) - acceptable.

Also update the two INSUFFICIENT/VETOED `GradedName(...)` constructions in phase 1 to add the extra `None` for `g` (they currently pass 5 metric slots `v,q,d,m,composite` = but now there are 6: `v,q,g,d,m,composite`). Both currently read:

```python
            results[sym] = GradedName(sym, sector, tier, None, None, None, None, None,
                                      "INSUFFICIENT", ...)
```

Count the Nones: they must be SIX (v,q,g,d,m,composite). The current code has FIVE. Change both the INSUFFICIENT construction(s) and the VETOED construction to SIX Nones:

```python
            results[sym] = GradedName(sym, sector, tier, None, None, None, None, None, None,
                                      "INSUFFICIENT", _insufficient)
```
```python
            results[sym] = GradedName(sym, sector, tier, None, None, None, None, None, None,
                                      f"{_insufficient}: {gap}")  # NOTE: keep the existing grade arg order
```
Be careful: the existing signature is `GradedName(symbol, sector, tier, v, q, g, d, m, composite, grade, note)`. So an INSUFFICIENT row is `GradedName(sym, sector, tier, None, None, None, None, None, None, "INSUFFICIENT", note)` - three positional strings, six Nones, then grade, then note. Verify each of the three suppressed constructions (the `bundle is None` one, the `gap is not None` one, and the `veto.vetoed` one) has exactly six Nones.

In `agentcy/render/scout.py`:

**(f)** Header gains a G column:

```python
_HEADER = ("Ticker", "Grade", "Comp", "V", "Q", "G", "D", "M")
```

**(g)** `_body_rows` emits `g.g`:

```python
def _body_rows(ranked):
    """The table body for one tier - one row list, shared by both skins (RF9)."""
    return [(g.symbol, g.grade, f"{g.composite:.0f}",
             _fmt_pillar(g.v), _fmt_pillar(g.q), _fmt_pillar(g.g),
             _fmt_pillar(g.d), _fmt_pillar(g.m))
            for g in ranked]
```

### Step 5 - regenerate goldens, run, see it pass

```
UPDATE_GOLDEN=1 uv run pytest tests/test_render_scout.py -q
uv run pytest tests/test_scout_grade_composite.py tests/test_render_scout.py -v
uv run pytest -q
```

After regenerating, OPEN `tests/golden/scout_graded.md.txt` and confirm the header row now reads `Ticker  Grade  Comp  V     Q     G     D     M` and each data row has the G value in the third-metric column (e.g. VEEV row shows `70.0` for G). Confirm the HTML golden matches. Then re-run without `UPDATE_GOLDEN` to prove the goldens are pinned.

**Expected:** composite + render tests pass; goldens regenerated and pinned. Full suite: the composite/batch/graded_run tests that grade real fixtures now include a G pillar - they must still pass their band/relative assertions. Full-suite count stays `866 passed, 3 skipped` (no net new tests this task; the render test's golden changed but the test count is the same). If `test_scout_grade_batch.py::test_same_sector_cohort_reaches_top_band_A` FAILS (the added G pillar shifts the leader's composite), inspect: the leader is engineered strictly-best on every leg incl. growth (shrinking shares -> highest per-share growth; revenue flat across peers so revenue-growth leg is neutral/tied), so it should still reach A. If it lands just below 80, that is a legitimate consequence of re-weighting - read the actual composite, verify by hand it is the true cohort max, and if the design intends A-reachability, the test's synthetic leader may need a stronger growth edge; adjust the leader's `shares` series (e.g. `[1.20e9, 1.10e9, 1.00e9]`) to widen the per-share-growth gap and re-pin. Document the change inline.

### Step 6 - commit

```
git add agentcy/scout_grade.py agentcy/render/scout.py tests/test_scout_grade_composite.py tests/test_render_scout.py tests/golden/scout_graded.md.txt tests/golden/scout_graded.html.txt
git commit -m "$(cat <<'EOF'
feat(scout): re-weight composite V25 Q25 G20 D15 M15 + integrate Growth pillar (Stage-1.5)

GradedName gains a g field; grade_universe scores G (ROIC-gated legs, neutral-50 degrade)
and composes it. Render adds a G column; goldens regenerated.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 6 - Cash-destruction veto carve-out for genuine reinvestors

Spare the cash-destruction veto (not the leverage veto) when `ROIC > 15% AND revenue growth > 10%/yr`, returning a flagged non-veto with a printed note.

### Files
- **Modify:** `agentcy/scout_grade.py` (`veto_check` body)
- **Modify:** `tests/test_scout_grade_veto.py` (add carve-out tests)
- **Modify:** `tests/test_scout_grade_batch.py` (add an integration carve-out test)

### Step 1 - write the failing tests

Append to `tests/test_scout_grade_veto.py`:

```python
def test_cash_destruction_spared_for_high_roic_fast_grower():
    """Stage-1.5 change 4: owner-FCF negative every period is SPARED (flagged non-veto) when
    ROIC>15% AND revenue growth>10%/yr - the young high-return compounder investing ahead of
    profits. Leverage is unaffected (this name is un-levered)."""
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=False, shares_yoy_pct=0.0,
                      roic_pct=25.0, revenue_growth_pct=30.0)
    assert not v.vetoed
    assert v.penalty == 0
    assert "reinvest" in v.reason.lower() or "flag" in v.reason.lower()


def test_cash_destruction_still_vetoes_low_roic_burner():
    """A low-ROIC cash-burner is still VETOED (the ROIC>15 gate keeps the carve-out from
    being a hype loophole)."""
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=False, shares_yoy_pct=0.0,
                      roic_pct=8.0, revenue_growth_pct=40.0)
    assert v.vetoed and "cash" in v.reason.lower()


def test_cash_destruction_still_vetoes_slow_grower_even_if_high_roic():
    """High ROIC but slow growth (<=10%/yr) is NOT the invest-ahead-of-profits case -> still
    vetoed."""
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=False, shares_yoy_pct=0.0,
                      roic_pct=25.0, revenue_growth_pct=5.0)
    assert v.vetoed and "cash" in v.reason.lower()


def test_cash_destruction_none_growth_or_roic_still_vetoes():
    """Missing ROIC or growth data can never SPARE (no evidence of profitable growth)."""
    assert sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                         owner_fcf_positive_any=False, shares_yoy_pct=0.0,
                         roic_pct=None, revenue_growth_pct=30.0).vetoed
    assert sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                         owner_fcf_positive_any=False, shares_yoy_pct=0.0,
                         roic_pct=25.0, revenue_growth_pct=None).vetoed


def test_leverage_still_beats_cash_destruction_carveout():
    """Leverage is always disqualifying - a levered high-ROIC fast-grower is STILL vetoed for
    leverage (the carve-out only touches the cash-destruction branch)."""
    v = sg.veto_check(net_debt_to_ebitda=6.8, ebitda=1.0, net_debt=6.8,
                      owner_fcf_positive_any=False, shares_yoy_pct=0.0,
                      roic_pct=25.0, revenue_growth_pct=30.0)
    assert v.vetoed and "leverage" in v.reason.lower()
```

Append to `tests/test_scout_grade_batch.py` (integration through `grade_universe`):

```python
def test_high_roic_fast_grower_is_flagged_not_vetoed_in_batch(tmp_db, yf_statements, yf_series):
    """Stage-1.5 change 4 integration: a name that destroys owner-FCF every period but has
    ROIC>15% and revenue growth>10%/yr is GRADED (flagged), not VETOED. A low-ROIC burner in
    the same batch is still VETOED."""
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)   # a normal peer for the cohort
    pack = yf_statements("msft_statements")

    # GROW: growth CapEx makes owner-FCF negative every period, but ROIC is high (small IC
    # denominator) and revenue is strongly rising -> spared.
    inc = pack["income"].copy()
    cols = list(inc.columns)                                # newest first
    inc.loc["Total Revenue"] = [80e9, 60e9, 45e9, 34e9]     # steep annualized growth
    inc.loc["EBIT"] = [40e9, 30e9, 22e9, 17e9]              # high EBIT vs small IC -> ROIC>15
    cf = pack["cashflow"].copy()
    for c in cols:
        cf.loc["Operating Cash Flow", c] = 5e9
        cf.loc["Capital Expenditure", c] = -25e9            # owner-FCF = 5-25-sbc < 0 every period
        cf.loc["Stock Based Compensation", c] = 1e9
    store.store_statements(tmp_db, "GROW",
                           {"income": inc, "balance": pack["balance"], "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "GROW", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")

    # BURN: same cash destruction but flat revenue + low ROIC -> still vetoed.
    inc2 = pack["income"].copy()
    inc2.loc["EBIT"] = [1e9, 1e9, 1e9, 1e9]                 # tiny EBIT -> ROIC well below 15
    cf2 = pack["cashflow"].copy()
    for c in cols:
        cf2.loc["Operating Cash Flow", c] = 1e9
        cf2.loc["Capital Expenditure", c] = -10e9
        cf2.loc["Stock Based Compensation", c] = 3e9
    store.store_statements(tmp_db, "BURN",
                           {"income": inc2, "balance": pack["balance"], "cashflow": cf2},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "BURN", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")

    universe = pd.DataFrame({
        "symbol": ["MSFT", "GROW", "BURN"],
        "sector": ["Technology", "Technology", "Technology"],
        "industry": ["Software", "Software", "Software"],
        "market_cap": ["large_cap", "large_cap", "large_cap"],
    })
    market = {
        "MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
        "GROW": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
        "BURN": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
    }
    graded = sg.grade_universe(tmp_db, universe, market_data=market, as_of=AS_OF)
    by_sym = {g.symbol: g for g in graded}
    assert by_sym["GROW"].grade != "VETOED"                 # spared -> graded
    assert by_sym["GROW"].composite is not None
    assert by_sym["BURN"].grade == "VETOED"                 # low-ROIC burner still vetoed
```

Before relying on the exact numbers, the implementer MUST verify GROW's ROIC>15 and revenue growth>10 by running the test and reading the intermediate metrics if it does not spare on the first run (see Step 4 note). Adjust `EBIT`/`Total Revenue`/balance rows until GROW genuinely clears both gates, then pin.

### Step 2 - run, see it fail

```
uv run pytest tests/test_scout_grade_veto.py tests/test_scout_grade_batch.py::test_high_roic_fast_grower_is_flagged_not_vetoed_in_batch -v
```

**Expected:** the carve-out unit tests FAIL (`veto_check` still vetoes on `owner_fcf_positive_any=False` regardless of ROIC/growth); the batch test FAILS (GROW is VETOED).

### Step 3 - implement

In `agentcy/scout_grade.py` `veto_check`, replace the cash-destruction branch:

```python
    # Cash-destruction veto (§2, RF3): owner-FCF negative across ALL available periods.
    if not owner_fcf_positive_any:
        return Veto(True, 0, "cash-destruction veto: owner-FCF negative every period")
```

with:

```python
    # Cash-destruction veto (§2, RF3): owner-FCF negative across ALL available periods.
    if not owner_fcf_positive_any:
        # Stage-1.5 change 4 carve-out: spare the GENUINE reinvestor - ROIC>15% AND revenue
        # growth>10%/yr (investing ahead of profits). The ROIC>15 gate keeps this from being a
        # hype loophole; a low-ROIC cash-burner is still vetoed. Leverage (above) is unaffected.
        if (roic_pct is not None and roic_pct > 100.0 * QV_ROIC_MIN
                and revenue_growth_pct is not None and revenue_growth_pct > 10.0):
            return Veto(False, 0,
                        f"flagged - normalized owner-FCF negative every period, spared as a "
                        f"reinvestor (ROIC {roic_pct:.0f}% > 15%, revenue growth "
                        f"{revenue_growth_pct:.0f}%/yr > 10%) - a caution, not a suppression")
        return Veto(True, 0, "cash-destruction veto: owner-FCF negative every period")
```

Note `100.0 * QV_ROIC_MIN == 15.0`. The reason string contains no `!`, no benchmark token, no imperative - it is lint-clean when it flows to render via `g.note`.

### Step 4 - run, see it pass

```
uv run pytest tests/test_scout_grade_veto.py -v
uv run pytest tests/test_scout_grade_batch.py::test_high_roic_fast_grower_is_flagged_not_vetoed_in_batch -v
uv run pytest -q
```

If the batch test's GROW is not spared, add a temporary debug print in the test (`print(sg.quality_metrics(tmp_db, "GROW", as_of=AS_OF))` and `print(sg.growth_metrics(tmp_db, "GROW", as_of=AS_OF))`) via `-s`, read the actual `roic_pct` and `revenue_growth_pct`, confirm which gate GROW misses, adjust the seeded `EBIT`/`Total Revenue`/`Working Capital`/`Total Assets`/`Current Assets`/`Cash` rows so ROIC genuinely exceeds 15% and revenue growth exceeds 10%/yr, remove the debug print, and re-run. Verify by hand that the pinned figures reflect a real high-ROIC fast-grower.

**Expected:** all veto tests + the batch carve-out test pass. Full suite: `866 + 5 (veto) + 1 (batch) = 872 passed, 3 skipped`.

### Step 5 - commit

```
git add agentcy/scout_grade.py tests/test_scout_grade_veto.py tests/test_scout_grade_batch.py
git commit -m "$(cat <<'EOF'
feat(scout): cash-destruction veto carve-out for genuine reinvestors (Stage-1.5 change 4)

owner-FCF negative every period is spared (flagged, graded) only when ROIC>15% AND revenue
growth>10%/yr; low-ROIC burners still vetoed; leverage veto unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 7 - Honest grade-vs-thesis framing line

Add one line to the Scout render stating the grade is quantitative evidence, not a thesis verdict (Stage-2 judgments pending). Keep lint clean; regenerate goldens.

### Files
- **Modify:** `agentcy/render/scout.py` (`_segments` - add the framing line; if any token trips lint, ride it in `owner_spans`)
- **Modify:** `tests/test_render_scout.py` (assert the framing line present)
- **Regenerate:** `tests/golden/scout_graded.md.txt`, `tests/golden/scout_graded.html.txt`

### Step 1 - write the failing assertion

In `tests/test_render_scout.py`, in `test_render_tiered_grade_sorted`, add before the two `golden(...)` lines:

```python
    # Stage-1.5 change 5: honest grade-vs-thesis framing (grade is evidence, not a verdict).
    assert "quantitative evidence" in md.lower()
    assert "stage-2" in md.lower() or "stage 2" in md.lower()
```

### Step 2 - run, see it fail

```
uv run pytest tests/test_render_scout.py::test_render_tiered_grade_sorted -v
```

**Expected:** FAIL - the framing line is not yet rendered (and, because the assertion runs before the golden call, the golden is not touched).

### Step 3 - implement

In `agentcy/render/scout.py`, add a module-level constant near the top (after `_HEADER`):

```python
_GRADE_FRAMING = (
    "This grade is quantitative evidence, not a thesis verdict: moat durability, management "
    "candor, and fad-risk are Stage-2 judgments still pending. A computed A is a strong "
    "lead to investigate, never a decision."
)
```

In `_segments`, emit it as its own text segment immediately BEFORE the evidence note (so it reads with the closing context). Replace:

```python
    segs.append(("text", ""))
    segs.append(("text", ctx.evidence_note))
    return segs
```

with:

```python
    segs.append(("text", ""))
    segs.append(("text", _GRADE_FRAMING))
    segs.append(("text", ""))
    segs.append(("text", ctx.evidence_note))
    return segs
```

Lint check: `_GRADE_FRAMING` contains no `!`, no `S&P|vs index|outperform|underperform|benchmark`, no `€\d`, no `buy now|sell now|you must`, no red glyphs. It is lint-safe as template text and needs NO `owner_spans` entry. (If a future word change trips `_BENCH`, add `_GRADE_FRAMING` to the `owner_spans` tuple in `render_scout_graded` alongside `ctx.evidence_note`.) The `test_render_tiered_grade_sorted` test already asserts `lint(r) == []`, which is the guard.

### Step 4 - regenerate goldens, run, see it pass

```
UPDATE_GOLDEN=1 uv run pytest tests/test_render_scout.py -q
uv run pytest tests/test_render_scout.py -v
uv run pytest -q
```

Open `tests/golden/scout_graded.md.txt` and confirm the framing line appears just above the honest evidence note, and that `lint` still passes (the render test asserts it). Re-run without `UPDATE_GOLDEN` to pin.

**Expected:** render tests pass; goldens updated. Full suite `872 passed, 3 skipped` (no net new tests; assertions added to an existing test).

### Step 5 - commit

```
git add agentcy/render/scout.py tests/test_render_scout.py tests/golden/scout_graded.md.txt tests/golden/scout_graded.html.txt
git commit -m "$(cat <<'EOF'
feat(scout): honest grade-vs-thesis framing line in the graded render (Stage-1.5 change 5)

The grade is quantitative evidence, not a thesis verdict; Stage-2 judgments pending. Lint-
clean; goldens regenerated.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 8 - Compounder-vs-cash-cow regression (the whole point)

One integration test seeding a heavy reinvestor (high CapEx, high ROIC, growing) and a mature cash cow in the SAME sector, asserting the reinvestor is NOT vetoed and its composite is now competitive with (>=) the cash cow's - proving Stage-1.5 fixed the structural bias.

### Files
- **Create:** `tests/test_scout_grade_compounder_regression.py`

### Step 1 - write the failing/regression test

Create `tests/test_scout_grade_compounder_regression.py`:

```python
"""Stage-1.5 regression (design 'Cost & testing'): a reinvesting compounder is no longer
dominated OR vetoed by a mature cash cow in the same sector. The compounder has high CapEx
(so its CONSERVATIVE owner-FCF is thin/negative) but modest D&A, high ROIC, and strong
revenue + per-share growth; the cash cow has low CapEx, flat revenue, lower ROIC.

Under the OLD grader the compounder would be suppressed (cash-destruction veto) or ranked
below the cow (owner-earnings penalized by growth CapEx). Under Stage-1.5 it grades, is
spared any cash-destruction veto, and its composite is competitive.
"""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
COLS = pd.to_datetime(["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])
SHARE_INDEX = pd.to_datetime(["2025-06-20", "2025-12-20", "2026-06-20"])


def _seed(conn, sym, *, revenue, ebit, ocf, capex, da, sbc, debt, cash, shares):
    inc = pd.DataFrame(index=["Total Revenue", "Cost Of Revenue", "Gross Profit",
                              "Operating Income", "EBITDA", "EBIT", "Net Income"],
                       columns=COLS, dtype=float)
    bal = pd.DataFrame(index=["Total Debt", "Cash And Cash Equivalents", "Total Assets",
                              "Current Assets", "Working Capital"], columns=COLS, dtype=float)
    cf = pd.DataFrame(index=["Operating Cash Flow", "Capital Expenditure",
                             "Stock Based Compensation", "Depreciation And Amortization"],
                      columns=COLS, dtype=float)
    for i, c in enumerate(COLS):                            # i=0 newest ... i=3 oldest
        rev = revenue[i]
        inc.loc["Total Revenue", c] = rev
        inc.loc["Gross Profit", c] = rev * 0.70
        inc.loc["Cost Of Revenue", c] = rev * 0.30
        inc.loc["Operating Income", c] = ebit[i]
        inc.loc["EBIT", c] = ebit[i]
        inc.loc["EBITDA", c] = ebit[i] * 1.2
        inc.loc["Net Income", c] = ebit[i] * 0.75
        bal.loc["Total Debt", c] = debt
        bal.loc["Cash And Cash Equivalents", c] = cash
        bal.loc["Total Assets", c] = rev * 2.5
        bal.loc["Current Assets", c] = rev * 1.5
        bal.loc["Working Capital", c] = rev * 0.15
        cf.loc["Operating Cash Flow", c] = ocf[i]
        cf.loc["Capital Expenditure", c] = -capex[i]
        cf.loc["Stock Based Compensation", c] = sbc
        cf.loc["Depreciation And Amortization", c] = da
    store.store_statements(conn, sym, {"income": inc, "balance": bal, "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, sym, pd.Series(shares, index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")


def test_reinvesting_compounder_not_dominated_or_vetoed_by_cash_cow(tmp_db):
    # COMPOUNDER: strong revenue growth, high ROIC, HIGH CapEx (conservative owner-FCF thin),
    # modest D&A (normalized owner-FCF healthy), shrinking shares (per-share growth positive).
    _seed(tmp_db, "COMP",
          revenue=[80e9, 62e9, 48e9, 38e9], ebit=[36e9, 28e9, 22e9, 17e9],
          ocf=[34e9, 27e9, 21e9, 16e9], capex=[30e9, 24e9, 19e9, 15e9],   # near-OCF CapEx
          da=[6e9, 6e9, 6e9, 6e9], sbc=1e9, debt=10e9, cash=40e9,
          shares=[1.10e9, 1.05e9, 1.00e9])
    # CASH COW: flat revenue, lower ROIC, LOW CapEx (fat conservative owner-FCF), flat shares.
    _seed(tmp_db, "COW",
          revenue=[50e9, 50e9, 50e9, 50e9], ebit=[15e9, 15e9, 15e9, 15e9],
          ocf=[18e9, 18e9, 18e9, 18e9], capex=[2e9, 2e9, 2e9, 2e9],
          da=[2e9, 2e9, 2e9, 2e9], sbc=1e9, debt=10e9, cash=40e9,
          shares=[1.00e9, 1.00e9, 1.00e9])
    universe = pd.DataFrame({
        "symbol": ["COMP", "COW"],
        "sector": ["Technology", "Technology"],
        "industry": ["Software", "Software"],
        "market_cap": ["large_cap", "large_cap"],
    })
    market = {
        "COMP": {"market_cap": 6.0e11, "total_debt": 10e9, "cash": 40e9},
        "COW": {"market_cap": 6.0e11, "total_debt": 10e9, "cash": 40e9},
    }
    graded = sg.grade_universe(tmp_db, universe, market_data=market, as_of=AS_OF)
    by = {g.symbol: g for g in graded}
    # the compounder is NOT suppressed
    assert by["COMP"].grade not in ("VETOED", "INSUFFICIENT"), by["COMP"].note
    assert by["COMP"].composite is not None
    # and it is competitive: the growth pillar + normalized earnings lift it to at least the
    # cash cow's composite (the whole point of Stage-1.5 - it is no longer dominated).
    assert by["COMP"].composite >= by["COW"].composite
    # the compounder's Growth pillar strictly beats the flat cash cow's
    assert by["COMP"].g > by["COW"].g
```

### Step 2 - run, see behavior

```
uv run pytest tests/test_scout_grade_compounder_regression.py -v -s
```

If any assertion fails, this is a TUNING task, not a code-change task (the code is already written in Tasks 1-6). Read the actual pillar values with `-s` (add temporary `print(by["COMP"], by["COW"])`), confirm the DIRECTION is right (COMP should have higher V yield on normalized earnings, higher G, comparable Q), and adjust the seeded magnitudes (CapEx vs OCF vs D&A, EBIT for ROIC, revenue slope, share slope) until COMP is genuinely a high-ROIC fast-growing reinvestor that the Stage-1.5 grader rewards. Do NOT weaken the assertions to force a pass - adjust the fixture so the economics are real. Then remove debug prints.

### Step 3 - run, confirm green

```
uv run pytest tests/test_scout_grade_compounder_regression.py -v
uv run pytest -q
```

**Expected:** the regression passes. Full suite `873 passed, 3 skipped` (872 + 1).

### Step 4 - commit

```
git add tests/test_scout_grade_compounder_regression.py
git commit -m "$(cat <<'EOF'
test(scout): compounder-vs-cash-cow regression proves Stage-1.5 de-bias (the whole point)

A heavy-reinvesting high-ROIC grower in the same sector as a mature cash cow is no longer
vetoed and is no longer dominated on composite.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Task 9 - Structural gate: monitoring path byte-unchanged, no new deps, no LLM

Prove `store.owner_fcf_ttm` and the monitoring path are untouched, no pip dependency was added, no LLM was imported, and the full suite is green.

### Files
- **Create:** `tests/test_scout_stage1_5_structural.py`

### Step 1 - write the gate test

Create `tests/test_scout_stage1_5_structural.py`:

```python
"""Stage-1.5 phase gate: the de-bias touched the Scout DISCOVERY path only. store.owner_fcf_ttm
and the monitoring surface are unchanged; no new pip dependency; no LLM import."""
import importlib
import inspect
import sys
import tomllib
from pathlib import Path

import agentcy.scout_grade  # noqa: F401
import agentcy.render.scout  # noqa: F401
from agentcy.fetch import store


def test_store_owner_fcf_ttm_still_conservative_min_is_total_capex():
    """store.owner_fcf_ttm's per-period construction is still (OCF - |CapEx|) - SBC (the
    conservative figure); it must NOT reference the normalized min(|CapEx|, D&A) proxy or the
    'Depreciation And Amortization' row. This is the byte-level guard on the monitoring path."""
    src = inspect.getsource(store.owner_fcf_ttm)
    assert "Depreciation And Amortization" not in src
    assert "abs(float(capex))" in src            # conservative: full CapEx subtracted
    # the normalized figure lives in the Scout layer, not store
    assert not hasattr(store, "normalized_owner_fcf_ttm")


def test_normalized_lives_in_scout_grade_not_store():
    from agentcy import scout_grade as sg
    assert hasattr(sg, "normalized_owner_fcf_ttm")


def test_no_new_pip_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {d.split("==")[0].split(">")[0].split("[")[0].strip().lower() for d in deps}
    assert names == {"yfinance", "pandas", "scipy", "quantstats"}
    extras = data["project"]["optional-dependencies"]
    assert set(extras) == {"scout"}


def test_scout_grade_imports_no_llm():
    for mod in ("agentcy.scout_grade", "agentcy.render.scout", "agentcy.scout"):
        importlib.reload(importlib.import_module(mod))
    banned = ("anthropic", "openai", "langchain", "llama", "cohere", "google.generativeai")
    loaded = set(sys.modules)
    assert not any(b in m for b in banned for m in loaded)
```

### Step 2 - run

```
uv run pytest tests/test_scout_stage1_5_structural.py -v
```

If `test_store_owner_fcf_ttm_still_conservative_min_is_total_capex` fails on the `abs(float(capex))` substring, read `store.owner_fcf_ttm` and adjust the substring to whatever exact conservative token is present (it is `fcf += float(ocf) - abs(float(capex))` in the current source) - the intent is to assert the conservative full-CapEx subtraction survived, so match a stable substring of that line.

### Step 3 - full suite + explicit monitoring-path guard

```
uv run pytest -q
git status --porcelain
git diff --stat HEAD~8 -- agentcy/fetch/store.py
```

**Expected:** full suite `877 passed, 3 skipped` (873 + 4 new gate tests). `git diff --stat HEAD~8 -- agentcy/fetch/store.py` shows NO changes to `agentcy/fetch/store.py` across the whole Stage-1.5 series (we only READ its helpers; we never edited it). If it shows edits, STOP - `store.py` must be byte-unchanged.

Also confirm the monitoring/trigger/Gate/Register modules are untouched:

```
git diff --stat HEAD~8 -- agentcy/triggers.py agentcy/register.py agentcy/asks.py agentcy/jobs/
```

**Expected:** empty output (no changes to any monitoring-path file).

### Step 4 - commit

```
git add tests/test_scout_stage1_5_structural.py
git commit -m "$(cat <<'EOF'
test(scout): Stage-1.5 structural gate - store.owner_fcf_ttm + monitoring path unchanged

Guards that the de-bias is discovery-only: conservative owner_fcf_ttm untouched, normalized
figure lives in scout_grade, no new pip dep, no LLM import.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Final verification

```
uv run pytest -q
```

**Expected:** `877 passed, 3 skipped`, 0 failures. License gate and no-LLM gate green.

Task count total: **10** (Task 0 baseline + Tasks 1-9). Net new tests added across the plan: +21 (Task 1: +4, Task 2: +3, Task 4: +4 growth / -1 deleted management, Task 6: +5 veto / +1 batch, Task 8: +1, Task 9: +4), so `856 + 21 = 877`. If your running count differs, reconcile before claiming completion (a task may have added/removed a test you did not account for).

---

## Explicit follow-ons (NOT built here)

Per design §Scope (YAGNI), the following are deliberately deferred and are NOT part of this plan:

- **Stage-2 (LLM qualitative reviewer).** Moat durability, management candor, and fad-risk judgments over the graded shortlist. The Task 7 framing line explicitly names these as pending Stage-2 work; no LLM client is imported in this build.
- **Fundamentals populator resume.** The archive batch populator (held task #24) resumes immediately AFTER this de-bias, running on the corrected grader. Not touched here.
- **FX.** No currency conversion added; market_data is consumed in the statement's native currency exactly as today.
- **ROIIC (return on incremental capital).** Too noisy from a <3yr archive; revenue growth + per-share normalized owner-earnings growth are the robust G legs. ROIIC stays deferred.
