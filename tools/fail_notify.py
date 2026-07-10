"""OnFailure=agentcy-fail@%n.service target (tech-arch §11.3, layer 2).

Direct-sends "unit %i FAILED — letter may be delayed; journalctl -u %i" to the owner
chat via stdlib urllib + the env token, DELIBERATELY bypassing the DB and the outbox:
the failure being reported may BE the database. Zero project imports — this must run
even when the venv/package is the thing that broke. If even this send fails, it writes
to journald (stderr, token redacted) and exits 0 — a failing notifier must never loop."""
import json
import os
import sys
import urllib.request


def notify(unit: str) -> int:
    token = os.environ.get("AGENTCY_BOT_TOKEN", "")
    chat = os.environ.get("AGENTCY_OWNER_CHAT_ID", "")
    text = f"unit {unit} FAILED — letter may be delayed; journalctl -u {unit}"
    if not token or not chat:
        print(f"fail_notify: missing token/chat env; unit={unit}", file=sys.stderr)
        return 0
    try:
        data = json.dumps({"chat_id": chat, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if not (200 <= resp.status < 300):
                print(f"fail_notify: telegram returned {resp.status}; unit={unit}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 — never loop; token must never leak into the log
        print(f"fail_notify: direct-send failed for unit={unit}: {type(exc).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(notify(sys.argv[1] if len(sys.argv) > 1 else "unknown"))
