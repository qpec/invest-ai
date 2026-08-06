#!/usr/bin/env bash
# The §3.6 weekly price grid, kept current (scout-prices.timer, nightly).
#
# Without this the grid is whatever the box was seeded with, ageing quietly: prices move
# slowly, so a market cap built on a three-month-old close still looks like a market cap.
# pit.PRICE_MAX_AGE_DAYS refuses those outright, which turns a silent wrong number into a
# visibly absent one — this job is what keeps the number present instead.
#
# Thesis names lead the queue and the budget can never cut them: the monitor grades them
# against pre-committed triggers, and a trigger tested on a stale price is worse than one
# reported UNCHECKED.
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

cd "$SCOUT_DIR"
exec "$PY" prices.py refresh \
    --grid "$SCOUT_PRICES" \
    --universe "$SCOUT/universe.csv" \
    --theses-dir "$SCOUT/theses" \
    --budget "${SCOUT_PRICES_BUDGET:-800}"
