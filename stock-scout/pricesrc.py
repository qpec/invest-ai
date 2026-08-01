"""Pluggable weekly price sources that DECLARE the basis of the prices they hand back
(RECONSTRUCTION.md §3.6 bars/splits; SCORECARD-DESIGN.md §4.1 "no price, no verdict").

Yahoo rate-limits (HTTP 429) the box this pipeline runs on, so the §3.6 weekly grid has to
be obtainable from more than one vendor — a price-less run is a quality profile and
explicitly NOT a verdict (§4.1), which is the whole scorecard withheld. But vendors do not
agree on what a "close" IS, and the difference is invisible in the payload:

- ``raw`` — Yahoo's ``Close``: the price as it actually traded on the bar's own day.
- ``split_adjusted_today`` — stockanalysis's ``c``: that same price divided by every split
  since. NVDA's 2026-05-28 bar reads 109.6 there; ~1096 is what traded (10:1 on 2024-06-10).

For a CURRENT run the distinction is moot: "adjusted to today" IS today's as-traded price,
so today's market cap is exact either way. For a HISTORICAL tick it is enormous.
``pit.as_of_bundle`` builds ``market_cap = as-reported dei share count x the raw close``,
and dei counts are as-reported (NVDA ~2.46bn pre-split, ~24.6bn after). An as-reported share
count times a split-adjusted price understates the cap by the split factor — ~$270bn where
the market said ~$2.7tn — and nothing in the numbers says so.

The fix is to put both sides in the same basis, never to assume one: against a
``split_adjusted_today`` price the share counts must be restated into TODAY's split terms,
which ``scoring.adjusted_shares_series`` already does. The future-split factor then cancels
between the two sides and the product is the true historical market cap in dollars — not
lookahead but an identity, since the factor that cancels is the same number on both sides.
Ratio metrics are indifferent either way: a factor common to two share observations cancels
in the trend.

So no source here returns bars without saying what they are. Every source carries ``basis``;
``auto`` carries the basis of whichever source actually served:

    src = pricesrc.get("auto")
    bars = src.weekly("ADBE", start="2016-01-01")   # §3.6 {"YYYY-MM-DD": {...}}
    src.served.name, src.basis                      # who answered, and in what basis

Empty is failure (vendor/yf_fetch's contract): a source that cannot deliver raises, it never
returns an empty map. No network at import time and no module-level vendor imports — yfinance
is lazy-loaded inside the Yahoo source, because the box where it is unusable is exactly the
box the stockanalysis source exists for.

Two boundaries worth stating plainly, because they are easy to assume away:

- The CLIs (populate §5.2, bt_fetch §5.8) do NOT drive `AutoSource`. Each keeps its own
  Yahoo fetch — populate's daily bars carry the currency and the §3.2 split events,
  bt_fetch's weekly path carries the raw close, and neither is reachable through this
  module's bar-only contract — so `populate.PriceLadder` owns the step-down and asks here
  only for the source BEHIND Yahoo. `AutoSource` is the ladder for a caller that wants bars
  and nothing else.
- Pacing here is PER PROCESS. The Yahoo leg serializes on vendor/yf_fetch's box-wide flock,
  so every process on the box shares one budget; PACE_SECONDS is a module global, so two
  concurrent runs halve the effective spacing at this vendor. Run them one at a time, or
  lower the pace (`set_pace`, wired to both CLIs' `--pace`).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

import pit

# ------------------------------------------------------------------------------- basis

PRICE_BASIS_RAW = "raw"                               # as traded on the bar's own day
PRICE_BASIS_SPLIT_ADJUSTED_TODAY = "split_adjusted_today"   # as traded / every later split
PRICE_BASES = (PRICE_BASIS_RAW, PRICE_BASIS_SPLIT_ADJUSTED_TODAY)

RAW_FIELD, ADJ_FIELD = pit.PRICE_FIELDS   # §3.6 bar fields: "close" / "adj_close"


class FetchFailed(Exception):
    """No usable bars — empty payload, unusable prices, or transport failure. Mirrors
    vendor.yf_fetch.FetchFailed: empty is failure, never an empty map."""


class RateLimited(FetchFailed):
    """The vendor throttled us and the backoff ladder ran out; the caller degrades to
    another source (`auto` retires this one) or stops."""


class NotFound(FetchFailed):
    """The vendor does not know this symbol — a fact about the symbol, not the transport,
    so no other source is likely to do better and no retry is worth paying for."""


# -------------------------------------------------------------------------- small helpers

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _day(value) -> str | None:
    """A vendor date cell -> "YYYY-MM-DD", or None when it is not an ISO day. No format
    guessing: an unrecognized cell drops its bar rather than inventing a date for it."""
    text = str(value if value is not None else "").strip()
    return text[:10] if _ISO_DAY.match(text) else None


def _price(value) -> float | None:
    """A vendor price cell -> a positive float, else None. Non-numeric, NaN and
    non-positive quotes are DROPPED, never zero-filled — a zero close would read as a
    total drawdown and a zero market cap (vendor/yf_fetch's non-positive-close rule)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out > 0 else None


def _at_or_after(bars: dict, start: str | None) -> dict:
    """The §3.6 bar map ascending, keeping only days at or after `start` (bt_fetch's own
    grid rule); `start` None keeps everything the vendor sent."""
    return {day: bar for day, bar in sorted(bars.items())
            if start is None or day >= str(start)}


class PriceSource:
    """One weekly price vendor. `name` identifies it in the registry and in reports;
    `basis` (one of PRICE_BASES) says what its closes ARE, so no caller has to assume."""

    name = ""
    basis = ""

    def weekly(self, symbol: str, *, start: str | None = None,
               state_dir: Path | None = None) -> dict:
        """The §3.6 weekly bar map {"YYYY-MM-DD": {"close": raw, "adj_close": adjusted}},
        ascending, bars before `start` dropped. A bar the vendor gave only one usable price
        for is written on that field alone — the degraded shape `pit.bar_value` already
        falls back on — never a fabricated second price. Raises NotFound for an unknown
        symbol, RateLimited when the vendor throttles, FetchFailed for everything else."""
        raise NotImplementedError

    def splits(self, symbol: str) -> dict:
        """The §3.6 split events {"YYYY-MM-DD": ratio} this source knows for `symbol`. {}
        means no split feed — never a fake ratio — and this makes no extra vendor call."""
        return {}

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name} basis={self.basis}>"


