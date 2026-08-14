# How small-/micro-cap investments destroy capital — and the mechanical checks that catch them

Research date: 2026-08-14. Focus: US-listed small/micro caps; concrete thresholds, filing types, and what is computable from SEC XBRL companyfacts + daily prices vs. what needs extra data.

---

## 1. Dilution death spirals

### The mechanism
- **Toxic ("death spiral") convertibles**: convertible notes/preferred with a *floating* conversion price set at a 20–50% discount to a look-back average (e.g. lowest VWAP of prior 10–20 days). Lender converts, sells (often shorting ahead), price falls, next conversion delivers even more shares — a self-reinforcing dilution loop that can end in insolvency. Sources: [Wikipedia — Death spiral financing](https://en.wikipedia.org/wiki/Death_spiral_financing), [InvestmentBank.com — "Death Spiral" Finance](https://investmentbank.com/death-spiral), [diversification.com — Death spiral convertible](https://diversification.com/term/death-spiral-convertible). The SEC has pursued these lenders as unregistered dealers ([KJK on SEC v. convertible debt lender, 2024](https://kjk.com/2024/06/20/sec-brings-action-against-convertible-debt-lender/); [Basile Law Firm on toxic-note damages](https://www.thebasilelawfirm.com/post/damages-exposure-from-convertible-notes-violating-sec-rules-usury-laws-and-federal-rico-statutes)).
- **ATM (at-the-market) programs**: slow-drip dilution. Company files an S-3 shelf, then sells continuously into the market via a sales agent under 424B prospectus supplements. "When you see a 424B3, a company is almost certainly establishing or operating an ATM program" ([DilutionWatch — SEC 424B filings explained](https://dilutionwatch.com/articles/sec-424b-filing-explained.html)).
- **Reverse split → offering**: the classic sequence — reverse split to regain the $1 bid price, then immediately sell shares into the mechanically higher price. So endemic that Nasdaq rewrote its rules around it in Jan 2025 (see §2). Background: [PubCo Insight — Reverse stock splits explained](https://pubcoinsight.com/learn/reverse-stock-splits-explained/).

### Mechanical detection
**A. Share-count history (fully computable from XBRL).**
- Build a split-adjusted shares-outstanding series from `dei:EntityCommonStockSharesOutstanding` (cover page of every 10-K/10-Q, so quarterly cadence) plus `us-gaap:CommonStockSharesOutstanding`, `WeightedAverageNumberOfSharesOutstandingBasic` and `...Diluted`.
- Practitioner alert thresholds: annualized dilution **>5%/yr = moderate alert, >10%/yr = critical / "serial diluter"** ([TradingView Share Dilution Tracker](https://www.tradingview.com/script/rOtQsvXF-Share-Dilution-Tracker-v11/)). (The repo's existing `scoring.py` veto at >20%/yr is looser than practitioner norms for this segment.)
- **Diluted vs. basic gap**: fully-diluted count rising faster than basic ⇒ growing convertible/warrant overhang — an early warning *before* the shares print ([StockTitan — What is a stock offering](https://www.stocktitan.net/articles/what-is-a-stock-offering-types-dilution-how-to-spot)).
- MicroCapClub's dilution-risk scorecard approach: past dilution history is the single strongest predictor — "little to no previous dilution" is the pass condition ([MicroCapClub — dilution risk scorecard](https://microcapclub.com/how-to-avoid-dilution-in-microcaps-a-dilution-risk-scorecard/)).

**B. Filing-cadence score (computable from EDGAR submissions JSON, not companyfacts).**
[PubCo Insight's dilution-risk leaderboard](https://pubcoinsight.com/dilution-risk/) weights filings in the trailing 180 days:
- **+8** per S-1 / S-3 / F-1 / F-3 (shelf = raise capacity)
- **+5** per 424B (active offering / ATM supplement)
- **+6** per 8-K **Item 3.02** (unregistered share issuance — toxic converts land here; it already happened)
- **+4** per DEF 14A (often votes to raise authorized share count)
- **+3** per 10-Q (baseline activity)

Other filing tells: EFFECT notices on shelfs; S-1 registering resale of shares underlying convertible notes/warrants held by a single "investor" LLC is the toxic-lender signature.

---

## 2. Going concern, cash runway, delisting

### Going concern (ASC 205-40 / ASU 2014-15)
- Management must evaluate, every annual and interim period, whether substantial doubt exists about continuing as a going concern for **12 months from the financial-statement issuance date**; effective for periods ending after 2016-12-15 ([FASB ASU 2014-15](https://storage.fasb.org/ASU%202014-15.pdf); [PwC Viewpoint](https://viewpoint.pwc.com/dt/us/en/fasb_financial_accou/asus_fulltext/2014/asu_201415presentati/asu_201415presentati_US/asu_201415presentati_US.html)).
- In XBRL it appears as `us-gaap:SubstantialDoubtAboutGoingConcernTextBlock` — a **text block**, so it is *not* in the numeric companyfacts API; detect it via the filing's XBRL instance or EDGAR full-text search (`efts.sec.gov/LATEST/search-index?q="substantial doubt"...`). Real-world examples in 10-Qs: [T2 Biosystems 10-Q](https://www.sec.gov/Archives/edgar/data/1492674/000095017023023425/ttoo-20230331.htm), [Petros Pharmaceuticals 10-Q](https://www.sec.gov/Archives/edgar/data/1815903/000141057825001811/tmb-20250630x10q.htm) — boilerplate is "not sufficient to fund operations for the next twelve months."

### Mechanical cash-runway check (fully computable from companyfacts)
```
monthly burn  = max(0, -(TTM us-gaap:NetCashProvidedByUsedInOperatingActivities)) / 12
liquid assets = CashAndCashEquivalentsAtCarryingValue + ShortTermInvestments
runway_months = liquid assets / monthly burn        (∞ if burn ≤ 0)
FLAG if runway_months < 12   (mirrors the ASC 205-40 horizon)
```
A stricter variant subtracts committed capex and debt maturities within 12 months (`LongTermDebtCurrent`).

### Exchange listing standards (the delisting treadmill)
- **$1 rule**: closing bid < $1.00 for 30 consecutive trading days ⇒ deficiency notice ⇒ automatic **180-day** compliance period; cure = bid ≥ $1.00 for 10 consecutive business days; a second 180 days is available on the Capital Market if the company meets other standards and commits to a reverse split ([Cooley PubCo](https://cooleypubco.com/2025/01/22/nasdaq-minimum-bid-price-compliance-periods/); [ArentFox Schiff](https://www.afslaw.com/perspectives/alerts/sec-approves-nasdaq-proposed-rules-modifying-minimum-bid-price-compliance)).
- **Jan 2025 tightening** (Rule 5810(c)(3)(A)): **no compliance period at all** if the company did a reverse split in the prior 1 year, or reverse splits with **cumulative ratio ≥ 250:1 over the prior 2 years**; and bid ≤ **$0.10 for 10 consecutive trading days ⇒ immediate delisting determination** ([K&L Gates](https://www.klgates.com/The-State-of-Play-for-Reverse-Stock-Splits-by-Nasdaq-and-NYSE-Listed-Issuers-1-23-2025); [National Law Review](https://natlawreview.com/article/navigating-nasdaq-and-nyse-essential-insights-companies); [Holland & Knight/HLC](https://www.hlc.com/en/publications/sec-approves-nasdaq-and-nyse-revisions-to-reverse-stock-split-rules-what-public-companies-need-to-know)).
- **Nasdaq Capital Market continued listing (Rule 5550)**: one of — stockholders' equity ≥ **$2.5M**, or MVLS ≥ **$35M**, or net income ≥ **$500k** (latest year or 2 of 3); plus ≥500k publicly held shares, ≥$1M market value of publicly held shares, ≥300 holders, ≥2 market makers ([Securities Law Blog — Nasdaq continued listing](https://securities-law-blog.com/2023/10/03/nasdaq-continued-listing-requirements/); [Baker McKenzie listing guide](https://resourcehub.bakermckenzie.com/en/resources/cross-border-listings-guide/north-america/nasdaq/topics/principal-listing-and-maintenance-requirements-and-procedures)). SEC approved a new **$5M MVLS** continued-listing floor in July 2026 ([Greenberg Traurig](https://www.gtlaw.com/en/insights/2026/7/sec-approves-nasdaqs-new-$5-million-mvls-continued-listing-standard)).
- Mechanical proxies from prices + XBRL: price < $1 (30d), price < $0.10, stockholders' equity < $2.5M (`StockholdersEquity`), any reverse split in trailing 12/24 months (detectable as a same-day share-count ÷ N and price × N discontinuity).

---

## 3. Fraud and promotion

### Patterns
- **Pump-and-dump**: promoters tout a thinly traded microcap with false statements, create apparent activity, sell into the spike. Microcaps are targeted precisely because public information is sparse ([SEC/Investor.gov — Frauds targeting Main Street investors](https://www.sec.gov/resources-for-investors/investor-alerts-bulletins/ia_frauds)). Modern variant: freshly IPO'd small Nasdaq listings (often via small underwriters) pumped through WhatsApp/social "investment clubs," then dumped ([Bloomberg 2026 graphic investigation](https://www.bloomberg.com/graphics/2026-wall-street-apparent-pump-and-dump-investor-scam/)).
- **Shell hijacking / reverse mergers**: dormant shells sell for up to ~$750k to manipulators; the SEC's Operation Shell-Expel suspended **379 dormant shells (2012)** and **255 more (2014)**, plus 61 OTC companies "ripe for fraud" (2013) ([SEC 2012 release](https://www.sec.gov/newsroom/press-releases/2012-2012-91htm); [SEC 2014 release](https://www.sec.gov/newsroom/press-releases/2014-21); [SEC 2013 release](https://www.sec.gov/newsroom/press-releases/2013-2013-97htm)).
- **China-hustle style**: China-based operating company + US shell reverse merger + **small, obscure auditor not inspectable by the PCAOB** + revenues that don't match domestic (SAIC) filings; exposed by on-the-ground short-sellers ([GeoInvesting — The China Hustle](https://geoinvesting.com/the-china-hustle/); [Lee & Ma, PCAOB inspections and Chinese reverse-merger frauds](https://www.tandfonline.com/doi/full/10.1080/21697221.2013.857816) — PCAOB inspection exposure significantly reduces fraud incidence, especially for low-reputation auditors; [red-flag characteristics study](https://www.academia.edu/23161021/Red_Flag_Characteristics_of_Fraudulent_U_S_listed_Chinese_Companies): reverse-merger listing, earnings management, weak governance, small/obscure auditor + banker + law firm).
- **SEC trading suspensions**: SEC can suspend trading up to **10 days** (Exchange Act §12(k)) when information is inaccurate/unreliable; suspension of an OTC name effectively kills the market (market makers cannot quote without piggyback eligibility).

### Mechanical checks
- **Auditor**: name is disclosed in the 10-K audit report and, structured, in **PCAOB Form AP / AuditorSearch** (free public dataset: engagements by issuer, audit firm, partner). Flags: audit firm with < a handful of issuer clients; firm not PCAOB-inspected / located in a non-inspection jurisdiction (HFCAA lists); **auditor change = 8-K Item 4.01**, repeated changes = red flag; going-concern audit opinions.
- **Shell markers from EDGAR**: SIC code 6770 (blank checks); the 10-K cover-page XBRL flag `dei:EntityShellCompany` (true/false — cover-page dei facts, machine-readable); frequent registrant **former names** (in the submissions JSON `formerNames` array); state of incorporation vs. operations mismatch; long dormancy then sudden filing/volume burst.
- **Promotion / venue flags** (external data): OTC Markets marks tickers with **Caveat Emptor (skull & crossbones)**, a **Promotion flag** (since Q1 2018) and a **Shell Risk flag** ([OTC Markets stock-promotion policy PDF](https://www.otcmarkets.com/files/OTC_Markets_Group_Policy_on_Stock_Promotion.pdf); [policy launch](https://blog.otcmarkets.com/2017/12/06/otc-markets-group-establishes-a-stock-promotion-policy/); [Benzinga — OTC warning symbols](https://www.benzinga.com/news/19/01/13040272/an-explanation-of-the-different-warning-symbols-on-otc-markets)). SEC trading-suspension list is published at sec.gov (litigation/suspensions pages).
- **Price/volume anomaly proxy** (computable from daily prices): volume > 10–20× trailing 90-day median with price +≥50% in days, on a sub-$300M name with no 8-K — the pump signature. Crude but honest as a *review* trigger, not a verdict.

---

## 4. Insider alignment (positive screen)

- **Cluster buying is the strongest Form 4 signal**: ≥3 distinct insiders making open-market purchases (transaction code **P**, not option exercises/awards) within a short window (typically ≤2 weeks). Decades of academic work put insider-purchase-following excess returns at **~4–8%/yr**; effects are largest in small caps where information asymmetry is greatest ([Form4API — cluster buy signals](https://www.form4api.com/guides/cluster-buy-signals); [MarketTriage tracker](https://markettriage.com/insider-trading-signals)).
- Microcap-specific evidence: [arXiv 2602.06198](https://arxiv.org/abs/2602.06198) — 17,237 open-market purchases, 1,343 issuers, $30M–$500M caps, 2018–2024; gradient boosting on insider identity/history reaches AUC 0.70 out-of-sample; purchases *after* >10% price appreciation carried the highest mean CAR (+6.3%).
- **Ownership %**: the beneficial-ownership table lives in **DEF 14A** (and Schedule 13D/G for >5% holders). It is prose/tables, **not** XBRL-tagged — no structured bulk source from the SEC. Practitioner heuristic: 10–40% insider ownership is the alignment sweet spot; >50–60% adds control/governance risk. Founder-CEO status is likewise only in DEF 14A/10-K prose.
- **Where the structured data lives**: SEC publishes **Insider Transactions Data Sets** — quarterly structured extracts of all Forms 3/4/5 ([SEC Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets); [readme PDF](https://www.sec.gov/files/insider_transactions_readme.pdf); mirrored on [data.gov](https://catalog.data.gov/dataset/insider-transactions-data-sets)). Forms 3/4/5 are also filed as XML on EDGAR daily, so near-real-time parsing is possible without vendors. Form 4 is EDGAR's highest-volume form (~150–200k/yr). **Not** part of the companyfacts API — a separate free SEC bulk feed.
- Screen formula practitioners use: net insider buying $ over trailing 6–12 months > 0, ≥3 distinct buyers, purchases ≥ some materiality floor (e.g. ≥$25k each or ≥$1M aggregate for high-conviction clusters — cf. [Apify $1M cluster feed](https://apify.com/datasignalslab/sec-form4-insider-buying-clusters/examples/high-value-insider-buying-clusters)).

---

## 5. Liquidity reality

- **Time-to-exit formula**: `days_to_exit = position_$ / (ADV_$ × participation_rate)`. Example: $250k position, $5M ADV$, 10% participation ⇒ ~5 trading days ([StockTitan — liquidity guide](https://www.stocktitan.net/articles/liquidity-what-it-really-means)).
- **Practitioner rules of thumb**:
  - Single order ≤ **1% of ADV** to avoid visible market impact; daily execution ≤ **5–15% of ADV** depending on urgency ([StockTitan](https://www.stocktitan.net/articles/liquidity-what-it-really-means); [Positioned — ADV glossary](https://positioned.app/traders-glossary/average-daily-volume)).
  - Position no larger than **1–2 days of dollar volume** (some concentrated microcap investors accept 5–10 days knowing exit takes weeks); holding more creates trap risk ([Tradewink ADV](https://tradewink.com/glossary/average-daily-volume)).
  - Common absolute floors before taking any position: **ADV$ ≥ $100k–$500k** for personal accounts; institutional screens often require ≥ $1M ADV$. Swing-trading floors are commonly ≥ 500k shares/day or ≥ $5–10M ADV$ ([Morpheus Trading — minimum volume](https://morpheustrading.com/blog/minimum-trading-volume/)).
- **Spreads**: microcap bid-ask spreads routinely run **2–5%** (example: $5.00/$5.25 = 4.9%) vs. ~0.01–0.05% for large caps — a round trip can cost more than a year of expected alpha ([StockTitan](https://www.stocktitan.net/articles/liquidity-what-it-really-means); [Trendshare — liquidity](https://trendshare.org/how-to-invest/what-is-liquidity)).
- **Computable proxies**: ADV$ = 20/60-day median(volume × close) from any daily price feed. Effective spread without quote data: the **Corwin–Schultz high-low estimator** from daily OHLC. (Note: the repo already imposes DESK_MIN_MARKET_CAP $300M and DESK_MIN_PRICE $5 in `thesis.top_symbols`, which excises most of this tail; an ADV$ floor would close the residual gap — a $300M cap name can still trade <$200k/day.)

---

## 6. Computability matrix — companyfacts + daily prices vs. extra sources

**Fully computable from XBRL companyfacts + daily OHLCV (no new sources):**
| Check | Inputs |
|---|---|
| Serial-diluter share CAGR (>5%/>10%/yr flags) | `dei:EntityCommonStockSharesOutstanding` per 10-Q/10-K; weighted-avg basic |
| Diluted-vs-basic overhang gap | `WeightedAverageNumberOfShares...Basic` vs `...Diluted` |
| Cash runway < 12 months | Cash + ShortTermInvestments ÷ TTM negative OCF |
| Equity < $2.5M (Nasdaq 5550(b)(1) proxy) | `StockholdersEquity` |
| $1 rule / $0.10 rule / reverse-split history | daily close + share-count discontinuities |
| Reverse-split-then-offering pattern | split detection + subsequent share-count jump |
| ADV$ floor, days-of-volume position cap | daily volume × close |
| Corwin–Schultz spread estimate | daily high/low |
| Shell flag | `dei:EntityShellCompany` (cover-page dei fact) |
| Pump anomaly (volume/price spike review trigger) | daily OHLCV |

**Needs EDGAR beyond companyfacts (still SEC, still free):**
- Filing-cadence dilution score (S-1/S-3/424B/8-K 3.02 counts) → **submissions JSON** (`data.sec.gov/submissions/CIK##########.json`, includes form types, dates, `formerNames`, SIC).
- Going-concern text block → XBRL instance of the filing or **EDGAR full-text search** (`efts.sec.gov`) for `SubstantialDoubtAboutGoingConcernTextBlock` / "substantial doubt".
- Insider Forms 3/4/5 → **SEC Insider Transactions Data Sets** (quarterly bulk) or daily ownership XML.
- Auditor identity/changes → 10-K parse or **PCAOB Form AP (AuditorSearch)** dataset; 8-K Item 4.01 for changes.

**Needs genuinely external sources:**
- Insider ownership % and founder-CEO status → DEF 14A prose (unstructured; vendor or LLM extraction).
- Short interest → FINRA (bi-monthly, free) / exchange files.
- Promotion & Caveat Emptor/Shell Risk flags → OTC Markets data products.
- SEC trading-suspension list → sec.gov suspensions page (scrapeable, not an API).
- Real bid-ask spreads → quote-level (NBBO) data.

### Fit with the repo's invariants
Every "fully computable" check above is deterministic over the Bundle + price grid (invariant 4), is refuse-not-guess-able (runway = `None` when cash or OCF is unmeasured), and belongs in the **inversion/veto layer**, never the scorecard (invariant 2). The $1/$0.10 checks are *listing-survival* facts, not price triggers on a thesis — they flag exchange-rule jeopardy, not valuation (consistent with invariant 7 if framed as delisting-risk probes rather than thesis invalidation on price).
