# Backfill-Thesis Onboarding (agentcy layer) - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

## Goal

Give every existing (eToro) holding that has NO live thesis a thesis that ORIGINATES from
the invested moment, so the Watchdog monitors it. This plan builds ONLY the agentcy
deterministic scaffolding:

1. detect thesis-less non-cash holdings from the latest snapshot,
2. compute a fundamentals baseline (revenue YoY, owner-FCF margin, net-debt/EBITDA, shares YoY),
3. auto-derive the four Moderate invalidation triggers from that baseline (exact formulas below),
4. create an `origin='backfill'` DRAFT thesis anchored to the invested moment (cost basis is
   RECORD-KEEPING only, quarantined from advice),
5. mint one Telegram ratification ask per drafted thesis (approve -> `intact` + triggers
   armed + monitored; edit -> stays `draft`),
6. wire it as `agentcy thesis backfill [--ticker T]` (idempotent), and
7. report DRAFT / thesis-less holdings honestly in the weekly letter, confirming an INTACT
   backfill thesis is picked up by the existing Watchdog with NO Watchdog change.

The Gate's new-buy discipline (C.2-C.6) and the Watchdog evaluation logic (`triggers.evaluate*`,
`weekly.run_trigger_tests`) are NOT changed. We only ensure backfill theses are picked up.

## Architecture

- New module `agentcy/backfill.py` holds the deterministic scaffolding (detection, baseline,
  trigger auto-derivation, draft-thesis creation, ratify-ask minting). It reuses
  `register.create_thesis(origin='backfill', ...)`, `register.TriggerSpec`, `asks.mint`,
  `mirror.advice_positions`, `db.fetch_position_details`, and the `store.*` series.
- The ratification consequence lives in `agentcy/asks.py` as a new `apply_consequence` branch
  (`bfr.approve`), mirroring the existing reconciliation/vfu dispatch pattern.
- The daemon callback path already routes any option-carrying ask through
  `asks.answer` -> `asks.apply_consequence`; the new ask uses the same generic path (no daemon
  code change beyond confirming behaviour in a test).
- The CLI adds `agentcy thesis backfill [--ticker T]` in `agentcy/cli.py`.
- The weekly letter change is a small addition to `agentcy/jobs/weekly.py`
  (`revalidation_lines`) so a thesis-less-or-draft holding is reported, not skipped.

## Tech Stack

- Python 3.13 (uv-managed CPython), stdlib + existing runtime deps (pandas/scipy already
  present). NO new pip dependency. NO LLM import anywhere in this plan.
- SQLite via `agentcy/db.py` append helpers only. Timestamps via `db.to_iso(clock.now())`.
- Tests: `uv run pytest`. Offline (autouse no-network guard); seed via the real fixtures
  (`tmp_db`, `fixed_clock`, `seeded_portfolio`), monkeypatch `store.*` for fundamentals.

---

## Review fixes (apply first - from the pre-execution fidelity review; two are BLOCKING)

**RF1 (BLOCKING, FR9 - Tasks 4/5) - "approve" must NOT promote placeholder judgment to a live thesis.** Creating the DRAFT thesis with placeholder qualitative fields (`conviction="medium"`, `moat_types=("switching_costs",)`, `business_model_2s="(draft ...)"`, `ten_year_statement="(draft ...)"`) is fine WHILE draft, but `_apply_backfill_approve` must NOT `register.activate` a thesis whose qualitative fields are still placeholders - that would render system-chosen placeholders as the owner's judgment (weekly.py:189 ten_year alert span, :406 conviction table, :271 anniversary "you set this to MEDIUM"). Fix: the ratify **approve** must carry the owner's REAL conviction (and the Claude-drafted moat/business-model/ten-year), and `_apply_backfill_approve` must `register.revise(...)` those qualitative fields from placeholder to the real values BEFORE `register.activate`. If approve is attempted while conviction is still the `"medium"` placeholder AND no real conviction was supplied, REFUSE it (the thesis stays draft) - never activate placeholders. Add a test: approve with placeholder-still-in-place and no owner conviction is refused (thesis stays draft, not monitored). (In tests, supply the real conviction/qualitative values to simulate the claudeclaw draft + owner ratification; the claudeclaw drafting itself is Part B.)

**RF2 (BLOCKING, draft-firing - new task before Task 7) - a DRAFT (unratified) thesis's triggers must NOT be evaluated/fire.** Triggers arm at `create_thesis` (v1 commit), and `db.fetch_armed_triggers` filters only `retired_at IS NULL` with NO thesis-status filter; `triggers.evaluate_armed`/`fire` have no status guard - so a draft backfill thesis's triggers get evaluated by the next weekly `run_trigger_tests` and can fire an alert + A-ask before the owner ever ratifies, violating "UNmonitored until approved." Fix: gate trigger evaluation on thesis status so ONLY `intact`/`under_review` theses' triggers are evaluated (filter in `evaluate_armed`, or equivalently in `run_trigger_tests`/`fetch_armed_triggers`). This is a deliberate, minimal Watchdog correctness change - so DROP the plan's absolute "NO Watchdog change" claim (change it to "the Watchdog evaluation math is unchanged; we add only a draft-status guard"). Add a test: a DRAFT backfill thesis with a breaching trigger does NOT fire (no alert, no A-ask); after ratify->intact it DOES fire.

**RF3 (MAJOR, Task 7) - preserve the exact glyphs.** `revalidation_lines` uses em-dash and middot; keep those EXACT characters and add ONLY the thesis-less/draft branch, so `test_render_weekly`'s golden does not break. Do not ASCII-ize the existing line.

**RF4 (MINOR, Task 5) - capture "edit" text reliably.** A bare tap of an "edit" button routes without `evidence=`, journaling an empty edit. Either open a ForceReply on the edit affordance (like the refute path) or accept edits only via free-text reply, so the owner's edit text is always captured.

**RF5 (MINOR, Task 4) - add a moat-link BOOTSTRAPPING test.** Add a case where >=2 non-moat legs compute but `margin_erosion` (the moat-linked leg) is absent, proving `_triggers_form_a_thesis` returns None (BOOTSTRAPPING) rather than a moat-linkless thesis.

The review confirmed everything else is code-accurate and design-faithful: the four trigger formulas + units + evaluability with no new evaluator, the ask-machinery reuse without a daemon change (no collision with ordinary N-notes), the cost-basis quarantine (value_at_purchase hard-None at v1 + positions_advice omits it), and the no-migration claim.

---

## Plan notes (assumptions, simplest compliant choice)

- **Where the logic lives.** A NEW module `agentcy/backfill.py`. `register.py` stays the pure
  thesis-versioning core; putting detection/baseline/auto-derivation there would bloat it and
  couple it to `mirror`/`store`. `backfill.py` is the composition layer, exactly as the design
  (section "Architecture") names "the deterministic scaffolding ... exposed as a job/CLI".
- **No schema migration is needed.** Every field the backfill thesis needs already exists:
  the `thesis` / `thesis_version` / `thesis_status_log` / `trigger` tables carry `origin`
  (CHECK includes `'backfill'`), all NOT-NULL qualitative columns, and `value_at_purchase`
  (nullable). The invested-moment anchor (`opened_at`, `invested_eur`, `quantity`) is already
  captured in `position_detail` (`schema/001_position_detail.sql`) and read via
  `db.fetch_position_details`. So NO `004_*.sql`. (For the record: 002=universe_fetch,
  003=scout_shortlist_verdict already exist; if a future need arises it would be `004_*.sql`
  following the 003 idiom.)
- **`value_at_purchase` handling.** Per the design it is RECORD-KEEPING only. `create_thesis`
  hard-writes `value_at_purchase=None` into `thesis_version` v1 for EVERY origin (see
  `register.create_thesis` line ~103: `"value_at_purchase": None`), and the `positions_advice`
  view physically omits `avg_open_price`. So the cost basis provably cannot leak into advice.
  We do NOT try to persist the entry price into the thesis in this build (YAGNI + it would need
  a schema change and risk the quarantine). We compute `entry = invested_eur / quantity` ONLY to
  put it in the ratification ask PROMPT text and in the returned `BackfillDraft` dataclass (for
  the letter / desk), never into `positions_advice`. Task 8 asserts the quarantine.
