# Academic/Quant Evidence on Small-Cap Equity Selection — What Works, What Is Myth

Research date: 2026-08-14. Scope: peer-reviewed asset-pricing and accounting-anomaly literature, with concrete formulas, thresholds, effect sizes, and implementability for an individual investor screening on SEC fundamentals (i.e., the stock-scout pipeline's data surface: as-filed XBRL company facts + prices).

---

## 1. The size premium: mostly myth as a standalone factor

**Original claim.** Banz (1981, *JFE*) documented that small-cap NYSE stocks earned higher risk-adjusted returns 1936–1975; Fama–French (1993, *JFE*, "Common risk factors in the returns on stocks and bonds") institutionalized it as **SMB** (Small Minus Big): the return of the three small portfolios minus the three big portfolios in a 2×3 size/book-to-market sort, with the size split at the NYSE median market cap.

**The critiques — each empirically established:**

- **Delisting bias (Shumway 1997, *JF*, "The Delisting Bias in CRSP Data"; Shumway & Warther 1999, *JF*, for Nasdaq).** CRSP recorded missing delisting returns as zero/omitted; the true average delisting return for performance-related delists is roughly **−30% (NYSE/AMEX) and −55% (Nasdaq)**. Because small caps delist far more often, uncorrected small-cap backtests are inflated. Correcting it, Shumway & Warther found the Nasdaq size effect essentially disappears.
- **Post-publication decay.** The premium weakened sharply after Banz's publication; recreations of Banz over his own sample show the premium was not statistically significant even in-sample once measured carefully ([Alpha Architect summary](https://alphaarchitect.com/does-the-small-cap-size-effect-exist-probably/), [Morningstar](https://www.morningstar.com/alternative-investments/what-happened-size-premium)).
- **"There is no size effect" — Alquist, Israel & Moskowitz (2018), "Fact, Fiction, and the Size Effect" (*JPM*; [SSRN 3177539](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3177539), [PDF](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Fact-Fiction-and-the-Size-Effect.pdf)).** Verdict: no reliable standalone premium after risk adjustment. The raw effect is (a) dominated by a January seasonal, (b) largely an illiquidity premium, (c) concentrated in microcaps, (d) weak internationally and absent in other asset classes, (e) hard to implement net of frictions. Crucially: **many *other* anomalies are stronger within small caps — that is not a size premium, it is an inefficiency locus.**

**Implementable takeaway.** Do not buy small merely because it is small. Use small-cap membership as a *hunting ground* where mispricing signals (quality, issuance, accruals, drift, momentum) have larger payoffs — which is exactly what the rest of this report documents. Expected standalone SMB premium going forward: ≈0–1%/yr, statistically indistinguishable from zero.

Sources: [Shumway 1997 context via PWL](https://pwlcapital.com/devilish-details-can-derail-your-small-cap-stock-funds/) · [arXiv survey "The Size Premium: Where is the Risk?"](https://arxiv.org/pdf/1708.00644) · [Fama–French 2005 working paper](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/acrobat/Size%20Value%20and%20the%20CAPM_2005_05.pdf).

---

## 2. Asness et al.: size works *conditional on quality*

**Asness, Frazzini, Israel, Moskowitz & Pedersen, "Size Matters, If You Control Your Junk" (*JFE* 2018, 129(3):479-509; [SSRN 2553889](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2553889), [published version](https://www.sciencedirect.com/science/article/pii/S0304405X18301326), [PDF](https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2015/05/Size-Matters-if-You-Control-Your-Junk.pdf)).**

- Mechanism: **small firms are on average junky** (unprofitable, unstable, high-distress); large firms are on average high quality. The unconditional SMB return mixes a positive pure-size effect with a negative quality-composition drag.
- Controlling for quality (their QMJ factor: profitability, growth, safety, payout composites), a **significant, stable size premium re-emerges** — robust across time (incl. post-1980s), across 30 industries and 24 international markets, present in non-January months, not confined to microcaps, robust to non-price size measures (book assets, sales, employees), and **not subsumed by illiquidity**.
- Effect size: the quality-adjusted SMB roughly **doubles the Sharpe of unconditional SMB** and becomes comparable in economic significance to value and momentum (unconditional SMB t≈1.9 becomes t≈4–6 after hedging quality exposure, sample 1957–2012).

**Implementable takeaway.** The tradable form for a screener is not a factor hedge but a conditional sort: **within small caps, buy only high-quality names** (high profitability, low leverage, stable margins, shareholder-friendly capital allocation). This is the single most important design principle for a small-cap screen and directly endorses a scorecard-gated small-cap universe.

---

## 3. Piotroski F-Score: quality inside cheap, neglected small caps

**Piotroski (2000), "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers" (*Journal of Accounting Research* 38 Supplement, 1–41).**

**The 9 binary signals (1 point each; F = 0–9):**

*Profitability (4):*
1. ROA > 0 (net income before extraordinary items / beginning total assets)
2. CFO > 0 (operating cash flow / beginning total assets)
3. ΔROA > 0 (ROA improved vs prior year)
4. **Accrual check:** CFO > ROA (cash earnings exceed accounting earnings)

*Leverage / liquidity / funding (3):*
5. ΔLeverage < 0 (long-term debt / avg total assets fell)
6. ΔCurrent ratio > 0
7. **No new equity issuance** during the year (shares out did not rise)

*Operating efficiency (2):*
8. ΔGross margin > 0
9. ΔAsset turnover > 0 (sales / beginning assets improved)

**Effect sizes (1976–1996, applied to the top book-to-market quintile):** buying high-F (8–9) value stocks raised mean one-year market-adjusted return by **+7.5%/yr** vs the whole value quintile; long high-F / short low-F (0–1) earned **≈23%/yr**. Critically for this brief: **the effect is concentrated in small firms, low share-turnover firms, and firms with no analyst following** — Piotroski explicitly reports the benefit is largest in the informationally neglected two-thirds of the value universe, and roughly 1/6 of the annual spread accrues around subsequent earnings announcements (mispricing, not risk). Out-of-sample confirmations: European and Asia-Pacific replications hold; the signal decays but persists post-publication ([Quant Investing backtest](https://www.quant-investing.com/strategies/price-to-book-and-piotroski-f-score-strategy), [StableBread component guide](https://stablebread.com/piotroski-f-score/), [Old School Value](https://www.oldschoolvalue.com/piotroski-score/)).

**Implementable thresholds.** Screen universe = cheap (top B/M quintile or bottom EV/FCF quintile) small caps; require **F ≥ 7** to buy (or ≥8 for concentration); treat **F ≤ 3 as a veto**. Every input is computable from two consecutive 10-Ks — perfectly suited to SEC-fundamentals-only pipelines. Note components 4 and 7 independently proxy the accruals anomaly (§7) and the issuance anomaly (§4) — the F-Score is a bundle of three separately-validated anomalies plus trend signals.

---

## 4. Net share issuance: the strongest single negative predictor

- **Daniel & Titman (2006), "Market Reactions to Tangible and Intangible Information" (*JF* 61(4):1605–1643):** the composite issuance measure ι = log(ME growth over 5y) − 5y log stock return predicts returns **negatively**; issuers underperform, repurchasers outperform.
- **Pontiff & Woodgate (2008), "Share Issuance and Cross-sectional Returns" (*JF* 63(2):921–945; [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01335.x)):** post-1970, the split-adjusted change in shares outstanding predicts returns with **greater statistical significance than size, book-to-market, or momentum**. Approximate marginal effect: each 1% of annual share issuance ≈ −0.3 to −0.5%/yr in subsequent return; the extreme-issuer decile underperforms by ~5–7%/yr.
- **Fama & French (2008), "Dissecting Anomalies" (*JF* 63(4):1653–1678; [draft PDF](https://www.ivey.uwo.ca/media/3775531/dissecting_anomalies.pdf)):** of all anomalies tested, **net stock issuance and momentum are the only two pervasive across all size groups, including microcaps** — the issuance anomaly is *not* a small-cap-only artifact, and it survives in small caps where most others get noisy. Repurchasers (negative NSI) earn positive abnormal returns in all size buckets.
- International confirmation: McLean, Pontiff & Watanabe (2009, *JFE*; [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X09001007)) — holds in 41 countries.

**Implementable formula.** NSI = ln(split-adjusted shares out at t / shares out at t−12m). **Veto NSI > ~5%/yr; prefer NSI ≤ 0** (flat or shrinking share count). Use actual weighted/period-end share counts from filings, not float. This is cheap to compute, slow-turnover, and among the most robust results in the entire literature. (The repo's existing >20%/yr dilution veto is directionally right but far looser than the literature's action point; the *positive* side — buybacks — is also predictive.)

---

## 5. PEAD and momentum: strongest exactly where coverage is thinnest

**PEAD — Bernard & Thomas (1989), "Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?" (*JAR* 27 Supplement:1–36; [RePEc](https://ideas.repec.org/a/bla/joares/v27y1989ip1-36.html)).** Sort on SUE = (EPS_q − EPS_{q−4}) / σ(seasonal-random-walk forecast errors). Top-minus-bottom SUE decile drifts **≈4.2% over the next 60 trading days (~18% annualized)** in their sample; the spread was positive in 41 of 48 quarters 1974–1985. **Drift magnitude is inversely related to firm size** — small firms drift roughly 2× large firms — and remains economically significant (>2% per 60 days) in low-coverage small/mid caps in modern samples ([review, ScienceDirect 2020](https://www.sciencedirect.com/science/article/pii/S2214635020303750); [Caltech note](https://jkatz.caltech.edu/documents/28622/peads.pdf)). Post-2000s the large-cap drift is mostly arbitraged away; the small-cap, low-coverage residual persists but is partly a bid-ask/transaction-cost mirage at the microcap floor — mid/small caps above ~$300M with real volume are the sweet spot.

**Momentum conditioning — Hong, Lim & Stein (2000), "Bad News Travels Slowly: Size, Analyst Coverage, and the Profitability of Momentum Strategies" (*JF* 55(1):265–295; [PDF](https://www.columbia.edu/~hh2679/jf-badnews.pdf), [NBER w6553](https://www.nber.org/papers/w6553)).** Three results: (1) past the very smallest bucket, momentum profits **decline sharply with size**; (2) holding size fixed, momentum is stronger in **low-analyst-coverage** stocks (residual coverage, size-adjusted); (3) the coverage effect is concentrated in **losers** — neglected losers keep falling. Mechanism: gradual information diffusion.

**Implementable takeaway.** For a fundamentals-first desk: (a) after a strong earnings report (high SUE), do not treat the price pop as "too late" — the literature says drift continues for 1–2 quarters in exactly this universe; (b) avoid catching falling knives in uncovered small caps — negative momentum there is *more* informative, not less (this also aligns with CHS distress evidence, §7); (c) a 12-1 month momentum filter (skip most recent month) as a tie-breaker adds value in small caps but demands monthly rebalancing that conflicts with buy-and-hold cost discipline — using it only as an *entry-timing veto* (don't initiate in the bottom momentum tercile) captures most of the benefit at near-zero turnover.

---

## 6. Liquidity premium and capacity: the individual's structural edge

**Amihud (2002), "Illiquidity and stock returns: cross-section and time-series effects" (*Journal of Financial Markets* 5:31–56; [PDF](https://www.cis.upenn.edu/~mkearns/finread/amihud.pdf)).** ILLIQ_i = (1/D) Σ_d |r_{i,d}| / DollarVolume_{i,d} — average daily price impact per dollar traded. Expected returns increase in ILLIQ cross-sectionally; part of the classic "size premium" is this illiquidity premium in disguise (consistent with Alquist et al., §1). Later work (Lou & Shu 2017; [PDF](https://www.icmagroup.org/assets/documents/Regulatory/Secondary-markets/Bond-Market-Liquidity-Library/Lou-X_Shu-T---2016---Price-Impact-or-Trading-Volume-Why-is-the-Amihud-2002-Illiquidity-Measure-Priced-290118.pdf)) shows the pricing is driven mainly by the volume component — so the premium is real but partly a compensation for trading friction you only earn if you *don't* trade much.

**Capacity and costs:**
- **Novy-Marx & Velikov (2016), "A Taxonomy of Anomalies and Their Trading Costs" (*RFS* 29(1):104–147; [OUP](https://academic.oup.com/rfs/article/29/1/104/1844518)):** effective one-way costs 20–57 bps for mid-turnover anomalies; anomalies with **<50%/month turnover survive costs**, high-turnover ones mostly do not. Best mitigation: **buy/hold spread** — stricter entry threshold than exit threshold (e.g., buy at decile 10, hold until it leaves decile 8).
- **Frazzini, Israel & Moskowitz (2018), "Trading Costs" ([PDF](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Trading-Cost.pdf)):** $1.7T of live institutional trades — real-world costs are ~10× smaller than TAQ-based estimates for a patient trader, but **capacity in small caps is what breaks funds**: strategy break-even capacities are in the low billions for large-cap factors and far smaller for small-cap value/quality.

**The asymmetry that matters:** a fund running $1B cannot hold meaningful positions in a $300M–$2B company without moving the price for weeks; an individual deploying $5k–$100k per position is **capacity-irrelevant** — trades at ~the spread, can use limit orders over days, holds through illiquidity. The illiquidity premium and the small-cap-concentrated anomalies (F-Score, PEAD, accruals) are therefore *structurally reserved* for small, patient capital. Practical guardrails for an individual: position ≤ ~1–5% of a stock's average daily dollar volume per day of execution; prefer names with ADV > ~$250k; expect round-trip costs of 20–80 bps in $300M–$1B names (spread-dominated), which annualized is trivial at buy-and-hold turnover (<30%/yr) and fatal at monthly rebalancing.

---

## 7. Accruals and distress: the two great small-cap value traps

**Accruals — Sloan (1996), "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?" (*The Accounting Review* 71(3):289–315; [Quantpedia summary](https://quantpedia.com/strategies/accrual-anomaly), [Lev & Nissim](http://www.columbia.edu/~dn75/The%20Persistence%20of%20the%20Accruals%20Anomaly.pdf)).** Total accruals = (ΔCA − ΔCash) − (ΔCL − ΔSTD − ΔTaxPayable) − Dep, scaled by average total assets (balance-sheet method; cash-flow method: (NI − CFO)/avg assets is now preferred, Hribar & Collins 2002). Cash earnings persist; accrual earnings mean-revert; the market misprices both. Hedge return (low-minus-high accrual deciles): **≈10–12%/yr** in-sample. Decayed post-2003 in large caps (Green, Hand & Soliman) but persists where arbitrage is costly — i.e., small caps with high idiosyncratic risk ([Mashruwala et al. 2006](https://www.sciencedirect.com/science/article/abs/pii/S0165410106000309)). **Threshold:** veto |accruals/assets| in the top quintile (roughly > +10% of assets); prefer bottom half. Note the repo's existing accrual-divergence M-block metric and Piotroski signal 4 already encode the direction — the literature supports making high accruals a hard veto, not a score deduction, for small caps.

**Distress prediction:**
- **Altman Z (1968, *JF*):** Z = 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MVE/TL + 1.0·Sales/TA. Distress < 1.81, grey 1.81–2.99, safe > 2.99. Built on 66 manufacturers 1946–65; coefficients are stale and sector-inappropriate outside manufacturing (Z′′ = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4 for non-manufacturers). Fine as a display-only flag; weak as a modern classifier (AUC ~0.75 vs ~0.87 for CHS-type models).
- **Ohlson O-Score (1980, *JAR* 18(1):109–131):** 9-variable logit (size, TL/TA, WC/TA, CL/CA, NI/TA, FFO/TL, loss dummies, ΔNI). P(bankruptcy) = 1/(1+e^{−O}); common alarm threshold O > 0.5 (i.e., p > 0.5, originally ~3.8% cutoff optimizing type I/II errors). Better than Z out-of-sample; still accounting-only.
- **Campbell, Hilscher & Szilagyi (2008), "In Search of Distress Risk" (*JF* 63(6):2899–2939; [PDF](https://scholar.harvard.edu/files/campbell/files/campbellhilscherszilagyi_jf2008.pdf)):** best-in-class 12-month failure logit combining accounting and market inputs — NIMTAAVG (profitability to market total assets, distributed lag), TLMTA (leverage at market), EXRETAVG (excess return vs S&P), SIGMA (3-month daily vol), RSIZE, CASHMTA, MB, log price (capped at $15). **The distress anomaly:** since 1981 the highest-failure-probability decile earned **−17%/yr four-factor alpha** (high vol, high beta, high SMB/HML loadings, terrible returns) — distress risk is *penalized*, not rewarded. This kills the "deep value = distressed small caps" story: cheap-and-distressed is the classic small-value trap, and it is why quality conditioning (§2, §3) is what makes small-cap value work. Precursor: Dichev (1998, *JF*) — high-Z/O-risk firms earn *lower* returns.

**Implementable takeaway.** Use distress metrics only as vetoes/flags (as invariant 6 of the repo already mandates for composites): flag Z′′ < 1.1, O-score p > 20%, or CHS-style combination of (negative NIMTA + TLMTA > 0.5 + high vol). Never buy the "cheap because dying" cohort in small caps — the literature's most consistent negative-alpha pocket.

---

## 8. The literature-endorsed small-cap quality-value screen (SEC-fundamentals implementable)

Synthesis of §1–§7 into a screen an individual can run on XBRL companyfacts + prices, matching the constraints (buy-and-hold, no shorting, capacity-irrelevant capital, ~annual fundamental refresh):

**Universe (the hunting ground, not the signal):** market cap ~$300M–$3B (above the microcap cost floor per Alquist et al./Novy-Marx-Velikov; below institutional capacity); price > $5 (CHS uses low price as a distress input); ADV > $250k.

**Hard vetoes (each independently supported):**
1. **NSI > 5%/yr** (Pontiff-Woodgate/Fama-French: the one anomaly pervasive even in microcaps) — and treat NSI ≤ 0 as a positive mark.
2. **Accruals/assets in top quintile** (Sloan; persists in small caps).
3. **Distress:** O-score p > ~20% or Z′′ < 1.1 or CHS-style {loss-making + TLMTA > 0.5 + high vol} (CHS: −17%/yr alpha decile).
4. **Bottom-tercile 12-1 momentum at entry** (Hong-Lim-Stein: uncovered small-cap losers keep losing) — entry-timing veto only, no ongoing price trigger needed.

**Ranking (quality × value, never merged with the vetoes):**
- **Quality:** gross profits/assets (Novy-Marx 2013, *JFE* 108(1):1–28: predictive power ≈ value, negatively correlated with it, so combining ~doubles opportunity set; [PDF](https://oldschoolvalue-files.s3.amazonaws.com/pdf/Novy-Marx_Gross-Profitability-Anomaly_JFE_2013.pdf)) + **Piotroski F ≥ 7** on the cheap half (Piotroski: +7.5%/yr over plain small value, strongest exactly in no-coverage small caps).
- **Value:** owner-FCF yield or EV-based yields, ranked within sector (cross-sectional evidence favors within-industry comparisons).
- **Rationale for the combination:** Asness et al. — quality is *what makes size investable*; Piotroski — quality is *what makes small value work*; Novy-Marx — profitability and value are complementary legs. Expected edge from the combined literature (honest, post-decay estimate): **~3–6%/yr over a small-cap index at annual-refresh turnover**, concentrated in avoided losers (vetoes) more than picked winners.

**Cost/turnover discipline (Novy-Marx-Velikov):** buy/hold spread — enter only on strong signals (F ≥ 7, top-quintile rank), exit only on veto breach or thesis break, keeping turnover < 30%/yr so 20–80 bps round-trips are immaterial.

**What the literature says to ignore:** raw SMB tilts (§1); the January effect (untradeable after costs); low-price "lottery" names (negative skew preference is a documented *negative* alpha, Bali-Cakici-Whitelaw 2011 MAX effect); distressed deep value (§7).

**Fit to the existing system:** the stock-scout pipeline already implements most of this architecture — sector-relative composite with quality/dilution/leverage vetoes, F-Score as display-only, $300M/$5 floors. The literature's marginal suggestions: tighten the dilution veto from 20%/yr toward ~5%/yr NSI (and credit buybacks), make top-quintile accruals a hard veto rather than a score component, and consider a CHS-style distress flag (market-leverage + volatility + profitability) as an inversion probe, since Z/O accounting-only models are demonstrably weaker classifiers.

---

## Citation index

| # | Paper | Year | Venue | URL |
|---|---|---|---|---|
| 1 | Banz, "The relationship between return and market value" | 1981 | JFE | — |
| 2 | Fama & French, "Common risk factors" | 1993 | JFE | — |
| 3 | Shumway, "The Delisting Bias in CRSP Data" | 1997 | JF | via [PWL](https://pwlcapital.com/devilish-details-can-derail-your-small-cap-stock-funds/) |
| 4 | Alquist, Israel, Moskowitz, "Fact, Fiction, and the Size Effect" | 2018 | JPM | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3177539) |
| 5 | Asness, Frazzini, Israel, Moskowitz, Pedersen, "Size Matters, If You Control Your Junk" | 2018 | JFE | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2553889) / [JFE](https://www.sciencedirect.com/science/article/pii/S0304405X18301326) |
| 6 | Piotroski, "Value Investing" | 2000 | JAR | [component guide](https://stablebread.com/piotroski-f-score/) |
| 7 | Daniel & Titman, "Market Reactions to Tangible and Intangible Information" | 2006 | JF | — |
| 8 | Pontiff & Woodgate, "Share Issuance and Cross-sectional Returns" | 2008 | JF | [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01335.x) |
| 9 | Fama & French, "Dissecting Anomalies" | 2008 | JF | [draft](https://www.ivey.uwo.ca/media/3775531/dissecting_anomalies.pdf) |
| 10 | McLean, Pontiff, Watanabe, international issuance | 2009 | JFE | [SD](https://www.sciencedirect.com/science/article/abs/pii/S0304405X09001007) |
| 11 | Bernard & Thomas, PEAD | 1989 | JAR | [RePEc](https://ideas.repec.org/a/bla/joares/v27y1989ip1-36.html) |
| 12 | Hong, Lim, Stein, "Bad News Travels Slowly" | 2000 | JF | [PDF](https://www.columbia.edu/~hh2679/jf-badnews.pdf) |
| 13 | Amihud, "Illiquidity and stock returns" | 2002 | JFM | [PDF](https://www.cis.upenn.edu/~mkearns/finread/amihud.pdf) |
| 14 | Novy-Marx & Velikov, "A Taxonomy of Anomalies and Their Trading Costs" | 2016 | RFS | [OUP](https://academic.oup.com/rfs/article/29/1/104/1844518) |
| 15 | Frazzini, Israel, Moskowitz, "Trading Costs" | 2018 | WP | [PDF](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Trading-Cost.pdf) |
| 16 | Sloan, accruals | 1996 | TAR | [Quantpedia](https://quantpedia.com/strategies/accrual-anomaly) |
| 17 | Altman, Z-score | 1968 | JF | — |
| 18 | Ohlson, O-score | 1980 | JAR | — |
| 19 | Campbell, Hilscher, Szilagyi, "In Search of Distress Risk" | 2008 | JF | [PDF](https://scholar.harvard.edu/files/campbell/files/campbellhilscherszilagyi_jf2008.pdf) |
| 20 | Dichev, "Is the Risk of Bankruptcy a Systematic Risk?" | 1998 | JF | — |
| 21 | Novy-Marx, "The Other Side of Value" | 2013 | JFE | [PDF](https://oldschoolvalue-files.s3.amazonaws.com/pdf/Novy-Marx_Gross-Profitability-Anomaly_JFE_2013.pdf) |
| 22 | Mashruwala, Rajgopal, Shevlin, accrual limits-to-arbitrage | 2006 | JAE | [SD](https://www.sciencedirect.com/science/article/abs/pii/S0165410106000309) |

Caveats: effect sizes quoted are in-sample academic estimates before publication decay; a realistic haircut is 30–50% (McLean & Pontiff 2016, *JF*, "Does Academic Research Destroy Stock Return Predictability?" — anomaly returns fall ~32% post-publication on average, less for high-cost-to-arbitrage small-cap signals, which is the one silver lining for this universe.)
