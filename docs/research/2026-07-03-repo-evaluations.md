# Repo Evaluations — Simple Add-ons for Assessment Quality

**Date:** 2026-07-03 · **Method:** deep-research workflow (106 agents, adversarial 3-vote verification, 24 sources) + 3 targeted verification agents. All license/maintenance/ToS facts verified live against primary sources on 2026-07-03.

**Question:** which of 9 candidate repos can add a *narrow, simple* capability that improves assessment quality in stock-agentcy — a thesis-driven, buy-and-hold, advise-only portfolio system under an anti-complexity (Munger) constraint? None of them becomes a foundation.

**Outcome: 2 adopt · 1 partial · 6 reject.** The verdicts are framework judgments applied to verified facts; the facts below are cited.

---

## Verdict table

| # | Repo | Verdict | License (verified) | Health (verified) |
|---|------|---------|--------------------|-------------------|
| 1 | OpenBB | ❌ REJECT | AGPL-3.0-only (since 2024-05; GitHub NOASSERTION is a LICENSE-preamble artifact) | Active (4.7.2, 2026-05-26) |
| 2 | yfinance | ✅ ADOPT (base) + hardening | Apache-2.0 | Active |
| 3 | TradingView-Screener | ⚠️ PARTIAL (human-run only) | MIT (v3.2.1, 2026-06-20) | Active, fields regenerated daily |
| 4 | vectorbt | ❌ REJECT (fit) | Apache-2.0 + Commons Clause | Active (1.0.0, 2026-04-22) — reject is fit-based, not health-based |
| 5 | backtrader | ❌ REJECT (fit + health) | GPL-3.0 | Dormant: no code since 2023-04; official forum HTTP 522; forks also stale |
| 6 | pybroker | ❌ REJECT (fit) | Apache-2.0 + Commons Clause | Maintained (1.2.12, 2026-03-05) |
| 7a | PyPortfolioOpt | ❌ REJECT (for this need) | MIT | Active again (v1.6.0, 2026-02-26, GC.OS/PyPortfolio org — org URL is canonical, repo moved from robertmartin8) |
| 7b | quantstats | ✅ ADOPT (narrow) | Apache-2.0 | Active but bursty; pin `>=0.0.81` (0.0.78–0.0.80 broke on import) |
| 8 | qlib | ❌ REJECT | MIT | Low-cadence maintenance (release 2025-08; push 2026-04) |
| 9 | FinRL | ❌ REJECT | MIT | Active as RL research framework |

---

## Per-repo evidence

### 1. OpenBB — REJECT
- License definitively AGPL-3.0-only since 2024-05-14/15 (blog + LICENSE + PyPI classifier). Private unmodified local use triggers no obligations, but it's strong copyleft in the dependency tree.
- One `pip install openbb` mandates ~30 `openbb-*` packages incl. 17 provider connectors; without paid API keys (FMP/Intrinio/Polygon/Tiingo) the keyless fundamentals fallback reduces to **Yahoo + SEC** — marginal value over yfinance alone.
- Verdict: heavy copyleft dependency for marginal keyless value → fails the anti-complexity test.

