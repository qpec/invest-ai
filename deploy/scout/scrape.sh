#!/usr/bin/env bash
# Sat 06:00 — Saturday's final freshness pass, same engine as the nightly rolling
# refresh: thesis names (committed first, then drafts) are ALWAYS refetched at the
# head of the plan, so the names the 12:00 monitor will test are the newest data on
# the box; the remaining budget tops up the stalest of the rest before the sweep.
# NFR1: if this fails, the 12:00 monitor still runs on the cache and the report
# says what is stale — a failed scrape alerts but never blocks Saturday.
#
# Deliberately NOT here: the bulk SEC export regen and the universe refresh are
# desk rituals (universe.py --sec-merge / the quarterly export), not box jobs.
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

cd "$SCOUT_DIR"
exec "$PY" enrich.py \
    --rolling "${SCOUT_SCRAPE_BUDGET:-800}" \
    --universe "$SCOUT/universe.csv" \
    --cache "$SCOUT/enrich_cache" \
    --theses-dir "$SCOUT/theses"
