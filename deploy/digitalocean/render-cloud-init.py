#!/usr/bin/env python3
"""Render cloud-init.template.sh into the user_data for a fresh box.

    export TG_TOKEN=... CHAT_ID=... GH_PAT=... CLAUDE_OAT=...
    python deploy/digitalocean/render-cloud-init.py > /tmp/user-data.sh

The template is committed with `__PLACEHOLDER__` markers and this script fills them
from the environment. The rendered output holds four live credentials, so it is
written to stdout and never to the repo — pipe it straight into the droplet-create
call and delete it. `.gitignore` does not protect a file somebody redirects into the
worktree by accident; not having a default output path does.

Every placeholder must be supplied. A blank one would install an empty credential
and the box would come up *looking* deployed while the Telegram letter, the state
push or the judgement lane silently did nothing — the failure mode this whole deploy
is instrumented to prevent.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).with_name("cloud-init.template.sh")

# placeholder -> environment variable
FIELDS = {
    "__TG_TOKEN__": "TG_TOKEN",      # Telegram bot token (the outward report)
    "__CHAT_ID__": "CHAT_ID",        # owner's Telegram chat id
    "__GH_PAT__": "GH_PAT",          # fine-grained, contents-only, two repos
    "__CLAUDE_OAT__": "CLAUDE_OAT",  # `claude setup-token` — subscription, NOT an API key
}


def main() -> int:
    text = TEMPLATE.read_text(encoding="utf-8")
    missing = [env for env in FIELDS.values() if not os.environ.get(env, "").strip()]
    if missing:
        print(f"missing: {', '.join(missing)}", file=sys.stderr)
        return 2

    for placeholder, env in FIELDS.items():
        if placeholder not in text:
            print(f"{TEMPLATE.name} no longer contains {placeholder}", file=sys.stderr)
            return 2
        text = text.replace(placeholder, os.environ[env].strip())

    # Catch a placeholder added to the template but not to FIELDS, which would
    # otherwise ship a literal __SOMETHING__ into a credential file — a box that
    # boots, reports OK, and is authenticated to nothing.
    leftovers = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", text)))
    if leftovers:
        print(f"unrendered placeholders: {leftovers}", file=sys.stderr)
        return 2

    if len(text.encode()) >= 65536:
        print("user_data exceeds DigitalOcean's 64KiB limit", file=sys.stderr)
        return 2

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
