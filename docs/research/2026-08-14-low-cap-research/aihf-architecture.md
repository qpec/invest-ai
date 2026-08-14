# ai-hedge-fund (virattt/ai-hedge-fund) — architecture analysis

Analyzed from local clone at `/tmp/claude-0/-home-user-invest-ai/0e1d606b-c18b-5de9-bee2-f1d3534d6ef8/scratchpad/ai-hedge-fund`. Date of analysis: 2026-08-14. The repo is mid-rebuild ("v2") into a persistent fund engine; all findings below refer to the `hedge_fund/` v2 package. Educational-only per README/VISION disclaimers; README states "the system does not actually make any trades" (SimBroker only today; paper/live brokers are roadmap ⬜).

## 1. Conceptual model: fund / strategy / signal / sleeve, and how a philosophy is expressed

The org-chart metaphor (VISION.md) is load-bearing and mirrored 1:1 in code (`hedge_fund/fund/spec.py` docstring):

```
FUND      = capital slices over STRATEGIES  (master risk on the netted book)
STRATEGY  = a blend policy over MODELS      (a "pod")
MODEL     = an alpha model -> Signal
```

- **Signal** (`hedge_fund/models.py`): the atomic unit. Pydantic model with `model_name`, `ticker`, `date` (as-of, YYYY-MM-DD), `value: float` — conviction in [-1.0 bearish, +1.0 bullish], `reasoning: str | None` (the written thesis — "central for LLM agents"), `components: dict[str,float]` (quant decomposition), `metadata: dict`. Both quant models and LLM agents emit this identical shape.
- **AlphaModel** (`hedge_fund/signals/base.py`): ABC with `name` property and `predict(ticker, date, data_client) -> Signal`. Contract in the docstring: MUST be point-in-time (only data with date ≤ as-of), 0.0 = abstain/no view. Two subclass flavors: `QuantModel` (pure math; shared helpers `_safe_float`, `_percentile_rank`, `_sigmoid` = tanh(x·5), `_compute_rsi`) and `LLMAgent`. Explicit doctrine: "The alpha model only forms a *view*. It does NOT decide position mechanics (timing, sizing, holding period)".
- **Strategy / pod** (`StrategySpec` in `fund/spec.py`): `name`, optional `display_name`, `weight` (the fund's capital slice relative to siblings, normalized at netting time), `models: list[ModelSpec]` (min 1), `blend: BlendPolicy`. `ModelSpec` = `{name (key into ALPHA_MODEL_REGISTRY), weight (blend weight, default 1.0, gt=0), params (constructor kwargs)}`. `BlendPolicy` = `{method: Literal["conviction_weighted"], gross_target (default 1.0), market_neutral (bool, default False)}`.
- **Sleeve**: the per-strategy target-weight vector produced by blending that strategy's signals; all sleeves are netted by capital slice into one fund book in `run_cycle`.
- **Fund** (`FundSpec`): `name`, `strategies` (unique names enforced by validator), `risk: RiskLimits` (MASTER risk on the netted book), `capital` (default 100,000), `rebalance: Literal["daily","weekly","monthly"]` (default weekly — a mandate choice the backtester/daemon obeys; `run_cycle` itself never sees it), `benchmark` (default "SPY"; also the source of the backtest's trading-day grid). `extra="forbid"` on every spec model: "YAML typos fail loud at load time, not silently at trade time."
- **`Fund` class** (plain Python, not pydantic): spec + models instantiated once per fund, never per cycle, because models are stateful (LLM prompt caches, PEAD earnings caches).

**How a philosophy is expressed** — two mechanisms:

1. **A persona is ONLY a system prompt.** `hedge_fund/signals/buffett.py`: `BuffettAgent(LLMAgent)` defines just `name` → `"buffett"` and `get_system_prompt()` → a Buffett checklist prompt (circle of competence, moat via durable ROE / margins, management via BVPS compounding, financial strength, valuation, the 10-year test) plus signal rules (bullish/bearish/neutral definitions), a 0–100 confidence scale, hard rules ("Reason ONLY from the data provided… treat the most recent filing date shown as the present"), and a strict JSON output schema `{"signal","confidence","reasoning"}`. Munger/Graham/Lynch/Druckenmiller are the same pattern. All machinery lives in the `LLMAgent` base class.
2. **A strategy is data.** Shipped library `hedge_fund/strategies/*.yaml` composes personas/quant models with blend weights. Comments in each YAML name the *claimed edge* — e.g. deep-value: "Edge claimed: mispriced quality with a margin of safety." The strategy's discretionary-vs-systematic character is *derived from its staff, never declared* (spec.py docstring). `hedge_fund/fund/test_strategy_library.py` pins that every shipped YAML loads and every referenced model exists in `ALPHA_MODEL_REGISTRY` (currently: `pead`, `buffett`, `munger`, `graham`, `lynch`, `druckenmiller` — `signals/__init__.py`).

Specs are declared authorship-neutral: "The wizard, a chat LLM, and the strategy generator all emit this same format — nothing downstream ever needs to know who authored a fund."

## 2. Signal production, scoring, weighting, combination — exact mechanisms

### What the LLM does vs what Python does

**Python (deterministic) computes:** all arithmetic. `hedge_fund/features/snapshot.py` builds a `FundamentalsSnapshot` — up to 20 TTM periods of filed metrics (market_cap, P/E, ROE, gross/operating/net margins, D/E, current ratio, revenue growth, EPS, BVPS, FCF/share), filtered on **filing_date, not report_period** (PIT), min 4 periods or raise `InsufficientData`. Derived aggregates are computed in Python "so the LLM reasons over facts instead of re-deriving arithmetic": `roe_avg`, `net_margin_avg`, `gross_margin_trend` (latest−oldest), `bvps_cagr` (quarter-spaced annualization), `debt_to_equity_latest`, `market_cap_latest`. Market cap deliberately comes from the most recent FILED metrics row, not `get_company_facts` (that is latest-only → lookahead in a backtest). `render()` emits a compact date-free text table — deliberately no `as_of` in either the hash or the prompt so identical data on two dates is a cache hit and the LLM cannot anchor on a calendar date and smuggle in post-date world knowledge.

**The LLM does exactly one thing** (`hedge_fund/signals/llm_agent.py`): given system prompt (persona) + rendered snapshot, return JSON `{"signal": bullish|neutral|bearish, "confidence": 0-100, "reasoning": "2-4 sentences"}`. Python then converts: `value = sign(signal) × confidence / 100` where sign ∈ {+1, 0, −1} (`_SIGNAL_TO_SIGN`). Validation in `_parse`: invalid signal word or confidence outside [0,100] → parse failure.

**Failure contract (locked decisions, llm_agent.py docstring):**
- Data-layer errors PROPAGATE (fail loud — "a broken snapshot must never silently become a neutral view").
- `InsufficientData` → abstain: `Signal(value=0.0, metadata.abstained=True, abstain_reason=…)`.
- LLM call failure or unparseable response → abstain (raw response still persisted as a debug trail).
- Every LLM decision persists exact prompt + response via `PromptCache`, keyed by `prompt_key(name, model, system, user)`; an unchanged snapshot never pays for a second LLM call. `run_cycle`'s determinism claim rests on this: replays are byte-identical once the cache is warm.

**Quant example — PEAD** (`signals/pead.py`): ±1.0 fixed conviction if a qualifying earnings surprise (BEAT/MISS) was *filed* within `signal_window_days` (default 4) of as-of, else 0.0 — but that 0.0 is a *real neutral vote*, not an abstain. 8-K prioritized over 10-Q/10-K/20-F as earliest announcement; filings dropped if stale >45 days vs report period; per-ticker earnings cache.

### Blending (`hedge_fund/portfolio/construction.py`, pure function)

Per ticker, conviction is a **weighted mean over voting models**:

```
conviction_t = Σ(w_m · value_mt) / Σ(w_m)      # w_m from ModelSpec.weight
```

Critical distinction: an **abstained** signal (`metadata.abstained is True`) is excluded from numerator AND denominator — "'no opinion' must not masquerade as 'opinion: neutral'" — while a non-abstained 0.0 (PEAD outside its window) dilutes as a genuine neutral vote.

If `market_neutral`: convictions are demeaned cross-sectionally (long the best-liked *relative to the rest*, short the least-liked; sleeve nets to zero dollars). Then weights = `conviction_t / Σ|convictions| × gross_target`; gross below 1e-9 → all-flat book (guards against demeaning residue ~1e-16 being normalized into a full book). Documented accepted wart: normalization ignores *absolute* conviction — a lone weak view would get the full gross target; risk clamps it ("conviction requests, risk disposes").

### Netting and the full cycle (`hedge_fund/pipeline/run_cycle.py`)

`run_cycle(fund, as_of, broker, data_client, universe)` — the only impure stage; every delegate is pure. Sequence:

1. `_mark_prices`: last close on/before as-of within a 7-day lookback (`_MARK_LOOKBACK_DAYS`). Universe ticker with no price and no position → `TickerSkip`, analysts never called. A HELD ticker with no price → raise ("a fund that cannot price its own book has an infrastructure problem, and its NAV would be a lie"). Non-positive equity → raise.
2. Each strategy runs its own staff over the tradeable universe (every model, every ticker) and blends its own sleeve.
3. Netting: `netted[ticker] += (strategy.weight / total_slice) × sleeve_weight` — capital slices normalized across strategies (2/2 ≡ 1/1).
4. `apply_limits(netted, spec.risk)` — master risk on the netted book.
5. `build_orders` (`pipeline/execution.py`): diff target book vs broker book. `target_shares = int(weight × equity / mark)` — floor toward zero, never overshoot; sub-share dust stays in cash. Orders <1 share not emitted. Deterministic ordering: all sells first, then buys, alphabetical within each group (sells free cash that buys consume in the same cycle).
6. Broker fills; `CycleRecord` persists everything: spec, universe, marks, skips, per-strategy signals/convictions/weights, netted targets, every `ClampEvent`, final weights, orders, fills, positions, cash, NAV. Targets are the *complete* statement of the desired book — all-abstain → all-zero targets → the fund closes to flat (an outer daemon can choose to skip a tick instead; that guard belongs outside the pipeline).

Same pipeline, three modes (VISION): backtest = run_cycle looped over history with SimBroker; paper/live = same loop, different clock/broker. "The backtest is the live system."

## 3. Universe selection

**There are no market-cap ranges or liquidity filters anywhere in this codebase.** This is a deliberate, documented design decision, the opposite of what one might assume:

- `FundSpec` is "**Deliberately ticker-free**: a mandate is the DESK — its strategies, staff, risk limits, capital, and cadence — not a watchlist. Which names to trade is a run-time input" (`fund/spec.py`).
- The universe arrives as `--tickers AAPL,MSFT` on the CLI (README) or TUI input, passed as `universe: list[str]` to `run_cycle`. `normalize_universe` is the single normalizer: upper-cased, de-duped, order preserved, empty raises ("a cycle with nothing to trade is a caller mistake").
- Legacy compatibility: `load_spec` does `data.pop("universe", None)` — mandates *used to* carry a `universe` key; it is now silently dropped rather than failing `extra="forbid"`.
- The only universe-shaping YAML fields that exist are risk fields, not screens. From `fund/example.yaml`:

```yaml
risk:
  max_position_pct: 0.25      # master risk: no single name above 25% of equity
  max_gross_exposure: 1.0     # unlevered, across the netted book
capital: 100000
rebalance: weekly             # daily | weekly | monthly
benchmark: SPY
```

- De-facto screens emerge from mechanics, not config: <4 filed TTM periods → LLM agents abstain (`MIN_PERIODS = 4`, snapshot.py); no close within 7 days → ticker skipped. That is the entire "liquidity filter."

Strategy YAMLs (`hedge_fund/strategies/`) contain only `name`, `display_name`, `models` (+ per-model `weight`), and `blend` (`method: conviction_weighted`, `gross_target: 1.0`, `market_neutral: true` in fundamental-ls only). Their investment character lives in comments: deep-value = "discretionary, long-biased, quarterly horizon. Graham leads (double blend weight: `weight: 2.0`)"; earnings-drift = "systematic, event-time. The model is the strategy; no one is pretending it has opinions"; fundamental-ls = flagship market-neutral 5-agent pod; inflections = Druckenmiller + Lynch on "fundamentals rate-of-change."

## 4. Risk limits and validation

**Risk (`hedge_fund/risk/limits.py`)** — "hard caps the analysts cannot override… the LLM's influence over the book ends at the Signal, and no clamp is ever negotiable." Exactly two limits today:

- `max_position_pct` (gt 0, ≤1.0): max |weight| per ticker as fraction of equity. Clamped preserving sign, one `ClampEvent` per clamped ticker.
- `max_gross_exposure` (gt 0): max Σ|weights|. Applied *after* per-ticker caps by proportional scale-down; "scaling only shrinks, so it can never re-violate the per-ticker cap" — the ordering makes the pair idempotent.
- Exposure removed by a clamp is NOT redistributed — it stays in cash: "redistributing would let the risk stage *increase* positions, which inverts its job."
- Every firing is a recorded `ClampEvent{limit, ticker, before, after}` — "recorded so every clamp is explainable" — persisted on the `CycleRecord`.
- Roadmap: pod-level risk budgets 🚧 ("pod budgets with pods").

**Validation (`hedge_fund/validation/__init__.py`)** — a 5-line docstring stub: Combinatorial Purged Cross-Validation (CPCV) and Probability of Backtest Overfitting (PBO) are *planned* (Roadmap ⬜). VISION commits to "Self-improvement is gated… nothing it invents gets capital without passing the validation gate — and promotion into a live book stays human-approved by default." No code exists yet.

**Other guardrails scattered through the pipeline:**
- PIT honesty: filing-date filtering; snapshot market cap from filed rows only; PEAD keys on filing_date; render() is date-free.
- Fail-loud asymmetry: infrastructure/data failures raise; model-level failures abstain — degradation is per-analyst, never silent at the book level.
- Fail-loud config: `extra="forbid"` on every spec; unknown model name at `Fund` construction raises with the available registry listed; duplicate strategy names rejected.
- `test_strategy_library.py`: shipped YAML must always load against the registry (a CI tripwire for spec/registry drift).
- Complete auditability: `CycleRecord` keeps every signal (with reasoning + prompt_key + snapshot_hash), every clamp, every skip, every fill — VISION: "the fund explains itself."

## 5. What transfers to an advisory-only small-cap analysis lane (never executes)

Context: the receiving system (stock-agentcy) already has stronger invariants in some areas (refuse-never-guess, two unmerged judgements, no price triggers, pure decision layer). The transferable ideas are the ones orthogonal to those:

**Transfers well:**

1. **Philosophy-as-data (StrategySpec YAML).** An analysis "lens" = a named YAML bundling perspectives + weights + a one-line claimed edge, `extra="forbid"`, with a library test pinning every shipped spec against the registry. For an advisory lane: a "small-cap quality" lens vs a "deep-value" lens over the same universe, each a reviewable, diffable file — and authorship-neutral, so a human, a wizard, or an agent can emit the same format.
2. **Persona = system prompt only; machinery in one base class.** Adding an analytical perspective (skeptic, forensic accountant, industry specialist) costs ~40 lines: a name and a prompt. Caching, parsing, abstention, and audit are inherited. This is a very cheap way to get structured multi-perspective analysis without N bespoke agent harnesses.
3. **The abstain/neutral distinction.** "No opinion must not masquerade as opinion: neutral" — excluded from numerator AND denominator — is exactly the agentcy "refuse, never guess" invariant applied to *opinion aggregation*. Any multi-analyst advisory summary should carry it: "3 of 5 perspectives voted; 2 abstained (insufficient data)" mirrors "48 of 67 measurable."
4. **Snapshot hash → LLM cache → reproducible analysis.** Hash the point-in-time input bundle (excluding as-of), key every LLM call on `(agent, model, system, user)`, persist prompt + raw response even on parse failure. Gives: (a) zero re-spend between filings, (b) byte-identical replays, (c) a complete forensic trail per verdict. Directly applicable to the thesis-desk brief→agent→record loop and the weekly monitor (a monitored name whose inputs haven't changed needs no fresh agent verdict).
5. **Date-free prompt rendering.** Excluding the calendar date from the prompt both stabilizes the cache and stops the LLM anchoring on post-date world knowledge — a cheap, clever PIT hygiene trick for any backtestable or replayable agent analysis.
6. **Compute in Python, reason in prose.** The snapshot pre-computes trends/CAGRs/averages so "the LLM reasons over facts instead of re-deriving arithmetic." Same seam as agentcy's brief packet; the transferable refinement is the *derived aggregates* block — hand the agent the deltas and trends, not just the raw rows.
7. **The asymmetric failure contract.** Infrastructure errors raise; per-model errors abstain loudly with a reason in metadata. For advisory: a data-layer break should kill the run, one analyst failing should shrink the panel and be reported ("UNCHECKED, reported loudly" is the same idea).
8. **Structured LLM output → deterministic mapping.** `{signal, confidence, reasoning}` validated with hard rejection (invalid word, confidence out of range → abstain, not fudge) then mapped by pure code. The categorical-signal × bounded-confidence shape is more robust than asking for a free-form score.
9. **ClampEvent-style audit records.** Every mechanical override recorded as `{rule, target, before, after}`. For an advisory lane: every filter/veto/floor that removed a name from a report should leave the same kind of typed receipt.
10. **"One code path" doctrine.** What you backtest is what runs. For an analysis lane: the historical-replay evaluation of a lens should be the same code as today's report, only the clock differing.

**Transfers with caution / does not transfer:**

- **Conviction-weighted blending into portfolio weights** is precisely the forbidden merge for agentcy (invariant 2: judgements are never averaged; inversion severities are counted, never averaged — an average lets a good probe cancel a fatal one). Import the *panel* (N independent signed views with reasoning, shown unmerged), not the *mean*. If aggregation is ever wanted, count votes/vetoes, don't average convictions.
- **The whole weights→orders→broker tail** (`construction`, `execution`, `limits` as position caps, brokers) is out of scope by FR11. The only piece worth keeping is its *shape*: pure functions with typed audit output.
- **LLM personas as the primary judgement** conflicts with agentcy's "agent trusted for research and prose, never for the contract." In agentcy the deterministic layer scores and the agent narrates; in aihf the LLM's confidence *is* the score. For an advisory lane the aihf pattern fits best as a supplementary panel (multiple named perspectives attached to a dossier), never as an input to scorecard/inversion numbers.
- **Runtime-tickers universe** is the wrong fit for a screening system that owns a 7,000-name universe; aihf simply has no universe-selection machinery to borrow (no cap ranges, no liquidity screens — see §3). Small-cap eligibility must remain the receiving system's own floor logic (cf. `DESK_MIN_MARKET_CAP`/`DESK_MIN_PRICE`).
- **Validation gate (CPCV/PBO)** is vaporware here — a good idea to note, nothing to port.

## Key file index

- `/…/ai-hedge-fund/hedge_fund/models.py` — Signal, QuantSignals
- `/…/ai-hedge-fund/hedge_fund/fund/spec.py` — ModelSpec, BlendPolicy, StrategySpec, FundSpec, normalize_universe, Fund
- `/…/ai-hedge-fund/hedge_fund/fund/example.yaml` — full mandate example
- `/…/ai-hedge-fund/hedge_fund/strategies/{deep-value,earnings-drift,fundamental-ls,inflections}.yaml` — strategy library
- `/…/ai-hedge-fund/hedge_fund/signals/{base,llm_agent,buffett,pead}.py` — AlphaModel/QuantModel/LLMAgent + examples
- `/…/ai-hedge-fund/hedge_fund/features/snapshot.py` — PIT FundamentalsSnapshot, content_hash, render
- `/…/ai-hedge-fund/hedge_fund/portfolio/construction.py` — blend_signals
- `/…/ai-hedge-fund/hedge_fund/risk/limits.py` — RiskLimits, apply_limits, ClampEvent
- `/…/ai-hedge-fund/hedge_fund/pipeline/{run_cycle,execution}.py` — the one pipeline
- `/…/ai-hedge-fund/hedge_fund/validation/__init__.py` — CPCV/PBO stub (docstring only)
- `/…/ai-hedge-fund/{README,VISION,ROADMAP}.md` — doctrine and status
