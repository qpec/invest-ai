# Adversarial valuation review — philosophy, scout metrics, the Top 48, and the UI

**Status:** review, 2026-08-08. Owner ask: *"Review the philosophy, the scout metrics, the
proposed companies. Compare this to a deep research on how to value good investment
opportunities. Adversarially propose improvements in the system as well as UI for user
comprehension."*

**Method.** A 25-agent adversarial review: four readers mapped the code (scoring engine,
risk/monitor layer, candidate funnel, UI), five researchers built cited evidence briefs
(factor research, practitioner valuation, moat assessment, screen failure modes,
decision-process/UI research), four critics attacked the system against those briefs, and a
skeptic pass tried to refute the twelve highest-severity findings against the repo and the
web. Zero findings were refuted outright; three were CONFIRMED as stated and nine survived
with corrections. Findings below carry their verification status:

- **CONFIRMED** — the skeptic pass (or a direct in-repo check for this document) verified the
  load-bearing evidence.
- **VERIFIED, NUANCED** — the core defect stands but the critic's framing or fix was wrong;
  the corrected version is what appears here.
- **REPORTED** — a critic's finding whose cited evidence was consistent but which did not get
  an independent verification pass. Weigh accordingly.

Nothing here proposes changing the constitution. The constitution is the strongest artifact
in the repo; almost every finding is a place where the implementation is *less* Buffett,
*less* Munger than the text in CLAUDE.md demands.

---

## 0. Executive summary

