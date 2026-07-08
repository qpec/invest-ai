# stock-agentcy — Functional Design Baseline

**Status:** Requirements **FR1–FR14 / NFR1–NFR7 approved by owner on 2026-07-03** ("Vastleggen", with balance targets to be proposed in design as adjustable defaults). Functional architecture presented and directionally confirmed the same day; **detailed architecture elaboration is the next design step**. Technology/runtime choices deliberately deferred — owner steer: high-level architecture and requirements first, technology second.

**Provenance:** Reconstructed 2026-07-08 from the 2026-07-03 brainstorm session transcript (session `1c579d98`) and `docs/research/2026-07-03-repo-evaluations.md`. The original session hit its limit before this document was persisted; requirements below are translated from the Dutch originals without semantic changes.

---

## Purpose

A daily/weekly iterating financial-analysis system for portfolio oversight. The core object is the **investment thesis**, not the stock: every position carries a written thesis with a conviction level and pre-committed invalidation triggers. The system evaluates candidate buys, monitors holdings against their triggers, and reports on portfolio balance. It separates *price movement* from *thesis validity* and tells the owner when the reason they bought no longer exists — the pre-commitment structure is the Munger defense against commitment bias and thesis drift.

**The system advises and monitors. It never executes trades.**

The Buffett/Munger/Naval framework in `CLAUDE.md` is the constitution: its principles are the actual rubric applied every time a thesis is formed or re-tested, not decoration.

---

## Functional architecture

The system revolves around one core object — the **thesis** — and six functional components around the lifecycle of a position:

```
                      ┌──────────────────────────────────────────┐
  INPUTS              │               THE SYSTEM                 │        OUTPUTS
                      │                                          │
  eToro positions ───▶│  1. PORTFOLIO MIRROR                     │
  prices ────────────▶│     what do I own, weights, balance      │──▶ daily letter
  fundamentals ──────▶│                                          │    (email, short)
  filings/earnings ──▶│  2. THE GATE (buy discipline)            │
  news (filtered) ───▶│     Hell-No veto → Buffett analysis      │──▶ weekly review
                      │     → thesis + conviction + triggers     │    (email, deep)
  OWNER judgment ────▶│                                          │
  (conviction,        │  3. THESIS REGISTER                      │──▶ alerts
   trust in mgmt,     │     one living document per holding      │    (trigger-only)
   circle of comp.)   │                                          │
                      │  4. THE WATCHDOG (monitoring)            │──▶ archive
  FRAMEWORK ═════════▶│     daily / weekly / event-driven        │    (all reports,
  (CLAUDE.md, the     │                                          │     history)
   constitution that  │  5. DECISION JOURNAL                     │
   permeates every    │     every decision + reasoning; process  │
   component)         │     judged separately from outcome       │
                      │                                          │
                      │  6. THE STUDY (learning loop, Naval)     │
                      │     weekly digest, mental models         │
                      └──────────────────────────────────────────┘
```

### Components

1. **Portfolio Mirror** — what do I own, position weights, portfolio balance.
2. **The Gate** (buy discipline) — every candidate passes: Hell-No veto → Buffett analysis → thesis + conviction + invalidation triggers.
3. **Thesis Register** — one living document per holding.
4. **The Watchdog** (monitoring) — daily / weekly / event-driven checks against the register.
5. **Decision Journal** — every decision with its reasoning at that moment; process quality judged separately from outcome.
6. **The Study** (learning loop, Naval) — weekly digest, mental-model updates.

### Core data-flow principle

**The thesis drives the monitoring.** The Watchdog does not scan "all news about holding X" — it tests exclusively the pre-committed invalidation triggers from the Thesis Register. This keeps the daily loop cheap, signal-rich, and honest: the system can only raise alarms about things the owner declared material in advance.

### Pillar placement

- **Munger** sits at the front (the veto in the Gate) *and* in every output (behavioral rules).
- **Buffett** is the analysis engine in the Gate and the Watchdog.
- **Naval** is the meta-loop (Study + Decision Journal) that sharpens the owner's judgment every year.

---

## Functional requirements (approved 2026-07-03)

