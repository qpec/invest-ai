"""Shared pytest setup: make the flat stock-scout scripts (universe.py, scoring.py, ...)
importable from the tests directory without any package install (RECONSTRUCTION.md §2)."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
