"""Stage-1.5 phase gate: the de-bias touched the Scout DISCOVERY path only. store.owner_fcf_ttm
and the monitoring surface are unchanged; no new pip dependency; no LLM import."""
import importlib
import inspect
import sys
import tomllib
from pathlib import Path

import agentcy.scout_grade  # noqa: F401
import agentcy.render.scout  # noqa: F401
from agentcy.fetch import store


def test_store_owner_fcf_ttm_still_conservative_min_is_total_capex():
    """store.owner_fcf_ttm's per-period construction is still (OCF - |CapEx|) - SBC (the
    conservative figure); it must NOT reference the normalized min(|CapEx|, D&A) proxy or the
    'Depreciation And Amortization' row. This is the byte-level guard on the monitoring path."""
    src = inspect.getsource(store.owner_fcf_ttm)
    assert "Depreciation And Amortization" not in src
    assert "abs(float(capex))" in src            # conservative: full CapEx subtracted
    # the normalized figure lives in the Scout layer, not store
    assert not hasattr(store, "normalized_owner_fcf_ttm")


def test_normalized_lives_in_scout_grade_not_store():
    from agentcy import scout_grade as sg
    assert hasattr(sg, "normalized_owner_fcf_ttm")


def test_no_new_pip_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {d.split("==")[0].split(">")[0].split("[")[0].strip().lower() for d in deps}
    assert names == {"yfinance", "pandas", "scipy", "quantstats"}
    extras = data["project"]["optional-dependencies"]
    assert set(extras) == {"scout"}


def test_scout_grade_imports_no_llm():
    for mod in ("agentcy.scout_grade", "agentcy.render.scout", "agentcy.scout"):
        importlib.reload(importlib.import_module(mod))
    banned = ("anthropic", "openai", "langchain", "llama", "cohere", "google.generativeai")
    loaded = set(sys.modules)
    assert not any(b in m for b in banned for m in loaded)
