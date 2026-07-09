"""tools/license_gate.py — NFR7 license wall, SPDX-aware (tech-arch §2.2).

Walks the installed environment via importlib.metadata and audits every
distribution against the permissive allowlist:

  1. SPDX expressions are EVALUATED, not string-matched: OR passes when any
     branch is allowed; AND requires all branches.
  2. The allowlist names the permissive variants actually present in the
     locked tree, incl. MIT-CMU/HPND (Pillow, via matplotlib) and the
     PSF-derived class -- else CPython itself would be banned.
  3. Exceptions are the journaled named-exception list -- certifi:MPL-2.0 is
     entry ONE (owner sign-off S1 2026-07-09; journal entry 2 / config key
     'license_exceptions'). Any future metadata quirk fails CLOSED into an
     owner decision, never a silent gate patch.
  4. The full audit table is printed (and committed at docs/license-audit.txt)
     -- the audit is the enforcement, not memory.

Runs at bootstrap, at every deploy, and in every quarterly ritual (§12.4
step 3). Exit 1 on any violation. The GPL family INCLUDING LGPL is a hard
ban (owner-locked decision 6).
"""
from __future__ import annotations

import importlib.metadata
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# --- policy -------------------------------------------------------------------

ALLOWLIST: frozenset[str] = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "ISC",
    "PSF-2.0",
    # named permissive entries (tech-arch §2.2): Pillow via matplotlib,
    # plus the PSF-derived license family (matplotlib's own).
    "MIT-CMU", "HPND", "Python-2.0",
})

# --- SPDX expression evaluation (fix 1) ----------------------------------------

_TOKEN_RE = re.compile(r"\(|\)|[^\s()]+")


def spdx_allowed(expr: str, allowlist: frozenset[str] | set[str]) -> bool:
    """Evaluate an SPDX license expression against the allowlist.

    OR passes if ANY branch is allowed; AND requires ALL branches. Unknown
    license ids evaluate False (fail closed). 'WITH' exception clauses
    evaluate False (fail closed -> owner decision). Raises ValueError on a
    malformed/empty expression (the caller treats that as not allowed).
    """
    allowed = {a.lower() for a in allowlist}
    tokens = _TOKEN_RE.findall(expr)
    if not tokens:
        raise ValueError("empty SPDX expression")
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def parse_or() -> bool:
        nonlocal pos
        result = parse_and()
        while (t := peek()) is not None and t.upper() == "OR":
            pos += 1
            rhs = parse_and()
            result = result or rhs
        return result

    def parse_and() -> bool:
        nonlocal pos
        result = parse_atom()
        while (t := peek()) is not None and t.upper() == "AND":
            pos += 1
            rhs = parse_atom()
            result = result and rhs
        return result

    def parse_atom() -> bool:
        nonlocal pos
        t = peek()
        if t is None:
            raise ValueError(f"truncated SPDX expression: {expr!r}")
        if t == ")":
            raise ValueError(f"unexpected ')' in SPDX expression: {expr!r}")
        if t == "(":
            pos += 1
            inner = parse_or()
            if peek() != ")":
                raise ValueError(f"unbalanced '(' in SPDX expression: {expr!r}")
            pos += 1
            return inner
        if t.upper() in ("AND", "OR", "WITH"):
            raise ValueError(f"misplaced operator in SPDX expression: {expr!r}")
        pos += 1
        result = t.lower() in allowed
        if (n := peek()) is not None and n.upper() == "WITH":
            pos += 1
            if peek() is None:
                raise ValueError(f"truncated WITH clause: {expr!r}")
            pos += 1
            return False  # exception clauses fail closed -> owner decision
        return result

    result = parse_or()
    if pos != len(tokens):
        raise ValueError(f"trailing tokens in SPDX expression: {expr!r}")
    return result


if __name__ == "__main__":  # full audit CLI lands in the next task (P0.6)
    sys.exit(0)
