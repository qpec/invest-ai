"""Populator phase gate (populator design 1/9, constitution NFR3/NFR7): no new pip
dependency, no new fetch door, no LLM in the scheduled runtime."""
import ast
import tomllib
from pathlib import Path

import agentcy.populate  # noqa: F401
import agentcy.jobs.populate  # noqa: F401
import agentcy.render.populate  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_no_new_pip_dependency():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {d.split("==")[0].split(">")[0].split("[")[0].strip().lower() for d in deps}
    assert names == {"yfinance", "pandas", "scipy", "quantstats"}
    assert set(data["project"]["optional-dependencies"]) == {"scout"}


def test_yfinance_imported_only_in_fetch_yf():
    """The single fetch door (design 1): `import yfinance` appears in exactly one module."""
    offenders = []
    for path in (ROOT / "agentcy").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "yfinance"
                                                    for a in node.names):
                offenders.append(path)
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "yfinance":
                offenders.append(path)
    rel = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in set(offenders))
    assert rel == ["agentcy/fetch/yf.py"], f"yfinance imported outside the one door: {rel}"


def test_populator_imports_no_llm():
    import sys
    banned = ("anthropic", "openai", "langchain", "llama", "cohere", "google.generativeai")
    loaded = set(sys.modules)
    assert not any(b in m for b in banned for m in loaded)
