# The Thesis Engine — scout-first, and the thesis becomes executable

**Status:** design, 2026-08-03. Owner-directed refactor: *"The main starting engine should
now be the scout. After the scout a thesis builder should run for the best 1%... Output is
the thesis, executive summary (non technical) and the extensive report. The committed
investment + thesis will be validated by a weekly monitor."* Clarifications taken 2026-08-03:
LLM lock **fully lifted**, builder output is a **draft for the Gate**, grounding is a
**data tool + our own research loop**, cadence is an **on-demand batch**. Revised the same
day, on the owner's follow-up — *"This thing will be run by claude code or openclaw. Not
api"* — so the "own research loop" is executed by the agent harness itself and there is no
API client anywhere in the repo. See §5.

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

The follow-up decision, journaled the same day: the LLM enters as the **operator of the
tooling, not a dependency of it**. The owner runs this from Claude Code or OpenClaw, so the
harness supplies the model, the web search and the shell; the repo supplies the packet and
the validation and stays stdlib. NFR7 and the four-runtime-dependency budget are therefore
untouched by this revision — the thesis engine adds *zero* runtime dependencies, and the
one optional extra (edgartools, MIT) remains a desk-side guarded import.

## 2. The pipeline, re-anchored on the Scout

```
                 SCOUT (the starting engine)
  universe → fundamentals → prices → scoring → scorecard → inversion
                              │
                              ▼  top 1% (~19 of 1,904)
                    THESIS BUILDER  (on-demand batch, FR14)
      brief → WORK-ORDER.md → agent researches → record (validation)
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
        narrative triggers → asked as a brief, answered by the agent
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
3. **The open web** — the agent's own web search, used while executing the work order:
   news, competitive landscape, management changes, anything past the filings. The work
   order sets a budget (~20 searches) and says depth beats breadth; it does not, and
   cannot, police how the agent searches.

## 5. The agent is the runtime (revised 2026-08-03)

**There is no LLM API client in this repo.** The first cut of this design specified a
hand-rolled `urllib` Claude client (`llm.py`), a server-side `web_search` tool, a strict
`record_thesis` tool and a cost model. That was the right shape for a headless daemon and
the wrong shape for this system, because this system is run by an agent harness — Claude
Code, OpenClaw — that *already* has a model, web search, a file system and a shell. Asking
it to open a socket to a second model would be paying twice for the same capability, and
it would put an API key and a network dependency in front of work the harness can already
do. (The owner reached the same conclusion once before, for the Stage-2 qualitative
reviewer: `docs/plans/2026-07-11-scout-stage2-qualitative-reviewer-design.md` — "no
Anthropic API key, no new agentcy dependency".)

The client is deleted. What replaces it is a seam, in `deskwork.py`:

```
python … brief   →   the agent researches and writes files   →   python … record
```

**Beat 1 — `brief` writes a work order.** `deskwork.order()` renders
`theses/drafts/<SYM>/WORK-ORDER.md`: what to produce and where, how to go about it, the
rules, the research packet (both judgements unmerged), the filings text, the framework,
the trigger discipline, the JSON schema, and — last — the exact command that will judge
the result. A machine-readable `packet.json` is written beside it so beat 3 can check the
draft against the same numbers the agent was given.

**Beat 2 — the agent works.** It reads the order, researches with its own tools, and
writes `report.md`, `summary.md`, `thesis.json`. The repo has no opinion about how. The
agent-facing instructions live in `.claude/skills/thesis-desk/SKILL.md` at the repo root,
so a harness discovers the workflow without being told about it.

**Beat 3 — `record` accepts or refuses.** This is the seam's whole point. Every rule that
makes a thesis monitorable is re-checked mechanically against the files on disk: the three
artifacts exist and are non-empty, the summary carries its heading, the draft validates,
no conviction or circle-of-competence field leaked in from the builder (FR9), at least
three triggers with at least one mechanical, no metric outside the registry, no metric the
packet could not compute (it would be UNCHECKED forever), no narrative trigger with a
`break` action. Problems are written into `record.json` **and** raised: a non-zero exit
means the artifact is not accepted.

The seam is deliberately one-directional. The agent is trusted for research and prose and
never for the contract. Nothing in beat 3 depends on the agent having behaved well, which
is the only property that makes an LLM safe to put inside a decision pipeline.

### The model gate

Pinning a model was something the deleted client did for free (`AGENTCY_LLM_MODEL`,
default claude-opus-5). Removing it removed the guarantee, and quietly: the model became a
property of how the harness was launched, invisible to the repo and — worse — invisible to
whoever reads a thesis a year later. A thesis written by the cheapest available model would
have looked exactly like one written by the best.

The owner's rule is **best available only**, so:

- `deskwork.observed_model()` reads the model out of the harness's own transcript. This is
  the only mechanically trustworthy answer: an agent asked to name its model can say
  anything, and nothing else in this design trusts the agent for the contract.
- `record` stamps `{id, provenance, approved}` onto `record.json` and refuses an unapproved
  model — writing the record anyway, carrying the reason, because a refusal that leaves no
  trace is the failure mode the seam exists to prevent.
- `ratify` re-checks rather than trusting the stamp. `record.json` is an ordinary file; if
  the Gate believed its `approved` flag, editing one line would launder any model at all.
- `monitor.py run` gates **judgement, not arithmetic**: ingesting agent verdicts requires an
  approved model, a metric-only sweep requires none, and the weekly report names the model
  on its first line — whoever reads a BROKEN verdict is about to act on it.
- Where no transcript exists (OpenClaw, a bare shell), a `--model` declaration is accepted
  and labelled `NOT independently verified`. Where a transcript does exist, a declaration
  that contradicts it is refused; that cross-check is the only thing that makes accepting a
  declaration elsewhere defensible.

There is deliberately **no override flag**. An escape hatch on this gate would be operated
by the agent, and the agent is the thing being constrained. When a better model ships the
owner edits `deskwork.APPROVED_MODELS` — a code change, in a file under review, journalled
by git. That is the correct amount of friction for a rule that is otherwise unfalsifiable.

Two consequences worth stating:

- **The cost model is gone.** There is no per-name dollar figure to print, because there
  is no metered API call. The budget is the owner's harness subscription and the owner's
  attention.
- **Determinism moved to the right side of the line.** The parts that must be reproducible
  — packet, registry, validation, monitor arithmetic — are pure Python and covered by
  tests. The parts that cannot be reproducible — research, judgement, prose — are the
  agent's, and are bounded by what beat 3 will accept.

## 6. Outputs

Per name, under `theses/drafts/<SYM>/` (git-ignored — theses are portfolio data, NFR2;
state does not live in the code repo):

| File | Audience | Content |
|---|---|---|
| `thesis.json` | the machine | the FR2 schema + typed triggers + sources (the metrics snapshot and the validation verdict are recorded beside it in `record.json`) |
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
3. **Event/narrative triggers**: the same three-beat seam. `monitor.py brief` lists only
   the judgement questions — asking the agent about a metric trigger would be inviting an
   opinion about a fact — and the agent answers them into `verdicts.json` as
   `{tripped, confidence, evidence, sources}` per trigger id. A question with no verdict
   is reported **UNCHECKED**, loudly; silence is never safety. Confidence is mechanical:
   only `high` (documented public fact) lets a `break` trigger actually break, anything
   less demotes to review.
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
- **No API client, and no way to add one quietly.** The validation lives in Python and the
  research lives in the harness; a future transport would have to re-implement beat 3 to
  get around it, which is exactly the kind of change a review would notice.
