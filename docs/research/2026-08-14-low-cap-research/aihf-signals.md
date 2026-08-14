# ai-hedge-fund: philosophy-signal deep read

Source: `/tmp/claude-0/-home-user-invest-ai/0e1d606b-c18b-5de9-bee2-f1d3534d6ef8/scratchpad/ai-hedge-fund/hedge_fund/signals/` and `.../strategies/`. All line references are to files in that clone.

## 0. The headline architectural fact

**The five investor "philosophy signals" (Graham, Buffett, Munger, Lynch, Druckenmiller) contain NO computed decision rules.** Each file is ~55 lines and consists solely of a `name` property and a `get_system_prompt()` returning a persona system prompt. All machinery lives in `LLMAgent` (`signals/llm_agent.py`); all numbers come from a shared point-in-time `FundamentalsSnapshot` (`features/snapshot.py`). The thresholds below (Graham's P/E 15–20, Lynch's PEG) are *prompt text the LLM is asked to apply*, not Python. The **only pure-quant philosophy model is PEAD** (`signals/pead.py`), subclassing `QuantModel`.

Class tree (`signals/base.py`): `AlphaModel` (ABC, `name` + `predict(ticker, date, data_client) -> Signal`, hard point-in-time rule: only data with date <= as-of) → `QuantModel` (pure math, helpers: `_safe_float`, `_percentile_rank`, `_normalize_to_signal` clamp to [-1,1], `_sigmoid` = `tanh(x*5)`, `_compute_rsi` 14-period) and → `LLMAgent`.

Registry (`signals/__init__.py`): `ALPHA_MODEL_REGISTRY = {"pead": PEADModel, "buffett": BuffettAgent, "munger": MungerAgent, "graham": GrahamAgent, "lynch": LynchAgent, "druckenmiller": DruckenmillerAgent}`.

## 1. Shared LLM-agent machinery (`llm_agent.py`)

