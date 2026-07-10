# Scout v2 — Broad-Market Philosophy-Graded Discovery Engine

**Status:** Design approved by owner 2026-07-10. Synthesized from a 7-pillar deep-dive + 3-lens adversarial review (workflow `stock-grading-design`). Amends `docs/plans/2026-07-08-architecture-elaboration.md` §H (The Scout) and the anti-complexity ledger — see §9. Evidence base: `docs/research/2026-07-08-longterm-id-frameworks.md`, `docs/research/2026-07-03-repo-evaluations.md`.

**One-line:** grade *all* ~8,000 US+EU (≥ ~$300M) equities on a transparent, deterministic four-pillar composite that encodes Buffett/Munger/Naval; tier by circle-of-competence (priority, not filter); reserve an LLM for a ~30-name qualitative shortlist. **The Scout still only surfaces; the Gate still decides.**

---

## 0. What changed from v1

v1 (§H): one QV recipe (EV/EBITDA cheapness + ROIC>15% gate), circle-of-competence as a hard filter, human-run, top-20 by cheapness, live TradingView query (a stub in code today).

v2 (owner decisions, 2026-07-10):
- **Universe widened** to US + Europe, market cap ≥ ~$300M (small-cap and up) — ~8,000–10,000 names.
- **Multi-factor composite grade** that encodes the *philosophy*, not just cheapness — explicitly including **management quality**.
- **Circle of competence is a priority TIER, not a filter** — surface the best cheap+quality businesses anywhere; miss nothing great.
- **Deterministic-first, LLM-secondary** — all quantitative math is deterministic and runs on all names; the LLM reads prose only, on a shortlist only.

---

## 1. The grading model

Four pillar scores, each 0–100, computed deterministically per ticker from the hardened yfinance statements layer (`fetch/yf.py` + `store.py`) plus the FinanceDatabase categorical fields. **Every metric uses only what the data layer already computes from ≤5 statement periods** — no sixth quarter (MA-1), no DCF, no growth/WACC/terminal assumption, no ML, no black box.

**Scoring convention:** each raw metric → **cross-sectional percentile within the ticker's own sector** (FinanceDatabase `sector`) → [0,100]. Sector-relative percentile is what makes one composite fair across 8,000 heterogeneous names with **zero magic constants**; a small number of absolute reference lines (ROIC>15%, the veto thresholds) are the only fixed numbers, and they are inherited from v1.

### Pillar V — Value (Buffett: a fair price) · weight 30%
The single anchor, honoring BUF-1 (P/owner-FCF is the *only* valuation anchor; reported-EPS multiples banned) and BUF-5 (owner earnings = FCF − SBC).

| Metric | Validates | Scoring |
|---|---|---|
| **Owner-FCF yield** = (FCF − SBC) / EV | Fair price on real distributable cash, capital-structure-neutral | Sector percentile; higher = better |
| **P / owner-FCF** | The Gate's own anchor, printed for continuity | Display companion (same signal), not separately weighted |

One metric, one field family. No EV/EBITDA + P/FCF + earnings-yield stacking (cut in v1, MA-8; stays cut).

### Pillar Q — Quality / Moat (Buffett: a wonderful business) · weight 30%
Moat *evidence*, not a moat *label*. Three durable-economics proxies.

| Metric | Validates | Scoring |
|---|---|---|
| **ROIC** = NOPAT / (net working capital + net fixed assets) — Greenblatt denominator | Capital productivity → cost/scale advantage | Sector percentile; >15% reference line (v1 QV_ROIC_MIN) |
| **Gross margin: level + stability** across available periods | Pricing power → brand / switching-cost moat | Percentile of level, penalized for high variance |
| **Owner-FCF margin** = (FCF − SBC) / revenue | Converts sales to real cash (SaaS-circle sanity) | Sector percentile |

### Pillar D — Durability / Financial Strength (Munger: avoid ruin, graded) · weight 20%
The continuous version of the balance-sheet health the veto layer (§2) also enforces as a hard floor.

