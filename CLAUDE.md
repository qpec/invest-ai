# stock-agentcy

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

**Technology/runtime decided 2026-07-08, owner-ratified 2026-07-09: `docs/plans/2026-07-08-technology-architecture.md`** (+ companion `2026-07-08-telegram-interaction-spec.md`) — always-on Ubuntu box, systemd timers + oneshot jobs + one small synchronous daemon; stdlib spine (hand-rolled 8-method Telegram client, HTML mode; GPL-family incl. LGPL banned per NFR7, certifi/MPL-2.0 the one journaled exception); two SQLite files (benchmark physically quarantined) + rendered-markdown archive in its own git repo under `/var/lib/stock-agentcy`; four runtime pip packages only (yfinance, pandas, scipy, quantstats); no LLM in the scheduled runtime (Gate/Study are desk sessions via the `agentcy` CLI); uv-pinned CPython + wheelhouse, quarterly upgrade ritual with a yfinance emergency lane; 7-day letter cadence + owner-elected external dead-man ping. Next step: implementation plan.
