# FinanceToolkit as the metric engine — evaluation and decision

**Date** 2026-08-06 · **Question (owner)** "Can we implement this as a dependency instead
for the metrics? Do deep investigation and see how we can use it to improve reliability,
data completeness and coverage of the metrics for philosophies —
https://github.com/JerBouma/FinanceToolkit" · **Status** decided

**Decision: no.** FinanceToolkit stays where it already is — desk-side, in
`stock-scout/requirements-research.txt`, for audits. It is not adopted as a runtime
engine, not as a narrow ratio import, and not as an oracle of truth. The audit it was
run for has already delivered its whole value: it independently confirmed our arithmetic
and pointed at the data layer, which is where the work goes instead.

---

## 1. Why not — the three findings that decide it

### Reliability: there is nothing to gain, because we are already right

31 symbols × 12 same-formula metrics = **282 comparisons; 280 agree to 1e-9 relative** —
bit level, not "within tolerance". Per metric: current_ratio 31/31, sbc_pct 29/29,
op_margin 27/27, Greenblatt ROIC 27/27, ROE 25/25, fcf_yield 25/25, gross_margin 24/24,
nd2e 19/19, interest_coverage 18/18, rd_intensity 16/16, tax_gap 15/15. A second lens
reproduced it independently on 9 other names across 5 metrics: 36 exact, 0 disagreements.
The 2 market-cap misses are our own share feed, not FT arithmetic.

**An oracle that agrees with you bit-for-bit carries zero runtime information.** It is a
good auditor precisely because it is independent, and a pointless dependency for the same
reason.

### Where it disagrees, it disagrees *by definition* — and adopting it would silently re-baseline live triggers

- `interest_coverage`: ours EBIT/|int|, FT's solvency variant (EBIT+D&A)/int — CMCSA
  **4.163 → 7.745**. A pre-committed "below 5x ⇒ break" trigger reads BROKEN under ours
  and INTACT under FT's. FT ships **two functions of the same name** (profitability vs
  solvency model), median 22.3% apart, max 120.3% *with a sign flip*.
- `roic`: ours Greenblatt, FT's (NI−div)/(equity+debt) — TXN **25.03% vs 2.93%**, KO
  20.29% vs 3.85% (n=13, median gap 37.7%). Cash conversion n=20, median 78.7% apart.
  FCF conversion: ORCL sign-flips −166.78% → +187.14%.

All 77 disagreements reproduce by hand from the filings *on both sides*. **Nobody has a
bug, and therefore nobody can adjudicate the other.** Swapping the formula under a
committed thesis changes what its triggers mean — the one thing the trigger contract
exists to prevent.

### It violates refuse-never-guess in exactly the way that caused our last two defects

Absent data is handled honestly (NaN in → NaN out, zero `fillna` across all five ratio
modules). *Degenerate* data is not: a zero denominator returns `inf` — which passes
`isna()`, passes a float check, and trips any `> threshold` break — and a negative one
returns a confident wrong number. HCA: equity −$6.303bn, NI +$7.814bn ⇒ FT ROE −123.97%
and debt/equity −7.04, *reading as net cash* against $44.373bn of real debt. Our layer
refuses all of these: 199 of 806 cells (24.7%) refused by design. FT's Piotroski returns
**6/9 for a business whose only sin was three untagged inputs** — indistinguishable from
three genuine failures, and the precise COKE/Comcast failure mode. Guarding all of that
costs more code than the 175 executable lines of arithmetic it wraps.

FT is also not a source of truth: `get_return_on_tangible_assets` *adds* intangibles and
liabilities where the definition subtracts them (AAPL 19.56% vs the correct 119.91%, a
6.1× understatement, unchanged since 1.9.0), and 14 of 70 shared functions (20%) changed
signature across 1.9.0 → 2.1.4 — a positional call site silently computes something else.

### Footprint and packaging rule out even a narrow import

`financetoolkit/ratios/__init__.py` is 0 bytes and the package `__init__` eagerly imports
`Toolkit`, so `from financetoolkit.ratios import profitability_model` costs **1,864
modules / 176 MB peak RSS / 1.37 s — byte-identical to importing the whole library**,
dragging sklearn, yfinance, peewee, curl_cffi, requests, bs4, protobuf. Our pipeline goes
97.3 MB → ~207 MB on a 2 GB box, for arithmetic that currently takes 0.73 s. Runtime
packages 4 → 8 (11 with transitives). And 2.1.4 **cannot be installed-and-imported in a
clean venv** (undeclared pyyaml, declared only under `extra == 'mcp'`) and is sdist-only
where 1.9.0–2.1.0 shipped wheels, so it cannot enter the uv-pinned wheelhouse without a
special case.