| Metric | Validates | Scoring |
|---|---|---|
| **Net debt / EBITDA** = (Total Debt − Cash) / EBITDA | Survives the 10-year test | Lower = better; graded band, hard-capped in §2 |
| **Owner-FCF positive & self-funding** | Doesn't need capital markets to exist | Ramp: negative → 0, comfortably positive → full |
| **SBC / revenue** | How much "owner earnings" is really handed to employees | Lower = better (anti-dilution, BUF-5) |

### Pillar M — Management Quality (owner's explicit ask) · weight 20%
The Constitution's management tests are **skin in the game** and **don't dilute / don't destroy owner cash**. Only those are *deterministically evidenced* from the statements we have, so those are the deterministic M score. The **judgment** part (candor, capital-allocation track record, trustworthiness) is **deferred to the LLM shortlist (§4)** — the Constitution forbids faking trust in management (FR9).

| Metric | Validates | Scoring |
|---|---|---|
| **Share-count trend** (cleaned shares series, NFR6) | Buying back vs. serially diluting | Shrinking/flat → high; steady issuance → low |
| **Per-share owner-FCF CAGR** (3yr) vs. share growth | Compounding *per share* vs. empire-building on printed stock | Percentile of per-share owner-FCF CAGR |
| **Accrual/cash divergence** = sign & size of (net income − owner-FCF) | Earnings quality — reported profit with no cash behind it is a Munger red flag | Small/negative divergence → high |

*Deferred to LLM, never faked: insider ownership %, capital-allocation candor, related-party dealings. Output flags "M-qualitative: pending shortlist review."*

### Composite

```
Composite = 0.30·V + 0.30·Q + 0.20·D + 0.20·M          (each pillar 0–100)
```

Weights encode the philosophy: **wonderful business (Q) at a fair price (V)** co-equal and dominant (60%); **avoid ruin (D)** and **trust management (M)** the co-equal guardrails (40%).

| Composite | Grade | Meaning |
|---|---|---|
| ≥ 80 | **A** | cheap + wonderful + safe + owner-friendly — take to the Gate first |
| 65–79 | **B** | strong on most pillars, one soft leg |
| 50–64 | **C** | mixed; interesting only if the soft leg is a known, defensible story |
| 35–49 | **D** | weak; needs a special reason |
| < 35 | **F** | pass |
| — | **VETOED** | any §2 gate tripped — grade suppressed, reason printed |

Four pillars, ~11 metrics, all sector-relative percentiles of numbers the owner can recompute from a 10-K. Tunable surface: the four weights + the ROIC/net-debt reference lines already in v1. (HN2 rejects >~15 assumptions; this has zero free numeric assumptions beyond those.)

---

## 2. The veto / penalty layer (Munger: avoid ruin) — runs before grading

The Scout does **not** run the Hell-No filter (that needs the human, FR3/FR9). It **pre-flags the two Hell-No conditions that are computable**, so a wreck never sits atop an A-list.

| Gate | Rule | Action |
|---|---|---|
| **Leverage veto** | Net debt/EBITDA > 4, **or** EBITDA ≤ 0 with net debt > 0 | **VETOED** — grade suppressed |
| **Cash-destruction veto** | Owner-FCF < 0 across *all* available periods | **VETOED** |
| **Dilution penalty** | Share count growing > 5%/yr sustained | **−15 to composite**, flagged |
| **Data-integrity suspend** | Denominator non-positive/stale, or < 2 usable periods (MA-2/MA-3) | **NOT GRADED — "insufficient data"**, never a silent 0 |

