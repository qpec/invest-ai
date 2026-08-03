# stock-agentcy

A daily/weekly iterating financial-analysis system for portfolio oversight.
The core object is the **investment thesis**, not the stock. **The system
advises and monitors. It never executes trades.**

Binding design docs live under `docs/plans/` (functional baseline,
architecture elaboration, technology architecture, Telegram interaction spec).

---

## High-level design

New here? This section is the whole system in three tables. Everything in it is
enforced in code, and the requirement IDs (FR/NFR) are the owner-approved ones
from `docs/plans/2026-07-08-functional-design-baseline.md`.

### The idea in one paragraph

Every position carries a **written thesis** with a conviction level and
pre-committed, testable invalidation triggers. The system monitors holdings
against *those triggers only* — never open-ended news scanning — evaluates
candidate buys through a fixed framework, and reports on portfolio balance.
When the framework and a great-looking opportunity conflict, the framework wins.

### The framework it applies

| Pillar | Question | What it does here |
|---|---|---|
| **Buffett** | What to buy | Wonderful businesses at fair prices: circle of competence, a moat with evidence, owner earnings over reported EPS, the 10-year test |
| **Munger** | What to avoid | Inversion. The Hell-No filter runs *first* and a single fail rejects, regardless of upside |
| **Naval** | How to keep upgrading | Specific knowledge, the leverage stack (capital / labour / code / media), process judged separately from outcome |

### The seven components

| # | Component | Owns | Runs |
|---|---|---|---|
| 1 | **Portfolio Mirror** | holdings, weights, balance, leverage tripwire | on snapshot |
| 2 | **The Gate** | buy discipline: circle → Hell-No veto → Buffett dossier → owner judgement → thesis | human-triggered desk session |
| 3 | **Thesis Register** | one living, versioned document per holding; goalpost guard | on change |
| 4 | **The Watchdog** | tests the pre-committed triggers, nothing else | daily · weekly (Sat) · event · quarterly |
| 5 | **Decision Journal** | every decision plus the reasoning of that moment | on decision |
| 6 | **The Study** | the learning loop — weekly digest, mental models | weekly |
| 7 | **The Scout** | idea generation from a pre-committed universe | human-triggered only (FR14) |

`stock-scout/` is the Scout's screening pipeline and has [its own
README](stock-scout/README.md) with the same treatment: an eight-stage pipeline
table and fifteen key requirements of its own.

### Key requirements

The rules the system is not allowed to break. Full text in the functional
baseline; this is what each one means in practice.

| ID | Requirement | Why it exists |
|---|---|---|
| **FR1** | No thesis, no buy | An unwritten thesis cannot be tested, so it cannot be invalidated |
| **FR3** | Hell-No first | Munger's veto runs *before* any Buffett analysis; one fail rejects whatever the upside |
| **FR4** | "No action needed" is a first-class outcome | Counters action bias; a price drop with an intact thesis is an *opportunity*, not an alarm |
| **FR7** | A broken thesis produces sell advice that ignores cost basis | The stock does not know what you paid — sunk cost is the trap |
| **FR8** | Every decision is journalled with its reasoning | Process is judged separately from returns; a good outcome from a bad process catches up |
| **FR9** | Human judgement is sacred | Conviction, trust in management and circle fit are *asked*, never invented |
| **FR11** | Advice, never execution | There is no broker path in this repo, by construction |
| **FR12** | Hidden-concentration check | "Are my 12 positions really 3 bets?" — correlation clustering, weekly |
| **FR13** | Quarterly honesty check | One benchmark, quarterly only, never in daily output — "would an index fund beat my process?" |
| **FR14** | Idea generation is human-triggered only | Automated loops never scan for candidates; screener output reaches the watchlist, not the portfolio |
| **NFR1** | Robust to source failure | Keeps running on the last snapshot and *reports the staleness* |
| **NFR4** | Auditable | Every analysis, report and thesis change is traceable in history |
| **NFR5** | Low maintenance | Must run for months without tinkering |
| **NFR7** | Dependency discipline | Permissive licences only — no GPL family; enforced by a gate, not by good intentions |

### Runtime shape

Always-on Ubuntu box · systemd timers + oneshot jobs + one small synchronous
daemon · stdlib spine (hand-rolled Telegram client) · two SQLite files with the
benchmark physically quarantined · rendered-markdown archive in its own git
repo · four runtime pip packages · **no LLM in the scheduled runtime** — the
Gate and the Study are desk sessions through the `agentcy` CLI.

    agentcy run {daily,weekly,quarterly,event}
    agentcy bot

---

## Development

Requires [uv](https://docs.astral.sh/uv/); the interpreter is pinned in
`.python-version` (uv-managed CPython, never system Python).

    uv sync --locked
    uv run pytest -q          # fully offline — network access is a test failure

License wall (NFR7): `uv run python tools/license_gate.py` — exits 1 on any
violation; the audit table is committed at `docs/license-audit.txt`.