1. **"Exceptional" is substantially a cheapness label.** 34 of 48 Top-48 names are carried by
   the single owner-FCF-yield anchor; it is the card's largest anchor (15/25 price points),
   it saturates at 8% — so DXC at a 41.6% yield (the market pricing terminal decline) scores
   those 15 points identically to Adobe at 8.0% — and the same trailing yield is also the
   whole V pillar, the DCF base, and the valuation lens. One fact, counted four times, with
   no distress regime above the target. The research is unambiguous that cheap-with-
   deteriorating-fundamentals earns no value premium (Piotroski & So 2012; Penman's "value
   buys risky growth").
2. **The Munger layers exist but are advisory exactly where the money is.** The desk's Top 48
   is ranked by scorecard alone (`thesis.py:468-476`): 8 of 48 names are Fragile or Ruinous,
   26 of 48 are Unknown, and all 48 drafts were accepted — by a single model, with zero
   ratifications ever. `picks.shortlist()` refuses precisely these names
   (`picks.py:49-51,102-107`), so the repo's two public surfaces state opposite editorial
   positions about the same eight companies. A circle-of-competence classifier exists
   (`scoring.tier_of`, `scoring.py:481-489`) and gates nothing.
3. **The valuation machinery has three structural defects.** Trailing-TTM yields with no
   normalization put five cyclicals in the Top 48 at what their own packets describe as peak
   conditions (DINO, ARLP, SSRM, NVGS, PLAB); the DCF discounts post-interest (equity-level)
   owner-FCF at WACC, systematically inflating margin-of-safety for leveraged names; and
   every company on earth gets beta = 1.0 (`scoring.py:791-805`) — a coal MLP and Adobe share
   a 10.5% cost of equity.
4. **The input hygiene is not ready for the weight it carries.** Sector labels are provably
   wrong on Top-48 names (Stride is percentiled as "Consumer Staples", Bath & Body Works and
   Upwork as "Industrials", Nutex as "Information Technology"), corrupting every sector-
   percentile surface including the valuation lens; and there is no liquidity or integrity
   floor, so a $1.02 microcap, a negative-equity $1.58 stock, and a 91.5%-related-party
   roll-up rank beside Accenture as peers.
5. **The UI communicates less than the pipeline knows.** The valuation lens prints "appears
   inexpensive" on 47 of 48 cards (checked in the built page) — an informationless,
   accent-highlighted signal; thesis cards print a fabricated "/100" denominator; "Unknown"
   (the majority risk verdict, 26/48) is the *quietest* pill on the page; the stated ±5-point
   noise floor appears nowhere; and a page whose constitution celebrates inaction renders 48
   cards with exactly one affordance each — engage.

The single most important structural insight, which several findings share: **the system's
own honesty artifacts (inversion caveats, packet texts, picks.py's editorial rules) already
contain nearly everything needed to fix the slate — they are just not wired into the
decisions or the display.** The caveat on TDC's card says the cash engine fell 97%; the rank
says #7 of 5,763. The fix is mostly plumbing honesty it already computes.

---

## 1. What the research says (the measuring stick)

Each claim below is from the review's evidence briefs, with the source the brief cited.
This is the standard the findings in §2–§4 are measured against.

**Owner earnings and maintenance capex.** Buffett's 1986 definition explicitly makes
maintenance capex "a guess — and one sometimes very difficult to make," an *average annual*
requirement to maintain competitive position — not the lower of two accounting lines.
`min(|capex|, D&A)` is an asymmetric truncation: it can only ever raise computed owner-FCF,
flattering heavy reinvestors in expansion and — worse — flattering under-investors milking an
asset base, which is exactly when competitive position erodes (Mauboussin & Callahan,
"Underestimating the Red Queen": true maintenance investment, including intangible spend, is
usually *larger* than naive proxies imply).

**Which profitability measure predicts.** Cash-based operating profitability subsumes the
accruals anomaly and predicts returns up to ten years out (Ball, Gerakos, Linnainmaa &
Nikolaev, JFE 2016); gross profitability is the cleanest single line (Novy-Marx, JFE 2013).
Value and profitability are not independent alpha sources — the joint sort is what matters
(Fama-French 2015: RMW+CMA make HML redundant in US data). The system's Q pillar is
reasonably aligned here; its V pillar is not (see V-1).

**Value traps.** The cheapest names embed the highest earnings risk ("value buys risky
growth" — Penman & Reggiani). Piotroski (2000) exists precisely because a raw cheapness sort
needs a financial-health overlay to separate winners from losers — and this repo computes
Piotroski F but keeps it display-only. Trap markers with practitioner consensus: 3+ periods
of revenue decline, capital returns exceeding FCF, margin compression at high trailing
yield. DXC's consensus forward FCF is ~40% below trailing — a trailing yield roughly double
the forward economic yield.

**Cyclicals.** Trailing multiples are lowest at the exact top of the cycle (the Molodovsky
effect). Every practitioner remedy — Graham's 7–10-year average earnings, Shiller's CAPE,
mid-cycle margins — replaces the trailing numerator with a normalized one for
commodity-price-driven businesses. A screen with no normalization will reliably surface
refiners, miners and shippers at peak and rank them "cheapest."

**DCF practice.** Damodaran: the discount rate must match the cash-flow level (equity flows
at cost of equity, firm flows at WACC); terminal value dominates and small
growth/discount-rate inconsistencies swamp everything else; single-point DCFs mislead —
ranges and scenario weights are the honest output. Mauboussin & Rappaport's expectations
investing inverts the exercise: read the growth the price *implies*, then judge whether it's
plausible — far more robust in a screen than forecasting growth yourself.

**Moats.** Morningstar defines moat in cash-flow terms (excess returns on capital
persisting 10–20 years), requires quantitative *and* qualitative evidence, and rates
multi-label — 75% of wide-moat firms cite more than one source. Base rates: only ~14–17% of
a quality-skewed coverage universe earns "wide"; ~43% earn none. A labeler that names a moat
for 46 of 48 companies (96%) is miscalibrated on priors alone. Falsifiable switching-cost
claims require retention/NRR/churn evidence; "customers are locked in" without a retention
series is a story.

**Decision process.** Pre-mortems raise failure-mode identification ~30% (Klein; endorsed by
Kahneman). Mauboussin: journal what you believed and expected *at decision time*, so process
can be judged separately from outcome. Morningstar pairs every fair-value estimate with an
explicit **uncertainty rating** that widens the required margin of safety — uncertainty is
priced, never free. UI research on scores: point estimates with ordinal ranks manufacture
false precision; ranges, bands and "this difference is noise" statements are the honest
rendering; and a pair of judgments presented as equal siblings invites users to mentally
average them — the exact error a veto system exists to prevent.

---

## 2. The funnel vs. its own constitution

### F-1 · The desk feed and the picks report disagree about the same eight names — VERIFIED, NUANCED

`picks.shortlist()` refuses any name with a severe probe or a Fragile/Ruinous verdict, as
its stated editorial position (`picks.py:38-51`). `thesis.top_symbols()` ranks by scorecard
alone (`thesis.py:468-476`), so the desk spent 8 of its 48 work orders on names the shortlist
refuses to carry: TDC (#7), CCSI (#21), CRI (#33), SIG (#41) Fragile; MTCH (#8), SSRM (#17),
IRWD (#29), DXC (#37) Ruinous. All eight are "draft accepted." The `thesis.top` summary array
doesn't even carry the verdict field (`webapp.py:575-582`), so the public Top-48 tab presents
them typographically as peers.

The skeptic pass is right that this is *documented* design, not a silent bug: THESIS-DESIGN
requires drafts to address every severe finding in the bear case, and the Gate is the human
rejection point. But the constitution's order is "circle check → Hell-No veto → Buffett
dossier → owner judgment," and here a fifth of the desk's research budget flows to names the
system's own Munger layer has already flagged, while the two public surfaces state opposite
positions.

**Improvement (owner decision, journal it either way):** *don't* filter inside
`top_symbols` — that would shift ranks baked into `research_fingerprint` and break the
never-reconcile rule. Instead (a) add the verdict to each `thesis.top` entry and render
Fragile/Ruinous cards under an explicit "fails the shortlist's fragility tests — research
draft, not a candidate" partition, mirroring `picks.strong_but_fragile`; or (b) ratify a
policy that the desk feed applies the shortlist's two tests, with an explicit
`--include-fragile` escape hatch. Either way the two surfaces must stop disagreeing.

### F-2 · Circle of competence gates nothing — CONFIRMED

The constitution's first gate has a working implementation — `scoring.tier_of()` classifies
every name Core/Adjacent/Outside (`scoring.py:481-489`) and it is computed for every graded
row — but no selection step, work order, `record`, or `ratify` ever reads it. The result is a
Top 48 where roughly two-thirds sit outside "cloud infrastructure, healthcare/insurance
tech, SaaS, AI tooling": a coal MLP (ARLP), a gold miner (SSRM), an oil refiner (DINO), an
LPG shipper (NVGS), jewelry (SIG), children's apparel (CRI), footwear (CROX), mall retail
(BBWI), remittances (WU), executive search (KFY), construction fasteners (SSD).

**Improvement:** make the tier a visible dimension of the funnel: print it on every card and
row; quota the desk feed (e.g. work orders spend ≥60% on Core/Adjacent) or route Outside
names to a separate "outside your circle — study only" section. The classifier exists; this
is wiring, not modeling. (FR9 keeps the *personal* circle judgment at ratify — this is the
coarse pre-sort the constitution describes.)

### F-3 · The moat requirement is unenforced — CONFIRMED (mechanics), REPORTED (label quality)

Pillar 1: "at least one durable competitive advantage, with evidence." The schema permits
`moat.kind: "none"` and `validate()` has no moat rule at all (`thesis.py:121-131, 223-276`);
SSRM and NUTX carry `kind: "none"` at ranks 17 and 27, Exceptional band, drafts accepted.
Meanwhile the labeler names a moat for 46 of 48 (96%) against Morningstar's ~57% base rate
on a *quality-skewed* universe — with `brand_trust` going to CROX, BBWI, SIG, CRI (fashion
retail with collapsed cash engines) and `switching_costs` to the three most documented
melting ice cubes on the list (TDC, DXC, MNDO). Both directions are miscalibrated: "none"
should be constitutional PASS, and "named" should be hard to earn.

**Improvement:** in `validate()`: `kind ≠ "none"` requires non-empty evidence including at
least one *quantitative* series (retention/NRR for switching costs, realized price increases
for brand, unit-cost gap for cost advantage); `kind = "none"` forces the draft to
PASS-RECOMMENDED status — renderable, but `ratify` refuses it without an explicit typed
override. Longer term, adopt multi-label moat with a strength field (none/narrow/wide);
Morningstar's modal wide-moat company cites more than one source.

### F-4 · The judgment stage has never said no — VERIFIED, NUANCED

48 work orders → 48 accepted drafts → 0 ratified, all authored by one model
(`gpt-5.6-sol`), including the four Ruinous names whose own caveats read as bear cases.
`record` checks schema, model rule and trigger mechanics — by design it validates the
contract, not the judgment (`thesis.py:417-465`). Which means the funnel currently has *no*
judgment stage at all between the scorecard and the owner: a 100%-pass stage is a formatter,
not a filter. Compounding it, the monitor/journal half of the loop has never run in
production (`committed: 0`), so the flagship output is 48 unratified research documents and
the system's celebrated "no action needed" state has never once fired.

**Improvement:** (a) give the agent an explicit PASS verb — the work order should state that
"this fails the framework, here is why" is a first-class, *expected* outcome (the
constitution: "You'll miss some winners; you'll also avoid catastrophic losses"), and the
run summary should celebrate the pass count; (b) throttle work orders (e.g. 5/week) so 48
simultaneous "buy candidates" cannot exist as a surface; (c) ratify 2–3 in-circle names now
so the monitor, sticky-broken logic and decision journal execute on real data before the
system is trusted further; (d) require a second approved model (or the same model on fresh
data) to countersign any event-trigger break verdict — one model currently is the whole
judgment layer.

### F-5 · Uncertainty is free — REPORTED

26 of 48 verdicts are Unknown — the layer explicitly saying "I could not certify this" —
and Unknown costs nothing anywhere: same eligibility, same rank, same acceptance path as
Ordinary. Morningstar's system makes uncertainty *widen the required margin of safety*;
here it doesn't even change a pixel's weight (§4, U-4). Meanwhile "Ordinary" reads as
certification on names whose packets describe related-party roll-ups and arbitration-funded
windfalls, because the verdict conflates evidence coverage with risk reading.

**Improvement:** split the two axes — evidence coverage (full/partial/skipped) and risk
reading (Robust→Ruinous) — and price Unknown: an Unknown name needs a higher band (or its
two mandatory probes measured) before a work order is written. Bootstrapped names whose
filings text was skipped should say so, not wear the same pill as a tested survivor.

---

## 3. The valuation machinery

### V-1 · One trailing yield, counted four times, blind above 8% — CONFIRMED

TTM owner-FCF / own EV is: the entire V pillar (25% of the composite,
`scoring.py:699-704`), the card's largest anchor (15/25 price points, saturating at 8%,
`scorecard.py:71-74`), the DCF's base-flow input, and the public valuation lens. The ramp's
saturation means the card cannot distinguish "fairly cheap" from "priced for terminal
decline": DXC (41.6%), NUTX (31.3%), MNDO (29.7%), TDC (29.4%), AREN (24.0%), CRI (20.4%)
all collect exactly the same 15.0/15 as a healthy 8% name, and 17 of 48 sit above 12%. The
research verdict on this shape is unambiguous: high yield with deteriorating fundamentals
is the value-trap signature, not the bargain signature (Piotroski & So 2012; Penman).

**Improvement:** two changes, both cheap. (a) A **congruence gate** on the top bands:
Exceptional/Strong additionally require the fundamentals not to contradict the price — e.g.
revenue not down 3+ consecutive annual periods, capital returned ≤ owner-FCF, owner-FCF/share
trend not in the bottom decile. The repo already computes Piotroski F and keeps it
display-only; a "no top band below F=5" rule is one line and pure Munger. (b) A **distress
regime** above the target: beyond ~15% yield the anchor stops adding points and the card
prints "priced for decline — the market is voting no" (the two-sided signal U-2 needs).
Neither change touches the never-reconcile rule — vetoes suppress, they don't average.

### V-2 · Trailing yields on cyclicals at cycle peak — CONFIRMED

DINO (#11, refining — its own packet: "may be a peak-period illusion"), ARLP (#32, coal),
SSRM (#17, gold at record prices; cash engine 100% negative in 2024 per its packet), NVGS
(#28, LPG day-rates), PLAB (#39, semi cycle). Trailing-TTM assembly with zero normalization
(`scoring.py:144-202`) guarantees the screen surfaces commodity businesses at exactly the
wrong moment — the Molodovsky effect, the single best-documented failure mode of mechanical
value screens.

**Improvement:** for a declared set of commodity-cyclical sectors, replace the yield
numerator with a normalized owner-FCF — median (or 0.7×mean) of the last 5–7 annual
owner-FCF observations, which `annual_owner_fcf` already produces — and label the card
"mid-cycle basis." Where the normalized figure can't be built, the honest output is NO
PRICE-style refusal for the yield anchor, not the peak number. (The universe already carries
sector; the sector map needs V-5 first.)

### V-3 · The DCF discounts equity-level flows at WACC, with uniform beta 1.0 — VERIFIED, NUANCED (mechanism corrected)

Owner-FCF is OCF − min(|capex|, D&A) − SBC, and US-GAAP OCF is *after* cash interest — an
equity-flavored flow. `margin_of_safety` discounts it at WACC (`scoring.py:869`), which for
leveraged names sits *below* the 10.5% cost of equity, systematically inflating intrinsic
value and MoS exactly for leveraged names. (The naive fix — subtract net debt — would
double-count debt service; don't.) On top: beta is hard-coded 1.0 for every business
(`scoring.py:796`), no size premium exists for the microcaps on the slate, and the
docstring still calls MoS "shadow — never scored" (`scoring.py:842`) while the scorecard
scores it 10/25 price points and it single-handedly carries BLKB (#42, "+67%") into the
Strong band.

**Improvement:** minimal and clean — discount owner-FCF at the cost of equity (already
computed inside `wacc_estimate`; expose it), keeping the market-cap comparison
level-consistent. Add a regression test asserting MoS no longer *rises* with leverage, fix
the stale docstring, and surface the DCF's inputs wherever its output is scored (U-7).
Consider replacing the point-estimate MoS entirely with the expectations-investing form:
report the growth rate the current price *implies* at the required return ("price implies
+9%/yr owner-FCF growth for a decade") — for a screen, a number the owner can falsify beats
a number the owner must trust. Also honestly reconsider whether `max(TTM, 0.85·3-yr avg)`
as the base flow (`scoring.py:857`) should be `min` or the average for anything cyclical —
"max" institutionalizes the peak.

### V-4 · min(capex, D&A) flatters exactly the wrong companies — VERIFIED (definition), REPORTED (magnitude)

The maintenance-capex proxy can only ever raise owner-FCF relative to plain FCF. It
flatters heavy reinvestors (fine — that's its purpose) but equally flatters under-investors
whose capex has fallen below true maintenance: a company milking its asset base screens as
a *rising* owner-FCF machine precisely while its competitive position erodes — several of
the slate's melting ice cubes (WU, TDC, DXC) are in their harvest phase, where this proxy is
most generous. Buffett's own definition is an average annual requirement to *maintain
competitive position*, explicitly a judgment call.

**Improvement:** keep the formula (it's declared and consistent) but add a **harvest flag**:
capex < 60% of D&A for 2+ consecutive years AND revenue declining → flag the owner-FCF
figure as "harvest-mode: maintenance likely understated," exclude the name from full yield
points, and pipe the flag into the work order. Sector-median capex/revenue is a cheap
cross-check the registry can carry.

### V-5 · Sector labels are wrong, and every percentile inherits the error — CONFIRMED

Checked in the built page: Stride/LRN is percentiled in "Consumer Staples", Bath & Body
Works and Upwork in "Industrials", Nutex (ER hospitals) is "99th percentile in Information
Technology." The sector percentile is the V-pillar's cohort, the formation's entry gate,
and the valuation lens's comparison scope (33 of 48 lens readings are sector-scoped) — a
wrong label silently distorts the one decision rule that was actually walk-forward
validated, plus the headline the owner reads.

**Improvement:** validate the sector map against SIC codes from the SEC companyfacts already
being fetched (a one-off diff report catches these four and every other mislabel), and
until fixed, render *both* percentiles on the lens ("94th of 1,719 universe · 99th of 181
sector") so a wrong cohort can never be the sole anchor.

### V-6 · No liquidity or integrity floor — REPORTED (spot-checks confirmed by critics)

The funnel applies no market-cap, price, ADV or integrity screen: MNDO ($1.02 microcap,
revenue shrinking, a known 2027 non-renewal), AREN ($1.58, negative shareholder equity),
SBC Medical ($2.97; its own packet records 91.5% related-party revenue and unresolved
internal-control weaknesses) rank as peers of ACN and ADBE. For a 10–15-position
concentrated portfolio this is pure noise in the desk's attention budget — and "management
we don't trust" is a Hell-No item that currently lives only in caveat prose.

**Improvement:** an eligibility floor on the desk feed (e.g. mcap > $300M and price > $5),
and promote two packet facts into inversion probes that count: majority related-party
revenue, and unresolved material weakness — both severe. That is Munger's checklist doing
what checklists are for.

### V-7 · The slate rides one macro bet in three costumes — REPORTED

Sector-agnostic cheapness has concentrated the list: AI-disruption-discounted IT services
(CTSH, DXC, EPAM, G, IBEX, ACN, TDC…), binary-risk pharma (HRMY, PBYI, IRWD, ANIP, HALO),
and peak commodities (DINO, ARLP, SSRM, NVGS). A portfolio built off this list top-down
would be short "AI eats services revenue," long "commodity prices stay here" — neither a
bet the constitution chose. **Improvement:** show bucket concentration on the slate (a
one-line tally by sector/theme), and cap any single theme in the desk feed.

### V-8 · Assorted mechanical fragilities — REPORTED

The registry's own "No price triggers" contract carves out the one quote-derived metric
(`registry.py:18-19`) and `owner_fcf_yield_pct` remains trigger-eligible — a price rally
can mechanically trip a "business" trigger; the scorecard that produces the headline slate
is the one ranking never walk-forward validated (SCORECARD-DESIGN §6 says so itself — the
validation harness in `backtest3.py` exists and should be run with the scorecard as the
engine); self-funding has a cliff at exactly 0 owner-FCF; gross-margin CV explodes near
zero-margin; the annual TTM fallback picks income and cashflow windows independently
(`scoring.py:172-173`).

---

## 4. The proposed companies, name by name

Review reading of the current slate (2026-08-07 build). "In-thesis" means: inside or
adjacent to the owner's circle, no unresolved trap/peak/integrity signature — *worth the
Gate's homework*, which is all a scout can honestly certify.

| # | Name | Reading |
|---|------|---------|
| 1 | INMD | Edge-of-circle medtech. Real cash machine, but cash engine −55% from peak, patent injunction risk, consumables thin. The 96/100 overstates; the caveat has it right. |
| 2 | LRN | Out of circle (K-12 education), mislabeled Consumer Staples. Decent business; percentiles corrupted. |
| 3 | CROX | Out of circle; fashion risk wearing a "brand_trust" label the evidence doesn't earn. |
| 4 | CTSH | In circle. IT services at a fair price; carries the AI-disruption theme (V-7). Legitimate Gate candidate. |
| 5 | PYPL | Adjacent (fintech). Network-effect claim contestable both ways; scale real. Gate-worthy with a hard look at competitive squeeze. |
| 6 | HRMY | Out of circle: single-drug specialty pharma; regulatory moat = patent cliff risk inverted. |
| 7 | TDC | **Trap signature.** Fragile; 29.4% yield; revenue −5%; "switching costs" on a business being unbundled by the cloud it must move to. |
| 8 | MTCH | Ruinous verdict, rank 8. Network effects real but demand-side eroding; the two judgements disagree and the UI shouldn't present them as equals. |
| 9 | ADBE | In circle, in-thesis. The reference case for "wonderful at fair": 8.0% yield exactly at target, no distress signature. Gate-worthy. |
| 10 | BBWI | Out of circle, mislabeled Industrials; mall retail with leverage. |
| 11 | DINO | **Peak-cycle refiner** scored on record crack spreads. Textbook Molodovsky. |
| 12 | UPWK | Adjacent (marketplace SaaS), mislabeled Industrials. Real network effect claim; AI-substitution bear case is the whole question. |
| 13 | YELP | Adjacent. Cash-generative; strategic dead-end risk; fine research candidate. |
| 14 | ALC | Adjacent healthcare devices. Genuine quality; least controversial top-15 name beside ADBE. |
| 15 | CHKP | In circle. Cybersecurity cash machine, slow-growth; classic quality-value. Gate-worthy. |
| 16 | NICE | In circle. Real switching costs; AI-repricing bear case; Gate-worthy. |
| 17 | SSRM | **Ruinous, moat "none", gold miner at record gold** — three separate constitutional PASSes at rank 17. The clearest single indictment of the funnel. |
| 18 | UTMD | Adjacent medical devices; illiquid family-run compounder; fine, small. |
| 19 | PAYC | In circle, in-thesis. HR SaaS, real ROIC; growth deceleration is the thesis question. Gate-worthy. |
| 20 | PBYI | Out of circle; single-product oncology pharma. Binary risk. |
| 21 | CCSI | Fragile; declining fax-workflow business at 9% yield; harvest-mode signature (V-4). |
| 22 | EPAM | In circle. AI-disruption theme; strong balance sheet; Gate-worthy with V-7 in mind. |
| 23 | GMED | Adjacent med-devices; robotics-led share gains; legitimate. |
| 24 | ZD | Adjacent digital media roll-up; declining core; roll-up accounting deserves the skeptic pass. |
| 25 | ACN | In circle, in-thesis. The quality-at-fair-price case with real bookings evidence. Gate-worthy. |
| 26 | MNDO | **Integrity/liquidity floor case:** $1 microcap, shrinking, known non-renewal, yet "switching_costs" at 29.7% yield. |
| 27 | NUTX | **Regulatory-arbitrage windfall**, moat "none", percentiled against IT. Its yield is a bet on a federal dispute process. |
| 28 | NVGS | Out of circle; LPG shipping day-rates at cycle levels. |
| 29 | IRWD | Ruinous, out of circle; single-asset pharma with debt. |
| 30 | WU | **Melting ice cube in harvest mode**; 14.8% yield priced for the decline it is experiencing. |
| 31 | G | In circle-adjacent (BPO); AI-disruption theme; plausible but crowded with better in-list options. |
| 32 | ARLP | Out of circle; **coal MLP at peak distributions**. |
| 33 | CRI | Fragile; children's apparel, cash down $556M→$48M per its own caveat; brand label unearned. |
| 34 | MZTI | Microcap with integrity flags per packet; liquidity floor case. |
| 35 | RMD | Adjacent healthcare devices, in-thesis. GLP-1 bear case is testable; quality real. Gate-worthy. |
| 36 | ANIP | Out of circle; generics/specialty pharma. |
| 37 | DXC | **Ruinous, 41.6% yield, consensus FCF −40% forward** — the slate's purest value trap, wearing "switching_costs." |
| 38 | INTU | In circle, in-thesis. Wonderful business; the debate is price vs. AI both as risk and moat-deepener. Gate-worthy. |
| 39 | PLAB | Semi-cycle capex play at cycle pricing. |
| 40 | SBC | **Integrity floor case:** 91.5% related-party revenue per its own packet; "Ordinary" verdict is the calibration failure F-5 describes. |
| 41 | SIG | Fragile; jewelry retail; lease-adjusted leverage; brand label unearned. |
| 42 | BLKB | In circle. Entire band rests on an uninspectable +67% MoS from the miscalibrated DCF (V-3) — fix the DCF before trusting the rank. |
| 43 | HALO | Adjacent biopharma platform; royalty cliffs are the question; researchable. |
| 44 | IBEX | Adjacent BPO; AI theme again; fine, small. |
| 45 | KFY | Out of circle; cyclical executive search. |
| 46 | SSD | Out of circle; housing-cycle exposure; good business, wrong desk. |
| 47 | VMD | Adjacent home-respiratory care; reimbursement risk; small but coherent. |
| 48 | AREN | **Negative equity, $1.58 media microcap at 24% yield** — should not survive any eligibility floor. |

Score for the funnel: roughly **10–12 of 48 are what the constitution says the desk should
be studying** (ADBE, ACN, INTU, PAYC, CHKP, NICE, EPAM, CTSH, RMD, ALC, BLKB-after-V-3,
PYPL/UPWK arguably). The other ~75% of the desk's research budget went to out-of-circle
names, peak cyclicals, integrity cases and priced-for-decline traps. That is not a scoring
bug to patch — it is the compounded effect of F-1…F-5 and V-1…V-6, and it is exactly what
the constitution's ordering (circle first, Hell-No second, Buffett third) exists to prevent.

---

## 5. The UI — user comprehension

The page's two standing rules (judgements never merged; owner fields never rendered) are
honored, and provenance badges, trigger safety margins and the three-tab pipeline mapping
are genuinely good. The findings are about what the page *doesn't* say.

### U-1 · Ruinous names rank top-10 with no visual gating — REPORTED (facts confirmed)

MTCH #8, SSRM #17, IRWD #29, DXC #37 render as two equal-sized sibling boxes ("Business
quality 88/100" beside a small "Ruinous" pill) with the same accent CTA as every other
card. Two equal siblings invite mental averaging — the exact error the never-merge rule
exists to prevent; equality of visual weight *is* a merge. **Fix:** verdict-conditional
layout: Fragile/Ruinous render a full-width warning banner above the quality box, muted
score treatment, and the CTA reworded "View the bear case" — different affordance, same
information, no reconciliation.

### U-2 · The valuation lens prints "appears inexpensive" on 47 of 48 cards — CONFIRMED

Checked in the built page: 47 × "Appears inexpensive on current owner cash flow", 1 ×
"somewhat inexpensive." A signal that fires identically for everything carries zero bits —
while holding the card's only accent highlight. It is also circular: names reach the Top 48
*because* of high yield, then the lens congratulates the yield. **Fix:** make
`valuation_signal()` two-sided: above a distress threshold (or when the caveat names a
severe cash-engine finding) emit "priced as if this cash flow will not last — the market is
voting no." Cheapness language should get *less* confident as yield rises past the target,
not more.

### U-3 · Cards fabricate a "/100" denominator — CONFIRMED (latent today)

The reader glance hard-codes `'/100'` (`webapp.py:1649`) while the pipeline's honesty rule
is score-of-available-max ("48/75, never 48/100"). All 48 current names happen to be
full-evidence, so the lie is latent — but the surface will misreport the first
partial-coverage name silently. **Fix:** ship `available_max` in the reader quality object
and render "72/100 · full evidence" or "48 of 67 measurable (72%) · partial" with the
existing evidence-tier chip.

### U-4 · "Unknown" — the majority verdict — is the quietest element on the page — REPORTED (facts confirmed)

26 of 48 cards carry Unknown rendered as the ghost pill (dashed border, faint text), with
its meaning ("could not certify — a fact about evidence, not safety") explained only in a
hover tooltip on a different tab. Faint styling tells the eye "ignorable." **Fix:** a
loud-but-neutral treatment (solid border, hatched background, label "Not certified") plus
one line of microcopy on the card naming *why* (e.g. "filings text skipped — bootstrapped
name"), and the count surfaced on the tab header: "26 of 48 could not be risk-certified."

### U-5 · False precision everywhere, noise floor nowhere — REPORTED (grep confirmed)

Integer scores, #1–#48 ordinal ranks, one-point distinctions (ranks 36–48 span 78–79) —
and the design's own ±5 noise floor appears nowhere in the rendered page (no "noise", no
"±" anywhere in `webapp.py` output). **Fix:** band-first presentation: cards lead with the
band, exact score one click down; divider rows in the grid ("scores 78–79 — order within
this group is not meaningful"); a one-line noise-floor statement in each tab's intro.

### U-6 · The page is structurally a 48-item buy menu — REPORTED

The constitution celebrates "no action needed" as a first-class output; the Thesis tab
renders 48 cards, every one terminating in a single engage affordance, no way to record a
pass, no base-rate statement that most candidates *should* fail the Gate. **Fix:** a
per-card "Pass — record why" affordance writing through the existing desk-note plumbing
into the decision journal (F-4's missing verb), cards graying into a persistent "Considered
and passed (N)" section — making inaction visible, countable, and celebrated in the run
summary.

### U-7 · The decision-relevant text is buried; assumptions are uninspectable — REPORTED

The caveat — which contains the severe findings (TDC "cash engine fell 97%", SBC "91.5%
related-party") — sits four sections deep as a 300-word blob while "appears inexpensive"
leads the card; the carrying metric ("carried by owner-FCF yield 15/15") never reaches the
card even though quality-and-valuation are then the same fact twice; and no surface shows
the DCF inputs behind a scored "+67% margin of safety" (BLKB's entire band). **Fix:** card
shows the caveat's first severe finding as one line under the valuation box; a "score led
by" chip with microcopy when the leader is the yield ("the quality grade is also led by
this yield — not independent confirmation"); an assumptions fold (base FCF, growth,
discount rate, method) wherever MoS is scored — Morningstar-style assumption disclosure is
the retail-product baseline, not a professional extra.

### U-8 · Smaller confirmed items

Sector cohort mislabels reach the lens headline (V-5) and the sector-vs-universe scope
switch is silent; trigger safety bars encode state by hue alone (add position/length);
hard-coded "48" copy; "Sev · Cau" unexplained; a Dutch-only disclaimer on an otherwise
English page.

---

## 6. Prioritized improvement plan

> **Implementation status (2026-08-08, same day — the "fix proposals" pass):** P0 items
> 1–7 are implemented, plus two P1 corrections: the DCF now discounts at a *levered* cost
> of equity with strict-inequality leverage tests (item 10), and `owner_fcf_yield_pct` is
> refused as a trigger metric (item 13b). Changes journaled in THESIS-DESIGN.md §9.
>
> **A review of that implementation caught four defects in it, all now fixed** — recorded
> here because the process point matters more than the patches: the Pillar-1 moat gate was
> bypassable by *omitting* the moat field (and crashed on a non-dict moat, since the schema
> is prose in the work order, not a validator); the eligibility floor read price from a key
> the CLI path never populates, so `batch` and the site computed different top-1% sets; and
> the DCF fix itself was misjustified — discounting at a *flat* cost of equity raised
> leveraged names ~1.8–2.3× and made the margin of safety blind to the balance sheet,
> with a regression test too weak to catch it. V-3's diagnosis stands; its first fix
> did not. See THESIS-DESIGN.md §9 for the corrected mechanism.
>
> Notes: item 1
> shipped as the *label-and-partition* variant (the verifier's recommendation — filtering
> `top_symbols` would shift fingerprinted ranks); item 6's severe-probe promotion
> (related-party / material-weakness) is deferred — those facts live in filings text, not
> in bundles, so a mechanical probe needs a data path first; the U-6 "record a pass"
> affordance is deferred with it (it needs the journal verb from item 14). The remaining
> P1/P2 items are modeling-policy decisions that stay proposals until the owner ratifies
> thresholds (congruence gate, mid-cycle normalization, circle quota, sector-map fix,
> walk-forward).

**P0 — this week, small diffs, no modeling decisions.**
1. Add the inversion verdict to `thesis.top` entries; partition or tag Fragile/Ruinous
   cards on the Thesis tab (F-1, U-1). Journal the policy either way.
2. Two-sided valuation signal + caveat's first severe finding on the card (U-2, U-7).
3. Fix "/100" to score-of-available (U-3). Surface "carried by" on the card (U-7).
4. Unknown restyled + counted + explained; verdict split into evidence × risk is P1, the
   styling is P0 (U-4, F-5).
5. Moat rule in `validate()`: no-moat → PASS-RECOMMENDED; evidence required otherwise (F-3).
6. Eligibility floor for the desk feed (mcap/price), and related-party / material-weakness
   promoted to severe probes (V-6).
7. Fix the stale "shadow — never scored" docstring; print DCF inputs where MoS is scored
   (V-3, U-7).

**P1 — the next iteration, modeling changes with tests.**
8. Congruence gate on top bands (revenue trend / capital-returns-vs-FCF / Piotroski floor)
   and the distress regime above ~15% yield (V-1).
9. Normalized mid-cycle owner-FCF for commodity-cyclical sectors (V-2).
10. DCF: discount owner-FCF at cost of equity; regression test that MoS no longer rises
    with leverage; revisit `max(TTM, 0.85·avg)` for cyclicals (V-3).
11. Sector map validated against SIC; both percentiles rendered on the lens (V-5).
12. Circle tier wired into the funnel as quota/partition + shown everywhere (F-2).
13. Harvest flag on min(capex, D&A) (V-4). Remove `owner_fcf_yield_pct` from
    trigger-eligible metrics (V-8).
14. PASS verb + journaled passes + work-order throttle + noise-floor/band-first UI
    (F-4, U-5, U-6).

**P2 — structural.**
15. Walk-forward the scorecard ranking itself through `backtest3.py`'s pinned halves —
    until then, every slate carries the "not validated" stamp picks.py already prints (V-8).
16. Expectations-investing line ("price implies X%/yr for 10y") beside or replacing the
    point-estimate MoS (V-3).
17. Multi-label moat with strength + quantitative evidence standards (F-3).
18. Second-model countersign for break verdicts; close the loop by ratifying 2–3 in-circle
    names and letting the monitor run (F-4).
19. Evidence-coverage / risk-reading split in the inversion verdict (F-5).

---

## 7. What was checked and how (verification appendix)

- **Skeptic-verified (12):** V-1 (two findings, one CONFIRMED), V-2 (CONFIRMED), V-3, F-1
  (two findings), F-2 (CONFIRMED), F-3 (mechanics), F-4, plus the philosophy framings of
  V-1/F-1. Zero refuted; corrections incorporated above.
- **Inline-checked for this document:** 47/48 lens signals; sector labels LRN/BBWI/UPWK/NUTX;
  `registry.py:18-19` carve-out; `webapp.py:1649` "/100"; `thesis.top` omits verdict;
  `top_symbols` / `shortlist` divergence; DCF constants (`scoring.py:791-872`);
  verdict ladder calibration note (`inversion.py:56-99`).
- **Reported (critic-verified evidence, no independent pass):** F-5, V-4 magnitude, V-6
  name-level claims (critics spot-checked via web), V-7, V-8, U-1, U-4–U-8, and the
  name-table readings in §4 for names not individually verified.
- The full 51-finding set, the four subsystem maps, and the five cited evidence briefs are
  in the review workflow's archive (session artifacts, 2026-08-08).

**Selected sources** (from the evidence briefs): Novy-Marx 2013 JFE; Ball, Gerakos,
Linnainmaa & Nikolaev 2016 JFE; Asness, Frazzini & Pedersen, "Quality Minus Junk" (RAS
2019); Piotroski 2000; Piotroski & So 2012; Penman & Reggiani, "The Value Trap"; Fama &
French 2015; Buffett 1986 letter appendix (owner earnings); Mauboussin & Callahan,
"Underestimating the Red Queen" and "Measuring the Moat" (2024); Mauboussin & Rappaport,
*Expectations Investing*; Damodaran on DCF/terminal value; Morningstar Equity Research
Methodology (moat + uncertainty rating; moat-trend retirement 2023); VanEck "Not All Moats
Are Created Equal"; Brandes "Falling Knives Around the World"; Klein pre-mortem literature;
Gawande, *The Checklist Manifesto*.
