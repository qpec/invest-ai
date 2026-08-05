#!/usr/bin/env bash
# Sat 12:30 — rebuild the desk site and push it to the `bot/site` branch (which
# is all the box's fine-grained PAT can vandalise — never main, never the
# workflows), then push the private state archive (theses + reports: the FR9
# material, which never appears in the site payload — webapp.strip_owner_fields
# is tested for exactly this).
#
# The site branch keeps the repo layout; only docs/index.html and docs/data/
# are generated, so only those are replaced — docs/plans/, the runbook and the
# rest of docs/ ride along untouched from whenever bot/site was last seeded.
set -euo pipefail
. /opt/stock-agentcy/deploy/scout/lib.sh

# Everything this script writes locally (site build, both clones — the state
# clone holds FR9 material) stays private to the agentcy user; the dirs are
# 0700 from install, this covers the files.
umask 077

SITE_REPO_URL="${SCOUT_SITE_REPO:-https://x-access-token@github.com/qpec/invest-ai.git}"
STATE_REPO_URL="${SCOUT_STATE_REPO:-https://x-access-token@github.com/qpec/invest-ai-state.git}"
SITE_BRANCH="${SCOUT_SITE_BRANCH:-bot/site}"

# --- 1. build ---------------------------------------------------------------
cd "$SCOUT_DIR"
"$PY" webapp.py \
    --sec-data "$SCOUT/secdata" \
    --enrich-cache "$SCOUT/enrich_cache" \
    --theses-dir "$SCOUT/theses" \
    --universe "$SCOUT/universe.csv" \
    ${SCOUT_PRICES:+--prices "$SCOUT_PRICES"} \
    --as-of "$AS_OF" \
    --out-dir "$SCOUT/site-build"

# --- 2. site -> bot/site ----------------------------------------------------
# Clone WITHOUT --branch: if bot/site was never seeded, --branch is fatal, while
# a default clone + checkout -B from origin/HEAD seeds the branch from main's
# real history — the only new commit then touches docs/ only, which the box's
# contents-only PAT can push (a rootless orphan commit would re-add the workflow
# files and be rejected).
if [ ! -d "$SCOUT/site-repo/.git" ]; then
    git clone "$SITE_REPO_URL" "$SCOUT/site-repo"
fi
cd "$SCOUT/site-repo"
git fetch origin
git checkout -B "$SITE_BRANCH" "origin/$SITE_BRANCH" 2>/dev/null \
    || git checkout -B "$SITE_BRANCH" origin/HEAD
install -m 644 "$SCOUT/site-build/index.html" docs/index.html
if [ -d "$SCOUT/site-build/data" ]; then
    rsync -a --delete "$SCOUT/site-build/data/" docs/data/
fi
# status --porcelain, not diff --quiet: a brand-new shard file is untracked,
# and diff would read that week as "unchanged".
if [ -z "$(git status --porcelain -- docs)" ]; then
    echo "site unchanged — nothing to push"
else
    git add -A docs
    git -c user.name=scout-box -c user.email=scout@localhost \
        commit -m "desk site $AS_OF"
    push_with_retry origin "$SITE_BRANCH"
fi

# --- 3. state archive -> private repo ---------------------------------------
if [ ! -d "$SCOUT/state-repo/.git" ]; then
    git clone "$STATE_REPO_URL" "$SCOUT/state-repo"
fi
cd "$SCOUT/state-repo"
# The architecture plan seeds the state repo FROM the box, so an empty remote
# (unborn main) is a legitimate first-run state, not an error.
git fetch origin
if git show-ref -q refs/remotes/origin/main; then
    git checkout -B main origin/main
else
    git checkout -B main
fi
mkdir -p state
rsync -a --delete --exclude '*.tmp' "$SCOUT/theses/"  state/theses/
rsync -a --delete --exclude '*.tmp' "$SCOUT/reports/" state/reports/
# The owner elected to keep the state repo PUBLIC (2026-08-05). FR9 still
# binds: conviction and circle-of-competence are the owner's alone and never
# reach a public surface — same rule, same fields as webapp.strip_owner_fields
# on the site. The archived copies here are redacted; the full-fidelity
# committed theses live on the box and its nightly backup volume.
"$PY" - state/theses/committed <<'STRIP'
import json, pathlib, sys
OWNER_ONLY = ("conviction", "circle_of_competence")
for p in pathlib.Path(sys.argv[1]).glob("*.json"):
    doc = json.loads(p.read_text(encoding="utf-8"))
    if any(k in doc for k in OWNER_ONLY):
        for k in OWNER_ONLY:
            doc.pop(k, None)
        p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
STRIP
if git status --porcelain | grep -q .; then
    git add state
    git -c user.name=scout-box -c user.email=scout@localhost \
        commit -m "monitor state $AS_OF"
    push_with_retry -u origin main
else
    echo "state archive unchanged"
fi
