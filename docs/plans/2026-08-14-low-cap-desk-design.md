# The Low-Cap Desk — a separate interface with its own constitution

**Date:** 2026-08-14
**Status:** RATIFIED (owner, 2026-08-14: "Prima") — phases 1–3 implemented same day
(`lowcap.py`, the fourth tab + `select_lowcap` stage + migration 011,
`lowcap_thesis.py`); phase 4 (volume/ADV$, filing-cadence score, Form 4 feed) open
**Owner directive:** "I don't want a tranche. I want a separate low-cap interface.
This needs a different philosophy. Use ai-hedge-fund (check github) to deploy the right
philosophies. Do extensive research into how others do this before you start planning."
**Research bundle:** `docs/research/2026-08-14-low-cap-research/` — eight reports:
the ai-hedge-fund v2 architecture, its five philosophy signals, its recovered v1
persona catalogue (19 agents, exact thresholds, from git history), small-cap
practitioners (Lynch, Graham, Cassel, Slater, Greenblatt, Royce, Wanger, Pabrai,
Burry, Fisher), the academic factor literature, small-cap failure modes, other
AI-investing systems (TradingAgents, FinRobot, GuruAgents, MicroCapClub), and this
repo's own constraints.

**Supersedes:** the reverted small-cap tranche (commit `ef83959`, reverted `9b7e24e`,
same day). The tranche gave small caps *slots in the main desk's game*; the owner's
point is that small caps are a *different game*, needing their own rules and their own
surface. This document is that game's constitution.

---

## 1 · Why a different philosophy — what the research actually says

Three findings force the design; they are not preferences.

**1. There is no size premium — small is a hunting ground, not a factor.**
Alquist/Israel/Moskowitz (2018): no reliable standalone size premium after risk
adjustment. But *other* anomalies — quality, share issuance, accruals, earnings drift —
are demonstrably strongest inside small caps with no analyst coverage. Piotroski's
F-Score gains are "concentrated in small firms, low share-turnover firms, and firms
with no analyst following." The literature's one structural gift to an individual:
funds cannot deploy into a $400M name without moving it for weeks; a private
investor's position is capacity-irrelevant. The edge is **neglect plus patient small
capital**, and it is real only where nobody is looking. So: the main desk asks "is this
one of the best businesses on the exchange?"; the low-cap desk must ask **"is this a
mispriced, *surviving* business nobody is looking at?"**

**2. Quality conditioning is what makes small caps investable at all.**
Asness et al., "Size Matters, If You Control Your Junk" (JFE 2018): small firms are on
average junk, and junk is why naive small-cap portfolios die; controlling for quality,
the small-cap opportunity roughly doubles in Sharpe. Campbell/Hilscher/Szilagyi
(2008): the highest-distress decile earned **−17%/yr alpha** — "cheap because dying"
is the single most consistent way to lose money in this universe. Every serious
practitioner enforces the same thing from the other direction: Cassel's "profitable
before scale, doesn't need to raise money to grow"; MicroCapClub excludes the ~82%
speculative/pre-revenue tier wholesale; Royce's balance-sheet-as-insurance. Survival
screening is not a nicety here — it IS the philosophy's first pillar.

**3. Dilution is the dominant capital destroyer, and the main desk's guard is far too
loose for this universe.** Pontiff/Woodgate (2008) and Fama/French (2008): net share
issuance is the *most* statistically robust negative predictor, and one of only two
anomalies pervasive even in microcaps. Practitioner alert levels: >5%/yr moderate,
>10%/yr critical. The main desk's 20%/yr dilution veto is calibrated for large caps;
at $200M, 20%/yr is not a red flag, it is the death spiral already turning. Cassel:
"dilution is my biggest risk as a microcap investor."

**What ai-hedge-fund contributes** (both generations, researched in depth):

- **v1 (the 19-persona zoo, recovered from git history):** the durable content is the
  *thresholds* — Graham's NCAV > market cap and √(22.5·EPS·BVPS); Burry's FCF-yield
  ≥8/12/15% bands, EV/EBIT < 6, net-cash test; Lynch's PEG < 1/2/3 bands; Pabrai's
  45%-weight downside protection (net cash, current ratio ≥ 2, D/E < 0.3); Fisher's
  R&D-in-3–15%-of-revenue sweet spot and margin-stability tests. Its architectural
  lesson is what NOT to do: 19 agents each reinvented FCF yield with contradictory
  thresholds, the LLM could silently overrule the computed score, and parse failures
  became indistinguishable "neutral" votes.
