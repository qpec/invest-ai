"""P6.20: structural invariants over agentcy/jobs/* (invariants 4/7 scoped to this phase)."""
import ast
import pathlib

JOBS = pathlib.Path("agentcy/jobs")
QUARANTINED_FROM = {"daily.py", "weekly.py", "event.py"}


def _module_level_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.col_offset == 0:
            names.add(node.module or "")
        elif isinstance(node, ast.Import) and node.col_offset == 0:
            names.update(a.name for a in node.names)
    return names


def test_daily_weekly_event_never_import_benchmark_or_quantstats():
    for name in QUARANTINED_FROM:
        mods = _module_level_imports(JOBS / name)
        assert not any("benchmark" in m for m in mods), f"{name} imports benchmark (invariant 7)"
        assert not any("quantstats" in m for m in mods), f"{name} imports quantstats (invariant 7)"


def test_only_quarterly_and_backup_reference_benchmark_at_all():
    for path in JOBS.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        if path.name in {"quarterly.py", "backup.py"}:
            continue
        assert "import benchmark" not in src and "from agentcy import benchmark" not in src, path.name


def test_no_job_selects_avg_open_price_except_quarterly_appendix():
    for path in JOBS.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        if "avg_open_price" in src:
            assert path.name == "quarterly.py", f"{path.name} references avg_open_price (invariant 4)"
        # even quarterly reaches it only via fetch_positions_records, never a raw column read:
        assert "SELECT avg_open_price" not in src and "avg_open_price FROM position" not in src


def test_full_suite_marker():
    """Documentation anchor: `uv run pytest -q` must be green at phase end."""
    assert True
