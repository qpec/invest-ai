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


# --- journaled named-exception list (fix 3) -------------------------------------
# Entry ONE: certifi (MPL-2.0), owner-signed S1 2026-07-09, venv-wide
# (journal_entry 2; config key 'license_exceptions' = 'certifi:MPL-2.0').
# The pair is exact: a DIFFERENT non-allowed license on the same name is NOT
# covered (fail closed). Additions require a new journaled owner decision AND
# a matching config append -- never a silent edit here.
EXCEPTIONS: dict[str, str] = {
    "certifi": "MPL-2.0",
}

# First-party: the wall governs third-party code, not this repo.
SELF: frozenset[str] = frozenset({"stock-agentcy"})

# Legacy free-text License metadata -> SPDX id (exact known variants only;
# anything unlisted falls through to raw-SPDX evaluation and fails closed).
LICENSE_TEXT_MAP: dict[str, str] = {
    "mit": "MIT",
    "mit license": "MIT",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "bsd": "BSD-3-Clause",
    "bsd license": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "0bsd": "0BSD",
    "isc": "ISC",
    "isc license": "ISC",
    "psf": "PSF-2.0",
    "psf-2.0": "PSF-2.0",
    "python software foundation license": "PSF-2.0",
    "mit-cmu": "MIT-CMU",
    "hpnd": "HPND",
    "mpl-2.0": "MPL-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
}

# Trove classifier -> SPDX id. Multiple license classifiers are combined with
# AND (classifiers cannot express OR; AND is the fail-closed reading -- a
# genuine dual-license lights up as an owner decision, never a silent pass).
CLASSIFIER_MAP: dict[str, str] = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Historical Permission Notice and Disclaimer (HPND)": "HPND",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
}

_GPL_RE = re.compile(r"\b[AL]?GPL", re.IGNORECASE)


def _norm(name: str) -> str:
    """PEP 503 name normalization (case + -_. equivalence)."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class DistInfo:
    """One installed distribution's license-relevant metadata (test-injectable)."""
    name: str
    version: str
    license_expression: str | None = None   # PEP 639 License-Expression
    license_text: str | None = None         # legacy License field
    classifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditRow:
    name: str
    version: str
    license: str
    source: str
    verdict: str


def resolve_expression(d: DistInfo) -> tuple[str | None, str]:
    """(SPDX expression to evaluate, metadata source) -- or (None, 'missing')."""
    if d.license_expression and d.license_expression.strip():
        return d.license_expression.strip(), "License-Expression"
    text = (d.license_text or "").strip()
    if text and "\n" not in text and len(text) <= 100:
        mapped = LICENSE_TEXT_MAP.get(text.lower())
        if mapped:
            return mapped, "License"
        return text, "License(raw)"  # may itself be SPDX ('MIT OR GPL-2.0-only')
    ids = [CLASSIFIER_MAP[c] for c in d.classifiers if c in CLASSIFIER_MAP]
    if ids:
        return " AND ".join(dict.fromkeys(ids)), "Classifier"
    return None, "missing"


def _allowed(expr: str) -> bool:
    try:
        return spdx_allowed(expr, ALLOWLIST)
    except ValueError:
        return False  # malformed metadata fails closed


def audit(dists: Iterable[DistInfo]) -> list[AuditRow]:
    """Verdict per distribution: OK | EXCEPTION (journaled S1) | SELF | VIOLATION*."""
    rows: list[AuditRow] = []
    for d in sorted(dists, key=lambda x: x.name.lower()):
        if _norm(d.name) in SELF:
            rows.append(AuditRow(d.name, d.version, "(first-party)", "-", "SELF"))
            continue
        expr, source = resolve_expression(d)
        if expr is None:
            rows.append(AuditRow(d.name, d.version, "(no license metadata)", source, "VIOLATION"))
            continue
        if _allowed(expr):
            verdict = "OK"
        else:
            expected = EXCEPTIONS.get(_norm(d.name))
            if expected is not None and expr.strip().lower() == expected.lower():
                verdict = "EXCEPTION (journaled S1)"
            elif _GPL_RE.search(expr):
                verdict = "VIOLATION (GPL family -- hard ban)"
            else:
                verdict = "VIOLATION"
        rows.append(AuditRow(d.name, d.version, expr, source, verdict))
    return rows


def format_table(rows: Sequence[AuditRow]) -> str:
    header = ("PACKAGE", "VERSION", "LICENSE", "SOURCE", "VERDICT")
    table = [header] + [(r.name, r.version, r.license, r.source, r.verdict) for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(5)]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
             for row in table]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def collect_installed() -> list[DistInfo]:
    """The importlib.metadata walk over the full installed set (fail-closed on
    unreadable metadata: such a dist becomes a VIOLATION row via missing fields)."""
    out: list[DistInfo] = []
    for dist in importlib.metadata.distributions():
        md = dist.metadata
        name = (md.get("Name") if md else None) or "UNKNOWN"
        try:
            version = dist.version or "?"
        except Exception:
            version = "?"
        out.append(DistInfo(
            name=name,
            version=version,
            license_expression=md.get("License-Expression") if md else None,
            license_text=md.get("License") if md else None,
            classifiers=tuple(md.get_all("Classifier") or ()) if md else (),
        ))
    return out


def main(argv: list[str] | None = None) -> int:
    rows = audit(collect_installed())
    print(format_table(rows))
    violations = [r for r in rows if r.verdict.startswith("VIOLATION")]
    exceptions = [r for r in rows if r.verdict.startswith("EXCEPTION")]
    if violations:
        print(f"\nLICENSE GATE: {len(violations)} violation(s) -- the wall holds; "
              f"owner decision required (tech-arch 2.2). Do NOT patch the allowlist.")
        return 1
    print(f"\nLICENSE GATE: clean -- {sum(r.verdict == 'OK' for r in rows)} allowed, "
          f"{len(exceptions)} journaled exception(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