- **FR1 — No thesis, no buy.** Every position has a thesis before purchase; existing holdings without a thesis are flagged until they receive a backfill thesis.
- **FR2 — Mandatory thesis content:** business model in two sentences, moat + evidence, owner-earnings picture, valuation anchor at purchase, conviction level, time horizon, explicit and **testable** invalidation triggers, 10-year statement.
- **FR3 — Hell-No first.** The Munger veto runs before any Buffett analysis; a single fail is a rejection, regardless of upside.
- **FR4 — Daily loop:** trigger check, balance drift, buying opportunities. A price drop with an intact thesis is presented as an *opportunity*, not an alarm. The default outcome is "no action needed" — a first-class, positive outcome.
- **FR5 — Weekly loop:** fundamentals refresh per holding, full thesis re-validation, portfolio balance (concentration 10–15 positions, sector spread, cash), learning digest.
- **FR6 — Event-driven:** earnings, filings, and management changes force an immediate thesis check, outside the regular rhythm.
- **FR7 — Thesis status:** intact / under review / broken. A broken thesis produces sell advice that ignores cost basis.
- **FR8 — Decision journal:** every decision (buy, sell, hold, alert ignored) is recorded with the reasoning of that moment; process quality is judged separately from returns.
- **FR9 — Human judgment is sacred:** conviction, trust in management, and circle-of-competence fit are always asked of the owner, never invented by the system.
- **FR10 — Outside-framework holdings** (crypto, copyportfolios) remain visible in the balance, marked "outside framework", without thesis pretension.
- **FR11 — Advice, never execution.** The system never executes transactions.
- **FR12 — Hidden-concentration check.** The weekly balance review includes correlation-cluster analysis: effective bet count + cluster membership + correlation matrix ("are my 12 positions really 3 bets?").
- **FR13 — Quarterly honesty check.** Quarterly performance comparison against one index benchmark; never surfaced in daily/weekly outputs (envy / action-bias rules). Answers Buffett's honesty question: "would an index fund beat my process?"
- **FR14 — Idea generation is human-triggered only.** Automated loops never scan for new candidates; screener output enters only the watchlist and only through the Gate.

## Non-functional requirements (approved 2026-07-03)

- **NFR1 — Robust to source failure:** if eToro or a data source fails, the system keeps running on the last snapshot and reports the staleness.
- **NFR2 — Privacy:** portfolio data stays private.
- **NFR3 — Low cost:** free data sources as the starting point; paid only on demonstrated shortfall.
- **NFR4 — Auditable:** every analysis, report, and thesis change is traceable in history.
- **NFR5 — Low maintenance:** the system must run for months without tinkering.
- **NFR6 — Data-layer hardening (yfinance):** own caching/request pacing; emptiness detection on every fundamentals field; shares-outstanding series resampling; staleness flagged in reports.
- **NFR7 — Dependency discipline:** permissive licenses only (MIT/Apache-2.0) in the runtime stack; no AGPL/GPL; no heavy transitive stacks (cvxpy-class) for narrow needs; every dependency must displace more complexity than it adds.

---

## Adopted tooling decisions (from the 2026-07-03 repo research)

See `docs/research/2026-07-03-repo-evaluations.md` for evidence and verdicts.

1. **yfinance** as base price/fundamentals source, with three mandatory hardening practices (app-level caching + pacing; `get_shares_full` resampling + dedup; silently-empty statement detection). *Data layer.*
2. **Hidden-concentration check** via ~5 lines of pandas+scipy correlation clustering — no PyPortfolioOpt dependency. *Weekly loop (FR12).*
3. **quantstats** (pinned `>=0.0.81`) for the quarterly honesty report; outputs treated as indicative, not authoritative. *Quarterly cadence (FR13).*
4. **TradingView-Screener** for occasional human-run quality screens only; never in the automated loop (FR14). Residual ToS tension consciously accepted.
5. **Nothing else.** OpenBB, vectorbt, backtrader, pybroker, qlib, FinRL rejected. SEC EDGAR fallback deferred until yfinance gaps hit actual portfolio tickers.

---

## Open items (carried forward)

1. ~~**Balance targets**~~ — **Resolved 2026-07-08:** defaults approved (cash 5–15%, position 15%/20% soft/hard, cluster 40%, N_eff ≥ 4.0, 10–15 positions, outside-framework cap 10%, opportunity discount 20%, 7-day alert window). See elaboration doc §E.3.
2. ~~**Benchmark choice for FR13**~~ — **Resolved 2026-07-08:** S&P 500 Total Return measured in EUR (PFIC rules make UCITS trackers punitive for a US citizen; US-domiciled fund is the honest counterfactual). See elaboration doc §E.6.
3. **eToro API verification** — portfolio read access, auth model, rate limits; requires a real account key. The elaboration's source-agnostic snapshot contract (§E.1) makes this a swap-in, not a blocker.
4. ~~**Detailed architecture elaboration**~~ — **Resolved 2026-07-08:** `docs/plans/2026-07-08-architecture-elaboration.md` (components A–H incl. the new Scout component, trigger taxonomy, loop specs, output formats, gap resolutions).
5. **Technology/runtime choice** — deliberately parked until the functional design is agreed (owner steer, 2026-07-03). Next open design step.
6. **TradingView ToS posture** — residual tension consciously accepted for occasional human-run screens (see tooling decision 4); revisit if TradingView changes its posture or an official API appears.
7. **ETF policy** — decided 2026-07-08: ETFs default to `outside_framework` (visible in balance and cluster math, no thesis pretension); revisit only if a thesis-worthy ETF need emerges.
