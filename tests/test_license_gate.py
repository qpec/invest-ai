"""tools/license_gate.py — the executable NFR7 wall (tech-arch §2.2).
SPDX expressions are EVALUATED: OR passes if any branch is allowed, AND
requires all; unknown ids and WITH clauses fail closed."""
from __future__ import annotations

import pytest

from tools.license_gate import ALLOWLIST, spdx_allowed


def ok(expr: str) -> bool:
    return spdx_allowed(expr, ALLOWLIST)


def test_single_allowed():
    assert ok("MIT")
    assert ok("Apache-2.0")
    assert ok("BSD-3-Clause")


def test_named_permissive_entries_present():
    # §2.2 fix 2: MIT-CMU/HPND (Pillow via matplotlib) + PSF-class whitelisted
    assert ok("MIT-CMU")
    assert ok("HPND")
    assert ok("PSF-2.0")
    assert ok("Python-2.0")


def test_gpl_family_banned():
    assert not ok("GPL-2.0-only")
    assert not ok("GPL-3.0-only")
    assert not ok("LGPL-3.0-only")


def test_mpl_not_on_allowlist():
    # certifi passes only via the journaled exception (P0.6), never the allowlist
    assert not ok("MPL-2.0")


def test_or_passes_if_any_branch_allowed():
    assert ok("MIT OR GPL-2.0-only")
    assert ok("GPL-2.0-only OR MIT")
    assert ok("Apache-2.0 OR BSD-2-Clause")  # the packaging-style dual


def test_or_fails_if_no_branch_allowed():
    assert not ok("GPL-2.0-only OR LGPL-3.0-only")


def test_and_requires_all_branches():
    assert ok("Apache-2.0 AND MIT")
    assert not ok("MIT AND GPL-3.0-only")


def test_nested_parentheses():
    assert ok("(GPL-3.0-only OR MIT) AND BSD-3-Clause")
    assert not ok("(GPL-3.0-only OR LGPL-3.0-only) AND MIT")


def test_unknown_id_fails_closed():
    assert not ok("WTFPL")


def test_with_clause_fails_closed():
    assert not ok("Apache-2.0 WITH LLVM-exception")


def test_case_insensitive_ids():
    assert ok("mit")


def test_malformed_expression_raises():
    with pytest.raises(ValueError):
        spdx_allowed("(MIT", ALLOWLIST)
    with pytest.raises(ValueError):
        spdx_allowed("", ALLOWLIST)
    with pytest.raises(ValueError):
        spdx_allowed("MIT OR", ALLOWLIST)
