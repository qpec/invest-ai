# Long-Term Investment Identification — Framework & Repo Evaluations for The Scout

**Date:** 2026-07-08 · **Method:** 8 parallel fact-gathering agents on primary sources (LICENSE files, raw source code, PyPI metadata, commit logs, journal registries, live code execution) + 3-vote adversarial verification of every adoption-critical claim (12 claims verified, **all survived 3-0**; 44 agents total). Verdicts are framework judgments applied to verified facts, same standard as `2026-07-03-repo-evaluations.md`.

**Question:** which parts of a candidate list (6 repos + 4 academic approaches for identifying long-term investments) can serve the new **Scout component** (idea generation, FR14) or deepen the Gate — under the anti-complexity constitution, NFR7 dependency discipline, and NFR3 cost discipline?

**Outcome: 1 adopt (narrow) · 2 method-extractions · 4 reject · 3 academic angles resolved.** Design consequence: component H (The Scout) in `docs/plans/2026-07-08-architecture-elaboration.md`.

---

## Verdict table

| # | Candidate | Verdict | License (verified) | Health (verified) |
|---|---|---|---|---|
| 1 | FinanceToolkit | ❌ REJECT for v1, **with pre-approved revisit condition** | MIT (3-0) | Active: v2.1.3 2026-06-27, 5,089★ (3-0) |
| 2 | FinanceDatabase | ✅ ADOPT (narrow: universe file, direct read — **not** the pip package) | MIT (3-0) | Active: push 2026-07-05; US data auto-updates every Sunday (3-0) |
| 3 | greenblatt-faustmann-screener, Quant_Value_Screener, valuation_data_pipeline | ❌ REJECT as code · ✅ methods extracted | **No license = all rights reserved** (all three) | 1–2★, abandoned; dead/credentialed data paths |
| 4 | FinQuant | ❌ REJECT | MIT | Dormant ~34 months (last release 2023-09); dead quandl dependency |
| 5 | QuantMuse | ❌ REJECT | MIT (generic copyright holder) | 9 commits total; star-count anomaly (~2.7k★, 561 forks); dormant ~11 months |
| 6 | Magic Formula (Greenblatt) | ✅ ADOPT as screen recipe (no dependency) | n/a — book method | Independent evidence: ~3–6%/yr, **not** the claimed 30% |
| 7 | Momentum / QVM dimension | ❌ REJECT for idea generation | n/a | Factor real at 3–12m rotation; reverses at 3–5y horizons |
| 8 | ESG factor | ❌ Not added | n/a | JFE-level evidence contested |
| 9 | Dual-memory LLM agents (gmssrj) + ESG paper (wjarr) | ❌ Sources discredited; insight retained | n/a | Both outlets predatory/paper-mill class |

---

## Per-candidate evidence

### 1. FinanceToolkit — REJECT for v1, revisit condition documented

All seven adoption-critical claims verified 3-0:
- **MIT**, actively maintained (v2.1.3 on PyPI 2026-06-27; pushed 2026-06-28; Python ≥3.10,<3.16).
- **Keyless operation genuinely works:** with no FMP key it defaults to Yahoo Finance (`enforce_source="YahooFinance"`), retrieving statements via yfinance; custom pandas DataFrames are a first-class input path (`historical`/`balance`/`income`/`cash` constructor params + `get_normalization_files()`), so our already-hardened yfinance statements could be fed in directly.
- **Capability is real:** FCF DCF intrinsic valuation, WACC, DDM, extended DuPont, Altman-Z, Piotroski, and 70+ ratios incl. FCF yield, P/FCF, EV/EBITDA, earnings yield — transparent formulas by design.
- **Why rejected anyway (NFR7 proportionality, verified):** the entire DCF engine is ~137 lines / ~50 effective lines of plain Python; the Gate needs roughly a dozen ratios it already computes from hardened yfinance data; and `scikit-learn>=1.6` is a **mandatory** runtime dependency (with openpyxl) — a heavy transitive stack irrelevant to Gate-slot use. Framework fit is also negative: a DCF with growth/WACC/terminal assumptions invites exactly the assumption-stacking a fair-band anchor system deliberately avoids (HN2).
- Red flags noted: single maintainer; FMP affiliate-link monetization throughout docs (keyless path works today, incentives favor the paid path); Yahoo statement history only ~4–5 periods.
- **Pre-approved revisit condition:** if Gate ratio needs outgrow ~10 formulas or statement normalization becomes a real maintenance burden, FinanceToolkit in custom-data/keyless mode is the verified fallback — this evaluation does not need to be redone.