- **DRAFT placeholder values for the NOT-NULL qualitative fields.** Claude's qualitative
  drafting is Part B (out of scope). Until then the deterministic scaffolding fills the NOT-NULL
  `thesis_version` columns with explicit, documented DRAFT placeholders (constants in
  `backfill.py`):
  - `business_model_2s`   = `"(draft - pending ratification)"`
  - `moat_types`          = `("switching_costs",)`  (a single placeholder moat; min-1 rule
    satisfied; owner edits at ratification / Part B replaces it)
  - `moat_evidence`       = `"(draft - pending ratification)"`
  - `owner_earnings_json` = the pinned owner-earnings JSON from `store.owner_fcf_ttm` when
    computable, else `"{}"`
  - `owner_earnings_narrative` = `"(draft - pending ratification)"`
  - `fair_band_low` / `fair_band_high` = `0.0` / `0.0`  (no price verdict for backfill, BUF-12;
    a zero band is a visible placeholder, never used as a buy signal here)
  - `denominator_note`    = `"P/owner-FCF"`
  - `conviction`          = `"medium"`   (documented neutral default; owner-typed at ratify, FR9)
  - `mgmt_trust`          = `"neutral"`   (documented default)
  - `mgmt_trust_note`     = `None`
  - `circle_fit`          = `"edge"`      (documented conservative default; owner confirms)
  - `circle_fit_note`     = `None`
  - `ten_year_statement`  = `"(draft - pending ratification)"`
  - `status_buy_flag`     = `0`,  `status_buy_note` = `None`
  These are placeholders, not fabricated convictions: the thesis stays `draft` (UNmonitored)
  and the ratification ask is the FR9 owner-judgment gate before anything goes `intact`.
- **At least one moat-linked trigger (BUF-4).** `register._validate_triggers` requires >=2
  triggers and >=1 with a `moat_link`. The auto-derived `margin_erosion` trigger carries
  `moat_link="switching_costs"` (it links to the placeholder moat); the other three carry
  `moat_link=None`. When a leg's baseline is not computable it is omitted; Task 4 guarantees at
  least the moat-linked `margin_erosion` leg is present or the onboarding is reported as
  BOOTSTRAPPING and no thesis is created (never a <2-trigger or moat-linkless thesis).
- **Approve/edit semantics.** The ratify ask is `kind="F"` reused? NO - `F` is anniversary
  re-affirmation. We use a NEW consequence on a generic ask. The ask is minted with
  `kind="N"` would be a plain note; instead we mint `kind="A"`? `A` is alert. To avoid
  overloading an existing kind's consequence map, we mint the ratify ask as `kind="F"` is
  wrong. **Decision:** mint as a generic `kind="N"`-style is not option-routable. The `ask`
  table CHECK allows only `('A','Q','R','F','V','N')`. We reuse `kind="V"`? `V` is the
  non-execution verdict-follow-up. **Chosen (simplest compliant):** mint the ratify ask with a
  dedicated consequence by giving it `kind="R"`-family? No. The cleanest is: mint with any kind
  whose `_consequence` prefix we can extend. `asks._consequence` returns `"<prefix>.<choice>"`
  for R/F/V/N and the literal map only special-cases A/Q. So minting `kind="N"` with options
  `["approve","edit"]` yields consequence `"note.approve"` / `"note.edit"`. We therefore add
  the ratify dispatch keyed on the ask's `thesis_ref` + a marker, NOT on a new kind. **Final
  chosen approach (Task 5):** mint `kind="N"`, `options=["approve","edit"]`,
  `expects_freetext=True`, `thesis_ref=<thesis_id>`; `_consequence("N","approve")` ->
  `"note.approve"`. Add branches in `apply_consequence` for `note.approve` (activate the thesis
  when its `thesis_ref` names a draft backfill thesis) and `note.edit` (record the owner's edit
  text as a journal note; thesis stays draft). This adds NO new ask kind and NO schema change.
  See Task 5 for the exact code.

---

## Task 0 - Record the live baseline (no code change)

**Files:** none.

Run the suite and record the numbers this branch actually shows (verify, do not trust the
~963/3 figure):

```
uv run pytest -q
```

**Expected:** `963 passed, 3 skipped` (the 3 skips are AF_UNIX/git tests that only run on the
Linux target). If the count differs, note the new baseline in the commit message of Task 1 and
proceed - the plan's per-task deltas are what matter, not the absolute number.

No commit (nothing changed).

---

## Task 1 - Detect thesis-less holdings

Add `agentcy/backfill.py` with `detect_thesis_less(conn, *, as_of)` returning the non-cash
holdings in the latest snapshot that have `register.live_thesis_for(symbol) is None`, each
joined to its `position_detail` (opened_at, invested_eur, quantity).

**Files:**
- CREATE `agentcy/backfill.py`
- CREATE `tests/test_backfill.py`

**Failing test (`tests/test_backfill.py`):**

```python
"""tests/test_backfill.py - backfill-thesis onboarding (agentcy layer)."""
from datetime import datetime, timezone

from agentcy import db

AS_OF = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def _seed_two_holdings(tmp_db, fixed_clock):
    """Snapshot with NVDA (has a thesis) + ADYEN (no thesis) + cash; ADYEN carries an
    invested-moment position_detail row."""
    from agentcy import journal, register
    from agentcy.journal import EntryIn
    from agentcy.register import ThesisFields, TriggerSpec
    conn = tmp_db
    now = db.to_iso(fixed_clock.now())
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    snap_id = db.append_snapshot(conn, as_of="2026-07-06T20:00:00Z", source="api_pull",
                                 cash_balance_eur=5000.0, created_at=now)
    db.append_positions(conn, snap_id, [
        dict(symbol="NVDA", yf_ticker="NVDA", instrument_type="stock", quantity=10.0,
             avg_open_price=100.0, native_currency="USD", mv_native=2000.0, mv_eur=1800.0,
             weight=0.30, leverage=1.0),
        dict(symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock", quantity=5.0,
             avg_open_price=None, native_currency="EUR", mv_native=4200.0, mv_eur=4200.0,
             weight=0.70, leverage=1.0)])
    db.append_position_details(conn, snap_id, [
        dict(symbol="ADYEN", opened_at="2024-01-15T00:00:00Z", invested_native=3000.0,
             invested_eur=3000.0, unrealized_pnl_native=1200.0, unrealized_pnl_pct=40.0,
             current_rate=840.0, direction="buy", lot_count=2, raw_json="{}")])
    # NVDA gets a live thesis so it is NOT thesis-less
    fields = ThesisFields(
        business_model_2s="a. b.", moat_types=("switching_costs",), moat_evidence="e",
        owner_earnings_json="{}", owner_earnings_narrative="n", value_at_purchase=None,
        fair_band_low=25.0, fair_band_high=35.0, denominator_note=None, conviction="high",
        mgmt_trust="neutral", mgmt_trust_note=None, circle_fit="core", circle_fit_note=None,
        ten_year_statement="t", status_buy_flag=False, status_buy_note=None)
    trigs = [
        TriggerSpec(type="growth_floor", statement="s", metric="revenue_yoy", comparator="<",
                    threshold=10.0, moat_link=None, persistence="2_consecutive_quarters"),
        TriggerSpec(type="margin_erosion", statement="s", metric="owner_fcf_margin",
                    comparator="<", threshold=20.0, moat_link="switching_costs",
                    persistence="ttm")]
    tid = register.create_thesis(conn, ticker="NVDA", origin="gate", fields=fields,
                                 triggers=trigs, journal_ref=je, clock=fixed_clock)
    register.activate(conn, tid, cause="seed", clock=fixed_clock)
    conn.commit()
    return conn


def test_detect_thesis_less_returns_only_undressed_holding(tmp_db, fixed_clock):
    from agentcy import backfill
    conn = _seed_two_holdings(tmp_db, fixed_clock)
    found = backfill.detect_thesis_less(conn, as_of=AS_OF)
    assert [h.symbol for h in found] == ["ADYEN"]
    h = found[0]
    assert h.yf_ticker == "ADYEN" and h.quantity == 5.0
    assert h.opened_at == "2024-01-15T00:00:00Z" and h.invested_eur == 3000.0


def test_detect_skips_cash(tmp_db, fixed_clock):
    from agentcy import backfill
    conn = _seed_two_holdings(tmp_db, fixed_clock)
    # a cash position is never onboarded
    snap = db.fetch_latest_snapshot(conn)
    assert all(h.instrument_type != "cash" for h in backfill.detect_thesis_less(conn, as_of=AS_OF))
```

