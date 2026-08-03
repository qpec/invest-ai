# The Thesis Engine — scout-first, and the thesis becomes executable

**Status:** design, 2026-08-03. Owner-directed refactor: *"The main starting engine should
now be the scout. After the scout a thesis builder should run for the best 1%... Output is
the thesis, executive summary (non technical) and the extensive report. The committed
investment + thesis will be validated by a weekly monitor."* Clarifications taken 2026-08-03:
LLM lock **fully lifted**, builder output is a **draft for the Gate**, grounding is a
**data tool + our own research loop**, cadence is an **on-demand batch**.

---

## 1. The architecture revision, said out loud

The 2026-07-08 technology architecture locked **"no LLM in the scheduled runtime"** — the
Gate and the Study were desk sessions. That lock is now **lifted in full**, by owner
decision on 2026-08-03. This entry is the journal record the decision-journal discipline
(FR8) requires: the lock was ratified, it served while the system's judgement was purely
mechanical, and it is consciously traded away because two new components are judgement
work that mechanical rules cannot do — writing a thesis draft, and answering a narrative
invalidation question. The rest of the constitution is untouched; in particular FR9 (human
judgement is sacred) and FR11 (advice, never execution) bind these components hardest of
all.

## 2. The pipeline, re-anchored on the Scout

```
                 SCOUT (the starting engine)
  universe → fundamentals → prices → scoring → scorecard → inversion
                              │
                              ▼  top 1% (~19 of 1,904)
                    THESIS BUILDER  (on-demand batch, FR14)
        metrics + fragility findings + filings text + web research
                              │
             draft thesis + executive summary + extensive report
                              ▼
                    THE GATE  (human, FR9)
        owner ratifies/edits: conviction, circle fit — or rejects
                              │
                              ▼  committed thesis, triggers armed
                    WEEKLY MONITOR
        metric triggers → evaluated mechanically from fresh SEC data
        narrative triggers → answered by LLM with web search
                              │
                              ▼
        intact / under review / broken  →  report; broken ⇒ sell
        advice that ignores cost basis (FR7). Never a trade (FR11).
```

Three properties are load-bearing:

- **The Scout starts everything.** Idea generation stays human-triggered (FR14): the
  builder runs when the owner asks, over whatever the pipeline currently ranks top 1%.
- **A thesis is a draft until the Gate.** The builder never invents conviction or circle
  fit — those fields do not exist in its output schema and are asked of the owner at
  ratification (FR9). Only a ratified thesis is monitored.
- **The thesis drives the monitoring** — the constitution's core principle, now executable:
  every trigger the builder writes must be machine-validatable, and ratification refuses a
  thesis whose triggers are not.

## 3. What a thesis is (FR2, made machine-checkable)

The mandatory content is FR2's, unchanged: business model in two sentences, moat with
evidence, owner-earnings picture, valuation anchor at purchase, conviction, horizon,
testable invalidation triggers, the 10-year statement. What this design adds is the
**validation contract**: a trigger is one of three kinds, and each kind names how a machine
checks it.

| Kind | Example | Validated by |
|---|---|---|
| `metric` | "TTM owner-FCF margin falls below 12% for 2 consecutive weekly checks" | the metric registry, mechanically, from the fresh SEC bundle — no LLM |
| `event` | "Loses the Apple modem contract" / "CEO departs" | LLM + web search, weekly — a yes/no question about a public fact |
| `narrative` | "Credible evidence that casual-footwear demand is structurally declining" | LLM + web search, weekly — judgement, so it can only put a thesis *under review*, never break it alone |

Rules the builder is held to (enforced by `thesis.validate()`, not by hoping):

- A `metric` trigger may reference **only** the declared metric registry — the same
  functions `scoring.py`/`scorecard.py` already compute, so live run and monitor cannot
  disagree about a number. No free-form expressions, no `eval`.
- An `event`/`narrative` trigger must be a **single yes/no question answerable from public
  information**, with the evidence standard stated in the question itself.
- Every trigger carries a pre-committed `action`: `break` or `review`. Mechanical triggers
  may break; narrative ones may only send to review — the owner breaks a thesis at the
  desk, which is FR7's "broken → sell advice ignoring cost basis" with FR9 intact.
- Conviction and circle-of-competence fields are **absent from the builder's schema** and
  added at ratification.

## 4. The builder's inputs — judgement grounded three ways

1. **The repo's own metrics** — the scorecard card (points, blocks, evidence tier,
   consensus) and the inversion verdict with its failure-mode sentences. The builder is
   explicitly required to address every severe fragility finding in the bear case; the two
   judgements arrive unmerged, per the standing rule.
