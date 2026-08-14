# stock-agentcy

> **Public rebrand 2026-08-05 (owner-directed):** the GitHub repository is
> `qpec/invest-ai` and the repo is public; the private state archive is
> `qpec/invest-ai-state`. Internal names (`agentcy`, `stock-scout`, this file)
> deliberately keep the working name.

A daily/weekly iterating financial-analysis system for portfolio oversight. The core
object is the **investment thesis**, not the stock: every position carries a written
thesis with a conviction level and pre-committed invalidation triggers. The system
evaluates candidate buys through the framework below, monitors holdings against their
triggers, and reports on portfolio balance.

**The system advises and monitors. It never executes trades.**

---

# PART I — ORIENTATION FOR CODING AGENTS

Read this part first. Part II is the investment framework (the product spec — it is the
rubric every analysis obeys). Part III is the architecture.

## The 60-second model

```
SEC filings + prices  ──►  Bundle  ──►  scoring/scorecard/inversion  ──►  top 1%
                                              (pure, no I/O)                 │
                                                                             ▼
 site (docs/)  ◄──  production run  ◄──  monitor  ◄──  committed thesis  ◄── Gate (human)
                                                                             ▲
                                                          agent writes draft ─┘
```

Two ideas explain most of the code:

1. **The thesis drives the monitoring.** The Watchdog only ever tests triggers the
   thesis pre-committed to. There is no open-ended news scanning.
2. **The agent is trusted for research and prose, never for the contract.** Every
   agent-facing task is three beats — `brief` writes a work order, the agent writes
   artifacts, `record` re-checks every rule mechanically and exits non-zero if it
   refuses the work.

## Where to start reading

| To understand… | Read |
|---|---|
| the rubric | Part II below |
| how a company is scored | `stock-scout/scoring.py`, then `stock-scout/scorecard.py` |
| how it can break you | `stock-scout/inversion.py` |
| the agent seam | `stock-scout/thesis.py` + `.claude/skills/thesis-desk/SKILL.md` |
| a production run | `stock-scout/production.py` + `stock-scout/local_production.py` |
| the UI | `stock-scout/webapp.py` |
| why a thing is the way it is | `docs/plans/`, `docs/superpowers/plans/` (decision journal) |

## Running things

```bash
# tests — this container's working incantation (uv-managed CPython)
cd stock-scout && uv run -p 3.13.7 --project .. python -m pytest tests/ -q   # 888
cd .. &&          uv run -p 3.13.7             python -m pytest tests/ -q   # 1110

uv run -p 3.13.7 python tools/license_gate.py    # dependency licence policy (NFR7)
```

A full local production cycle:

```bash
cp deploy/local/scout-production.env.example ~/config/invest-ai-production.env
SCOUT_PRODUCTION_ENV=~/config/invest-ai-production.env \
  deploy/local/scout-production.sh manual
```

## Shipping a change — the published site is part of "done"

**Every change that can alter what the site shows must end with the site republished.**
Code merged but not published is a lie on a public page: the desk keeps serving the last
build, so a fixed bug still reads as broken and a new metric silently does not exist. A
change is not done at the commit, it is done when the live page carries it.

```bash
# after committing a change that touches scoring, the desk loop, or the UI:
SCOUT_PRODUCTION_ENV=~/config/invest-ai-production.env \
  deploy/local/scout-production.sh manual      # rebuild, publish, verify live
```

That one command is the whole ritual: it runs the six stages, validates, pushes the built
site to the branch GitHub Pages serves, **and then reads the live page back to prove the
publication happened.** It needs the real data (SEC export, enrich cache, price grid,
theses), so it runs on the owner's machine.

**Publication is the page, not the push** (learned the hard way, 2026-08-08). The
publisher targeted `bot/site` while Pages was actually serving `main/docs`: every run
reported success, and the public page silently went months out of date. Nothing in the
pipeline could catch it, because nothing ever looked at the site. So:

- `SCOUT_SITE_BRANCH` must equal whatever *Settings → Pages → Source* says. Today that
  is **`main`, folder `/docs`** — verified by fetching the live page and finding it
  byte-identical to `main:docs/index.html`.
- `SCOUT_SITE_URL` is required config, and after pushing the run polls it for the
  `snapshot_id` it just built. If the live page does not serve that snapshot, the run
  **fails** and does not record a publication. This catches the branch mismatch and every
  other way publishing fails open — Pages disabled, a stuck deploy, a stale CDN.
- If you ever move the Pages source, change `SCOUT_SITE_BRANCH` in the same commit. The
  verification will tell you immediately if you forget, which is the point.