# ------------------------------------------------------------------------ stockanalysis

STOCKANALYSIS_URL = "https://stockanalysis.com/api/symbol/s/{symbol}/history"
# Spans the API HONORS (verified 2026-08-01). Anything else is not an error there — it
# silently answers 52 weekly bars, so the allowlist is the guard, not a denylist.
STOCKANALYSIS_SPANS = ("6M", "YTD", "5Y", "10Y")
# Honored spans that cover a whole number of years, deepest last — the ladder span_for
# climbs. 6M/YTD are honored but not year-shaped, so no --start maps onto them.
SPAN_YEARS = ((5, "5Y"), (10, "10Y"))
DEFAULT_SPAN = "10Y"
DEEPEST_SPAN = SPAN_YEARS[-1][1]      # the vendor serves nothing older than this
# A browser agent is required: urllib's default "Python-urllib/3.x" is answered 403.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
PACE_SECONDS = 0.35            # in-process spacing between calls (~0.3 s/request measured)
RETRY_BACKOFF = (1.0, 5.0, 20.0)   # transient-only ladder; 4 attempts in ~26 s worst case
TIMEOUT_SECONDS = 15           # a ~0.3 s endpoint; 15 s is already a dead connection
NOT_FOUND_CODES = (400, 404)   # the API answers 400 "Unknown error" for an unknown symbol
TRANSIENT_CODES = (408, 429, 500, 502, 503, 504)

_last_call = 0.0


def set_pace(seconds: float) -> None:
    """Override the per-call spacing (a bulk backfill may want more, a single lookup less)."""
    global PACE_SECONDS
    PACE_SECONDS = float(seconds)


def span_for(start: str | None, *, today: date | None = None) -> str:
    """The smallest HONORED span covering `start` -> today (bt_fetch.yf_period's rule for
    this vendor). `start` None asks for the default. A start older than the deepest span
    gets that deepest one: the vendor simply has no more history, and `covers` is how the
    caller finds out that the requested window is wider than what it will get."""
    if start is None:
        return DEFAULT_SPAN
    years = ((today or date.today()) - date.fromisoformat(str(start))).days / 365.25
    return next((span for cap, span in SPAN_YEARS if years < cap), DEEPEST_SPAN)