### 2. FinanceDatabase — ADOPT (narrow): the Scout universe layer

All five decisive claims verified 3-0, including by live execution:
- **MIT** (both LICENSE commits in history are standard MIT — the "historically non-standard license" concern was tested and does not hold for this repo).
- **What it is:** static categorization database — 160,995 equities (of 300k+ symbols) with sector/industry_group/industry/country/exchange/market_cap(categorical)/ISIN fields. **Zero fundamentals** — it complements, never overlaps, the adopted stack.
- **No key, no package needed (verified empirically):** `compression/equities.bz2` loads directly with `pd.read_csv(url, compression="bz2", index_col=0)` → 160,995×21 DataFrame, no credentials, no pip install. The pip package's sole dependency is financetoolkit (which drags scikit-learn/openpyxl) — **for a CSV lookup, install nothing; read the file** (pin a commit SHA, cache locally).
- **Freshness:** US exchanges auto-update every Sunday via GitHub Action (cron verified in the workflow file; consecutive Sunday commits verified). **EU rows are community-maintained** → treat as a starting list, re-verify at screen time.
- **Tickers are Yahoo-namespace** (AGN.AS, ORC.DE, BRK-B dash convention; live-resolved against Yahoo's search API) → feed yfinance directly.
- **Universe query works as designed (executed live):** `select(country=['United States','Netherlands'], sector=['Information Technology','Health Care'], market_cap=['Mid Cap','Large Cap','Mega Cap'], only_primary_listing=True)` → 509 rows.
- ⚠️ **Operational caveat found by verification:** `only_primary_listing=True` is a "no dot in ticker" heuristic — it keeps US cross-listings (ASML) and **drops Euronext home listings (ASML.AS)**. Universe config must apply the flag to the US leg only and filter EU legs by exchange/market instead. (Reflected in elaboration §H.1.)

### 3. Three tiny value screeners — REJECT as code; methods extracted

- All three have **no license file → all rights reserved**: even verbatim copying is unlicensed. Only the published methods (from Greenblatt's and Spitznagel's books) are used — no code is copied, which also avoids repo 1's **non-canonical math** (its ROIC = net income/(equity+debt) deviates silently from Greenblatt's EBIT/(NWC+NFA)).
- Repo 1 scrapes magicformulainvesting.com behind a selenium login (ToS-hostile, fragile); repo 2's sole data source (IEX Cloud sandbox) was retired 2024-08-31 — dead code; repo 3 hides its data source behind credentials env vars — unreproducible, presumably paid (NFR3 fail).
- **Extracted for the Scout:** (a) quality-value screen recipes expressible in already-adopted TradingView-Screener fields; (b) canonical Magic Formula metrics (EY = EBIT/EV; ROC = EBIT/(net working capital + net fixed assets)) computed per-shortlisted-candidate from yfinance statements; (c) repo 3's Greenwald earnings-power-value formula set noted as a possible future Gate dossier enrichment (~30 lines; deferred, not adopted).

### 4. FinQuant — REJECT

MIT but dormant ~34 months (no release since v0.7.0, 2023-09); hard dependency on quandl, itself dead since 2021 and key-gated; core value is Efficient Frontier/Monte Carlo weight optimization — the exact category rejected with PyPortfolioOpt — plus moving-average buy/sell signals (trader tooling, action-bias vector). No capability the stack lacks.

### 5. QuantMuse — REJECT

The already-rejected categories in one monolith: backtesting + ML/GPT stock picking + **real-time order execution (violates FR11 by design intent)** + crypto exchange integration. Requires Binance and paid OpenAI keys (NFR3). Integrity signals are poor: ~2.7k stars on 9 content-free commits (star-inflation pattern), LICENSE copyright holder is the generic "Quantitative Trading System", not on PyPI, dormant ~11 months despite "production-ready" claims. Nothing salvageable.

### 6. Magic Formula — ADOPT as a screen recipe (zero dependencies)