2. **Filings text** — via **edgartools** (MIT; chosen 2026-08-03 by a DeepGit-style search
   across GitHub: the dominant, actively-maintained SEC-filings library; the runner-up
   `sec-edgar-toolkit` is AGPL-3.0 and thus banned by NFR7; `defeatbeta-api` (Apache-2.0,
   transcripts) is noted as a future add). Risk factors and MD&A from the latest 10-K are
   clipped into the packet. edgartools carries a heavy dependency tree, so it is confined
   to the **desk-triggered builder only** behind a guarded import — the scheduled runtime
   never imports it, and its absence degrades the packet honestly ("filings text
   unavailable — web research only") instead of failing the run.
3. **The open web** — Anthropic's server-side `web_search` tool inside the research loop:
   news, competitive landscape, management changes, anything past the filings.

## 5. The research loop (own loop, stdlib transport)

Per the repo's stdlib-spine precedent (the hand-rolled Telegram client), the Claude
Messages API client is ~200 lines of `urllib` in `llm.py` — no SDK dependency in the
runtime. The loop:

- **Model** `claude-opus-5` (thinking on by default; no sampling params). Configurable via
  `AGENTCY_LLM_MODEL`.
- **Tools**: `web_search_20260209` (server-side, capped uses) + one custom **strict** tool,
  `record_thesis`, whose input schema *is* the thesis draft. The system prompt requires the
  run to end by calling it exactly once; strict mode makes the API guarantee the JSON
  validates. Structured output and free-prose research coexist in one conversation: the
  extensive report and executive summary are written as text turns, the thesis arrives as
  the tool call.
- **`pause_turn`** (server tool iteration limit) is resumed by re-sending; **`refusal`** is
  handled before reading content, with the server-side `fallbacks: "default"` opt-in
  (beta `server-side-fallback-2026-07-01`) enabled by default so a classifier
  false-positive re-runs on the recommended fallback instead of killing a batch. Turned
  off with `fallbacks=None`.
- Usage is accumulated across turns and written into the run record — every thesis carries
  what it cost to write.

**Cost model** (opus-5 at $5/$25 per MTok): a deep-research run is ~8–20 searches and a
long context, ≈ $1.5–4 per name; a full top-1% batch (~19 names) ≈ **$30–75**. The weekly
monitor touches only narrative/event triggers with small contexts: ≈ $0.05–0.20 per thesis
per week. Both numbers are printed by the tools themselves after each run.

## 6. Outputs

Per name, under `theses/drafts/<SYM>/` (git-ignored — theses are portfolio data, NFR2;
state does not live in the code repo):

| File | Audience | Content |
|---|---|---|
| `thesis.json` | the machine | the FR2 schema + typed triggers + metrics snapshot + sources + usage |
| `summary.md` | the owner's non-technical self, family, future-you | one page, no jargon: what the business does, why it might compound, what would make us leave, what it costs to be wrong |
| `report.md` | the Gate session | the extensive research: moat evidence, owner-earnings history, valuation work, bear case addressing every severe fragility finding, competitive landscape, sources |

Ratification (`thesis.py ratify SYM`) asks the owner the FR9 questions, validates every
trigger is checkable, stamps version/status/date, and moves the thesis to
`theses/committed/`. The monitor reads only `committed/`.

## 7. The weekly monitor

`monitor.py` runs in the weekly loop (Saturday, with the Watchdog):

1. Rebuild fresh bundles (SEC export / caches) for committed symbols.
2. **Metric triggers**: evaluate against the registry; a trigger with
   `consecutive_checks: N` keeps its streak in the thesis's own trigger state, so a single
   noisy week cannot break a thesis that demands persistence.
3. **Event/narrative triggers**: one LLM call per trigger — web search on, a strict
   `record_verdict` tool returning `{tripped, confidence, evidence, sources}`. No API key
   → the trigger is reported **unchecked**, loudly; silence is never safety.
4. Status per FR7: any tripped `break`-action trigger ⇒ **broken** (sell advice ignoring
   cost basis); any tripped `review`-action trigger ⇒ **under review** with the evidence
   quoted; else **intact** — and "no action needed" is printed as the first-class good
   outcome it is (FR4).
5. Output: `reports/monitor-<date>.md` + updated trigger state. The monitor never
   executes anything (FR11) and never edits thesis content — only status and state.

## 8. What this deliberately does not do

- **No auto-commit.** The builder cannot arm its own triggers; the Gate is a human step.
- **No portfolio sizing, no price targets.** The valuation anchor records what the price
  was and how it was judged; it is not a target.
- **No thesis for the un-scoreable.** A name the pipeline cannot score (NO PRICE, VETOED)
  cannot be in the top 1% and gets no thesis; a veto is Munger's pillar doing its job.
- **No narrative auto-break.** An LLM's judgement can summon the owner to the desk; it
  cannot fire the owner's sell rule on its own.
