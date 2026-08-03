# The Owner's Scorecard — an interpretable composite

**Status:** design, 2026-08-01. Answers the owner's ask: *"use the repository philosophy to
further improve the scout on ease of interpretation and give a real composite score that is
logical and easy to interpret."* Reference for structure and anchors: `virattt/ai-hedge-fund`
persona agents (points-with-reasons), already adopted in v2.3 as the 13-point Buffett lens.

---

## 1. What is wrong with the current composite

Not a bug — a category error. `composite = 0.25·V + 0.25·Q + 0.20·G + 0.15·D + 0.15·M`,
where every pillar is a **sector percentile**. The chat diagnosed all of this itself:

1. **The number has no fixed meaning.** 75 means "roughly 75th percentile among whoever else
   happened to be graded in this run". Grow the pool from 428 to 1,952 names and every score
   moves without a single business changing. Msg 64 saw it coming: *"in een pool die ~10×
   groter is, is 'top-15' een véél strengere eis."*
2. **Within-band ordering is noise, yet it is printed to one decimal.** Msg 36: *"Het verschil
   tussen #9 (75.8) en #11 (75.6) betekent niets"* — and YOU moved 81.7 → 79.7 → 81.7 → 83.3
   across versions purely from defensible modelling choices.
3. **It hides disagreement.** Msg 36 names three different definitions of "good" (relatively
   cheap-and-strong, absolutely cheap, Buffett-safe) that *"zelden samenvallen"*, and proposed
   a consensus column. The owner never answered; it was never built. This design builds it.
4. **It does not say what to do.** "B 78.5" is not a decision.
5. **Averaging percentiles is dimensionally meaningless** — 0.25·(a percentile) + 0.25·(another
   percentile) is a number with no units and no interpretation.
6. **It is the least Buffett-like part of the system.** Buffett does not rank; he asks whether a
   *specific* business is wonderful and whether the price is fair. A weighted average of
   cross-sectional ranks cannot express "wonderful business at a fair price" — it lets a
   terrific price paper over a broken business, which is exactly the trade the framework forbids.

## 2. What replaces it

An **absolute, anchored scorecard**: 100 points across four blocks, each point earned against
an economically meaningful reference line rather than against the peer group. The same business
scores the same tomorrow, in a different universe, in a different sector.

The sector percentiles are **not deleted** — they remain as *"rank within sector"* context, and
they remain the engine the v3 formation and the walk-forward validation run on (§6). What
changes is which number leads and how the evidence is presented.

### Block 1 — Business quality · 35 pts · *"Would I want to own this business?"*

| Metric | Floor (0 pts) | Target (full) | Pts | Validates |
|---|---|---|---|---|
| ROIC | 5% | 25% | 12 | Capital productivity — the moat's arithmetic |
| Gross margin level | 20% | 60% | 6 | Pricing power |
| Gross margin stability (CV) | 0.35 | 0.05 | 5 | Is the pricing power *durable* |
| Owner-FCF margin | 0% | 20% | 7 | Sales actually become owner cash |
| Revenue growth (annualized) | 0% | 15% | 5 | The business is still growing |

### Block 2 — Price · 25 pts · *"Am I paying a fair price?"*

| Metric | Floor | Target | Pts | Validates |
|---|---|---|---|---|
| Owner-FCF yield on EV | 2% | 8% | 15 | BUF-1: the only valuation anchor |
| Margin of safety (DCF) | −25% | +50% | 10 | Absolute cheapness, independent of peers |

### Block 3 — Safety · 25 pts · *"Can this be permanently impaired?"* (Munger)

| Metric | Floor | Target | Pts | Validates |
|---|---|---|---|---|
| Net debt / EBITDA | 4.0 | 0.0 | 10 | Survives the 10-year test |
| Self-funding (share of periods with positive owner-FCF) | 0.5 | 1.0 | 8 | Does not need capital markets |
| SBC / revenue | 10% | 2% | 4 | Owner earnings are not handed to staff |
| Current ratio | 1.0 | 2.0 | 3 | Near-term solvency |

### Block 4 — Stewardship · 15 pts · *"Is management on my side?"*

| Metric | Floor | Target | Pts | Validates |
|---|---|---|---|---|
| Share-count trend | +5%/yr | −2%/yr | 7 | Buying back vs. printing stock |
| Accruals (NI − OCF)/revenue | +10% | 0% | 5 | Earnings quality |
| Capital returned / owner-FCF | 0 | 0.5 | 3 | Cash actually reaches owners |

**Scoring rule.** Each metric scores `clamp((value − floor) / (target − floor), 0, 1) × points`
— linear between two anchors, **no cliffs**. A 14.9% ROIC is not punished relative to 15.1%;
the ratified 15% line lands at exactly the midpoint of the ROIC ramp by construction. A metric
whose inputs are missing scores **no points out of a reduced maximum** — never a silent zero
(§4). The block score is the sum; the composite is the sum of blocks.

## 3. Every constant, and where it comes from

The anti-complexity ledger (HN2) rejects models with many free assumptions, so every anchor is
declared. There are **14 metrics × 2 endpoints = 28 anchors**. Four ramps are pinned by lines
the owner already ratified — and in three of those the ratified line sits at the ramp's
*midpoint*, with the endpoints bracketing it symmetrically, so the inherited judgement is what
positions the ramp even where the endpoints themselves are new. The rest are new and declared
as such. This table is generated from `scorecard.ANCHORS`; the code is the source of truth.

