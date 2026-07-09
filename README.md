# stock-agentcy

A daily/weekly iterating financial-analysis system for portfolio oversight.
The core object is the **investment thesis**, not the stock. **The system
advises and monitors. It never executes trades.**

Binding design docs live under `docs/plans/` (functional baseline,
architecture elaboration, technology architecture, Telegram interaction spec).

## Development

Requires [uv](https://docs.astral.sh/uv/); the interpreter is pinned in
`.python-version` (uv-managed CPython, never system Python).

    uv sync --locked
    uv run pytest -q          # fully offline — network access is a test failure

License wall (NFR7): `uv run python tools/license_gate.py` — exits 1 on any
violation; the audit table is committed at `docs/license-audit.txt`.
