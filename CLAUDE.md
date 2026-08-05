# stock-agentcy

> **Public rebrand 2026-08-05 (owner-directed):** the GitHub repository is
> `qpec/invest-ai` and the repo is public; the private state archive is
> `qpec/invest-ai-state`. Internal names (`agentcy`, `stock-scout`, this file)
> deliberately keep the working name.

A daily/weekly iterating financial-analysis system for portfolio oversight. The core object is the **investment thesis**, not the stock: every position carries a written thesis with a conviction level and pre-committed invalidation triggers. The system evaluates candidate buys through the framework below, monitors holdings against their triggers, and reports on portfolio balance.

**The system advises and monitors. It never executes trades.**

---

## The Investment Framework (Constitution)

> Buffett teaches you what to buy. Munger teaches you what to avoid. Naval teaches you how to keep upgrading.

Every analysis agent MUST apply this framework. It is the rubric for every candidate evaluation, every thesis, every re-validation, and every report. When the framework and a "great opportunity" conflict, the framework wins.

### Pillar 1 — What to Buy (Buffett)

Buy wonderful businesses at fair prices, and let compounding do the heavy lifting.

- **Circle of competence.** Only businesses the owner genuinely understands: [redacted]. If the business model and its moat cannot be explained in two sentences, PASS.
- **Moat checklist.** Require at least one durable competitive advantage, with evidence:
  - Network effects (each new user makes the product more valuable)
  - Switching costs (customers locked in by data, workflows, integrations)
  - Cost advantages (structural, not temporary)
  - Brand / trust (especially powerful in healthcare and financial services)
  - Regulatory barriers (relevant in Dutch/EU markets the owner understands well)
- **Owner earnings over reported earnings.** Judge by free cash flow — how much cash the owner could pull out after maintaining competitive position — not by reported EPS.
- **The 10-year test.** Would we hold this if the market closed for a decade? If not, it is speculation, not investment.
- **Practical rules:**
  - Concentrate in 10–15 high-conviction positions; do not over-diversify
  - Reinvest dividends unless income is needed
  - Buy more when great businesses go on sale — market panics are opportunities
  - Default holding period is forever

### Pillar 2 — What to Avoid (Munger)

Inversion: instead of "how do I succeed?", ask "how would I guarantee failure?" — then don't do those things.

**The Hell-No filter** — run BEFORE any Buffett analysis. Failing even ONE test means automatic rejection, regardless of upside. You'll miss some winners; you'll also avoid catastrophic, compounding-ending losses.

- Leverage on volatile assets — never borrow to invest in equities
- Businesses we don't understand — if the thesis needs a spreadsheet with 47 assumptions, walk away
- Management we don't trust — look for owner-operators with significant skin in the game
- Fads disguised as trends — the "lollapalooza effect"; AI is a real trend, most AI-branded vehicles are fads
- High-fee structures — actively managed funds, 2-and-20, frequent trading; fees compound against you

**Psychology traps the system actively counters in its outputs:**

