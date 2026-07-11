"""Scout Stage-2 (Part A) phase gate (design 2026-07-11 + constitution NFR3/NFR7/FR9):
no new pip dependency, no LLM import, Stage-1 grade math frozen, and Stage-2 writes ONLY the
review-artifact table (no monitoring-table writes)."""
import importlib
import inspect
import sys
import tomllib
from pathlib import Path

import agentcy.scout_review  # noqa: F401
import agentcy.render.scout_review  # noqa: F401
from agentcy import scout_grade as sg


def test_no_new_pip_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {d.split("==")[0].split(">")[0].split("[")[0].strip().lower() for d in deps}
    assert names == {"yfinance", "pandas", "scipy", "quantstats"}
    extras = data["project"]["optional-dependencies"]
    assert set(extras) == {"scout"}


def test_stage2_imports_no_llm():
    for mod in ("agentcy.scout_review", "agentcy.render.scout_review"):
        importlib.reload(importlib.import_module(mod))
    banned = ("anthropic", "openai", "langchain", "llama", "cohere", "google.generativeai")
    loaded = set(sys.modules)
    assert not any(b in m for b in banned for m in loaded), (
        "Stage-2 Part A is deterministic/desk-only: no LLM client may be imported")


def test_stage1_grade_math_unchanged():
    # the tunable surface (weights + bands) is byte-identical to Stage-1; Stage-2 never edits it
    assert (sg.W_V, sg.W_Q, sg.W_G, sg.W_D, sg.W_M) == (0.25, 0.25, 0.20, 0.15, 0.15)
    assert sg._GRADE_BANDS == ((80.0, "A"), (65.0, "B"), (50.0, "C"), (35.0, "D"))
    # scout_review imports scout_grade but defines NO grading function of its own
    import agentcy.scout_review as srv
    for name in ("composite", "grade_universe", "grade_letter", "sector_percentile"):
        assert not hasattr(srv, name), f"scout_review must not redefine Stage-1 {name}"


def test_stage2_writes_only_the_review_artifact_table():
    # the Stage-2 modules touch NO monitoring-table writer: only append_scout_verdict is allowed
    banned_writers = ("append_report", "append_alert", "append_trigger", "append_trigger_check",
                      "append_thesis", "append_positions", "append_journal_entry",
                      "update_alert_resolution", "append_watchlist_item")
    src = inspect.getsource(agentcy.scout_review) + inspect.getsource(agentcy.render.scout_review)
    for w in banned_writers:
        assert w not in src, f"Stage-2 must not call monitoring writer {w}"