Licensing is **clean** — MIT, and `tools/license_gate.py` run against a FT venv reports
zero GPL-family violations. NFR7 is not the blocker here; semantics, footprint and
packaging are.

## 2. The premise, inverted: the gap is ours, and it is not a formula gap

Only 56 of 87 FT ratios are computable from our bundles today — **because of our concept
tables, not because EDGAR lacks the data.** The SEC tag index carries a median of 537
distinct tags per filer. Measured coverage across all 1,951 fetched filers:

| line | coverage | | line | coverage |
|---|---|---|---|---|
| operating lease liability | **92.1%** | | COGS | 65.6% |
| accounts payable | 88.1% | | inventory | 62.4% |
| PP&E net | 84.4% | | deferred revenue | 57.9% (61.6% in-circle) |
| D&A | 83.7% | | SG&A | 54.4% |
| accounts receivable | 81.2% | | preferred dividends | 5.2% |

Feeding 14 such lines back would lift computability to 84/87. What does *not* move:
**all-31 coverage stays at 7/87 even at tier 2** — no ratio family is universally
computable, which independently vindicates the shrinking-denominator rule.

## 3. Follow-ups, ranked (wrong numbers → unreachable numbers → missing numbers)

Anything touching `scoring.py`/`registry.py` needs a full-universe baseline diff first.

- **R1 — share-trend staleness guard. DONE, this commit.** The 450-day guard protected
  the market *cap* and not the *series* the trend reads. Measured on the universe: 47 of
  1,461 names (3.2%) carried a trend off a dead series — ANIP −80.88%/yr off a 4,907-day
  series, CHTR +141.41% off 3,689 days, NXT +227.33% off 918. Worse, the names whose cap
  the 2026-08-05 fix *repaired* via the weighted-average path kept a live, wrong trend:
  CMCSA +0.19%/yr off 6,062 days, UPS +3.63% off 6,014, F +10.71% off 5,579. The trend is
  a scored criterion, the hard dilution veto's input, and a legal thesis-trigger metric.
- **R2 — make the deferred-revenue float caveat reachable.** `scoring._deferred_revenue`
  and its 30%-of-revenue ROIC caveat are **dead code on every EDGAR bundle** (0 of 600
  carry any `Deferred*` label) because `pit.py` declares no deferred-revenue concept.
  Adding the four contract-liability tags to `_SUPPLEMENT_POINT_CONCEPTS` makes a caveat
  that fires on 0% of bundles checkable on ~58% of filers / ~62% in-circle — and customer
  prepayment is Buffett moat evidence (switching costs, negative working capital) in
  exactly the SaaS/healthcare circle. **Constraint:** new tags go in `_SUPPLEMENT_*`,
  never in `_INCOME_/_CASHFLOW_/_BALANCE_CONCEPTS` — `_section` unions labels onto one set
  of period ends and TTM reads `sorted(inc_src)[-1:]`, so a statement-dict addition whose
  newest period post-dates revenue's silently breaks TTM. `enrich.consumed_tags()`
  introspects the tables, so tier 2 picks it up with no second edit.
- **R3 — close the defect *class* with two mechanical tests.** (i) label reachability:
  every statement/supplement label read by `scoring`/`registry`/`inversion` must be
  emitted by some `pit.py` concept table — this catches R2 at write time and every future
  vendor-shaped dead path. (ii) staleness: every dated series a metric consumes must be
  unable to produce a number past its declared max age. Highest leverage after R1, and
  the reason the last three defects were found by investigation rather than by CI.
- **R4 — widen the concept tables only where a named consumer exists**: operating lease
  liability (92.1%, and *no* FT ratio expresses it — fixed obligation `nd2e` misses
  entirely), AP (88.1%), PP&E (84.4%), AR (81.2%). Not a race to 84/87.
- **R5 — one new registry metric: `days_sales_outstanding`** (81.2% coverage, better than
  the long-term-debt tag `nd2e` already leans on). The only genuinely new
  decision-relevant quantity in 248 FT functions: nothing in the 26 metrics or 7
  inversion probes looks at receivables, and receivables outgrowing sales is the earliest
  mechanical tell that revenue quality is rotting.
- **R6 — time-to-recover in the inversion layer.** `inversion.max_drawdown` returns a
  binary `recovered`; add the span, which separates a fall regained in three quarters
  from one regained after nine years. Hand-rolled — *not* FT's `get_max_drawdown`, whose
  `(1 + returns.fillna(0)).cumprod()` turns missing weeks into zero-return weeks, the
  error INVERSION-DESIGN §8 already records and fixes.

## 4. What FT stays useful for

An **independent second implementation** to audit against, exactly as used here. That is
worth keeping in `requirements-research.txt` and re-running after any change to the
frozen decision layer — a desk tool with no runtime footprint, no trigger semantics, and
no say over what a thesis means.
