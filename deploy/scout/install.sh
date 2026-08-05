#!/usr/bin/env bash
# install.sh (scout lane) — the mechanical half of the distributed desk
# (docs/plans/2026-08-04-distributed-desk-architecture.md §3, §7 step 4).
# Run as root, AFTER the repo-root install.sh (which owns the agentcy user,
# the venv and the base state tree). Idempotent.
set -euo pipefail

CODE=/opt/stock-agentcy
SCOUT=/var/lib/stock-agentcy/scout
ETC=/etc/stock-agentcy

# --- 1. the shared-work group: agentcy hands spool dirs to it, openclaw joins
#        it at its own install. Nothing else ever does. ------------------------
getent group scoutwork >/dev/null || groupadd --system scoutwork
id -nG agentcy | grep -qw scoutwork || usermod -aG scoutwork agentcy

# --- 2. state tree + the §4 permission seam ----------------------------------
# Writable by the judgement lane: theses/drafts and the per-week monitor spool
# (opened by brief.sh). Readable only: caches and reports. Invisible: the two
# repo clones (state-repo holds FR9 material) and everything credentialed.
mkdir -p "$SCOUT"/{secdata,prices,enrich_cache,reports,site-build} \
         "$SCOUT"/theses/{drafts,committed}
chown -R agentcy:agentcy "$SCOUT"
chmod 755 "$SCOUT" "$SCOUT"/secdata "$SCOUT"/prices "$SCOUT"/enrich_cache \
          "$SCOUT"/reports "$SCOUT"/theses "$SCOUT"/theses/committed
chown agentcy:scoutwork "$SCOUT"/theses/drafts
chmod 2775 "$SCOUT"/theses/drafts
chmod 750 "$SCOUT"/site-build
# The SQLite files are the agentcy runtime's alone — the judgement lane gets
# no read on them (§4: "no access to the SQLite files").
chmod o-rwx /var/lib/stock-agentcy/*.db* 2>/dev/null || true

# --- 3. secrets: 0640 root:agentcy — agentcy units read it, openclaw cannot --
if [ ! -f "$ETC/scout.env" ]; then
    install -m 0640 -o root -g agentcy "$CODE/deploy/scout/scout.env.example" \
        "$ETC/scout.env"
    echo ">>> edit $ETC/scout.env: set GH_PAT (fine-grained, contents-only, two repos)."
fi
chown root:agentcy "$ETC/scout.env"; chmod 0640 "$ETC/scout.env"

# --- 4. units ----------------------------------------------------------------
chmod 0755 "$CODE"/deploy/scout/*.sh
install -m 0644 "$CODE"/deploy/systemd/scout-*.service \
                "$CODE"/deploy/systemd/scout-*.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/scout-*.service /etc/systemd/system/scout-*.timer
systemctl daemon-reload
systemctl enable --now scout-scrape.timer scout-monitor-brief.timer \
                       scout-monitor-run.timer scout-site.timer scout-backup.timer

# --- 5. data seed check (the box needs the bulk export to score anything) ----
if [ -z "$(ls -A "$SCOUT/secdata" 2>/dev/null)" ]; then
    cat <<'EOF'
>>> secdata/ is empty. Seed it from the private state repo's batches/
    (see qpec/invest-ai-state README for the restore commands) or copy the
    export from the desk. The monitor refuses to guess: until seeded, runs
    report every metric trigger UNCHECKED.
EOF
fi

echo ">>> scout lane installed. Verify: systemctl list-timers 'scout-*'"
echo ">>> next: deploy/openclaw/install.sh for the judgement lane."
