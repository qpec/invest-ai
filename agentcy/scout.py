"""The Scout (H) — idea generation, strictly human-triggered (FR14).

Universe: direct bz2 read of FinanceDatabase's equities file (pinned-SHA, ~3 lines
of pandas — NOT the pip package, NFR7). Screen: QV recipe via a lazy `[scout]`
import. Results are human-read and NEVER persisted as monitoring state (H).
"""
from __future__ import annotations

import bz2
import hashlib
import io
from pathlib import Path

import pandas as pd


class UniverseSHAError(Exception):
    """H.1 — the universe file's SHA-256 does not match the pinned config value;
    an unpinned or tampered file is never trusted."""


def load_universe(path: Path, *, expect_sha: str) -> pd.DataFrame:
    """H.1 — read equities.bz2 directly, verifying SHA-256 against the pin first.
    Empty pin or mismatch raises UniverseSHAError (never a silent pass)."""
    path = Path(path)
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if not expect_sha or actual != expect_sha:
        raise UniverseSHAError(
            f"universe SHA mismatch: file {actual}, pinned '{expect_sha}'. "
            "Set config universe_pin_sha to the verified commit's file hash (H.1).")
    return pd.read_csv(io.BytesIO(bz2.decompress(raw)))
