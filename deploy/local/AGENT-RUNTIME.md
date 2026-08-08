# OpenClaw on the box — configuration contract

This file is the judgement lane's configuration checklist. The exact config
syntax depends on the installed OpenClaw version (`openclaw --help`,
`openclaw config`); what must be TRUE is fixed by the architecture doc
(`docs/plans/2026-08-04-distributed-desk-architecture.md` §4) and is listed
here. `deploy/openclaw/install.sh` already created the user, the CLIs and the
filesystem seam — and asserted the seam holds.

## 1. Auth — Claude-CLI reuse, nothing else

**The automated path (default):** `openclaw-bootstrap.timer` runs a 25-minute
Telegram exchange slice every ~4h until auth succeeds (bounded slices because
the exchange must pause the agentcy bot — getUpdates is exclusive — and the
letters channel must never be down for long). The bot messages the owner: run
`claude setup-token` on the desk, reply with the `sk-ant-…` token *within the
slice*; the box deletes the message (and says so honestly if it could not),
installs the token at `/etc/stock-agentcy/openclaw.env` (root:openclaw 0640 —
read by `scout-verdicts.service`), verifies it with a real claude round-trip
against a per-run nonce, and confirms the Telegram queue so the restarted bot
can never re-read the credential. Tokens are revocable at the Anthropic
console; rotate by removing `/var/lib/stock-agentcy/.openclaw-authed` and
`systemctl start openclaw-bootstrap`, then replying with a fresh one.

**The manual path** (equivalent, and what the bootstrap's 'done' reply checks):

```
sudo -u openclaw claude login
```

(For any `openclaw …` daemon command, target the user bus — the account is a
system user, so its manager only exists because install.sh enabled lingering:
`sudo -u openclaw XDG_RUNTIME_DIR=/run/user/$(id -u openclaw) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u openclaw)/bus openclaw …`)

The owner's subscription, through the `claude` binary OpenClaw drives as a
subprocess. **No `ANTHROPIC_API_KEY` anywhere on this box** — if a config asks
for one, leave it empty; API-key mode is the path the owner locked out
("run by claude code or openclaw. Not api"). The static `setup-token` route is
the fragile fallback (it broke once, April 2026) — use it only if CLI reuse is
unavailable in your OpenClaw version.

If the login ever expires on the headless box, the failure is the benign one —
the Saturday monitor reports judgement triggers UNCHECKED, loudly, and the
letter says so. Recovery is one line: SSH in, `sudo -u openclaw claude login`,
re-run the job.

## 2. Model — pinned to the best available

Pin the model to `claude-opus-5` (the id in `deskwork.APPROVED_MODELS`).
`monitor.py run` refuses verdicts declared from any other id, so a drifted
config doesn't corrupt a thesis — it just wastes a Saturday.

## 3. Gateway — loopback only, owner only

- Bind the daemon/gateway to `127.0.0.1`; no public port (droplet firewall
  stays: 22 in, 443 out).
- Telegram channel allowlisted to the owner's chat-id only.
- Web UI disabled.

## 4. The Saturday 07:30 verdicts job

**Already live as `scout-verdicts.timer`** (Sat 07:30 Europe/Amsterdam,
`User=openclaw`, driving `claude -p` directly via `deploy/openclaw/verdicts.sh`)
— deliberately independent of OpenClaw, per the plan's §6 symmetry: a work
order is a file, either harness can execute one. If you later prefer OpenClaw's
own cron to run it, disable the timer and schedule the same prompt there —
same beat, after the 07:00 brief and well before the 12:00 mechanical run:

> Look for `/var/lib/stock-agentcy/scout/theses/monitor-<today's date>/WORK-ORDER.md`.
> If it does not exist, reply "no work order this week" and stop.
> If it exists, execute it exactly: research each pre-committed question with
> your own tools (budget per the order), and write `verdicts.json` next to the
> order, matching its schema. Do NOT run the order's final `monitor.py run`
> command — on this box the mechanical lane ingests and validates your
> verdicts at 12:00, and your user has no permission to write where that
> command writes. Writing `verdicts.json` is the whole deliverable.

Thesis *drafting* is deliberately not scheduled (FR14): the owner triggers it
by Telegram ("draft the new top-1%") or a desk session, and ratification is a
human ritual over SSH (`thesis.py ratify`, as the agentcy user — the only
identity that can write `theses/committed/`).

## 5. What this lane can never do (enforced, not requested)

- Commit a thesis — no write on `theses/committed/` (install.sh asserts it).
- Touch portfolio state — no read on the SQLite files.
- Push anywhere — no git credentials exist in this user's reach.
- Fire a trigger — verdicts only *answer questions*; the arithmetic and the
  sticky-broken logic run in the mechanical lane.

Prompt injection from the open web is an assumed input here, not a surprise:
the blast radius is a bad draft or a bad verdict, both of which the mechanical
lane validates, labels, and can only ever turn into "review" or "UNCHECKED" —
never a silent action.
