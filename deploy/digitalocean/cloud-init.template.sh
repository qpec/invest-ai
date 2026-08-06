#!/bin/bash
# First-boot deploy for the invest-ai box (DigitalOcean cloud-init user_data).
#
# Rendered by deploy/digitalocean/render-cloud-init.py, which substitutes the four
# placeholders below. It exists because the box is deployed from a machine that
# cannot SSH into it: every outcome therefore has to report itself outward — a status
# file pushed to the bot/deploy-log branch, and a Telegram message to the owner.
#
# NOTHING SECRET LIVES IN THIS FILE. The placeholders are filled at render time and the
# rendered copy is passed straight to the DO API, never written to the repo.
LOG=/var/log/invest-ai-deploy.log
RES=/root/deploy-status.txt
touch "$LOG" && chmod 600 "$LOG"
exec >"$LOG" 2>&1
export DEBIAN_FRONTEND=noninteractive HOME=/root
: >"$RES"
note() { echo "$1" >>"$RES"; echo "### $1"; }
run()  { local desc="$1"; shift; if "$@"; then note "OK   $desc"; else note "FAIL $desc"; fi; }

echo "=== invest-ai deploy $(date -Is) ==="

# --- 0. wall off the metadata service from non-root --------------------------
# Cloud-init user_data (THIS script, secrets included) is readable from
# 169.254.169.254 by ANY local process by default — which would hand the PAT and both
# tokens to the judgement-lane user and void the §4 "no credentials" seam.
cat > /etc/systemd/system/metadata-guard.service <<'UNIT'
[Unit]
Description=Block non-root access to the cloud metadata service
After=network-pre.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/iptables -I OUTPUT -d 169.254.169.254 -m owner ! --uid-owner 0 -j REJECT
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now metadata-guard.service
run "metadata service walled off (non-root)" \
    systemctl is-active --quiet metadata-guard.service

# --- 1. base tooling (first-boot apt races apt-daily: timeout + retry) -------
printf 'DPkg::Lock::Timeout "600";\n' > /etc/apt/apt.conf.d/90lock-timeout
apt_ok=1
for attempt in 1 2 3 4 5; do
    if apt-get update -q && apt-get install -y -q git rsync curl; then apt_ok=0; break; fi
    echo "apt attempt $attempt failed; retrying in 30s"; sleep 30
done
[ "$apt_ok" -eq 0 ] && note "OK   apt base (git rsync curl)" \
                    || note "FAIL apt base after 5 attempts"
run "uv" bash -c \
    'command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh;
     ln -sf /root/.local/bin/uv /usr/local/bin/uv; uv --version'
run "timezone Europe/Amsterdam" timedatectl set-timezone Europe/Amsterdam

# --- 2. 2GB swapfile (memory insurance) --------------------------------------
run "swapfile" bash -c \
    '[ -f /swapfile ] || { fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile; };
     swapon /swapfile 2>/dev/null || true;
     grep -q "^/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab'

# --- 3. backup volume --------------------------------------------------------
# Format ONLY a device with no filesystem signature at all: a dirty or unreadable
# device is reported FAIL, never wiped — surviving backups must not be destroyed by
# an installer's guess.
run "backup volume mount" bash -c '
    DEV=/dev/disk/by-id/scsi-0DO_Volume_invest-ai-backup
    [ -b "$DEV" ] || { echo "volume device absent"; exit 1; }
    if ! blkid "$DEV" >/dev/null 2>&1; then
        [ -z "$(wipefs -n "$DEV" 2>/dev/null)" ] || { echo "unrecognised signatures on $DEV"; exit 1; }
        mkfs.ext4 -L agentcy-backup "$DEV"
    fi
    mkdir -p /mnt/agentcy-backup
    grep -q agentcy-backup /etc/fstab || echo "$DEV /mnt/agentcy-backup ext4 defaults,nofail,discard 0 2" >> /etc/fstab
    mount -a
    mountpoint -q /mnt/agentcy-backup'

# --- 4. secrets BEFORE any install ------------------------------------------
mkdir -p /etc/stock-agentcy
umask 077
cat > /etc/stock-agentcy/agentcy.env <<'ENV'
AGENTCY_BOT_TOKEN=__TG_TOKEN__
AGENTCY_OWNER_CHAT_ID=__CHAT_ID__
AGENTCY_ETORO_API_KEY=
AGENTCY_ETORO_USER_KEY=
ENV
chmod 600 /etc/stock-agentcy/agentcy.env
cat > /etc/stock-agentcy/scout.env <<'ENV'
GH_PAT=__GH_PAT__
SCOUT_AGENT_MODEL=claude-opus-5
ENV
chmod 640 /etc/stock-agentcy/scout.env
# The judgement lane's subscription credential (owner-generated via `claude setup-token`).
cat > /etc/stock-agentcy/openclaw.env <<'ENV'
CLAUDE_CODE_OAUTH_TOKEN=__CLAUDE_OAT__
ENV
chmod 600 /etc/stock-agentcy/openclaw.env
umask 022
note "OK   secrets written (0600/0640)"

# --- 5. code from GitHub (the seam) ------------------------------------------
run "clone qpec/invest-ai@main -> /opt/stock-agentcy" \
    git clone --branch main https://github.com/qpec/invest-ai.git /opt/stock-agentcy