An agent working in a container cannot run the full cycle (no real data). It *can*
re-render an existing published snapshot through the current renderer when only the
template changed — same data, same `snapshot_id`, new projections — but it must never
approximate a figure the pipeline would compute from source bundles (that is
"refuse, never guess"). When you are that agent and cannot publish: say so explicitly in
your hand-off rather than leaving the site stale and unmentioned.

Publishing is skipped only when a change provably cannot reach the page — a test-only
edit, a comment, a doc. If you are unsure, republish; it is idempotent and a no-op when
the output is unchanged.

## The invariants — break these and the system is wrong, not just broken

These are enforced by tests. If a change makes one of them false, the change is wrong.

1. **Never executes trades** (FR11). No broker, no order path, ever.
2. **The two judgements are never merged.** The scorecard says how good the business
   is; the inversion layer says how it breaks. They are never added, averaged or
   reconciled — not in code, not in a report, not in a pixel. A name can be Exceptional
   and Ruinous at once and every surface must show exactly that.
3. **Owner-only fields (FR9) never reach a public surface.** `conviction` and
   `circle_of_competence` are the owner's, asked only at the Gate. The builder's schema
   has no field for them; `webapp.strip_owner_fields` strips them at the render layer;
   the publisher strips them from archived theses.
4. **The decision layer is pure.** `scoring.py`, `scorecard.py`, `inversion.py`,
   `registry.py` do no I/O, no network, no clock. Same Bundle in ⇒ same numbers out.
5. **Refuse, never guess.** A metric whose input is unmeasured is `None` — never 0,
   never a default. Missing data shrinks the denominator (`48 of 67 measurable`), it
   never silently scores zero. A verdict that cannot be certified is `Unknown`, said
   out loud.
6. **Supplements never enter the decision.** Registry v2's extra metrics can never
   enter the scoring sums, and composites (Piotroski F, Altman Z) are display-only —
   letting one fire a trigger would be the forbidden merge.
7. **No price triggers.** A falling quote with an intact thesis is an opportunity, not
   an invalidation. The one quote-derived registry metric (`owner_fcf_yield_pct`) is
   display-only and refused as a trigger metric.
8. **No LLM API client in this repo.** The agent runtime is a *subscription* CLI. No
   `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` anywhere. `llm.py` was deleted deliberately;
   re-adding a transport would have to re-implement `record` to get around the seam.
9. **Four runtime pip packages** — `yfinance`, `pandas`, `scipy`, `quantstats`.
   GPL-family licences (incl. LGPL) are banned; `certifi` (MPL-2.0) is the one
   journaled exception. `tools/license_gate.py` enforces it.
10. **Append-only production state.** Production runs, top-1% membership and thesis
    evaluations are append-only; exactly one snapshot is active; a failed run leaves
    the last known good snapshot untouched.
11. **Ratification is human and CLI-only.** A browser button is the wrong door for the
    one irreversible step.
12. **Munger gates the desk feed.** A vetoed band, a Fragile/Ruinous verdict or any
    severe probe means the name never becomes a thesis — the Hell-No filter runs BEFORE
    the Buffett dossier, in `thesis.top_symbols`, not as a label afterwards. `Unknown` is
    not a veto: it means the layer could not certify, which is a fact about the evidence.
13. **The published site tracks the code, and publication is verified.** A change that
    can alter the page is not done until the live page serves it. The production run
    reads `SCOUT_SITE_URL` back and fails if it is not serving the snapshot just built —
    a push is not a publication. See "Shipping a change" above.

---

# PART II — THE INVESTMENT FRAMEWORK (CONSTITUTION)

> Buffett teaches you what to buy. Munger teaches you what to avoid. Naval teaches you
> how to keep upgrading.

Every analysis agent MUST apply this framework. It is the rubric for every candidate
evaluation, every thesis, every re-validation, and every report. When the framework and
a "great opportunity" conflict, the framework wins.

## Pillar 1 — What to Buy (Buffett)

Buy wonderful businesses at fair prices, and let compounding do the heavy lifting.

- **Understand it or pass.** If the business model and its moat cannot be explained in
  two sentences, PASS.
- **Moat checklist.** Require at least one durable competitive advantage, with evidence:
  network effects, switching costs, cost advantages, brand/trust, regulatory barriers.
- **Owner earnings over reported earnings.** Judge by free cash flow — how much cash the
  owner could pull out after maintaining competitive position — not by reported EPS.
