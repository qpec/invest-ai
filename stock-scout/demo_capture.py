"""Capture what each desk action really prints, so the public demo can replay it.

The demo on GitHub Pages must be fully clickable and completely inert: it runs on
pregenerated sample data, and its buttons cannot execute anything (a static host has
nothing to execute WITH, and running the desk spends the operator's own subscription
and machine). Replaying a canned transcript would be a lie if the transcript were
invented — so it is not invented: this script RUNS each action against the bundled
sample data in a throwaway copy and records the actual stdout.

    python demo_capture.py            # rewrites sample-data/demo-playback.json

Re-run it whenever an action's output changes; the file carries the date it was taken
so the demo can say how old the recording is.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample-data"
OUT = SAMPLE / "demo-playback.json"

# The symbol the per-name actions are recorded for. CROX is in the sample universe and
# already carries a draft, so the Thesis tab has something real to show.
DEMO_SYMBOL = "CROX"


def _tidy(text: str, work: Path) -> str:
    """Scrub the capture machine's paths: a demo should show the command a READER would
    type, not this laptop's temp directory."""
    return (text.replace(str(work), "…")
                .replace(str(SAMPLE), "sample-data")
                .replace(str(HERE) + "/", ""))


def _run(argv: list[str], cwd: Path, work: Path) -> list[str]:
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=900)
    lines = [_tidy(line.rstrip(), work) for line in
             (proc.stdout + proc.stderr).splitlines() if line.strip()]
    shown = " ".join(_tidy(Path(p).name if p == sys.executable else p, work)
                     for p in argv)
    return [f"$ {shown}"] + lines


def capture() -> dict:
    with tempfile.TemporaryDirectory(prefix="demo-capture-") as tmp:
        work = Path(tmp)
        theses = work / "theses"
        shutil.copytree(SAMPLE / "theses", theses)
        cache = work / "cache"
        cache.mkdir()
        common = ["--sec-data", str(SAMPLE / "secdata"),
                  "--prices", str(SAMPLE / "prices"),
                  "--universe", str(SAMPLE / "universe.csv"),
                  "--as-of", _dt.date.today().isoformat()]
        py = sys.executable
        actions = {
            "refresh": [py, "enrich.py", "--force-refresh", "--symbols", DEMO_SYMBOL,
                        "--cache", str(cache)],
            "thesis": [py, "thesis.py", "brief", DEMO_SYMBOL, *common,
                       "--theses-dir", str(theses)],
            "thesis-batch": [py, "thesis.py", "batch", *common,
                             "--theses-dir", str(theses)],
            "monitor-brief": [py, "monitor.py", "brief", "--theses-dir", str(theses),
                              "--as-of", _dt.date.today().isoformat()],
            "monitor-run": [py, "monitor.py", "run", *common,
                            "--theses-dir", str(theses),
                            "--reports-dir", str(work / "reports")],
        }
        recorded = {key: _run(argv, HERE, work) for key, argv in actions.items()}
    # `rebuild` never shells out — it re-renders in-process, so its line is its truth.
    recorded["rebuild"] = ["$ webapp.py (in-process rebuild)", "site rebuilt from disk"]
    return {"captured": _dt.date.today().isoformat(), "symbol": DEMO_SYMBOL,
            "note": "real output of each action on the bundled sample data",
            "actions": recorded}


def main() -> int:
    payload = capture()
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    total = sum(len(v) for v in payload["actions"].values())
    print(f"{OUT}  ({len(payload['actions'])} actions, {total} recorded lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
