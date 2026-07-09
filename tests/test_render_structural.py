# tests/test_render_structural.py
import ast
import pathlib

RENDER = pathlib.Path(__file__).resolve().parents[1] / "agentcy" / "render"


def _py_files():
    files = list(RENDER.glob("*.py"))
    assert files, f"no render modules found under {RENDER}"
    return files


def test_no_avg_open_price_anywhere_in_render():
    for f in _py_files():
        assert "avg_open_price" not in f.read_text(encoding="utf-8"), f"{f} references cost basis"


def test_no_benchmark_module_import_in_render():
    for f in _py_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("benchmark"):
                raise AssertionError(f"{f} imports benchmark")
            if isinstance(node, ast.Import):
                for n in node.names:
                    assert not n.name.endswith("benchmark"), f"{f} imports benchmark"


def test_no_quantstats_import_in_render():
    for f in _py_files():
        assert "quantstats" not in f.read_text(encoding="utf-8"), f"{f} imports quantstats"


def test_render_functions_do_not_open_db():
    # renderers are pure: no sqlite3, no conn.execute in render/*
    for f in _py_files():
        src = f.read_text(encoding="utf-8")
        assert "sqlite3" not in src and ".execute(" not in src, f"{f} touches the DB"
