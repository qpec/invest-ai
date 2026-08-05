#!/usr/bin/env bash
# Sat 07:30 — the judgement lane's weekly beat, OpenClaw-independent: drive the
# claude CLI directly as the openclaw user (§6 of the distributed-desk plan:
# a work order is a file, either harness can execute one). OpenClaw, once
# onboarded, adds the interactive Telegram desk on top; this unit is what
# guarantees the Saturday verdicts regardless.
#
# Containment is the filesystem seam, not the prompt: this user can write only
# theses/drafts/ and the open spool, so the blast radius of a misled agent is
# a bad verdict — which the 12:00 mechanical run validates and labels.
set -euo pipefail

SCOUT=/var/lib/stock-agentcy/scout
AS_OF="$(date +%F)"
SPOOL="$SCOUT/theses/monitor-$AS_OF"

# After= orders this unit behind the brief on a same-boot catch-up, but a slow
# 07:00 brief on a normal Saturday still deserves a short grace, not a skip.
for _ in $(seq 30); do
    [ -f "$SPOOL/WORK-ORDER.md" ] && break
    sleep 10
done
if [ ! -f "$SPOOL/WORK-ORDER.md" ]; then
    echo "no work order at $SPOOL — nothing to judge this week"
    exit 0
fi
if [ -f "$SPOOL/verdicts.json" ]; then
    echo "verdicts already written — not re-running"
    exit 0
fi

PROMPT="Execute the work order at $SPOOL/WORK-ORDER.md exactly: research each
pre-committed question with your web tools and write $SPOOL/verdicts.json
matching the order's schema. Do NOT run the order's final monitor.py command —
on this machine the mechanical lane validates your verdicts at 12:00, and your
user cannot write where that command writes. Writing verdicts.json is the
whole deliverable."

# An explicit tool allowlist, never a blanket permission bypass: the work
# order needs web research plus one JSON file — a shell or unscoped reads
# would let a misled agent go fishing (its own credential file included).
cd "$SCOUT"
claude -p "$PROMPT" --model "${SCOUT_AGENT_MODEL:-claude-opus-5}" \
    --allowedTools "WebSearch,WebFetch,Read(/var/lib/stock-agentcy/scout/**),Write(/var/lib/stock-agentcy/scout/theses/**)"

if [ ! -f "$SPOOL/verdicts.json" ]; then
    echo "agent finished without writing verdicts.json — the monitor will say UNCHECKED" >&2
    exit 1
fi
echo "verdicts written: $SPOOL/verdicts.json"