- **Honest evidence base:** Greenblatt's book claims ~30%/yr; the cleanest independent US replication finds ~3%/yr gross alpha (with a 57% drawdown 2007–2010), a peer-reviewed Finnish study ~6%/yr, and Novy-Marx's horse race significant large-cap alpha. **The cheapness leg (EBIT/EV) carried most of the alpha in multiple independent tests; the quality leg (ROC) is the weakest part.** Design consequence: cheapness is load-bearing, ROIC is a confirmatory cut, in recipe QV (§H.2).
- **Fit:** as an idea-generation filter feeding a full qualitative Gate — not a mechanical buy list — the weaker-than-advertised alpha is irrelevant; it reliably surfaces cheap, capital-productive businesses (the Buffett pre-filter). Greenblatt's own investor-behavior data shows discretionary second-guessing of the screen's valuation call destroyed the edge → the Gate judges the framework, never re-times the screen.
- The honest evidence note is printed on every screen output (H.2).

### 7. Momentum / QVM — REJECT for idea generation

Momentum is a real academic factor at 3–12-month horizons with rotation-level turnover (Jegadeesh/Titman); it dissipates after year one and **reverses at the 3–5-year horizons this book holds at** (De Bondt/Thaler). Mechanically, a momentum rank sorts beaten-down intact-thesis quality names to the bottom — hiding exactly the "wonderful business on sale" candidates — and is most wrong during post-panic rebounds (Daniel/Moskowitz momentum crashes: loser decile +163% Mar–May 2009), the Constitution's prime buying windows. Stockopedia's StockRank evidence is generated by annual rebalancing — borrowing a rotation strategy's evidence for a never-rotating system. At most: fundamental-momentum as display-only context, never filter or rank.

The pasted "14.2% p.a. for 5+ years vs 6.4% under 1 year" claim traces to ISJEM — a pay-to-publish outlet (₹1000, publication within 12–24h of payment, self-asserted impact factor with no verifiable indexing) — and rests on a 150-investor survey. Unusable.

### 8. ESG — not added

High-quality evidence is contested: Pástor–Stambaugh–Taylor (JFE 2022) attributes green outperformance to an unexpected demand shift with *lower* expected returns ahead; Friede et al. 2015 supports only a broad nonnegative ESG–corporate-performance link, not portfolio alpha; PE-specific quality evidence is thin. The wjarr citation offered as support is a textbook predatory mega-journal (sells 3–4-day publication for $35, fabricated impact factor, absent from DOAJ/Scopus/WoS). Not in the Constitution; not added; any future doc claiming "ESG improves long-run returns" as settled would contradict JFE-level evidence.

### 9. Dual-memory LLM agents — sources discredited; the insight validates the existing design

- The gmssrj citation is functionally a paper mill: not in DOAJ/Scopus/WoS, vanity metrics only, APC $120–250, DOI prefix registered to "International Study Counselor", **zero references in its Crossref deposit**, claimed University-of-Melbourne authors with no discoverable research footprint. Its conclusions coincidentally mirror credible literature — which makes it seductive to cite; don't.
- The credible line — FinMem (arXiv 2311.13743), FinAgent (2402.18485), FinCon (2407.06567), EMNLP 2025 Findings survey — is **day-frequency trading-agent research**: citable as literature, off-framework as tooling (the already-rejected category).
- **What survives is architectural validation:** layered memory for investment agents = exactly what the Thesis Register (semantic memory) + Decision Journal (episodic memory) + The Study (consolidation loop) already are. The credible finding — LLMs excel at qualitative reasoning over text, underperform at consistent long-horizon quantitative optimization — confirms the existing division of labor: LLM for thesis reasoning, deterministic pandas/scipy for all math. No new component, no new dependency.

---

## Requirements impact (proposed)

- **FR15 — Scout formalization.** The candidate universe and screen recipes are pre-committed config (changes journaled); screen output is capped (top 20 by the cheapness leg), printed with the honest evidence note, and discarded after the session; only hand-picked names enter the watchlist, only as `raw` items, only through the Gate. (Extends FR14; implemented as component H.)
- **NFR7 addendum (practice, not new number):** "adopt the file, not the package" is a legitimate dependency-discipline move when a package's value is static data (FinanceDatabase precedent: pin commit SHA, cache locally, journal refreshes).

## Open items

1. FinanceToolkit revisit condition (see §1) — pre-approved, no re-evaluation needed if triggered.
2. Universe refresh ritual: suggested quarterly, manual, journaled; EU rows re-verified at screen time (community-maintained staleness).
3. `only_primary_listing` heuristic: US leg only; EU legs filtered by exchange/market (verified behavior, elaboration §H.1).
4. TradingView earnings-yield field: EV/EBITDA and P/FCF are the verified cheapness proxies; re-grep the fields page before ever hard-coding an EBIT/EV field assumption (one fact agent flagged the fields check was done via a summarizing fetch).
