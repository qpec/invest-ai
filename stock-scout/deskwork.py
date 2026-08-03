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

# --- Which model did the work (the owner's "best available" rule) ------------------------
#
# Deleting the API client also deleted the one place a model was pinned (`AGENTCY_LLM_MODEL`,
# default claude-opus-5). The model is now a property of how the harness was launched:
# invisible to this repo, and — worse — invisible to whoever reads a thesis a year from now.
# A thesis written by a cheap model would look exactly like one written by the best model.
# So the model is recorded on every artifact, and the record is enforced.
#
# There is deliberately NO override flag. An escape hatch on this gate would be operated by
# the agent, and the agent is the thing being constrained. When a better model ships, the
# owner edits this one constant — a code change, in a file under review, journalled by git.
APPROVED_MODELS = ("claude-opus-5",)

# The harness transcript is a big append-only file; the model is on every assistant message,
# so the last one is the model running right now.
_TRANSCRIPT_TAIL_BYTES = 512 * 1024


class OrderError(Exception):
    """A work order could not be prepared, or its artifact could not be accepted."""


def transcript_path() -> Path | None:
    """The current harness transcript, or None when the harness does not keep one where
    we can see it (OpenClaw, a bare shell, a subprocess with the env stripped)."""
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        return None
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    matches = sorted((root / "projects").glob(f"*/{session}.jsonl"))
    return matches[-1] if matches else None


def observed_model(transcript: Path | None = None) -> str | None:
    """The model actually driving this session, read out of the harness's own transcript
    rather than taken on the agent's word.

    This is the only mechanically trustworthy answer available: an agent asked to name its
    model can say anything, and the whole design rests on not trusting the agent for the
    contract. Returns None when there is no transcript to read, which is a real state and
    is reported as such — never quietly treated as approval."""
    path = transcript if transcript is not None else transcript_path()
    if path is None or not Path(path).exists():
        return None
    path = Path(path)
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        start = max(0, size - _TRANSCRIPT_TAIL_BYTES)
        fh.seek(start)
        chunk = fh.read()
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    if start and lines:
        lines = lines[1:]        # the seek almost certainly landed mid-line
    for line in reversed(lines):
        try:
            model = (json.loads(line).get("message") or {}).get("model")
        except (json.JSONDecodeError, AttributeError):
            continue
        # "<synthetic>" marks harness-generated turns (cancellations, injected notices),
        # which carry no model and must not be mistaken for one.
        if model and not model.startswith("<"):
            return model
    return None


def resolve_model(declared: str | None = None, *,
                  transcript: Path | None = None) -> tuple[dict, list[str]]:
    """Establish which model did the work, and whether the owner allows it.

    Returns ``({"id", "provenance", "approved"}, problems)``. Problems are returned rather
    than raised so the caller can fold them into the rest of its refusal and still write a
    record — a refused artifact that leaves no trace of WHY is the failure mode this whole
    seam exists to prevent."""
    seen = observed_model(transcript)
    declared = (declared or "").strip() or None
    problems: list[str] = []

    if seen and declared and seen != declared:
        # The declaration is only worth anything because it is cross-checked. A mismatch
        # is not a typo to smooth over: one of the two is wrong about what wrote the file.
        problems.append(f"model mismatch: the harness transcript says {seen!r} but "
                        f"--model says {declared!r}")
    model_id = seen or declared
    provenance = "observed" if seen else ("declared" if declared else None)

    if model_id is None:
        problems.append(
            "no model recorded: this harness keeps no readable transcript, so pass "
            "`--model <your model id>`. A thesis whose author is unknown cannot be "
            "told apart from one written by the cheapest model available.")
    elif model_id not in APPROVED_MODELS:
        problems.append(
            f"model {model_id!r} is not approved for desk work — the owner's rule is best "
            f"available only, currently {', '.join(APPROVED_MODELS)}. Re-run this task on "
            f"an approved model, or have the OWNER (not you) widen "
            f"deskwork.APPROVED_MODELS.")

    return ({"id": model_id, "provenance": provenance,
             "approved": bool(model_id) and model_id in APPROVED_MODELS}, problems)


def model_note(info: dict) -> str:
    """One line naming the model and how confidently, for a report a human will read."""
    if not info or not info.get("id"):
        return "model: UNRECORDED"
    if info.get("provenance") == "observed":
        return f"model: {info['id']} (read from the harness transcript)"
    return f"model: {info['id']} (declared by the agent, NOT independently verified)"


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
