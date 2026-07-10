#!/usr/bin/env bash
# install.sh — one-shot provisioning of the always-on Ubuntu box (tech-arch §1, §11, §12).
# Idempotent where it can be; run as root. Nothing here writes portfolio data.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CODE=/opt/stock-agentcy
STATE=/var/lib/stock-agentcy
ETC=/etc/stock-agentcy
BACKUP=/mnt/agentcy-backup

# --- 1. dedicated no-login user (system unit topology, §1.1) ------------------
id agentcy >/dev/null 2>&1 || useradd --system --home "$STATE" --shell /usr/sbin/nologin agentcy

# --- 2. code at /opt (read-only to the runtime) -------------------------------
mkdir -p "$CODE"
if [ "$REPO" != "$CODE" ]; then cp -a "$REPO/." "$CODE/"; fi
cd "$CODE"

# --- 3. state tree incl. locks/ and the spool/{tmp,events,done,failed} (§1.5) --
mkdir -p /var/lib/stock-agentcy/locks \
         /var/lib/stock-agentcy/spool/tmp \
         /var/lib/stock-agentcy/spool/events \
         /var/lib/stock-agentcy/spool/done \
         /var/lib/stock-agentcy/spool/failed \
         /var/lib/stock-agentcy/archive \
         /var/lib/stock-agentcy/universe \
         /var/lib/stock-agentcy/backups
chown -R agentcy:agentcy "$STATE"

# --- 4. secrets: 0600 EnvironmentFile, exactly two entries (§9) ----------------
mkdir -p "$ETC"
if [ ! -f /etc/stock-agentcy/agentcy.env ]; then
  cat > /etc/stock-agentcy/agentcy.env <<'ENV'
AGENTCY_BOT_TOKEN=REPLACE_ME
AGENTCY_OWNER_CHAT_ID=REPLACE_ME
ENV
  echo ">>> edit /etc/stock-agentcy/agentcy.env with the real bot token and owner chat-id, then re-run."
fi
chmod 600 /etc/stock-agentcy/agentcy.env
chown root:agentcy /etc/stock-agentcy/agentcy.env

# --- 5. the locked venv via uv (pinned interpreter + lockfile, §12.2/§12.3) ----
uv sync --locked
# archive the recovery toolchain on-box (nightly backup syncs it to the second disk, §11.6):
mkdir -p "$STATE"/toolchain/wheelhouse
uv export --format requirements-txt > "$STATE"/toolchain/requirements.lock.txt
uv pip download -r "$STATE"/toolchain/requirements.lock.txt -d "$STATE"/toolchain/wheelhouse
cp "$(command -v uv)" "$STATE"/toolchain/uv
# the pinned python-build-standalone interpreter tarball uv fetched:
cp -a "${UV_PYTHON_INSTALL_DIR:-$HOME/.local/share/uv/python}" "$STATE"/toolchain/python-build-standalone || true
chown -R agentcy:agentcy "$STATE"/toolchain

# --- 6. NFR7 license wall — blocks the install on any violation (§2.2) ---------
"$CODE"/.venv/bin/python "$CODE"/tools/license_gate.py

# --- 7. migrate the DB (forward-only at open) + choose the S2 ping service -----
# `agentcy render --rebuild` opens the DB under the agentcy user, which forces
# open_db+migrate before any `agentcy run <job>` timer fires (the units' ExecStart).
sudo -u agentcy env AGENTCY_STATE_DIR="$STATE" "$CODE"/.venv/bin/agentcy render --rebuild || true
# S0/S1/S3 land as migration-000 bootstrap journal seeds (entries 1-5, contracts §2.1).
# S2's concrete ping service is the one install-time choice (tech-arch §15 S2):
read -r -p "Dead-man ping URL (healthchecks.io-class; blank to leave OFF for now): " PING_URL || true
if [ -n "${PING_URL:-}" ]; then
  sudo -u agentcy env AGENTCY_STATE_DIR="$STATE" \
    "$CODE"/.venv/bin/agentcy config set deadman_ping_url "$PING_URL" \
    --reason "S2 dead-man ping service chosen at install (tech-arch §15)"
fi

# --- 8. archive git repo with the second-disk backup remote (§1.1/§11.6) -------
# `git init /var/lib/stock-agentcy/archive` seeds the archive repo; the backup job
# then `git remote add backup /mnt/agentcy-backup/archive.git` mirrors it (R9).
sudo -u agentcy git -C /var/lib/stock-agentcy/archive rev-parse >/dev/null 2>&1 || {
  sudo -u agentcy git init /var/lib/stock-agentcy/archive
  sudo -u agentcy git -C /var/lib/stock-agentcy/archive config user.name agentcy
  sudo -u agentcy git -C /var/lib/stock-agentcy/archive config user.email agentcy@localhost
}
mkdir -p /mnt/agentcy-backup/archive.git
git init --bare /mnt/agentcy-backup/archive.git 2>/dev/null || true
chown -R agentcy:agentcy /mnt/agentcy-backup
cd /var/lib/stock-agentcy/archive
sudo -u agentcy git remote add backup /mnt/agentcy-backup/archive.git 2>/dev/null || true
cd "$CODE"

# --- 9. install + verify units, enable timers and the daemon (§1, §12.4 step 5)-
install -m 0644 "$CODE"/deploy/systemd/*.service "$CODE"/deploy/systemd/*.timer "$CODE"/deploy/systemd/*.path /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/agentcy-*.service /etc/systemd/system/agentcy-*.timer /etc/systemd/system/agentcy-*.path
systemctl daemon-reload
systemctl enable --now agentcy-bot.service
systemctl enable --now agentcy-daily.timer agentcy-weekly.timer agentcy-quarterly.timer agentcy-backup.timer
systemctl enable --now agentcy-event.path
echo ">>> install complete. Verify: systemctl status 'agentcy-*'  —  runbook: docs/runbook.md"
