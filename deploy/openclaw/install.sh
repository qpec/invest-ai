#!/usr/bin/env bash
# install.sh (judgement lane) — OpenClaw + the claude CLI, as a dedicated user
# whose reach is exactly §4 of the distributed-desk plan: write theses/drafts/
# and the weekly monitor spool, read the rest of the scout tree, and NOTHING
# else — no committed theses, no SQLite, no git credentials. The seam is
# asserted at the end of this script; a failed assertion fails the install.
#
# Run as root, after deploy/scout/install.sh. Two steps stay interactive by
# nature and are printed at the end: `claude login` (the owner's subscription —
# Claude-CLI reuse is the supported auth path; no API key ever lands on this
# box) and the OpenClaw onboarding.
set -euo pipefail

SCOUT=/var/lib/stock-agentcy/scout

# --- 1. the user -------------------------------------------------------------
id openclaw >/dev/null 2>&1 || \
    useradd --system --create-home --home-dir /home/openclaw \
            --shell /usr/sbin/nologin openclaw
usermod -aG scoutwork openclaw
# The daemon installs as a systemd USER service; without lingering a system
# account has no user manager, no /run/user/<uid>, no session bus — onboarding
# would fail and nothing would start at boot. enable-linger also starts
# user@<uid> right now, so the bus exists for the onboarding step below.
loginctl enable-linger openclaw

# --- 2. node 22 + the two CLIs ----------------------------------------------
# First-boot apt races the image's own apt-daily/unattended-upgrades; a held
# dpkg lock must wait, not instantly fail the whole judgement lane.
printf 'DPkg::Lock::Timeout "600";\n' > /etc/apt/apt.conf.d/90lock-timeout
if ! command -v node >/dev/null || [ "$(node -e 'console.log(+process.versions.node.split(".")[0])')" -lt 22 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -o DPkg::Lock::Timeout=600 nodejs
fi
npm install -g openclaw @anthropic-ai/claude-code

# --- 3. config template (only if absent — never clobber a tuned config) ------
install -d -o openclaw -g openclaw -m 0750 /home/openclaw/.openclaw
if [ ! -f /home/openclaw/.openclaw/SETUP.md ]; then
    install -o openclaw -g openclaw -m 0640 \
        "$(dirname "$0")/SETUP.md" /home/openclaw/.openclaw/SETUP.md
fi

# --- 4. assert the seam (§4) — the Gate as a filesystem fact ------------------
# Every denial check first asserts (as root) that its target EXISTS: a check
# against a file that is not there passes for the wrong reason, and a seam that
# was never exercised is a seam assumed, not asserted.
fail=0
check() { # check <expect: ok|no> <description> <cmd...>
    local expect="$1" desc="$2"; shift 2
    if runuser -u openclaw -- "$@" >/dev/null 2>&1; then local got=ok; else local got=no; fi
    if [ "$got" = "$expect" ]; then
        echo "  seam OK   $desc"
    else
        echo "  seam FAIL $desc (expected $expect, got $got)"; fail=1
    fi
}
exists() { # exists <path> — a missing target makes the matching denial vacuous
    [ -e "$1" ] || { echo "  seam FAIL $1 absent — cannot assert against it"; fail=1; return 1; }
}
tmp="$SCOUT/theses/drafts/.seamcheck-$$"
check ok "can write theses/drafts/"            touch "$tmp"
rm -f "$tmp"
check no "cannot write theses/committed/"      touch "$SCOUT/theses/committed/.seamcheck-$$"
rm -f "$SCOUT/theses/committed/.seamcheck-$$" 2>/dev/null || true
check no "cannot list theses/committed/ (FR9)" ls "$SCOUT/theses/committed"
check ok "can read the enrichment cache"       ls "$SCOUT/enrich_cache"
check ok "can read reports/"                   ls "$SCOUT/reports"
exists /etc/stock-agentcy/scout.env && \
    check no "cannot read scout.env (the PAT)"     cat /etc/stock-agentcy/scout.env
exists /etc/stock-agentcy/agentcy.env && \
    check no "cannot read agentcy.env (bot token)" cat /etc/stock-agentcy/agentcy.env
for db in agentcy.db benchmark.db; do   # by name: a zero-match glob asserts nothing
    exists "/var/lib/stock-agentcy/$db" && \
        check no "cannot read $db"             cat "/var/lib/stock-agentcy/$db"
done
for clone in site-repo state-repo; do   # state-repo holds FR9 after ratification
    exists "$SCOUT/$clone" && \
        check no "cannot list $clone/"         ls "$SCOUT/$clone"
done
[ "$fail" -eq 0 ] || { echo ">>> SEAM BROKEN — fix permissions before going live."; exit 1; }

cat <<EOF
>>> judgement lane installed and the seam holds. Two interactive steps remain
    (as the openclaw user; see /home/openclaw/.openclaw/SETUP.md). The daemon
    is a systemd USER service, so point the commands at openclaw's own user
    bus (lingering is already enabled):
      1. sudo -u openclaw claude login          # owner subscription, no API key
      2. sudo -u openclaw XDG_RUNTIME_DIR=/run/user/$(id -u openclaw) \\
           DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u openclaw)/bus \\
           openclaw onboard --install-daemon
    Then configure per SETUP.md: model pin, Telegram binding, loopback-only
    gateway, and the Saturday 07:30 verdicts job.
EOF
