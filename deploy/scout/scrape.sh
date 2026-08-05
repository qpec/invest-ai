#!/usr/bin/env bash
# Sat 06:00 — refresh the tier-2 EDGAR enrichment cache for every name the desk
# holds or is drafting (fill-only-missing, paced, cache-first: enrich.py's own
# discipline). NFR1: if this fails, the 12:00 monitor still runs on the last
# good cache and the report says what is stale — a failed scrape alerts but
# never blocks Saturday.
#
# Deliberately NOT here: the bulk SEC export regen and the universe refresh are
# the quarterly desk ritual (the export is republished quarterly; there is no
# downloader in this repo, on purpose — the box only refreshes what the weekly
# monitor actually tests).
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

SYMBOLS="$(thesis_symbols)"
if [ -z "$SYMBOLS" ]; then
    echo "no committed or draft theses — nothing to refresh"
    exit 0
fi

cd "$SCOUT_DIR"
exec "$PY" enrich.py \
    --sec-data "$SCOUT/secdata" \
    --symbols "$SYMBOLS" \
    --cache "$SCOUT/enrich_cache" \
    --universe "$SCOUT/universe.csv" \
    ${SCOUT_PRICES:+--prices "$SCOUT_PRICES"} \
    --as-of "$AS_OF"
