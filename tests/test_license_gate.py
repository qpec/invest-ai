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


# --- audit over distribution metadata (fakes; the walk itself is injected) -----

from tools.license_gate import DistInfo, audit, format_table, main  # noqa: E402


def d(name: str, **kw) -> DistInfo:
    return DistInfo(name=name, version="1.0", **kw)


def test_ok_via_license_expression():
    (row,) = audit([d("pandas", license_expression="BSD-3-Clause")])
    assert row.verdict == "OK"


def test_ok_via_dual_or_expression():
    (row,) = audit([d("packaging", license_expression="Apache-2.0 OR BSD-2-Clause")])
    assert row.verdict == "OK"


def test_ok_via_license_text_variant():
    (row,) = audit([d("legacy", license_text="Apache Software License")])
    assert row.verdict == "OK"


def test_ok_via_raw_spdx_license_text():
    (row,) = audit([d("thing", license_text="MIT OR GPL-2.0-only")])
    assert row.verdict == "OK"


def test_ok_via_classifier_fallback():
    (row,) = audit([d("bs4ish", classifiers=("License :: OSI Approved :: MIT License",))])
    assert row.verdict == "OK"


def test_multiline_license_text_skipped_classifier_wins():
    (row,) = audit([d("verbose",
                      license_text="Permission is hereby granted...\n(full text)",
                      classifiers=("License :: OSI Approved :: MIT License",))])
    assert row.verdict == "OK"


def test_multiple_classifiers_conservative_and():
    # classifiers cannot express OR; AND is the fail-closed reading
    (row,) = audit([d("dualbad", classifiers=(
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    ))])
    assert row.verdict.startswith("VIOLATION")


def test_certifi_exception_journaled():
    (row,) = audit([d("certifi", license_text="MPL-2.0")])
    assert row.verdict == "EXCEPTION (journaled S1)"


def test_exception_rows_cite_distinct_correct_bases():
    # A committed governance record: each journaled exception must cite ITS OWN
    # basis. certifi is the certifi/MPL-2.0 owner sign-off S1; peewee is a
    # DIFFERENT, newer owner decision (the license-wall resolution of 2026-07-09).
    (certifi_row,) = audit([d("certifi", license_text="MPL-2.0")])
    (peewee_row,) = audit([d("peewee")])
    assert certifi_row.verdict.startswith("EXCEPTION (")
    assert peewee_row.verdict.startswith("EXCEPTION (")
    # distinct
    assert certifi_row.verdict != peewee_row.verdict
    # correct, per-package bases
    assert "S1" in certifi_row.verdict
    assert "2026-07-09" in peewee_row.verdict
    assert peewee_row.verdict == "EXCEPTION (owner 2026-07-09)"


def test_exception_is_a_name_license_pair_not_a_blanket():
    # if certifi ever ships under a different non-allowed license, S1 does NOT cover it
    (row,) = audit([d("certifi", license_expression="GPL-3.0-only")])
    assert row.verdict.startswith("VIOLATION")


def test_other_mpl_package_is_violation():
    (row,) = audit([d("some-mpl-pkg", license_expression="MPL-2.0")])
    assert row.verdict == "VIOLATION"


def test_gpl_family_annotated_hard_ban():
    (row,) = audit([d("python-telegram-bot", license_expression="LGPL-3.0-only")])
    assert row.verdict == "VIOLATION (GPL family -- hard ban)"


def test_no_license_metadata_fails_closed():
    (row,) = audit([d("mystery")])
    assert row.verdict == "VIOLATION"
    assert "no license metadata" in row.license


def test_first_party_skipped():
    (row,) = audit([d("stock-agentcy")])
    assert row.verdict == "SELF"


def test_rows_sorted_by_name():
    rows = audit([d("zeta", license_expression="MIT"), d("alpha", license_expression="MIT")])
    assert [r.name for r in rows] == ["alpha", "zeta"]