Vetoes **cap, never rank** — a VETOED name is removed from the shortlist, not sorted to the bottom where it could still surface. The three uncomputable Hell-No axes (can't-understand, distrust-management, fad/high-fees) remain the human's call at the Gate. The Scout says "this has a balance-sheet problem"; it never says "this passes Hell-No."

---

## 3. Tiering — circle of competence as a priority lane

Tier assigned purely from FinanceDatabase `sector`/`industry` — deterministic, no LLM.

| Tier | Definition | Lane |
|---|---|---|
| **Core** | Cloud/SaaS infra, healthcare & insurance tech, AI tooling — the owner's edge | Priority |
| **Adjacent** | Broader software, IT services, med-devices, fintech, data/analytics — one hop out | Second |
| **Outside** | Everything else | Third |

**Tier and grade are orthogonal axes, never blended** (blending would let a mediocre core name outrank a wonderful outside name — the exact "nothing great is missed" failure to avoid). Output is **tier-sectioned, grade-sorted within each**, plus a cross-cutting **"Outside-tier A-grades"** list — an A outside the circle is precisely what Naval says to notice (expand the circle where the evidence is strongest). Tier tells the owner *how much homework the Gate will be*; grade tells them *how good the business looks*.

---

## 4. The two-stage pipeline

**Stage 1 — deterministic pass over all ~8,000 names (the workhorse, no LLM).**
Per ticker: cached statements → ~11 metrics → veto layer → sector percentiles → four pillar scores → composite → tier. Pure pandas/scipy. Output: the full graded, tiered table. **This stage is standalone-valuable and ships first** (§8 build order).

**Stage 2 — LLM qualitative review of the shortlist only (secondary, efficiency-bounded).**
Shortlist **N = top 10 per tier (≈30 names) + any Outside-tier A-grade.** The LLM is invoked only here, only on genuinely qualitative dimensions left out of the deterministic score.

- **Source docs (per shortlisted name):** latest annual report / 10-K **MD&A + business-description**, and the latest earnings-call transcript if available. No prices, no ratios — the deterministic layer owns all numbers.
- **The four questions** (each returns a short verdict + one evidence quote):
  1. **Moat in two sentences** — durable advantage stated in ≤2 sentences with filing evidence? → {clear / plausible / not-evident} + moat type.
  2. **Management-qualitative** (the deferred half of Pillar M) — candid capital-allocation reasoning + owner-operator alignment, or promotional/evasive? → {aligned / neutral / red-flag}.
  3. **Fad-vs-trend** — real business on a real trend, or a theme-branded vehicle? → {real / theme-branded / can't-tell}.
  4. **Circle sanity** — does the actual business match its sector tier? → tier-confirm or tier-correction.
- **How it adjusts the grade:** the LLM **cannot move the composite number** (math stays deterministic + auditable). It attaches a **badge** (✓ moat-confirmed / ⚠ moat-not-evident / ⛔ fad-flag / ✎ tier-correction) and applies **one bounded, reason-printed adjustment**: a ⛔ fad-flag or management red-flag demotes one grade band; ✓ on all four can promote one band **only if** no pillar is < 50. Never silent.

**LLM invocation (resolved):** Stage 2 is built as a **pluggable `QualitativeReviewer` interface** with two adapters — an **Anthropic API adapter** (automated, needs a key + a few cents/run) and a **manual/desk adapter** (the owner runs it via a Claude Code session and pastes verdicts). The deterministic Stage-1 is complete without either. **Default: API adapter, but only ever invoked inside a human-triggered Scout session** (never the scheduled runtime — honors "no LLM in the loop"). Which adapter is active is a journaled config choice.

---

## 5. Data source

- **Universe (categorical):** FinanceDatabase `compression/equities.bz2`, direct read, pinned commit SHA, cached (already in `scout.py`: `load_universe`, `UniverseSHAError`). Sector/industry/country/market-cap-band for tiering + the ≥$300M floor. MIT (verified 3-0).
- **Fundamentals (the numbers):** the already-hardened yfinance layer — the same feed the Gate/Watchdog trust; the Scout adds no new numeric dependency. Percentiles over whatever periods exist, count printed (MA-5), integrity-suspend when thin (§2).
- **Scale reality:** grading ~8,000 names is a **batch job over the cached fundamentals archive**, not 8,000 live calls. The archive is populated on a slow background cadence (paced fetch, respecting NFR6); a triggered Scout session grades from cache and returns fast. **Pre-approved fallback (NFR7):** if the metric set outgrows what the hardened layer cleanly yields, **FinanceToolkit in keyless / custom-DataFrame mode** (MIT, fed our own cleaned statements). TradingView-Screener is demoted to an optional human spot-check, never the grading feed.
- License-clean per NFR7; no new key, no paid feed (NFR3), beyond the optional Stage-2 LLM key.

---

## 6. Cadence

**Human-triggered (FR14), never scheduled.** A weekly auto-emailed A-list manufactures exactly the FOMO/action-bias Pillar 2 exists to suppress. The deterministic Stage-1 grades may be **cached and refreshed on a slow background cadence** (e.g. after each earnings season) so a triggered session returns instantly — but the **session, the reading, the LLM spend, and any watchlist entry are always owner-initiated.** Results are human-read, never persisted as monitoring state; hand-picked tickers enter the watchlist as `raw` (cap 10, 90-day expiry) and each still passes the full Gate.

---

## 7. Worked examples

**A — Core SaaS (Veeva-like).** V 58 (quality trades rich) · Q 92 · D 84 · M 80 → **Composite 78 → B**, Core. LLM: "✓ moat-confirmed (switching costs + regulatory); founder-led, candid; not a fad." Surfaced #1 in Core with the honest note: *the only thing between this and an A is price.*

**B — Outside cheap-quality (a specialty distributor).** V 90 · Q 74 · D 82 · M 88 → **Composite 83 → A**, Outside → **★ Outside-tier A-grade.** LLM: "✓ cost-scale moat, disciplined buybacks, not a fad, tier correct." *The design working as intended:* a wonderful, cheap, well-run business the owner would never have screened for, surfaced with an A as a circle-expansion candidate. The Gate still demands the owner understand it before buying.

**C — Veto kill (a leveraged "AI" rollup).** Net debt/EBITDA 6.8 + owner-FCF negative every period → **VETOED**, grade suppressed, shares +14%/yr flagged. Never reaches the shortlist → **no LLM token spent.** The Munger Hell-No wreck, killed deterministically before any attention is paid.

---

## 8. Build order (deterministic first)

1. **Stage-1 deterministic engine** — the four pillars, sector-percentile scoring, veto layer, tiering, the graded/tiered CLI output, over the FinanceDatabase universe + cached fundamentals. Standalone-valuable, fully constitution-clean, no LLM. **Ships as Scout v2.0.**
2. **The fundamentals-archive batch populator** — paced background fetch so grading runs from cache at scale.
3. **Stage-2 `QualitativeReviewer`** — the interface + the two adapters (API / manual), the shortlist selection, the four questions, the bounded badge/adjustment. **Ships as v2.1.**

---

## 9. Constitution note — anti-complexity ledger amendments (owner-ratified 2026-07-10)

**Amendment 1 — §H.2 "one cheapness recipe, top-20" → four-pillar composite grade over the broad universe.**
*Reconciliation:* adds factors, not opacity. V is unchanged (the same single owner-FCF anchor, BUF-1/BUF-5). Q, D, M use only metrics the data layer already computes; scoring is transparent sector-percentile — **no ML, no DCF, no growth/WACC/terminal assumptions**. The set is the *minimal evidence-backed one*: everything the review found uncomputable (6-quarter persistence, MA-1), unproven (momentum, ESG; trend-slope/stability folklore), or redundant (multi-metric valuation stacking, MA-8) is **excluded**. Four weights + two reference lines are the entire tunable surface.

**Amendment 2 — §H "screen surfaces cheap names" → graded, tiered, LLM-annotated shortlist.**
*Reconciliation:* the score's role is unchanged in kind — it **surfaces, it never decides.** The **Gate is untouched** (single P/owner-FCF anchor, full human-run Hell-No, owner judgment on the three uncomputable Hell-No axes and all FR9 fields). The deterministic/LLM split honors §H.4 exactly: **code does all the math; the LLM only reads prose on ~30 names, with a bounded, one-band, reason-printed adjustment it can never silently override.** Tiering replaces the hard circle filter with a priority lane — an improvement in *fidelity* (the circle is Naval's expanding edge, not a cage) at no cost in transparency.

**Unchanged and reaffirmed:** human-triggered only (FR14); results human-read, never persisted as monitoring state; hand-picked tickers only, as `raw` watchlist items, through the full Gate; honest evidence note printed every run; local storage / owner-only delivery (NFR2); MIT-file + existing-yfinance data stack, FinanceToolkit-keyless the pre-approved fallback (NFR3/NFR7); **no LLM in the scheduled runtime** — the Scout's LLM runs only in a human-triggered desk session. **The Scout advises and surfaces. It never executes, and it never decides — the Gate does.**