**Run (expect fail):**

```
uv run pytest -q tests/test_backfill.py
```

Expected: `ModuleNotFoundError: No module named 'agentcy.backfill'` (then, after the module
skeleton, `AttributeError`/assertion failures).

**Minimal implementation (`agentcy/backfill.py`):**

```python
"""agentcy/backfill.py - backfill-thesis onboarding (deterministic scaffolding).

Detects held positions with no live thesis, computes a fundamentals baseline as of the
invested moment, auto-derives the four Moderate invalidation triggers, creates an
origin='backfill' DRAFT thesis anchored to the invested moment, and mints a Telegram
ratification ask (approve -> intact + armed; edit -> stays draft). The Claude qualitative
drafting is Part B (out of scope); until then the NOT-NULL qualitative fields carry explicit
DRAFT placeholders and the thesis stays draft (UNmonitored) until ratified. Cost basis is
RECORD-KEEPING only and never enters positions_advice (invariant 4)."""
from __future__ import annotations

from dataclasses import dataclass

from agentcy import db, mirror, register
from agentcy.clock import Clock


@dataclass(frozen=True)
class HeldWithoutThesis:
    symbol: str
    yf_ticker: str | None
    instrument_type: str
    quantity: float
    opened_at: str | None
    invested_eur: float | None


def detect_thesis_less(conn, *, as_of) -> list[HeldWithoutThesis]:
    """Non-cash holdings in the latest snapshot with no live thesis, joined to their
    invested-moment position_detail (opened_at, invested_eur). Backed by advice_positions
    (invariant 4) + fetch_position_details (record-keeping companion)."""
    snap = db.fetch_latest_snapshot(conn)
    if snap is None:
        return []
    details = {d["symbol"]: d for d in db.fetch_position_details(conn, snap["snapshot_id"])}
    out: list[HeldWithoutThesis] = []
    for p in mirror.advice_positions(conn, snap["snapshot_id"]):
        if p.instrument_type == "cash":
            continue
        if register.live_thesis_for(conn, p.symbol) is not None:
            continue
        d = details.get(p.symbol)
        out.append(HeldWithoutThesis(
            symbol=p.symbol, yf_ticker=p.yf_ticker, instrument_type=p.instrument_type,
            quantity=p.quantity,
            opened_at=(d["opened_at"] if d else None),
            invested_eur=(d["invested_eur"] if d else None)))
    return out
```

**Run (expect pass):**

```
uv run pytest -q tests/test_backfill.py
```

Expected: both tests pass.

**Commit:**

```
feat(thesis): detect thesis-less holdings for backfill onboarding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 2 - Fundamentals baseline (None-safe)

Add `compute_baseline(conn, yf_ticker, *, as_of) -> Baseline`. Each leg reads the existing
`store` series and is None when not computable (thin/stale data -> that leg is skipped /
BOOTSTRAPPING, never faked).

Baseline legs and their sources (exact):
- `revenue_yoy`     <- last value of `store.revenue_yoy_series` (percent, e.g. 14.2)
- `owner_fcf_margin`<- `store.margin_series` last value (percent, e.g. 30.0)
- `net_debt_ebitda` <- `store.balance_safety_series` last value (ratio, e.g. 1.5)
- `shares_yoy`      <- `store.shares_yoy` scalar (percent, e.g. 1.2)
- `owner_earnings_json` <- `store.owner_fcf_ttm` pinned JSON when usable, else `"{}"`

A leg is None when its `Stamped` is None / not `.usable()` / carries a None value.

**Files:**
- EDIT `agentcy/backfill.py`
- EDIT `tests/test_backfill.py`

**Failing test (append to `tests/test_backfill.py`):**

```python
def _stub_store(monkeypatch, *, rev=None, margin=None, ndte=None, shares=None, oe_json=None):
    from agentcy.fetch import store
    from agentcy.freshness import Stamped, DataState

    def _stamped(value, state="fresh"):
        return Stamped(value=value, fetched_at=AS_OF, state=DataState(state), note=None)

    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: (_stamped(rev) if rev is not None else None),
                        raising=False)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: (_stamped(margin) if margin is not None else None),
                        raising=False)
    monkeypatch.setattr(store, "balance_safety_series",
                        lambda c, t, *, as_of: (_stamped(ndte) if ndte is not None else None),
                        raising=False)
    monkeypatch.setattr(store, "shares_yoy",
                        lambda c, t, *, as_of: (_stamped(shares) if shares is not None else None),
                        raising=False)

    class _OE:
        def usable(self): return oe_json is not None
    monkeypatch.setattr(store, "owner_fcf_ttm",
                        lambda c, t, *, as_of: (object() if False else None), raising=False)


def test_baseline_full(tmp_db, fixed_clock, monkeypatch):
    from agentcy import backfill
    _stub_store(monkeypatch,
                rev=[("2026-06-30", 14.2)], margin=[("2026-06-30", 30.0)],
                ndte=[("2026-06-30", 1.5)], shares=1.2)
    b = backfill.compute_baseline(tmp_db, "ADYEN", as_of=AS_OF)
    assert b.revenue_yoy == 14.2 and b.owner_fcf_margin == 30.0
    assert b.net_debt_ebitda == 1.5 and b.shares_yoy == 1.2
    assert b.owner_earnings_json == "{}"


def test_baseline_thin_legs_are_none(tmp_db, fixed_clock, monkeypatch):
    from agentcy import backfill
    _stub_store(monkeypatch, rev=None, margin=[("2026-06-30", 25.0)], ndte=None, shares=None)
    b = backfill.compute_baseline(tmp_db, "ADYEN", as_of=AS_OF)
    assert b.revenue_yoy is None and b.owner_fcf_margin == 25.0
    assert b.net_debt_ebitda is None and b.shares_yoy is None
```

Note: `revenue_yoy_series` / `margin_series` / `balance_safety_series` return a `Stamped`
whose `.value` is a `[(period_end, value), ...]` list; `shares_yoy` returns a `Stamped` whose
`.value` is a scalar percent. `compute_baseline` takes the LAST tuple's value for the series,
the scalar for shares.

**Run (expect fail):**

```
uv run pytest -q tests/test_backfill.py -k baseline
```

Expected: `AttributeError: module 'agentcy.backfill' has no attribute 'compute_baseline'`.

**Minimal implementation (append to `agentcy/backfill.py`):**

```python
from agentcy.fetch import store


@dataclass(frozen=True)
class Baseline:
    yf_ticker: str
    revenue_yoy: float | None
    owner_fcf_margin: float | None
    net_debt_ebitda: float | None
    shares_yoy: float | None
    owner_earnings_json: str


def _last_series_value(stamped) -> float | None:
    """Last (period_end, value) value of a usable series Stamped, else None."""
    if stamped is None or not stamped.usable():
        return None
    series = stamped.value
    if not series:
        return None
    return series[-1][1]


def _scalar_value(stamped) -> float | None:
    if stamped is None or not stamped.usable():
        return None
    return stamped.value


