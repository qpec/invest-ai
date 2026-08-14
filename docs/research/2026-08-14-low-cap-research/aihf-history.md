# virattt/ai-hedge-fund — the old persona-zoo architecture (v1, 2024–2026) recovered from git history

**Method.** The scratchpad clone at `/tmp/claude-0/-home-user-invest-ai/0e1d606b-c18b-5de9-bee2-f1d3534d6ef8/scratchpad/ai-hedge-fund` was shallow (1 commit); `git fetch --unshallow` recovered the full 904-commit history. The last commit carrying `src/agents/` is `84c2f9e` ("Fix news sentiment handling when news is missing"); the directory was deleted in `a7a99e5` ("Make 2.0.0 the default", 2026-08-02, author virattt). The complete v1 tree was exported to `/tmp/claude-0/-home-user-invest-ai/0e1d606b-c18b-5de9-bee2-f1d3534d6ef8/scratchpad/aihf-old/src/` — everything below is read from actual source, not blog reconstructions. All web claims are unnecessary; the code itself is authoritative.

## 0. Architecture in one paragraph

v1 was a **LangGraph StateGraph** (`src/main.py:create_workflow`): `start_node` fans out to every selected analyst **in parallel**, every analyst writes `{signal, confidence, reasoning}` per ticker into `state["data"]["analyst_signals"][agent_id]`, all analysts edge into `risk_management_agent`, which edges into `portfolio_manager`, which edges to `END`. 19 analysts were registered in `src/utils/analysts.py::ANALYST_CONFIG` (order 0–18): Aswath Damodaran, Ben Graham, Bill Ackman, Cathie Wood, Charlie Munger, Michael Burry, Mohnish Pabrai, Nassim Taleb, Peter Lynch, Phil Fisher, Rakesh Jhunjhunwala, Stanley Druckenmiller, Warren Buffett, Technical Analyst, Fundamentals Analyst, Growth Analyst, News Sentiment Analyst, Sentiment Analyst, Valuation Analyst. Data came from the financialdatasets.ai API (`get_financial_metrics`, `search_line_items`, `get_market_cap`, `get_insider_trades`, `get_company_news`, `get_prices`).

**The universal persona pattern** (same in every file): (1) fetch metrics + line items + market cap (+ news/insider trades for some), (2) run 3–7 **pure-Python sub-analyses** that each return `{score, details}` with hard-coded thresholds, (3) combine into `total_score` (sometimes weighted), (4) map to a preliminary signal (typically `>=0.7*max` bullish, `<=0.3*max` bearish, else neutral), (5) hand the numeric evidence to an LLM prompt in the investor's voice which returns `{signal: bullish|bearish|neutral, confidence: 0-100, reasoning}` (pydantic-validated, with a neutral default_factory on parse failure). So the Python did the measuring; the LLM did the judging and narrating — and could overrule the mechanical signal.

---

## 1. The persona catalogue — what each Python analysis computed

### Warren Buffett (`warren_buffett.py`, 826 lines)
Seven sub-analyses; total scored against `max_possible_score = 10 + moat(5) + mgmt(2) + pricing_power(5) + book_value(5)`:
- **Fundamentals (0–10 shown as ROE/debt/margins/liquidity, actually 0–7):** ROE > 15% → +2; debt/equity < 0.5 → +2; operating margin > 15% → +2; current ratio > 1.5 → +1.
- **Consistency:** ≥4 periods of net income; strictly monotone earnings growth → +3; also reports total growth from oldest to latest.
- **Moat (0–5):** ROE > 15% in ≥80% of ≥5 periods → +2 (60–80% → +1); operating margin avg > 20% and stable/improving → +1; any asset turnover > 1.0 → +1; combined ROE+margin stability (1 − stdev/mean) > 0.7 → +1.
- **Management (0–2):** negative `issuance_or_purchase_of_equity_shares` (buybacks) → +1; dividends paid → +1.
- **Pricing power (0–5):** gross-margin recent-vs-old improvement > +2pp → +3, improving → +2, stable ±1pp → +1; avg gross margin > 50% → +2, > 30% → +1.
- **Book value growth (0–5):** BVPS = equity/shares; growth in ≥80% of periods → +3 (≥60% → +2, ≥40% → +1); BVPS CAGR > 15% → +2, > 10% → +1; negative→positive flip → +3.
- **Owner earnings** = net income + D&A − maintenance capex − ΔWC. Maintenance capex estimated as the **median of three methods**: 85% of latest capex; 100% of D&A; 5-period avg capex/revenue × latest revenue. Sanity warnings if owner earnings < 30% of NI or maint-capex > 2× D&A.
- **Intrinsic value:** three-stage DCF on owner earnings. Historical NI growth capped to [−5%, +15%], then ×0.7 haircut; stage 1 = min(that, 8%) for 5y; stage 2 = min(half, 4%) for 5y; terminal 2.5%; discount 10%; final ×0.85 (additional 15% haircut). `margin_of_safety = (IV − market_cap)/market_cap`.
- **LLM prompt rules:** bullish only if strong business AND margin_of_safety > 0; neutral if good business but MoS ≤ 0. Confidence bands spelled out (90–100 exceptional-in-circle … 10–29 poor/overvalued).

