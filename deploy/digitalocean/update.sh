#!/usr/bin/env bash
# update.sh — pull new code onto a running box and re-assert the units. Run AS ROOT
# ON THE BOX; the usual way is one line from the desk:
#
#     ssh root@<box> 'bash /opt/stock-agentcy/deploy/digitalocean/update.sh'
#
# This is the light path. cloud-init.template.sh builds a box from nothing and
# deploy.sh ships secrets to a fresh one; neither is what you want when the only
# thing that changed is code. Nothing here reads or writes a secret, so it needs no
# environment and leaves /etc/stock-agentcy untouched.
#
# Idempotent, and safe to run while the weekly jobs are idle. The three installers
# are themselves idempotent (they create-if-missing and re-assert permissions), so
# the cost of running all three is a few seconds and the benefit is that a unit
# added in the new commits — like scout-desk.service, added 2026-08-05 — actually
# gets installed. A code pull alone would leave it on disk and unknown to systemd.
set -euo pipefail

CODE=${CODE:-/opt/stock-agentcy}
BRANCH=${BRANCH:-main}

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
[ -d "$CODE/.git" ] || { echo "no clone at $CODE — this box was never deployed"; exit 1; }

echo ">>> [1/4] fetch $BRANCH"
git -C "$CODE" fetch origin "$BRANCH"
OLD=$(git -C "$CODE" rev-parse HEAD)
NEW=$(git -C "$CODE" rev-parse "origin/$BRANCH")
if [ "$OLD" = "$NEW" ]; then
    echo "    already at $(git -C "$CODE" log -1 --format='%h %s')"
else
    git -C "$CODE" log --oneline "$OLD..$NEW" | sed 's/^/    /'
    # Hard reset, not merge: the box is a READER of the seam. Anything edited in
    # place here is either a mistake or an emergency hotfix that belongs in git,
    # and silently keeping it would make the box's behaviour undiagnosable from
    # the repo — the one property the GitHub-as-only-seam design exists to hold.
    git -C "$CODE" reset --hard "origin/$BRANCH"
fi

echo ">>> [2/4] runtime (install.sh)"
bash "$CODE/install.sh" </dev/null

echo ">>> [3/4] mechanical lane (deploy/scout/install.sh)"
bash "$CODE/deploy/scout/install.sh"

echo ">>> [4/4] judgement lane (deploy/openclaw/install.sh)"
# Never fatal: the judgement lane can be un-onboarded (no `claude login` yet) on a
# box whose mechanical half is perfectly healthy. Report and continue — a failure
# here must not leave the timers un-reasserted.
bash "$CODE/deploy/openclaw/install.sh" || echo "    !! judgement lane install returned non-zero (see above)"

echo
echo "== at $(git -C "$CODE" log -1 --format='%h %s') =="
echo "== desk UI: $(systemctl is-active scout-desk.service 2>&1) on 127.0.0.1:${SCOUT_DESK_PORT:-8899} =="
echo "   reach it:  ssh -N -L 8899:127.0.0.1:8899 root@<box>   then open http://127.0.0.1:8899/"
echo "== failed units =="
systemctl --failed --no-pager
