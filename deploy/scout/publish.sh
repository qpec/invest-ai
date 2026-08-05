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

SITE_REPO_URL="${SCOUT_SITE_REPO:-https://x-access-token@github.com/qpec/invest-ai.git}"
STATE_REPO_URL="${SCOUT_STATE_REPO:-https://x-access-token@github.com/qpec/invest-ai-state.git}"
SITE_BRANCH="${SCOUT_SITE_BRANCH:-bot/site}"

# --- 1. build ---------------------------------------------------------------
cd "$SCOUT_DIR"
"$PY" webapp.py \
    --sec-data "$SCOUT/secdata" \
    --enrich-cache "$SCOUT/enrich_cache" \
    --theses-dir "$SCOUT/theses" \
    --universe universe.csv \
    ${SCOUT_PRICES:+--prices "$SCOUT_PRICES"} \
    --as-of "$AS_OF" \
    --out-dir "$SCOUT/site-build"

# --- 2. site -> bot/site ----------------------------------------------------
if [ ! -d "$SCOUT/site-repo/.git" ]; then
    git clone --branch "$SITE_BRANCH" --single-branch "$SITE_REPO_URL" "$SCOUT/site-repo"
fi
cd "$SCOUT/site-repo"
git fetch origin "$SITE_BRANCH"
git checkout -B "$SITE_BRANCH" "origin/$SITE_BRANCH"
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
git fetch origin && git checkout -B main origin/main
mkdir -p state
rsync -a --delete --exclude '*.tmp' "$SCOUT/theses/"  state/theses/
rsync -a --delete --exclude '*.tmp' "$SCOUT/reports/" state/reports/
if git status --porcelain | grep -q .; then
    git add state
    git -c user.name=scout-box -c user.email=scout@localhost \
        commit -m "monitor state $AS_OF"
    push_with_retry origin main
else
    echo "state archive unchanged"
fi