- `predict()` builds a `FundamentalsSnapshot`; `InsufficientData` (fewer than `MIN_PERIODS = 4` filed TTM rows, `snapshot.py:26`) → **abstain** `Signal(value=0.0, metadata.abstained=True)`. Any other data-layer error **propagates** ("fail loud — a broken snapshot must never silently become a neutral view", locked decision in the module docstring; test `test_data_layer_error_propagates`).
- LLM call failure or JSON parse failure → abstain (value 0.0, `abstained=True`, reason recorded). Unparseable raw responses are still persisted with a `parse_error` key ("the debug trail").
- Response contract, validated in `_parse()`: `{"signal": "bullish"|"bearish"|"neutral", "confidence": 0-100, "reasoning": str}`; invalid signal or confidence out of [0,100] raises → abstain.
- **Value folding** (`_to_signal`, line 146): `value = {"bullish": +1, "neutral": 0, "bearish": -1}[signal] * confidence / 100.0` → conviction in [-1, +1]. Tests pin: bullish/80 → +0.8, bearish/60 → −0.6, neutral/90 → 0.0.
- **Prompt cache = persistence + spend control**: cache key = `prompt_key(agent_name, llm_model, system, user)`; the snapshot's `content_hash` (sha256 of the pydantic JSON *excluding* `as_of`, first 24 hex chars) and `render()` are both date-free, so two dates between filings produce identical prompts → cache hit, no second paid call (`test_new_as_of_same_data_hits_cache`); a new filing changes the hash and forces re-reasoning (`test_new_filing_forces_new_llm_call`). Every decision persists exact system+user prompt, raw response, parsed result, snapshot hash.
- All persona prompts share two hard rules, pinned by `test_llm_personas_share_the_contract`: the string "most recent filing date" (the PIT rule: treat the newest filing as the present, use no knowledge after it, don't invent numbers) and the JSON schema keys.

### Input data every persona sees (`features/snapshot.py`)

`FundamentalsSnapshot` = up to 20 TTM `PeriodFundamentals` rows (newest first), each row filtered by **filing_date** ≤ as_of (not report_period — provably public). Per-row fields: `report_period, filing_date, market_cap, price_to_earnings_ratio, return_on_equity, gross_margin, operating_margin, net_margin, debt_to_equity, current_ratio, revenue_growth, earnings_per_share, book_value_per_share, free_cash_flow_per_share`. Plus Python-derived aggregates so the LLM doesn't do arithmetic: `roe_avg`, `net_margin_avg`, `gross_margin_trend` (latest − oldest), `bvps_cagr` (annualized over quarter-spaced TTM rows: `(latest/oldest)^(4/(n-1)) − 1`), `debt_to_equity_latest`, `market_cap_latest`, and sector/industry from latest company facts (documented PIT approximation). `render()` emits a compact pipe-delimited table headed "All figures below were publicly filed by their filing dates. Treat the most recent filing shown as the present." Market cap deliberately comes from the most recent *filed* metrics row, not `get_market_cap()` (latest-only = lookahead).

**Nothing else.** No price history, no news, no analyst estimates, no macro, no insider/ownership data reaches any persona.

## 2. Per-persona decision rules (all prompt-text, `graham.py` / `buffett.py` / `munger.py` / `lynch.py` / `druckenmiller.py`)

### Graham (`name="graham"`) — "margin of safety above all," defensive investor
Criteria in the prompt: (1) **Margin of safety** — price low vs demonstrated earning power and book value; compare P/E and P/B ("infer from market cap, EPS, and book value per share"); "A P/E far above 15-20 demands extraordinary justification you will rarely grant." (2) **Financial strength** — "current ratio comfortably above 1.5, modest debt to equity. A weak balance sheet disqualifies regardless of prospects." (3) **Earnings stability** — positive earnings across the whole shown record, no wild swings. (4) Deep suspicion of paying for projected growth. Signal rules: bullish = sound business + strong balance sheet + genuine margin of safety; bearish = weak finances, unstable earnings, or price capitalizing hope — "Overvaluation IS a bearish fact"; neutral = sound enterprise, inadequate margin of safety. Confidence bands: 90–100 clear quantitative case on every criterion; 70–89 most met; 40–69 mixed; 10–39 speculative. **Note: there is no net-net / NCAV computation anywhere — the snapshot has no current-assets or total-liabilities fields, so a true Graham net-net screen is impossible with this data surface.**

### Buffett (`name="buffett"`) — long-term business owner
Checklist: circle of competence (understandable from the data given); moat = "durable high returns on equity, stable or improving margins, pricing power"; management via numbers (book value compounding, sensible leverage, consistent FCF); financial strength (low debt, healthy current ratio, consistent earnings); valuation ("wonderful company at a fair price beats a fair company at a wonderful price"); the 10-year holding test. Bullish = strong durable business at reasonable-or-better price; bearish = weak/deteriorating business or price demanding perfection; neutral = mixed, or great business at clearly excessive price.

### Munger (`name="munger"`) — quality, judged without mercy
Mental models: **invert** (look for deteriorating margins, rising leverage, eroding ROE); quality = high returns on capital "year after year without heroic assumptions," consistency across the whole history; incentives/capital allocation (book value compounding, FCF real and growing); price (fair OK, silly not); the **too-hard pile** — "if the numbers don't paint a clear picture… say so and go neutral. Most things do." Bearish includes "dishonest-looking numbers." Extra hard rule: "Be blunt. No hedging." Confidence 90–100 explicitly labeled "rare."

### Lynch (`name="lynch"`) — GARP, "know what you own"
(1) **Categorize**: fast grower (20%+ earnings growth), stalwart (10–12%), slow grower, or turnaround — "your expectations and your signal depend on the category." (2) **The PEG test**, stated verbally not as a formula: "compare the P/E to the earnings growth rate you can actually see in the numbers. A P/E well below the growth rate is attractive; a P/E far above it means you're paying for a story." (3) Story check: revenue growth → earnings growth, margins holding, "EPS marching upward quarter after quarter." (4) Avoid debt-loaded companies. (5) "Earnings drive stock prices… that's the whole game." Bullish = visible growth at a P/E that doesn't price it in (PEG comfortably attractive); bearish = decelerating growth at a premium multiple ("that's how people lose money"); neutral = fully priced, or category undeterminable. Extra rule: "Plain language. If you can't explain the story simply, go neutral."

### Druckenmiller (`name="druckenmiller"`) — inflections and asymmetry
Honest scope note in the docstring: **no macro, rates, or price-action data — fundamentals-trajectory only**, and the prompt tells the persona not to pretend otherwise. Read: (1) inflection — recent quarters vs older ones, revenue growth accelerating/decelerating, margins inflecting/rolling over, "direction and rate-of-change matter more than levels"; (2) EPS momentum in the most recent periods; (3) what's priced in — "a rich P/E on accelerating numbers can still be a buy; a cheap P/E on deteriorating numbers is usually a trap"; (4) asymmetry — "If the setup is merely average, the correct position is none"; (5) never lose big — "deteriorating fundamentals plus leverage… is a short or a pass, never a hold."

## 3. PEAD (`pead.py`) — the one real quant model

**Rule**: long after an EPS **BEAT**, short after a **MISS**, fixed ±1.0 conviction ("scaling by surprise size is a future enhancement"), else 0.0. Exact logic in `predict()`:
1. Fetch earnings history (`data_client.get_earnings_history(ticker, limit=8)`, cached per ticker for the whole backtest).
2. Qualify events (`_qualifying_events`): need `filing_date`, `quarterly.eps_surprise in ("BEAT","MISS")`; **45-day retrospective filter** — drop rows where `filing_date − report_period >= 45` days (`_RETROSPECTIVE_CUTOFF_DAYS = 45`; guards against the extractor parsing prior-quarter comparison data out of a current 8-K); **dedupe per report_period preferring the earliest announcement source**: `_SOURCE_PRIORITY = {"8-K": 0, "10-Q": 1, "10-K": 2, "20-F": 3}`.
3. Point-in-time: only filings with `filing_date <= as_of` (test: a filing dated after the query date is invisible).
4. **Freshness window**: fire only if `(as_of − filing_date).days <= signal_window_days` (default **4** — bridges weekends; a 30-day-old event is neutral).
5. Output `Signal(value=±1.0)` with reasoning like "BEAT on 2025-06-30 earnings (filed 2025-08-01, 8-K)" and metadata `{eps_surprise, source_type, report_period, filing_date}`. MEET → neutral; no history → neutral.

Inputs: `EarningsRecord` list (ticker, report_period, source_type, filing_date, `quarterly.eps_surprise`). Where BEAT/MISS is computed is upstream in the data layer, not in this file.

## 4. Output shape (all models)

`hedge_fund/models.py::Signal`: `{model_name, ticker, date, value: float ∈ [-1,+1] (0.0 = abstain/no view), reasoning: str|None, components: dict[str,float], metadata: dict}`. LLM agents additionally carry `metadata = {signal, confidence, model, prompt_key, snapshot_hash, cached, abstained}`. Portfolio construction (`portfolio/construction.py::blend_signals`) turns convictions into weights: `weight_t = conviction_t / Σ|convictions| * gross_target`; with `market_neutral`, convictions are demeaned cross-sectionally first (uniform views go flat).

## 5. Strategy YAMLs (`hedge_fund/strategies/`)

**No YAML specifies a universe.** `FundSpec` is "deliberately ticker-free: a mandate is the DESK… not a watchlist" (`fund/spec.py:103-108`); tickers are a run-time input through `normalize_universe()` (uppercase, dedupe, order-preserving, empty raises), and `load_spec` drops a legacy `universe` key from old files. All four use `blend: {method: conviction_weighted, gross_target: 1.0}`; unlisted model weight defaults to 1.0 (`ModelSpec.weight`).

| Strategy | Models (weight) | Blend extras | Stated edge |
|---|---|---|---|
| `deep-value.yaml` (Deep Value) | graham (**2.0**), buffett (1.0), munger (1.0) | — | "mispriced quality with a margin of safety"; long-biased, quarterly horizon |
| `earnings-drift.yaml` (Earnings Drift) | pead (1.0) | — | systematic, event-time; "the model is the strategy" |
| `fundamental-ls.yaml` (Fundamental L/S) | all five at 1.0 | **market_neutral: true** | flagship discretionary pod; "collective judgment ranks names better than the market prices them" |
| `inflections.yaml` (Inflections) | druckenmiller (1.0), lynch (1.0) | — | long/short on fundamentals rate-of-change "before the multiple reprices it" |

Fund defaults (`FundSpec`): capital 100,000; rebalance weekly (daily/weekly/monthly allowed); benchmark SPY; master `RiskLimits` on the netted book. Models are instantiated once per fund so LLM prompt caches and the PEAD earnings cache survive across cycles; a persona in two strategies gets two instances but shares the disk prompt cache.

## 6. Small-cap fit ($50M–$2B), per philosophy

- **Graham — excellent fit historically, partially expressible here.** Deep value/net-net is the canonical small/micro-cap philosophy: statistical cheapness vs book and demonstrated earnings persists exactly where institutions can't deploy size and coverage is thin. The implementation supports the P/E≤15-20, current-ratio>1.5, P/B and earnings-stability legs from the snapshot; it **cannot** do net-nets (no NCAV fields). Caveat: small-cap value is where value traps and dying microcaps live, and the persona has no liquidity or delisting-risk view.
- **Buffett — structurally poor fit as implemented; the *early*-Buffett variant would fit but isn't what the prompt encodes.** The prompt encodes late-Buffett quality-compounder criteria (durable moats, decade-long ROE consistency, pricing power) — properties that are rare and hard to certify in $50M–$2B names, where the snapshot may barely clear 4 TTM periods and moats are unproven. (Buffett's own "I could make 50% a year on $1M" refers to Graham-style workouts, not this checklist.) Expect frequent low-confidence/neutral output down-cap.
- **Munger — deliberately hostile to small caps, which is a feature.** "Most things belong in the too-hard pile" plus the demand for consistency "across the whole history" means short-history, noisy small caps land neutral by design. Useful as a veto/quality brake in a small-cap book (its role in deep-value.yaml), not as an idea generator.
- **Lynch — the best philosophical fit of the five.** Lynch at Magellan explicitly hunted under-covered small/mid fast growers before analysts arrived ("tenbaggers"); PEG discriminates well exactly where growth is fast and multiples dispersed. The implementation sees revenue growth, EPS trajectory, P/E, and D/E — enough for a real GARP read. Missing vs the real Lynch: no same-store/unit economics, no insider buying, no institutional-ownership ("nobody owns it yet") signal.
- **Druckenmiller — philosophy is cap-agnostic, implementation is handicapped.** Fundamental inflections are *more* violent and *less* pre-priced in small caps (low coverage → slow repricing), so the edge should be larger down-cap. But the persona has no price action, positioning, or macro — the pillars of actual Druckenmiller — and quarterly small-cap fundamentals are noisy, so "acceleration" over 4–8 TTM rows is a weak detector.
- **PEAD — the strongest documented small-cap edge in the file set.** The academic literature (Bernard & Thomas 1989 onward) finds drift concentrated in small, low-analyst-coverage, low-institutional-ownership, illiquid names, and largely arbitraged away in large caps. The 8-K-first sourcing, 45-day retrospective filter, and 4-day freshness window are sensible event hygiene. Missing for small-cap deployment: surprise-magnitude scaling (fixed ±1), no liquidity/short-borrow reality check (shorting a $80M name after a miss is often untradeable), and BEAT/MISS quality depends on the upstream extractor precisely where consensus estimates are sparsest.
- **Portfolio note:** `fundamental-ls` market-neutral shorting and `earnings-drift` shorts are the two places small-cap frictions (borrow, spread, impact) would bite hardest; nothing in the specs models them — `gross_target` scaling assumes frictionless weights.

## 7. Contrast with invest-ai (for the parent's purposes)

ai-hedge-fund trusts the LLM with the *judgement* (thresholds live in prompts; determinism only in PEAD, PIT plumbing, caching, and the abstain/fail-loud contract), whereas invest-ai's constitution (CLAUDE.md invariants 2, 5, 8, 12) keeps every decision rule mechanical and uses the agent only for research/prose behind a `record`-validated seam. The transferable pieces are the mechanical ones: PEAD's event hygiene (source priority, retrospective filter, freshness window), the snapshot content-hash cache discipline, and the abstain-vs-propagate failure contract; the persona prompts are the part invest-ai's design explicitly forbids as decision-makers.
