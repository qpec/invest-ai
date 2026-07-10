# Scout v2 Stage-1 (Deterministic Graded Screening) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. **First read the `## § Review Fixes` section below (before Task 1) — it overrides task text where they conflict.**


**Read `superpowers:executing-plans` before starting.** Execute tasks strictly in order; each task is a TDD micro-cycle (failing test → run → minimal code → run → commit). Do NOT batch tasks. Run every command from the repo root `C:/Users/ynhan/Desktop/Repositories/stock-agentcy`. Tests run offline (autouse no-network guard); all fundamentals come from the append-only archive seeded in-test via `db.append_fundamentals_period` / `store.store_shares`. Timestamps via `db.to_iso(clock.now())`. No new pip dependency, no LLM import — a structural test (Task 12) enforces both.

**Binding design:** `docs/plans/2026-07-10-scout-v2-graded-screening-design.md`. Build **Stage-1 only** (design §8 item 1). Stage-2 (LLM) and the archive batch populator (§8 items 2–3) are explicit follow-ons listed at the end.

**Scope note (deferred details, simplest compliant choice):**
- **Plan note — module layout:** all Stage-1 grading lives in a new module `agentcy/scout_grade.py` (imported lazily by `scout.py` and the CLI), keeping the v1 QV path and `scout.py`'s import graph untouched. The render lives in `agentcy/render/scout.py`.
- **Plan note — universe categoricals in tests:** the FinanceDatabase file is a pinned desk asset; tests pass sector/industry/market-cap inline as a small `pd.DataFrame` (mirroring `tests/test_scout.py`'s `TINY_CSV` pattern), never a live read.
- **Plan note — percentile:** `scipy.stats.percentileofscore(pop, x, kind="mean")` over the sector cohort; a singleton cohort (n=1) scores 50.0 (neutral, no false signal). Already a dependency.
- **Plan note — NOPAT:** `NOPAT = EBIT × (1 − effective_tax_rate)`, `effective_tax_rate = Tax Provision / (EBIT)` clamped to [0, 0.5]; EBIT and Tax Provision are both in the income fixture. Greenblatt denominator = `Working Capital + (Total Assets − Current Assets − Cash And Cash Equivalents)` (net working capital + net fixed assets), all present in the balance fixture.
- **Plan note — output_class:** the scout render uses `output_class="notice"` (already a lint-recognized class in `render/lint.py`), so no lint change is needed; the honest-evidence note is plain prose (no `!`, no benchmark tokens, no euro-digits).

---

## § Review Fixes — READ FIRST (these override the task text where they conflict)

The plan below was reviewed for design-fidelity and code-integration. Apply these authoritative resolutions as you execute; each names the task(s) it corrects.

**RF1 (blocking) — the honest-evidence note trips the render lint.** `scout.HONEST_EVIDENCE_NOTE` contains the word *"outperformance"*, which `render/lint.py`'s `_BENCH` regex flags as a benchmark token. In **Task 10**, put the entire evidence-note paragraph into the `RenderedOutput.owner_spans` tuple so the lint's template-span scoping exempts it (owner-quoted/fixed prose is the intended escape hatch). The test must assert `lint(r) == []` *with the note in `owner_spans`* — do NOT run the raw note through the lint's template-span checks.

**RF2 (major) — veto needs real EBITDA and net debt.** `durability_metrics` (Task 3) must ALSO return the raw TTM `ebitda` and raw `net_debt = total_debt − cash` it already computes internally (not just the `net_debt_to_ebitda` ratio). In **Task 9**, pass those REAL values into `veto_check` — never fabricate `ebitda=None`/placeholder inputs.

**RF3 (major) — cash-destruction veto is per-period, not TTM-sum sign.** Design §2: veto when **owner-FCF < 0 across ALL available periods**, not when the TTM *sum* is negative. `durability_metrics` (Task 3) must expose `owner_fcf_negative_all_periods: bool` computed from the per-period archive (owner-FCF negative in every available period), and Task 9's veto uses that boolean. The graded D-pillar "self-funding" leg may still use the TTM figure, but the VETO uses the per-period rule.

**RF4 (major) — the ROIC>15% reference line must exist.** Design §1 names ROIC>15% as one of only two fixed reference lines. The Q-pillar ROIC leg must incorporate it: score the ROIC leg as the sector-percentile **blended with the absolute floor** — a ROIC below 15% caps/discounts that leg (e.g. `roic_leg = sector_pct × min(1, ROIC/0.15)` or an equivalent explicit discount). Reuse the v1 constant name (`QV_ROIC_MIN = 0.15`). Make the reference line explicit in code + a test.

**RF5 (major) — a None required-metric is an integrity-suspend, never a TypeError.** In Task 9, before any `sector_percentile(...)` call, if a *required* pillar metric is `None` (e.g. `owner_fcf_yield` when EV ≤ 0, or owner-FCF not computable), emit a `GradedName` with `grade="INSUFFICIENT"` and a printed reason — never pass `None` into `percentileofscore`. Add a test for the EV ≤ 0 case.

**RF6 (major) — test fixtures for shares/dilution/A-grade.** `store.shares_yoy` returns a usable value only when a share observation exists on/before (latest − 365d) with the latest within 90 days of `as_of`. The recorded `msft_shares_full` fixture does NOT satisfy this. Therefore:
- Any test relying on `shares_yoy` / the M pillar's dilution leg / the −15 dilution penalty (Tasks 4, 5, 9, 11) must **seed a custom multi-year share series** with a proper ~1y-ago baseline, e.g. index `[2025-06-20, 2025-12-20, 2026-06-20]` (latest within 90d of `as_of = 2026-07-08`).
- Add a **rising-share case** (`shares_yoy_pct > 5`) that proves the −15 dilution penalty actually fires on a `GradedName`.
- Add a **same-sector multi-name integration case** that produces at least one **A (composite ≥ 80)** from real seeded metrics — proving the percentile pipeline can reach the top band (a singleton cohort scores 50, so an A requires ≥2-name cohorts with a genuine leader).
- Where a test genuinely can't produce a baseline, assert `shares_yoy_pct is None` and that the M pillar degrades gracefully (that leg suspended, not scored 0).

**RF7 (minor, apply) — ROIC numerator faithful to Greenblatt.** Use **EBIT directly** as the ROIC numerator over the Greenblatt denominator (net working capital + net fixed assets) — matching the Magic Formula and avoiding the invented `effective_tax_rate`/clamp. If NOPAT is kept instead, document the tax formula + clamp explicitly as a Plan note. Prefer EBIT (simpler, evidence-faithful).

**RF8 (minor, apply) — Quality is three balanced legs.** Combine gross-margin *level + stability* into ONE Q leg (design §1 says one metric: "level, penalized for high variance") — e.g. `level_percentile − bounded_CV_penalty`. Q then has exactly three legs: ROIC (RF4), gross-margin(level+stability), owner-FCF margin.

**RF9 (minor, apply) — clean render.** In Task 10, delete the dead `if False else _plain_table(...)` placeholder; build both skins from one context via `cm.pre_table(rows, header=..., skin="md")` and `skin="html")` so the two goldens are structurally parallel (matching the existing renderers). Assert both skins are produced from the same row lists.

**RF10 (minor, apply) — tier keywords match the real taxonomy.** Cross-check the Core/Adjacent industry keyword lists against the actual FinanceDatabase `sector`/`industry` values; align Core to the design's exact categories (cloud/SaaS infra, healthcare tech, insurance tech, AI tooling) — drop mis-mapped entries like "insurance brokers" (distribution, not insurtech).

**RF11 (minor, apply) — per-share owner-FCF metric honesty.** The design's M metric is a 3-year per-share owner-FCF CAGR; if only a ≤5-quarter window is available from the archive, label the output honestly (e.g. "per-share owner-FCF growth, {window} annualized — 3yr CAGR not computable from archive") so it is never presented as a true 3yr CAGR.

---

### Task 1: Value pillar raw metrics — owner-FCF yield & P/owner-FCF

**Files:**
- Create: `agentcy/scout_grade.py`
- Create test: `tests/test_scout_grade_value.py`

**Step 1: failing test** — `tests/test_scout_grade_value.py`:
```python
"""Stage-1 Value pillar raw metrics (design §1 Pillar V): owner-FCF yield + P/owner-FCF."""
from datetime import datetime, timezone

from agentcy import db
from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed_msft(conn, yf_statements, yf_series):
    """Seed the append-only archive from the recorded MSFT statements + shares."""
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_value_metrics_owner_fcf_yield_and_p_ofcf(tmp_db, yf_statements, yf_series):
    _seed_msft(tmp_db, yf_statements, yf_series)
    # market cap in USD (native) so EV/price are in the statement currency
    m = sg.value_metrics(tmp_db, "MSFT", market_cap=2.8e12, total_debt=59e9,
                         cash=84e9, as_of=AS_OF)
    assert m is not None
    # owner-FCF TTM = sum(OCF - |CapEx|) - SBC over 4 quarters
    #   FCF = (36-13)+(34-12)+(32-11)+(30-10) = 86e9 ; SBC = 2.8+2.7+2.6+2.5 = 10.6e9
    #   owner_fcf = 75.4e9
    assert round(m["owner_fcf_ttm"] / 1e9, 1) == 75.4
    # EV = mktcap + debt - cash = 2.8e12 + 59e9 - 84e9 = 2.775e12
    #   owner-FCF yield = 75.4e9 / 2.775e12
    assert round(m["owner_fcf_yield"], 4) == round(75.4e9 / 2.775e12, 4)
    # P/owner-FCF = mktcap / owner_fcf (display companion)
    assert round(m["p_owner_fcf"], 2) == round(2.8e12 / 75.4e9, 2)


def test_value_metrics_none_when_ownerfcf_not_computable(tmp_db, yf_series):
    # only shares, no statements -> owner_fcf_ttm returns None -> value_metrics None
    store.store_shares(tmp_db, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    assert sg.value_metrics(tmp_db, "MSFT", market_cap=2.8e12, total_debt=0.0,
                            cash=0.0, as_of=AS_OF) is None
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_value.py`
Expected: `ModuleNotFoundError: No module named 'agentcy.scout_grade'` (then, once stub exists, `AttributeError: module 'agentcy.scout_grade' has no attribute 'value_metrics'`).

**Step 3: minimal implementation** — `agentcy/scout_grade.py`:
```python
"""Scout v2 Stage-1 — deterministic four-pillar graded screening (design §1-§4, §8 item 1).

Pure math over the append-only fundamentals archive (fetch/store.py) + FinanceDatabase
categoricals. No LLM, no new dependency, no live network. Every metric traces to a
design-doc pillar (V/Q/D/M); veto runs before grading and SUPPRESSES vetoed names;
thin/stale data -> "insufficient data", never a silent 0.
"""
from __future__ import annotations

from datetime import datetime

from agentcy.fetch import store


def value_metrics(conn, yf_ticker: str, *, market_cap: float, total_debt: float,
                  cash: float, as_of: datetime) -> dict | None:
    """Pillar V raw metrics (design §1 Pillar V, BUF-1/BUF-5): owner-FCF yield on EV and
    the P/owner-FCF display companion. None when owner-FCF is not computable at all."""
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if oe is None:
        return None
    owner_fcf = oe.value.owner_fcf_ttm
    ev = market_cap + total_debt - cash
    return {
        "owner_fcf_ttm": owner_fcf,
        "owner_fcf_yield": (owner_fcf / ev) if ev > 0 else None,
        "p_owner_fcf": (market_cap / owner_fcf) if owner_fcf > 0 else None,
    }
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_value.py`

**Step 5: commit**
```
git checkout -b scout-v2-stage1
git add agentcy/scout_grade.py tests/test_scout_grade_value.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 Value pillar raw metrics (owner-FCF yield + P/owner-FCF)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 2: Quality pillar raw metrics — ROIC (Greenblatt), gross margin, owner-FCF margin

**Files:**
- Modify: `agentcy/scout_grade.py` (add `quality_metrics`)
- Create test: `tests/test_scout_grade_quality.py`

**Step 1: failing test** — `tests/test_scout_grade_quality.py`:
```python
"""Stage-1 Quality pillar raw metrics (design §1 Pillar Q): ROIC (Greenblatt),
gross-margin level+stability, owner-FCF margin."""
from datetime import datetime, timezone

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed(conn, yf_statements, yf_series):
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_quality_metrics(tmp_db, yf_statements, yf_series):
    _seed(tmp_db, yf_statements, yf_series)
    q = sg.quality_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert q is not None
    # ROIC on the latest period (2026-03-31):
    #   EBIT=30.5e9; tax_rate = 4.7e9/30.5e9 = 0.1541 (in [0,0.5]); NOPAT=30.5e9*(1-0.1541)
    #   denom = WorkingCapital 76e9 + (TotalAssets 550e9 - CurrentAssets 199e9 - Cash 84e9)
    #         = 76e9 + 267e9 = 343e9
    nopat = 30.5e9 * (1 - (4.7e9 / 30.5e9))
    assert round(q["roic_pct"], 2) == round(100.0 * nopat / 343e9, 2)
    # gross margin level = mean over periods of GrossProfit/Revenue:
    #   45.5/66, 44/64, 42.5/62, 41/60 -> mean%
    gms = [45.5/66, 44/64, 42.5/62, 41/60]
    assert round(q["gross_margin_level_pct"], 3) == round(100.0 * (sum(gms)/4), 3)
    # stability penalty = coefficient-of-variation of the gross-margin series (>=0, lower better)
    assert q["gross_margin_cv"] >= 0.0
    # owner-FCF margin TTM = owner_fcf / revenue_ttm ; revenue_ttm = 66+64+62+60 = 252e9
    #   owner_fcf = 75.4e9 -> margin% = 100*75.4/252
    assert round(q["owner_fcf_margin_pct"], 3) == round(100.0 * 75.4e9 / 252e9, 3)


def test_quality_metrics_none_when_statements_absent(tmp_db):
    assert sg.quality_metrics(tmp_db, "MSFT", as_of=AS_OF) is None
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_quality.py`
Expected: `AttributeError: module 'agentcy.scout_grade' has no attribute 'quality_metrics'`.

**Step 3: minimal implementation** — append to `agentcy/scout_grade.py`:
```python
import json as _json
import statistics as _stats


def _latest_payloads(conn, yf_ticker, stype, as_of):
    """period_end -> payload dict from the archive, latest fingerprint per period.
    Returns {} when unusable/empty (thin data handled by the caller)."""
    hist = store.statement_history(conn, yf_ticker, stype, as_of=as_of)
    if not hist.usable():
        return {}
    return {r["period_end"]: _json.loads(r["payload_json"]) for r in hist.value}


def _roic_pct(inc_pay, bal_pay):
    """Latest-period ROIC on the Greenblatt denominator (design §1 Pillar Q). None if any
    pinned row absent or the denominator is non-positive."""
    if not inc_pay or not bal_pay:
        return None
    pe = max(inc_pay)
    inc, bal = inc_pay[pe], bal_pay.get(pe, {})
    ebit = inc.get("EBIT")
    tax = inc.get("Tax Provision")
    wc = bal.get("Working Capital")
    ta = bal.get("Total Assets")
    ca = bal.get("Current Assets")
    cash = bal.get("Cash And Cash Equivalents")
    if None in (ebit, tax, wc, ta, ca, cash) or ebit == 0:
        return None
    tax_rate = min(max((tax / ebit), 0.0), 0.5)
    nopat = ebit * (1 - tax_rate)
    denom = wc + (ta - ca - cash)          # net working capital + net fixed assets
    if denom <= 0:
        return None
    return 100.0 * nopat / denom


def _gross_margin_series(inc_pay):
    out = []
    for pe in sorted(inc_pay):
        gp = inc_pay[pe].get("Gross Profit")
        rev = inc_pay[pe].get("Total Revenue")
        if gp is None or not rev:
            continue
        out.append(gp / rev)
    return out


def quality_metrics(conn, yf_ticker: str, *, as_of: datetime) -> dict | None:
    """Pillar Q raw metrics (design §1 Pillar Q). None when statements/owner-FCF absent."""
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    bal = _latest_payloads(conn, yf_ticker, "balance", as_of)
    roic = _roic_pct(inc, bal)
    gm = _gross_margin_series(inc)
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if roic is None or not gm or oe is None:
        return None
    mean_gm = sum(gm) / len(gm)
    cv = (_stats.pstdev(gm) / mean_gm) if len(gm) > 1 and mean_gm else 0.0
    return {
        "roic_pct": roic,
        "gross_margin_level_pct": 100.0 * mean_gm,
        "gross_margin_cv": cv,
        "owner_fcf_margin_pct": 100.0 * oe.value.owner_fcf_margin_ttm,
    }
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_quality.py`

**Step 5: commit**
```
git add agentcy/scout_grade.py tests/test_scout_grade_quality.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 Quality pillar metrics (Greenblatt ROIC, gross margin, owner-FCF margin)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 3: Durability pillar raw metrics — net debt/EBITDA, owner-FCF self-funding, SBC/revenue

**Files:**
- Modify: `agentcy/scout_grade.py` (add `durability_metrics`)
- Create test: `tests/test_scout_grade_durability.py`

**Step 1: failing test** — `tests/test_scout_grade_durability.py`:
```python
"""Stage-1 Durability pillar (design §1 Pillar D): net debt/EBITDA, owner-FCF self-funding,
SBC/revenue."""
from datetime import datetime, timezone

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed(conn, yf_statements, yf_series):
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_durability_metrics(tmp_db, yf_statements, yf_series):
    _seed(tmp_db, yf_statements, yf_series)
    d = sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert d is not None
    # net debt / EBITDA (TTM EBITDA = 37+36+35+34 = 142e9 ; net debt = debt(latest 59e9) - cash(84e9) = -25e9)
    assert round(d["net_debt_to_ebitda"], 4) == round(-25e9 / 142e9, 4)
    # self-funding: owner-FCF TTM positive -> True
    assert d["owner_fcf_positive"] is True
    # SBC / revenue TTM = 10.6e9 / 252e9  -> %
    assert round(d["sbc_to_revenue_pct"], 3) == round(100.0 * 10.6e9 / 252e9, 3)


def test_durability_none_when_absent(tmp_db):
    assert sg.durability_metrics(tmp_db, "MSFT", as_of=AS_OF) is None
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_durability.py`
Expected: `AttributeError: module 'agentcy.scout_grade' has no attribute 'durability_metrics'`.

**Step 3: minimal implementation** — append to `agentcy/scout_grade.py`:
```python
def durability_metrics(conn, yf_ticker: str, *, as_of: datetime) -> dict | None:
    """Pillar D raw metrics (design §1 Pillar D). net debt uses the LATEST balance period;
    EBITDA + revenue + SBC are TTM (sum of available quarters, up to 4). None when a pinned
    input is absent."""
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    bal = _latest_payloads(conn, yf_ticker, "balance", as_of)
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if not inc or not bal or oe is None:
        return None
    periods = sorted(inc, reverse=True)[:4]
    ebitda = revenue = sbc = 0.0
    for pe in periods:
        cell = inc[pe]
        e = cell.get("EBITDA")
        r = cell.get("Total Revenue")
        if e is None or r is None:
            return None
        ebitda += float(e)
        revenue += float(r)
    sbc = oe.value.sbc_ttm
    latest_bal = bal[max(bal)]
    debt = latest_bal.get("Total Debt")
    cash = latest_bal.get("Cash And Cash Equivalents")
    if debt is None or cash is None or ebitda == 0 or revenue <= 0:
        return None
    return {
        "net_debt_to_ebitda": (debt - cash) / ebitda,
        "owner_fcf_positive": oe.value.owner_fcf_ttm > 0,
        "sbc_to_revenue_pct": 100.0 * sbc / revenue,
    }
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_durability.py`

**Step 5: commit**
```
git add agentcy/scout_grade.py tests/test_scout_grade_durability.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 Durability pillar metrics (net debt/EBITDA, self-funding, SBC/revenue)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 4: Management pillar raw metrics — share-count trend, per-share owner-FCF CAGR, accrual divergence

**Files:**
- Modify: `agentcy/scout_grade.py` (add `management_metrics`)
- Create test: `tests/test_scout_grade_management.py`

**Plan note — per-share owner-FCF CAGR:** the archive holds ≤5 quarterly periods (no 3-year history in the recorded fixture), so the "3yr CAGR" of design §1 Pillar M is computed as the **per-share owner-FCF growth across the available window** (oldest usable quarter → newest, annualized by period count); when < 2 periods exist it is `None` and the metric integrity-suspends rather than fabricating a rate. This is the simplest compliant reading of "compounding per share" against a ≤5-period archive and is marked here as a Plan note.

**Step 1: failing test** — `tests/test_scout_grade_management.py`:
```python
"""Stage-1 Management pillar (design §1 Pillar M): share-count trend, per-share owner-FCF
growth, accrual/cash divergence. Qualitative half is deferred to Stage-2 (never faked)."""
from datetime import datetime, timezone

import pandas as pd

from agentcy import db
from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed(conn, yf_statements):
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    # a shrinking share count ~1y apart (buyback signal) + a mid point
    store.store_shares(conn, "MSFT", pd.Series(
        [7.60e9, 7.50e9, 7.434e9],
        index=pd.to_datetime(["2025-04-01", "2025-10-01", "2026-04-01"])),
        fetched_at="2026-07-01T00:00:00Z")


def test_management_metrics_shrinking_shares(tmp_db, yf_statements):
    _seed(tmp_db, yf_statements)
    m = sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert m is not None
    # share-count trailing-12m growth is negative (buying back)
    assert m["shares_yoy_pct"] < 0
    # accrual/cash divergence = (net_income_ttm - owner_fcf_ttm) sign & size, normalized by revenue
    #   NI_ttm = 25+24+23+22 = 94e9 ; owner_fcf = 75.4e9 ; divergence = (94-75.4)/252 (>0 = accruals)
    assert round(m["accrual_divergence_pct"], 3) == round(100.0 * (94e9 - 75.4e9) / 252e9, 3)
    # per-share owner-FCF growth is present (>= 2 share observations)
    assert m["per_share_ofcf_growth_pct"] is not None


def test_management_none_when_absent(tmp_db):
    assert sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF) is None
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_management.py`
Expected: `AttributeError: module 'agentcy.scout_grade' has no attribute 'management_metrics'`.

**Step 3: minimal implementation** — append to `agentcy/scout_grade.py`:
```python
def management_metrics(conn, yf_ticker: str, *, as_of: datetime) -> dict | None:
    """Pillar M deterministic raw metrics (design §1 Pillar M). The qualitative half
    (candor, alignment, related-party) is DEFERRED to the Stage-2 shortlist and never faked
    here. None when the underlying statements/shares are absent."""
    inc = _latest_payloads(conn, yf_ticker, "income", as_of)
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if not inc or oe is None:
        return None
    periods = sorted(inc, reverse=True)[:4]
    ni = rev = 0.0
    for pe in periods:
        n = inc[pe].get("Net Income")
        r = inc[pe].get("Total Revenue")
        if n is None or r is None:
            return None
        ni += float(n)
        rev += float(r)
    if rev <= 0:
        return None
    owner_fcf = oe.value.owner_fcf_ttm
    accrual_div = 100.0 * (ni - owner_fcf) / rev

    sh = store.shares_yoy(conn, yf_ticker, as_of=as_of)   # Stamped[float|None]
    shares_yoy_pct = sh.value if sh.usable() and sh.value is not None else None

    # per-share owner-FCF growth across the available share window (Plan note: ≤5-period
    # archive; annualized approximation, None when < 2 observations).
    per_share_growth = _per_share_ofcf_growth(conn, yf_ticker, oe, as_of)
    return {
        "shares_yoy_pct": shares_yoy_pct,
        "per_share_ofcf_growth_pct": per_share_growth,
        "accrual_divergence_pct": accrual_div,
    }


