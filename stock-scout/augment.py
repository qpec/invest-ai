"""Quarterly-statement augment of an existing annual-only cache (RECONSTRUCTION.md §5.3).

The v2.2 path (msgs 20-23): add the "quarterly" key to cache entries that lack it so
TTM metrics can move from annual proxies to true trailing-4-quarter sums. Same
contracts as populate.py — paced via vendor/yf_fetch with the cache dir's parent as
lock state_dir, one failures.log line per failure, progress.json (task "augment")
rewritten after EVERY symbol for the detached reporter (§5.4).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from vendor import yf_fetch
from populate import (FAILURES_FILE, PROGRESS_FILE, STATEMENT_TYPES, append_failure,
                      atomic_write_json, cache_filename, statement_payload, write_progress)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Add quarterly statements to the cache (§5.3).")
    ap.add_argument("--universe", default="universe.csv")
    args = ap.parse_args(argv)

    cache_dir = Path("cache")
    state_dir = cache_dir.resolve().parent
    symbols = [str(s) for s in pd.read_csv(args.universe)["symbol"]]
    targets = [(s, cache_dir / cache_filename(s)) for s in symbols
               if (cache_dir / cache_filename(s)).exists()]

    total, done, failed = len(targets), 0, 0
    started_at = datetime.now(timezone.utc).isoformat()
    write_progress(PROGRESS_FILE, task="augment", total=total, done=done, failed=failed,
                   started_at=started_at)

    for symbol, path in targets:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            failed += 1
            append_failure(FAILURES_FILE, symbol, f"unreadable cache entry: {e}")
            write_progress(PROGRESS_FILE, task="augment", total=total, done=done,
                           failed=failed, started_at=started_at)
            continue
        if "quarterly" in entry:
            done += 1
            write_progress(PROGRESS_FILE, task="augment", total=total, done=done,
                           failed=failed, started_at=started_at)
            continue
        try:
            frames = yf_fetch.fetch_statements(symbol, state_dir=state_dir, freq="quarterly")
            entry["quarterly"] = {st: statement_payload(frames[st]) for st in STATEMENT_TYPES}
            atomic_write_json(path, entry)
            done += 1
        except yf_fetch.RateLimited as e:
            failed += 1
            append_failure(FAILURES_FILE, symbol, f"rate-limited: {e}")
            write_progress(PROGRESS_FILE, task="augment", total=total, done=done,
                           failed=failed, started_at=started_at)
            print(f"{symbol}: rate-limited after the full backoff ladder — stopping the run",
                  file=sys.stderr)
            return 1
        except Exception as e:  # never fatal, same contract as populate (§5.2/§5.3)
            failed += 1
            append_failure(FAILURES_FILE, symbol, e)
        write_progress(PROGRESS_FILE, task="augment", total=total, done=done,
                       failed=failed, started_at=started_at)

    write_progress(PROGRESS_FILE, task="augment", total=total, done=done, failed=failed,
                   started_at=started_at, finished=True,
                   finished_at=datetime.now(timezone.utc).isoformat())
    print(f"augment finished: {done}/{total} augmented, {failed} failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
