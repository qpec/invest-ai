"""prices.py — the price grid's missing producer (2026-08-06).

The grid was seeded once by hand and never refreshed, so these tests are mostly about
the two properties that keep a refresher honest: a failed fetch must not damage what is
already on disk, and freshness must be read from the CONTENTS, because a rate-limited
vendor produces a file that was written recently and learned nothing.
"""
import json

import pytest

import prices


class FakeVendor:
    name = "fake"
    price_basis = "raw"

    def __init__(self, bars=None, fail=()):
        # `is None`, not `or`: an EMPTY answer is a case under test, not a missing arg.
        self._bars = {"2026-08-01": {"close": 10.0}} if bars is None else bars
        self._fail = set(fail)
        self.asked = []

    def weekly(self, symbol, **kw):
        self.asked.append(symbol)
        if symbol in self._fail:
            raise RuntimeError("vendor said no")
        return dict(self._bars)

    def splits(self, symbol):
        return {}


@pytest.fixture
def vendor(monkeypatch):
    """pricesrc is imported lazily inside refresh(); patch the module object it gets."""
    import pricesrc
    made = FakeVendor()
    monkeypatch.setattr(pricesrc, "get", lambda source: made)
    return made


def write_grid(tmp_path, symbol, newest):
    path = tmp_path / f"{symbol}.json"
    path.write_text(json.dumps({"symbol": symbol, "bars": {newest: {"close": 1.0}}}))
    return path


def test_a_fresh_symbol_is_not_refetched(tmp_path, vendor):
    write_grid(tmp_path, "AAA", "2026-08-01")
    out = prices.refresh(tmp_path, ["AAA"], today="2026-08-06", log=lambda *_: None)
    assert vendor.asked == [] and out["fetched"] == 0


def test_a_stale_symbol_and_a_missing_one_are_both_fetched(tmp_path, vendor):
    write_grid(tmp_path, "OLD", "2026-01-01")
    out = prices.refresh(tmp_path, ["OLD", "NEW"], today="2026-08-06", log=lambda *_: None)
    assert set(vendor.asked) == {"OLD", "NEW"} and out["fetched"] == 2
    assert json.loads((tmp_path / "NEW.json").read_text())["price_basis"] == "raw"


def test_thesis_names_lead_the_queue_and_the_budget_cannot_cut_them(tmp_path, vendor):
    # Thesis names are graded against pre-committed triggers; a trigger tested on a stale
    # price is worse than one reported UNCHECKED, so the budget may never reach them.
    for i in range(5):
        write_grid(tmp_path, f"S{i}", "2020-01-01")
    prices.refresh(tmp_path, [f"S{i}" for i in range(5)], priority=["S4"], budget=1,
                   today="2026-08-06", log=lambda *_: None)
    assert vendor.asked[0] == "S4"


def test_a_failed_fetch_leaves_the_previous_file_untouched(tmp_path, monkeypatch):
    import pricesrc
    monkeypatch.setattr(pricesrc, "get", lambda source: FakeVendor(fail={"BAD"}))
    before = write_grid(tmp_path, "BAD", "2020-01-01").read_text()
    out = prices.refresh(tmp_path, ["BAD"], today="2026-08-06", log=lambda *_: None)
    assert out["failed"] == 1 and out["fetched"] == 0
    assert (tmp_path / "BAD.json").read_text() == before   # degrade the age, never the data


def test_an_empty_vendor_answer_is_a_failure_not_an_empty_grid(tmp_path, monkeypatch):
    import pricesrc
    monkeypatch.setattr(pricesrc, "get", lambda source: FakeVendor(bars={}))
    write_grid(tmp_path, "X", "2020-01-01")
    out = prices.refresh(tmp_path, ["X"], today="2026-08-06", log=lambda *_: None)
    assert out["failed"] == 1
    assert json.loads((tmp_path / "X.json").read_text())["bars"] == {"2020-01-01": {"close": 1.0}}


def test_freshness_is_read_from_the_bars_not_the_mtime(tmp_path):
    # A file rewritten a second ago whose newest bar is from 2020 is stale. Trusting the
    # mtime would mark a rate-limited no-op sweep as a successful one.
    path = write_grid(tmp_path, "X", "2020-01-01")
    assert prices.newest_bar(path) == "2020-01-01"
    assert prices.newest_bar(tmp_path / "missing.json") is None


def test_unreadable_and_empty_files_are_infinitely_stale(tmp_path, vendor):
    (tmp_path / "JUNK.json").write_text("{not json")
    (tmp_path / "EMPTY.json").write_text(json.dumps({"symbol": "EMPTY", "bars": {}}))
    prices.refresh(tmp_path, ["JUNK", "EMPTY"], today="2026-08-06", log=lambda *_: None)
    assert set(vendor.asked) == {"JUNK", "EMPTY"}


def test_thesis_symbols_reads_committed_and_drafts(tmp_path):
    for sub, sym in (("committed", "AAA"), ("drafts", "BBB"), ("drafts", "AAA")):
        d = tmp_path / sub
        d.mkdir(exist_ok=True)
        (d / f"{sym}.json").write_text("{}")
    assert prices.thesis_symbols(tmp_path) == ["AAA", "BBB"]     # committed first, deduped
    assert prices.thesis_symbols(None) == []