def test_main_clean_exit_zero(monkeypatch, capsys):
    import tools.license_gate as lg
    monkeypatch.setattr(lg, "collect_installed", lambda: [
        d("pandas", license_expression="BSD-3-Clause"),
        d("certifi", license_text="MPL-2.0"),
    ])
    assert lg.main([]) == 0
    out = capsys.readouterr().out
    assert "PACKAGE" in out and "pandas" in out and "certifi" in out
    assert "LICENSE GATE: clean" in out
    assert "1 journaled exception(s)" in out


def test_main_violation_exit_one(monkeypatch, capsys):
    import tools.license_gate as lg
    monkeypatch.setattr(lg, "collect_installed", lambda: [
        d("badpkg", license_expression="GPL-3.0-only"),
    ])
    assert lg.main([]) == 1
    out = capsys.readouterr().out
    assert "VIOLATION" in out
    assert "owner decision required" in out


# --- owner decision 2026-07-09: the six ratified permissive resolutions ---------
# yfinance/multitasking/python-dateutil (non-SPDX free-text License masking
# permissive classifiers), cffi (MIT-0), numpy (Zlib/CC0-1.0), peewee (no
# metadata). The wall must resolve these to PASS while still biting copyleft.


def test_classifier_precedence_free_text_apache_masks_classifier():
    # yfinance / multitasking: License="Apache" (not a valid SPDX id) but the
    # OSI classifier says Apache -> resolve via classifier, PASS.
    (row,) = audit([d("yfinance",
                      license_text="Apache",
                      classifiers=("License :: OSI Approved :: Apache Software License",))])
    assert row.verdict == "OK"
    assert row.source == "Classifier"


def test_classifier_precedence_dual_license_free_text_masks_classifiers():
    # python-dateutil: License="Dual License" (not SPDX) with BSD + Apache
    # classifiers -> both permissive -> PASS.
    (row,) = audit([d("python-dateutil",
                      license_text="Dual License",
                      classifiers=(
                          "License :: OSI Approved :: BSD License",
                          "License :: OSI Approved :: Apache Software License",
                      ))])
    assert row.verdict == "OK"
    assert row.source == "Classifier"


def test_license_expression_mit0_allowed():
    # cffi: License-Expression = MIT-0 (valid SPDX; MIT No Attribution).
    (row,) = audit([d("cffi", license_expression="MIT-0")])
    assert row.verdict == "OK"


def test_numpy_and_expression_allowed():
    # numpy: the exact locked AND-expression, incl. Zlib and CC0-1.0.
    (row,) = audit([d("numpy",
                      license_expression="BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0")])
    assert row.verdict == "OK"


def test_peewee_named_exception_no_metadata():
    # peewee: ships NO license metadata; MIT upstream -> named exception.
    (row,) = audit([d("peewee")])
    assert row.verdict.startswith("EXCEPTION")


# --- the wall must still bite (negatives) --------------------------------------


def test_gpl_classifier_still_fails():
    (row,) = audit([d("gplpkg",
                      classifiers=("License :: OSI Approved :: "
                                   "GNU General Public License v3 (GPLv3)",))])
    assert row.verdict.startswith("VIOLATION")


def test_non_spdx_free_text_with_gpl_classifier_fails():
    # non-SPDX free-text License must NOT be taken verbatim, but a GPL
    # classifier alongside it must still FAIL (every classifier must be allowed).
    (row,) = audit([d("sneaky",
                      license_text="Free For All",
                      classifiers=(
                          "License :: OSI Approved :: BSD License",
                          "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
                      ))])
    assert row.verdict.startswith("VIOLATION")


def test_absent_metadata_not_in_exception_list_fails():
    (row,) = audit([d("mystery-no-meta")])
    assert row.verdict == "VIOLATION"
    assert "no license metadata" in row.license


def test_unknown_spdx_id_still_fails():
    (row,) = audit([d("weird", license_expression="WTFPL")])
    assert row.verdict.startswith("VIOLATION")


def test_free_text_non_spdx_no_classifier_fails_closed():
    # "Apache" free text alone with NO classifier must not resolve to Apache-2.0.
    (row,) = audit([d("orphan", license_text="Apache")])
    assert row.verdict.startswith("VIOLATION")
