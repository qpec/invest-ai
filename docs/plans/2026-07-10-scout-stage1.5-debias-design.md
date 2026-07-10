# Scout Stage-1.5 — De-bias the Grader for Compounders (Design)

**Status:** approved 2026-07-10. Amends `docs/plans/2026-07-10-scout-v2-graded-screening-design.md` §1 (pillars + composite weights). Scout discovery only — the live monitoring path (`store.owner_fcf_ttm`, Watchdog triggers, Gate, Thesis Register) is deliberately untouched.

## Motivation (the fidelity audit)

A philosophy-fidelity audit of the shipped Stage-1 grader (`agentcy/scout_grade.py`) found one structural, non-deferred bias: owner earnings are defined as `(OCF - total CapEx) - SBC` (`store.py:265`), which treats high-return **growth** CapEx as a cost. That single choice penalizes reinvesting compounders in four scored places (Value yield, Quality owner-earnings margin, Durability self-funding, Management accrual divergence) and can trip the cash-destruction veto — so a mature no-growth cash cow outranks a compounder, and a young high-ROIC reinvestor gets suppressed outright. This is the opposite of "buy the wonderful business and let compounding do the heavy lifting" (Buffett) and "own equity in things that scale" (Naval). Growth itself is near-invisible in the grade (only an optional Management leg, ~0-7% effective weight). This design repairs that, deterministically, for the discovery path only.

## The five changes

### 1. Normalized owner earnings (Scout discovery only)
A new figure `normalized_owner_fcf = OCF - min(CapEx, D&A) - SBC`, computed per-period and TTM from the archive. `min(CapEx, D&A)` is the maintenance-CapEx proxy (Buffett's owner earnings subtract only maintenance CapEx; D&A approximates the replacement cost of assets in use, and `min` keeps it never above actual CapEx). **D&A source:** the cashflow statement's `Depreciation And Amortization` pinned row; if absent for a name, fall back to total CapEx so `normalized == conservative` (a safe degradation, never an error). The conservative `store.owner_fcf_ttm` is unchanged and keeps guarding held positions. The Scout grader uses the normalized figure in: V (`owner_fcf_yield`, `p_owner_fcf`), Q (`owner_fcf_margin_pct`), D (`owner_fcf_positive` self-funding leg + the cash-destruction veto input), and the G growth legs.

### 2. Sloan accrual fix (capex-independent earnings quality)
Accrual divergence becomes `NI - Operating Cash Flow` over TTM (classic Sloan accruals), not `NI - owner-FCF`. Earnings quality must be independent of capital intensity; the old form flagged capital-intensive compounders as if they were accounting frauds. This is a correctness fix. Still lower-better, still normalized by revenue.

### 3. New Growth pillar (G) — re-weighted V25 / Q25 / G20 / D15 / M15
Composite becomes `0.25 V + 0.25 Q + 0.20 G + 0.15 D + 0.15 M + penalty`. G has up to two sector-percentile legs, **each gated by ROIC** (`leg x min(1, ROIC / 15%)`, mirroring RF4's roic_leg_score):
- (a) annualized **revenue growth** over the available archive window (oldest usable quarter -> newest, annualized), honestly labeled with the same <3yr-window caveat as the per-share growth metric;
- (b) per-share **normalized** owner-earnings growth (moved here from M, where it never belonged).

The ROIC gate only rewards *profitable* growth — a deliberate lightweight Munger fad-guard ("growth at any cost" scores ~0). If growth data is too thin to compute either leg, G degrades to **neutral 50.0** (unknown != punished), so the name still grades on V/Q/D/M. M keeps dilution + the (now Sloan) accrual metric.

### 4. Cash-destruction veto carve-out for genuine reinvestors
The **leverage** veto is unchanged (leverage is always disqualifying — Munger Hell-No #1). The **cash-destruction** veto (normalized owner-FCF negative in every available period) now spares a name **only if** `ROIC > 15% AND revenue growth > 10%/yr` — the young high-return compounder investing ahead of profits; it becomes a *flagged caution* (a printed note), not a suppression. The ROIC>15% gate keeps this from being a hype loophole; a low-ROIC cash-burner is still vetoed.

### 5. Honest grade-vs-thesis framing
One line in the Scout render (`render/scout.py`): the grade is quantitative evidence; moat durability, management candor, and fad-risk are Stage-2 judgments (pending) — so a computed "A" is never read as a thesis verdict (counters the Munger overconfidence trap). Lint-safe (through `owner_spans` if any token trips the benchmark lint).

## Cost & testing
Changing the weights + adding G + the accrual fix + normalized earnings will move many of the ~60 existing `scout_grade` expected values and the render goldens; those are updated task-by-task under TDD. New tests cover: normalized earnings incl. the D&A-absent -> conservative fallback; the Sloan accrual; the G legs + ROIC gating + thin->neutral-50; the re-weighted composite; the veto carve-out (high-ROIC reinvestor spared, low-ROIC burner still vetoed); and a **regression proving a reinvesting compounder is no longer dominated or vetoed by a mature cash cow** (the whole point). All offline (autouse no-network guard); seeds via `db.append_fundamentals_period` etc.; timestamps via `db.to_iso(clock.now())`.

## Scope (YAGNI)
**In:** the five changes above, plus the updated Stage-1 tests/goldens.
**Not in:** any change to `store.owner_fcf_ttm` or the monitoring/trigger/Gate/Register path; Stage-2 (LLM); the fundamentals populator (resumes immediately after, on the de-biased grader — held task #24); FX; and return-on-*incremental*-capital (too noisy from a <3yr archive — revenue growth + per-share normalized owner-earnings growth are the robust legs; ROIIC stays deferred).
