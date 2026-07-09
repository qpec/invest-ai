"""P0 structural tests: layout per tech-arch §3 + contracts §3 module homes;
pins per contracts §0. A missing module is a named failure."""
from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

MODULES = [
    "agentcy",
    "agentcy.db", "agentcy.sdnotify", "agentcy.config", "agentcy.clock",
    "agentcy.freshness", "agentcy.runlog",
    "agentcy.fetch", "agentcy.fetch.yf", "agentcy.fetch.store",
    "agentcy.mirror", "agentcy.cluster", "agentcy.register", "agentcy.triggers",
    "agentcy.journal", "agentcy.absence", "agentcy.study", "agentcy.gate", "agentcy.scout",
    "agentcy.asks", "agentcy.events",
    "agentcy.jobs", "agentcy.jobs.daily", "agentcy.jobs.weekly",
    "agentcy.jobs.quarterly", "agentcy.jobs.event", "agentcy.jobs.backup",
    "agentcy.benchmark",
    "agentcy.tg", "agentcy.tg.client", "agentcy.tg.outbox", "agentcy.tg.daemon",
    "agentcy.render", "agentcy.render.contexts", "agentcy.render.common",
    "agentcy.render.lint", "agentcy.render.daily", "agentcy.render.weekly",
    "agentcy.render.alert", "agentcy.render.event", "agentcy.render.quarterly",
    "agentcy.render.gate", "agentcy.render.study",
    "agentcy.archive", "agentcy.gitio", "agentcy.cli",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_schema_dir_exists():
    assert (ROOT / "agentcy" / "schema").is_dir()


def test_console_entry_point_callable():
    from agentcy import cli
    assert callable(cli.main)


def test_pyproject_pins():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    proj = data["project"]
    deps = proj["dependencies"]
    assert "yfinance==1.5.1" in deps
    assert "quantstats==0.0.81" in deps
    assert "pandas" in deps
    assert "scipy" in deps
    assert len(deps) == 4, "runtime deps are EXACTLY four (tech-arch §2.1)"
    assert proj["requires-python"] == "==3.13.*"
    assert proj["scripts"]["agentcy"] == "agentcy.cli:main"
    assert proj["optional-dependencies"]["scout"] == ["tradingview-screener"]
    assert data["dependency-groups"]["dev"] == ["pytest"]


def test_python_version_exact_patch_pin():
    v = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert v.startswith("3.13."), f".python-version must pin an exact 3.13.x patch, got {v!r}"
