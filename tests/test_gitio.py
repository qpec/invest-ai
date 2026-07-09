"""gitio: subprocess git mechanics, commit failure non-fatal (tech-arch §3, §8/§11.6).

Uses a real temporary git repo (the git binary is a project dependency; the no-network
guard blocks sockets, not subprocess to a local git). Skips if git is unavailable."""
import shutil
import subprocess

import pytest

from agentcy import gitio

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def test_ensure_repo_initializes(tmp_path):
    repo = tmp_path / "archive"
    gitio.ensure_repo(repo, committer="agentcy")
    assert (repo / ".git").exists()
    # idempotent
    gitio.ensure_repo(repo, committer="agentcy")


def test_commit_returns_sha(tmp_path):
    repo = tmp_path / "archive"
    gitio.ensure_repo(repo)
    f = repo / "letters" / "2026-07-08.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("hello", encoding="utf-8")
    sha = gitio.commit(repo, [f], "feat: daily letter 2026-07-08")
    assert sha and len(sha) == 40
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "daily letter" in log


def test_commit_failure_is_non_fatal_returns_none(tmp_path):
    # committing outside any repo -> None, never raises (delivery must not depend on git)
    not_a_repo = tmp_path / "nope"
    not_a_repo.mkdir()
    f = not_a_repo / "x.md"
    f.write_text("x", encoding="utf-8")
    assert gitio.commit(not_a_repo, [f], "msg") is None


def test_commit_nothing_to_commit_returns_none(tmp_path):
    repo = tmp_path / "archive"
    gitio.ensure_repo(repo)
    f = repo / "a.md"
    f.write_text("x", encoding="utf-8")
    gitio.commit(repo, [f], "first")
    # committing the same file again with no change -> nothing to commit -> None, no raise
    assert gitio.commit(repo, [f], "again") is None
