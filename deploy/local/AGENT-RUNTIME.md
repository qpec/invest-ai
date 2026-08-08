# The agent runtime — configuration contract (local)

The desk needs one **subscription** coding-agent CLI to do its research and
judgement work. This file is the checklist for setting that up on the machine
you run the desk on. Exact config syntax depends on which CLI and version you
installed (`claude --help`, `openclaw config`, `codex --help`); what must be
TRUE is fixed by the architecture (see `CLAUDE.md`) and is listed here.

There is no server. Everything below happens on your own machine, under your
own user account.

## 1. Auth — a subscription, never an API key

Log in once, interactively, with whichever CLI you use:

```bash
claude login          # Claude Pro/Max, via Claude Code
openclaw login        # OpenClaw, driving the claude binary as a subprocess
codex login           # ChatGPT, via the Codex CLI
```

**No `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` anywhere.** API-key mode is the
path the owner locked out ("run by claude code or openclaw. Not api") — it is a
cost decision and a hard rule, not a preference. If a config field asks for a
key, leave it empty.

When the login expires the failure is the benign one: the monitor reports
judgement triggers UNCHECKED, loudly. Recovery is one line — log in again and
re-run the job.

## 2. Model — pinned to the best available

Pin the model to an id in `deskwork.APPROVED_MODELS` (keyed per provider).
`thesis.py record` and `monitor.py run` refuse work declared from any other id,
so a drifted config cannot corrupt a thesis — it only wastes a run. Widening
the approved list is an owner-side code change; there is no override flag.

`deploy/local/scout-thesis-runner.sh` is what the production run invokes per
candidate. It pins the model and runs each symbol in its own session key.

## 3. Exposure — loopback only

- The production desk (`webapp.py --serve`) binds to `127.0.0.1`. Reach it over
  an SSH tunnel if you want it from another device; never open a port.
- If your agent CLI runs a daemon or gateway, bind it to `127.0.0.1` too, and
  disable its web UI.
- A served build carries a capability token and must never be written into the
  published `docs/` tree. The generator guards this.

## 4. The two agent beats

Both beats are the same shape: a work order is a file, any harness can execute
one.

**Thesis drafting** — `thesis.py brief SYM` writes the work order, the agent
researches and writes `report.md` / `summary.md` / `thesis.json`, then
`thesis.py record SYM` re-checks every rule mechanically and exits non-zero if
it refuses the work. In a production run this is the `evaluate_theses` stage,
driven by `scout-thesis-runner.sh`.

**Weekly verdicts** — `monitor.py brief` writes the week's questions, the agent
answers them into `verdicts.json`, and `monitor.py run` ingests them. The
arithmetic and the sticky-broken logic always run in Python; a verdict only
ever *answers a question*.

> Note: the unattended production run (`local_production.run_monitor`) does not
> currently supply verdicts, so event/narrative triggers read UNCHECKED unless
> you run the verdict beat yourself. That is the honest state, and UNCHECKED is
> reported loudly by design — a missing judgement never reads as "fine".

Ratification is never automated. `thesis.py ratify` is a human ritual: it asks
for conviction and circle-of-competence (FR9), and only then does a thesis reach
`theses/committed/` where the monitor acts on it.

## 5. What the agent can never do (enforced, not requested)

- **Commit a thesis.** Ratification is CLI + human; the browser has no door to it.
- **Fire a trigger.** Verdicts answer questions; the metric arithmetic, the
  persistence streaks and the sticky-broken state are mechanical.
- **Execute a trade.** The system advises and monitors. It never trades (FR11).
- **Write the contract.** The agent is trusted for research and prose; `record`
  re-checks every rule against the file on disk.

Prompt injection from the open web is an assumed input, not a surprise: the
blast radius is a bad draft or a bad verdict, both of which the mechanical layer
validates, labels, and can only ever turn into "review" or "UNCHECKED" — never a
silent action.
