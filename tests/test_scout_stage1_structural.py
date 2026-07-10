"""Stage-1 phase gate (design §8 item 1, constitution NFR3/NFR7): the graded engine adds
NO pip dependency and imports NO LLM. Deterministic-only in this build."""
import importlib
import sys
import tomllib
from pathlib import Path

import agentcy.scout_grade  # noqa: F401
import agentcy.render.scout  # noqa: F401


def test_no_new_pip_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {d.split("==")[0].split(">")[0].split("[")[0].strip().lower() for d in deps}
    # Stage-1 uses ONLY what was already declared (yfinance/pandas/scipy/quantstats)
    assert names == {"yfinance", "pandas", "scipy", "quantstats"}
    # the Scout adds no new optional-extra beyond the existing [scout] tradingview one
    extras = data["project"]["optional-dependencies"]
    assert set(extras) == {"scout"}


def test_scout_grade_imports_no_llm():
    # fresh import of the grading + render modules pulls in no LLM client
    for mod in ("agentcy.scout_grade", "agentcy.render.scout", "agentcy.scout"):
        importlib.reload(importlib.import_module(mod))
    banned = ("anthropic", "openai", "langchain", "llama", "cohere", "google.generativeai")
    loaded = set(sys.modules)
    assert not any(b in m for b in banned for m in loaded), (
        "Stage-1 is deterministic-only (design §8): no LLM client may be imported")


def test_stage2_and_populator_are_explicit_followons():
    # Stage-2 (LLM reviewer) and the archive batch populator are NOT built in Stage-1.
    assert not any("qualitative" in m.lower() for m in sys.modules)
