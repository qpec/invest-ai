"""tests/test_events.py — §1.5 event spool write/drain."""
import json

import pytest


def _req(**kw):
    from agentcy import events
    base = dict(yf_ticker="MSFT", source="fingerprint", kind="earnings", note=None,
                detected_at="2026-07-11T08:00:00Z", detected_late=False)
    base.update(kw)
    return events.EventRequest(**base)


def test_scheduled_for_key(tmp_path):
    from agentcy import events
    assert events.scheduled_for(_req()) == "MSFT:2026-07-11T08:00:00Z"


def test_spool_write_atomic_and_paths(tmp_path):
    from agentcy import events
    p = events.spool_write(tmp_path, _req())
    assert p.parent.name == "events" and p.exists()
    assert (tmp_path / "spool" / "tmp").exists() and not list((tmp_path / "spool" / "tmp").iterdir())
    assert [x.name for x in events.spool_paths(tmp_path)] == [p.name]


def test_spool_take_moves_to_done_on_success(tmp_path):
    from agentcy import events
    events.spool_write(tmp_path, _req())
    [path] = events.spool_paths(tmp_path)
    req = events.spool_take(tmp_path, path)
    assert req is not None and req.yf_ticker == "MSFT" and req.kind == "earnings"
    assert not path.exists()                                     # moved out of the watched dir
    assert (tmp_path / "spool" / "done" / path.name).exists()
    assert events.spool_paths(tmp_path) == []                    # watched dir empties


def test_spool_take_poison_goes_to_failed(tmp_path):
    from agentcy import events
    events_dir = tmp_path / "spool" / "events"
    events_dir.mkdir(parents=True)
    bad = events_dir / "MSFT_bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert events.spool_take(tmp_path, bad) is None
    assert not bad.exists() and (tmp_path / "spool" / "failed" / "MSFT_bad.json").exists()
