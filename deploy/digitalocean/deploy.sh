#!/usr/bin/env bash
# deploy.sh — ship the code + secrets to a provisioned droplet and install both
# lanes. Run from the desk after provision.sh printed the IP. Idempotent: safe
# to re-run for upgrades (it pulls, re-installs units, never clobbers secrets).
#
#   IP=<ip> BOT_TOKEN=<telegram> CHAT_ID=<owner> GH_PAT=<fine-grained> \
#     [PING_URL=<healthchecks>] bash deploy/digitalocean/deploy.sh
#
# GH_PAT: fine-grained, contents read/write on qpec/invest-ai and
# qpec/invest-ai-state only, NO workflow scope (the containment ladder in
# docs/plans/2026-08-04-distributed-desk-architecture.md §2).
set -euo pipefail

IP="${IP:?set IP to the droplet address}"
BOT_TOKEN="${BOT_TOKEN:?set BOT_TOKEN (Telegram)}"
CHAT_ID="${CHAT_ID:?set CHAT_ID (owner Telegram chat-id)}"
GH_PAT="${GH_PAT:?set GH_PAT (fine-grained, contents-only, two repos)}"
REPO_URL="${REPO_URL:-https://github.com/qpec/invest-ai.git}"
SSH=(ssh -o StrictHostKeyChecking=accept-new "root@$IP")

echo ">>> [1/6] prerequisites + 2GB swapfile (the memory insurance, plan §3)"
"${SSH[@]}" 'set -e
  export DEBIAN_FRONTEND=noninteractive
  printf "DPkg::Lock::Timeout \"600\";\n" > /etc/apt/apt.conf.d/90lock-timeout
  apt-get update -q && apt-get install -y -q git rsync curl
  command -v uv >/dev/null || (curl -LsSf https://astral.sh/uv/install.sh | sh)
  ln -sf ~/.local/bin/uv /usr/local/bin/uv 2>/dev/null || true
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile
    mkswap /swapfile && swapon /swapfile
    grep -q "^/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
  fi'

echo ">>> [2/6] code: clone/pull $REPO_URL -> /opt/stock-agentcy (GitHub is the seam)"
"${SSH[@]}" "set -e
  if [ -d /opt/stock-agentcy/.git ]; then
    git -C /opt/stock-agentcy fetch origin main && git -C /opt/stock-agentcy reset --hard origin/main
  else
    git clone --branch main $REPO_URL /opt/stock-agentcy
  fi"

echo ">>> [3/6] secrets (0600/0640; written before install so nothing runs on REPLACE_ME)"
# The secrets travel on stdin and are handled remote-side by shell BUILTINS
# (read/printf) only — nothing secret ever appears in argv, where any local
# user could read it out of /proc/*/cmdline during the deploy.
printf '%s\n%s\n%s\n' "$BOT_TOKEN" "$CHAT_ID" "$GH_PAT" | "${SSH[@]}" '
  set -e
  IFS= read -r bot; IFS= read -r chat; IFS= read -r pat
  mkdir -p /etc/stock-agentcy
  umask 077
  if [ ! -f /etc/stock-agentcy/agentcy.env ] || grep -q REPLACE_ME /etc/stock-agentcy/agentcy.env; then
    printf "AGENTCY_BOT_TOKEN=%s\nAGENTCY_OWNER_CHAT_ID=%s\nAGENTCY_ETORO_API_KEY=\nAGENTCY_ETORO_USER_KEY=\n" \
      "$bot" "$chat" > /etc/stock-agentcy/agentcy.env
  fi
  chmod 600 /etc/stock-agentcy/agentcy.env
  if [ ! -f /etc/stock-agentcy/scout.env ] || grep -q REPLACE_ME /etc/stock-agentcy/scout.env; then
    { grep -v "^GH_PAT=" /opt/stock-agentcy/deploy/scout/scout.env.example
      printf "GH_PAT=%s\n" "$pat"; } > /etc/stock-agentcy/scout.env
  fi
  chmod 640 /etc/stock-agentcy/scout.env'
# group-owner fix happens after install.sh creates the agentcy user (step 4).

echo ">>> [4/6] agentcy runtime (repo-root install.sh: user, venv, DBs, 12 units)"
"${SSH[@]}" 'bash /opt/stock-agentcy/install.sh < /dev/null'
"${SSH[@]}" 'chown root:agentcy /etc/stock-agentcy/scout.env /etc/stock-agentcy/agentcy.env'
if [ -n "${PING_URL:-}" ]; then
  "${SSH[@]}" "sudo -u agentcy env AGENTCY_STATE_DIR=/var/lib/stock-agentcy \
    /opt/stock-agentcy/.venv/bin/agentcy config set deadman_ping_url '$PING_URL' \
    --reason 'S2 dead-man ping chosen at deploy'"
fi

echo ">>> [5/6] scout lane (the four Saturday units + backup mirror + the seam dirs)"
"${SSH[@]}" 'bash /opt/stock-agentcy/deploy/scout/install.sh'

echo ">>> [6/6] judgement lane (OpenClaw + claude CLI + seam assertions)"
"${SSH[@]}" 'bash /opt/stock-agentcy/deploy/openclaw/install.sh'

cat <<EOF

>>> deployed. Remaining by hand (interactive by nature):
      ssh root@$IP
      sudo -u openclaw claude login                       # owner subscription
      sudo -u openclaw openclaw onboard --install-daemon  # then follow
      less /home/openclaw/.openclaw/SETUP.md              #   the contract
    Seed the bulk data if secdata/ is empty (state repo batches/ README).
    Verify:  ssh root@$IP 'systemctl list-timers "agentcy-*" "scout-*"'
EOF
