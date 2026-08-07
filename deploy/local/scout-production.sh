#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-manual}"
case "$MODE" in daily|weekly|manual) ;; *) echo "invalid mode: $MODE" >&2; exit 2;; esac

ENV_FILE="${SCOUT_PRODUCTION_ENV:-/home/openclaw/config/invest-ai-production.env}"
if [ ! -r "$ENV_FILE" ]; then
    echo "production environment is not readable: $ENV_FILE" >&2
    exit 2
fi
# shellcheck source=/dev/null
. "$ENV_FILE"

: "${SCOUT_REPO:?set SCOUT_REPO}"
: "${SCOUT_DB_DIR:?set SCOUT_DB_DIR}"
: "${SCOUT_ARTIFACT_ROOT:?set SCOUT_ARTIFACT_ROOT}"
: "${SCOUT_SEC_DATA:?set SCOUT_SEC_DATA}"
: "${SCOUT_PRICE_GRID:?set SCOUT_PRICE_GRID}"
: "${SCOUT_UNIVERSE:?set SCOUT_UNIVERSE}"
: "${SCOUT_ENRICH_CACHE:?set SCOUT_ENRICH_CACHE}"
: "${SCOUT_THESES_DIR:?set SCOUT_THESES_DIR}"
: "${SCOUT_REPORTS_DIR:?set SCOUT_REPORTS_DIR}"
: "${SCOUT_SITE_REPO:?set SCOUT_SITE_REPO}"
: "${SCOUT_SITE_CHECKOUT:?set SCOUT_SITE_CHECKOUT}"
: "${SCOUT_GIT_ASKPASS:?set SCOUT_GIT_ASKPASS}"

mkdir -p "$SCOUT_ARTIFACT_ROOT/locks" "$SCOUT_ARTIFACT_ROOT/runs"
exec 9>"$SCOUT_ARTIFACT_ROOT/locks/production.lock"
if ! flock -n 9; then
    echo "another production run owns the lock" >&2
    exit 75
fi

RUN_ID="run-$(date -u +%Y%m%dT%H%M%SZ)-$MODE"
PY="${SCOUT_PYTHON:-$SCOUT_REPO/.venv/bin/python}"

"$PY" "$SCOUT_REPO/stock-scout/production.py" run \
    --mode "$MODE" --run-id "$RUN_ID" --db-dir "$SCOUT_DB_DIR" \
    --repo "$SCOUT_REPO" --artifact-root "$SCOUT_ARTIFACT_ROOT/runs" \
    --sec-data "$SCOUT_SEC_DATA" --price-grid "$SCOUT_PRICE_GRID" \
    --universe "$SCOUT_UNIVERSE" --enrich-cache "$SCOUT_ENRICH_CACHE" \
    --theses-dir "$SCOUT_THESES_DIR" --reports-dir "$SCOUT_REPORTS_DIR" \
    --as-of "$(date -u +%F)" --network-refresh

"$PY" "$SCOUT_REPO/stock-scout/production.py" verify-artifact \
    --run-id "$RUN_ID" --db-dir "$SCOUT_DB_DIR"
ARTIFACT="$SCOUT_ARTIFACT_ROOT/runs/$RUN_ID"
test -f "$ARTIFACT/production-manifest.json"
test -f "$ARTIFACT/docs/index.html"

export GIT_ASKPASS="$SCOUT_GIT_ASKPASS"
export GIT_TERMINAL_PROMPT=0
if [ ! -d "$SCOUT_SITE_CHECKOUT/.git" ]; then
    git clone "$SCOUT_SITE_REPO" "$SCOUT_SITE_CHECKOUT"
fi
git -C "$SCOUT_SITE_CHECKOUT" fetch origin
git -C "$SCOUT_SITE_CHECKOUT" checkout -B "${SCOUT_SITE_BRANCH:-bot/site}" \
    "origin/${SCOUT_SITE_BRANCH:-bot/site}"
rsync -a --delete "$ARTIFACT/docs/" "$SCOUT_SITE_CHECKOUT/docs/"
install -m 644 "$ARTIFACT/production-manifest.json" \
    "$SCOUT_SITE_CHECKOUT/production-manifest.json"
git -C "$SCOUT_SITE_CHECKOUT" add -A docs production-manifest.json
if ! git -C "$SCOUT_SITE_CHECKOUT" diff --cached --quiet; then
    git -C "$SCOUT_SITE_CHECKOUT" \
        -c user.name=scout-local -c user.email=scout@localhost \
        commit -m "production snapshot $RUN_ID"
    git -C "$SCOUT_SITE_CHECKOUT" push origin "${SCOUT_SITE_BRANCH:-bot/site}"
fi
COMMIT="$(git -C "$SCOUT_SITE_CHECKOUT" rev-parse HEAD)"
"$PY" "$SCOUT_REPO/stock-scout/production.py" mark-published \
    --run-id "$RUN_ID" --commit "$COMMIT" --db-dir "$SCOUT_DB_DIR"
