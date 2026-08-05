#!/usr/bin/env bash
# Nightly 03:45 — mirror the scout dirs the architecture doc names (§5:
# enrich_cache, theses, reports) to the second disk. A unit-level extension of
# the ratified backup arrangement: the agentcy backup job itself stays
# untouched (it owns the DBs, the archive mirror and the toolchain — different
# invariants, different code, deliberately not entangled with a shell rsync).
# Not mirrored: secdata/prices (re-downloadable bulk), site-build and the two
# git clones (regenerable), all of which also ride in the state repo's seed
# batches.
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

DEST=/mnt/agentcy-backup/scout
mkdir -p "$DEST"
for d in enrich_cache theses reports; do
    [ -d "$SCOUT/$d" ] || continue
    rsync -a --delete "$SCOUT/$d/" "$DEST/$d/"
done
echo "scout backup -> $DEST ($(date -Is))"
