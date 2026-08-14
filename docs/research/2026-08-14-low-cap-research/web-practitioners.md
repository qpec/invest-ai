# How renowned small-cap / micro-cap practitioners actually select stocks
### Concrete, mechanizable rules from eight philosophies, with position-sizing and illiquidity guidance
Research date: 2026-08-14. Every rule below is restated as something computable from SEC fundamentals (income/balance/cashflow/shares) + a price series — the same inputs the stock-scout Bundle carries. Rules requiring analyst forecasts, insider Form-4 data, or 13F holdings are flagged, since they need data outside the current pipeline.

---

## 1. Peter Lynch — GARP, the six categories, "fast growers" as ten-bagger source

**Philosophy.** Growth At a Reasonable Price. Classify every stock into one of six categories before valuing it, because "the P/E of a slow grower and the P/E of a fast grower are different animals": **slow growers, stalwarts, fast growers, cyclicals, turnarounds, asset plays** (One Up On Wall Street, ch. 7). Fast growers — small, aggressive companies compounding earnings 20–25%/yr — are "the land of the ten-baggers." Small caps matter because "big companies have small moves, small companies have big moves." Lynch also prized boring/ugly names in no-growth industries with no analyst coverage — the amateur's structural edge.

**Mechanizable rules (from Validea/AAII codifications of the book):**
1. **PEG < 1.0** (buy zone), **< 0.5** = strongly attractive; PEG = trailing P/E ÷ EPS growth rate. Lynch's book version is yield-adjusted PEG: P/E ÷ (EPS growth + dividend yield) < 1. For a Bundle: use historical 3–5y EPS CAGR as G (Lynch used forward but historical is the honest point-in-time proxy).
2. **Fast-grower band: EPS growth 20–25%/yr** (Validea passes 20–50%); Lynch explicitly *distrusts growth > 25–30%* — "hot industry" fads, unsustainable. So the rule is a band, not a floor.
3. **Debt/equity < 25–35% preferred; reject > 80%** (Validea: <80% acceptable, financial companies exempt).
4. **Net cash per share / price > 30%** = bonus signal (net cash = cash + securities − LT debt).
5. **Inventory growth ≤ sales growth** (inventories rising faster than sales is his single favorite red flag for manufacturers/retailers).
6. **P/E below its own historical average and below industry median.**
7. **Low institutional ownership** and **insider buying / company buybacks** = plus factors (needs 13F/Form-4 data — outside a fundamentals-only pipeline; buybacks ARE computable from falling split-adjusted share count).
8. For **stalwarts** (10–12% growers): PEG (yield-adjusted) < 1; for **slow growers** the test shifts to dividend yield vs. history.

**Position sizing / risk for illiquid names.** Lynch ran hundreds of names at Magellan but told individuals: **own 3–10 companies you can personally follow** — "the more stocks you own, the more likely one is a ten-bagger", but never diversify into the unknown ("diworseification"). No stop-losses ever — "selling on a 10% drop guarantees you'll never get the ten-bagger"; the sell trigger is thesis deterioration (story change), not price. Small caps deserve smaller starting positions that are added to as the story confirms (he "watered the flowers, cut the weeds"). He gave fast growers multi-year holding horizons — the big move takes 3–10 years.

