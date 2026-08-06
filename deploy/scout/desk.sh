#!/usr/bin/env bash
# The production desk UI: real data, actions live, bound to loopback on the box.
# Reached over an SSH tunnel (owner decision 2026-08-05) — never a public port:
#
#     ssh -N -L 8899:127.0.0.1:8899 root@<box>      # then open http://127.0.0.1:8899/
#
# The build lands in a scratch directory under the scout state tree, NEVER in the
# repo's docs/ — a served build carries a live capability token and docs/ is what
# GitHub Pages publishes (webapp.py refuses that path outright, this is the belt).
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

# The served build embeds a live capability token AND the owner's desk notes. $SCOUT is
# world-traversable (the judgement lane reads caches from it), so the build directory
# must not be: 0700, and every file inside it private.
umask 077
install -d -m 0700 "$SCOUT/desk-ui"

cd "$SCOUT_DIR"
exec "$PY" webapp.py \
    --serve "${SCOUT_DESK_PORT:-8899}" \
    --sec-data "$SCOUT/secdata" \
    --enrich-cache "$SCOUT/enrich_cache" \
    --theses-dir "$SCOUT/theses" \
    --universe "$SCOUT/universe.csv" \
    ${SCOUT_PRICES:+--prices "$SCOUT_PRICES"} \
    --out-dir "$SCOUT/desk-ui"