# --- 6. the three installers, each reported separately -----------------------
run "agentcy runtime (install.sh)" bash -c \
    'bash /opt/stock-agentcy/install.sh </dev/null'
chown root:agentcy /etc/stock-agentcy/agentcy.env /etc/stock-agentcy/scout.env 2>/dev/null || true
run "scout lane (deploy/scout/install.sh)" \
    bash /opt/stock-agentcy/deploy/scout/install.sh
run "judgement lane (deploy/openclaw/install.sh)" \
    bash /opt/stock-agentcy/deploy/openclaw/install.sh
chown root:openclaw /etc/stock-agentcy/openclaw.env 2>/dev/null || true
chmod 640 /etc/stock-agentcy/openclaw.env 2>/dev/null || true

# --- 7. universe + bulk data -------------------------------------------------
run "universe.csv seed" bash -c '
    curl -fsSL -o /var/lib/stock-agentcy/scout/universe.csv \
        https://raw.githubusercontent.com/qpec/invest-ai/bot/seed/universe.csv \
    && head -1 /var/lib/stock-agentcy/scout/universe.csv | grep -qi symbol \
    && chown agentcy:agentcy /var/lib/stock-agentcy/scout/universe.csv'

printf '#!/bin/sh\necho "$GH_PAT"\n' > /root/.askpass && chmod 700 /root/.askpass
SCOUTD=/var/lib/stock-agentcy/scout
git_pat() { GH_PAT=__GH_PAT__ GIT_ASKPASS=/root/.askpass GIT_TERMINAL_PROMPT=0 git "$@"; }
if git_pat clone --depth 1 https://x-access-token@github.com/qpec/invest-ai-state.git \
     /root/stateseed 2>&1 && [ -d /root/stateseed/batches ]; then
    seed_fail=0
    for t in secdata prices enrich_cache; do
        parts=(/root/stateseed/batches/*/"$t".tar.gz.part-*)
        [ -e "${parts[0]}" ] || { echo "no batch parts for $t"; continue; }
        mkdir -p "$SCOUTD/$t"
        cat "${parts[@]}" | tar xzf - -C "$SCOUTD/$t" || seed_fail=1
    done
    [ -d /root/stateseed/state/theses/drafts ] && {
        mkdir -p "$SCOUTD/theses/drafts"
        cp -a /root/stateseed/state/theses/drafts/. "$SCOUTD/theses/drafts/" || true; }
    rm -rf /root/stateseed
    bash /opt/stock-agentcy/deploy/scout/install.sh >/dev/null 2>&1 || true   # re-assert the seam
    [ "$seed_fail" -eq 0 ] && note "OK   bulk data restored from invest-ai-state" \
                           || note "FAIL bulk data restore (partial — see log)"
else
    rm -rf /root/stateseed
    note "SEED PENDING: invest-ai-state unreachable — weekly jobs degraded until seeded"
fi

# --- 8. status collection (facts, no secrets) --------------------------------
{
    echo
    echo "== desk UI: $(systemctl is-active scout-desk.service 2>&1) "\
"(loopback :${SCOUT_DESK_PORT:-8899}, reach with ssh -N -L 8899:127.0.0.1:8899) =="
    echo "== bot daemon: $(systemctl is-active agentcy-bot.service 2>&1) =="
    echo "== judgement auth: $([ -s /etc/stock-agentcy/openclaw.env ] && echo 'token installed' || echo 'PENDING') =="
    echo
    echo "== enabled timers =="
    systemctl list-timers 'agentcy-*' 'scout-*' --no-pager 2>&1
    echo
    echo "== failed units =="
    systemctl --failed --no-pager 2>&1
    echo "== disk: $(df -h / --output=avail | tail -1 | tr -d ' ') free, swap: $(free -h | awk '/Swap/{print $2}') =="
} >>"$RES"

# --- 9. report outward: deploy-log branch + Telegram -------------------------
rm -rf /root/deploylog && mkdir -p /root/deploylog && cd /root/deploylog
git init -q -b bot/deploy-log . && cp "$RES" status.txt && git add status.txt
git -c user.name=invest-ai-box -c user.email=box@localhost \
    commit -qm "first-boot deploy status $(date -Is)"
GH_PAT=__GH_PAT__ GIT_ASKPASS=/root/.askpass GIT_TERMINAL_PROMPT=0 \
    git push -f https://x-access-token@github.com/qpec/invest-ai.git \
    bot/deploy-log 2>&1 | tail -2
cd / && rm -rf /root/deploylog /root/.askpass

cat > /root/.tgsend <<CFG
url = "https://api.telegram.org/bot__TG_TOKEN__/sendMessage"
CFG
chmod 600 /root/.tgsend
for attempt in 1 2 3; do
    if curl -sS -m 20 -K /root/.tgsend \
        --data-urlencode "chat_id=__CHAT_ID__" \
        --data-urlencode "text=$(printf 'Invest AI box: deploy finished.\n\n%s' "$(head -c 3300 "$RES")")" \
        >/dev/null; then echo "telegram sent"; break; fi
    echo "telegram attempt $attempt failed"; sleep 10
done
rm -f /root/.tgsend

echo "=== deploy done $(date -Is) ==="
