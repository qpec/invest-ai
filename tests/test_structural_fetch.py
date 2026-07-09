"""P2-scoped structural invariants: banned .info token + benchmark quarantine (tech-arch 7.2, 4.6)."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _sources(*rel_dirs: str) -> list[Path]:
    files: list[Path] = []
    for d in rel_dirs:
        files.extend((ROOT / d).rglob("*.py"))
    return files


def test_no_dot_info_accessor_anywhere():
    offenders = []
    for path in _sources("agentcy", "tools"):
        text = path.read_text(encoding="utf-8")
        if ".info" in text:                                  # fast_info is fine; the bare `info` accessor is banned (§7.2)
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"banned `.info` accessor in: {offenders}"


def test_data_layer_never_names_benchmark_db_or_attaches():
    for rel in ("agentcy/fetch/yf.py", "agentcy/fetch/store.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "benchmark.db" not in text, f"{rel} must not know benchmark.db's path (invariant 7)"
        assert "ATTACH" not in text.upper(), f"{rel} must not ATTACH (only benchmark.py opens benchmark.db)"


def test_benchmark_module_is_the_only_place_naming_benchmark_db():
    named = []
    for path in _sources("agentcy"):
        if path.name == "benchmark.py":
            continue
        if "benchmark.db" in path.read_text(encoding="utf-8"):
            named.append(str(path.relative_to(ROOT)))
    assert named == [], f"only benchmark.py may name benchmark.db; found in: {named}"
