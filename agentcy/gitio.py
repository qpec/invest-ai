"""Archive git mechanics via the system git binary (subprocess) — plumbing-stable
porcelain (tech-arch §3). Commit failure is NON-FATAL to delivery (the letter already
sits in the outbox; SQLite is the source of truth): commit() returns None on any failure,
logged by the caller as a data-health line. The only sanctioned push is
'git push backup' (§8/§11.6)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def ensure_repo(path: Path, *, committer: str = "agentcy") -> None:
    """Init the dedicated archive repo if absent (install.sh path §1.1). Idempotent."""
    path.mkdir(parents=True, exist_ok=True)
    if (path / ".git").exists():
        return
    subprocess.run(["git", "init", "-q", str(path)], capture_output=True, text=True)
    _git(path, "config", "user.name", committer)
    _git(path, "config", "user.email", f"{committer}@localhost")


def commit(repo: Path, paths: Sequence[Path], message: str) -> str | None:
    """git add <paths> -> commit -> rev-parse HEAD. Returns the 40-char SHA, or None on
    ANY failure (not a git repo, nothing staged, hook failure) — never raises."""
    try:
        rel = [str(p) for p in paths]
        add = _git(repo, "add", "--", *rel)
        if add.returncode != 0:
            return None
        # nothing staged -> nothing to commit -> None (not an error)
        status = _git(repo, "status", "--porcelain")
        if not status.stdout.strip():
            return None
        c = _git(repo, "commit", "-q", "-m", message)
        if c.returncode != 0:
            return None
        rev = _git(repo, "rev-parse", "HEAD")
        sha = rev.stdout.strip()
        return sha if rev.returncode == 0 and len(sha) == 40 else None
    except OSError:
        return None


def push_backup(repo: Path) -> bool:
    """'git push backup' to the bare mirror on the second disk — the ONLY sanctioned push
    (§8/§11.6). Non-fatal: returns False on failure, never raises."""
    try:
        r = _git(repo, "push", "backup")
        return r.returncode == 0
    except OSError:
        return False
