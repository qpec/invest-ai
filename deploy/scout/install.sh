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
# repo clones AND theses/committed (both hold FR9 material after ratification),
# the DB backups, and everything credentialed.
mkdir -p "$SCOUT"/{secdata,prices,enrich_cache,reports,site-build} \
         "$SCOUT"/theses/{drafts,committed}
chown -R agentcy:agentcy "$SCOUT"
chmod 755 "$SCOUT" "$SCOUT"/secdata "$SCOUT"/prices "$SCOUT"/enrich_cache \
          "$SCOUT"/reports "$SCOUT"/theses
chmod 750 "$SCOUT"/theses/committed
chown agentcy:scoutwork "$SCOUT"/theses/drafts
chmod 2775 "$SCOUT"/theses/drafts
chmod 750 "$SCOUT"/site-build
# install -d resets mode+owner on existing dirs (mkdir -p would not), and git
# clones into an existing empty dir keep it — so the FR9-bearing clones are
# unreadable to the judgement lane from birth, on fresh and re-run installs.
install -d -m 0700 -o agentcy -g agentcy "$SCOUT"/site-repo "$SCOUT"/state-repo
# Re-run safety: the recursive chown above (and root install.sh's over $STATE)
# strips the scoutwork group from any LIVE weekly spool — re-open them exactly
# as brief.sh does, or a mid-Saturday re-deploy silently breaks the 07:30 job.
for spool in "$SCOUT"/theses/monitor-*; do
    [ -d "$spool" ] || continue
    chgrp -R scoutwork "$spool"
    chmod 2775 "$spool"
    chmod g+rw "$spool"/* 2>/dev/null || true
done
# The SQLite files are the agentcy runtime's alone (§4: "no access"). The
# runtime now creates them 0640 itself; pre-creating them here (an empty file
# IS a valid SQLite DB, and WAL/SHM sidecars inherit its mode) makes the
# openclaw seam assertions non-vacuous on a first boot where no timer has run.
for f in agentcy.db benchmark.db; do
    [ -f "/var/lib/stock-agentcy/$f" ] || \
        install -m 0640 -o agentcy -g agentcy /dev/null "/var/lib/stock-agentcy/$f"
done
chmod o-rwx /var/lib/stock-agentcy/*.db* 2>/dev/null || true
# DB backup copies carry the same data as the DBs — same denial.
[ -d /var/lib/stock-agentcy/backups ] && chmod 700 /var/lib/stock-agentcy/backups

# --- 3. secrets: 0640 root:agentcy — agentcy units read it, openclaw cannot --
if [ ! -f "$ETC/scout.env" ]; then
    install -m 0640 -o root -g agentcy "$CODE/deploy/scout/scout.env.example" \
        "$ETC/scout.env"
    echo ">>> edit $ETC/scout.env: set GH_PAT (fine-grained, contents-only, two repos)."
fi
chown root:agentcy "$ETC/scout.env"; chmod 0640 "$ETC/scout.env"

# --- 4. units ----------------------------------------------------------------
# The five MECHANICAL-lane pairs, enumerated — not a scout-* glob: the
# judgement lane's scout-verdicts unit shares the prefix but belongs to
# deploy/openclaw/install.sh, which installs it after its own prerequisites
# (the openclaw user, the script chmods) exist.
chmod 0755 "$CODE"/deploy/scout/*.sh
MECH_UNITS=(scout-refresh scout-scrape scout-monitor-brief scout-monitor-run
            scout-site scout-backup)
MECH_FILES=()
for u in "${MECH_UNITS[@]}"; do
    install -m 0644 "$CODE/deploy/systemd/$u.service" "$CODE/deploy/systemd/$u.timer" \
        /etc/systemd/system/
    MECH_FILES+=("/etc/systemd/system/$u.service" "/etc/systemd/system/$u.timer")
done
systemd-analyze verify "${MECH_FILES[@]}"
systemctl daemon-reload
systemctl enable --now scout-refresh.timer scout-scrape.timer \
                       scout-monitor-brief.timer scout-monitor-run.timer \
                       scout-site.timer scout-backup.timer

# --- 5. data seed check (the box needs the bulk export to score anything) ----
if [ -z "$(ls -A "$SCOUT/secdata" 2>/dev/null)" ]; then
    cat <<'EOF'
>>> secdata/ is empty. Seed it from the private state repo's batches/
    (see qpec/invest-ai-state README for the restore commands) or copy the
    export from the desk. The monitor refuses to guess: until seeded, runs
    report every metric trigger UNCHECKED.
EOF
fi
if [ ! -f "$SCOUT/universe.csv" ]; then
    # universe.csv is deliberately NOT in the code repo (state never lives
    # there), so a fresh clone cannot supply it — the weekly units read it
    # from the state tree and fail loudly without it.
    echo ">>> universe.csv missing at $SCOUT/universe.csv — seed it with the data."
fi

echo ">>> scout lane installed. Verify: systemctl list-timers 'scout-*'"
echo ">>> next: deploy/openclaw/install.sh for the judgement lane."
