#!/usr/bin/env bash
# Provision a DigitalOcean droplet + backup volume for stock-agentcy.
# Requires: doctl authenticated (run `doctl auth init` first).
# Prints the droplet's public IP on success.
set -euo pipefail

NAME="${DROPLET_NAME:-stock-agentcy}"
REGION="${REGION:-ams3}"            # Amsterdam — closest to the NL owner
SIZE="${SIZE:-s-1vcpu-2gb}"         # 2 GB: pandas/scipy/quantstats(matplotlib) need headroom; s-1vcpu-1gb is cheaper but risks OOM on the quarterly run
IMAGE="ubuntu-24-04-x64"            # the technology architecture's target OS
VOLUME_NAME="${VOLUME_NAME:-agentcy-backup}"
VOLUME_SIZE="${VOLUME_SIZE:-10}"    # GiB — the S3-ratified second disk (/mnt/agentcy-backup)
SSH_KEY_NAME="${SSH_KEY_NAME:?Set SSH_KEY_NAME to the name of an SSH key already uploaded to your DO account (doctl compute ssh-key list)}"

key_id() { doctl compute ssh-key list --format ID,Name --no-header | awk -v n="$SSH_KEY_NAME" '$2==n{print $1}'; }
vol_id() { doctl compute volume list --format ID,Name --no-header | awk -v n="$VOLUME_NAME" '$2==n{print $1}'; }

KID="$(key_id)"; [ -n "$KID" ] || { echo "SSH key '$SSH_KEY_NAME' not found in your DO account. Upload it: doctl compute ssh-key import $SSH_KEY_NAME --public-key-file ~/.ssh/id_ed25519.pub"; exit 1; }

echo ">>> backup volume $VOLUME_NAME (${VOLUME_SIZE} GiB, $REGION)"
if [ -z "$(vol_id)" ]; then
  doctl compute volume create "$VOLUME_NAME" --region "$REGION" --size "${VOLUME_SIZE}GiB" --fs-type ext4
fi
VID="$(vol_id)"

echo ">>> droplet $NAME ($SIZE, $IMAGE, $REGION) — attaching volume + SSH key"
doctl compute droplet create "$NAME" \
  --region "$REGION" --size "$SIZE" --image "$IMAGE" \
  --ssh-keys "$KID" --volumes "$VID" \
  --tag-name agentcy --wait

IP="$(doctl compute droplet get "$NAME" --format PublicIPv4 --no-header)"
echo ""
echo ">>> droplet ready:  $IP"
echo "    deploy the code + secrets:  IP=$IP BOT_TOKEN=<telegram> CHAT_ID=<owner> bash deploy/digitalocean/deploy.sh"
