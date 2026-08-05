#!/usr/bin/env bash
# One-shot judgement-lane authenticator (runs as root at boot until it succeeds).
#
# The only step of the whole deploy that is irreducibly the owner's is
# authenticating to Anthropic — no automation may hold the owner's password,
# and no API key is allowed on this box. So the box asks, over the channel the
# owner already has: Telegram. The exchange:
#
#   1. box:   "run `claude setup-token` on your desk, reply here with the token"
#   2. owner: replies with the sk-ant-… token (or 'done' after an SSH login)
#   3. box:   DELETES the message from the chat immediately, installs the token
#             as the openclaw user's credential (root:openclaw 0640 — the same
#             file the Saturday verdicts unit reads), and VERIFIES it with a
#             real claude call before declaring success
#
# The agentcy bot daemon is paused during the exchange (two getUpdates pollers
# conflict) and restarted no matter how this script exits. The Saturday
# verdicts job (scout-verdicts.timer) is installed independently of OpenClaw
# onboarding, so a failed onboard degrades to "the Telegram channel is manual"
# — never to a silent Saturday.
set -u

ENVF=/etc/stock-agentcy/agentcy.env
OENV=/etc/stock-agentcy/openclaw.env
MARKER=/var/lib/stock-agentcy/.openclaw-authed
LOG=/var/log/openclaw-bootstrap.log
touch "$LOG" && chmod 600 "$LOG"
exec >>"$LOG" 2>&1
echo "=== bootstrap-auth $(date -Is) ==="

[ -e "$MARKER" ] && { echo "already authenticated — nothing to do"; exit 0; }

# On a first boot this service is started mid-cloud-init; pausing the bot and
# messaging the owner while the deploy is still collecting and reporting its
# own status would interleave the two conversations. Wait for the boot
# transaction (cloud-final included) to settle; on any later start this
# returns immediately.
systemctl is-system-running --wait >/dev/null 2>&1 || true
BOT_TOKEN=$(sed -n 's/^AGENTCY_BOT_TOKEN=//p' "$ENVF")
CHAT_ID=$(sed -n 's/^AGENTCY_OWNER_CHAT_ID=//p' "$ENVF")
[ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ] || { echo "no bot credentials in $ENVF"; exit 1; }
API="https://api.telegram.org/bot$BOT_TOKEN"

tg() { curl -sS -m 20 "$API/sendMessage" --data-urlencode "chat_id=$CHAT_ID" \
           --data-urlencode "text=$1" >/dev/null; }

OUID=$(id -u openclaw)

# Claude as the openclaw user. The token travels via the env file sourced
# INSIDE the child shell — never through argv, which any local user can read.
claude_as_openclaw() { # $1 = prompt
    runuser -u openclaw -- bash -c '
        set -a; [ -f /etc/stock-agentcy/openclaw.env ] && . /etc/stock-agentcy/openclaw.env; set +a
        export HOME=/home/openclaw
        exec claude -p "$1" --model claude-opus-5' _ "$1" 2>&1
}

verify_auth() {
    local out
    out=$(claude_as_openclaw "Reply with exactly: ok" | tail -3)
    case "$out" in *ok*) echo "auth verified"; return 0 ;; esac
    echo "verify failed: $out"
    VERIFY_TAIL="$out"
    return 1
}

finish_up() { # runs after verified auth: marker, onboard attempt, report
    touch "$MARKER"
    if runuser -u openclaw -- env \
         "XDG_RUNTIME_DIR=/run/user/$OUID" \
         "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$OUID/bus" \
         bash -c 'set -a; [ -f /etc/stock-agentcy/openclaw.env ] && . /etc/stock-agentcy/openclaw.env; set +a
                  export HOME=/home/openclaw
                  exec openclaw onboard --install-daemon' </dev/null; then
        tg "Judgement lane is live: auth verified, OpenClaw daemon onboarded. The Saturday 07:30 verdicts job was already scheduled. Configure the Telegram channel + model pin per SETUP.md when you want the interactive desk."
    else
        tg "Auth verified and the Saturday 07:30 verdicts job is live (it drives claude directly). OpenClaw's own onboarding needs a manual pass when you next SSH in — see /home/openclaw/.openclaw/SETUP.md. Nothing else is blocked."
    fi
}

