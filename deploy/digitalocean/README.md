# Deploying stock-agentcy to DigitalOcean

The system was designed for "an always-on Ubuntu box." A DigitalOcean Droplet running **Ubuntu 24.04 LTS** is exactly that target — so this is the intended production deployment, not a workaround.

## What you must provide (hard blockers)

| # | Item | Why | How to get it |
|---|---|---|---|
| 1 | **DigitalOcean API token** | Provision the droplet + volume | DO dashboard → API → Generate New Token (read+write). Then `doctl auth init`. |
| 2 | **Telegram bot token** | The system's *only* interface | Message **@BotFather** on Telegram → `/newbot` → copy the token. |
| 3 | **Your Telegram chat-id** | Locks the bot to you | Message your new bot once, then we read it from `getUpdates` (or use @userinfobot). |
| 4 | **An SSH key in your DO account** | So we can log into the droplet | `doctl compute ssh-key import mykey --public-key-file ~/.ssh/id_ed25519.pub` |

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

# 2. ship the code + secrets and run install.sh (writes the 0600 env file,
#    creates the agentcy user, mounts the volume, enables the systemd timers,
#    starts the Telegram daemon)
IP=<ip> BOT_TOKEN=<telegram> CHAT_ID=<owner> [PING_URL=<healthchecks>] \
  bash deploy/digitalocean/deploy.sh

# 3. verify
ssh root@<ip> 'systemctl --no-pager status "agentcy-*" ; systemctl list-timers "agentcy-*"'
#   send /start to your bot — it should reply
```

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
