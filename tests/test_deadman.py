"""P6.4 (R4): dead-man ping — single source, env-over-config, no-op on empty, never raises.

resolve_url layers env over the journaled config value; ping does a content-free GET that
is a no-op on an empty URL and swallows every failure (the ping must never fail the run).
Config-timing is out of scope here — config reads resolve at wall-clock, so the config leg
is exercised by stubbing config.get; the env leg and the no-op/never-raise legs are exact.
"""
from agentcy import config, deadman


def test_resolve_url_prefers_env_over_config(tmp_db, monkeypatch):
    monkeypatch.delenv("AGENTCY_DEADMAN_URL", raising=False)
    assert deadman.resolve_url(tmp_db) == ""                          # seeded '' -> empty
    monkeypatch.setattr(config, "get", lambda conn, key, **kw: "https://hc.example/cfg")
    assert deadman.resolve_url(tmp_db) == "https://hc.example/cfg"    # falls through to config
    monkeypatch.setenv("AGENTCY_DEADMAN_URL", "https://hc.example/env")
    assert deadman.resolve_url(tmp_db) == "https://hc.example/env"    # env wins over config


def test_ping_skips_when_unset_and_hits_url_when_set(tmp_db, monkeypatch):
    monkeypatch.delenv("AGENTCY_DEADMAN_URL", raising=False)
    calls = []
    monkeypatch.setattr(deadman.urllib.request, "urlopen",
                        lambda url, timeout=10: calls.append(url) or type("R", (), {"close": lambda s: None})())
    deadman.ping(tmp_db)                                              # empty URL -> no network
    assert calls == []
    monkeypatch.setenv("AGENTCY_DEADMAN_URL", "https://hc.example/abc")
    deadman.ping(tmp_db)
    assert calls == ["https://hc.example/abc"]


def test_ping_never_raises(tmp_db, monkeypatch):
    monkeypatch.setenv("AGENTCY_DEADMAN_URL", "https://hc.example/boom")

    def _boom(url, timeout=10):
        raise OSError("network down")
    monkeypatch.setattr(deadman.urllib.request, "urlopen", _boom)
    deadman.ping(tmp_db)                                              # swallowed, no exception