# ---- the exchange -----------------------------------------------------------
WAS_ACTIVE=0
systemctl is-active --quiet agentcy-bot.service && WAS_ACTIVE=1
[ "$WAS_ACTIVE" -eq 1 ] && systemctl stop agentcy-bot.service
trap '[ "$WAS_ACTIVE" -eq 1 ] && systemctl start agentcy-bot.service || true' EXIT

# A login done over SSH before this script ran needs no exchange at all.
if verify_auth; then finish_up; exit 0; fi

tg "Invest AI box: the judgement lane needs your Claude subscription (one-time).
On your desk: run \`claude setup-token\`, sign in when the browser opens, and reply HERE with the sk-ant-… token it prints. I delete your message immediately after reading it.
(Alternative: SSH in, \`sudo -u openclaw claude login\`, then reply: done)"

# Skip everything sent before this announcement — a token aimed at an earlier
# message may have been consumed by the bot daemon and cannot be trusted fresh.
OFFSET=$(curl -sS -m 20 "$API/getUpdates" --data-urlencode offset=-1 --data-urlencode timeout=0 \
    | python3 -c 'import json,sys; u=json.load(sys.stdin).get("result",[]); print(u[-1]["update_id"]+1 if u else 0)')

DEADLINE=$(( $(date +%s) + 7*24*3600 ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    RESP=$(curl -sS -m 70 "$API/getUpdates" --data-urlencode timeout=50 \
               --data-urlencode "offset=$OFFSET") || { sleep 10; continue; }
    while IFS=$'\t' read -r UPD MSGID CHAT TEXT; do
        [ -n "$UPD" ] || continue
        OFFSET=$((UPD + 1))
        [ "$CHAT" = "$CHAT_ID" ] || continue
        TEXT=$(printf '%s' "$TEXT" | tr -d '[:space:]')
        case "$TEXT" in
            sk-ant-*)
                # the token must not linger in the chat, whatever happens next
                curl -sS -m 20 "$API/deleteMessage" --data-urlencode "chat_id=$CHAT" \
                    --data-urlencode "message_id=$MSGID" >/dev/null
                umask 077
                printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TEXT" > "$OENV"
                chown root:openclaw "$OENV" && chmod 640 "$OENV"
                if verify_auth; then finish_up; exit 0; fi
                rm -f "$OENV"
                tg "Token received (and deleted from the chat) but verification failed: ${VERIFY_TAIL:-no output}. Generate a fresh one with \`claude setup-token\` and reply again."
                ;;
            done|Done|DONE)
                if verify_auth; then finish_up; exit 0; fi
                tg "I don't see a working login for the openclaw user yet (${VERIFY_TAIL:-no output}). Use \`sudo -u openclaw claude login\` over SSH, or reply with a setup-token."
                ;;
            *)
                tg "Waiting for the judgement-lane credential: reply with the sk-ant-… token from \`claude setup-token\`, or 'done' after an SSH login."
                ;;
        esac
    done < <(printf '%s' "$RESP" | python3 -c '
import json, sys
for u in json.load(sys.stdin).get("result", []):
    m = u.get("message") or {}
    print("%s\t%s\t%s\t%s" % (u["update_id"], m.get("message_id", ""),
                              (m.get("chat") or {}).get("id", ""),
                              (m.get("text") or "").replace("\t", " ").replace("\n", " ")))')
done

tg "Judgement-lane auth window (7 days) expired without a credential. Re-run: systemctl start openclaw-bootstrap — or SSH: sudo -u openclaw claude login"
exit 1