def compute_baseline(conn, yf_ticker, *, as_of) -> Baseline:
    """The invested-moment fundamentals anchor. Every leg is None-safe: a leg with no
    computable/usable series is None (skipped / BOOTSTRAPPING downstream, never faked)."""
    rev = _last_series_value(store.revenue_yoy_series(conn, yf_ticker, as_of=as_of))
    margin = _last_series_value(store.margin_series(conn, yf_ticker, as_of=as_of))
    ndte = _last_series_value(store.balance_safety_series(conn, yf_ticker, as_of=as_of))
    shares = _scalar_value(store.shares_yoy(conn, yf_ticker, as_of=as_of))
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    oe_json = "{}"
    if oe is not None and oe.usable():
        import json
        v = oe.value
        oe_json = json.dumps({
            "fcf_ttm": v.fcf_ttm, "sbc_ttm": v.sbc_ttm, "owner_fcf_ttm": v.owner_fcf_ttm,
            "owner_fcf_per_share_ttm": v.owner_fcf_per_share_ttm,
            "owner_fcf_margin_ttm": v.owner_fcf_margin_ttm,
            "periods_used": list(v.periods_used)})
    return Baseline(yf_ticker=yf_ticker, revenue_yoy=rev, owner_fcf_margin=margin,
                    net_debt_ebitda=ndte, shares_yoy=shares, owner_earnings_json=oe_json)
```

**Run (expect pass):**

```
uv run pytest -q tests/test_backfill.py -k baseline
```

Expected: both baseline tests pass.

**Commit:**

```
feat(thesis): None-safe fundamentals baseline for backfill anchor

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 3 - Auto-derive the four Moderate triggers

Add `derive_triggers(baseline) -> list[register.TriggerSpec]` with the EXACT formulas from the
design. A leg whose baseline value is None is OMITTED (not faked). The `margin_erosion` leg
carries the moat link so BUF-4 is satisfiable.

Exact formulas (all thresholds are the numeric `threshold`, comparator per the design):
- **growth_floor**        - metric `revenue_yoy`,       comparator `>`, threshold
  `baseline.revenue_yoy - 10.0`  (percent points; "> baseline_revenue_yoy - 10pp")
- **margin_erosion**      - metric `owner_fcf_margin`,  comparator `>`, threshold
  `baseline.owner_fcf_margin * 0.75`  ("> baseline_margin x 0.75"); `moat_link="switching_costs"`
- **balance_sheet_safety**- metric `net_debt_ebitda`,  comparator `<`, threshold
  `min(baseline.net_debt_ebitda + 1.0, 4.0)`  ("< min(baseline_ndte + 1.0, 4.0)")
- **dilution**            - metric `shares_yoy`,        comparator `<`, threshold `5.0`
  ("< 5%/yr"); NOTE this threshold is a fixed constant, NOT baseline-relative

Persistence per the Gate/type defaults (`gate._default_persistence`): `dilution` -> `"ttm"`,
the three series triggers -> `"2_consecutive_quarters"`. (These feed
`register._DATA_SOURCE`/`_CADENCE` unchanged: all four are `weekly` cadence, `automated`.)

Each `TriggerSpec` carries a plain-English `statement` (deterministic, owner edits at ratify).

**Files:**
- EDIT `agentcy/backfill.py`
- EDIT `tests/test_backfill.py`

**Failing test (append to `tests/test_backfill.py`):**

```python
def _baseline(**kw):
    from agentcy import backfill
    base = dict(yf_ticker="ADYEN", revenue_yoy=14.2, owner_fcf_margin=30.0,
                net_debt_ebitda=1.5, shares_yoy=1.2, owner_earnings_json="{}")
    base.update(kw)
    return backfill.Baseline(**base)


def test_derive_four_triggers_exact_thresholds():
    from agentcy import backfill
    specs = backfill.derive_triggers(_baseline())
    by_type = {s.type: s for s in specs}
    assert set(by_type) == {"growth_floor", "margin_erosion",
                            "balance_sheet_safety", "dilution"}
    assert by_type["growth_floor"].comparator == ">"
    assert round(by_type["growth_floor"].threshold, 4) == round(14.2 - 10.0, 4)
    assert by_type["margin_erosion"].comparator == ">"
    assert round(by_type["margin_erosion"].threshold, 4) == round(30.0 * 0.75, 4)
    assert by_type["margin_erosion"].moat_link == "switching_costs"
    assert by_type["balance_sheet_safety"].comparator == "<"
    assert by_type["balance_sheet_safety"].threshold == min(1.5 + 1.0, 4.0)
    assert by_type["dilution"].comparator == "<" and by_type["dilution"].threshold == 5.0
    assert by_type["dilution"].persistence == "ttm"


def test_balance_ndte_caps_at_four():
    from agentcy import backfill
    specs = backfill.derive_triggers(_baseline(net_debt_ebitda=8.0))
    ndte = next(s for s in specs if s.type == "balance_sheet_safety")
    assert ndte.threshold == 4.0   # min(8.0 + 1.0, 4.0)


def test_derive_omits_uncomputable_legs():
    from agentcy import backfill
    specs = backfill.derive_triggers(_baseline(revenue_yoy=None, shares_yoy=None))
    types = {s.type for s in specs}
    assert types == {"margin_erosion", "balance_sheet_safety"}   # rev + dilution omitted
    assert any(s.moat_link for s in specs)   # BUF-4 still satisfiable
```

**Run (expect fail):**

```
uv run pytest -q tests/test_backfill.py -k "derive or ndte"
```

Expected: `AttributeError: module 'agentcy.backfill' has no attribute 'derive_triggers'`.

**Minimal implementation (append to `agentcy/backfill.py`):**

```python
_PLACEHOLDER_MOAT = "switching_costs"   # links margin_erosion for BUF-4 until Part B


def derive_triggers(baseline: Baseline) -> list[register.TriggerSpec]:
    """The four Moderate invalidation triggers, each relative to the baseline (design section
    'Auto-derive'). A leg with no computable baseline value is OMITTED (not faked). Persistence
    matches the Gate type defaults; data_source/cadence are resolved by register.commit_trigger."""
    specs: list[register.TriggerSpec] = []
    if baseline.revenue_yoy is not None:
        floor = baseline.revenue_yoy - 10.0
        specs.append(register.TriggerSpec(
            type="growth_floor",
            statement=(f"If revenue YoY falls to or below {floor:.1f}% "
                       f"(more than 10pp under the {baseline.revenue_yoy:.1f}% baseline), "
                       "the growth story that anchors this holding is gone."),
            metric="revenue_yoy", comparator=">", threshold=floor, moat_link=None,
            persistence="2_consecutive_quarters"))
    if baseline.owner_fcf_margin is not None:
        floor = baseline.owner_fcf_margin * 0.75
        specs.append(register.TriggerSpec(
            type="margin_erosion",
            statement=(f"If owner-FCF margin TTM falls to or below {floor:.1f}% "
                       f"(a quarter below the {baseline.owner_fcf_margin:.1f}% baseline), "
                       "the moat is leaking."),
            metric="owner_fcf_margin", comparator=">", threshold=floor,
            moat_link=_PLACEHOLDER_MOAT, persistence="2_consecutive_quarters"))
    if baseline.net_debt_ebitda is not None:
        ceiling = min(baseline.net_debt_ebitda + 1.0, 4.0)
        specs.append(register.TriggerSpec(
            type="balance_sheet_safety",
            statement=(f"If net-debt/EBITDA rises to or above {ceiling:.1f}x, "
                       "the balance sheet is no longer the one I underwrote."),
            metric="net_debt_ebitda", comparator="<", threshold=ceiling, moat_link=None,
            persistence="2_consecutive_quarters"))
    if baseline.shares_yoy is not None:
        specs.append(register.TriggerSpec(
            type="dilution",
            statement=("If the share count grows 5%/yr or more, dilution is eating the "
                       "per-share compounding."),
            metric="shares_yoy", comparator="<", threshold=5.0, moat_link=None,
            persistence="ttm"))
    return specs
```

**Run (expect pass):**

```
uv run pytest -q tests/test_backfill.py -k "derive or ndte"
```

Expected: the three trigger tests pass.

**Commit:**

