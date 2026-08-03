"""pricesrc.py — the pluggable weekly price sources and their declared bases (§3.6).

Everything here runs offline: `pricesrc._http_get` (the module's one network touch) and
`pricesrc._yf_fetch` (its one vendor import) are the two seams, and the autouse fixture
below wires the first of them to a tripwire so a test that forgets to script a response
fails loudly instead of reaching stockanalysis.com.

What has to be proven is the CONTRACT, not a vendor's arithmetic: the §3.6 bar map that
comes out of each payload shape, that every source says what basis its closes are in, that
an unhonored range is refused before it can silently truncate ten years of history to 52
bars, and that the auto ladder falls back — and says who served.
"""
import json
import urllib.error
from types import SimpleNamespace

import pandas as pd
import pytest

import pit
import pricesrc


# ------------------------------------------------------------------ fixture builders

def row(day, close, adj=None, **extra):
    """One stockanalysis history row (`a` defaults to `c`, as it does on a bar with no
    dividend since); `extra` overwrites, so a test can null or corrupt a single field."""
    out = {"t": day, "o": 1.0, "h": 2.0, "l": 0.5, "c": close,
           "a": close if adj is None else adj, "v": 1_000, "ch": 0.1}
    out.update(extra)
    return out


def history(rows, status=200):
    """The vendor envelope: newest-first rows under `data`, status repeated in the body."""
    return {"status": status, "data": list(rows)}


def frame_of(rows, *, raw=True, splits=None):
    """rows = [(day, close, adj_close)] -> a vendor weekly frame (DatetimeIndex). `raw`
    off drops the `close` column, the shape today's fetch_weekly_bars actually returns;
    `splits` adds the normalized `split` column with one ratio per row."""
    index = pd.DatetimeIndex([pd.Timestamp(day) for day, *_ in rows])
    data = {"adj_close": [adj for _, _c, adj in rows]}
    if raw:
        data["close"] = [close for _, close, _a in rows]
    if splits is not None:
        data["split"] = list(splits)
    return pd.DataFrame(data, index=index)


class Http:
    """A scripted stand-in for `pricesrc._http_get`. Records every URL asked for and
    replays the scripted responses in order (bytes/dicts are returned, exceptions raised);
    the last entry repeats, so a one-item script answers every call the same way."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        item = self.responses[min(len(self.urls) - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, bytes) else json.dumps(item).encode()


def http_error(code, url="https://stockanalysis.com/api"):
    return urllib.error.HTTPError(url, code, f"status {code}", {}, None)


class StubFetchFailed(Exception):
    """The vendor's OWN error class — distinct from pricesrc's, so the translation into
    this module's hierarchy is proven rather than assumed."""


class StubRateLimited(StubFetchFailed):
    pass


def stub_vendor(frame=None, error=None):
    """A stand-in for `vendor.yf_fetch`: `fetch_weekly_bars` records its arguments and
    either raises `error` or returns `frame`."""
    calls = []

    def fetch_weekly_bars(symbol, *, period, state_dir):
        calls.append({"symbol": symbol, "period": period, "state_dir": state_dir})
        if error is not None:
            raise error
        return frame

    return SimpleNamespace(fetch_weekly_bars=fetch_weekly_bars, calls=calls,
                           FetchFailed=StubFetchFailed, RateLimited=StubRateLimited)


