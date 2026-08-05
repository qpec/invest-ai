#!/usr/bin/env bash
# Judgement-lane authenticator — short Telegram exchange slices until success.
#
# The only step of the whole deploy that is irreducibly the owner's is
# authenticating to Anthropic — no automation may hold the owner's password,
# and no API key is allowed on this box. So the box asks over the channel the
# owner already has. Because getUpdates is exclusive per bot token, the agentcy
# bot daemon (which also DELIVERS letters and alerts) must pause during an
# exchange — so each slice is bounded at 25 minutes and a timer re-arms the
# service every ~4h until auth succeeds. The daemon is back after every slice,
# on every exit path (ExecStopPost in the unit + the trap here), so the
# owner's normal channel is never down for more than one slice.
#
# The exchange:
#   1. box:   "run `claude setup-token` on your desk, reply here with the token
#              within 25 minutes; I confirm within seconds or you delete it"
#   2. owner: replies with the sk-ant-… token (or 'done' after an SSH login)
#   3. box:   deletes the message (and says so honestly if deletion failed),
#             installs the token root:openclaw 0640, VERIFIES it with a real
#             claude round-trip against a per-run nonce, confirms the Telegram
#             update queue so the restarted daemon can never re-read the token,
#             and only then declares success.
set -u

ENVF=/etc/stock-agentcy/agentcy.env
OENV=/etc/stock-agentcy/openclaw.env
MARKER=/var/lib/stock-agentcy/.openclaw-authed
LOG=/var/log/openclaw-bootstrap.log
SLICE_SECONDS=1500
touch "$LOG" && chmod 600 "$LOG"
exec >>"$LOG" 2>&1
echo "=== bootstrap-auth $(date -Is) ==="

[ -e "$MARKER" ] && { echo "already authenticated — nothing to do"; exit 0; }

# On a first boot this service starts mid-cloud-init; wait for the boot
# transaction (cloud-final's own status reporting included) to settle before
# pausing the bot. Returns immediately on any later start.
systemctl is-system-running --wait >/dev/null 2>&1 || true

BOT_TOKEN=$(sed -n 's/^AGENTCY_BOT_TOKEN=//p' "$ENVF")
CHAT_ID=$(sed -n 's/^AGENTCY_OWNER_CHAT_ID=//p' "$ENVF")
[ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ] || { echo "no bot credentials in $ENVF"; exit 1; }

# The bot token stays out of argv (/proc/*/cmdline is world-readable and the
# long poll runs for most of a slice): each endpoint URL lives in a root-only
# curl config on tmpfs, and only non-secret parameters travel as arguments.
umask 077
CFGDIR=$(mktemp -d /run/openclaw-tg.XXXXXX)
trap 'rm -rf "$CFGDIR"; systemctl start agentcy-bot.service || true' EXIT
for method in sendMessage getUpdates deleteMessage; do
    printf 'url = "https://api.telegram.org/bot%s/%s"\n' "$BOT_TOKEN" "$method" \
        > "$CFGDIR/$method.cfg"
done

tg()      { curl -sS -m 20 -K "$CFGDIR/sendMessage.cfg" \
                --data-urlencode "chat_id=$CHAT_ID" --data-urlencode "text=$1" >/dev/null; }
tg_get()  { curl -sS -m 70 -K "$CFGDIR/getUpdates.cfg" "$@"; }
tg_del()  { curl -sS -m 20 -K "$CFGDIR/deleteMessage.cfg" \
                --data-urlencode "chat_id=$1" --data-urlencode "message_id=$2"; }

OUID=$(id -u openclaw)

# Claude as the openclaw user. The token travels via the env file sourced
# INSIDE the child shell — never through argv.
claude_as_openclaw() { # $1 = prompt
    runuser -u openclaw -- bash -c '
        set -a; [ -f /etc/stock-agentcy/openclaw.env ] && . /etc/stock-agentcy/openclaw.env; set +a
        export HOME=/home/openclaw
        exec claude -p "$1" --model claude-opus-5' _ "$1" 2>&1
}

VERIFY_TAIL=""
verify_auth() {
    # A fixed marker like "ok" is a substring of "token"/"look" and error prose
    # would self-verify; a per-run nonce cannot collide, and the exit status is
    # captured before any pipeline can launder it.
    local nonce out rc
    nonce="agentcy-verify-$(date +%s)-$RANDOM"
    out=$(claude_as_openclaw "Reply with exactly: $nonce"); rc=$?
    case "$out" in
        *"$nonce"*) if [ "$rc" -eq 0 ]; then echo "auth verified"; return 0; fi ;;
    esac
    VERIFY_TAIL=$(printf '%s' "$out" | tail -3)
    echo "verify failed (rc=$rc): $VERIFY_TAIL"
    return 1
}