- **The 10-year test.** Would we hold this if the market closed for a decade? If not, it
  is speculation, not investment.
- **Practical rules:** concentrate in 10–15 high-conviction positions; reinvest
  dividends unless income is needed; buy more when great businesses go on sale; the
  default holding period is forever.

## Pillar 2 — What to Avoid (Munger)

Inversion: instead of "how do I succeed?", ask "how would I guarantee failure?" — then
don't do those things.

**The Hell-No filter** — run BEFORE any Buffett analysis. Failing even ONE test means
automatic rejection, regardless of upside.

- Leverage on volatile assets — never borrow to invest in equities
- Businesses we don't understand — if the thesis needs 47 assumptions, walk away
- Management we don't trust — look for owner-operators with skin in the game
- Fads disguised as trends — AI is a real trend, most AI-branded vehicles are fads
- High-fee structures — fees compound against you

**Psychology traps the system actively counters:** envy · FOMO/action bias ("no action
needed" is a first-class, celebrated output) · sunk cost (recommendations ignore cost
basis — the stock doesn't know what you paid) · overconfidence after wins (judge process
separately from outcome) · complexity addiction.

## Pillar 3 — How to Keep Upgrading (Naval)

- **Specific knowledge.** Weight analysis toward the owner's own hard-won edge — the
  domains they know better than the market does.
- **Leverage stack.** Capital, labour, code (this system), media. Shift income from
  labour-based to leverage-based.
- **Continuous learning compounds.** The most important investment is the owner's own
  judgment.
- **Wealth vs. status.** Status games are zero-sum. Buy the boring compounder, not the
  dinner-party stock. The system flags status buys.

---

# PART III — ARCHITECTURE

## Runtime model: local-first

**There is no server.** (Owner-directed, 2026-08-08: the DigitalOcean box was retired
and its whole lane deleted.) The desk runs on a machine the owner already owns:

- One command, one atomic run: `deploy/local/scout-production.sh {manual|daily|weekly}`
  takes a `flock` so runs can never overlap, writes a run-scoped artifact, and only then
  publishes.
- Unattended via `deploy/systemd/scout-production@.service` + daily/weekly timers.
- **GitHub is only a publishing seam:** the built site is pushed to the branch Pages
  serves (today `main`, folder `/docs` — see "Shipping a change"), and the run then
  verifies the live page. Rollback is an ordinary revert on that branch.
- The agent runtime is a subscription CLI (Claude Code / OpenClaw / Codex) logged in
  interactively — see `deploy/local/AGENT-RUNTIME.md`.

## Branches — there is one

**`main` is the only long-lived branch.** Everything is on it: the code, the decision
journal, the seed universe (`data/universe.csv`) and the built site (`docs/`), which is
what GitHub Pages serves. Feature branches are merged and then deleted; nothing else is
expected to persist.

The repo briefly carried five extra branches, all artefacts of the retired DigitalOcean
box, and they are the reason this section exists:

| Branch | What it was | Fate |
|---|---|---|
| `bot/seed` | bootstrap data the box fetched at first boot — it held the ONLY copy of the 7,033-name universe | migrated to `data/universe.csv`, then retired |
| `bot/deploy-log` | a `status.txt` the box wrote on first boot | retired |
| `bot/site` | the box's publish target — which Pages never served | retired; Pages serves `main/docs` |
| `claude/*` | merged feature branches nobody deleted | retired |

If you are about to create a branch that outlives a pull request, don't: put the thing on
`main`, or accept that in six months nobody will know whether it holds the only copy of
something. That is exactly what happened with `bot/seed`.

## Repo map

| Path | What lives there |
|---|---|
| `stock-scout/` | the Scout, the scorecard, the desk loop, the monitor, the site generator |
| `stock-scout/tests/` | the decision-layer + desk suite (888 tests) |
| `agentcy/` | the original portfolio system: DB, schema, Telegram bot, letters, eToro ingest |
| `tests/` | the agentcy suite (1110 tests) |
| `deploy/local/` | the production wrapper, thesis runner, git askpass, agent-runtime setup |
| `deploy/systemd/` | local timers/services (`scout-production*`, `agentcy-*`) |
| `docs/` | the published site (`index.html` + `data/`), runbook, plans, research |
| `docs/plans/`, `docs/superpowers/plans/` | the decision journal — history, never rewritten |
| `tools/` | licence gate, fixture recorder, failure notifier |

## The data flow, stage by stage