### Charlie Munger (`charlie_munger.py`, 856 lines)
Weighted: **moat 35% + management 25% + predictability 25% + valuation 15%**, each sub-score scaled 0–10.
- **Moat:** ROIC > 15% (Munger's threshold) in ≥80% of periods → +3 (≥50% → +2, any → +1); gross margins improving in ≥70% of periods → +2 or avg > 30% → +1; **capex/revenue < 5% → +2, < 10% → +1** (low capital intensity); R&D spend exists → +1; goodwill/intangibles exist → +1. Raw /9 → 0–10.
- **Management:** capital allocation (FCF/NI conversion), debt/equity, cash/revenue balance, insider buys vs sells, falling share count.
- **Predictability (needs 5+ years):** revenue avg growth > 5% with volatility < 0.1 → +3; positive op income in all periods → +3; op-margin mean-abs-deviation < 0.03 → +2; positive FCF in all periods → +2. Raw /10 → 0–10.
- **Valuation:** normalized FCF = 5y average; **FCF yield > 8% → +4, > 5% → +3, > 3% → +1**; IV range = 10×/15×/20× normalized FCF (conservative/reasonable/optimistic); MoS vs 15× value > 30% → +3, > 10% → +2, within ±10% → +1; FCF recent-3y avg > older ×1.2 → +3. Also a deterministic `compute_confidence` helper weighted toward quality.

### Ben Graham (`ben_graham.py`, 348) — max 15 pts across three blocks
- **Earnings stability:** EPS positive in all periods → +3 (≥80% → +2); EPS grew first→last → +1.
- **Financial strength:** current ratio ≥ 2.0 → +2 (≥1.5 → +1); total-liabilities/total-assets < 0.5 → +2 (< 0.8 → +1); dividends paid in majority of years → +1.
- **Graham valuation:** **NCAV = current assets − total liabilities; NCAV > market cap → +4** ("classic Graham deep value"); NCAV/share ≥ ⅔ price → +2. **Graham Number = √(22.5 × EPS × BVPS)**; MoS vs price > 50% → +3, > 20% → +1.
- Signal: ≥70% of 15 bullish, ≤30% bearish.

### Michael Burry (`michael_burry.py`, 376) — deep-value contrarian, max 12 pts
- **Value (6):** **FCF yield ≥ 15% → +4, ≥ 12% → +3, ≥ 8% → +2**; **EV/EBIT < 6 → +2, < 10 → +1**.
- **Balance sheet (3):** D/E < 0.5 → +2, < 1 → +1; **cash > total debt (net cash) → +1**.
- **Insider activity (2):** net buying over trailing 365 days; net buys > sells → +1, buys/sells ratio > 1 → +2 ("hard catalyst").
- **Contrarian sentiment (1):** **≥5 negative headlines → +1** — hatred in the press is a *positive* if fundamentals hold.
- Prompt: "Focus on downside first – avoid leveraged balance sheets… terse, data-driven style" with example outputs like "FCF yield 12.8%. EV/EBIT 6.2. … Strong buy."

### Peter Lynch (`peter_lynch.py`, 507) — GARP, weighted 30% growth + 25% valuation + 20% fundamentals + 15% sentiment + 10% insider (each 0–10; bullish ≥ 7.5, bearish ≤ 4.5)
- **Growth:** revenue growth over ~5y > 25% → +3, > 10% → +2, > 2% → +1; same bands for EPS. Raw /6 → 0–10.
- **Fundamentals:** D/E < 0.5 → +2, < 1.0 → +1; op margin > 20% → +2, > 10% → +1; positive FCF → +2.
- **Valuation — the PEG bands:** P/E ≈ market_cap/NI; EPS growth as CAGR; **PEG = P/E ÷ (growth×100). PEG < 1 → +3, < 2 → +2, < 3 → +1**; plus P/E < 15 → +2, < 25 → +1. Raw /5 → 0–10.
- **Sentiment:** keyword scan (lawsuit/fraud/decline/investigation/recall…); >30% negative headlines → 3/10, some → 6/10, none → 8/10.
- **Insider:** buy ratio > 0.7 → 8/10, > 0.4 → 6/10, else 4/10.
- Prompt: cite PEG, mention "ten-bagger" potential, folksy voice ("If my kids love the product…").

### Phil Fisher (`phil_fisher.py`, 603) — growth-quality, weighted 30/25/20/15/5/5 (growth-quality / margins-stability / mgmt-efficiency / valuation / insider / sentiment)
- **Growth & quality:** revenue CAGR > 20% → +3, > 10% → +2, > 3% → +1; EPS CAGR same bands; **R&D/revenue in 3–15% → +3** ("healthy"), > 15% → +2, > 0 → +1. Raw /9.
- **Margins & stability:** op margin stable-or-improving → +2; gross margin > 50% → +2, > 30% → +1; op-margin pstdev < 0.02 → +2, < 0.05 → +1. Raw /6.
- **Management efficiency:** ROE > 20% → +3, > 10% → +2, > 0 → +1; D/E < 0.3 → +2, < 1.0 → +1; positive FCF in > 80% of periods → +1. Raw /6.
- **Valuation (Fisher pays up but checks):** P/E < 20 → +2, < 30 → +1; P/FCF < 20 → +2, < 30 → +1. Raw /4.

### Mohnish Pabrai (`mohnish_pabrai.py`, 359) — "heads I win, tails I don't lose much"; weighted **downside 45% + valuation 35% + double-potential 20%** (bullish ≥ 7.5, bearish ≤ 4.0)
- **Downside protection:** net cash (cash > total debt) → +3; current ratio ≥ 2 → +2 (≥1.2 → +1); D/E < 0.3 → +2 (< 0.7 → +1); positive & stable/improving FCF (3y avg) → +2.
- **Valuation:** normalized FCF = 5y avg; **FCF yield > 10% → +4, > 7% → +3, > 5% → +2, > 3% → +1**; **asset-light bonus: avg capex/revenue < 5% → +2, < 10% → +1**.
- **Double-in-2-3-years:** 3y-avg revenue growth > 15% → +2 (>5% → +1); FCF growth > 20% → +3 (>8% → +2, >0 → +1); **FCF yield > 8% → +3** ("doubling can come from cash generation alone").

### Aswath Damodaran (`aswath_damodaran.py`, 419) — the valuation professor
- **Growth (0–4):** 5y revenue CAGR > 8% → +2, > 3% → +1; positive FCFF growth → +1; ROIC > WACC → +1.
- **Risk (0–3):** beta < 1.3 → +1; D/E < 1 → +1; interest coverage > 3× → +1.
- **Relative valuation (±1):** TTM P/E < 70% of 5y median → +1; > 130% → −1.
- **Intrinsic value:** FCFF DCF — base = latest FCF, growth = 5y revenue CAGR capped 12%, fading linearly to 2.5% terminal by year 10, discounted at CAPM cost of equity. Signal driven mainly by margin of safety (bullish if MoS > ~25%).

### Bill Ackman (`bill_ackman.py`, 468) — quality + activism; max 20 (four ~5-pt blocks)
- **Quality:** cumulative revenue growth > 50% → +2 (positive → +1); op margin > 15% in majority of periods → +2; positive FCF majority → +1; ROE > 15% → +2.
- **Financial discipline:** deleveraging trend, dividends/buybacks over multiple periods.
- **Activism potential:** revenue growing but op margin < 10% → "operational upside a activist could unlock" → points.
- **Valuation:** DCF on latest FCF, growth 6%, discount 10%, terminal multiple 15×, 5y horizon; MoS > 30% → +3, > 10% → +1.

### Cathie Wood (`cathie_wood.py`, 436) — disruption; max 15 across 3 blocks
- **Disruptive potential:** revenue growth *acceleration* (later YoY > earlier +2pp), gross-margin expansion, R&D intensity > 15% of revenue, capex intensity as growth signal.
- **Innovation growth:** R&D growth > 50% → +3; FCF funding capacity; operating leverage.
- **Valuation (aggressive DCF):** growth 20%, discount 15%, terminal multiple 25×, 5y; MoS > 50% → +3, > 20% → +1. (Same skeleton as Ackman's DCF with hyper-growth parameters — persona = parameter set.)

### Stanley Druckenmiller (`stanley_druckenmiller.py`, 602) — growth+momentum, weighted 35/20/20/15/10 (growth-momentum / risk-reward / valuation / sentiment / insider)
- **Growth & momentum:** revenue CAGR > 8% → +3, > 4% → +2, > 1% → +1; EPS CAGR same; **price momentum over lookback: +50% → +3, +20% → +2, >0 → +1**. Raw /9. The only persona that consumed the price series directly.
- **Risk-reward:** D/E < 0.3 → +3, < 0.7 → +2, < 1.5 → +1; daily-return stdev < 1% → +3, < 2% → +2, < 4% → +1.
- **Valuation:** P/E, P/FCF, EV/EBIT, EV/EBITDA bands (e.g. P/E < 15 → +2, < 25 → +1).

### Rakesh Jhunjhunwala (`rakesh_jhunjhunwala.py`, 707) — Indian growth-quality bull; max 24 = profitability 8 + growth 7 + balance sheet 4 + cash flow 3 + management 2
- **Profitability:** ROE > 20% → +3, > 15% → +2, > 10% → +1; op margin > 20% → +2, > 15% → +1; EPS CAGR > 20% → +3, > 15% → +2, > 10% → +1.
- **Growth:** revenue CAGR > 20% → +3, > 15% → +2, > 10% → +1; NI CAGR > 25% → +3, > 20% → +2, > 15% → +1; growth in ≥80% of years → +1.
- **Intrinsic value:** 5y earnings DCF where growth is a haircut of historical CAGR (capped at 20%), and **quality sets the discount rate: high quality 12% + 18× terminal, medium 15% + 15×, low 18% + 12×**; fallback = 12–15× earnings.

### Nassim Taleb (`nassim_taleb.py`, 761) — the most quantitative persona; 7 probes, raw-added max ≈ 50
- **Tail risk (0–8):** 63-day rolling **kurtosis > 5 → +2** (>2 → +1; near-Gaussian labeled "suspiciously thin"); **skew > 0.5 → +2**; tail ratio (95th pct gains / |5th pct losses|) > 1.2 → +2; max drawdown better than −15% → +2.
- **Antifragility (0–10):** net cash > 20% of market cap → +3; D/E < 0.3 → +2; op-margin CV < 0.15 with mean > 15% → +3; FCF positive in all periods → +2.
- **Convexity (0–10):** R&D optionality, upside/downside ratio, cash optionality.
- **Fragility via negativa (0–8):** high score = NOT fragile.
- **Skin in the game (0–4):** net insider buying.
- **Volatility regime (0–6):** the "turkey problem" — persistently *low* volatility scored as dangerous.
- **Black-swan sentinel (0–4):** abnormal negative-news ratio, volume spikes, price dislocations.

### The six non-persona analysts
- **valuation.py (494):** four methods blended — **DCF 35% + owner-earnings 35% + EV/EBITDA 20% + residual income 10%**; each produces a value, `gap = (value − mcap)/mcap`; **weighted gap > +15% → bullish, < −15% → bearish; confidence = min(|gap|/0.30, 1)×100**. DCF is scenario-based (bear/base/bull) on FCF history with a computed WACC (risk-free 4.5%, ERP 6%, beta proxy 1.0, distress premia from interest coverage) and FCF-volatility damping. Owner-earnings method: Buffett formula, growth 5%, required return 15%, MoS 25% baked in.
- **fundamentals.py (163):** fully deterministic, no LLM. Four signal groups voted: profitability (ROE > 15%, net margin > 20%, op margin > 15% — 2 of 3 → bullish); growth (revenue/earnings/BV growth each > 10%); health (current ratio > 1.5, D/E < 0.5, FCF/share > 0.8×EPS); price ratios (P/E > 25, P/B > 3, P/S > 5 → bearish votes). Overall = majority vote; confidence = winning votes / 4.
- **growth_agent.py (338):** weights growth 40% / valuation 25% / margins 15% / insider 10% / health 10% on 0–1 scores (PEG < 1 → +0.5, P/S < 2 → +0.5; margins with trend bonuses; insider by dollar flow). weighted > 0.6 bullish, < 0.4 bearish; confidence = |score−0.5|×2.
- **sentiment.py (138):** deterministic. **Insider trades weight 0.3, news sentiment weight 0.7**; weighted bullish vs bearish counts; confidence = winning weighted share.
- **news_sentiment.py (221):** LLM classifies headlines; confidence = 70% LLM confidence + 30% signal proportion.
- **technicals.py (531):** deterministic 5-strategy ensemble — **trend 25% (EMA 8/21/55 + ADX), mean-reversion 20% (z-score vs 50d MA, Bollinger, RSI 14/28), momentum 25% (1m/3m/6m returns + volume), volatility 15% (21d hist vol, vol regime), stat-arb 15% (63d skew/kurtosis, Hurst exponent)**; signals mapped to ±1 and combined by weight×confidence.
- **risk_manager.py / portfolio_manager.py:** see §2.

## 2. Signal flow: analysts → risk manager → portfolio manager

1. **Analysts (parallel):** each writes `{ticker: {signal, confidence, reasoning}}` into shared state. No analyst sees another's output.
2. **Risk manager (`risk_manager.py`, 317 — deterministic, no LLM):** ignores analyst opinions entirely; computes **position limits**. Base limit 20% of portfolio NAV per ticker, scaled by realized volatility (60-day, annualized): ann.vol < 15% → up to 25%; 15–30% → 20%→12.5% linear; 30–50% → 15%→5%; > 50% → capped 10% (multiplier clamp 0.25–1.25). Then a **correlation multiplier** vs existing positions: avg corr ≥ 0.8 → ×0.70, ≥ 0.6 → ×0.85, ≥ 0.4 → ×1.0, ≥ 0.2 → ×1.05, < 0.2 → ×1.10. Output per ticker: `remaining_position_limit` (also capped by cash) + `current_price`. Missing price data → limit 0 (fail closed).
3. **Portfolio manager (`portfolio_manager.py`, 262 — LLM with deterministic guardrails):** Python first computes **allowed actions** per ticker (buy/sell/short/cover/hold with max quantities from the risk limit, cash, and margin: `available_margin = equity/margin_req − margin_used`). Tickers where only "hold" is possible are **pre-filled without an LLM call**. The rest go to an LLM with a minimal prompt: compressed `{agent: {sig, conf}}` signals + allowed actions; "Pick one allowed action per ticker and a quantity ≤ the max… No cash or margin math." Parse failure → hold. So the LLM chose *among pre-validated actions*; it could never size beyond the deterministic caps — the same "conviction requests, risk disposes" principle the v2 VISION.md later made explicit.

Notable: there was **no numeric aggregation of the 19 signals** — no weighted average of persona conviction. The "blend" was the portfolio-manager LLM eyeballing a JSON dict of `{sig, conf}` pairs. That's a key weakness the v2 rewrite fixed with conviction-weighted portfolio construction.

## 3. Which personas matter most for small/micro-cap analysis

- **Graham** — the only agent with a **net-net/NCAV test (NCAV > market cap → +4)** and the Graham Number. NCAV situations essentially only exist in micro-caps; the current-ratio ≥ 2 / debt-ratio < 0.5 / dividend-record checks are balance-sheet-first, exactly what thin-coverage names need. Caveat: needs `book_value_per_share` and EPS positive.
- **Burry** — purpose-built for neglected small caps: raw **FCF yield ≥ 8/12/15%** bands, **EV/EBIT < 6**, **net-cash** check, and two catalysts that matter disproportionately in micro-caps: **insider net buying** (management skin in a name nobody covers) and **negative-headline contrarianism**. Smallest data footprint of the persona set — works when only 1–2 filings exist (metrics limit=5, ttm).
- **Lynch** — small caps are where GARP lives: **PEG < 1** on a 25%+ grower is essentially a small-cap phenomenon; the "ten-bagger" framing presumes a small base. D/E < 0.5 and positive-FCF checks filter the junky end. Weakness: PEG needs positive, growing EPS across ≥2 periods — refuses on pre-profit names (correctly).
- **Fisher** — the quality-growth screen for small caps that will *become* big: R&D/revenue 3–15% sweet spot, margin-stability stdev tests, ROE > 20%. Best for identifying which micro-cap is a real compounder vs a promotional story; its insider/scuttlebutt inputs are exactly the information edge that exists in under-covered names.
- **Pabrai** — the most directly transplantable rubric: **45% weight on downside protection** (net cash, current ratio ≥ 2, D/E < 0.3), normalized 5-year FCF yield > 10%, asset-light capex < 5% of revenue, and an explicit "double in 2–3 years" test. Low-risk-high-uncertainty framing is the canonical micro-cap value setup.
- Honorable mentions: **Taleb's** antifragility probe (net cash > 20% of mcap; the fragility via-negativa) is a good micro-cap survival screen; **fundamentals.py** is a decent deterministic first-pass filter. **Least relevant:** Wood (TAM/hyper-growth DCF with 20% growth assumption is a story-stock amplifier), Ackman (activism logic presumes institutional scale), Druckenmiller (momentum + macro on thin liquidity), and both sentiment agents (micro-caps have too little news for keyword counting to mean anything).

## 4. Why the project abandoned the persona zoo — and the lessons

The v2 rewrite (commit `a7a99e5` deleted `src/agents/`; the repo now ships the `hedge_fund/` package, version 2.2.0) restructured around `VISION.md` + `ROADMAP.md`:

**What v2 actually is:** one pipeline `run_cycle` = `data → analysts → portfolio → risk → execution → ledger`, run in three modes (backtest / paper / live) where only the clock and broker change. Analysts implement one `AlphaModel` interface returning a `Signal` (conviction in [-1,+1] + thesis) — **LLM personas and quant models (e.g. PEAD in `hedge_fund/signals/pead.py`) are the same plug**. Only 5 personas were ported (buffett, munger, graham, lynch, druckenmiller in `hedge_fund/signals/`); Burry/Fisher/Pabrai/Wood/Ackman/Damodaran/Taleb/Jhunjhunwala remain roadmap items marked ⬜ as "a great first contribution."

**How the ported personas changed — the biggest lesson:** in v2 a persona is *only a system prompt* (`hedge_fund/signals/buffett.py`: "The persona is ONLY a system prompt — all machinery lives in LLMAgent"). The thousands of lines of per-persona Python scoring were deleted. All personas now reason over one shared, point-in-time `FundamentalsSnapshot` (`hedge_fund/features/snapshot.py`) with a handful of *centrally computed* aggregates (roe_avg, net_margin_avg, gross_margin_trend, bvps_cagr, debt_to_equity_latest, market_cap_latest). The differentiation moved entirely into the prompt checklist; the metric computation was deduplicated and hardened once.

**Stated reasons (VISION.md, ROADMAP.md, and the v2 code docstrings):**
1. **"Most AI trading projects are one-shot scripts: run it, get a signal, exit."** v1 was exactly that — no persistent book, no NAV memory, no track record. v2's core object is a *fund* with a ledger ("The Books"), mandates, and capital slices.
2. **Backtestability.** v1 personas could not be honestly backtested: the persona code freely mixed "latest" metrics with no filing-date discipline. v2's non-negotiables: **"Point-in-time honesty. On any simulated date, the fund may only use data that was actually public by then. No lookahead, ever"** and **"The backtest is the live system. Same pipeline, same code."** The snapshot even renders *date-free* so the LLM can't anchor on calendar knowledge of post-date events.
3. **The LLM's role was shrunk and fenced.** "The LLM never touches the trade. Language models form views and narrate decisions. Deterministic code sizes positions and places orders, and risk limits are hard gates an agent cannot exceed." v1 already gestured at this (allowed-actions pre-validation) but still let an LLM pick quantities; v2 makes portfolio construction conviction-weighted *math*.
4. **A defined failure contract.** v1: any LLM/parse failure silently became `neutral, confidence 0` — indistinguishable from a genuine neutral view, and averaged into decisions. v2 locks: data errors **propagate** (fail loud), LLM failures **abstain** (`Signal(0.0, metadata.abstained=True)`), every LLM decision persists its exact prompt+response, and an unchanged snapshot never pays for a second LLM call (`content_hash` prompt cache).
5. **Cost/duplication.** 19 agents × N tickers × LLM call per run, each with its own copy-pasted insider/sentiment/valuation helpers (Lynch's and Fisher's `analyze_sentiment`/`analyze_insider_activity` are literal duplicates; Ackman's and Wood's DCFs are the same code with different constants). v2: one snapshot build, one cached call per persona per *fundamentals change*, not per date.
6. **Composability over headcount.** v2 organizes analysts into Strategies ("pods": `hedge_fund/strategies/{fundamental-ls,deep-value,inflections,earnings-drift}.yaml`) under a CIO allocator, netted into one book under master risk — the persona list stops being the product and becomes a contribution surface.

**Lessons for anyone building a persona-based analysis system (e.g. stock-agentcy):**
- **Personas differ legitimately in *judgment*, not in *arithmetic*.** Compute every metric once, in one tested module; let personas differ only in checklist, weighting, and voice. v1's per-persona math independently reinvented FCF yield ~6 times with 6 different threshold sets — some contradictory (Munger's "excellent" 8% FCF yield is Burry's "low" < 8%). That contradiction is fine as *judgment* but was buried as *code*.
- **Score-then-narrate beats narrate-then-score, but only if the mechanical signal is binding or the override is logged.** In v1 the LLM could silently overrule the computed signal; nothing recorded when or why.
- **Fallback-to-neutral is a silent failure mode.** Distinguish "abstained" from "neutral view" in the schema.
- **Point-in-time discipline must be structural, not per-agent.** One snapshot builder that refuses lookahead beats 19 agents each calling the API with an end_date parameter they may or may not respect.
- **A persona without a backtest is a costume.** The whole v2 thesis: if a persona can't be expressed on the same PIT data path as a quant model and backtested as an `AlphaModel`, its value is unfalsifiable.
- **Thresholds are the persona.** The recovered tables above (Graham's 22.5, Lynch's PEG<1, Burry's EV/EBIT<6, Pabrai's 45% downside weight, Munger's capex<5% of revenue) are the durable, reusable content of the zoo — they survive any architecture.

**Key file paths (recovered v1 tree):** `/tmp/claude-0/-home-user-invest-ai/0e1d606b-c18b-5de9-bee2-f1d3534d6ef8/scratchpad/aihf-old/src/agents/*.py`, `/tmp/claude-0/-home-user-invest-ai/0e1d606b-c18b-5de9-bee2-f1d3534d6ef8/scratchpad/aihf-old/src/utils/analysts.py`, `/tmp/claude-0/-home-user-invest-ai/0e1d606b-c18b-5de9-bee2-f1d3534d6ef8/scratchpad/aihf-old/src/main.py`. **v2:** `/tmp/claude-0/-home-user-invest-ai/0e1d606b-c18b-5de9-bee2-f1d3534d6ef8/scratchpad/ai-hedge-fund/{VISION.md,ROADMAP.md,hedge_fund/signals/llm_agent.py,hedge_fund/features/snapshot.py}`.
