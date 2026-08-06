# Deploying stock-agentcy to DigitalOcean

The system was designed for "an always-on Ubuntu box." A DigitalOcean Droplet running **Ubuntu 24.04 LTS** is exactly that target — so this is the intended production deployment, not a workaround.

## What you must provide (hard blockers)

| # | Item | Why | How to get it |
|---|---|---|---|
| 1 | **DigitalOcean API token** | Provision the droplet + volume | DO dashboard → API → Generate New Token (read+write). Then `doctl auth init`. |
| 2 | **Telegram bot token** | The system's *only* interface | Message **@BotFather** on Telegram → `/newbot` → copy the token. |
| 3 | **Your Telegram chat-id** | Locks the bot to you | Message your new bot once, then we read it from `getUpdates` (or use @userinfobot). |
| 4 | **An SSH key in your DO account** | So we can log into the droplet | `doctl compute ssh-key import mykey --public-key-file ~/.ssh/id_ed25519.pub` |
| 5 | **Fine-grained GitHub PAT** | The box pushes the site (`bot/site`) + the private state archive | GitHub → Settings → Developer settings → Fine-grained tokens: `qpec/invest-ai` + `qpec/invest-ai-state`, **Contents read/write only, no workflow scope** |
| 6 | **`main` branch protection** | The box's PAT must never touch code | Repo Settings → Branches → protect `main`, restrict pushers to owner + the Claude app |

Optional but ratified in the design:
- **Dead-man ping URL** (S2, elected ON): a free healthchecks.io check URL → the box pings it after each successful daily run so you're alerted if it dies during a vacation.
- The **backup volume** (S3) is provisioned automatically as `/mnt/agentcy-backup`.

## Cost

- Droplet `s-1vcpu-2gb`: ~**$12/mo** (recommended — 2 GB gives the pandas/scipy/matplotlib quarterly run headroom). `s-1vcpu-1gb` is ~$6/mo but risks running out of memory on the quarterly report.
- Backup volume 10 GiB: ~**$1/mo**.

## Steps (autonomous once the blockers are supplied)

```bash
# 0. authenticate (you, once)
doctl auth init                       # paste your DO API token

# 1. provision the droplet + backup volume
SSH_KEY_NAME=mykey bash deploy/digitalocean/provision.sh
#   → prints the droplet IP

# 2. ship code + secrets, install BOTH lanes (agentcy runtime + scout units
#    + OpenClaw judgement lane with its §4 permission seam, asserted)
IP=<ip> BOT_TOKEN=<telegram> CHAT_ID=<owner> GH_PAT=<fine-grained> \
  [PING_URL=<healthchecks>] bash deploy/digitalocean/deploy.sh

# 3. the two interactive steps deploy.sh prints (judgement-lane auth is the
#    owner's Claude subscription — no API key ever lands on the box)
ssh root@<ip>
sudo -u openclaw claude login
sudo -u openclaw openclaw onboard --install-daemon   # then: /home/openclaw/.openclaw/SETUP.md

# 4. verify
ssh root@<ip> 'systemctl --no-pager status "agentcy-*" ; systemctl list-timers "agentcy-*" "scout-*"'
#   send /start to your bot — it should reply
```

## The weekly relay (Saturday, Europe/Amsterdam)

| Time | Unit | Lane |
|---|---|---|
| 06:00 | `scout-scrape` — Saturday's final freshness pass (thesis names first, then stalest) | mechanical |
| 07:00 | `scout-monitor-brief` — work order into the spool, opened to the judgement lane | mechanical |
| 07:30 | `scout-verdicts` — claude researches the pre-committed questions → `verdicts.json` | judgement |
| 12:00 | `scout-monitor-run` — force-refresh of monitored names, then trigger arithmetic + verdict ingestion (missing ⇒ UNCHECKED, loud) | mechanical |
| 12:30 | `scout-site` — site rebuild → push `bot/site` (Pages deploys) + private state push | mechanical |

## Upgrading a live box (new code, no rebuild)

The box is a **reader** of the GitHub seam: it clones `main` at deploy time and
never pulls again on its own. So merging to `main` does not change the box — one
command does:

```bash
ssh root@<box> 'bash /opt/stock-agentcy/deploy/digitalocean/update.sh'
```

It fetches `main`, prints the commits it is taking, hard-resets, re-runs all three
installers (idempotent), and reports unit health. Re-running the installers is the
point rather than a precaution: a systemd unit added in the new commits — like
`scout-desk.service` — would otherwise sit on disk unknown to systemd. It touches
no secret and needs no environment, so it is safe to run from a shell you did not
prepare. Rebuilding the droplet also works (cloud-init re-runs from stored
`user_data`) but wipes the caches for no reason; prefer `update.sh`.

On a box deployed *before* this script existed there is nothing to invoke yet, so
the first upgrade pulls it into place and then runs it:

```bash
ssh root@<box> 'git -C /opt/stock-agentcy fetch origin main \
  && git -C /opt/stock-agentcy reset --hard origin/main \
  && bash /opt/stock-agentcy/deploy/digitalocean/update.sh'
```

## The production desk UI (real data, your machine's browser)

`scout-desk.service` runs the same page the public demo shows, with its actions
live, bound to loopback on the box. Reach it over an SSH tunnel — no public port,
and SSH is the authentication:

```bash
ssh -N -L 8899:127.0.0.1:8899 root@<box>     # leave running
# then open http://127.0.0.1:8899/ in your browser
```

Nightly: `agentcy-populate` 01:30, `scout-refresh` 02:15 (rolling EDGAR sweep —
thesis names always first, then the stalest of the whole universe, budgeted via
`SCOUT_REFRESH_BUDGET`), `scout-prices` 02:45 (the §3.6 weekly price grid, same
priority rule — without it market caps age silently and `pit.PRICE_MAX_AGE_DAYS`
starts refusing them), `agentcy-backup` 03:30, `scout-backup` 03:45.
Full design: `docs/plans/2026-08-04-distributed-desk-architecture.md`.

## First-run reality

`install.sh` and the systemd units were built and structurally verified, but this is their **first execution on a real Ubuntu host** (the test suite runs on the Windows desk with the Linux-only checks skipped). Treat the first deploy as a supervised shakedown — expect to fix a path/permission/dependency-build issue or two. Nothing here is destructive; the droplet is disposable and re-provisionable.

## After it's live

The daemon runs and the timers fire, but the system has **nothing to monitor until you add a holding + its thesis** at the desk:
```bash
ssh root@<ip>
sudo -u agentcy agentcy snapshot import <your-portfolio.csv>   # or: agentcy snapshot enter
sudo -u agentcy agentcy gate start <TICKER>                    # write the thesis through the Gate
```
Until then it will send calm "no positions yet" daily letters — which is correct behaviour, not an error.