**1 · Universe → facts.** `universe.py` builds the security master (~7,000 names via the
SEC ticker+exchange map, one canonical share class per CIK). `secsv.py` loads the bulk
SEC export; `enrich.py` is the tiered fetch chain — tier 1 bulk export, tier 2 live
EDGAR `companyfacts` per symbol (as-filed, `filed` dates intact so point-in-time
survives, disk-cached, fill-only-missing with a provenance ledger), tier 3 yfinance as
**display-only** vendor aggregates that never enter scoring. `pit.py` assembles the
point-in-time view; `prices.py`/`pricesrc.py` supply the price grid.

**2 · The Bundle.** The one object the decision layer consumes: annual + quarterly
income/balance/cashflow cells, shares series, price, market cap, sector/industry. Built
by `pit.as_of_bundle` / `secsv.bundles`, consumed by everything downstream. No module
below this line does I/O.

**3 · Scoring (`scoring.py`) — the relative view.** TTM is assembled over one aligned
window (the newest 4 period-ends present in *both* quarterly income and cashflow).
Owner-FCF = `OCF − min(|capex|, D&A) − SBC`. Then:

- **Composite** = `0.25·V + 0.25·Q + 0.20·G + 0.15·D + 0.15·M`, percentiles computed
  **within sector** over survivors. V = owner-FCF yield on own EV; Q = ROIC ×
  gross-margin level/stability × owner-FCF margin; G = revenue and per-share owner-FCF
  CAGR, gated by a ROIC floor factor; D = net debt/EBITDA, self-funding, SBC; M = share
  count trend, accrual divergence.
- **Veto layer** (runs first, suppresses rather than scores): net debt/EBITDA > 4;
  credit-loss add-backs ≥ 25% of OCF; share dilution > 20%/yr; cash destruction in every
  annual period. Then an integrity-suspend for missing required legs (`INSUFFICIENT`).
- **Margin of safety** — a 3-stage DCF on owner-FCF, discounted at
  `levered_cost_of_equity` (Hamada: β_L = 1.0 × (1 + 0.75 × net-debt/market-cap), CAPM,
  clamped [10.5%, 20%]). Owner-FCF is post-interest, so it is an *equity* flow and takes
  an equity rate; leverage raises the discount and lowers the margin of safety. WACC is
  still reported for reference and discounts nothing.

**4 · Scorecard (`scorecard.py`) — the absolute view.** 100 points over four blocks —
quality 35, price 25, safety 25, stewardship 15 — across 14 anchored metrics, each a
linear ramp. Missing inputs shrink `available_max` (never a silent zero); bands are
computed on the percentage of *available* points: Exceptional ≥80, Strong ≥65, Mixed
≥50, Weak ≥35, else Pass, plus `VETOED` and `NO PRICE`. Evidence tiers (full/partial/
thin) sort **before** percentage. The noise floor is 5 points — differences under it are
not real.

**5 · Inversion (`inversion.py`) — Munger's pillar.** Seven deterministic probes over
~10 years of weekly total-return prices and up to 19 years of filings (six count toward
the verdict; one is flag-only, its data too sparse to score). Severities are **counted,
never averaged** (an average would let a good probe cancel a fatal one).
Ladder: ≥3 severe → Ruinous; 2 severe or ≥4 cautions → Fragile; ≤1 severe → Ordinary;
nothing → Robust; thin evidence collapses Robust/Ordinary → **Unknown** (a verdict that
names a failure mode still stands — missing data can refuse to certify safety, never
manufacture it). **This layer never adds a point to the scorecard.**

**6 · Registry (`registry.py`).** 26 metrics (`thesis.METRICS`) — the entire vocabulary
a thesis trigger may test, computed over the exact same periods `assemble_ttm` selected.
Supplements can never enter the scoring sums; composites are display-only.

**7 · The desk loop (`thesis.py`, `deskwork.py`, `monitor.py`).**
`top_symbols` takes the best 1% of the screened universe by scorecard rank (evidence
tier first, then percentage), above an eligibility floor (`DESK_MIN_MARKET_CAP` $300M,
`DESK_MIN_PRICE` $5). A small-cap tranche (owner-directed 2026-08-14) reserves at least
20% of those slots for the best qualifying names ≤ $2B (`DESK_SMALL_CAP_CEILING`) — same
gates, same rank key, never padded — so small caps stop losing every slot to
longer-filed large caps on evidence tier alone. Then the three beats:

```
thesis.py brief SYM   →  work order (packet: both judgements unmerged + registry values)
   <agent researches, writes report.md / summary.md / thesis.json>
thesis.py record SYM  →  mechanical validation; non-zero exit if refused
thesis.py ratify SYM  →  THE GATE (human, FR9): conviction + circle of competence
```

