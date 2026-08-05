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

# The volume must actually be there, or rsync "succeeds" onto the root disk and
# reports protection that does not exist. mountpoint(1) cannot be trusted here:
# ProtectSystem=strict + ReadWritePaths bind-mounts the path inside this unit's
# namespace, so it reads as a mountpoint even when the disk is absent. Comparing
# st_dev with the parent is namespace-safe: equal devices = root-fs decoy.
if [ "$(stat -c %d /mnt/agentcy-backup)" -eq "$(stat -c %d /mnt)" ]; then
    echo "backup volume not mounted at /mnt/agentcy-backup — refusing the decoy" >&2
    exit 1
fi

DEST=/mnt/agentcy-backup/scout
install -d -m 0700 "$DEST"
# enrich_cache is deliberately NOT mirrored (2026-08-05): every entry is a pruned
# EDGAR companyfacts fetch, refetchable in minutes, and at expanded-universe scale
# it would outgrow the 10 GiB volume — crowding out the irreplaceable dirs below.
for d in theses reports; do
    [ -d "$SCOUT/$d" ] || continue
    rsync -a --delete --chmod=D700,F600 "$SCOUT/$d/" "$DEST/$d/"
done
# a stale cache mirror from before this policy must not masquerade as current
rm -rf "$DEST/enrich_cache"
echo "scout backup -> $DEST ($(date -Is))"