```
feat(thesis): auto-derive the four Moderate backfill triggers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 4 - Create the backfill DRAFT thesis

Add `create_backfill_draft(conn, held, baseline, *, journal_ref, clock) -> str | None`. It
assembles the `ThesisFields` with the documented DRAFT placeholders (Plan notes), the
auto-derived triggers, and calls `register.create_thesis(origin='backfill', ...)`. The thesis
stays `draft` (NOT monitored). Returns the thesis_id, or None when fewer than 2 triggers /
no moat-linked trigger could be derived (reported BOOTSTRAPPING; never a malformed thesis).

`value_at_purchase` is NOT written into the thesis (create_thesis pins it to None for v1;
the entry price is record-keeping only). We compute `entry = invested_eur / quantity` only for
the returned draft record + ratify prompt (Task 5), never for advice.

**Files:**
- EDIT `agentcy/backfill.py`
- EDIT `tests/test_backfill.py`

**Failing test (append to `tests/test_backfill.py`):**

```python
def test_create_backfill_draft_origin_and_status(tmp_db, fixed_clock):
    from agentcy import backfill
    from agentcy import journal
    from agentcy.journal import EntryIn
    conn = tmp_db
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    held = backfill.HeldWithoutThesis(symbol="ADYEN", yf_ticker="ADYEN",
                                      instrument_type="stock", quantity=5.0,
                                      opened_at="2024-01-15T00:00:00Z", invested_eur=3000.0)
    baseline = backfill.Baseline(yf_ticker="ADYEN", revenue_yoy=14.2, owner_fcf_margin=30.0,
                                 net_debt_ebitda=1.5, shares_yoy=1.2, owner_earnings_json="{}")
    tid = backfill.create_backfill_draft(conn, held, baseline, journal_ref=je, clock=fixed_clock)
    assert tid == "TH-ADYEN-001"
    assert db.fetch_thesis(conn, tid)["origin"] == "backfill"
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "draft"   # NOT monitored
    assert len(db.fetch_armed_triggers(conn, tid)) == 4
    tv = db.fetch_current_thesis_version(conn, tid)
    assert tv["value_at_purchase"] is None                  # cost basis quarantined at v1
    assert "(draft - pending ratification)" in tv["business_model_2s"]


def test_create_backfill_draft_bootstrapping_when_no_triggers(tmp_db, fixed_clock):
    from agentcy import backfill, journal
    from agentcy.journal import EntryIn
    conn = tmp_db
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    held = backfill.HeldWithoutThesis(symbol="THIN", yf_ticker="THIN", instrument_type="stock",
                                      quantity=1.0, opened_at=None, invested_eur=None)
    # only a growth_floor leg computable -> 1 trigger, no moat link -> cannot form a thesis
    baseline = backfill.Baseline(yf_ticker="THIN", revenue_yoy=14.2, owner_fcf_margin=None,
                                 net_debt_ebitda=None, shares_yoy=None, owner_earnings_json="{}")
    tid = backfill.create_backfill_draft(conn, held, baseline, journal_ref=je, clock=fixed_clock)
    assert tid is None
    assert db.fetch_theses(conn) == []
```

**Run (expect fail):**

```
uv run pytest -q tests/test_backfill.py -k "create_backfill"
```

Expected: `AttributeError: ... has no attribute 'create_backfill_draft'`.

**Minimal implementation (append to `agentcy/backfill.py`):**

```python
from agentcy.register import ThesisFields

# Documented DRAFT placeholders for the NOT-NULL qualitative fields (Plan notes). The thesis
# stays draft (UNmonitored) until the owner ratifies via Telegram; these are placeholders, not
# fabricated convictions.
_DRAFT_TEXT = "(draft - pending ratification)"


def _draft_fields(baseline: Baseline) -> ThesisFields:
    return ThesisFields(
        business_model_2s=_DRAFT_TEXT,
        moat_types=(_PLACEHOLDER_MOAT,),
        moat_evidence=_DRAFT_TEXT,
        owner_earnings_json=baseline.owner_earnings_json,
        owner_earnings_narrative=_DRAFT_TEXT,
        value_at_purchase=None,                 # record-keeping only; create_thesis pins v1 None
        fair_band_low=0.0, fair_band_high=0.0,  # no price verdict for backfill (BUF-12)
        denominator_note="P/owner-FCF",
        conviction="medium", mgmt_trust="neutral", mgmt_trust_note=None,
        circle_fit="edge", circle_fit_note=None,
        ten_year_statement=_DRAFT_TEXT,
        status_buy_flag=False, status_buy_note=None)


def _triggers_form_a_thesis(specs) -> bool:
    """register._validate_triggers requires 2-5 triggers with >=1 moat_link (BUF-4)."""
    return len(specs) >= 2 and any(s.moat_link for s in specs)


def create_backfill_draft(conn, held: HeldWithoutThesis, baseline: Baseline, *,
                          journal_ref: int, clock: Clock) -> str | None:
    """Create the origin='backfill' DRAFT thesis anchored to the invested moment. Returns the
    thesis_id, or None when too few triggers could be derived (reported BOOTSTRAPPING; never a
    malformed thesis). value_at_purchase stays None at v1 - cost basis is record-keeping only
    and never enters positions_advice (invariant 4)."""
    specs = derive_triggers(baseline)
    if not _triggers_form_a_thesis(specs):
        return None
    return register.create_thesis(conn, ticker=held.symbol, origin="backfill",
                                  fields=_draft_fields(baseline), triggers=specs,
                                  journal_ref=journal_ref, clock=clock)


def entry_price(held: HeldWithoutThesis) -> float | None:
    """RECORD-KEEPING ONLY: invested_eur / quantity, for the ratify prompt / letter. This value
    is NEVER written to positions_advice or used by any invalidation trigger (the triggers fire
    on the business deteriorating, never on price-vs-entry)."""
    if held.invested_eur is None or not held.quantity:
        return None
    return held.invested_eur / held.quantity
```

**Run (expect pass):**

```
uv run pytest -q tests/test_backfill.py -k "create_backfill"
```

Expected: both tests pass.

**Commit:**

```
feat(register): create origin=backfill DRAFT thesis with placeholders

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 5 - The Telegram ratification ask (approve/edit -> intact/draft)

Add `mint_ratify_ask(conn, thesis_id, held, *, clock) -> asks.Ask` in `backfill.py` and the
`note.approve` / `note.edit` consequence branches in `asks.apply_consequence`.

- The ask is minted `kind="N"`, `options=["approve","edit"]`, `expects_freetext=True`,
  `thesis_ref=<thesis_id>`. `_consequence("N","approve")` yields `"note.approve"`,
  `_consequence("N","edit")` yields `"note.edit"` (existing `_consequence` prefix map for N).
- On APPROVE: if `thesis_ref` names a `draft` `origin='backfill'` thesis, journal a
  `config_or_designation[config_change]` entry, then `register.activate(...)` (draft -> intact),
  which arms the triggers for the Watchdog. Returns an owner-facing note.
- On EDIT: journal the owner's edit text as a note (thesis stays `draft`); returns a note. The
  edit text feeds the Part-B drafting round; no field is mutated deterministically here.

**Files:**
- EDIT `agentcy/asks.py` (add two branches + two helpers)
- EDIT `agentcy/backfill.py` (add `mint_ratify_ask`)
- EDIT `tests/test_backfill.py`

**Failing test (append to `tests/test_backfill.py`):**

```python
def _seed_draft(conn, fixed_clock):
    from agentcy import backfill, journal
    from agentcy.journal import EntryIn
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    held = backfill.HeldWithoutThesis(symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock",
                                      quantity=5.0, opened_at="2024-01-15T00:00:00Z",
                                      invested_eur=3000.0)
    baseline = backfill.Baseline(yf_ticker="ADYEN", revenue_yoy=14.2, owner_fcf_margin=30.0,
                                 net_debt_ebitda=1.5, shares_yoy=1.2, owner_earnings_json="{}")
    tid = backfill.create_backfill_draft(conn, held, baseline, journal_ref=je, clock=fixed_clock)
    return tid, held


def test_ratify_approve_activates_and_arms(tmp_db, fixed_clock):
    from agentcy import asks, backfill
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    assert ask.kind == "N" and ask.options == ("approve", "edit") and ask.thesis_ref == tid
    out = asks.answer(conn, ask.ask_id, choice="approve", clock=fixed_clock)
    assert out.consequence == "note.approve"
    asks.apply_consequence(conn, out, clock=fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "intact"   # monitored now
    assert len(db.fetch_armed_triggers(conn, tid)) == 4


def test_ratify_edit_keeps_draft(tmp_db, fixed_clock):
    from agentcy import asks, backfill
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    out = asks.answer(conn, ask.ask_id, choice="edit",
                      text="conviction should be high; add an owner-attested CEO trigger",
                      clock=fixed_clock)
    assert out.consequence == "note.edit"
    asks.apply_consequence(conn, out, clock=fixed_clock, evidence=out.ask.answer.get("text"))
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "draft"   # still not monitored
```

