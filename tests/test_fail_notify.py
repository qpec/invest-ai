"""tech-arch §11.3: OnFailure notifier direct-sends via stdlib urllib + the env token,
DELIBERATELY bypassing the DB and the outbox (the failure being reported may BE the DB).
If even the send fails, it writes to journald (stderr) and exits 0 — never a fail loop."""
import sys


def _load(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("fail_notify", None)
    # tools/ is on sys.path in tests via conftest rootdir; import by file:
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "fail_notify", Path(__file__).resolve().parents[1] / "tools" / "fail_notify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builds_direct_send_url_and_posts_unit_name(monkeypatch):
    mod = _load(monkeypatch, {"AGENTCY_BOT_TOKEN": "T", "AGENTCY_OWNER_CHAT_ID": "42"})
    seen = {}
    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["data"] = req.data
        class _R:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _R()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    rc = mod.notify("agentcy-daily.service")
    assert rc == 0
    assert "api.telegram.org/botT/sendMessage" in seen["url"]
    assert b"42" in seen["data"] and b"agentcy-daily.service" in seen["data"]
    assert b"FAILED" in seen["data"]


def test_token_never_appears_in_stderr_on_failure(monkeypatch, capsys):
    mod = _load(monkeypatch, {"AGENTCY_BOT_TOKEN": "SECRET", "AGENTCY_OWNER_CHAT_ID": "42"})
    def boom(req, timeout):
        raise OSError("telegram down")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert mod.notify("agentcy-bot.service") == 0     # never a fail loop
    err = capsys.readouterr().err
    assert "SECRET" not in err and "agentcy-bot.service" in err