Sources: [Picture Perfect Portfolios — six categories](https://pictureperfectportfolios.com/peter-lynch-six-stock-categories/) · [Forbes — One Up screening strategy](https://www.forbes.com/sites/investor/2021/04/16/lynchs-one-up-on-wall-street-inspired-screening-strategy/) · [Validea — Lynch P/E/Growth model](https://blog.validea.com/strategy-of-the-week-the-peter-lynch-p-e-growth-investor-model/) · [Validea — investment strategy of Peter Lynch](https://blog.validea.com/the-investment-strategy-of-peter-lynch/) · [Old School Value — Lynch's final checklist](https://www.oldschoolvalue.com/tutorial/peter-lynchs-final-investment-checklist/) · [Nasdaq/AAII — finding stocks using Lynch's principles](https://www.nasdaq.com/articles/finding-stocks-using-principles-peter-lynch-2010-10-09)

---

## 2. Benjamin Graham — net-nets/NCAV, the Graham Number, margin of safety

**Philosophy.** Buy dollars for 66 cents, in bulk, statistically. Net-nets were historically a micro/small-cap hunting ground almost by definition — only tiny, hated names trade below liquidation value. Margin of safety is *the* central concept: the price discount does the risk management, and diversification substitutes for certainty about any one name.

**Mechanizable rules:**
1. **NCAV rule (the net-net screen):** Price per share < **2/3 × NCAV per share**, where NCAV = current assets − total liabilities − preferred stock. Fixed assets counted at zero. Fully computable from a balance sheet.
2. **Stricter NNWC variant:** NNWC = cash + short-term investments + 0.75×receivables + 0.5×inventory − total liabilities; buy below that.
3. **Earnings filter:** eliminate names with a **net loss over the trailing 12 months** (Graham's own qualifier on the NCAV screen).
4. **Graham Number (max fair price):** √(22.5 × EPS × BVPS); 22.5 = max P/E 15 × max P/B 1.5. Buy only below it.
5. **Defensive-investor checklist** (Intelligent Investor ch. 14, all computable): current ratio ≥ 2; LT debt ≤ net current assets; positive EPS in each of the last 10 years; 10-year EPS growth ≥ 33% cumulative (≈2.9%/yr); uninterrupted dividends 20 yrs (relaxable); P/E ≤ 15 on 3-yr average earnings; P/E × P/B ≤ 22.5.
6. **Debt screen for net-nets (Graham/Oppenheimer refinement):** debt-to-equity kept low; many modern implementations require total liabilities < 50% of NCAV and burn-rate checks (NCAV not shrinking >10–15%/yr).

**Position sizing / risk for illiquid names.** Explicit and mechanical: **~30 net-net issues, i.e. ≤ 3.3% per position** — "a diversified group … the results should be quite satisfactory," where any single net-net can be a fraud or a melting ice cube. Group behavior is the unit of analysis, not the single stock. Sell discipline in later Graham writings: sell at +50% gain or after 2–3 years, whichever first. This is the polar opposite of Fisher/Cassel concentration: safety from statistics, not from knowledge.

Sources: [GrahamValue — two-thirds NCAV strategy](https://www.grahamvalue.com/blog/benjamin-grahams-two-thirds-ncav-net-net-strategy) · [AAII — Graham's NCAV approach](https://www.aaii.com/journal/article/benjamin-graham-s-net-current-asset-value-approach) · [GrahamValue — applying NCAV correctly](https://www.grahamvalue.com/blog/applying-ncav-strategy-correctly) · [Net Net Hunter — Graham's mechanical net-net strategy](https://www.netnethunter.com/grahams-net-net-mechanical-strategy/) · [GrahamValue — using the Graham Number correctly](https://www.grahamvalue.com/article/using-graham-number-correctly) · [Quant Investing — worldwide net-net implementation](https://www.quant-investing.com/blog/why-and-how-to-implement-a-net-net-investment-strategy-world-wide)

---

## 3. Ian Cassel / MicroCapClub — qualitative microcap, owner-operators

**Philosophy.** Microcap = sub-$500M; Cassel prefers **sub-$100M entry, where there is no institutional ownership** — the informational edge is structural, not analytical. Find "intelligent fanatic" owner-operators leading a business that **dominates a small but expanding market**, and buy before institutions *can*. "Active patience": define exactly what you want, then wait. Dilution is "my biggest risk as a microcap investor."

**Mechanizable rules (his stated filter, restated as screens):**
1. **Market cap < $500M (ideally < $100–300M)** — computable from shares × price.
2. **Already profitable before scale:** positive TTM net income *and* positive operating cash flow — "growing, profitable, doesn't need to raise money to grow."
3. **Self-funding: no dilution.** Split-adjusted shares outstanding flat or shrinking over 3–5 years (e.g. share CAGR ≤ +2%/yr). This single test encodes "hasn't diluted shareholders" and "doesn't need to raise money."
4. **Clean share structure:** low absolute share count, one class of common, options+warrants small vs. shares outstanding (share classes and warrant overhang are extractable from 10-K cover/notes; the count trend is trivially computable).
5. **Low or no debt** — "small companies and debt don't go well together; travel light, travel far." Screen: net debt ≤ 0 or debt/EBITDA ≪ 1.
6. **Revenue growth positive and sustained** (repeatable growth, not one spike).
7. **Insider/founder ownership meaningful** (proxy-statement data; note Cassel himself cautions high insider ownership alone doesn't predict outperformance — it's alignment he wants, not a threshold).

**Position sizing / risk for illiquid names.** Extreme concentration: Cassel typically holds **5–10 positions**, biggest conviction 20%+; he is fully invested in microcaps and treats illiquidity as the *source* of return, not a risk to be sized away — the risk control is knowing the business better than anyone and buying profitable self-funders (a profitable company can't be killed by a closed capital market). Practical illiquidity rules from his writing: size positions to average daily volume (weeks, not days, to exit), never use leverage on illiquid names, and let the position become big by appreciation rather than by purchase.

Sources: [MicroCapClub — about/experts](https://microcapclub.com/about/microcap-experts/) · [Safal Niveshak — Microcap investing the Ian Cassel way](https://www.safalniveshak.com/ian-cassel-microcap-investing/) · [Morningstar India — 6 smart tips for micro-cap investors](https://www.morningstar.in/posts/39305/6-smart-tips-for-micro-cap-investors-2.aspx) · [The Investor's Podcast TIP606 — Multi-bagger first principles](https://www.theinvestorspodcast.com/episodes/multi-bagger-first-principles-w-ian-cassel/) · [Acquirer's Multiple podcast with Cassel](https://acquirersmultiple.com/2019/08/podcast-ian-cassel/)

---

## 4. Jim Slater — The Zulu Principle (UK small-cap PEG growth)

**Philosophy.** Narrow, deep specialization ("Zulu principle": modest focused study makes you a national expert in something small). "Elephants don't gallop" — small caps outrun large caps. The engine is a cheap PEG plus quality-and-momentum confirmations. The most quantified system on this list.

**Mechanizable rules (his own checklist, per Stockopedia/AAII codifications):**
1. **PEG ≤ 0.75, ideally < 0.66** (prospective P/E ÷ forecast EPS growth; historical-CAGR G is the pipeline-honest substitute).
2. **P/E < 20** (avoid paying up even for growth) with **EPS growth ≥ 15%/yr** — 4–5 consecutive years of ≥15% diluted-EPS growth from continuing operations; growth must not be from a low/depressed base.
3. **Cash-flow quality:** EPS backed by cash — operating cash flow per share ≥ EPS (last reported year and 5-yr average). His guard against accrual-driven "growth."
4. **Low gearing:** net debt < 50% of net assets (net gearing < 50%), preferably net cash.
5. **High ROCE > 12%** (Stockopedia codification; Slater wanted ROCE comfortably above cost of capital and rising margins as competitive-advantage evidence).
6. **Relative price strength positive vs. market over both 1 month/3 months and 12 months** — a pure price-series test; he refused cheap-and-sinking names.
7. **Market cap small** (his sweet spot: £10–100M in 1990s UK terms; i.e. deliberately below institutional coverage) — plus something new (management, product) and a "story."
8. Optional confirmations he named: dividend paid and growing; director (insider) buying; low absolute share count.

**Position sizing / risk for illiquid names.** ~10–12 positions for a serious private portfolio (concentration is inherent in the Zulu specialization idea). His explicit risk rules: never average down on a growth stock whose relative strength has broken; **sell on a PEG re-rating completed** (cheapness gone) or on story failure; spread across sectors to avoid one-theme wipeout. He accepted wide dealing spreads on small caps as the toll for the anomaly, but insisted the growth record (rule 2) and cash backing (rule 3) be in place first, precisely because exit from an illiquid loser is expensive.

Sources: [AAII — Screening on Slater's Zulu Principle](https://www.aaii.com/journal/article/screening-on-jim-slater-s-zulu-principle) · [Stockopedia/Ben Hobson — Zulu Principle explained](https://medium.com/stockopedia/jim-slaters-zulu-principle-growth-investing-mixed-with-value-in-brief-40ed0db13548) · [Stockopedia — how to use the Zulu Principle](https://www.stockopedia.com/content/how-to-use-jim-slaters-zulu-principle-to-find-cheap-growth-stocks-345403/) · [interactive investor — Zulu growth screen rules](https://www.ii.co.uk/analysis-commentary/zulu-growth-stocks-passing-jim-slaters-investing-rules-ii509414) · [ChartMill — Zulu Principle screen](https://www.chartmill.com/documentation/stock-screener/fundamental-analysis-investing-strategies/484-The-Zulu-Principle-by-Jim-Slater)

---

## 5. Joel Greenblatt — Magic Formula + special situations

**Philosophy A (Magic Formula, "The Little Book That Beats the Market"):** buy good companies (high return on capital) cheap (high earnings yield), mechanically, in a basket, and hold the discipline for years because the formula underperforms in 1-of-4 years — that pain is *why* it persists.

**Mechanizable rules:**
1. **Earnings yield = EBIT / Enterprise Value** (EV = mkt cap + debt + preferred + minorities − excess cash). Rank universe descending.
2. **Return on capital = EBIT / (net working capital + net fixed assets)** — tangible capital only, deliberately excluding goodwill. Rank descending.
3. **Combined rank = rank(EY) + rank(ROC); buy the lowest combined ranks.** Never average the two into a score — it is a double sort (structurally identical to scout invariant #2's "two judgements, never merged" — the ranks are combined but each metric stays pure).
4. **Universe floor: market cap > $50M** (his book's smallest tier; he also ran >$200M and >$1B versions); **exclude financials and utilities** (EBIT/EV meaningless); exclude ADRs.
5. **Portfolio mechanics: 20–30 stocks, bought 5–7 at a time over 12 months, each held exactly ~1 year** (sell losers just before the 1-yr mark, winners just after, for tax), then re-screen and replace.

**Philosophy B (special situations, "You Can Be a Stock Market Genius"):** hunt where forced, non-economic selling creates mispricing — **spinoffs, partial spinoffs, rights offerings, merger securities, recapitalizations, post-bankruptcy equities**. Spinoffs beat the market by ~10%/yr in the studies he cites. Mechanizable pieces: flag Form 10/spinoff events; check whether the spun entity is small enough to force index/institutional selling (mkt cap below parent's index threshold); check insider incentive alignment (options/ownership in the SpinCo per the Form 10 — needs filings parsing, not just financials); prefer leveraged SpinCos where equity is a stub option. Timing: initial forced selling typically exhausts in the first months — the anomaly is event-driven, not a permanent screen.

**Position sizing / risk.** Two regimes. Magic Formula = 20–30 names, equal-weight, ~3–5% each — diversification because you *haven't* researched them. Special situations = concentrated: Greenblatt personally ran 6–8 positions with the top idea at times >20%, saying **"diversification beyond 6–8 uncorrelated ideas adds little"**; sizing scales with downside protection, not upside. For illiquid stubs/spinoffs: buy patiently into forced selling with limit orders; the position size is capped by what the exit liquidity will bear.

Sources: [Wikipedia — Magic formula investing](https://en.wikipedia.org/wiki/Magic_formula_investing) · [Quantified Strategies — Magic Formula methodology & backtest](https://www.quantifiedstrategies.com/the-magic-formula-strategy/) · [StableBread — implementing Magic Formula](https://stablebread.com/magic-formula-investing/) · [Quant Investing — 2026 Magic Formula backtest](https://www.quant-investing.com/blog/magic-formula-investment-strategy-back-test) · [MicroCapClub — review of You Can Be a Stock Market Genius](https://microcapclub.com/book-review-you-can-be-a-stock-market-genius-by-joel-greenblatt/) · [Medium/Cerebral Cafe — Genius summary](https://medium.com/@thecerebralcafe/you-can-be-a-stock-market-genius-joel-greenblatt-60bdde286bd6)

---

## 6. Chuck Royce & Ralph Wanger — quality small caps, long holding periods

**Chuck Royce (Royce Investment Partners).** Small-cap *quality* at a *price*: "strong balance sheet, a record of success as a business, and the potential for a profitable future."

Mechanizable rules:
1. **ROIC ≥ 20%** target ("the two most important fundamentals are return on capital and a solid balance sheet").
2. **Low leverage:** conservative balance sheet — screen net debt/EBITDA low or negative; he explicitly buys "strong balance sheets" as his volatility-control device.
3. **Positive, persistent free cash flow** across a full cycle (multi-year OCF and FCF positive).
4. **Price discipline:** buy at a discount to his estimate of enterprise worth — implementable as EV/EBIT or FCF-yield cheapness vs. sector, never paying up for quality.
5. Prefers names **$100M–$3B**, holds **3–5+ years**, and treats temporary bad news / cycle troughs in a structurally sound business as the entry point.

**Ralph Wanger (Acorn Fund, 16.3%/yr 1970–2003; "A Zebra in Lion Country").** Buy small companies downstream of a durable multi-year **theme** ("don't buy the gold miners' technology, buy who benefits"); zebras must leave the herd's center to eat fresh grass but get eaten at the edge — hence small caps with financial strength only.

Mechanizable rules (AAII's codified Wanger screen):
1. **Market cap $100M–$2B.**
2. **Total liabilities/total assets below industry median** (his "financial strength" test — broader than LT debt/equity).
3. **Positive 3-year sales growth AND TTM sales growth ≥ 3-year rate** (growth intact and not decelerating).
4. **Positive earnings and cash generation**; understandable niche-dominant business (qualitative), entrepreneurial/owner management (proxy data).
5. **Growth at a reasonable price:** P/E below the company's growth rate (Wanger was a GARP buyer, not a momentum buyer).

**Position sizing / risk for illiquid names (both).** Diversified-but-meaningful: Acorn held many names but theme-clustered; Royce funds hold 50–100+, yet his advice to individuals is a smaller set of high-quality names held for years. The shared illiquidity doctrine: **the balance sheet is the position-size insurance** — because you cannot exit a small cap quickly, only own ones that cannot be forced into distress; enter gradually, hold 3–5+ years so the round-trip cost of the spread amortizes to nothing; sell on deterioration of the theme/quality, not on drawdown.

Sources: [GuruFocus — Chuck Royce: how to succeed with small-caps](https://www.gurufocus.com/news/646019/chuck-royce-how-to-succeed-with-smallcaps) · [Oninvest — five tips from Chuck Royce](https://en.oninvest.com/article/how-to-invest-in-small-caps-five-tips-from-wall-street-legend-chuck-royce) · [Fundamental Finance Playbook — Royce on small caps](https://fundamentalfinanceplaybook.com/chuck-royce-small-cap-funds/) · [AAII — Wanger (Revised) screening model](https://www.aaii.com/stocks/screens/72) · [AAII — Wanger's survival guide to small-cap investing](https://www.aaii.com/journal/article/ralph-wanger-s-survival-guide-to-investing-in-small-cap-stocks) · [AAII — unlocking small-cap growth through Wanger's strategy](https://www.aaii.com/stockideas/article/293563-unlocking-reliable-small-cap-growth-through-ralph-wangers-strategy)

---

## 7. Mohnish Pabrai & Michael Burry — Dhandho bets and "ick" deep value

**Mohnish Pabrai (The Dhandho Investor).** "Heads I win; tails I don't lose much" — seek **low-RISK, high-UNCERTAINTY** situations: the market prices uncertainty as if it were risk, so a wide outcome distribution with a protected floor is systematically cheap. "Few bets, big bets, infrequent bets." Clone shamelessly; only simple businesses; buy distressed *good* businesses in distressed industries.

Mechanizable rules:
1. **Price < 50% of conservatively-estimated intrinsic value 2–3 years out** (his stated entry bar — implementable as buy when price < 0.5 × DCF/exit-multiple value on owner earnings).
2. **Downside floor test:** tangible asset backing or net cash such that plausible worst case loses little — e.g. price near tangible book / net-net territory while the business still earns.
3. **Simple business:** stable, existing cash-generative model (multi-year positive FCF history), no story stocks.
4. **Distress markers as *entry* context, not veto:** price down >50% from high in an out-of-favor industry while fundamentals (FCF) hold.
5. **Sell rule:** exit within 2–3 years if price reaches intrinsic value; hold losers minimum 2–3 years before concluding error (his "Abhimanyu" exit doctrine).

Position sizing: originally **10 bets × 10%** each; he endorses **Kelly-formula sizing but at quarter-Kelly**, scaled so simultaneous ideas sum to 100%. After painful 2008 lessons he moved toward 5–7.5% initial positions for higher-uncertainty names. Explicitly: never leverage, because Kelly assumes serial bets and illiquid value stocks mark against you before they pay.

**Michael Burry (Scion; his own MSN Money articles, 2000–01).** Ick investing: "the stocks that make you shriek 'ick!' " — lawsuit-tainted, delisted-index, hated, obscure small caps; "rare birds": asset plays, companies at < 2/3 of net value, arbitrage. All grounded in Graham: "my weapon of choice is research; it is critical for me to understand a company's value before laying down a dime."

Mechanizable rules (he described his screen precisely):
1. **Screen on EV/EBITDA lowest deciles** (acceptable ratio varies by industry and cycle position — so rank within industry, echoing sector-relative percentiles).
2. Confirm with **free cash flow**: sustainable FCF vs. EV after "adjusting for off-balance-sheet items"; **ignores P/E; considers ROE deceptive and dangerous** (leverage-blind).
3. **Minimal debt** required; prefer net cash.
4. **Price test: within 10–15% of the 52-week low** — his stated entry preference and the one hard price-technical rule he allowed; if it breaks to a new low he re-examines rather than averages down blindly.
5. **Rare birds:** price < 2/3 × net asset value (net-net/asset-play test, straight from Graham).
6. Out-of-favor context (index deletions, scandals) as the *source* list — event data, partially mechanizable.

Position sizing / risk: ran a focused book of **12–18 stocks, all in out-of-favor names, fully invested** — enough concentration to matter, enough spread that one zero doesn't kill; barred himself from averaging down below thesis-invalidating levels; managed portfolio-level drawdown by holding cash when nothing qualified. For illiquid names he emphasized that the screen's cheapness must survive *his own* worst-case liquidation math because exit liquidity won't be there when wrong.

Sources: [Medium/ICR — The Dhandho Investor summary](https://medium.com/@Manybooks/the-dhandho-investor-the-low-risk-value-method-to-high-returns-12d263df9a31) · [Acquirer's Multiple — Pabrai on Kelly sizing](https://acquirersmultiple.com/2025/02/mohnish-pabrai-how-the-kelly-formula-can-improve-your-financial-strategy/) · [Old School Value — Pabrai checklist/Dhandho framework](https://www.oldschoolvalue.com/investment-tools/mohnish-pabrai-checklist-investor/) · [FinMasters — Burry's investment strategy](https://finmasters.com/michael-burry-investment-strategy/) · [Macro Ops — evaluate stocks like Michael Burry](https://macro-ops.com/how-to-evaluate-stocks-like-michael-burry/) · [michael-burry.com — think and invest like Burry (MSN article archive)](https://www.michael-burry.com/think-and-invest-like-michael-burry/)

---

## 8. Phil Fisher — scuttlebutt and the 15 points

**Philosophy.** Buy a handful of outstanding growth companies and hold "almost forever"; the research is qualitative field work ("scuttlebutt": interview customers, suppliers, competitors, ex-employees before ever meeting management). The 15 points (Common Stocks and Uncommon Profits, 1958) test growth runway, margin economics, R&D productivity, sales organization, people/management quality, accounting integrity, candor — **management integrity is the one non-negotiable point**. Do not sell because a stock "looks expensive" or has run up; sell only on (a) original analysis wrong, (b) company deteriorates past the 15 points, (c) a dramatically better use of the money.

**Mechanizable proxies (the points are qualitative; these are the standard AAII/quant codifications):**
1. **Sustained above-industry sales growth**, multi-year (points 1–2: products with years of growth runway) — e.g. 5-yr revenue CAGR > industry median, growth in ≥4 of 5 years.
2. **Profit margin above industry AND stable-or-improving** (points 5–6: worthwhile margins and what's being done to maintain them) — net or operating margin > sector median, 5-yr margin slope ≥ 0.
3. **R&D productivity** (point 3): R&D/sales meaningful for the sector *and* revenue growth per R&D dollar ≥ peers.
4. **Long-range profit orientation:** consistent reinvestment (capex+R&D)/sales with rising per-share owner earnings — per-share tests matter because of point 15's proxy below.
5. **No equity-financing treadmill** (point 14 area / financial strength): growth funded internally — share count flat/down over 5 yrs; if dilution funds growth, the "outstanding company" claim fails.
6. **Accounting quality proxy** (points 12–13): accruals low — (net income − OCF)/assets in the best quartile; smooth, not restated, earnings.
7. AAII's Fisher screen adds a valuation guard: **price-to-sales relative to margin** (his "PSR" concept was actually popularized by son Ken, but AAII's Philip Fisher screen uses P/S ≤ industry-relative bands for growth names).

**Position sizing / risk for illiquid names.** Deliberate concentration: **maximum ~20 holdings; most of the value in a handful**; his guidance — **10–20% positions for large stable growth companies, ~5% for small, risky young firms** — is the clearest illiquidity-scaled sizing rule on this list. "A long list of securities is a sign of the investor being unsure of himself." Returns are expected to come from 2–3 names compounding for decades; the risk control is depth of knowledge (scuttlebutt) plus the three-reason-only sell rule, not diversification or stops.

Sources: [Real Wealth Concepts — Fisher's 15 points](https://realwealthconcepts.substack.com/p/philip-fishers-15-points-to-look-for-in-common-stock) · [The Investor's Podcast — Common Stocks and Uncommon Profits summary](https://www.theinvestorspodcast.com/billionaire-book-club-executive-summary/common-stocks-and-uncommon-profits/) · [AAII — Fisher (Philip) screen](https://www.aaii.com/stocks/screens/30) · [Quartr — the timeless investment wisdom of Philip Fisher](https://quartr.com/insights/investment-strategy/the-timeless-investment-wisdom-of-philip-fisher) · [Hidden Value Gems — book review](https://hiddenvaluegems.com/library/common-stocks-and-uncommon-profits-by-phil-fisher)

---

## Cross-cutting synthesis (what a machine should take from this)

**Rules that recur across ≥4 practitioners (highest-confidence mechanizable signals):**
- **Low/no dilution — flat or shrinking split-adjusted share count** (Cassel, Fisher, Slater, Lynch-buybacks, Royce). The single most-shared small-cap test, and already a scout M-block input.
- **Low leverage / net cash** (everyone except Greenblatt-spinoffs, who inverts it deliberately): thresholds cluster at net gearing < 50%, D/E < 25–80%, net debt/EBITDA ≪ scout's existing 4× veto — small-cap practitioners set the bar far tighter than the scout's large-cap-tolerant veto.
- **Cash-backed earnings** (Slater's OCF/share ≥ EPS; Fisher accruals; Burry FCF-vs-EBITDA confirm; Lynch inventory-vs-sales) — accrual-divergence tests, already in the scout M-block.
- **Growth in a band, not a maximum** (Lynch 20–25% and *distrusts* >30%; Slater ≥15% not from a low base; Wanger growth-not-decelerating): screens should cap as well as floor growth.
- **Sector-relative, not absolute, cheapness** (Burry EV/EBITDA within industry; Greenblatt double-rank; Wanger liabilities vs. industry median) — matches the scout's within-sector percentiles.
- **PEG family** (Lynch <1, Slater <0.75): the one common valuation ratio built from EPS growth the pipeline already computes; use historical CAGR as G to stay point-in-time honest.

**Position sizing splits into exactly three regimes, keyed to research depth:**
1. **Statistical baskets** — Graham net-nets ≤3.3%/name ×30; Magic Formula 20–30 equal-weight ×1-yr rotation. Diversification replaces knowledge.
2. **Researched concentration** — Fisher ≤20 names (5% for small risky ones), Cassel 5–10, Pabrai 10×10% / quarter-Kelly, Greenblatt-special-sits 6–8, Burry 12–18, Slater 10–12. Knowledge replaces diversification; **every one of them scales the size DOWN for smaller/riskier/illiquid names** (Fisher's 5% small-firm cap is the canonical number).
3. **Universal illiquidity doctrine:** no leverage on illiquid names (Cassel, Pabrai, CLAUDE.md Hell-No filter agree); enter/exit via patience not market orders; multi-year holding periods so spreads amortize; balance-sheet strength as the substitute for exit liquidity (Royce/Wanger); sell on thesis/story breakage, never on price drawdown alone (Lynch, Fisher, Royce — consonant with scout invariant #7, "no price triggers"), with Burry's 52-week-low entry band the lone price-technical exception, and it is an *entry* rule, not an exit trigger.

**Data-availability notes for the scout pipeline:** everything above is computable from the Bundle except: analyst forecast growth (substitute historical CAGR), insider Form-4 buying (Lynch/Slater/Greenblatt plus-factor), institutional ownership 13F (Lynch/Cassel context), proxy-statement insider ownership % (Cassel/Wanger), and spinoff event flags (Form 10 feed). Warrant/option overhang and share-class structure are in 10-K text, not XBRL fundamentals.
