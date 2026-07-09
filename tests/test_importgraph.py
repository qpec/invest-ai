"""Import-graph + source-scan structural tests (tech-arch §13, §4.6 wall 4).

P1 arms the harness; P2/P5/P6 add benchmark/quantstats/advice-path assertions as those
modules appear — the constraints below are written to hold from day one onward."""
from __future__ import annotations

import sys
from pathlib import Path

from tests import util_importgraph as ig


def test_harness_resolves_absolute_and_relative_imports(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("import json\nfrom pkg import b\n", encoding="utf-8")
    (pkg / "b.py").write_text("from . import c\n", encoding="utf-8")
    (pkg / "c.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "d.py").write_text("from ..c import thing\nfrom . import e\n",
                                      encoding="utf-8")
    (pkg / "sub" / "e.py").write_text("import pkg.a\n", encoding="utf-8")
    g = ig.import_graph(root=pkg)
    assert "json" in g["pkg.a"] and "pkg.b" in g["pkg.a"]
    assert "pkg.c" in g["pkg.b"]                       # from . import c
    assert "pkg.c" in g["pkg.sub.d"]                   # from ..c import thing
    assert "pkg.sub.e" in g["pkg.sub.d"]               # from . import e
    assert ig.importers_of("pkg.c", root=pkg) == {"pkg.b", "pkg.sub.d"}
    assert "pkg.sub.e" in ig.transitive_importers("pkg.b", root=pkg)  # e -> a -> b


def test_no_attach_outside_benchmark_module():
    # invariant 7 wall 4: ATTACH would let any connection reach benchmark.db
    offenders = ig.source_scan(r"\bATTACH\b")
    assert offenders <= {"agentcy.benchmark"}, offenders


def test_benchmark_reachable_only_from_quarterly_and_backup():
    allowed = {"agentcy.jobs.quarterly", "agentcy.jobs.backup"}
    assert ig.transitive_importers("agentcy.benchmark") <= allowed


def test_quantstats_and_tradingview_quarantined():
    assert ig.importers_of("quantstats") <= {"agentcy.jobs.quarterly"}
    assert ig.importers_of("tradingview_screener") <= {"agentcy.scout"}


def test_p1_storage_core_is_stdlib_plus_agentcy_only():
    # the spine imports nothing outside the standard library (tech-arch §2.1)
    for mod in ("agentcy.db", "agentcy.clock", "agentcy.freshness",
                "agentcy.config", "agentcy.runlog"):
        path = ig.iter_modules()[mod]
        for imported in ig.imports_of(path):
            top = imported.split(".")[0]
            assert top in sys.stdlib_module_names or top == "agentcy", \
                f"{mod} imports non-stdlib {imported}"