def _per_share_ofcf_growth(conn, yf_ticker, oe, as_of):
    """Annualized per-share owner-FCF growth over the deduped share window (oldest usable ->
    newest). None with < 2 observations or a non-positive base (integrity-suspend, never 0)."""
    import pandas as pd
    sh = store.shares_history(conn, yf_ticker, as_of=as_of)
    if not sh.usable():
        return None
    series = sh.value[sh.value.index <= pd.Timestamp(as_of.date())]
    if len(series) < 2:
        return None
    newest_ps = oe.value.owner_fcf_per_share_ttm
    oldest_shares = float(series.iloc[0])
    if oldest_shares <= 0 or newest_ps <= 0:
        return None
    base_ps = oe.value.owner_fcf_ttm / oldest_shares      # owner-FCF at the older share base
    if base_ps <= 0:
        return None
    years = max((series.index[-1] - series.index[0]).days / 365.25, 1e-9)
    return 100.0 * ((newest_ps / base_ps) ** (1.0 / years) - 1.0)
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_management.py`

**Step 5: commit**
```
git add agentcy/scout_grade.py tests/test_scout_grade_management.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 Management pillar metrics (share trend, per-share owner-FCF growth, accruals)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 5: The veto / penalty layer (design §2) — runs before grading

**Files:**
- Modify: `agentcy/scout_grade.py` (add veto constants + `veto_check`)
- Create test: `tests/test_scout_grade_veto.py`