- **Envy** — never benchmark against someone else's 10x; comparison is the thief of compounding
- **FOMO / action bias** — doing nothing is often the highest-return decision; "no action needed" is a first-class, celebrated output
- **Sunk cost** — if the thesis is broken, sell; recommendations must ignore cost basis (the stock doesn't know what you paid)
- **Overconfidence after wins** — judge process separately from outcome (decision journal); a good outcome from a bad process eventually catches up
- **Complexity addiction** — exotic derivatives, leveraged ETFs, crypto yield farming are off-path, always

### Pillar 3 — How to Keep Upgrading (Naval)

Wealth isn't just picking stocks — it's continuously increasing the capacity to generate and allocate capital.

- **Specific knowledge.** The owner's deepest edge is the intersection of [redacted]. Weight analysis toward this edge; build income streams around knowledge that feels like play.
- **Leverage stack.** Capital (investments), labor (teams), code (this system itself — software that works while you sleep), media (writing, frameworks, reputation). Progressively shift income from labor-based to leverage-based.
- **Continuous learning compounds.** Weekly time studying businesses, annual reports, and updating mental models. The most important investment is the owner's own judgment — every year pattern recognition improves and the circle of competence expands.
- **Productize yourself.** the owner in the Netherlands with deep enterprise-AI expertise is unique positioning: consulting, content, advisory, angel investing in understood sectors.
- **Wealth vs. status.** Status games are zero-sum; wealth games are positive-sum. Don't buy the flashy stock to discuss at dinner parties — buy the boring compounder that quietly doubles every five years. The system flags status buys.

### Owner context

- [redacted] (relevant for tax treatment of funds vs. individual stocks; base currency EUR, most holdings likely USD)
- [redacted]
- Circle of competence: [redacted]

---

## Architecture

Functional baseline approved 2026-07-03 (`docs/plans/2026-07-08-functional-design-baseline.md`, FR1–FR14 / NFR1–NFR7). Detailed functional architecture approved 2026-07-08: **`docs/plans/2026-07-08-architecture-elaboration.md`** — schemas, trigger taxonomy, loop specifications, balance defaults, output formats. Seven components around the thesis lifecycle:

1. **Portfolio Mirror** — holdings, weights, balance; source-agnostic snapshots; leverage tripwire
2. **The Gate** — buy discipline: circle check → Hell-No veto → Buffett dossier → owner judgment → thesis + verdict
3. **Thesis Register** — one living document per holding; versioned; goalpost guard
4. **The Watchdog** — daily / weekly (Saturday) / event-driven / quarterly monitoring
5. **Decision Journal** — every decision + reasoning; process judged separately from outcome
6. **The Study** — learning loop (Naval): weekly digest, mental models
7. **The Scout** — idea generation (FR14): human-triggered only; pre-committed universe + quality-value screen recipes

Core principle: **the thesis drives the monitoring** — the Watchdog tests only pre-committed invalidation triggers, never open-ended news scanning.

Key locked decisions (2026-07-08): FR13 benchmark = S&P 500 TR in EUR (PFIC-aware) · balance defaults per elaboration §E.3 · ETFs outside-framework by default · daily letter carries no portfolio value.

**Technology/runtime decided 2026-07-08, owner-ratified 2026-07-09: `docs/plans/2026-07-08-technology-architecture.md`** (+ companion `2026-07-08-telegram-interaction-spec.md`) — always-on Ubuntu box, systemd timers + oneshot jobs + one small synchronous daemon; stdlib spine (hand-rolled 8-method Telegram client, HTML mode; GPL-family incl. LGPL banned per NFR7, certifi/MPL-2.0 the one journaled exception); two SQLite files (benchmark physically quarantined) + rendered-markdown archive in its own git repo under `/var/lib/stock-agentcy`; four runtime pip packages only (yfinance, pandas, scipy, quantstats); no LLM in the scheduled runtime (Gate/Study are desk sessions via the `agentcy` CLI); uv-pinned CPython + wheelhouse, quarterly upgrade ritual with a yfinance emergency lane; 7-day letter cadence + owner-elected external dead-man ping.

**Implemented 2026-07-09/10** per `docs/plans/2026-07-09-implementation-plan.md` — 148 tasks across 9 phases (P0 scaffold → P8 CLI/deploy), each via fresh implementer + spec-compliance + code-quality review; then a final whole-repo adversarial review closed 3 cross-phase seam gaps (alert-resolution dispatcher, reconciliation R-asks, crashed-run re-sweep). 714 tests pass, license gate clean, end-to-end smoke green. Runnable: `agentcy run {daily,weekly,quarterly,event}` + `agentcy bot` + the desk CLI; 12 systemd units + `install.sh` + runbook ready for the Ubuntu box. Interactive system explainer at `docs/site/index.html`. Toolchain note: this repo's suite runs on the Windows desk under `uv` (uv-managed CPython 3.13); 3 tests skip on Windows (AF_UNIX/git) and run on the Linux target.

**eToro ingestion (branch `feat/etoro-ingest`, 2026-07-10)** — automated `api_pull` ingestion via eToro's official read-only API (stdlib-only client → canonical `SnapshotIn` → the existing Portfolio Mirror pipeline unchanged; weekly-auto when both keys are set, plus on-demand `agentcy snapshot etoro`), capturing rich per-position detail (open date, cost basis, P&L, lots) in a new append-only `position_detail` table; zero new runtime dependencies.

**Architecture revision 2026-08-03 (owner-directed): the Scout is the starting engine, and the "no LLM in the scheduled runtime" lock is lifted** — journaled in `stock-scout/docs/THESIS-DESIGN.md` §1. The scout's top 1% feeds a thesis builder (`stock-scout/thesis.py`; edgartools (MIT) as desk-side filings-text grounding behind a guarded import); output is a DRAFT thesis (FR2 schema, machine-validatable triggers, no conviction fields — FR9) plus executive summary and extensive report; the owner ratifies at the Gate (`thesis.py ratify`) and only then does the weekly monitor (`stock-scout/monitor.py`) validate: metric triggers mechanically off `scoring.evaluate` with persistence streaks, event/narrative triggers from agent verdicts (narrative can only send to review; event breaks need high confidence; broken is sticky until the desk acts; a missing verdict ⇒ UNCHECKED, loudly). FR11 unchanged: never executes trades.

**The agent IS the runtime (2026-08-03, same-day follow-up: "run by claude code or openclaw. Not api").** There is no LLM API client in this repo — `llm.py` was deleted. Every agent-facing task runs in three beats: `python … brief` writes a work order (`stock-scout/deskwork.py`), the agent researches with its own tools and writes the artifacts, `python … record` re-checks every rule mechanically and **exits non-zero if it refuses the work**. The agent is trusted for research and prose, never for the contract. Agent-facing instructions live in `.claude/skills/thesis-desk/SKILL.md`. Runtime dependency budget unchanged (four packages); no API key, no network transport, no per-run cost model. **Metric hardening + desk site (2026-08-03, owner-directed).** `stock-scout/enrich.py` is the tiered fetch chain — tier 1 the bulk SEC export, tier 2 live EDGAR companyfacts per symbol (as-filed, `filed` dates intact so PIT survives, disk-cached, fill-only-missing at tag level with a provenance ledger; measured on the real universe: net_debt_to_ebitda went from 0% export coverage to filled for 50 of 76 enriched names), tier 3 yfinance as *display-only* vendor aggregates that never enter scoring. `monitor.py run --enrich-cache` uses the same cache so leverage-style triggers stay checkable weekly. `stock-scout/webapp.py` renders Scout · Thesis · Monitor as one self-contained interactive page (filters, sortable universe, per-name drill-down with provenance badges, thesis drafts in full, trigger safety margins) into `docs/` for GitHub Pages; owner-only FR9 fields are stripped at the render layer so they cannot reach a public page. **Registry v2 (2026-08-03, owner-ratified: "maintain within the philosophy, use metrics for a richer overview").** `stock-scout/registry.py` + a `supplements` stream in `pit.py` widen the trigger vocabulary to 26 metrics (`thesis.METRICS`: per-share owner-FCF, FCF conversion, operating margin + its MAD, incremental ROIC, interest coverage, capex/R&D intensity, goodwill share, tax gap, dividends/buybacks/acquisitions as % of OCF, …). The decision layer stays frozen — supplements can never enter the statement sections scoring sums (full-universe bit-identity proven, 1,904 names, 0 diffs), extras can never shadow an evaluate() key, and Piotroski F / Altman Z are display-only composites that never fire a trigger. FinanceToolkit (MIT) is the desk-side ratio canon + test oracle (`requirements-research.txt`); journal in `stock-scout/docs/REGISTRY-DESIGN.md`. **Best-available models only** (owner rule): `deskwork.APPROVED_MODELS` is enforced at `record` and re-checked at `ratify`, the model is read from the harness transcript rather than asked of the agent (a contradicting `--model` is refused), the monitor gates judgement but never arithmetic, and there is no override flag — widening the list is an owner-side code change.
