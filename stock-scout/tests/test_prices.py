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


class TestUnservableSymbols:
    """A symbol no vendor will serve writes no file, and "no file" is the same shape as
    "never fetched" — so it sorted to the front of the plan every single night, forever.
    Measured against the real universe: ~760-814 of 7,033 symbols are permanently
    unfetchable (delisted, foreign listings, pink sheets) against a nightly budget of 800,
    so the sweep would have spent most of every night re-failing the same dead names while
    exiting 0."""

    def test_a_failure_leaves_a_tombstone(self, tmp_path, monkeypatch):
        import pricesrc
        monkeypatch.setattr(pricesrc, "get", lambda s: FakeVendor(fail={"DEAD"}))
        prices.refresh(tmp_path, ["DEAD"], today="2026-08-06", log=lambda *_: None)
        assert (tmp_path / "DEAD.miss").read_text() == "2026-08-06"

    def test_a_tombstoned_symbol_is_not_retried_the_next_night(self, tmp_path, vendor):
        (tmp_path / "DEAD.miss").write_text("2026-08-06")
        prices.refresh(tmp_path, ["DEAD"], today="2026-08-07", log=lambda *_: None)
        assert vendor.asked == []

    def test_but_it_is_retried_after_a_month(self, tmp_path, vendor):
        (tmp_path / "DEAD.miss").write_text("2026-08-06")
        prices.refresh(tmp_path, ["DEAD"], today="2026-09-30", log=lambda *_: None)
        assert vendor.asked == ["DEAD"]

    def test_a_tombstone_never_parks_a_thesis_name(self, tmp_path, vendor):
        # Thesis names are graded against pre-committed triggers. They ride in `head`,
        # outside the staleness filter, so no tombstone may ever silence one.
        (tmp_path / "HELD.miss").write_text("2026-08-06")
        prices.refresh(tmp_path, ["HELD"], priority=["HELD"], today="2026-08-07",
                       log=lambda *_: None)
        assert vendor.asked == ["HELD"]

    def test_serving_again_clears_the_tombstone(self, tmp_path, vendor):
        (tmp_path / "BACK.miss").write_text("2026-01-01")     # expired, so it is retried
        prices.refresh(tmp_path, ["BACK"], today="2026-08-06", log=lambda *_: None)
        assert not (tmp_path / "BACK.miss").exists()

    def test_an_unreadable_tombstone_expires_rather_than_parking_the_symbol(self, tmp_path, vendor):
        (tmp_path / "X.miss").write_text("")
        prices.refresh(tmp_path, ["X"], today="2026-08-06", log=lambda *_: None)
        assert vendor.asked == ["X"]

    def test_tombstones_are_not_mistaken_for_price_files(self, tmp_path, vendor):
        (tmp_path / "DEAD.miss").write_text("2026-08-06")
        out = prices.refresh(tmp_path, ["DEAD"], today="2026-08-07", log=lambda *_: None)
        assert out["symbols"] == 0        # counts *.json only


class TestExitCodeIsTheAlarm:
    """systemd's OnFailure is the only channel that reaches an owner with no shell, so the
    exit code is the alarm. A sweep failing at least as much as it fetches is a grid that
    has stopped converging, and exit 0 would keep that invisible forever."""

    def test_mostly_failing_exits_nonzero(self, tmp_path, monkeypatch):
        import pricesrc
        monkeypatch.setattr(pricesrc, "get", lambda s: FakeVendor(fail={"A", "B"}))
        rc = prices.main(["refresh", "--grid", str(tmp_path), "--symbols", "A,B,C"])
        assert rc == 1

    def test_mostly_succeeding_exits_zero(self, tmp_path, monkeypatch):
        import pricesrc
        monkeypatch.setattr(pricesrc, "get", lambda s: FakeVendor(fail={"A"}))
        rc = prices.main(["refresh", "--grid", str(tmp_path), "--symbols", "A,B,C"])
        assert rc == 0

    def test_nothing_to_do_is_success(self, tmp_path, vendor):
        write_grid(tmp_path, "FRESH", "2026-08-01")
        rc = prices.main(["refresh", "--grid", str(tmp_path), "--symbols", "FRESH",
                          "--as-of", "2026-08-06"])
        assert rc == 0


class TestPriceBasisIsRecorded:
    """pricesrc exists to stop anyone assuming what a "close" is: a split-adjusted-today
    close read as as-traded understates a historical market cap by the whole split factor.
    The attribute is `basis`; asking for `price_basis` (as the first cut of this module did)
    returns None for every file, which pit.checked_basis reads back as "raw"."""

    def test_the_served_basis_reaches_the_file(self, tmp_path, monkeypatch):
        import pricesrc

        class Adjusted(FakeVendor):
            name = "stockanalysis"
            basis = pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY

        monkeypatch.setattr(pricesrc, "get", lambda s: Adjusted())
        prices.refresh(tmp_path, ["X"], today="2026-08-06", log=lambda *_: None)
        written = json.loads((tmp_path / "X.json").read_text())
        assert written["price_basis"] == pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY

    def test_the_ladder_is_asked_per_symbol_not_per_handle(self, tmp_path, monkeypatch):
        # A run is mixed by construction: the ladder steps down mid-run, so the handle's
        # LAST answer describes some other symbol. Recording it would label one vendor's
        # bars with another's basis.
        import pricesrc

        class Ladder(FakeVendor):
            name = "auto"
            basis = pricesrc.PRICE_BASIS_RAW           # the handle's "last" answer
            def basis_for(self, symbol):
                return (pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY if symbol == "A"
                        else pricesrc.PRICE_BASIS_RAW)

        monkeypatch.setattr(pricesrc, "get", lambda s: Ladder())
        prices.refresh(tmp_path, ["A", "B"], today="2026-08-06", log=lambda *_: None)
        assert json.loads((tmp_path / "A.json").read_text())["price_basis"] == \
            pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY
        assert json.loads((tmp_path / "B.json").read_text())["price_basis"] == \
            pricesrc.PRICE_BASIS_RAW

    def test_an_unknown_basis_raises_rather_than_defaulting(self, tmp_path, monkeypatch):
        # pit.checked_basis refuses an unrecognised declaration. Falling back to a default
        # is precisely the silent assumption this layer removes.
        import pricesrc

        class Weird(FakeVendor):
            basis = "who-knows"

        monkeypatch.setattr(pricesrc, "get", lambda s: Weird())
        out = prices.refresh(tmp_path, ["X"], today="2026-08-06", log=lambda *_: None)
        assert out["failed"] == 1 and not (tmp_path / "X.json").exists()