`record` re-checks everything: artifacts exist and are non-empty, schema shape, the moat
rule (a named moat needs evidence; `kind: "none"` is honest research but marks the draft
PASS-RECOMMENDED, which `ratify` refuses without a typed override), ≥3 triggers with at
least one mechanical, no owner-only fields, no untestable or quote-derived trigger, and
the approved-model rule (`deskwork.APPROVED_MODELS`, keyed per provider, observed from
the harness transcript where one exists).

**8 · The monitor.** Weekly, over *committed* theses only. Metric triggers are evaluated
mechanically off the same `scoring.evaluate` values the grader uses, with persistence
streaks (a threshold usually must hold N consecutive checks). Event/narrative triggers
come from agent verdicts — narrative can only ever send to *review*, never break. Broken
is sticky until the desk acts. A missing verdict is **UNCHECKED**, reported loudly.
Monitored names are always refreshed immediately before they are tested.

**9 · The production run (`production.py` + `local_production.py`).** Six stages —
`refresh → score → select_top → evaluate_theses → monitor → build_site` — then
`validate` and `publish`. State lands in SQLite (`agentcy/schema/010_production_snapshot.sql`):
append-only `production_run`, `production_top_member`, `production_thesis_evaluation`,
and `production_snapshot` with exactly one active row. The release gate blocks
publication on its own terms (e.g. thesis evaluations not current, privacy checks), and
a failed run leaves the last good snapshot untouched.

**10 · The site (`webapp.py`).** One generator, two surfaces, so a UI change lands on
both at once:

- **Public demo** (GitHub Pages) — real latest numbers, a persistent "visual demo —
  nothing is executing" banner, and desk actions that replay captured output (`--demo`).
- **Production desk** (`--serve`) — real data, actions live, bound to loopback and
  reached over an SSH tunnel. A served build carries a capability token and must
  therefore never be written into the published `docs/` tree (guarded).

Output is `docs/index.html` plus lazy per-letter shards in `docs/data/`, entirely
self-contained: hand-rolled CSS/JS, system fonts, no CDN, so it works from a mail
attachment or under a strict CSP. Public projections are **allowlists**
(`public_thesis_reader`, `public_valuation_lens`, `public_portfolio_thesis`), never
redaction. Editable in production: desk *content* only (thesis prose, triggers, notes),
written back through the same validation the CLIs use.

## The agentcy subsystem

The original seven components around the thesis lifecycle — Portfolio Mirror, The Gate,
Thesis Register, The Watchdog, Decision Journal, The Study, The Scout — plus the SQLite
layer, the Telegram daemon (`agentcy bot`) and the scheduled letters
(`agentcy run {daily,weekly,quarterly,event}`). Two SQLite files, with the benchmark DB
physically quarantined, and a rendered-markdown archive in its own git repo.

It is **kept and still runs locally**, and it is not optional plumbing:
`stock-scout/production.py` imports `agentcy.db` and `agentcy.production` for all
production state. Locked decisions: FR13 benchmark = S&P 500 Total Return, measured in
the portfolio's base currency; ETFs outside-framework by default (fund structures can
carry adverse pass-through tax treatment depending on the owner's jurisdiction — the
reasoning is journaled in `docs/plans/`, not here); the daily letter carries no
portfolio value.

## Testing

Two suites, both green and both required: **888** in `stock-scout/tests/` (decision
layer, desk loop, site) and **1110** in `tests/` (agentcy). Three scout tests skip
unless optional research data is present locally — two need a FinanceDatabase
`equities.bz2`, one needs `financetoolkit` (it lives in `requirements-research.txt`,
not the runtime budget). The tests that pin the invariants above — privacy/FR9, append-only,
no-merge of the two judgements, licence policy, never-trades — are load-bearing: treat a
failure there as a design error, not a broken assertion.

## History

This file is the current state, not the changelog. The decision journal lives in
`docs/plans/` and `docs/superpowers/plans/` — functional baseline and architecture
elaboration (2026-07-08), implementation plan (2026-07-09), eToro ingest (2026-07-10),
the Scout-as-starting-engine revision and "the agent IS the runtime" (2026-08-03),
registry v2 (2026-08-03), distributed desk and continuous data refresh (2026-08-04/05),
the local production cutover (2026-08-07), and the adversarial valuation review
(`docs/research/2026-08-08-adversarial-valuation-review.md`). Those documents describe
the world as it was when they were written; where they disagree with this file, this
file wins.