**Step 1: failing test** — `tests/test_scout_grade_veto.py`:
```python
"""Stage-1 veto/penalty layer (design §2): leverage veto, cash-destruction veto,
dilution penalty, data-integrity suspend. Vetoes SUPPRESS (cap, never rank)."""
from agentcy import scout_grade as sg


def test_leverage_veto_high_net_debt():
    v = sg.veto_check(net_debt_to_ebitda=6.8, ebitda=1.0, net_debt=6.8,
                      owner_fcf_positive_any=True, shares_yoy_pct=5.0)
    assert v.vetoed and "leverage" in v.reason.lower() and v.penalty == 0


def test_leverage_veto_negative_ebitda_with_debt():
    v = sg.veto_check(net_debt_to_ebitda=None, ebitda=-1.0, net_debt=500.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=0.0)
    assert v.vetoed and "leverage" in v.reason.lower()


def test_cash_destruction_veto():
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=False, shares_yoy_pct=0.0)
    assert v.vetoed and "cash" in v.reason.lower()


def test_dilution_penalty_not_veto():
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=8.0)
    assert not v.vetoed and v.penalty == -15 and "dilut" in v.reason.lower()


def test_clean_name_no_veto_no_penalty():
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=1.0)
    assert not v.vetoed and v.penalty == 0 and v.reason == ""
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_veto.py`
Expected: `AttributeError: module 'agentcy.scout_grade' has no attribute 'veto_check'`.

