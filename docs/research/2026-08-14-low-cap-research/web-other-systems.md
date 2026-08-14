# Survey: How Other AI-Driven Investing Systems Structure Multi-Philosophy Stock Analysis

Research date: 2026-08-14. Focus: multi-agent / multi-philosophy architectures, small-cap-specific practice, and design lessons transferable to stock-agentcy (thesis-driven, two-judgement, refuse-never-guess).

---

## 1. TradingAgents (Tauric Research) — adversarial debate as an architecture

- Paper: arXiv:2412.20138, "TradingAgents: Multi-Agents LLM Financial Trading Framework" (https://arxiv.org/abs/2412.20138); code: https://github.com/TauricResearch/TradingAgents; site: https://tradingagents-ai.github.io/
- **Role structure mirrors a trading firm**, four tiers:
  1. **Analyst team** (run concurrently): Fundamentals Analyst (financial metrics/intrinsic value), Sentiment Analyst (news + StockTwits + Reddit mood), News Analyst (macro indicators, global events), Technical Analyst (MACD, RSI etc.).
  2. **Researcher team**: dedicated **Bull** and **Bear** researcher agents run **structured debate rounds** over the analysts' reports; round count is a config knob (`max_debate_rounds`).
  3. **Trader agent** synthesizes the debate into a concrete trade decision (direction, timing, magnitude).
  4. **Risk management team + Portfolio Manager**: risk debators assess the proposal; the PM approves/rejects before the (simulated) exchange.
- Config: separate `deep_think_llm` (slow reasoning: debates, final decisions) vs `quick_think_llm` (data summarization) — a cost/latency split worth copying; multi-provider (OpenAI/Anthropic/Google/DeepSeek/Qwen); temperature and checkpointing exposed.
- Reported results: improvements over baselines in cumulative return, Sharpe, max drawdown — but the backtest window overlaps LLM training data, so results are contaminated by look-ahead/memorization (see §6).
- **What transfers to stock-agentcy:** (a) the *institutionalized bear* — a standing adversarial role rather than hoping the drafting agent self-criticizes. stock-agentcy's inversion layer is the deterministic version; a "bear researcher" beat inside the thesis-desk brief (agent must write the strongest case *against* before the thesis) would be the LLM version, and it stays on the safe side of the no-merge invariant because it produces prose, not scores. (b) Separation of information-gathering agents from decision agents. (c) Config-bounded debate rounds instead of open-ended discussion.
- **What does not transfer:** the trader/execution tier (FR11: never executes), sentiment/technical analysts (no price triggers, no open-ended news scanning), and the implicit merging of all views into one buy/sell number — the exact merge stock-agentcy forbids.

## 2. FinRobot / FinGPT (AI4Finance Foundation)

- FinRobot: arXiv:2405.14767 (https://arxiv.org/abs/2405.14767), code https://github.com/AI4Finance-Foundation/FinRobot
- **Four-layer architecture:** (1) Financial AI Agents layer — "Financial Chain-of-Thought" that decomposes an analysis into a logical sequence of sub-problems; (2) Financial LLM Algorithms layer — picks model strategy per task; (3) LLMOps/DataOps layer — fine-tuning + task-relevant data; (4) Multi-source LLM Foundation layer — pluggable models ("Smart Scheduler" routes tasks to the best model).
- Newer FinRobot Desktop: a **Lead Agent orchestrates specialized research agents** through a pipeline — data → filings → valuation → *debate* → synthesis → **investment-committee-style report**, with the workflow "traceable" end-to-end. The equity-research use case produces sell-side-style reports from filings + market data.
- FinGPT (https://github.com/AI4Finance-Foundation/FinGPT): open-source financial LLM ecosystem — LoRA/QLoRA fine-tuned sentiment models (Llama-2 base), FinGPT-Forecaster (predicts next-week price movement from news + history), FinGPT-RAG for sentiment, FinGPT-Benchmark. An independent assessment (arXiv:2507.08015) finds it strong at sentiment/classification (F1 rivaling GPT-4) but that is NLP task quality, not stock-picking quality.
- **What transfers:** the decomposition idea — a fixed, named chain of analysis stages rather than one mega-prompt — is exactly stock-agentcy's brief→artifacts→record seam. The "traceable workflow" and committee-report framing validate the work-order/dossier design. FinGPT's lesson is mostly negative for this repo: fine-tuned transports and forecasting price movement are both out of scope (no LLM API client; no price triggers).

## 3. virattt/ai-hedge-fund — the persona-ensemble pattern (closest published cousin)

- https://github.com/virattt/ai-hedge-fund (~43–52k stars). **18 agents: 12 investor personas** (Warren Buffett — moats/consistent earnings/management; Charlie Munger — multidisciplinary quality-at-fair-price; plus Graham, Ackman, Burry, Cathie Wood, Fisher, Damodaran, etc.) **+ 6 analyst agents** (valuation, fundamentals, technicals, sentiment, risk manager, portfolio manager).
- Each persona emits a signal (bullish/bearish/neutral + confidence + reasoning); a **Portfolio Manager agent aggregates** signals into a final simulated decision. Recent refactor recasts personas as "pluggable, backtestable alpha models" driven by YAML *mandates* with a rebalance cadence and CLI backtests (`aihf mandate.yaml --tickers ... --backtest`).
- Data via a paid Financial Datasets API; multi-provider LLM; explicitly "educational purposes only... does not actually make any trades."
- **Lesson:** the persona ensemble is popular but epistemically weak — averaging Buffett-bullish against Burry-bearish into one score is precisely the forbidden merge; confidence numbers are LLM-invented, not calibrated. stock-agentcy's alternative (personas as *pillars with different jobs* — Buffett = what to buy, Munger = veto layer, never reconciled) is the sturdier reading of the same inspiration. The one mechanism worth borrowing: making each philosophy's verdict a separately displayed, separately reasoned artifact.

## 4. OpenBB — small-cap screening workflows

- OpenBB Platform screener (https://docs.openbb.co/odp/python/reference/equity/screener) wraps provider screeners (Finviz under the hood for the classic workflow); Python-first: filter by `mktcap_min`/`mktcap_max` (small cap conventionally 300M–2B), price, volume, beta, analyst ratings, then pull fundamentals per survivor.
- Typical community workflow: coarse screener pass (cap/liquidity/valuation) → pull standardized fundamentals into pandas → custom ranking → manual research. Example community builds: relative-strength screener dashboards (https://github.com/PrymeTyme/OpenBBDashboard).
- OpenBB has blogged about **AI-driven screening on unstructured data** (LLM-interpreted filings/news as screen inputs) — experimental, not a shipped methodology (https://openbb.co/blog/openbb-is-experimenting-with-ai-driven-stock-screening-based-on-unstructured-data; page now 404s).
- **Lesson:** OpenBB is a data/plumbing layer, not a judgment layer — everyone builds the funnel shape stock-agentcy already has (universe → mechanical screen → human/agent research on survivors). Its `DESK_MIN_MARKET_CAP` $300M floor sits exactly at the conventional microcap/small-cap boundary; OpenBB users routinely screen below it, which stock-agentcy deliberately does not.

## 5. Published LLM-persona / LLM stock-picking evaluations

- **GuruAgents** (arXiv:2510.01664, https://arxiv.org/abs/2510.01664) — the most direct "LLM as Buffett/Graham" evaluation. Five personas: Graham (margin of safety), Buffett (quality at fair price), Greenblatt (Magic Formula), Piotroski (F-Score), Altman (Z-Score zones). Key design: a **deterministic three-stage pipeline** — (1) metrics computed by predefined code functions, (2) algorithmic scoring with investor-specific weights, (3) portfolio construction with fixed tie-breaking rules (liquidity, debt, margin). The LLM encodes the philosophy; the numbers are computed in code. Backtest: NASDAQ-100, Q4-2023→Q2-2025 (post-knowledge-cutoff, so memorization-safe), quarterly rebalance, 1bp costs. Results: Buffett agent 42.2% CAGR (best), Piotroski 30.9%, Graham ≈ index, Greenblatt and Altman underperformed. Limitations they admit: prompt-fidelity to the real investor is unvalidated; single bull-market regime.
- **Financial Statement Analysis with LLMs** (Kim, Muhn, Nikolaev, Chicago Booth; arXiv:2407.17866) — GPT-4 given **standardized, anonymized** financial statements + analyst-style CoT predicts earnings direction at 60.35% accuracy, beating median human analysts (~53–57%) and matching specialized ML. Crucially, anonymization + no narrative = the gain is from ratio reasoning, not memory.
- **FinanceBench** (Patronus AI, arXiv:2311.11944) — 10,231 open-book financial QA pairs over public-company filings. GPT-4-Turbo **with retrieval failed or refused 81%** of questions; best config (oracle context) only 85% correct; models produced *precise but wrong* numbers. Verdict: LLMs are not reliable for unsupervised extraction of financial figures — the empirical basis for "refuse, never guess."
- **InvestorBench** (arXiv:2412.18174, ACL 2025) — standardized environment benchmark for LLM trading agents (stocks/crypto/ETF), built on FinMem's layered-memory architecture; 13 backbone LLMs compared. Establishes that agent scaffolding (memory, reflection) matters as much as the base model.
- **AFIB / SuperInvesting benchmark** (arXiv:2603.08704) — evaluates finance AI systems on five axes: factual accuracy/hallucination resistance, analytical depth, completeness, data recency, consistency across repeated queries. Finding: retrieval-grounded systems get recency right, pure-reasoning models hallucinate; **hybrids win**.

## 6. What goes wrong with LLM stock pickers, and the guardrails published systems use

**Failure modes (documented):**
- **Look-ahead bias / memorization.** GPT-4o recalls exact S&P 500 closes with <1% error inside its training window — "prediction" in-sample is recall (https://hedgefundalpha.com/education/your-llms-alpha-might-be-mere-memorization/). arXiv:2309.17322 shows both look-ahead bias and a "distraction effect" (entity knowledge polluting sentiment); anonymized headlines actually performed *better* in-sample. **Look-Ahead-Bench** (arXiv:2601.13770) formalizes the test: matched in-sample vs post-cutoff six-month periods with ~equal buy-and-hold returns; performance gaps = bias. ScienceDirect (S0165176525004392): bias is worst for low-frequency, index-level data; weakest for high-frequency single-stock data.
- **Hallucinated figures.** FinanceBench: models emit precise wrong numbers rather than abstaining; retrieval reduces but does not eliminate it.
- **Uncalibrated confidence.** Persona ensembles (ai-hedge-fund) attach confidence percentages with no calibration basis; TradingAgents' debate can converge on a confidently wrong consensus.
- **Backtest contamination.** TradingAgents-style results over pre-cutoff windows are unfalsifiable; GuruAgents' post-cutoff window is the honest design.

**Guardrails converged on by the better systems:**
1. **Compute all numbers in code; LLM only reasons over supplied, verified values** (GuruAgents' deterministic pipeline; Chicago Booth feeding standardized statements). = stock-agentcy's pure decision layer + registry-as-vocabulary.
2. **Anonymize/standardize inputs** to break memorization and distraction (Booth, arXiv:2309.17322).
3. **Backtest only post-knowledge-cutoff** (GuruAgents; Look-Ahead-Bench as the audit).
4. **Retrieval grounding + explicit abstention** for factual claims (AFIB finding; FinanceBench's refusal-rate metric treats *wrong* as worse than *refused*). = "refuse, never guess," `Unknown` verdicts.
5. **Structural adversarialism** — a standing bear/risk role, not optional self-critique (TradingAgents).
6. **Mechanical validation gate on agent output** — nobody else has stock-agentcy's `record` seam explicitly, but GuruAgents' fixed scoring stage and FinRobot's traceable pipeline are partial equivalents.
7. **Simulation-only + loud disclaimers** (ai-hedge-fund "does not actually make any trades") = FR11.

## 7. Small-cap / microcap community screening practice

- **MicroCapClub** (https://microcapclub.com/) — the serious-community benchmark. Gatekeeping IS the methodology: membership requires an original 2–3 page long-only investment thesis on a microcap (<$500M in current practice; historically <$300M), voted on by members; ~17% acceptance (https://community.microcapclub.com/forums/forum/2-apply-for-membership/, https://traderhq.com/microcapclub-review-platform-for-microcap-investors/). Focus: **profitable** microcaps with real operating businesses — they note ~82% of the microcap universe is speculative/pre-revenue and exclude it wholesale. Ian Cassel's screen shape: profitability first, then per-share value creation, owner-operators with skin in the game, expecting 100%+ appreciation over 12–24 months on a buy-and-hold basis. The thesis-per-position, community-vetted structure is the human analogue of stock-agentcy's brief→record→ratify.
- **stockanalysis.com** (https://stockanalysis.com/stocks/screener/, https://stockanalysis.com/data-sources/) — free screener, ~300+ metrics over 130k+ securities; transparency is the differentiator: S&P Global as primary source, a **data-source selector** with a documented multi-provider chain (up to 40+ years history), updated per-minute. Lesson: publishing your data provenance is itself a credibility feature — matches stock-agentcy's enrich provenance ledger.
- Serious microcap screens generally share: profitability floor (positive owner earnings, not just EPS), liquidity/share-count sanity checks, insider ownership, and *explicit exclusion* of the promotional tier — i.e., a Hell-No filter before any upside analysis. Reddit-tier "penny stock" screens invert this (volume/momentum first) and are the anti-pattern.

## 8. Synthesis — positioning stock-agentcy against the field

| Design axis | Field norm | stock-agentcy |
|---|---|---|
| Philosophy combination | Ensemble → merged score (ai-hedge-fund, TradingAgents) | Pillars with distinct jobs, never merged (invariant 2) |
| Numbers | Increasingly code-computed (GuruAgents, Booth) | Pure decision layer, registry vocabulary |
| Adversarial view | LLM bear/risk agents in debate | Deterministic inversion probes + Munger veto pre-filter |
| Missing data | Mostly silent defaults | Refuse-never-guess, shrinking denominators — rare in the field, validated by FinanceBench |
| Agent output control | Prompt discipline | Mechanical `record` gate — essentially unique |
| Human in loop | Optional/none | CLI-only ratification Gate |
| Backtest hygiene | Often contaminated | N/A (advisory, forward-only monitoring) — but any future eval should follow Look-Ahead-Bench: post-cutoff windows only |

Concrete ideas worth stealing: (1) a mandatory bear-case section in the thesis brief (TradingAgents' bull/bear debate, kept as prose); (2) deep-think vs quick-think model split for cost; (3) GuruAgents-style post-cutoff evaluation if desk performance is ever measured; (4) MicroCapClub's "profitable operating business only" framing as validation of the eligibility floor + Munger gate ordering.

## Sources

- https://arxiv.org/abs/2412.20138 · https://github.com/TauricResearch/TradingAgents · https://tradingagents-ai.github.io/
- https://arxiv.org/abs/2405.14767 · https://github.com/AI4Finance-Foundation/FinRobot · https://github.com/AI4Finance-Foundation/FinGPT · https://arxiv.org/pdf/2507.08015
- https://github.com/virattt/ai-hedge-fund
- https://docs.openbb.co/odp/python/reference/equity/screener · https://github.com/PrymeTyme/OpenBBDashboard · https://openbb.co/blog/openbb-is-experimenting-with-ai-driven-stock-screening-based-on-unstructured-data
- https://arxiv.org/abs/2510.01664 (GuruAgents) · https://arxiv.org/html/2407.17866v1 (Booth FSA) · https://arxiv.org/abs/2311.11944 (FinanceBench) · https://arxiv.org/abs/2412.18174 (InvestorBench) · https://arxiv.org/html/2603.08704v1 (AFIB)
- https://arxiv.org/abs/2309.17322 · https://arxiv.org/pdf/2601.13770 (Look-Ahead-Bench) · https://www.sciencedirect.com/science/article/pii/S0165176525004392 · https://hedgefundalpha.com/education/your-llms-alpha-might-be-mere-memorization/ · https://paperswithbacktest.com/course/look-ahead-bias-llm-trading
- https://microcapclub.com/ · https://community.microcapclub.com/forums/forum/2-apply-for-membership/ · https://traderhq.com/microcapclub-review-platform-for-microcap-investors/ · https://stockanalysis.com/stocks/screener/ · https://stockanalysis.com/data-sources/