**Run (expect fail):**

```
uv run pytest -q tests/test_backfill.py -k "ratify"
```

Expected: `AttributeError: ... 'mint_ratify_ask'` first; after that, the approve test fails
because `apply_consequence` does not yet handle `note.approve`.

**Minimal implementation:**

1. Append to `agentcy/backfill.py`:

```python
from agentcy import asks as _asks

_RATIFY_PROMPT = (
    "Ratify the backfill thesis for {sym} ({tid}). I anchored it to your invested moment "
    "(opened {opened}, entry approx {entry}) and auto-derived {n} Moderate invalidation "
    "triggers from the fundamentals baseline. Tap APPROVE to make it intact and monitored, or "
    "reply with your edits (conviction, triggers, rationale) to keep drafting. Cost basis is "
    "record-keeping only and plays no part in the triggers.")


def mint_ratify_ask(conn, thesis_id: str, held: HeldWithoutThesis, *, clock: Clock) -> "_asks.Ask":
    """One ratification ask per drafted backfill thesis: approve -> intact + armed; edit reply
    -> stays draft (records the owner's text for the drafting round)."""
    n_triggers = len(db.fetch_armed_triggers(conn, thesis_id))
    entry = entry_price(held)
    prompt = _RATIFY_PROMPT.format(
        sym=held.symbol, tid=thesis_id, opened=(held.opened_at or "unknown"),
        entry=(f"{entry:.2f}" if entry is not None else "n/a"), n=n_triggers)
    return _asks.mint(conn, kind="N", prompt=prompt, options=["approve", "edit"],
                      expects_freetext=True, thesis_ref=thesis_id, clock=clock)
```

2. In `agentcy/asks.py`, add the dispatch branches inside `apply_consequence` (BEFORE the
   final `return None`, alongside the existing `recon.` branch):

```python
    if cons == "note.approve":
        return _apply_backfill_approve(conn, outcome.ask, clock=clock, run_id=run_id)
    if cons == "note.edit":
        return _apply_backfill_edit(conn, outcome.ask, clock=clock, evidence=evidence,
                                    run_id=run_id)
```

3. Add the two helpers to `agentcy/asks.py` (function-level imports, mirroring the existing
   `_apply_reconciliation` idiom):

```python
def _apply_backfill_approve(conn, ask: Ask, *, clock: Clock, run_id: int | None) -> str | None:
    """Ratify a backfill DRAFT thesis: draft -> intact (arms the auto-derived triggers for the
    Watchdog). A no-op unless thesis_ref names a draft origin='backfill' thesis (so an ordinary
    N-note approve never activates anything)."""
    from agentcy import journal, register
    from agentcy.journal import EntryIn
    thesis_id = ask.thesis_ref
    if thesis_id is None:
        return None
    th = db.fetch_thesis(conn, thesis_id)
    st = db.fetch_current_thesis_status(conn, thesis_id)
    if th is None or th["origin"] != "backfill" or st is None or st["status"] != "draft":
        return None
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        ticker=th["ticker"], thesis_ref=thesis_id,
        system_recommendation="backfill thesis ratified -> intact + triggers armed",
        owner_action="followed",
        reasoning_at_the_moment="Owner ratified the backfill thesis (FR9 owner judgment).",
        inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"), clock=clock)
    register.activate(conn, thesis_id, cause="owner ratified backfill thesis", clock=clock)
    return f"{th['ticker']}: backfill thesis {thesis_id} ratified. Intact and monitored."


def _apply_backfill_edit(conn, ask: Ask, *, clock: Clock, evidence: str | None,
                         run_id: int | None) -> str | None:
    """Owner replied edits instead of approving: journal the text verbatim; the thesis stays
    draft (UNmonitored). The text feeds the Part-B drafting round; no field is mutated here."""
    from agentcy import journal
    from agentcy.journal import EntryIn
    thesis_id = ask.thesis_ref
    th = db.fetch_thesis(conn, thesis_id) if thesis_id else None
    if th is None or th["origin"] != "backfill":
        return None
    text = (evidence or (ask.answer or {}).get("text") or "").strip()
    journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        ticker=th["ticker"], thesis_ref=thesis_id,
        reasoning_at_the_moment=(text or "Owner requested edits to the backfill draft."),
        owner_action="no_action", inputs_ref=run_id, ask_ref=ask.ask_id, actor="owner"),
        clock=clock)
    return (f"{th['ticker']}: edits recorded; the backfill thesis stays draft (unmonitored) "
            "until you approve.")
```

**Run (expect pass):**

```
uv run pytest -q tests/test_backfill.py -k "ratify"
uv run pytest -q tests/test_asks.py
```

Expected: the ratify tests pass; `test_asks.py` stays green (the new branches only fire on
`note.approve`/`note.edit` with a backfill `thesis_ref`, so ordinary N-notes are untouched).

**Commit:**

```
feat(register): Telegram ratification ask for backfill theses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 6 - CLI/job `agentcy thesis backfill [--ticker T]`

Add `run_backfill(conn, *, ticker=None, clock, as_of) -> list[BackfillResult]` in `backfill.py`
(orchestrates detect -> baseline -> triggers -> draft -> ratify ask, for one or all thesis-less
holdings; idempotent), and wire it as `agentcy thesis backfill [--ticker T]` in `cli.py`.

Idempotence: a holding that already has a DRAFT (or any live) backfill thesis is skipped
(`detect_thesis_less` already excludes any live thesis, so a re-run does not double-create).

**Files:**
- EDIT `agentcy/backfill.py` (add `run_backfill` + `BackfillResult`)
- EDIT `agentcy/cli.py` (add the `backfill` subparser + `_cmd_thesis` branch)
- EDIT `tests/test_backfill.py`

**Failing test (append to `tests/test_backfill.py`):**

```python
def _stub_full_baseline(monkeypatch):
    _stub_store(monkeypatch, rev=[("2026-06-30", 14.2)], margin=[("2026-06-30", 30.0)],
                ndte=[("2026-06-30", 1.5)], shares=1.2)


def test_run_backfill_creates_draft_and_ratify_ask(tmp_db, fixed_clock, monkeypatch):
    from agentcy import asks, backfill
    conn = _seed_two_holdings(tmp_db, fixed_clock)   # ADYEN has no thesis
    _stub_full_baseline(monkeypatch)
    results = backfill.run_backfill(conn, ticker=None, clock=fixed_clock, as_of=AS_OF)
    assert [r.symbol for r in results] == ["ADYEN"]
    r = results[0]
    assert r.thesis_id == "TH-ADYEN-001" and r.ratify_ask_id is not None
    assert db.fetch_current_thesis_status(conn, r.thesis_id)["status"] == "draft"
    assert [a.thesis_ref for a in asks.open_asks(conn, kind="N")] == ["TH-ADYEN-001"]


def test_run_backfill_is_idempotent(tmp_db, fixed_clock, monkeypatch):
    from agentcy import backfill
    conn = _seed_two_holdings(tmp_db, fixed_clock)
    _stub_full_baseline(monkeypatch)
    backfill.run_backfill(conn, ticker=None, clock=fixed_clock, as_of=AS_OF)
    again = backfill.run_backfill(conn, ticker=None, clock=fixed_clock, as_of=AS_OF)
    assert again == []                       # ADYEN now has a draft thesis -> not re-detected
    assert len(db.fetch_theses(conn)) == 2   # NVDA (seeded) + ADYEN (one draft), no duplicate