- **v2 (the rewrite, 2026):** the lessons the project itself drew, all of which this
  repo already holds as invariants: compute every number once in code ("the LLM never
  touches the trade"); personas differ in *judgment*, never in *arithmetic*; abstain ≠
  neutral (their version of refuse-never-guess); point-in-time discipline must be
  structural. And one lesson this repo should adopt: **a philosophy is a named,
  versioned spec** (their strategy YAMLs) — not prose scattered through code.
- **What is deliberately NOT imported:** conviction averaging across personas (the
  forbidden merge, invariant 2), LLM-invented confidence percentages (uncalibrated —
  GuruAgents/FinanceBench evidence), and everything downstream of portfolio
  construction (FR11: this system never executes).

---

## 2 · The Low-Cap Constitution (Part II-b — the lane's rubric)

Where the main desk is Buffett→Munger→Naval, the low-cap desk is
**Survive → Lenses → Scuttlebutt**. Three pillars.

### Pillar 1 — Survive first (the Forge)

Junk is the default state of this universe; the first judgement is not "how good?"
but "will it live, without taking your capital to stay alive?" Deterministic probes,
severities counted, never averaged (inversion.py's exact pattern):

| Probe | Test (all computable from Bundle + prices today) | Severity |
|---|---|---|
| Serial diluter | split-adjusted NSI > 10%/yr, or > 5%/yr in 2+ of last 3 years | severe / caution |
| Cash runway | cash + ST investments ÷ TTM operating burn < 12 months (∞ if OCF ≥ 0) | severe |
| Distress | loss-making AND total liabilities/market-equity > 0.5 AND high vol (CHS-style) | severe |
| Delisting jeopardy | close < $1 sustained, reverse split in trailing 24m, or equity < $2.5M | severe |
| Overhang | diluted share count diverging from basic (convertible/warrant load) | caution |
| Accrual mirage | accruals/assets in top quintile (Sloan; persists in small caps) | caution |
| Shell/promotion pattern | dei shell flag; volume/price spike without a filing (review-only) | caution / flag |

Ladder: any severe ⇒ **Forged-out** (no work order, shown with the named failure);
2+ cautions ⇒ **Watch**; else **Survivor**. Thin evidence ⇒ **Unknown**, said out
loud — a probe that cannot certify survival never manufactures it. The Forge is the
lane's Hell-No filter and runs BEFORE any lens (invariant 12's ordering, kept).

### Pillar 2 — Four lenses, side by side, never merged

Personas differ in judgment, not arithmetic (ai-hedge-fund's hardest-won lesson).
Every metric is computed once in the pure layer; each lens is a deterministic
checklist over those shared numbers with its own named thresholds. A lens **speaks**,
stays **silent**, or **refuses** (inputs unmeasured — refuse, never guess). Absolute
anchors, not sector percentiles: 4,099 SEC-merge universe rows carry no sector
metadata, so percentile cohorts are garbage exactly where this lane lives.

- **GRAHAM (deep value / asset floor).** NCAV = current assets − total liabilities;
  speaks at price < ⅔·NCAV/share (classic net-net) or price < Graham Number
  √(22.5·EPS·BVPS) with positive TTM earnings; balance-sheet strength checks
  (current ratio ≥ 2, liabilities/assets < 0.5). Net-nets exist essentially only
  down-cap — the one lens impossible on the main desk.
- **GARP (Lynch/Slater).** PEG < 1 on historical EPS CAGR (Slater strict: ≤ 0.75),
  growth in a **band** 15–30%/yr — both floor and cap, Lynch distrusts >30% —
  cash-backed earnings (OCF/share ≥ EPS), gearing < 50%, growth not from a depressed
  base. The ten-bagger hunting lens.
- **DOWNSIDE (Pabrai/Burry).** Downside floor first: net cash or tangible backing,
  current ratio ≥ 2, D/E < 0.3; then cheapness on normalized (5y-avg) FCF: yield
  ≥ 8/12/15% bands, EV/EBIT < 6–10. Low-risk-high-uncertainty; hated is fine,
  dying is not (the Forge already removed dying).
- **COMPOUNDER (Cassel/Fisher).** Profitable before scale (positive TTM NI *and*
  OCF), self-funding (share count flat/shrinking over 3–5y), margins stable or
  improving, R&D productivity in the 3–15%-of-revenue sweet spot where applicable,
  ROIC quality. The "small company that will become big" lens; its qualitative half
  (owner-operator, niche dominance) belongs to Pillar 3.

The interface shows **four shortlists side by side** — each lens ranks only within
its own logic. A name on two lists is visibly on two lists; the confluence is a fact
the owner sees, never a number the system computes. No composite low-cap score
exists, anywhere, ever (invariant 2 generalized to lenses).

### Pillar 3 — Scuttlebutt (the agent beat)

What Fisher called field work and Cassel calls knowing the business better than
anyone: owner-operator evidence, insider alignment, share-structure cleanliness,
promotion red flags, niche dominance. Unmeasurable from XBRL — this is the research
half, through the existing seam (brief → agent artifacts → mechanical record), with
lens-specific work orders and the same standing bear-case obligation. LLM narrates
and researches; it never scores (GuruAgents/FinanceBench: models emit precise wrong
numbers rather than abstaining — exactly why `record` re-checks everything).

**Position-sizing doctrine (display-only, FR11 untouched):** the practitioners split
cleanly into statistical baskets (Graham: ~30 names, ≤3.3% each) versus researched
concentration (Cassel 5–10, Fisher's 5%-cap for small risky names) — and unanimously:
no leverage on illiquid names, exit measured in weeks, balance-sheet strength as the
substitute for exit liquidity, sell on thesis breakage never on drawdown. The
interface states this doctrine next to each lens; the system still never sizes,
advises amounts, or executes.

---

## 3 · The lane's eligibility (not the main desk's)

| Parameter | Main desk (V-6) | Low-cap desk | Why |
|---|---|---|---|
| Market cap | ≥ $300M | **$50M – $2B** | Below $50M is the promotion/shell tier (MicroCapClub's excluded 82%); above $2B the main desk already covers it. $300M–$2B names appear on BOTH surfaces — different questions, different answers, deliberately. |
| Price | ≥ $5 | **≥ $1** | $5 is a large-cap respectability floor; $1 is the exchange survival line, and the Forge's delisting probe handles the approach to it. |
| Exchange | NYSE/Nasdaq/AmEx | same | OTC stays out: no reliable data, promotion flags live there, fraud density (China-hustle pattern) — journaled, revisitable. |
| Liquidity | — | ADV$ floor **when volume data lands** (phase 4); until then liquidity shown as `Unknown`, loudly | Bars carry close/adj_close only today; a figure we don't have is never guessed (invariant 5). |
| Munger gate | inversion verdicts | Forge (lane-specific probes) **plus** existing inversion | Hell-No before the dossier, both layers. |

---

## 4 · Architecture (Part III-b) — how it lands without breaking an invariant

All 13 invariants bind unchanged; the own-repo report maps each one. The load-bearing
choices:

1. **`stock-scout/lowcap.py` — a new pure module** (no I/O, no clock): the Forge
   probes, the four lenses, and the new metrics they need — NSI, runway months, NCAV,
   Graham Number, PEG on EPS CAGR, EV/EBIT, normalized-FCF yield, overhang gap —
   computed over the exact same Bundle. New metrics that theses may trigger on join
   the registry as lane metrics; composites stay display-only (invariant 6).
   Everything testable the way scoring/inversion are tested.
2. **A fourth tab in the one generator** (`webapp.py`): the stated design goal is one
   generator, two surfaces — a `tab-lowcap` pane with the lane's constitution as
   intro prose, the Forge verdict per name, and the four shortlists side by side.
   Public projections reuse `strip_owner_fields` + allowlists (invariant 3).
   *(Amended same day, owner-directed: the lane gets its **own page** instead —
   `docs/lowcap/index.html`, written by the same `write_site`, same CSS, same
   `docs/data/` shards for drill-downs, linked from the main page's stepper and
   footer. The separateness is the point: a different game, visibly its own desk.)*
3. **Production: same run, same snapshot, own table.** A `select_lowcap` stage after
   `select_top`; a new append-only `production_lowcap_member` table via a new
   numbered migration with the same no-update/no-delete trigger pattern —
   append-only is achieved by adding tables, never altering existing ones
   (invariant 10). One active snapshot, one verified publication (invariant 13).
4. **The agent seam reused wholesale**: `lowcap` briefs through `deskwork.order`
   with lens-specific work-order sections; its own `record` re-checks the lane's
   rules mechanically; ratify stays human and CLI-only (invariant 11); theses live in
   a parallel `theses-lowcap/` tree; the monitor gains the lane's mechanical triggers
   (dilution restart, runway breach) as ordinary registry-metric triggers with
   persistence streaks.
5. **Work-order budget**: top 3 per lens per cycle (max 12 orders, overlap collapses
   them) — the desk's research budget stays bounded and the Forge keeps it honest.

### Phases

- **Phase 0 (this document):** owner ratifies the constitution — the philosophy
  choices, the eligibility band, and the no-composite rule are the decisions that
  need the Gate.
- **Phase 1:** `lowcap.py` pure layer (Forge + lenses + metrics) with tests.
- **Phase 2:** selection + the tab + production stage + migration + release-gate
  checks; site republished by the owner (container agents cannot — real data).
- **Phase 3:** the agent beat (brief/record), thesis flow, monitor integration.
- **Phase 4 (data work, separately sized):** weekly volume into the price grid
  (pricesrc drops the vendor's `v` field today) → ADV$ eligibility + Amihud display;
  EDGAR submissions-JSON filing-cadence dilution score (S-1/S-3/424B/8-K 3.02
  counts); Form 4 insider-cluster feed (SEC bulk dataset, free). Each lands as its
  own journaled change.

### Honest limits, stated up front

- Coverage below $300M is unmeasured in-container; expect thin/partial evidence,
  `INSUFFICIENT` grades and `Unknown` inversion to cluster there. The lane's surfaces
  say so per name rather than hiding the denominator (invariant 5). ~760–814 universe
  symbols are permanently price-unfetchable and concentrate exactly here.
- Going-concern text, insider ownership %, and real spreads need data beyond
  companyfacts; until fetched they are agent-research questions (Pillar 3), never
  silent defaults.
- Split events ride the price fetch; a name served by a splitless grid can read a
  split as dilution — the Forge's diluter probe must use the split-adjusted series
  and refuse where adjustment is unavailable (the pit.py docstrings already warn).