class ScriptedSource(pricesrc.PriceSource):
    """A registrable source that serves a fixed bar map or raises a fixed error — the only
    way to drive the auto ladder through error combinations the real sources cannot both
    produce (two NotFounds, or two different kinds)."""

    def __init__(self, name, basis, *, bars=None, splits=None, error=None):
        self.name, self.basis = name, basis
        self._bars, self._splits, self._error = bars or {}, splits or {}, error
        self.calls = []

    def weekly(self, symbol, *, start=None, state_dir=None):
        self.calls.append(symbol)
        if self._error is not None:
            raise self._error
        return dict(self._bars)

    def splits(self, symbol):
        return dict(self._splits)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No pacing, no backoff sleeps, and a tripwire on the network seam: a test that does
    not script `_http_get` must fail rather than reach the vendor."""
    def tripwire(url):
        raise AssertionError(f"the suite never touches the network (asked for {url})")

    monkeypatch.setattr(pricesrc, "PACE_SECONDS", 0.0)
    monkeypatch.setattr(pricesrc, "RETRY_BACKOFF", (0.0, 0.0))
    monkeypatch.setattr(pricesrc, "_http_get", tripwire)


def serve(monkeypatch, *responses):
    """Script `_http_get` and hand the recorder back."""
    http = Http(*responses)
    monkeypatch.setattr(pricesrc, "_http_get", http)
    return http


# --------------------------------------------------- payload -> the §3.6 bar map

def test_newest_first_payload_becomes_an_ascending_bar_map():
    bars = pricesrc.bars_from_history(history([row("2026-07-27", 334.54),
                                               row("2026-07-20", 320.0),
                                               row("2026-07-13", 310.0)]))
    assert list(bars) == ["2026-07-13", "2026-07-20", "2026-07-27"]
    assert bars["2026-07-27"] == {"close": 334.54, "adj_close": 334.54}


def test_c_becomes_close_and_a_becomes_adj_close():
    """`c` is split-adjusted to today (the basis says so) and is the field a share count
    multiplies; `a` is split AND dividend adjusted and is the total-return field (§3.6)."""
    bars = pricesrc.bars_from_history(history([row("2026-07-27", 100.0, adj=99.0)]))
    assert bars["2026-07-27"] == {pricesrc.RAW_FIELD: 100.0, pricesrc.ADJ_FIELD: 99.0}
    assert (pricesrc.RAW_FIELD, pricesrc.ADJ_FIELD) == pit.PRICE_FIELDS


@pytest.mark.parametrize("bad", [
    {"c": "n/a", "a": "n/a"},        # non-numeric
    {"c": None, "a": None},          # missing
    {"c": 0.0, "a": 0.0},            # a zero close is not a price
    {"c": -3.0, "a": -3.0},          # nor a negative one
    {"t": ""},                       # no date
    {"t": "not-a-day"},              # unparseable date, never guessed
])
def test_unusable_rows_are_dropped_never_zero_filled(bad):
    bars = pricesrc.bars_from_history(history([row("2026-07-27", 100.0),
                                               row("2026-07-20", 90.0, **bad)]))
    assert bars == {"2026-07-27": {"close": 100.0, "adj_close": 100.0}}


def test_row_with_one_usable_price_is_written_on_that_field_alone():
    """The §3.6 degraded bar: `pit.bar_value` falls back to the other field, and
    `pit.grid_is_degraded` can still see that the raw close was never there — which a
    fabricated second price would have hidden."""
    bars = pricesrc.bars_from_history(history([row("2026-07-27", 100.0, adj="n/a"),
                                               row("2026-07-20", None, adj=90.0)]))
    assert bars == {"2026-07-20": {"adj_close": 90.0}, "2026-07-27": {"close": 100.0}}
    assert pit.bar_value(bars["2026-07-20"], "close") == 90.0
    assert pit.grid_is_degraded(bars) is True


def test_start_drops_earlier_bars():
    bars = pricesrc.bars_from_history(
        history([row("2026-07-27", 3.0), row("2026-07-20", 2.0), row("2026-07-13", 1.0)]),
        start="2026-07-20")
    assert list(bars) == ["2026-07-20", "2026-07-27"]


def test_payload_that_leaves_no_usable_bar_is_a_failure():
    with pytest.raises(pricesrc.FetchFailed, match="no usable weekly bars"):
        pricesrc.bars_from_history(history([row("2026-07-27", "n/a", adj=None)]),
                                   symbol="ADBE")


# ------------------------------------------------------------------ declared basis

def test_every_source_declares_its_basis():
    assert pricesrc.get("yahoo").basis == pricesrc.PRICE_BASIS_RAW
    assert pricesrc.get("stockanalysis").basis == pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY
    assert set(pricesrc.PRICE_BASES) == {pricesrc.PRICE_BASIS_RAW,
                                         pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY}
    assert pricesrc.PRICE_BASIS_RAW != pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY


def test_stockanalysis_reports_no_splits():
    """No split feed there — {} means "none known", never a fake ratio (§3.6). A caller
    pairing these split-adjusted-to-today closes with as-reported share counts must restate
    the counts itself (scoring.adjusted_shares_series)."""
    assert pricesrc.get("stockanalysis").splits("ADBE") == {}


# ------------------------------------------------------------------- the range guard

@pytest.mark.parametrize("span", ["MAX", "ALL", "20Y", "1M", "10y", ""])
def test_unhonored_ranges_are_rejected_loudly(span):
    """The API does not fail on an unknown range — it silently answers 52 weekly bars, so
    a run asking for ten years would grade on one. The allowlist is the whole guard."""
    with pytest.raises(ValueError, match="52 weekly bars"):
        pricesrc.StockAnalysisSource(span)


@pytest.mark.parametrize("span", pricesrc.STOCKANALYSIS_SPANS)
def test_honored_ranges_are_accepted_and_reach_the_url(span):
    assert f"range={span}" in pricesrc.StockAnalysisSource(span).url("ADBE")


def test_the_default_span_is_honored_and_the_agent_is_a_browser_agent():
    assert pricesrc.DEFAULT_SPAN in pricesrc.STOCKANALYSIS_SPANS
    assert pricesrc.USER_AGENT.startswith("Mozilla/5.0")   # the API answers 403 without one


# ------------------------------------------------------------------------ URL shape

def test_dotted_symbol_travels_verbatim_and_a_slash_cannot_reshape_the_url(monkeypatch):
    http = serve(monkeypatch, history([row("2026-07-27", 100.0)]))
    source = pricesrc.get("stockanalysis")
    source.weekly("BRK.B")
    assert http.urls == ["https://stockanalysis.com/api/symbol/s/BRK.B/history"
                         f"?range={source.span}&period=Weekly"]
    assert "%2F" in source.url("BRK/B") and "/BRK/B/" not in source.url("BRK/B")


# -------------------------------------------------------------------- vendor failures

@pytest.mark.parametrize("code", pricesrc.NOT_FOUND_CODES)
def test_unknown_symbol_is_not_found_and_is_never_retried(monkeypatch, code):
    """404 is the documented answer; 400 "Unknown error" is what the API actually returns
    for a symbol it does not know (verified). Neither is worth a retry."""
    http = serve(monkeypatch, http_error(code))
    with pytest.raises(pricesrc.NotFound):
        pricesrc.get("stockanalysis").weekly("NOTAREAL")
    assert len(http.urls) == 1


def test_in_band_status_is_honored_like_the_http_one(monkeypatch):
    serve(monkeypatch, {"status": 400, "message": "Unknown error"})
    with pytest.raises(pricesrc.NotFound, match="Unknown error"):
        pricesrc.get("stockanalysis").weekly("NOTAREAL")


def test_in_band_server_error_is_a_plain_failure(monkeypatch):
    serve(monkeypatch, {"status": 500, "message": "boom"})
    with pytest.raises(pricesrc.FetchFailed) as caught:
        pricesrc.get("stockanalysis").weekly("ADBE")
    assert not isinstance(caught.value, pricesrc.NotFound)


@pytest.mark.parametrize("payload", [history([]), {"status": 200}, {"status": 200, "data": {}},
                                     []], ids=["no-rows", "no-data-key", "data-not-a-list",
                                               "payload-not-an-object"])
def test_empty_is_failure(monkeypatch, payload):
    serve(monkeypatch, payload)
    with pytest.raises(pricesrc.FetchFailed) as caught:
        pricesrc.get("stockanalysis").weekly("ADBE")
    assert not isinstance(caught.value, pricesrc.NotFound)


def test_a_body_that_is_not_json_fails_on_the_spot(monkeypatch):
    """A contract violation, not bad luck: retrying an HTML error page buys nothing."""
    http = serve(monkeypatch, b"<html>rate limited</html>")
    with pytest.raises(pricesrc.FetchFailed, match="not JSON"):
        pricesrc.get("stockanalysis").weekly("ADBE")
    assert len(http.urls) == 1


def test_rejected_user_agent_is_named_in_the_error(monkeypatch):
    http = serve(monkeypatch, http_error(403))
    with pytest.raises(pricesrc.FetchFailed, match="User-Agent"):
        pricesrc.get("stockanalysis").weekly("ADBE")
    assert len(http.urls) == 1


def test_transient_error_is_retried_then_raised(monkeypatch):
    http = serve(monkeypatch, http_error(503))
    with pytest.raises(pricesrc.FetchFailed, match="attempts failed"):
        pricesrc.get("stockanalysis").weekly("ADBE")
    assert len(http.urls) == len(pricesrc.RETRY_BACKOFF) + 1


def test_transient_error_that_clears_is_served(monkeypatch):
    http = serve(monkeypatch, urllib.error.URLError("connection reset"),
                 history([row("2026-07-27", 100.0)]))
    assert pricesrc.get("stockanalysis").weekly("ADBE") == {
        "2026-07-27": {"close": 100.0, "adj_close": 100.0}}
    assert len(http.urls) == 2


def test_a_throttle_that_survives_the_ladder_is_rate_limited(monkeypatch):
    """RateLimited rather than a plain failure, so the auto ladder can retire the source
    instead of paying the ladder again on every remaining symbol."""
    serve(monkeypatch, http_error(429))
    with pytest.raises(pricesrc.RateLimited):
        pricesrc.get("stockanalysis").weekly("ADBE")


# --------------------------------------------------------------------- yahoo source

def test_yahoo_frame_becomes_a_bar_map_and_declares_the_raw_basis(monkeypatch):
    vendor = stub_vendor(frame_of([("2026-07-20", 90.0, 89.0), ("2026-07-27", 100.0, 99.0)]))
    monkeypatch.setattr(pricesrc, "_yf_fetch", lambda: vendor)
    source = pricesrc.YahooSource()
    assert source.weekly("ADBE", state_dir="/tmp/state") == {
        "2026-07-20": {"close": 90.0, "adj_close": 89.0},
        "2026-07-27": {"close": 100.0, "adj_close": 99.0}}
    assert source.basis == pricesrc.PRICE_BASIS_RAW
    assert vendor.calls[0]["state_dir"].name == "state"


def test_yahoo_adjusted_only_frame_stays_adjusted_only(monkeypatch):
    """Today's fetch_weekly_bars returns Adj Close alone; that is a degraded §3.6 grid and
    must read as one, not as a raw close it never had."""
    vendor = stub_vendor(frame_of([("2026-07-27", None, 99.0)], raw=False))
    monkeypatch.setattr(pricesrc, "_yf_fetch", lambda: vendor)
    bars = pricesrc.YahooSource().weekly("ADBE")
    assert bars == {"2026-07-27": {"adj_close": 99.0}}
    assert pit.grid_is_degraded(bars) is True


def test_yahoo_splits_ride_the_same_fetch(monkeypatch):
    vendor = stub_vendor(frame_of([("2026-07-20", 90.0, 90.0), ("2026-07-27", 100.0, 100.0)],
                                  splits=[0.0, 2.0]))
    monkeypatch.setattr(pricesrc, "_yf_fetch", lambda: vendor)
    source = pricesrc.YahooSource()
    source.weekly("ADBE")
    assert source.splits("ADBE") == {"2026-07-27": 2.0}      # the 0.0 week is not a ratio
    assert source.splits("MSFT") == {}                       # never fetched, never invented
    assert len(vendor.calls) == 1                            # no second Yahoo call (§3.6)


@pytest.mark.parametrize("raised, expected", [
    (StubRateLimited("429 after the ladder"), pricesrc.RateLimited),
    (StubFetchFailed("empty price frame"), pricesrc.FetchFailed),
])
def test_yahoo_translates_vendor_errors_into_this_hierarchy(monkeypatch, raised, expected):
    monkeypatch.setattr(pricesrc, "_yf_fetch", lambda: stub_vendor(error=raised))
    with pytest.raises(expected):
        pricesrc.YahooSource().weekly("ADBE")


def test_an_error_escaping_yfinance_is_still_a_refusal_to_serve(monkeypatch):
    """Observed live: yfinance raises curl_cffi's SSLError straight past vendor.yf_fetch's
    declared contract. Untranslated it aborts the run the fallback exists to save, so it
    becomes a FetchFailed — with its class named, so a real bug stays visible."""
    monkeypatch.setattr(pricesrc, "_yf_fetch",
                        lambda: stub_vendor(error=OSError("connection reset by peer")))
    with pytest.raises(pricesrc.FetchFailed, match="OSError escaped yfinance"):
        pricesrc.YahooSource().weekly("ADBE")


def test_yahoo_is_a_failure_where_yfinance_cannot_be_imported(monkeypatch):
    """The module itself imports fine on such a box — that box is why stockanalysis
    exists — and the Yahoo source simply refuses to serve, like any other failure."""

    def unusable():
        raise ImportError("No module named 'yfinance'")

    monkeypatch.setattr(pricesrc, "_yf_fetch", unusable)
    with pytest.raises(pricesrc.FetchFailed, match="unusable"):
        pricesrc.YahooSource().weekly("ADBE")


def test_no_vendor_import_at_module_scope():
    assert not {"yfinance", "yf_fetch"} & set(vars(pricesrc))


# ------------------------------------------------------------------------ auto ladder

def test_auto_prefers_yahoo_and_reports_who_served(monkeypatch):
    vendor = stub_vendor(frame_of([("2026-07-27", 100.0, 99.0)]))
    monkeypatch.setattr(pricesrc, "_yf_fetch", lambda: vendor)
    auto = pricesrc.get("auto")
    assert auto.basis is None                        # nothing served yet: no basis to claim
    assert auto.weekly("ADBE") == {"2026-07-27": {"close": 100.0, "adj_close": 99.0}}
    assert auto.served.name == "yahoo"
    assert auto.basis == pricesrc.PRICE_BASIS_RAW


def test_auto_falls_back_to_stockanalysis_when_yahoo_is_rate_limited(monkeypatch):
    monkeypatch.setattr(pricesrc, "_yf_fetch",
                        lambda: stub_vendor(error=StubRateLimited("429")))
    serve(monkeypatch, history([row("2026-07-27", 334.54)]))
    auto = pricesrc.get("auto")
    assert auto.weekly("ADBE") == {"2026-07-27": {"close": 334.54, "adj_close": 334.54}}
    assert auto.served.name == "stockanalysis"
    assert auto.basis == pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY


def test_a_rate_limit_retires_the_source_for_the_rest_of_the_run(monkeypatch):
    """Yahoo's own ladder costs 30 s -> 5 min -> 30 min; paying it again per symbol is the
    difference between a run and a hang."""
    vendor = stub_vendor(error=StubRateLimited("429"))
    monkeypatch.setattr(pricesrc, "_yf_fetch", lambda: vendor)
    serve(monkeypatch, history([row("2026-07-27", 100.0)]))
    auto = pricesrc.get("auto")
    auto.weekly("ADBE")
    auto.weekly("MSFT")
    assert len(vendor.calls) == 1


def test_a_plain_failure_retires_nothing(monkeypatch):
    """A FetchFailed is usually about the one symbol, so the next one still tries Yahoo."""
    vendor = stub_vendor(error=StubFetchFailed("dead ticker"))
    monkeypatch.setattr(pricesrc, "_yf_fetch", lambda: vendor)
    serve(monkeypatch, history([row("2026-07-27", 100.0)]))
    auto = pricesrc.get("auto")
    auto.weekly("ADBE")
    auto.weekly("MSFT")
    assert len(vendor.calls) == 2


def test_auto_splits_come_from_the_source_that_served(monkeypatch):
    monkeypatch.setattr(pricesrc, "_yf_fetch",
                        lambda: stub_vendor(error=StubRateLimited("429")))
    serve(monkeypatch, history([row("2026-07-27", 100.0)]))
    auto = pricesrc.get("auto")
    assert auto.splits("ADBE") == {}                 # nothing has served yet
    auto.weekly("ADBE")
    assert auto.splits("ADBE") == {}                 # stockanalysis has no split feed


def _ladder(monkeypatch, *sources):
    for source in sources:
        monkeypatch.setitem(pricesrc._SOURCES, source.name, source)
    return pricesrc.AutoSource(order=tuple(s.name for s in sources))


def test_auto_raises_not_found_when_every_source_says_not_found(monkeypatch):
    auto = _ladder(monkeypatch,
                   ScriptedSource("one", pricesrc.PRICE_BASIS_RAW,
                                  error=pricesrc.NotFound("unknown")),
                   ScriptedSource("two", pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY,
                                  error=pricesrc.NotFound("unknown")))
    with pytest.raises(pricesrc.NotFound, match="one: unknown; two: unknown"):
        auto.weekly("NOTAREAL")


def test_auto_raises_a_plain_failure_when_the_sources_disagree(monkeypatch):
    auto = _ladder(monkeypatch,
                   ScriptedSource("one", pricesrc.PRICE_BASIS_RAW,
                                  error=pricesrc.RateLimited("429")),
                   ScriptedSource("two", pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY,
                                  error=pricesrc.NotFound("unknown")))
    with pytest.raises(pricesrc.FetchFailed) as caught:
        auto.weekly("ADBE")
    assert type(caught.value) is pricesrc.FetchFailed


def test_auto_says_so_once_every_source_has_been_retired(monkeypatch):
    auto = _ladder(monkeypatch, ScriptedSource("one", pricesrc.PRICE_BASIS_RAW,
                                               error=pricesrc.RateLimited("429")))
    with pytest.raises(pricesrc.RateLimited):
        auto.weekly("ADBE")
    with pytest.raises(pricesrc.FetchFailed, match="retired"):
        auto.weekly("MSFT")


def test_auto_reports_the_basis_of_whichever_scripted_source_served(monkeypatch):
    served = ScriptedSource("two", pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY,
                            bars={"2026-07-27": {"close": 1.0}}, splits={"2024-06-10": 10.0})
    auto = _ladder(monkeypatch,
                   ScriptedSource("one", pricesrc.PRICE_BASIS_RAW,
                                  error=pricesrc.FetchFailed("nope")),
                   served)
    auto.weekly("NVDA")
    assert auto.served is served
    assert auto.basis == pricesrc.PRICE_BASIS_SPLIT_ADJUSTED_TODAY
    assert auto.splits("NVDA") == {"2024-06-10": 10.0}


# --------------------------------------------------------------------------- registry

def test_available_names_are_the_names_get_accepts():
    assert pricesrc.available() == ["auto", "yahoo", "stockanalysis"]
    for name in pricesrc.available():
        assert pricesrc.get(name).name == name


def test_get_is_case_and_whitespace_forgiving():
    assert pricesrc.get("  Yahoo ").name == "yahoo"


def test_unknown_source_names_the_available_ones():
    with pytest.raises(ValueError, match="stockanalysis"):
        pricesrc.get("bloomberg")


def test_concrete_sources_are_shared_and_auto_handles_are_fresh():
    """A ladder carries per-run state (which source a rate limit retired), so it must never
    be shared between runs; the concrete sources are safe to share."""
    assert pricesrc.get("yahoo") is pricesrc.get("yahoo")
    assert pricesrc.get("auto") is not pricesrc.get("auto")