OFFSET=""
confirm_updates() {
    # Telegram only marks updates confirmed when a LATER offset arrives; exiting
    # without this leaves the token-bearing update queued, and the restarted
    # daemon would re-read the credential into its own stream.
    [ -n "$OFFSET" ] && tg_get --data-urlencode "offset=$OFFSET" \
        --data-urlencode timeout=0 >/dev/null || true
}

finish_up() { # after verified auth: confirm queue, marker, onboard attempt, report
    confirm_updates
    touch "$MARKER"
    if runuser -u openclaw -- env \
         "XDG_RUNTIME_DIR=/run/user/$OUID" \
         "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$OUID/bus" \
         bash -c 'set -a; [ -f /etc/stock-agentcy/openclaw.env ] && . /etc/stock-agentcy/openclaw.env; set +a
                  export HOME=/home/openclaw
                  exec openclaw onboard --install-daemon' </dev/null; then
        tg "Judgement lane is live: auth verified, OpenClaw daemon onboarded. The Saturday 07:30 verdicts job was already scheduled. Configure the Telegram channel + model pin per SETUP.md when you want the interactive desk."
    else
        tg "Auth verified and the Saturday 07:30 verdicts job is live (it drives claude directly). OpenClaw's own onboarding needs a manual pass over SSH — see /home/openclaw/.openclaw/SETUP.md. Nothing else is blocked."
    fi
}

# ---- one exchange slice -----------------------------------------------------
systemctl stop agentcy-bot.service || true

# A login done over SSH before this slice needs no exchange at all.
if verify_auth; then finish_up; exit 0; fi

tg "Invest AI box: the judgement lane needs your Claude subscription (one-time).
On your desk: run \`claude setup-token\`, sign in when the browser opens, and reply HERE with the sk-ant-… token within 25 minutes. I confirm within seconds — if I don't, delete your message yourself and wait for my next prompt (I retry every ~4h).
(Alternative: SSH in, \`sudo -u openclaw claude login\`, then reply: done)"

DEADLINE=$(( $(date +%s) + SLICE_SECONDS ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    ARGS=(--data-urlencode timeout=50)
    [ -n "$OFFSET" ] && ARGS+=(--data-urlencode "offset=$OFFSET")
    RESP=$(tg_get "${ARGS[@]}") || { sleep 10; continue; }
    PARSED=$(printf '%s' "$RESP" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d.get("ok") is True
for u in d.get("result", []):
    m = u.get("message") or {}
    print("%s\t%s\t%s\t%s" % (u["update_id"], m.get("message_id", ""),
                              (m.get("chat") or {}).get("id", ""),
                              (m.get("text") or "").replace("\t", " ").replace("\n", " ")))' \
        2>/dev/null) || { echo "getUpdates returned not-ok — retrying"; sleep 10; continue; }
    while IFS=$'\t' read -r UPD MSGID CHAT TEXT; do
        [ -n "$UPD" ] || continue
        OFFSET=$((UPD + 1))
        [ "$CHAT" = "$CHAT_ID" ] || continue
        TEXT=$(printf '%s' "$TEXT" | tr -d '[:space:]')
        case "$TEXT" in
            sk-ant-*)
                # delete FIRST, unconditionally — chat hygiene is the invariant,
                # and it must be reported honestly, not assumed.
                DEL=$(tg_del "$CHAT" "$MSGID") || DEL=""
                case "$DEL" in
                    *'"ok":true'*) DELETED=1 ;;
                    *) DELETED=0
                       tg "I could NOT delete your token message from this chat — delete it yourself right now." ;;
                esac
                umask 077
                printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TEXT" > "$OENV"
                chown root:openclaw "$OENV" && chmod 640 "$OENV"
                if verify_auth; then finish_up; exit 0; fi
                rm -f "$OENV"
                if [ "$DELETED" -eq 1 ]; then
                    tg "Token received (and deleted from the chat) but verification failed: ${VERIFY_TAIL:-no output}. Generate a fresh one with \`claude setup-token\` and reply again."
                else
                    tg "Verification failed: ${VERIFY_TAIL:-no output}. Generate a fresh token with \`claude setup-token\` and reply again."
                fi
                ;;
            done|Done|DONE)
                if verify_auth; then finish_up; exit 0; fi
                tg "I don't see a working login for the openclaw user yet (${VERIFY_TAIL:-no output}). Use \`sudo -u openclaw claude login\` over SSH, or reply with a setup-token."
                ;;
            *)
                tg "Waiting for the judgement-lane credential: reply with the sk-ant-… token from \`claude setup-token\`, or 'done' after an SSH login."
                ;;
        esac
    done <<< "$PARSED"
done

confirm_updates
echo "slice expired without a credential — the timer re-arms in ~4h"
exit 0