def covers(span: str, start: str | None, *, today: date | None = None) -> bool:
    """Does `span` reach back to `start`? False means the run will silently get a SHORTER
    window than it asked for — bars_from_history cannot raise on that (it only fails when
    NOTHING survives the start filter), so the caller has to say so itself."""
    if start is None:
        return True
    years = ((today or date.today()) - date.fromisoformat(str(start))).days / 365.25
    return any(years < cap for cap, name in SPAN_YEARS if name == span)


def _http_get(url: str) -> bytes:
    """The one network touch in this module — the tests monkeypatch it and never reach
    the wire."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def _paced_get(url: str) -> bytes:
    """One GET that waits out PACE_SECONDS since the previous one (bt_fetch's EDGAR
    spacing, in-process: this vendor is keyless and needs no box-wide lock)."""
    global _last_call
    wait = PACE_SECONDS - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    return _http_get(url)


def _fetch_json(url: str) -> dict:
    """A paced GET -> the decoded payload. 429/5xx and transport errors are transient and
    retried down RETRY_BACKOFF; 404 (and the 400 this API answers for a symbol it does not
    know) is NotFound and never retried, and a body that is not JSON is a contract
    violation, not bad luck — it fails on the spot.

    A 429 ANYWHERE in the ladder makes the exhausted result RateLimited, not just a 429 on
    the last attempt: 429, 429, 429, 503 is a throttled vendor whatever its parting shot
    was, and reading only the final error there leaves the source un-retired and every
    remaining symbol paying the same ladder."""
    attempts = len(RETRY_BACKOFF) + 1
    error: Exception | None = None
    throttled = False
    for attempt in range(attempts):
        try:
            raw = _paced_get(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(
                    f"{url}: HTTP 404 — the vendor does not know this symbol") from e
            if e.code == 400:
                # The vendor's answer for an unknown symbol, but also what any origin
                # answers a malformed path — so the URL is named rather than the symbol
                # blamed. Still not retried: neither cause improves on a second try.
                raise NotFound(f"{url}: HTTP 400 — the vendor does not know this symbol, "
                               f"or this URL is malformed") from e
            if e.code not in TRANSIENT_CODES:
                raise FetchFailed(f"{url}: HTTP {e.code} {e.reason}" + (
                    " — the User-Agent was rejected" if e.code == 403 else "")) from e
            throttled = throttled or e.code == 429
            error = e
        except OSError as e:      # URLError, timeouts and socket errors all land here
            error = e
        else:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise FetchFailed(f"{url}: response is not JSON ({e})") from e
        if attempt < attempts - 1:
            time.sleep(RETRY_BACKOFF[attempt])
    kind = RateLimited if throttled else FetchFailed
    raise kind(f"{url}: {attempts} attempts failed — {error}") from error


def bars_from_history(payload, *, symbol: str = "", start: str | None = None) -> dict:
    """A stockanalysis history payload -> the §3.6 weekly bar map, ascending.

    The vendor answers newest-first, `{"status": 200, "data": [{"t": day, "o":, "h":, "l":,
    "c": close, "a": adjusted, "v":, "ch":}, ...]}`, and repeats its status INSIDE the body,
    so a body-level status is honored exactly like the HTTP one. `c` (split-adjusted to
    today — see the module docstring) becomes `close`, `a` (split AND dividend adjusted)
    becomes `adj_close`. A row whose date is unreadable, or which has no usable price at
    all, is dropped; a row with one usable price is written on that field alone. A payload
    that is not an object, carries no `data` list, or leaves no usable bar is a failure —
    empty is failure, never an empty map."""
    if not isinstance(payload, dict):
        raise FetchFailed(f"{symbol or 'history'}: payload is a "
                          f"{type(payload).__name__}, not an object")
    status = payload.get("status")
    if status is not None and str(status) != "200":
        kind = NotFound if str(status) in {str(c) for c in NOT_FOUND_CODES} else FetchFailed
        raise kind(f"{symbol or 'history'}: vendor status {status} "
                   f"({payload.get('message') or 'no message'})")
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise FetchFailed(f"{symbol or 'history'}: no history rows — empty is failure")
    bars = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = _day(row.get("t"))
        if day is None:
            continue
        bar = {field: value for field, value in ((RAW_FIELD, _price(row.get("c"))),
                                                 (ADJ_FIELD, _price(row.get("a"))))
               if value is not None}
        if bar:
            bars[day] = bar
    out = _at_or_after(bars, start)
    if not out:
        raise FetchFailed(f"{symbol or 'history'}: no usable weekly bars in "
                          f"{len(rows)} rows (start={start})")
    return out


def vendor_symbols(symbol: str) -> list[str]:
    """The spellings to try at stockanalysis, most likely first. The universe carries
    Yahoo's convention for share classes, preferreds and warrants — BF-A, BRK-B, ALP-PQ,
    CHPT-WT — and this vendor spells the class suffix with a DOT: verified live, BRK-B is
    answered 404 and BRK.B is answered 200 with 521 weekly bars. Without the translation
    those 14 universe names read as "the vendor does not know this symbol" and drop out of
    the cache, which under `auto` means they drop out of the backtest pool. The symbol as
    given is tried FIRST, because a dash is a legal part of some tickers and only the
    vendor knows which."""
    text = str(symbol)
    out = [text]
    for separator in ("-", "/"):
        swapped = text.replace(separator, ".")
        if swapped != text and swapped not in out:
            out.append(swapped)
    return out


class StockAnalysisSource(PriceSource):
    """stockanalysis.com's keyless weekly history — the fallback for when Yahoo throttles
    the box. Closes are SPLIT-ADJUSTED TO TODAY: right as they stand for a current run,
    right for a historical tick only against share counts restated into today's split terms
    (`scoring.adjusted_shares_series`). That is what `basis` is for.

    `span` is the vendor's own range token and must be one it HONORS. An unrecognized range
    is not an error there: it silently answers 52 weekly bars (verified for MAX, ALL, 20Y,
    1M), so a run asking for ten years of history would quietly grade on one — hence the
    allowlist, checked before anything is fetched.
    """

    name = "stockanalysis"
    basis = PRICE_BASIS_SPLIT_ADJUSTED_TODAY

    def __init__(self, span: str = DEFAULT_SPAN):
        if span not in STOCKANALYSIS_SPANS:
            raise ValueError(
                f"{self.name}: range {span!r} is not honored — the API answers 52 weekly "
                f"bars for anything outside {list(STOCKANALYSIS_SPANS)} instead of failing, "
                f"so the run would silently grade on one year of prices")
        self.span = span

    def url(self, symbol: str) -> str:
        """The history endpoint for `symbol`, path-quoted so a dotted or slashed symbol
        (BRK.B, BRK/B) cannot reshape the URL. A dot is unreserved and survives verbatim,
        which is what the vendor wants."""
        quoted = urllib.parse.quote(str(symbol), safe="")
        return f"{STOCKANALYSIS_URL.format(symbol=quoted)}?range={self.span}&period=Weekly"

    def weekly(self, symbol: str, *, start: str | None = None,
               state_dir: Path | None = None) -> dict:
        """The §3.6 bar map for `symbol` (PriceSource.weekly), asking under each spelling
        in `vendor_symbols` until one is known. `state_dir` is accepted for the contract
        and unused: this vendor is keyless and paced IN-PROCESS by PACE_SECONDS, never by
        the box-wide Yahoo lock (see the module docstring on concurrent runs)."""
        tried = vendor_symbols(symbol)
        last: NotFound | None = None
        for spelling in tried:
            try:
                return bars_from_history(_fetch_json(self.url(spelling)),
                                         symbol=symbol, start=start)
            except NotFound as e:      # only the spelling is in doubt; the rest propagates
                last = e
        if len(tried) == 1:
            raise last
        raise NotFound(f"{symbol}: unknown at {self.name} under any of "
                       f"{', '.join(tried)} — {last}") from last


# --------------------------------------------------------------------------------- yahoo

YAHOO_PERIOD = "10y"
_YAHOO_SPLIT_COLUMNS = ("split", "Stock Splits")   # vendor-normalized / raw Yahoo spelling


def _yf_fetch():
    """vendor.yf_fetch, imported HERE and not at module scope: pricesrc must import cleanly
    on a box where yfinance is unusable — that box is precisely why stockanalysis exists."""
    from vendor import yf_fetch
    return yf_fetch


def bars_from_frame(frame, *, start: str | None = None) -> dict:
    """A vendor weekly frame (DatetimeIndex; `adj_close`, plus `close` when the vendor hands
    the raw column over) -> the §3.6 bar map. Same drop rules as `bars_from_history`: a bar
    with no usable price is dropped, and a bar with one is written on that field alone
    rather than passing the adjusted close off as a raw one (bt_fetch.prices_payload)."""
    bars = {}
    for stamp, row in frame.iterrows():
        bar = {field: value for field, value in ((RAW_FIELD, _price(row.get(RAW_FIELD))),
                                                 (ADJ_FIELD, _price(row.get(ADJ_FIELD))))
               if value is not None}
        if bar:
            bars[pd.Timestamp(stamp).date().isoformat()] = bar
    return _at_or_after(bars, start)


def splits_from_frame(frame) -> dict:
    """The §3.6 split map {"YYYY-MM-DD": ratio} riding the same weekly fetch — no second
    Yahoo call (§3.6). Cells go through `pit.split_ratio`, the one filter every writer of a
    §3.6 split map shares (Yahoo's 0.0 on an ordinary week and an inert 1.0 are both
    dropped); a frame with no split column yields {}, i.e. no splits KNOWN, never a fake
    ratio. Today's vendored `fetch_weekly_bars` returns adj_close and currency only, so in
    practice that is {} and the split-aware PIT grid stays `bt_fetch.weekly_frame`'s job."""
    columns = getattr(frame, "columns", [])
    column = next((c for c in _YAHOO_SPLIT_COLUMNS if c in columns), None)
    if column is None:
        return {}
    out = {}
    for stamp, raw in frame[column].items():
        ratio = pit.split_ratio(raw)
        if ratio is not None:
            out[pd.Timestamp(stamp).date().isoformat()] = ratio
    return dict(sorted(out.items()))


