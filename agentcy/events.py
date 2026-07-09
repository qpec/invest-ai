"""agentcy/events.py — event spool write/drain (tech-arch §1.5)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class EventRequest:
    yf_ticker: str
    source: str          # 'fingerprint' | 'owner' | 'officer_diff'
    kind: str            # 'earnings' | 'filing' | 'mgmt' | 'other'
    note: str | None
    detected_at: str
    detected_late: bool = False


def scheduled_for(req: EventRequest) -> str:
    """RunLog logical key: '{yf_ticker}:{detected_at}' (§1.3)."""
    return f"{req.yf_ticker}:{req.detected_at}"


def _spool(state_dir: Path) -> Path:
    return Path(state_dir) / "spool"


def _sanitize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s)


def spool_write(state_dir: Path, req: EventRequest) -> Path:
    """Serialize into spool/tmp/ then os.rename into spool/events/ — atomic, same filesystem."""
    spool = _spool(state_dir)
    tmp_dir, events_dir = spool / "tmp", spool / "events"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    events_dir.mkdir(parents=True, exist_ok=True)
    name = f"{_sanitize(req.yf_ticker)}_{_sanitize(req.detected_at)}.json"
    tmp_path = tmp_dir / name
    tmp_path.write_text(json.dumps(asdict(req)), encoding="utf-8")
    final = events_dir / name
    os.rename(tmp_path, final)                       # atomic same-fs move
    return final


def spool_paths(state_dir: Path) -> list[Path]:
    """Pending spool files, oldest first."""
    events_dir = _spool(state_dir) / "events"
    if not events_dir.exists():
        return []
    return sorted((p for p in events_dir.iterdir() if p.is_file()),
                  key=lambda p: p.stat().st_mtime)


def spool_take(state_dir: Path, path: Path) -> EventRequest | None:
    """MOVE the file out of the watched dir FIRST (done/ on success, failed/ on error), then parse."""
    spool = _spool(state_dir)
    (spool / "done").mkdir(parents=True, exist_ok=True)
    (spool / "failed").mkdir(parents=True, exist_ok=True)
    staged = spool / "done" / path.name
    os.rename(path, staged)                          # out of the watched dir before acting (§1.5)
    try:
        data = json.loads(staged.read_text(encoding="utf-8"))
        return EventRequest(**data)
    except Exception:
        os.replace(staged, spool / "failed" / path.name)
        return None
