"""The agent seam — work orders out, validated artifacts in (THESIS-DESIGN.md §5).

**There is no API client in this repo.** The system is driven by an agent harness —
Claude Code, OpenClaw — that already has web search, file tools, and judgement. Asking
it to run a second LLM over HTTP would be paying twice for the same capability and
adding a credential, a retry loop and a token budget the harness already owns.

So the seam is the filesystem, and it runs in two beats:

    1. Python writes a WORK ORDER  — the packet, the schema, the rules, the file to write
    2. the agent does the work     — research with its own tools, then writes the artifact
    3. Python VALIDATES the result — mechanically, and refuses what it cannot check

The property that matters is that beat 3 is not negotiable. The agent cannot smuggle an
unvalidatable trigger past `record`, cannot invent a conviction level, and cannot mark
its own thesis committed — those are Python's checks and the owner's decision (FR9).
The agent is trusted for research and prose, never for the contract.

This module owns the shared mechanics of that seam; thesis.py and monitor.py define what
their own orders and artifacts contain.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ORDER_NAME = "WORK-ORDER.md"


class OrderError(Exception):
    """A work order could not be prepared, or its artifact could not be accepted."""


def write_atomic(path: Path, text: str):
    """Write via tmp + rename. Theses and trigger state are portfolio data living outside
    the code repo (NFR2) — the file is the only copy, so a truncate-then-write interrupted
    by a crash destroys it. After a rename the file is the old version or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: Path, payload) -> Path:
    write_atomic(path, json.dumps(payload, indent=2))
    return path


def read_json(path: Path):
    if not Path(path).exists():
        raise OrderError(f"{path} does not exist — the agent has not written it yet")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise OrderError(f"{path} is not valid JSON: {error}") from None


def schema_block(schema: dict, *, title: str) -> str:
    """A JSON Schema rendered into a work order. The agent reads this instead of a tool
    definition — same contract, delivered as a file rather than an API parameter."""
    return (f"### {title}\n\nWrite JSON matching this schema exactly. Every listed field "
            f"is required; no extra fields.\n\n```json\n"
            f"{json.dumps(schema, indent=2)}\n```\n")


def order(*, title: str, why: str, steps: list[str], artifacts: list[tuple[str, str]],
          body: str, rules: list[str], finish: str) -> str:
    """One work order, in the shape an agent can execute top to bottom without guessing.

    `artifacts` is (path, description) — the files the agent must write. `finish` is the
    command that validates them, and it is stated as the last step because an artifact
    nobody validated is not a deliverable."""
    lines = [f"# {title}", "", why, "", "## What to produce", ""]
    for path, description in artifacts:
        lines.append(f"- `{path}` — {description}")
    lines += ["", "## How", ""]
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")
    lines += ["", "## Rules", ""]
    for rule in rules:
        lines.append(f"- {rule}")
    lines += ["", body, "", "## When you are done", "",
              f"Run `{finish}`. It validates what you wrote and prints any problem it "
              f"finds. **A non-zero exit means the artifact is not accepted** — fix and "
              f"re-run; do not report the work as finished until it exits clean.", ""]
    return "\n".join(lines)
