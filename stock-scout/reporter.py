"""Detached Telegram progress reporter (RECONSTRUCTION.md §5.4; msgs 5-6 "hard geregeld").

Runs nohup-friendly next to populate/augment/bt_fetch: every --interval seconds it
reads progress.json (§3.2 contract) and sends the pinned NL progress line via tg.py;
when finished flips true it sends the KLAAR line and exits 0; --max-hours is the
hard safety stop. A missing or partial progress.json means wait, never crash — the
reporter may start before the worker has written its first state.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import tg

REQUIRED_KEYS = ("task", "total", "done", "failed", "started_at")


def load_progress(path) -> dict | None:
    """progress.json payload, or None when missing/unparsable/incomplete (§5.4:
    tolerate and wait, do not crash)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or any(k not in data for k in REQUIRED_KEYS):
        return None
    return data


def _parse_ts(value) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def format_progress_line(progress: dict, *, now: datetime) -> str:
    """The pinned §5.4 line: '⏳ Stock Scout <task>: <done>/<total> gecached (<pct>%)
    · <failed> dode tickers · <rate>/min · ETA ~<m> min'. rate = cached per minute
    since started_at; ETA = remaining (total − done − failed) at that rate; both '?'
    until the first success."""
    task = progress["task"]
    total, done, failed = int(progress["total"]), int(progress["done"]), int(progress["failed"])
    pct = int(round(100.0 * done / total)) if total else 0
    started = _parse_ts(progress["started_at"])
    elapsed_min = (now - started).total_seconds() / 60.0 if started else 0.0
    if done > 0 and elapsed_min > 0:
        rate = done / elapsed_min
        rate_s = f"{rate:.1f}"
        eta_s = str(math.ceil(max(total - done - failed, 0) / rate))
    else:
        rate_s = eta_s = "?"
    return (f"⏳ Stock Scout {task}: {done}/{total} gecached ({pct}%) · "
            f"{failed} dode tickers · {rate_s}/min · ETA ~{eta_s} min")


def format_finished_line(progress: dict) -> str:
    """The pinned KLAAR line (msg 7 verbatim shape)."""
    return (f"✅ Stock Scout {progress['task']} KLAAR: {progress['done']}/{progress['total']} "
            f"gecached, {progress['failed']} dode tickers overgeslagen.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detached Telegram progress reporter (§5.4).")
    ap.add_argument("--interval", type=float, default=900, help="seconds between reports")
    ap.add_argument("--max-hours", type=float, default=4, help="hard safety stop")
    ap.add_argument("--progress", default="progress.json")
    args = ap.parse_args(argv)

    deadline = time.monotonic() + args.max_hours * 3600.0
    while True:
        progress = load_progress(args.progress)
        if progress is not None and progress.get("finished"):
            tg.send_message(format_finished_line(progress))
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            tg.send_message(f"⚠️ Stock Scout reporter: {args.max_hours:g}-uurslimiet bereikt, gestopt.")
            return 1
        time.sleep(min(args.interval, remaining))
        progress = load_progress(args.progress)
        if progress is None:
            continue
        if progress.get("finished"):
            tg.send_message(format_finished_line(progress))
            return 0
        tg.send_message(format_progress_line(progress, now=datetime.now(timezone.utc)))


if __name__ == "__main__":
    raise SystemExit(main())
