"""Task 3: EtoroClient transport + error classes — no network, monkeypatched urlopen.

Mirrors the TelegramClient test style but stubs urllib.request.urlopen directly
(no in-process server) since the client is a thin read-only GET transport.
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
        url="https://api.etoro.com/x", code=code, msg="err",
        hdrs=None, fp=io.BytesIO(body))


@pytest.fixture()
def client():
    return EtoroClient(api_key="APIKEY", user_key="USERKEY", timeout=2.0)


def test_get_positions_sends_auth_headers_and_parses_list_body(client, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["headers"] = dict(req.header_items())
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return _FakeResp(json.dumps([{"instrumentId": 1}, {"instrumentId": 2}]).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)

    out = client.get_positions()
    assert [p["instrumentId"] for p in out] == [1, 2]

    # urllib title-cases header keys; compare case-insensitively.
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers["x-api-key"] == "APIKEY"
    assert headers["x-user-key"] == "USERKEY"
    assert headers["x-request-id"]  # a fresh uuid is present
    assert headers["accept"] == "application/json"
    assert captured["method"] == "GET"
    assert captured["timeout"] == 2.0


def test_request_id_is_fresh_per_call(client, monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None, context=None):
        headers = {k.lower(): v for k, v in req.header_items()}
        seen.append(headers["x-request-id"])
        return _FakeResp(b"[]")

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    client.get_positions()
    client.get_positions()
    assert len(seen) == 2 and seen[0] != seen[1]


def test_429_raises_retry_after(client, monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        raise _http_error(429, json.dumps({"retryAfter": 7}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(EtoroRetryAfter) as ei:
        client.get_positions()
    assert ei.value.retry_after == 7.0


def test_non_429_http_error_raises_etoro_error(client, monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        raise _http_error(500, json.dumps({"message": "boom"}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(EtoroError) as ei:
        client.get_positions()
    assert not isinstance(ei.value, EtoroRetryAfter)
    assert "500" in str(ei.value)


def test_unknown_json_fields_are_ignored(client, monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        return _FakeResp(json.dumps({"cash": 100, "some_future_field": 1}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    out = client.get_balances()
    assert out["cash"] == 100  # extra fields do not break parsing


def test_get_portfolio_returns_dict(client, monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        return _FakeResp(json.dumps({"positions": []}).encode())

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    assert client.get_portfolio() == {"positions": []}


def test_empty_or_invalid_body_coerces_to_default(client, monkeypatch):
    # An empty positions body coerces to [].
    def fake_urlopen(req, timeout=None, context=None):
        return _FakeResp(b"")

    monkeypatch.setattr(etoro.urllib.request, "urlopen", fake_urlopen)
    assert client.get_positions() == []


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
    assert set(names) == {"get_positions", "get_portfolio", "get_balances"}
