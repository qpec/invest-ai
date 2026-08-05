#!/usr/bin/env bash
# Sat 12:00 — the mechanical monitor run. Metric triggers are pure arithmetic
# off the export + enrichment cache (cache-first: no network needed); the
# agent's verdicts.json is ingested IF the judgement lane delivered it by now.
#
# Missing verdicts never block: monitor.py reports those triggers UNCHECKED,
# loudly, and the letter says so (a dead OpenClaw degrades the week, it does
# not silence it). When verdicts ARE present, the owner's best-available model
# rule binds: on this box no harness transcript is visible to systemd, so the
# model is declared from the pinned config — and the report carries the honest
# label "declared, NOT independently verified" (the degraded-but-labelled path
# the architecture doc accepts; OpenClaw's own config pins the same id).
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

VERDICTS="$SCOUT/theses/monitor-$AS_OF/verdicts.json"
EXTRA=()
if [ -f "$VERDICTS" ]; then
    EXTRA=(--verdicts "$VERDICTS" --model "${SCOUT_AGENT_MODEL:?set in scout.env}")
else
    echo "no verdicts at $VERDICTS — judgement triggers will be UNCHECKED (loud)"
fi

cd "$SCOUT_DIR"
exec "$PY" monitor.py run \
    --sec-data "$SCOUT/secdata" \
    --theses-dir "$SCOUT/theses" \
    --reports-dir "$SCOUT/reports" \
    --enrich-cache "$SCOUT/enrich_cache" \
    --universe "$SCOUT/universe.csv" \
    ${SCOUT_PRICES:+--prices "$SCOUT_PRICES"} \
    --as-of "$AS_OF" \
    "${EXTRA[@]}"
