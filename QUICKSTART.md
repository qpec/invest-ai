# Quickstart — a working desk on your own machine

> **Not investment advice.** See the [README disclaimer](README.md) — it applies
> to everything this produces, including everything you build with it.

This gets you from clone to a running local desk in a few minutes, on a bundled
sample dataset (13 well-known US filers, real as-filed SEC data). Every command
below is tested against exactly this repo. The same pipeline scales to the full
~1,900-name universe when you bring the full data; the always-on box deployment
is the last section.

## 0. What you need

- [uv](https://docs.astral.sh/uv/) and git. Everything runs offline on the
  sample data; the enrichment tier needs plain internet (SEC EDGAR, no key).
- For the judgement steps: **a subscription-backed agent CLI** — see §0b. There
  is **no API key** anywhere in this system, by design.

## 0b. The subscription setup (do this once)

The thesis desk is driven by an agent CLI you are **already paying a flat
subscription for**, not by metered API calls. That is a deliberate cost
decision: research and prose are the expensive part of this system, and a
subscription makes them a fixed monthly cost instead of a per-token one.

Pick one:

| Subscription | CLI | One-time setup |
|---|---|---|
| **Claude** Pro / Max | [Claude Code](https://claude.com/claude-code) (or [OpenClaw](https://openclaw.ai) driving it) | `npm i -g @anthropic-ai/claude-code` → `claude login` |
| **ChatGPT** Plus / Pro | [Codex CLI](https://developers.openai.com/codex/cli) | `npm i -g @openai/codex` → `codex login` (choose "Sign in with ChatGPT") |

Then tell the desk which model did the work. The rule is **best available
only**, enforced per provider in `stock-scout/deskwork.py`:

```python
APPROVED_MODELS = {
    "anthropic": ("claude-opus-5",),
    "openai": (),        # ← fill in your subscription's best model, then it is allowed
}
```

An empty list means that provider is **refused**, loudly — the gate never
guesses which model is good enough on your behalf. Where the harness keeps a
readable transcript (Claude Code) the model is read from it rather than taken
on the agent's word; elsewhere pass `--model <id>` and the record says
`declared, NOT independently verified`.

**Never set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.** If one is set, you are
paying per token for something your subscription already covers.

## 1. Install and prove it works

```bash
git clone https://github.com/qpec/invest-ai.git && cd invest-ai
uv sync --locked
uv run pytest -q                              # root suite — fully offline
cd stock-scout && uv run pytest -q            # scout suite
```

## 2. Run the Scout on the sample data

```bash
cd stock-scout
uv run python picks.py   --sec-data sample-data/secdata --prices sample-data/prices \
    --universe sample-data/universe.csv --as-of 2026-08-01
uv run python webapp.py  --sec-data sample-data/secdata --prices sample-data/prices \
    --universe sample-data/universe.csv --as-of 2026-08-01 --out-dir /tmp/desk-site
```

Open `/tmp/desk-site/index.html`: the three-tab desk — ① Scout (every name,
graded twice: the Owner's Scorecard and the Inversion Layer, never merged),
② Thesis Desk, ③ Monitor. `reports/picks-<date>.html` is the audit-grade picks
report. On the sample, expect 2 picks of 13 screened.

## 2b. Drive the desk from the page (`--serve`)

```bash
uv run python webapp.py --serve --sec-data sample-data/secdata \
    --prices sample-data/prices --universe sample-data/universe.csv \
    --enrich-cache enrich_cache --theses-dir theses --out-dir /tmp/desk-site
# → http://127.0.0.1:8899/
```

Same page, with the **Desk actions** live: refresh a name's filings from EDGAR,
draft a thesis, write the weekly work order, run the monitor, rebuild the page.
The server binds loopback only and every call carries a per-run capability
token, so nothing outside your machine can start a job — and on the
[public site](https://qpec.github.io/invest-ai/) these same buttons render
disabled, because running the desk spends the operator's own agent budget.

**Ratifying is deliberately not a button.** `thesis.py ratify <SYM>` asks *you*
for conviction and circle-of-competence; a browser click is the wrong door for
the one irreversible step (FR9).

## 3. The judgement beats (Claude Code / OpenClaw)

Every LLM-facing task runs in three beats — Python writes a work order, the
agent researches with its own tools and writes files, Python re-validates
mechanically and **exits non-zero if it refuses the work**:

```bash
# 1. brief — write the work order for a candidate
uv run python thesis.py brief CROX --sec-data sample-data/secdata \
    --prices sample-data/prices --universe sample-data/universe.csv --as-of 2026-08-01

# 2. work — open this repo in Claude Code (or point OpenClaw at it) and ask it
#    to execute theses/drafts/CROX/WORK-ORDER.md. The order is self-contained:
#    research steps, schema, rules, and the file to write.

# 3. record — mechanical validation; refuses untestable triggers, forbidden
#    fields, and any model not on the best-available list
uv run python thesis.py record CROX
```

A draft becomes real only at the Gate — `uv run python thesis.py ratify CROX` —
where conviction and circle-of-competence are asked of a **human,
interactively**. No agent can answer them; machine-written drafts don't even
have the fields (FR9). The weekly monitor is the same shape:
`monitor.py brief` → agent answers the pre-committed questions →
`monitor.py run` evaluates every trigger (an unanswered question is reported
UNCHECKED, loudly — never guessed).

## 4. Bring the full universe

The sample is a subset of three inputs you can grow independently:

| Input | Sample | Full |
|---|---|---|
| `universe.csv` | 13 names | `uv run python universe.py` builds ~2,900 candidates from FinanceDatabase; `--sec-merge` extends any universe with every NYSE/Nasdaq/NYSE-American filer straight from the SEC's own map (~7,000 total, stdlib only) |
| SEC export dir | `sample-data/secdata/` | the same two CSV shapes for any symbols (`secsv.py` documents them); a full 2026-08-01 snapshot lives in the owner's private state archive as `batches/` |
| price grids | `sample-data/prices/` | `populate.py` walks them from public sources, politely paced |

Missing data never scores zero and never blocks: absence shrinks the
denominator and is labelled (R7). `enrich.py` is the tiered gap-filler — tier 2
fetches as-filed EDGAR companyfacts straight from the SEC (cached, no key) for
whatever symbols you point it at.

## 5. Make it yours

- **The constitution** (`CLAUDE.md`, top section) encodes the investment
  framework *and this owner's* circle of competence — replace the owner
  context with your own; the Buffett/Munger/Naval machinery is generic.
- **The universe** is pre-committed by design (FR14): edit `universe.csv` /
  `universe.py` filters to your own hunting ground.
- **The model gate** (`stock-scout/deskwork.py` → `APPROVED_MODELS`) pins which
  model may do desk work. Widening it is a deliberate code change, on purpose.

## 6. Going always-on (the box)

One small VPS runs the whole weekly loop unattended — mechanical lane (systemd
timers: scrape → brief → monitor → publish) and judgement lane (an `openclaw`
user whose filesystem permissions ARE the guardrails), with GitHub as the only
seam: code pulled from `main`, the site pushed to `bot/site` (GitHub Pages),
private state archived to its own repo. `deploy/digitalocean/README.md` is the
step-by-step; `docs/plans/2026-08-04-distributed-desk-architecture.md` is the
full design with its security model.

## 7. The two surfaces

| Surface | Data | Actions | Where |
|---|---|---|---|
| **Public demo** ([live](https://qpec.github.io/invest-ai/)) | pregenerated sample | replay a recording, banner says nothing executes | GitHub Pages |
| **Your desk** | your real data | live, token-gated | `webapp.py --serve` on loopback |

Both come out of the same generator, so a UI change lands in both at once —
`python webapp.py --demo …` builds the first, `--serve` runs the second. On the
box the desk runs as `scout-desk.service` and you reach it with
`ssh -N -L 8899:127.0.0.1:8899 root@<box>`.