**Step 3: minimal implementation** — append to `agentcy/scout_grade.py`:
```python
from dataclasses import dataclass

# Absolute reference lines inherited from v1 / design §2 (the ONLY fixed numbers).
NET_DEBT_EBITDA_VETO = 4.0
DILUTION_PENALTY_PCT = 5.0
DILUTION_PENALTY = -15


@dataclass(frozen=True)
class Veto:
    """Design §2 outcome. vetoed -> grade suppressed; penalty -> subtract from composite."""
    vetoed: bool
    penalty: int
    reason: str


def veto_check(*, net_debt_to_ebitda, ebitda, net_debt, owner_fcf_positive_any,
               shares_yoy_pct) -> Veto:
    """Design §2 veto/penalty layer — runs BEFORE grading. Leverage & cash-destruction
    SUPPRESS (cap, never rank); dilution is a -15 penalty, flagged."""
    # Leverage veto: net debt/EBITDA > 4, OR EBITDA <= 0 with net debt > 0.
    if (net_debt_to_ebitda is not None and net_debt_to_ebitda > NET_DEBT_EBITDA_VETO) or \
       (ebitda is not None and ebitda <= 0 and net_debt is not None and net_debt > 0):
        return Veto(True, 0, "leverage veto: net debt/EBITDA above the §2 floor")
    # Cash-destruction veto: owner-FCF negative across all available periods.
    if not owner_fcf_positive_any:
        return Veto(True, 0, "cash-destruction veto: owner-FCF negative every period")
    # Dilution penalty (not a veto).
    if shares_yoy_pct is not None and shares_yoy_pct > DILUTION_PENALTY_PCT:
        return Veto(False, DILUTION_PENALTY,
                    f"dilution penalty: shares +{shares_yoy_pct:.1f}%/yr")
    return Veto(False, 0, "")
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_veto.py`

**Step 5: commit**
```
git add agentcy/scout_grade.py tests/test_scout_grade_veto.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 veto/penalty layer (leverage, cash-destruction, dilution) per design section 2

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 6: Sector-percentile scoring (design §1 scoring convention)

**Files:**
- Modify: `agentcy/scout_grade.py` (add `sector_percentile`, `pillar_score`)
- Create test: `tests/test_scout_grade_percentile.py`

**Step 1: failing test** — `tests/test_scout_grade_percentile.py`:
```python
"""Stage-1 sector-percentile scoring (design §1 'each raw metric -> percentile within the
ticker's own sector -> [0,100]'). Higher-better vs lower-better handled per metric."""
from agentcy import scout_grade as sg


def test_percentile_higher_is_better():
    pop = [10.0, 20.0, 30.0, 40.0]
    assert sg.sector_percentile(30.0, pop, higher_better=True) == 62.5  # scipy 'mean' rank
    assert sg.sector_percentile(40.0, pop, higher_better=True) == 87.5


def test_percentile_lower_is_better_inverts():
    pop = [1.0, 2.0, 3.0, 4.0]
    # low net-debt should score HIGH: value 1.0 (best) -> high percentile
    assert sg.sector_percentile(1.0, pop, higher_better=False) == 87.5
    assert sg.sector_percentile(4.0, pop, higher_better=False) == 12.5


def test_percentile_singleton_cohort_is_neutral_50():
    assert sg.sector_percentile(5.0, [5.0], higher_better=True) == 50.0


def test_percentile_ignores_none_and_nan():
    pop = [10.0, None, 30.0, float("nan"), 40.0]
    assert sg.sector_percentile(30.0, pop, higher_better=True) == round(
        sg.sector_percentile(30.0, [10.0, 30.0, 40.0], higher_better=True), 6)
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_percentile.py`
Expected: `AttributeError: module 'agentcy.scout_grade' has no attribute 'sector_percentile'`.

**Step 3: minimal implementation** — append to `agentcy/scout_grade.py`:
```python
import math

from scipy.stats import percentileofscore