| Metric | Block | Floor → target | Pts | Provenance |
|---|---|---|---|---|
| `roic` | quality | 5 → 25 % | 12 | **Inherited** — `scoring.QV_ROIC_MIN` (15%) sits at this ramp's exact midpoint; the endpoints bracket it symmetrically |
| `gross_margin` | quality | 20 → 60 % | 6 | New — spans commodity to software economics |
| `gross_margin_cv` | quality | 0.35 → 0.05 | 5 | New — brackets a stable margin (CV ≤ 0.05) against a visibly drifting one (CV ≥ 0.35) |
| `owner_fcf_margin` | quality | 0 → 20 % | 7 | New — a 1-in-5 cash conversion is exceptional |
| `revenue_growth` | quality | 0 → 15 %/yr | 5 | New — the G pillar already gates reinvestors at 10%/yr |
| `owner_fcf_yield` | price | 2 → 8 % | 15 | New — 8% ≈ 12.5× owner earnings, Buffett's habitual "fair" |
| `margin_of_safety` | price | −25 → +50 % | 10 | New — mirrors ai-hedge-fund's 25% margin-of-safety convention |
| `net_debt_ebitda` | safety | 4.0 → 0.0 | 10 | **Inherited** — `scoring.NET_DEBT_EBITDA_VETO`, the §4.4 leverage veto line, as the ramp floor |
| `self_funding` | safety | 0.5 → 1.0 | 8 | New — half the annual periods self-funding is the floor, every period the target |
| `sbc` | safety | 10 → 2 % | 4 | New — 2% is conventional "low SBC" for profitable software |
| `current_ratio` | safety | 1.0 → 2.0 | 3 | **Inherited** — the ai-hedge-fund Buffett-checklist line (>1.5) sits at this ramp's midpoint |
| `share_count_trend` | stewardship | +5 → −2 %/yr | 7 | **Inherited** — `scoring.DILUTION_PENALTY_PCT`, the §4.4 dilution line, as the ramp floor |
| `accruals` | stewardship | +10 → 0 % of revenue | 5 | New — earnings that fully become cash score full |
| `capital_returned` | stewardship | 0 → 0.5 × owner-FCF | 3 | New — half of owner earnings returned is shareholder-friendly |

**Two metrics are dropped rather than scored when the evidence is weak**, because an absolute
scorecard has no "neutral" to fall back on the way a percentile does:
- *gross-margin stability* when fewer than two usable periods exist — `scoring._gross_margin_cv`
  returns 0.0 for "no evidence of drift", which is harmless for a percentile but would hand a
  name with no margin history the full 5 stability points;
- *share-count trend* on a `SHARE_CLASS`-flagged name — §4.5 parks that leg at neutral 50
  precisely because the trend is untrustworthy there, and neutral does not exist here.

Both shrink `available_max` and are named in `coverage` (§4.2).

## 4. Honesty rules (non-negotiable, inherited from the repo's own contracts)

1. **No price, no verdict.** The Price block is the one the market has *not* already arbitraged
   away: msg 55 proved quality alone is fairly priced (*"kwaliteit-op-zich wordt door de markt al
   eerlijk geprijsd — een lijstje 'beste bedrijven' kopen levert niets op"*). So when price data
   is absent the scorecard reports a **quality profile only, explicitly not a verdict**, and
   refuses to emit a band. This is the single most important rule here.
2. **Missing inputs shrink the denominator, never score zero.** A name scoring 48 of an available
   75 reports `48/75 (64%)`, with the unavailable block named — never 48/100.
3. **Vetoes suppress, never rank** — the §2/§4.4 layer is unchanged and runs first.
4. **Bands, not ranks.** The noise floor is stated on every output: differences under ~5 points
   are not meaningful. Names are ordered but the order is presented as a band membership.

## 5. Interpretation layer

Per name, four things a human can read in five seconds:

- **Headline** — `78 / 100 · Strong` plus the band's plain-language meaning.
- **Blocks** — `Quality 29/35 · Price 17/25 · Safety 21/25 · Stewardship 11/15`, so the reader
  sees *where* the score comes from without opening anything.
- **Why, in words** — the single strongest and single weakest metric, named with their values
  ("carried by a 31% ROIC; held back by SBC at 11% of revenue").
- **Consensus** — how many of three *independent* lenses call it good: the Scorecard (≥60),
  the DCF margin of safety (>0), and the 13-point Buffett checklist (≥9). This is msg 36's
  proposal, finally built. Three-of-three is the real signal; the chat's own example was Adobe
  (*"B 78.5, MoS +51%, Buffett-lens vrijwel maximaal"*), and it noted that a name green on all
  three is *"een sterker signaal dan de #1-positie zelf"*.

Bands:

| Score | Band | Meaning |
|---|---|---|
| 80–100 | **Exceptional** | Wonderful business at a fair price — take to the Gate first |
| 65–79 | **Strong** | Worth the Gate's homework |
| 50–64 | **Mixed** | One or more legs genuinely weak |
| 35–49 | **Weak** | Needs a special reason |
| 0–34 | **Pass** | — |
| — | **VETOED** | A §4.4 gate tripped; score suppressed, reason printed |
| — | **NO PRICE** | Quality profile only — not a verdict (§4.1) |

## 6. What this is and is not

**Is:** absolute, stable across runs and universes, traceable to a threshold per point,
cliff-free, and honest about missing data.

**Is not: validated.** The percentile composite has the only empirical evidence this system
owns — the blind walk-forward of msgs 49–50 (v3 owner-mode beat v2 on both blind halves). The
scorecard has **no such evidence yet**, and swapping the formation's engine for it on the
strength of "it reads better" would throw that evidence away for nothing. So:

- the formation and the backtests keep running on the validated percentile engine;
- the scorecard leads the **report and datasheet**, where interpretation is the whole job;
- validating it is a defined next step, not a claim: run `backtest3.py` with the scorecard as
  the ranking engine over the same two blind halves and compare against the pre-registered
  criterion. The owner's box has the price grids that makes this runnable today.