def test_run_backfill_ticker_filter(tmp_db, fixed_clock, monkeypatch):
    from agentcy import backfill
    conn = _seed_two_holdings(tmp_db, fixed_clock)
    _stub_full_baseline(monkeypatch)
    results = backfill.run_backfill(conn, ticker="MISSING", clock=fixed_clock, as_of=AS_OF)
    assert results == []                     # no thesis-less holding named MISSING
```

**Run (expect fail):**

```
uv run pytest -q tests/test_backfill.py -k "run_backfill"
```

Expected: `AttributeError: ... 'run_backfill'`.

**Minimal implementation:**

1. Append to `agentcy/backfill.py`:

```python
from agentcy import journal as _journal
from agentcy.journal import EntryIn as _EntryIn


@dataclass(frozen=True)
class BackfillResult:
    symbol: str
    thesis_id: str | None
    ratify_ask_id: str | None
    note: str


def run_backfill(conn, *, ticker: str | None, clock: Clock, as_of) -> list[BackfillResult]:
    """detect -> baseline -> triggers -> draft thesis -> ratify ask, for one or all thesis-less
    holdings. Idempotent: a holding with a live/draft thesis is not re-detected. A holding whose
    baseline yields too few triggers is reported BOOTSTRAPPING (no thesis, no ask)."""
    held = detect_thesis_less(conn, as_of=as_of)
    if ticker is not None:
        held = [h for h in held if h.symbol == ticker]
    results: list[BackfillResult] = []
    for h in held:
        yf = h.yf_ticker or h.symbol
        baseline = compute_baseline(conn, yf, as_of=as_of)
        je = _journal.append(conn, _EntryIn(
            decision_type="config_or_designation", decision_subtype="config_change",
            ticker=h.symbol,
            reasoning_at_the_moment=f"Backfill onboarding started for held position {h.symbol}.",
            owner_action="no_action", actor="owner"), clock=clock)
        tid = create_backfill_draft(conn, h, baseline, journal_ref=je, clock=clock)
        if tid is None:
            results.append(BackfillResult(symbol=h.symbol, thesis_id=None, ratify_ask_id=None,
                                          note="BOOTSTRAPPING: too few triggers derivable"))
            continue
        ask = mint_ratify_ask(conn, tid, h, clock=clock)
        results.append(BackfillResult(symbol=h.symbol, thesis_id=tid, ratify_ask_id=ask.ask_id,
                                      note="draft created; ratification ask minted"))
    conn.commit()
    return results
```

2. In `agentcy/cli.py`, add the subparser under the existing `th` (thesis) parser (after the
   `trev` block, before `return p`):

```python
    tbf = tsub.add_parser("backfill", help="onboard held positions that have no thesis (C.6)")
    tbf.add_argument("--ticker", default=None, help="onboard only this held symbol")
    tbf.set_defaults(handler="thesis")
```

3. In `_cmd_thesis`, add a `backfill` branch at the TOP (before the `show`/`revise` branches):

```python
    if args.thesis_cmd == "backfill":
        from agentcy import backfill
        clock = _clock()
        results = backfill.run_backfill(conn, ticker=args.ticker, clock=clock,
                                        as_of=clock.now())
        if not results:
            print("no thesis-less holdings to onboard.")
            return 0
        for r in results:
            tid = r.thesis_id or "-"
            print(f"{r.symbol}: {tid}  {r.note}"
                  + (f"  ratify: {r.ratify_ask_id}" if r.ratify_ask_id else ""))
        return 0
```

**Run (expect pass):**

```
uv run pytest -q tests/test_backfill.py -k "run_backfill"
uv run pytest -q tests/test_cli.py
```

Expected: the three run_backfill tests pass; `test_cli.py` stays green.

**Commit:**

```
feat(thesis): agentcy thesis backfill CLI/job (idempotent)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 7 - Weekly letter: report drafts honestly + confirm intact pickup

Change `weekly.revalidation_lines` so a thesis-less-or-DRAFT holding is reported as "awaiting
thesis ratification" instead of being silently skipped, and add a test proving an INTACT
backfill thesis is picked up by `run_trigger_tests` with NO Watchdog change.

Current `revalidation_lines` does `tid = live_thesis_for(...); if tid is None: continue` -
that silent skip is the bug. A DRAFT thesis IS returned by `live_thesis_for` (it is
non-retired), and the existing code already prints `st['status']` (which is `draft`) - so the
DRAFT case is already visible. The change is the THESIS-LESS case: when `tid is None` and the
holding is non-cash and non-outside-framework, emit an "awaiting thesis ratification" line.

**Files:**
- EDIT `agentcy/jobs/weekly.py` (`revalidation_lines`)
- CREATE `tests/test_backfill_weekly.py`

**Failing test (`tests/test_backfill_weekly.py`):**

```python
"""tests/test_backfill_weekly.py - weekly letter reports drafts honestly; Watchdog picks up
an intact backfill thesis with no Watchdog change."""
from datetime import datetime, timezone

from agentcy import db

SAT = datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc)


def test_thesis_less_holding_reported_not_skipped(tmp_db, fixed_clock):
    from agentcy import journal
    from agentcy.jobs import weekly
    from agentcy.journal import EntryIn
    conn = tmp_db
    now = db.to_iso(fixed_clock.now())
    je = journal.append(conn, EntryIn(decision_type="config_or_designation",
                                      decision_subtype="config_change",
                                      reasoning_at_the_moment="seed", actor="owner"),
                        clock=fixed_clock)
    snap_id = db.append_snapshot(conn, as_of="2026-07-06T20:00:00Z", source="api_pull",
                                 cash_balance_eur=1000.0, created_at=now)
    db.append_positions(conn, snap_id, [dict(
        symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock", quantity=5.0,
        avg_open_price=None, native_currency="EUR", mv_native=4200.0, mv_eur=4200.0,
        weight=1.0, leverage=1.0)])
    conn.commit()
    lines = weekly.revalidation_lines(conn, as_of=SAT)
    assert any("ADYEN" in ln and "awaiting thesis ratification" in ln for ln in lines)


def test_intact_backfill_thesis_fires_via_existing_watchdog(tmp_db, fixed_clock, monkeypatch):
    """A ratified (intact) backfill thesis with a broken auto-trigger fires an alert through
    weekly.run_trigger_tests with NO Watchdog change (seeded, offline)."""
    from agentcy import asks, backfill, journal, runlog
    from agentcy.jobs import weekly
    from agentcy.journal import EntryIn
    from agentcy.fetch import store
    from agentcy.freshness import Stamped, DataState
    conn = tmp_db
    now = db.to_iso(fixed_clock.now())
    je = journal.append(conn, EntryIn(decision_type="config_or_designation",
                                      decision_subtype="config_change",
                                      reasoning_at_the_moment="seed", actor="owner"),
                        clock=fixed_clock)
    snap_id = db.append_snapshot(conn, as_of="2026-07-06T20:00:00Z", source="api_pull",
                                 cash_balance_eur=1000.0, created_at=now)
    db.append_positions(conn, snap_id, [dict(
        symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock", quantity=5.0,
        avg_open_price=None, native_currency="EUR", mv_native=4200.0, mv_eur=4200.0,
        weight=1.0, leverage=1.0)])
    db.append_position_details(conn, snap_id, [dict(
        symbol="ADYEN", opened_at="2024-01-15T00:00:00Z", invested_native=3000.0,
        invested_eur=3000.0, unrealized_pnl_native=1200.0, unrealized_pnl_pct=40.0,
        current_rate=840.0, direction="buy", lot_count=2, raw_json="{}")])
    conn.commit()

    # baseline: margin baseline 30.0 -> margin_erosion floor 22.5 (comparator '>')
    def _stamped(v, state="fresh"):
        return Stamped(value=v, fetched_at=SAT, state=DataState(state), note=None)
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: _stamped([("2026-06-30", 14.2)]), raising=False)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: _stamped([("2026-06-30", 30.0)]), raising=False)
    monkeypatch.setattr(store, "balance_safety_series",
                        lambda c, t, *, as_of: _stamped([("2026-06-30", 1.5)]), raising=False)
    monkeypatch.setattr(store, "shares_yoy",
                        lambda c, t, *, as_of: _stamped(1.2), raising=False)
    monkeypatch.setattr(store, "owner_fcf_ttm", lambda c, t, *, as_of: None, raising=False)

    # onboard + ratify -> intact
    results = backfill.run_backfill(conn, ticker="ADYEN", clock=fixed_clock, as_of=SAT)
    tid = results[0].thesis_id
    ask_id = results[0].ratify_ask_id
    out = asks.answer(conn, ask_id, choice="approve", clock=fixed_clock)
    asks.apply_consequence(conn, out, clock=fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "intact"

    # now BREAK the margin_erosion trigger: margin TTM collapses to 10% (< floor 22.5, '>' floor)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: _stamped([("2026-03-31", 10.0), ("2026-06-30", 9.0)]),
                        raising=False)
    handle = runlog.start(conn, run_type="weekly", scheduled_for="2026-07-11", clock=fixed_clock)
    res = weekly.run_trigger_tests(conn, run_id=handle.run_id, clock=fixed_clock)
    assert res["fired_alert_ids"]                                   # an alert fired
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "under_review"
```