class YahooSource(PriceSource):
    """vendor/yf_fetch's validated weekly bars — the primary source, and the one that gets
    rate-limited on this box, which is the reason this module exists.

    Its closes are RAW, the basis `pit.as_of_bundle` assumes when it multiplies an
    as-reported dei share count by the close, so nothing downstream has to be restated.
    Split events ride the SAME weekly fetch (§3.6), so `splits` reports what the last
    `weekly` for that symbol carried and never spends another Yahoo call.
    """

    name = "yahoo"
    basis = PRICE_BASIS_RAW

    def __init__(self, period: str = YAHOO_PERIOD):
        self.period = period
        self._splits: dict[str, dict] = {}

    def weekly(self, symbol: str, *, start: str | None = None,
               state_dir: Path | None = None) -> dict:
        """The §3.6 bar map for `symbol` (PriceSource.weekly). `state_dir` is where
        vendor/yf_fetch keeps the box-wide Yahoo pacing lock; None means the working
        directory. Vendor exceptions are translated into this module's hierarchy so every
        caller — `auto` above all — has ONE set of errors to handle, and a box where
        yfinance will not even import is a FetchFailed like any other refusal to serve.

        That translation is deliberately total. yfinance leaks transport failures of its
        own past the vendor's declared contract (a curl_cffi SSLError on this box, where
        the connection is reset outright), and an untranslated one aborts the very run the
        fallback exists to save. So anything escaping the vendor is a refusal to serve —
        with its class named in the message, so a real bug stays visible."""
        try:
            vendor = _yf_fetch()
        except ImportError as e:
            raise FetchFailed(f"{symbol}: vendor.yf_fetch unusable here ({e})") from e
        try:
            frame = vendor.fetch_weekly_bars(str(symbol), period=self.period,
                                             state_dir=Path(state_dir or "."))
        except vendor.RateLimited as e:
            raise RateLimited(f"{symbol}: {e}") from e
        except vendor.FetchFailed as e:
            raise FetchFailed(f"{symbol}: {e}") from e
        except Exception as e:
            raise FetchFailed(f"{symbol}: {type(e).__name__} escaped yfinance — {e}") from e
        self._splits[str(symbol)] = splits_from_frame(frame)
        bars = bars_from_frame(frame, start=start)
        if not bars:
            raise FetchFailed(f"{symbol}: no usable weekly bars in the vendor frame "
                              f"(start={start}) — empty is failure")
        return bars

    def splits(self, symbol: str) -> dict:
        """The split events the last `weekly` for `symbol` carried; {} when it carried none
        or the symbol has not been fetched through this handle."""
        return dict(self._splits.get(str(symbol)) or {})


