---
name: thesis-desk
description: Run the stock-agentcy thesis desk — build draft investment theses for the Scout's top 1%, and run the weekly monitor over committed theses. Use when asked to research a candidate, write or update a thesis, ratify one at the Gate, or check whether committed theses are still intact. Triggers on "thesis", "the Gate", "top 1%", "weekly monitor", "is my thesis still true".
---

# The thesis desk

You are the runtime. This repo has **no LLM API client** — the Python owns the packet and
the validation, and *you* do the research and the writing with your own tools.

Every task runs in three beats:

```
python … brief   →   you research and write files   →   python … record
```

Beat 3 is not negotiable. It re-checks everything mechanically and **exits non-zero if it
refuses your work**. Do not report a task finished until it exits clean.

## Ground rules (these come from the owner's Constitution, not from style)

- **You never decide conviction, circle-of-competence fit, or whether to buy.** Those are
  the owner's at the Gate (FR9). The schemas have no field for them; do not editorialise
  them into prose either.
- **This system never executes trades** (FR11). No price targets, no position sizing.
- **Ignore cost basis and entry timing entirely.** The stock does not know what anyone
  paid (FR7).
- **Cite a source URL for every factual claim you get from research.** A weakness stated
  plainly beats a strength oversold.
- **Address every severe fragility finding by name** in a bear case. You may argue against
  one; you may never ignore one.
- **Best-available models only.** Desk work is refused outright if the model doing it is
  not on the owner's approved list. This is read from the harness transcript, not from
  anything you say — and if you also pass `--model`, a mismatch with what the harness
  reports is itself a refusal. If you are not running an approved model, stop and say so
  rather than producing work that will be thrown away.

## Building a thesis

```bash
cd stock-scout
python thesis.py batch --sec-data <dir> --prices <dir>       # top 1%, one order each
python thesis.py brief CROX --sec-data <dir> --prices <dir>  # or one name
```

Then, for each `theses/drafts/<SYM>/WORK-ORDER.md`:

1. **Read the whole order.** It carries the research packet (both judgements, unmerged),
   the filings text if available, the framework, the trigger rules, and the JSON schema.
2. **Research with your own tools.** Web search for competitive landscape, management,
   recent events — anything the filings and metrics cannot show. Depth beats breadth.
3. **Write the three artifacts** into the same directory:
   - `report.md` — the extensive research, including what you could **not** verify
   - `summary.md` — one page for a non-technical reader, opening with the exact heading
     `## Executive summary`
   - `thesis.json` — the structured draft, matching the schema in the order
4. **`python thesis.py record <SYM>`** — fix whatever it reports, re-run until accepted.
   Add `--model <your model id>` if your harness keeps no transcript (OpenClaw, a bare
   shell); on Claude Code it is read for you and the flag is only cross-checked.

The trigger rules are where most rejections come from. A `metric` trigger may only
reference the registry metrics listed in the packet, and only ones with a real current
value — a trigger on an `n/a` metric is refused, because the monitor could never check it.
A `narrative` trigger's action must be `review`: judgement summons the owner, it never
fires the sell rule alone.

## The Gate (the owner does this, not you)

```bash
python thesis.py ratify CROX
```

It asks for conviction and circle fit, re-validates, versions and archives any prior
thesis, warns about any trigger that got easier, and refuses to silently re-arm a broken
one. Only after this does the monitor see the thesis.

## The weekly monitor

```bash
python monitor.py brief --theses-dir theses            # 1. the open questions
# you answer them → theses/monitor-<date>/verdicts.json
python monitor.py run --sec-data <dir> --prices <dir> \
    --verdicts theses/monitor-<date>/verdicts.json     # 2. evaluate everything
```

`brief` lists only the **event/narrative** triggers — metric triggers are answered by
arithmetic, and asking you about them would be inviting an opinion about a fact. Answer
every question in the list; a missing verdict is reported UNCHECKED, which is a gap in
the owner's monitoring, not a pass.

Confidence matters mechanically: `high` means documented public fact (a filing, a company
statement, a major outlet), and it is what lets a `break` trigger actually break. Anything
less demotes to review.

`run` writes `reports/monitor-<date>.md` and sets each thesis to intact / under review /
broken. **Broken is sticky** — it stays until the owner acts at the desk. The report names
the model that answered the questions, and says plainly whether that was observed or merely
declared. A metric-only run (no `--verdicts`) involves no judgement and needs no model.

## What good looks like

A thesis that gets accepted first time reads like a careful colleague wrote it: two real
sentences on the business, moat evidence with sources, an owner-earnings history with its
warts, a valuation anchor that is an observation rather than a target, a bear case that
takes the fragility findings seriously, and three-to-five triggers the owner would
actually recognise a year from now as the reason to leave.
