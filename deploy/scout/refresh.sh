#!/usr/bin/env bash
# Nightly 02:15 — the rolling freshness sweep (owner-directed 2026-08-05: the box
# fetches data continuously, not just Saturdays, so the picture is complete before
# the weekly sweep). Thesis names are ALWAYS refetched first; the remaining budget
# goes to the stalest cache entries — a name never fetched at all is infinitely
# stale, which is what makes a universe expansion converge over a few nights.
# EDGAR pacing lives in enrich.py (well under SEC fair-use).
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

cd "$SCOUT_DIR"
exec "$PY" enrich.py \
    --rolling "${SCOUT_REFRESH_BUDGET:-1500}" \
    --universe "$SCOUT/universe.csv" \
    --cache "$SCOUT/enrich_cache" \
    --theses-dir "$SCOUT/theses"
