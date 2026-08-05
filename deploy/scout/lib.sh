# Shared paths + helpers for the scout units (distributed-desk plan §3).
# Sourced by the scout-* scripts; never executed directly.
#
# The mechanical lane's contract: these scripts do arithmetic, file moves and
# git pushes. No LLM runs here, ever — the judgement lane is the openclaw user,
# and it cannot even read this lane's credentials (scout.env is root:agentcy 0640).

CODE=/opt/stock-agentcy
SCOUT_DIR="$CODE/stock-scout"
PY="$CODE/.venv/bin/python"
SCOUT=/var/lib/stock-agentcy/scout
AS_OF="$(date +%F)"

# Git, without ever storing the PAT: the remote embeds only the username, and
# askpass answers the password prompt from the environment of THIS process.
export GIT_ASKPASS="$CODE/deploy/scout/git-askpass.sh"
export GIT_TERMINAL_PROMPT=0

# Symbols the desk actually holds or is drafting — the weekly refresh scope.
# (The full-universe export regen is the quarterly desk ritual, not a box job.)
thesis_symbols() {
    local out=""
    local f
    for f in "$SCOUT"/theses/committed/*.json "$SCOUT"/theses/drafts/*.json; do
        [ -e "$f" ] || continue
        out="$out,$(basename "$f" .json)"
    done
    [ -n "${SCOUT_EXTRA_SYMBOLS:-}" ] && out="$out,$SCOUT_EXTRA_SYMBOLS"
    printf '%s' "${out#,}"
}

# git push with the deploy doc's retry ladder (network errors only — an auth
# or permission failure repeats identically and should alert, not loop).
push_with_retry() {
    local delay
    for delay in 0 2 4 8 16; do
        sleep "$delay"
        if git push "$@"; then return 0; fi
    done
    echo "git push $* failed after 5 attempts" >&2
    return 1
}
