"""AST import-graph walker (tech-arch §13) — shared by P1 and every later phase's
structural tests. No module is ever imported; pure source analysis."""
from __future__ import annotations

import ast
import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1] / "agentcy"


def module_name(path: Path, root: Path = PKG_ROOT) -> str:
    rel = path.relative_to(root.parent)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def iter_modules(root: Path = PKG_ROOT) -> dict[str, Path]:
    """{'agentcy.db': Path(...), ...} for every .py under the package."""
    return {module_name(p, root): p for p in sorted(root.rglob("*.py"))}


def imports_of(path: Path, root: Path = PKG_ROOT) -> set[str]:
    """Absolute module names imported by the file; relative imports resolved;
    'from X import Y' records both X and X.Y (Y may be a submodule)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mod_parts = module_name(path, root).split(".")
    if path.name != "__init__.py":
        pkg_parts = mod_parts[:-1]
    else:
        pkg_parts = mod_parts
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                stem = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                stem = node.module or ""
            if stem:
                out.add(stem)
            for alias in node.names:
                if stem:
                    out.add(f"{stem}.{alias.name}")
    return out


def import_graph(root: Path = PKG_ROOT) -> dict[str, set[str]]:
    return {m: imports_of(p, root) for m, p in iter_modules(root).items()}


def _hits(imports: set[str], target: str) -> bool:
    return any(i == target or i.startswith(target + ".") for i in imports)


def importers_of(target: str, root: Path = PKG_ROOT) -> set[str]:
    """Modules directly importing target (or a submodule of it)."""
    return {m for m, imps in import_graph(root).items() if _hits(imps, target)}


def transitive_importers(target: str, root: Path = PKG_ROOT) -> set[str]:
    """Every module from which target is reachable through the package's import edges."""
    graph = import_graph(root)
    result = {m for m, imps in graph.items() if _hits(imps, target)}
    changed = True
    while changed:
        changed = False
        for m, imps in graph.items():
            if m in result:
                continue
            if any(_hits(imps, r) for r in result):
                result.add(m)
                changed = True
    return result


def source_scan(pattern: str, root: Path = PKG_ROOT) -> set[str]:
    """Module names whose source matches the regex (case-insensitive) — e.g. ATTACH."""
    rx = re.compile(pattern, re.IGNORECASE)
    return {m for m, p in iter_modules(root).items()
            if rx.search(p.read_text(encoding="utf-8"))}
