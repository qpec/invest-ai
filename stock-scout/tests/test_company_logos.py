from __future__ import annotations

import company_logos


PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 80


def test_sync_downloads_valid_image_and_writes_index(tmp_path):
    def fetch(url, timeout):
        assert url.endswith("/AAA.png") and timeout == 10
        return 200, "image/png", PNG

    result = company_logos.sync(["AAA"], tmp_path, fetch=fetch)

    assert result == {"AAA": "logos/AAA.png"}
    assert (tmp_path / "logos" / "AAA.png").read_bytes() == PNG


def test_sync_uses_initials_fallback_for_bad_response(tmp_path):
    result = company_logos.sync(
        ["BAD"], tmp_path,
        fetch=lambda *_: (200, "text/html", b"not an image"),
    )

    assert result == {"BAD": None}


def test_sync_reuses_valid_cached_file_without_network(tmp_path):
    target = tmp_path / "logos" / "AAA.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(PNG)

    result = company_logos.sync(
        ["AAA"], tmp_path,
        fetch=lambda *_: (_ for _ in ()).throw(AssertionError("network called")),
    )

    assert result["AAA"] == "logos/AAA.png"


def test_sync_rejects_unsafe_symbol_without_network(tmp_path):
    result = company_logos.sync(
        ["../BAD"], tmp_path,
        fetch=lambda *_: (_ for _ in ()).throw(AssertionError("network called")),
    )

    assert result == {"../BAD": None}


def test_valid_image_rejects_oversize_and_magic_mismatch():
    assert not company_logos.valid_image("image/png", b"x" * 100)
    assert not company_logos.valid_image("image/png", PNG + b"x" * 2_000_000)
