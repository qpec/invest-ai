#!/usr/bin/env bash
# Sat 07:00 — write the week's monitor work order (the judgement questions the
# owner pre-committed at the Gate). Then open the spool directory to the
# judgement lane: the openclaw user must be able to write verdicts.json next to
# the order, and ONLY there — theses/committed/ stays out of its reach (§4 of
# the distributed-desk plan: the Gate is a filesystem fact).
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

cd "$SCOUT_DIR"
"$PY" monitor.py brief --theses-dir "$SCOUT/theses" --as-of "$AS_OF"

SPOOL="$SCOUT/theses/monitor-$AS_OF"
if [ -d "$SPOOL" ]; then
    chgrp -R scoutwork "$SPOOL"
    chmod 2775 "$SPOOL"
    chmod g+rw "$SPOOL"/*
    echo "spool opened to the judgement lane: $SPOOL"
fi