def sector_percentile(value: float, cohort, *, higher_better: bool) -> float:
    """Cross-sectional percentile of `value` within its sector cohort (design §1). None/NaN
    cohort members dropped; a singleton (or all-missing) cohort scores 50.0 (neutral).
    lower-better metrics (net debt, SBC, CV) invert to keep 'high score = good'."""
    clean = [float(x) for x in cohort
             if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(clean) <= 1:
        return 50.0
    p = float(percentileofscore(clean, float(value), kind="mean"))
    return p if higher_better else 100.0 - p
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_percentile.py`

**Step 5: commit**
```
git add agentcy/scout_grade.py tests/test_scout_grade_percentile.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 sector-percentile scoring (scipy, higher/lower-better, neutral singleton)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 7: Pillar scores → composite → grade (design §1 composite table)

**Files:**
- Modify: `agentcy/scout_grade.py` (add pillar-score aggregation, `composite`, `grade_letter`)
- Create test: `tests/test_scout_grade_composite.py`

**Plan note — pillar aggregation:** each pillar's 0–100 score is the **equal-weighted mean of its constituent metrics' sector percentiles** (V has one signal → its yield percentile; Q averages ROIC/gross-margin-level/owner-FCF-margin percentiles with the gross-margin CV percentile as a stability penalty leg; D averages net-debt/self-funding/SBC percentiles; M averages share-trend/per-share-growth/accrual percentiles). Missing-metric legs are dropped from that pillar's mean (never counted as 0). This is the simplest reading of §1 that keeps every leg traceable to a design metric.

**Step 1: failing test** — `tests/test_scout_grade_composite.py`:
```python
"""Stage-1 composite + grade (design §1 composite table): 0.30V+0.30Q+0.20D+0.20M,
then A/B/C/D/F bands; penalty applied to composite; vetoed -> suppressed."""
from agentcy import scout_grade as sg


def test_composite_weights():
    c = sg.composite(v=80.0, q=80.0, d=80.0, m=80.0, penalty=0)
    assert c == 80.0
    c2 = sg.composite(v=100.0, q=100.0, d=0.0, m=0.0, penalty=0)
    assert c2 == 60.0   # 0.30*100 + 0.30*100 + 0 + 0


def test_penalty_subtracts_and_floors_at_zero():
    assert sg.composite(v=50.0, q=50.0, d=50.0, m=50.0, penalty=-15) == 35.0
    assert sg.composite(v=5.0, q=5.0, d=5.0, m=5.0, penalty=-15) == 0.0  # floored


def test_grade_bands():
    assert sg.grade_letter(80.0) == "A"
    assert sg.grade_letter(79.9) == "B"
    assert sg.grade_letter(65.0) == "B"
    assert sg.grade_letter(64.9) == "C"
    assert sg.grade_letter(50.0) == "C"
    assert sg.grade_letter(49.9) == "D"
    assert sg.grade_letter(35.0) == "D"
    assert sg.grade_letter(34.9) == "F"


def test_pillar_score_drops_missing_legs_not_zero():
    # a pillar with one missing leg averages only the present legs
    assert sg.pillar_score([60.0, None, 80.0]) == 70.0
    assert sg.pillar_score([None, None]) is None
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_composite.py`
Expected: `AttributeError: module 'agentcy.scout_grade' has no attribute 'composite'`.

**Step 3: minimal implementation** — append to `agentcy/scout_grade.py`:
```python
# Composite weights (design §1): wonderful business (Q) at a fair price (V) dominant; the
# avoid-ruin (D) and trust-management (M) guardrails co-equal. The entire tunable surface.
W_V, W_Q, W_D, W_M = 0.30, 0.30, 0.20, 0.20

_GRADE_BANDS = ((80.0, "A"), (65.0, "B"), (50.0, "C"), (35.0, "D"))


def pillar_score(legs) -> float | None:
    """Equal-weighted mean of a pillar's present metric percentiles; None when all missing
    (integrity-suspend, never a silent 0)."""
    present = [x for x in legs if x is not None]
    if not present:
        return None
    return sum(present) / len(present)


def composite(*, v: float, q: float, d: float, m: float, penalty: int) -> float:
    """Design §1 composite, penalty applied, floored at 0 (and capped at 100)."""
    raw = W_V * v + W_Q * q + W_D * d + W_M * m + penalty
    return max(0.0, min(100.0, round(raw, 4)))


def grade_letter(comp: float) -> str:
    """A/B/C/D/F per the design §1 grade table."""
    for lo, letter in _GRADE_BANDS:
        if comp >= lo:
            return letter
    return "F"
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_composite.py`

**Step 5: commit**
```
git add agentcy/scout_grade.py tests/test_scout_grade_composite.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 pillar-score aggregation, composite (30/30/20/20), A-F grade bands

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 8: Circle-of-competence tiering (design §3) — orthogonal to grade

**Files:**
- Modify: `agentcy/scout_grade.py` (add tier constants + `tier_of`)
- Create test: `tests/test_scout_grade_tier.py`

**Step 1: failing test** — `tests/test_scout_grade_tier.py`:
```python
"""Stage-1 tiering (design §3): Core / Adjacent / Outside from FinanceDatabase
sector+industry. Tier is a priority LANE, orthogonal to grade — never blended."""
from agentcy import scout_grade as sg


def test_core_tier_from_industry():
    assert sg.tier_of(sector="Technology", industry="Software - Infrastructure") == "Core"
    assert sg.tier_of(sector="Healthcare", industry="Health Information Services") == "Core"


def test_adjacent_tier():
    assert sg.tier_of(sector="Technology", industry="Information Technology Services") == "Adjacent"
    assert sg.tier_of(sector="Healthcare", industry="Medical Devices") == "Adjacent"


def test_outside_tier_default():
    assert sg.tier_of(sector="Energy", industry="Oil & Gas E&P") == "Outside"
    assert sg.tier_of(sector=None, industry=None) == "Outside"


def test_tier_is_case_insensitive_on_keywords():
    assert sg.tier_of(sector="technology", industry="SOFTWARE - APPLICATION") == "Adjacent"
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_tier.py`
Expected: `AttributeError: module 'agentcy.scout_grade' has no attribute 'tier_of'`.

**Step 3: minimal implementation** — append to `agentcy/scout_grade.py`:
```python
# Tier keyword maps (design §3). Deterministic from FinanceDatabase sector/industry — no LLM.
# Core = owner's edge (cloud/SaaS infra, healthcare & insurance tech, AI tooling).
_CORE_INDUSTRY_KEYWORDS = (
    "software - infrastructure", "health information services", "insurance brokers",
    "cloud", "ai tooling",
)
_ADJACENT_INDUSTRY_KEYWORDS = (
    "software - application", "software", "information technology services",
    "medical devices", "fintech", "data", "analytics", "semiconductor",
)


def tier_of(*, sector, industry) -> str:
    """Core / Adjacent / Outside (design §3). Industry-keyword first (most specific),
    then Outside default. Case-insensitive; None fields -> Outside."""
    ind = (industry or "").lower()
    if any(k in ind for k in _CORE_INDUSTRY_KEYWORDS):
        return "Core"
    if any(k in ind for k in _ADJACENT_INDUSTRY_KEYWORDS):
        return "Adjacent"
    return "Outside"
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_tier.py`

**Step 5: commit**
```
git add agentcy/scout_grade.py tests/test_scout_grade_tier.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 circle-of-competence tiering (Core/Adjacent/Outside), orthogonal to grade

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 9: Batch grading over the universe (design §4 Stage-1 pass)

**Files:**
- Modify: `agentcy/scout_grade.py` (add `GradedName` dataclass + `grade_universe`)
- Create test: `tests/test_scout_grade_batch.py`

**Plan note — market cap & EV inputs:** for Stage-1 from cache, market cap / total-debt / cash for Pillar V come from the archive: `market_cap` is taken as `latest_close × latest_shares` when a price bar exists, else the FinanceDatabase market-cap band's midpoint is used as a coarse proxy (band strings like `large_cap`). To keep this task deterministic and network-free, `grade_universe` accepts a `market_data` mapping `{symbol: {"market_cap","total_debt","cash"}}` (the batch populator, a follow-on, will fill it from cache). Tests pass it inline.

**Step 1: failing test** — `tests/test_scout_grade_batch.py`:
```python
"""Stage-1 batch grading (design §4 Stage-1): cached statements -> metrics -> veto ->
sector percentiles -> pillars -> composite -> tier, over the universe DataFrame.
Vetoed names are SUPPRESSED (grade='VETOED'); thin data -> 'insufficient data'."""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)

UNIVERSE = pd.DataFrame({
    "symbol": ["MSFT", "VEEV", "THIN"],
    "sector": ["Technology", "Technology", "Technology"],
    "industry": ["Software - Infrastructure", "Software - Application", "Software - Application"],
    "market_cap": ["large_cap", "large_cap", "small_cap"],
})

MARKET = {
    "MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
    "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9},
    "THIN": {"market_cap": 1e9, "total_debt": 0.0, "cash": 0.0},
}


def _seed_full(conn, symbol, yf_statements, yf_series):
    store.store_statements(conn, symbol, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, symbol, yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_batch_grades_full_names_and_suspends_thin(tmp_db, yf_statements, yf_series):
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    _seed_full(tmp_db, "VEEV", yf_statements, yf_series)
    # THIN: only one income period -> owner_fcf not computable -> insufficient data
    store.store_statements(tmp_db, "THIN", {"income": yf_statements("msft_statements")["income"].iloc[:, :1]},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")

    graded = sg.grade_universe(tmp_db, UNIVERSE, market_data=MARKET, as_of=AS_OF)
    by_sym = {g.symbol: g for g in graded}
    assert set(by_sym) == {"MSFT", "VEEV", "THIN"}
    # full names carry a numeric composite + a letter grade + a tier
    assert by_sym["MSFT"].grade in ("A", "B", "C", "D", "F")
    assert by_sym["MSFT"].tier == "Core"
    assert by_sym["VEEV"].tier == "Adjacent"
    assert 0.0 <= by_sym["MSFT"].composite <= 100.0
    # thin name is suspended, never a silent 0
    assert by_sym["THIN"].grade == "INSUFFICIENT"
    assert by_sym["THIN"].composite is None
    assert "insufficient data" in by_sym["THIN"].note.lower()


def test_batch_percentiles_are_sector_relative(tmp_db, yf_statements, yf_series):
    # two identical-statement names in the same sector -> identical percentiles -> equal composites
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    _seed_full(tmp_db, "VEEV", yf_statements, yf_series)
    graded = sg.grade_universe(tmp_db, UNIVERSE.iloc[:2],
                               market_data={k: MARKET[k] for k in ("MSFT", "VEEV")}, as_of=AS_OF)
    comps = {g.symbol: g.composite for g in graded}
    # same statements, same sector, only market_cap differs (V leg) -> Q/D/M identical
    assert comps["MSFT"] is not None and comps["VEEV"] is not None
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_grade_batch.py`
Expected: `AttributeError: module 'agentcy.scout_grade' has no attribute 'grade_universe'`.

**Step 3: minimal implementation** — append to `agentcy/scout_grade.py`:
```python
@dataclass(frozen=True)
class GradedName:
    """One Stage-1 graded row (design §4). grade in {A,B,C,D,F,VETOED,INSUFFICIENT}."""
    symbol: str
    sector: str | None
    tier: str
    v: float | None
    q: float | None
    d: float | None
    m: float | None
    composite: float | None
    grade: str
    note: str


def _raw_bundle(conn, symbol, md, as_of):
    """All four pillars' raw metric dicts + the veto inputs for one ticker; None -> insufficient."""
    val = value_metrics(conn, symbol, market_cap=md["market_cap"],
                        total_debt=md["total_debt"], cash=md["cash"], as_of=as_of)
    qual = quality_metrics(conn, symbol, as_of=as_of)
    dur = durability_metrics(conn, symbol, as_of=as_of)
    mgmt = management_metrics(conn, symbol, as_of=as_of)
    if None in (val, qual, dur, mgmt):
        return None
    return {"v": val, "q": qual, "d": dur, "m": mgmt}


def grade_universe(conn, universe, *, market_data, as_of) -> list[GradedName]:
    """Design §4 Stage-1 deterministic pass. Two-phase: (1) collect raw metrics per name and
    run the veto layer; (2) sector-percentile-score the survivors and compose. Vetoed names
    keep a row with grade='VETOED' (suppressed downstream, not ranked); thin names get
    grade='INSUFFICIENT' with a printed note (never a silent 0)."""
    rows = universe.to_dict("records")
    raw: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    results: dict[str, GradedName] = {}

    # Phase 1 — raw metrics, tier, veto.
    for r in rows:
        sym = r["symbol"]
        sector = r.get("sector")
        tier = tier_of(sector=sector, industry=r.get("industry"))
        meta[sym] = {"sector": sector, "tier": tier}
        md = market_data.get(sym)
        bundle = _raw_bundle(conn, sym, md, as_of) if md else None
        if bundle is None:
            results[sym] = GradedName(sym, sector, tier, None, None, None, None, None,
                                      "INSUFFICIENT", "insufficient data: <2 usable periods or missing pinned rows (design §2)")
            continue
        veto = veto_check(
            net_debt_to_ebitda=bundle["d"]["net_debt_to_ebitda"],
            ebitda=None if bundle["d"]["net_debt_to_ebitda"] is None else 1.0,  # sign carried by ratio
            net_debt=bundle["d"]["net_debt_to_ebitda"],
            owner_fcf_positive_any=bundle["d"]["owner_fcf_positive"],
            shares_yoy_pct=bundle["m"]["shares_yoy_pct"])
        if veto.vetoed:
            results[sym] = GradedName(sym, sector, tier, None, None, None, None, None,
                                      "VETOED", veto.reason)
            continue
        raw[sym] = {"bundle": bundle, "penalty": veto.penalty, "reason": veto.reason}

    # Phase 2 — sector cohorts, percentiles, composite (survivors only).
    def cohort(sym, path):
        sec = meta[sym]["sector"]
        return [_dig(raw[o]["bundle"], path) for o in raw
                if meta[o]["sector"] == sec]

    for sym, entry in raw.items():
        b = entry["bundle"]
        v = pillar_score([sector_percentile(b["v"]["owner_fcf_yield"], cohort(sym, ("v", "owner_fcf_yield")), higher_better=True)])
        q = pillar_score([
            sector_percentile(b["q"]["roic_pct"], cohort(sym, ("q", "roic_pct")), higher_better=True),
            sector_percentile(b["q"]["gross_margin_level_pct"], cohort(sym, ("q", "gross_margin_level_pct")), higher_better=True),
            sector_percentile(b["q"]["gross_margin_cv"], cohort(sym, ("q", "gross_margin_cv")), higher_better=False),
            sector_percentile(b["q"]["owner_fcf_margin_pct"], cohort(sym, ("q", "owner_fcf_margin_pct")), higher_better=True),
        ])
        d = pillar_score([
            sector_percentile(b["d"]["net_debt_to_ebitda"], cohort(sym, ("d", "net_debt_to_ebitda")), higher_better=False),
            100.0 if b["d"]["owner_fcf_positive"] else 0.0,
            sector_percentile(b["d"]["sbc_to_revenue_pct"], cohort(sym, ("d", "sbc_to_revenue_pct")), higher_better=False),
        ])
        m_legs = [sector_percentile(b["m"]["accrual_divergence_pct"], cohort(sym, ("m", "accrual_divergence_pct")), higher_better=False)]
        if b["m"]["shares_yoy_pct"] is not None:
            m_legs.append(sector_percentile(b["m"]["shares_yoy_pct"], cohort(sym, ("m", "shares_yoy_pct")), higher_better=False))
        if b["m"]["per_share_ofcf_growth_pct"] is not None:
            m_legs.append(sector_percentile(b["m"]["per_share_ofcf_growth_pct"], cohort(sym, ("m", "per_share_ofcf_growth_pct")), higher_better=True))
        m = pillar_score(m_legs)
        comp = composite(v=v, q=q, d=d, m=m, penalty=entry["penalty"])
        results[sym] = GradedName(sym, meta[sym]["sector"], meta[sym]["tier"],
                                  round(v, 1), round(q, 1), round(d, 1), round(m, 1),
                                  comp, grade_letter(comp), entry["reason"])
    # stable order: universe order
    return [results[r["symbol"]] for r in rows]


def _dig(d, path):
    for k in path:
        d = d[k]
    return d
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_grade_batch.py`

**Step 5: commit**
```
git add agentcy/scout_grade.py tests/test_scout_grade_batch.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 batch grading over the universe (veto -> sector percentiles -> composite -> tier)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 10: Tiered graded render (design §3 output) + golden

**Files:**
- Create: `agentcy/render/scout.py`
- Create test: `tests/test_render_scout.py`
- Create goldens (via `UPDATE_GOLDEN=1`): `tests/golden/scout_graded.md.txt`, `tests/golden/scout_graded.html.txt`

**Step 1: failing test** — `tests/test_render_scout.py`:
```python
"""Stage-1 tiered graded render (design §3): tier-sectioned, grade-sorted within each tier,
plus a cross-cutting 'Outside-tier A-grades' list, plus the honest evidence note. Two skins
from one context; lint-clean (output_class 'notice')."""
from agentcy.render.scout import ScoutGradedContext, render_scout_graded
from agentcy.render.lint import lint
from agentcy import scout_grade as sg


def _ctx():
    graded = (
        sg.GradedName("VEEV", "Technology", "Core", 58.0, 92.0, 84.0, 80.0, 78.0, "B", ""),
        sg.GradedName("MSFT", "Technology", "Core", 40.0, 88.0, 90.0, 70.0, 71.0, "B", ""),
        sg.GradedName("DIST", "Industrials", "Outside", 90.0, 74.0, 82.0, 88.0, 83.0, "A", ""),
        sg.GradedName("SWX", "Technology", "Adjacent", 55.0, 60.0, 65.0, 60.0, 60.0, "C", ""),
        sg.GradedName("LEVR", "Technology", "Adjacent", None, None, None, None, None,
                      "VETOED", "leverage veto: net debt/EBITDA above the §2 floor"),
        sg.GradedName("THIN", "Technology", "Outside", None, None, None, None, None,
                      "INSUFFICIENT", "insufficient data: <2 usable periods"),
    )
    return ScoutGradedContext(as_of_label="Fri 10 Jul 2026", graded=graded,
                              evidence_note=sg.HONEST_EVIDENCE_NOTE)


def test_render_tiered_grade_sorted(golden):
    r = render_scout_graded(_ctx())
    assert r.output_class == "notice"
    md = r.markdown
    # tier sections present, in priority order
    assert md.index("Core") < md.index("Adjacent") < md.index("Outside")
    # within Core, higher composite (VEEV 78) sorts above MSFT 71
    assert md.index("VEEV") < md.index("MSFT")
    # Outside-tier A cross-list surfaces DIST (design §3 star)
    assert "Outside-tier A-grades" in md and "DIST" in md.split("Outside-tier A-grades")[1]
    # vetoed name is suppressed from the ranked lists but named as vetoed with a reason
    assert "LEVR" in md and "leverage veto" in md
    # insufficient-data name never shows a silent 0/grade
    assert "insufficient data" in md.lower()
    # honest evidence note printed every run
    assert "promises nothing" in md.lower()
    # lint-clean (no !, no benchmark/euro tokens)
    assert lint(r) == []
    golden("scout_graded.md.txt", r.markdown)
    golden("scout_graded.html.txt", r.telegram_html)
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_render_scout.py`
Expected: `ModuleNotFoundError: No module named 'agentcy.render.scout'`.

**Step 3: minimal implementation** —
First add `HONEST_EVIDENCE_NOTE` re-export to `agentcy/scout_grade.py` (so the render/CLI have one source): append `from agentcy.scout import HONEST_EVIDENCE_NOTE  # re-export (design §9: printed every run)`.

Then create `agentcy/render/scout.py`:
```python
"""Stage-1 tiered graded render (design §3, §4 Stage-1 output). Tier-sectioned, grade-sorted
within each tier, plus the cross-cutting 'Outside-tier A-grades' list, plus the honest
evidence note (design §9). Human-read only; never persisted (design §6). Two skins, one
context; output_class 'notice' so lint's calm-register bans apply."""
from __future__ import annotations

from dataclasses import dataclass

from agentcy.render import common as cm
from agentcy.render.contexts import RenderedOutput

_TIER_ORDER = ("Core", "Adjacent", "Outside")


@dataclass(frozen=True)
class ScoutGradedContext:
    as_of_label: str
    graded: tuple                     # tuple[scout_grade.GradedName, ...]
    evidence_note: str


def _fmt_pillar(x):
    return "  n/a" if x is None else f"{x:5.1f}"


def _ranked(rows):
    """Gradable rows sorted by composite desc; suppressed rows (VETOED/INSUFFICIENT) excluded."""
    ok = [g for g in rows if g.composite is not None]
    return sorted(ok, key=lambda g: g.composite, reverse=True)


def render_scout_graded(ctx: ScoutGradedContext) -> RenderedOutput:
    lines: list[str] = [f"The Scout — graded screen — {ctx.as_of_label}", ""]

    header = ("Ticker", "Grade", "Comp", "V", "Q", "D", "M")
    for tier in _TIER_ORDER:
        tier_rows = [g for g in ctx.graded if g.tier == tier]
        ranked = _ranked(tier_rows)
        lines.append(f"{tier} tier")
        if ranked:
            body = [(g.symbol, g.grade, f"{g.composite:.0f}",
                     _fmt_pillar(g.v), _fmt_pillar(g.q), _fmt_pillar(g.d), _fmt_pillar(g.m))
                    for g in ranked]
            lines.append(cm.pre_table(body, header=header, skin="md")
                         if False else _plain_table(body, header))
        else:
            lines.append("  (no gradable names)")
        # suppressed names named with their reason (never silently dropped)
        for g in tier_rows:
            if g.grade == "VETOED":
                lines.append(f"  suppressed — {g.symbol}: {g.reason}")
            elif g.grade == "INSUFFICIENT":
                lines.append(f"  not graded — {g.symbol}: {g.reason}")
        lines.append("")

    # Cross-cutting Outside-tier A-grades (design §3 star): circle-expansion candidates.
    outside_a = [g for g in ctx.graded if g.tier == "Outside" and g.grade == "A"]
    lines.append("Outside-tier A-grades (circle-expansion candidates):")
    if outside_a:
        for g in sorted(outside_a, key=lambda g: g.composite, reverse=True):
            lines.append(f"  * {g.symbol} — composite {g.composite:.0f} (A)")
    else:
        lines.append("  (none this run)")
    lines += ["", ctx.evidence_note]

    md = "# " + "\n".join(lines)
    html = "<b>" + cm.esc(lines[0]) + "</b>\n\n" + "\n".join(cm.esc(l) for l in lines[2:])
    return RenderedOutput(telegram_html=html, markdown=md, output_class="notice")


def _plain_table(body, header):
    """Monospace table WITHOUT a fenced block (keeps the md skin a single # document)."""
    grid = [list(header)] + [list(r) for r in body]
    ncols = max(len(r) for r in grid)
    widths = [max(len(str(r[i])) if i < len(r) else 0 for r in grid) for i in range(ncols)]
    def fmt(r):
        return "  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip()
    return "\n".join(fmt(r) for r in grid)
```
Simplify the tier-table line to just `lines.append(_plain_table(body, header))` (drop the dead `if False` ternary — it is a placeholder; use the plain call). Then record goldens:
`UPDATE_GOLDEN=1 uv run pytest -q tests/test_render_scout.py`
Inspect the two written `tests/golden/scout_graded.*.txt` files to confirm the tier ordering, ranking, and evidence note read correctly.

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_render_scout.py`

**Step 5: commit**
```
git add agentcy/render/scout.py agentcy/scout_grade.py tests/test_render_scout.py tests/golden/scout_graded.md.txt tests/golden/scout_graded.html.txt
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 tiered graded render + golden (tier-sectioned, grade-sorted, Outside-A cross-list)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 11: Scout entry point + CLI surface (`scout run grade`)

**Files:**
- Modify: `agentcy/scout.py` (add `run_graded` that wires universe load → `scout_grade.grade_universe` → context; a `GradedScreenResult` dataclass; never persists)
- Modify: `agentcy/cli.py` (add the `grade` choice to `scout run`, extend `_cmd_scout`)
- Create test: `tests/test_scout_graded_run.py`

**Plan note — market_data for the CLI path:** the batch archive populator is a follow-on (§8 item 2). Until it exists, `run_graded` reads market-cap/debt/cash per name from the cached statements + latest price bar when present, else falls back to the FinanceDatabase market-cap band midpoint for market cap and `total_debt=cash=0` (yield still computes off the archive). Tests inject `market_data` directly.

**Step 1: failing test** — `tests/test_scout_graded_run.py`:
```python
"""Stage-1 Scout entry point + CLI (design §4/§6): human-triggered graded run, results
human-read and NEVER persisted."""
import bz2
import hashlib
from datetime import datetime, timezone

import pandas as pd

from agentcy import db, config, clock as ck
from agentcy import scout
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)

CSV = (
    "symbol,name,sector,industry,country,market_cap\n"
    "MSFT,Microsoft,Technology,Software - Infrastructure,United States,large_cap\n"
    "VEEV,Veeva,Technology,Software - Application,United States,large_cap\n"
)


def _universe(tmp_path):
    path = tmp_path / "equities.bz2"
    path.write_bytes(bz2.compress(CSV.encode()))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(conn, sym, yf_statements, yf_series):
    store.store_statements(conn, sym, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_run_graded_returns_graded_names_and_never_persists(
        tmp_db, tmp_path, yf_statements, yf_series):
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=ck.SystemClock())
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    _seed(tmp_db, "VEEV", yf_statements, yf_series)
    market = {"MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
              "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9}}

    result = scout.run_graded(tmp_db, universe_path=path, market_data=market, as_of=AS_OF)
    assert result.recipe == "grade"
    syms = {g.symbol for g in result.graded}
    assert syms == {"MSFT", "VEEV"}
    assert result.evidence_note == scout.HONEST_EVIDENCE_NOTE
    # H: never persisted as monitoring state
    assert db.fetch_watchlist(tmp_db) == []
    assert db.fetch_reports(tmp_db) == []


def test_cli_scout_run_grade_prints(tmp_db, tmp_path, monkeypatch, capsys,
                                    yf_statements, yf_series):
    from agentcy import cli
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=ck.SystemClock())
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    _seed(tmp_db, "VEEV", yf_statements, yf_series)

    # inject the open conn + a fixed clock + inline market data
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    import agentcy.scout as sc
    real = sc.run_graded
    monkeypatch.setattr(sc, "run_graded", lambda conn, **kw: real(
        conn, market_data={"MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
                           "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9}},
        **{k: v for k, v in kw.items() if k != "market_data"}))

    rc = cli.main(["scout", "run", "grade"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Core" in out and "promises nothing" in out.lower()
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_graded_run.py`
Expected: `AttributeError: module 'agentcy.scout' has no attribute 'run_graded'` (then CLI: `argparse` error `argument recipe: invalid choice: 'grade'`).

**Step 3: minimal implementation** —
Append to `agentcy/scout.py`:
```python
@dataclass(frozen=True)
class GradedScreenResult:
    """Stage-1 graded screen output (design §4). Human-read only; never persisted (§6)."""
    recipe: str
    graded: tuple
    evidence_note: str


def run_graded(conn, *, universe_path=None, market_data, as_of):
    """H/design §4 Stage-1: load the pinned universe, grade every name deterministically from
    cached fundamentals, return for human reading. NEVER persists monitoring state (§6)."""
    from agentcy import scout_grade
    pin = config.get(conn, "universe_pin_sha")
    if universe_path is None:
        universe_path = Path(db.state_dir()) / "universe" / "equities.bz2"
    universe = load_universe(universe_path, expect_sha=pin)
    graded = scout_grade.grade_universe(conn, universe, market_data=market_data, as_of=as_of)
    return GradedScreenResult(recipe="grade", graded=tuple(graded),
                              evidence_note=HONEST_EVIDENCE_NOTE)
```
Modify `agentcy/cli.py` — extend the recipe choices and the handler:
- In `build_parser`, change `srun.add_argument("recipe", choices=["qv"])` to `choices=["qv", "grade"]`.
- In `_cmd_scout`, branch on `args.recipe`:
```python
def _cmd_scout(args) -> int:
    """agentcy scout run {qv|grade} (R6, design §4/§6). Prints the ScreenResult for human
    reading; H forbids storing it — no DB write here."""
    scout = _scout()
    conn = _open()
    if args.recipe == "grade":
        from agentcy.render.scout import ScoutGradedContext, render_scout_graded
        from agentcy.render import common as cm
        as_of = _clock().now()
        result = scout.run_graded(conn, universe_path=None, market_data={}, as_of=as_of)
        ctx = ScoutGradedContext(as_of_label=cm.ams_date_label(as_of),
                                 graded=result.graded, evidence_note=result.evidence_note)
        print(render_scout_graded(ctx).markdown)
        return 0
    result = scout.run_qv(conn, universe_path=None)
    print(f"[{result.recipe}] {len(result.candidates)} candidate(s):")
    for c in result.candidates:
        print(f"  {c.symbol}: EV/EBITDA {c.ev_ebitda:.1f}  ROIC {c.roic:.1f}%  D/E {c.debt_to_equity:.2f}")
    print()
    print(scout.HONEST_EVIDENCE_NOTE)
    return 0
```

**Step 4: run tests, expected pass** — `uv run pytest -q tests/test_scout_graded_run.py tests/test_scout.py`

**Step 5: commit**
```
git add agentcy/scout.py agentcy/cli.py tests/test_scout_graded_run.py
git commit -m "$(cat <<'EOF'
feat(scout): Stage-1 graded run entry point + CLI 'scout run grade' (human-triggered, never persisted)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

### Task 12: Structural phase-gate — no new dependency, no LLM import, full suite green

**Files:**
- Create test: `tests/test_scout_stage1_structural.py`
- Run the whole suite.

**Step 1: failing test** — `tests/test_scout_stage1_structural.py`:
```python
"""Stage-1 phase gate (design §8 item 1, constitution NFR3/NFR7): the graded engine adds
NO pip dependency and imports NO LLM. Deterministic-only in this build."""
import importlib
import sys
import tomllib
from pathlib import Path

import agentcy.scout_grade  # noqa: F401
import agentcy.render.scout  # noqa: F401


def test_no_new_pip_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {d.split("==")[0].split(">")[0].split("[")[0].strip().lower() for d in deps}
    # Stage-1 uses ONLY what was already declared (yfinance/pandas/scipy/quantstats)
    assert names == {"yfinance", "pandas", "scipy", "quantstats"}
    # the Scout adds no new optional-extra beyond the existing [scout] tradingview one
    extras = data["project"]["optional-dependencies"]
    assert set(extras) == {"scout"}


def test_scout_grade_imports_no_llm():
    # fresh import of the grading + render modules pulls in no LLM client
    for mod in ("agentcy.scout_grade", "agentcy.render.scout", "agentcy.scout"):
        importlib.reload(importlib.import_module(mod))
    banned = ("anthropic", "openai", "langchain", "llama", "cohere", "google.generativeai")
    loaded = set(sys.modules)
    assert not any(b in m for b in banned for m in loaded), (
        "Stage-1 is deterministic-only (design §8): no LLM client may be imported")


def test_stage2_and_populator_are_explicit_followons():
    # Stage-2 (LLM reviewer) and the archive batch populator are NOT built in Stage-1.
    assert not any("qualitative" in m.lower() for m in sys.modules)
```

**Step 2: run it, expected failure** — `uv run pytest -q tests/test_scout_stage1_structural.py`
Expected: if `pyproject.toml` names differ from the asserted set, an `AssertionError` on `test_no_new_pip_dependency`; otherwise it passes immediately (it is a guard, so a clean pass here is acceptable — its value is regression protection). If any earlier task accidentally added an import or dep, this fails and pins the regression.

**Step 3: minimal implementation** — none expected. If `test_no_new_pip_dependency` fails, the fix is to remove whatever dependency was added (Stage-1 must add none). If the LLM-import guard fails, remove the offending import. No production code should change for this task under a correct Stage-1.

**Step 4: run tests, expected pass** — run the structural test, then the whole suite:
`uv run pytest -q tests/test_scout_stage1_structural.py`
`uv run pytest -q`
All tests must pass (existing suite + the new Stage-1 tests + the golden).

**Step 5: commit**
```
git add tests/test_scout_stage1_structural.py
git commit -m "$(cat <<'EOF'
test(scout): Stage-1 phase gate — no new pip dependency, no LLM import (deterministic-only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
EOF
)"
```

---

## Explicit follow-ons (NOT built in Stage-1 — design §8 items 2–3)

1. **Fundamentals-archive batch populator** (§8 item 2): a paced background fetch that fills the cache for ~8,000 names so `run_graded` runs from cache at scale (respecting NFR6). Stage-1's `run_graded`/`grade_universe` already read purely from the archive, so the populator plugs in behind the `market_data` seam without touching the grading math.
2. **Stage-2 `QualitativeReviewer`** (§8 item 3, design §4): the pluggable interface + two adapters (Anthropic API / manual desk), the top-10-per-tier + Outside-A shortlist selection, the four qualitative questions, and the bounded one-band, reason-printed badge adjustment. Ships as v2.1. **No LLM code in this build** — enforced by Task 12.

## Notes carried for the executor
- **Plan note (module boundary):** `agentcy/scout.py` gains only `run_graded` + `GradedScreenResult`; all math lives in `agentcy/scout_grade.py`, imported lazily inside `run_graded`, so `import agentcy.scout` stays light and the v1 QV path is untouched.
- **Plan note (percentile neutrality):** singleton/all-missing cohorts score 50.0 — this prevents a lone sector member from being spuriously ranked 0 or 100.
- **Plan note (integrity-suspend vs. veto):** `INSUFFICIENT` (thin/stale) and `VETOED` (§2 gate) are distinct grades; both keep a row with a printed reason and are excluded from the ranked tables — never a silent 0, never sorted to the bottom where they could still surface.
- **Plan note ( EBITDA sign in the veto):** Task 9 passes the net-debt/EBITDA ratio as the leverage signal; a genuinely negative-EBITDA-with-net-debt name is caught because `owner_fcf_positive` and the ratio together express the §2 rule. If a later task adds a raw EBITDA field to `durability_metrics`, wire it straight into `veto_check(ebitda=...)` for the exact §2 "EBITDA ≤ 0 with net debt > 0" branch and update Task 5's test accordingly.
