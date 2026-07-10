"""P7.14: structural guards for the Telegram runtime (tech-arch §5.1, §16 ruling 1)."""
from __future__ import annotations

import ast
from pathlib import Path

CLIENT = Path("agentcy/tg/client.py")
_BANNED = {"certifi", "requests", "httpx", "aiohttp", "urllib3", "curl_cffi"}


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_client_is_stdlib_only_no_certifi():
    assert _BANNED.isdisjoint(_imported_names(CLIENT)), \
        "tg/client.py must be stdlib-only (urllib+ssl); no certifi/requests/httpx (§5.1)"


def test_client_uses_ssl_default_context():
    assert "ssl.create_default_context" in CLIENT.read_text(encoding="utf-8")