Note: the `runlog.start(...)` call must match the real `runlog` API - if the signature differs,
use the same run-start idiom `tests/test_jobs_weekly_triggers.py` uses (open the test file and
copy its run-handle seed exactly). The load-bearing assertions are `fired_alert_ids` non-empty
and the thesis going `under_review` - use whatever run-handle seed the weekly-triggers tests use.

**Run (expect fail):**

```
uv run pytest -q tests/test_backfill_weekly.py
```

Expected: `test_thesis_less_holding_reported_not_skipped` fails (no "awaiting thesis
ratification" line yet).

**Minimal implementation (`agentcy/jobs/weekly.py`, `revalidation_lines`):**

Replace the `if tid is None: continue` skip with an honest line. The updated function:

```python
def revalidation_lines(conn, *, as_of) -> tuple[str, ...]:
    """D.2 check 3: per holding one line - status, version, headroom scorecard. A non-cash
    holding with no live thesis (or a DRAFT one) is reported as awaiting thesis ratification,
    never silently skipped (backfill onboarding)."""
    snap = db.fetch_latest_snapshot(conn)
    out = []
    for p in (mirror.advice_positions(conn, snap["snapshot_id"]) if snap else []):
        if p.instrument_type == "cash":
            continue
        tid = register.live_thesis_for(conn, p.symbol)
        if tid is None:
            fs = mirror.framework_status(conn, p.symbol, as_of=as_of)
            if fs == "outside_framework":
                out.append(f"{p.symbol} - outside framework (no thesis by design)")
            else:
                out.append(f"{p.symbol} - awaiting thesis ratification "
                           "(no live thesis; run `agentcy thesis backfill`)")
            continue
        st = db.fetch_current_thesis_status(conn, tid)
        tv = db.fetch_current_thesis_version(conn, tid)
        rows = triggers.headroom_table(conn, tid, as_of=as_of)
        score = ", ".join(f"T{r.trigger_id}:{r.result}"
                          + (f" (headroom {r.headroom:+.1f})" if r.headroom is not None else "")
                          for r in rows) or "no armed triggers"
        out.append(f"{p.symbol} - {st['status'] if st else 'draft'} (v{tv['version']}) . {score}")
    return tuple(out)
```

Keep the existing ASCII glyphs the file already uses (the current file uses an em-dash and a
middot). Match the file's existing style - if it uses `-` and `.` keep those; if the golden
tests key on the exact glyph, run the render-weekly goldens and, if they break, revert the
glyphs to the file's originals (`—` / `·`) while keeping the NEW thesis-less line.
The load-bearing change is the thesis-less branch, not the glyph.

**Run (expect pass):**

```
uv run pytest -q tests/test_backfill_weekly.py
uv run pytest -q tests/test_jobs_weekly_context.py tests/test_render_weekly.py
```

Expected: the new tests pass; the weekly-context and render-weekly suites stay green (if a
golden keys on the revalidation glyph, restore the original glyph per the note above and re-run).

**Commit:**

```
feat(thesis): report thesis-less/draft holdings in the weekly letter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Task 8 - End-to-end + structural guards

Add the structural tests: cost basis never reaches `positions_advice`, no new pip dependency,
no LLM import in `backfill.py`. (The end-to-end broken-trigger-fires path is already proven in
Task 7's `test_intact_backfill_thesis_fires_via_existing_watchdog`; this task adds the
quarantine + structural asserts.)

**Files:**
- EDIT `tests/test_backfill.py`

**Failing test (append to `tests/test_backfill.py`):**

```python
def test_cost_basis_never_in_positions_advice(tmp_db, fixed_clock, monkeypatch):
    from agentcy import backfill
    conn = _seed_two_holdings(tmp_db, fixed_clock)
    _stub_full_baseline(monkeypatch)
    backfill.run_backfill(conn, ticker="ADYEN", clock=fixed_clock, as_of=AS_OF)
    snap = db.fetch_latest_snapshot(conn)
    rows = db.fetch_positions_advice(conn, snap["snapshot_id"])
    # positions_advice physically omits avg_open_price / invested_eur; assert the columns are gone
    assert all("avg_open_price" not in r.keys() for r in rows)
    assert all("invested_eur" not in r.keys() for r in rows)
    # and the ratified thesis version pins value_at_purchase to None (cost basis quarantined)
    for th in db.fetch_theses(conn):
        tv = db.fetch_current_thesis_version(conn, th["thesis_id"])
        assert tv["value_at_purchase"] is None


def test_no_new_pip_dependency_and_no_llm_import():
    import ast
    from pathlib import Path
    src = Path("agentcy/backfill.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # only stdlib + agentcy; no new runtime pip package, no LLM SDK
    allowed = {"agentcy", "dataclasses", "json", "__future__"}
    assert imported <= allowed, f"unexpected imports in backfill.py: {imported - allowed}"
    for banned in ("anthropic", "openai", "claudeclaw", "yfinance", "requests"):
        assert banned not in src
```

Note: if `backfill.py` ends up importing `store`/`clock`/`register`/`mirror`/`journal`/`asks`
these are all under the `agentcy` top-level package, so `imported` collapses to `{"agentcy",
...stdlib}`. If the AST test flags a legitimate stdlib module (e.g. `json` used at function
level), add it to `allowed` - do NOT add any third-party name.

**Run (expect fail then pass):**

```
uv run pytest -q tests/test_backfill.py -k "cost_basis or pip_dependency"
```

Expected: passes once the earlier tasks are in (these assert existing guarantees; if the AST
`allowed` set is too tight, widen it to the stdlib names actually used - never to a third party).

**Full-suite gate:**

```
uv run pytest -q
```

Expected: baseline + all new backfill tests green (963 + the new tests, still 3 skipped).
Confirm no regression before committing.

**Commit:**

```
test(thesis): quarantine cost basis + structural guards for backfill

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016C7KMzHLLmggj1DGZ7GQUJ
```

---

## Explicit follow-ons (NOT built here)

- **Part B - Claude qualitative-drafting via claudeclaw.** The NOT-NULL qualitative fields
  (`business_model_2s`, `moat_types`/`moat_evidence`, `owner_earnings_narrative`, `fair_band`,
  `conviction`, `mgmt_trust`, `circle_fit`, `ten_year_statement`) currently carry documented
  DRAFT placeholders. Part B has Claude draft them from the fundamentals + latest filings + the
  invested moment, on the droplet, sharing the Stage-2 claudeclaw harness (owner subscription on
  the box). Until then the deterministic triggers + ratification still work; the owner can fill
  the qualitative draft at the desk via `agentcy gate start --backfill`.
- **Track 1 - live eToro API wiring.** This plan seeds `position_detail` from an existing
  snapshot. The live eToro Read-API pull (`snapshot etoro`) that populates `opened_at` /
  `invested_eur` from the broker in production needs the owner's API key and is out of scope
  here (the plan is testable offline with seeded positions + fundamentals).
