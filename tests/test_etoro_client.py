"""EtoroClient transport + error classes — no network, monkeypatched urlopen.

Mirrors the TelegramClient test style but stubs urllib.request.urlopen directly
(no in-process server) since the client is a thin read-only GET transport. The two
real endpoints are the portfolio pull and the instrument-metadata resolve.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from agentcy.fetch import etoro
from agentcy.fetch.etoro import EtoroClient, EtoroError, EtoroRetryAfter, _loads


class _FakeResp:
    """Context-manager response with .read(); mirrors urlopen's return value."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://public-api.etoro.com/x", code=code, msg="err",
        hdrs=None, fp=io.BytesIO(body))


@pytest.fixture()
def client():
    return EtoroClient(api_key="APIKEY", user_key="USERKEY", timeout=2.0)


def test_default_host_is_public_api():
    c = EtoroClient(api_key="a", user_key="b")
    assert c._base == "https://public-api.etoro.com"


def test_get_portfolio_sends_all_four_headers_and_parses_body(client, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["headers"] = dict(req.header_items())
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return _FakeResp(json.dumps({"clientPortfolio": {"positions": [], "credit": 1.0}}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)

    out = client.get_portfolio()
    assert out["clientPortfolio"]["credit"] == 1.0
    # the real portfolio endpoint path
    assert captured["url"].endswith("/api/v1/trading/info/portfolio")

    # urllib title-cases header keys; compare case-insensitively.
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    # env AGENTCY_ETORO_API_KEY -> x-api-key ; AGENTCY_ETORO_USER_KEY -> x-user-key
    assert headers["x-api-key"] == "APIKEY"
    assert headers["x-user-key"] == "USERKEY"
    assert headers["x-request-id"]  # a fresh uuid is present
    assert headers["accept"] == "application/json"
    # the browser User-Agent is REQUIRED (Cloudflare 403s the default urllib UA)
    assert "mozilla" in headers["user-agent"].lower()
    assert "chrome" in headers["user-agent"].lower()
    assert captured["method"] == "GET"
    assert captured["timeout"] == 2.0


def test_get_instruments_builds_comma_separated_query(client, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["url"] = req.full_url
        return _FakeResp(json.dumps({"instrumentDisplayDatas": [
            {"instrumentID": 3000, "symbolFull": "SPY", "instrumentTypeID": 6}]}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    rows = client.get_instruments([3000, 4148])
    assert captured["url"].endswith("/api/v1/market-data/instruments?instrumentIDs=3000,4148")
    assert rows[0]["symbolFull"] == "SPY"


def test_get_instruments_empty_ids_short_circuits_no_network(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no network for an empty instrument list")

    monkeypatch.setattr(etoro.urllib.request, "urlopen", boom)
    assert client.get_instruments([]) == []


def test_request_id_is_fresh_per_call(client, monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None, context=None):
        headers = {k.lower(): v for k, v in req.header_items()}
        seen.append(headers["x-request-id"])
        return _FakeResp(json.dumps({"clientPortfolio": {}}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    client.get_portfolio()
    client.get_portfolio()
    assert len(seen) == 2 and seen[0] != seen[1]


def test_429_raises_retry_after(client, monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        raise _http_error(429, json.dumps({"retryAfter": 7}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(EtoroRetryAfter) as ei:
        client.get_portfolio()
    assert ei.value.retry_after == 7.0


def test_non_429_http_error_raises_etoro_error(client, monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        raise _http_error(500, json.dumps({"message": "boom"}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(EtoroError) as ei:
        client.get_portfolio()
    assert not isinstance(ei.value, EtoroRetryAfter)
    assert "500" in str(ei.value)


def test_url_error_wrapped_as_etoro_error(client, monkeypatch):
    # Transport failure (e.g. DNS): URLError must be wrapped, not propagated raw,
    # so the weekly job's `except EtoroError` fallback catches it.
    def fake_urlopen(req, timeout=None, context=None):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(EtoroError) as ei:
        client.get_portfolio()
    assert not isinstance(ei.value, urllib.error.URLError)
    assert "transport error" in str(ei.value)


def test_timeout_error_wrapped_as_etoro_error(client, monkeypatch):
    # Socket timeout raises the builtin TimeoutError; also wrapped as EtoroError.
    def fake_urlopen(req, timeout=None, context=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(EtoroError) as ei:
        client.get_portfolio()
    assert "transport error" in str(ei.value)


def test_unknown_json_fields_are_ignored(client, monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        return _FakeResp(json.dumps(
            {"clientPortfolio": {"credit": 100}, "some_future_field": 1}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    out = client.get_portfolio()
    assert out["clientPortfolio"]["credit"] == 100  # extra fields do not break parsing


def test_empty_or_invalid_body_coerces_to_default(client, monkeypatch):
    # An empty portfolio body coerces to {}.
    def fake_urlopen(req, timeout=None, context=None):
        return _FakeResp(b"")

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    assert client.get_portfolio() == {}


def test_loads_tolerates_empty_and_garbage():
    assert _loads(b"") == {}
    assert _loads(b"not json") == {}
    assert _loads(b'{"a": 1}') == {"a": 1}


def test_client_is_read_only_by_construction():
    # The "never executes trades" charter is enforced structurally: no method
    # whose name implies an order/trade/close/open/buy/sell mutation may exist.
    banned = ("order", "trade", "close", "buy", "sell", "execute", "open_position", "place")
    names = [n for n in dir(EtoroClient) if not n.startswith("_")]
    offenders = [n for n in names if any(b in n.lower() for b in banned)]
    assert offenders == [], f"read-only client must not expose mutating methods: {offenders}"
    assert set(names) == {"get_portfolio", "get_instruments"}
