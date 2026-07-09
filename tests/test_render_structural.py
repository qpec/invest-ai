# tests/test_render_structural.py
import ast
import pathlib

RENDER = pathlib.Path(__file__).resolve().parents[1] / "agentcy" / "render"
GOLDEN = pathlib.Path(__file__).resolve().parents[1] / "tests" / "golden"


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


# --- golden-lint sweep: the scheduled goldens ARE the format spec (§6.2) -------------
# Every rendered scheduled HTML golden must be free of the calm-register's banned
# state-emphasis tokens. A golden that leaks one is a renderer bug, not a test bug —
# fix the offending renderer/golden, never this guard. Owner-quoted verbatim (alert/
# weekly) legitimately carries '!' and 'S&P', so those classes are checked by the
# lint's owner-span scoping in test_render_lint.py, not here; this sweep covers the
# static-text scheduled classes only.
_STRICT = {
    "daily_all_clear", "daily_opportunity", "daily_weekend_pulse", "daily_degraded",
    "daily_total_failure", "daily_holiday_vs_outage", "pause_mode_letter",
    "status_card", "event_quiet", "event_data_lag", "study_digest",
}

# red-alarm typography banned as state emphasis (mirrors render.lint._RED_GLYPHS)
_RED = ("\U0001f534", "\U0001f6a8", "⚠️", "❗", "❌")


def test_strict_scheduled_html_goldens_have_no_red_glyphs():
    for name in sorted(_STRICT):
        p = GOLDEN / f"{name}.html.txt"
        assert p.exists(), f"missing {p}"
        text = p.read_text(encoding="utf-8")
        assert not any(g in text for g in _RED), f"{name} has a red glyph"
        assert "€" not in text, f"{name} leaked a euro amount"
        assert "S&P" not in text, f"{name} leaked a benchmark token"