# ------------------------------------------------------------------------ registry + auto

AUTO_NAME = "auto"
AUTO_ORDER = ("yahoo", "stockanalysis")   # validated source first, fallback second

_SOURCES: dict[str, PriceSource] = {source.name: source
                                    for source in (YahooSource(), StockAnalysisSource())}


class AutoSource(PriceSource):
    """The ladder: the validated Yahoo source first, stockanalysis when Yahoo refuses.
    (The CLIs drive `populate.PriceLadder` instead, because each owns its own Yahoo fetch —
    see the module docstring. This is the ladder for a bars-only caller.)

    `basis` is None until something has served — the honest answer, because which basis the
    bars carry depends on WHO answered. Read `served` and `basis` after each `weekly`; the
    one thing a caller must never do is assume.

    Which source served is remembered PER SYMBOL, not just for the handle: a run is mixed
    by construction (Yahoo answers until it throttles, the fallback answers after), and
    `splits`/`basis_for` keyed on the handle's last answer would report the fallback's
    empty split map for a symbol Yahoo actually served — an empty map re-arms the §4.4 hard
    dilution veto on a splitter and drops a today-basis market cap by the split factor.

    A RateLimited retires that source for the rest of THIS handle's life: Yahoo's ladder
    costs 30 s -> 5 min -> 30 min per call, and paying it again on every remaining name of a
    400-symbol run is the difference between a run and a hang. A plain FetchFailed retires
    nothing — it is usually about the one symbol. Handles are therefore stateful and
    per-run, which is why `get("auto")` hands out a fresh one every time.
    """

    name = AUTO_NAME

    def __init__(self, order=AUTO_ORDER):
        self._ladder = [get(n) for n in order]
        self._served: dict[str, PriceSource] = {}
        self.served: PriceSource | None = None

    @property
    def basis(self) -> str | None:
        """The basis of the bars served MOST RECENTLY — None before anything has. Read it
        right after the `weekly` it belongs to; for a symbol served earlier in a mixed run,
        ask `basis_for`."""
        return self.served.basis if self.served is not None else None

    def basis_for(self, symbol: str) -> str | None:
        """The basis of the bars served for `symbol`; None when this handle never served
        it."""
        source = self._served.get(str(symbol))
        return source.basis if source is not None else None

    def weekly(self, symbol: str, *, start: str | None = None,
               state_dir: Path | None = None) -> dict:
        """The §3.6 bar map from the first source that serves it, recording that source in
        `served` and against the symbol. Raises when every source refuses: NotFound when
        they all agreed the symbol is unknown, RateLimited when they were all throttled (or
        when the ladder had already been emptied by rate limits, so a caller's stop-the-run
        guard still fires instead of the run grinding through 2,900 more names),
        FetchFailed otherwise — with every source's own complaint named in the message."""
        failures: list[tuple[PriceSource, FetchFailed]] = []
        for source in list(self._ladder):
            try:
                bars = source.weekly(symbol, start=start, state_dir=state_dir)
            except RateLimited as e:
                self._ladder.remove(source)
                failures.append((source, e))
            except FetchFailed as e:
                failures.append((source, e))
            else:
                self.served = self._served[str(symbol)] = source
                return bars
        if not failures:
            raise RateLimited(f"{symbol}: every source has been retired by a rate limit")
        kinds = {type(exc) for _, exc in failures}
        kind = kinds.pop() if len(kinds) == 1 else FetchFailed
        raise kind(f"{symbol}: no price source served — "
                   + "; ".join(f"{src.name}: {exc}" for src, exc in failures)
                   ) from failures[-1][1]

    def splits(self, symbol: str) -> dict:
        """The split events of the source that served THIS symbol; {} when none did."""
        source = self._served.get(str(symbol))
        return source.splits(symbol) if source is not None else {}


def available() -> list[str]:
    """Every name `get` accepts, in ladder-preference order."""
    return [AUTO_NAME, *_SOURCES]


def get(name: str) -> PriceSource:
    """A source by name. The concrete sources are shared handles (Yahoo's carries the split
    events its last fetch delivered); `"auto"` returns a FRESH ladder each call, because a
    ladder carries per-run state — which source a rate limit retired, and which one served."""
    key = str(name).strip().lower()
    if key == AUTO_NAME:
        return AutoSource()
    source = _SOURCES.get(key)
    if source is None:
        raise ValueError(f"unknown price source {name!r} — available: {available()}")
    return source