### 2. yfinance — ADOPT as base, with three mandatory hardening practices
All three verified from official docs + maintainer (ValueRaider) statements:
1. **App-level caching + request pacing.** The library caches only timezones and the Yahoo cookie — no price/fundamentals response caching. The legacy `requests_cache` session pattern is broken since the curl_cffi migration (issue #2486). We must cache on disk and pace requests ourselves.
2. **Shares outstanding via `Ticker.get_shares_full(start, end)`** (the old `Ticker.shares` is a dead stub). Returns an irregular event-driven series with adjacent-date jumps and duplicate-date conflicts (issues #1133, #1954) → apply last-value-per-period resampling + dedup before computing per-share figures (FCF/share, buyback tracking).
3. **Silently-empty statement detection.** Yahoo omits quarterly statements for a small % of tickers; yfinance 0.2+ returns silently empty DataFrames; the 0.1-era HTML recovery is permanently removed (issue #1265 closed *not-planned*, 2025-02-16). The buy gate and weekly refresh must detect emptiness explicitly and degrade gracefully, reporting staleness.
- Fallback path if gaps ever hit actual portfolio tickers (unlikely — mostly large caps): direct SEC EDGAR, **not** openbb-sec (AGPL). Deferred until proven necessary.

### 3. TradingView-Screener — PARTIAL: human-triggered idea generation only
- **Capability confirmed**, including absolute owner-earnings fields (grep of the full 474 KB fields page): `cash_f_operating_activities_ttm/fy/fq`, `capital_expenditures_ttm/fy/fq`, `free_cash_flow_ttm/fy/fq` (absolute, distinct from margin/ratio variants), `total_revenue_*`, `net_income_*`, plus `return_on_invested_capital`, `debt_to_equity`, all three margin levels, `price_free_cash_flow_ttm`, `enterprise_value_ebitda_ttm`. SQL-like DSL (`Query().select().where()`), no login needed for delayed data (live POST reproduced during verification: ROIC>15 AND D/E<1 → 1,115 matches, plausible values).
- **ToS constraint (verbatim, verified live):** TradingView licenses data for "exclusive display-only use", expressly forbids "algorithmic decision-making … or any machine-driven processes that do not involve the direct, human-readable display of such data" and third-party tools enabling such usage. The library POSTs to the undocumented scanner endpoint with spoofed headers; TradingView states it has no public data API and confirms bans for automated collection.
- **Consequence:** never wired into the automated daily/weekly loop. Occasional, manually-triggered screens whose output a human reads (least-exposed class — residual ToS tension consciously accepted) → feeds the watchlist; every idea still passes the full Gate. Sanity-filter outputs (royalty trusts show absurd ROIC on near-zero invested capital).

### 4. vectorbt — REJECT on fit
- Healthy and revived (1.0.0 April 2026; Apache-2.0 + Commons Clause — personal use fine). Rejection is purely framework fit: vectorized backtesting of thousands of strategy variants is the trader's tool, and its own tagline — "Run thousands of trading ideas before others finish one" — is verbatim the Munger anti-pattern (action bias + complexity addiction). No narrow salvageable piece a thesis investor needs.

### 5. backtrader — REJECT on fit and health
- GPL-3.0 confirmed. No code commits since 2023-04; PyPI release gap 2020→2023→nothing; official community forum returns HTTP 522; fork maintainers publicly state the original is unmaintained. Dead ecosystem + copyleft + off-framework purpose.

### 6. pybroker — REJECT on fit
- Apache-2.0 + Commons Clause (personal use clearly permitted), maintained. Rejection: ML-driven stock picking contradicts the thesis-driven process, and the overfitting evidence (see FinRL) generalizes to backtest-selected ML strategies.

### 7a. PyPortfolioOpt — REJECT for our narrow need (healthy project otherwise)
- The needed capability — hidden-concentration detection via correlation clustering — is ~5 lines of pandas+scipy, mathematically identical to HRPOpt's internals (verified from source: same `sqrt((1-corr)/2)` distance + `scipy.cluster.hierarchy.linkage`):

```python
corr = prices.pct_change().corr()
dist = np.sqrt(np.clip((1 - corr) / 2, 0, 1))
Z = sch.linkage(ssd.squareform(dist.values, checks=False), method="average")
labels = sch.fcluster(Z, t=k, criterion="maxclust")   # holding → cluster id
```

- pypfopt adds a mandatory cvxpy install **and import-time load** (verified: `hierarchical_portfolio` → `pypfopt.base` → module-level `import cvxpy`) and still doesn't expose flat cluster labels (`HRPOpt.clusters` is the raw linkage matrix; you'd call `fcluster` yourself anyway). Its unique value is HRP *weight allocation* — out of scope for a conviction-weighted book.

### 7b. quantstats — ADOPT (narrow)
- Input: a `pd.Series` of daily portfolio returns (DatetimeIndex). Core calls: `qs.stats.cagr/max_drawdown/volatility/sharpe/sortino`, `qs.reports.metrics(returns, benchmark=...)`, `qs.reports.html(returns, benchmark="SPY", output=...)`. Benchmark auto-fetched via yfinance (already in stack) or supplied as a Series.
- Pin `quantstats>=0.0.81`. Caveats: bursty maintenance, open metric-correctness issues (#493, #514, #516) → treat outputs as **indicative, not authoritative**; pandas-3.0 compatibility unstated.
- Portfolio returns series reconstructed from position snapshots × price history (approximation ignoring intra-period flows — good enough for a quarterly honesty check).

### 8. qlib — REJECT
- MIT, but an AI/ML quant research platform: 4–5 moving parts (binary data download in proprietary format, `qlib.init`, workflow configs) before any output; the only quasi-standalone module is an OHLCV/technical expression engine, CN-centric, with **zero fundamentals** (their docs: PE/EPS etc. "you could add … to the CSV" yourself). Nothing extractable for a fundamentals investor. Microsoft's energy is moving to RD-Agent (LLM factor mining) — deeper into the direction we don't want.

### 9. FinRL — REJECT
- MIT, education/research framing by its own README, with its own disclaimer ("Nothing herein constitutes financial advice…").
- The decisive evidence comes from **FinRL's own core team** (Liu, Wang et al., arXiv:2209.05559): standard walk-forward-trained DRL agents measured at 17.5% (PPO) and 21.3% (SAC) backtest-overfitting probability — rejected as overfitted under their own hypothesis test; FinRL-Meta's README concedes the simulation-reality gap. Cite as arXiv preprint (no confirmed formal proceedings).

---

## Ranked shortlist — the simple additions we actually take

1. **yfinance hardening trio** (cache/pacing, shares resampling, empty-statement detection) — the data-quality floor under owner-earnings analysis. *Data layer.*
2. **Hidden-concentration check** — pandas+scipy correlation clustering in the weekly balance review: "are my 12 positions really 3 bets?" + correlation matrix in the weekly report. Zero new dependencies. *Portfolio Mirror / weekly loop.*
3. **Quarterly honesty report** — quantstats (pinned) tear sheet + key stats of portfolio returns vs one index benchmark, **quarterly only** — deliberately quarantined from daily/weekly outputs (envy / action-bias rules). Answers Buffett's honesty question: "would an index fund beat my process?" *New quarterly cadence.*
4. **Manual quality screener** — TradingView-Screener, human-triggered, quality filters incl. absolute FCF/OCF/capex, results human-read, feeding the watchlist; every idea still passes the full Gate. *Idea generation.*
5. **Nothing else.** SEC EDGAR fallback only if yfinance statement gaps hit actual portfolio tickers. Everything else rejected.

Note: additions 3 and 4 are as much *behavioral rules* (when to measure, who triggers) as they are code — consistent with the framework being the point of the system.

## Requirements impact (proposed)

- **FR12** — weekly balance review includes correlation-cluster analysis: effective bet count + cluster membership + correlation matrix.
- **FR13** — quarterly performance honesty check vs one index benchmark; never surfaced in daily/weekly outputs.
- **FR14** — idea generation is human-triggered only; automated loops never scan for new candidates; screener output enters only the watchlist and only through the Gate.
- **NFR6** — data-layer hardening per yfinance findings (own caching/pacing; emptiness detection on every fundamentals field; shares-series resampling; staleness flagged in reports).
- **NFR7** — dependency discipline: permissive licenses only (MIT/Apache-2.0) in the runtime stack; no AGPL/GPL; no heavy transitive stacks (cvxpy-class) for narrow needs; every dependency must displace more complexity than it adds.

## Open items

- Benchmark choice for FR13 (S&P 500 TR vs MSCI World; USD vs EUR perspective) — config decision, defer to design.
- eToro API: portfolio read access, auth model, rate limits still to be verified with a real account key (separate task, unrelated to these repos).
- TradingView residual ToS tension: accepted consciously for occasional human-run screens; revisit if TradingView changes posture or an official API appears.
