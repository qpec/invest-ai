# stock-agentcy — Operations Runbook (one page)

The system runs itself. This page is for the four things a human ever does.

## Public Top 48 thesis reader

Section 2 of the GitHub Pages site presents every accepted Top 1% thesis as a
plain-English company card. The visible **View assessment & thesis** action opens a
focused reader. Direct links use `#thesis/<SYMBOL>` and browser Back returns to the
previous search, filters, and list position. Top 48 rows in Scout expose the same action.

The production build downloads decorative company images from the generic Financial
Modeling Prep ticker-image endpoint into the local company-logo cache. `webapp.py`
copies validated images into `docs/data/logos/`; the public browser never contacts the
provider. Invalid, unavailable, oversized, or corrupt images render as deterministic
initials tiles and do not block publication.

Reader integrity is fail-closed. Publication requires one accepted reader per Top 48
member, unique symbols and ranks, all required assessment sections, local-only logo
paths, and the existing public-field privacy allowlist. Logo availability alone remains
non-blocking.

Every Top 48 card and reader also carries a **Valuation context** lens. Its current price
and quote date come from the same point-in-time Scout bundle used for screening; the site
does not fetch a second browser-side quote. Owner free-cash-flow yield is translated into
an equivalent owner-cash multiple and ranked within the measured sector cohort. If sector
metadata is absent or fewer than 20 sector observations are available, the lens explicitly
falls back to the measured Scout universe. The signal is conditional on current cash flow
being representative and remains separate from business quality and downside risk.
Publication blocks when any Top 48 reader lacks a positive dated price, positive yield,
valid comparison, signal, or caveat.

## 1. The dead-man rule (the only daily check)
**No message by 08:00 Amsterdam = the box is down.** The daily letter's absence IS the
alarm — the letter is produced 7 days a week (full letter on US market days, a two-line
pulse Sun/Mon), so silence is loud. If nothing arrived:

    ssh the box
    systemctl status 'agentcy-*'
    journalctl -u agentcy-daily -u agentcy-bot --since -1d

A failed unit also direct-sends "unit X FAILED …" via the fail@ notifier (bypasses the
DB/outbox). The S2 dead-man ping (healthchecks.io-class) is the backup heartbeat during a
quiet-mode absence — if it alerts, same drill.

## 2. Quarterly ritual (~1 hour, per tech-arch §12.4) — steps 0–6, verbatim
- **(0) Patch-health check** — Ubuntu Pro attachment active, unattended-upgrades running,
  "security updates last applied {date}". A box that silently stops patching is the
  archetypal decade-scale silent failure.
- **(1) Restore drill** — open the newest backup, `PRAGMA integrity_check`, row-count
  sanity, toolchain-artifact hash check (this also yields the rehearsal copy for any
  pending migration).
- **(2)** `uv lock --upgrade` into a quarantine venv (quantstats moves only here).
- **(3)** `tools/license_gate.py` — blocks on any violation.
- **(4)** Offline suite + the network-marked golden yfinance contract test
  (`uv run pytest -m network`): EURUSD=X/^SP500TR schema, MSFT quarterly statements
  non-empty with pinned rows, shares-dedup behavior.
- **(5)** Promote the lockfile, `uv sync --locked`, refresh the wheelhouse,
  `systemd-analyze verify deploy/systemd/*`.
- **(6)** Commit; journal a `config_or_designation` if anything behavior-affecting moved.

Honest ops budget: 4 rituals + the historical 1–2 yfinance emergency bumps ≈ 5–6 touches/year.

## 3. yfinance emergency lane (pre-authorized, §12.5)
When the two-run all-fail alarm fires ("probable upstream breakage — check yfinance
releases"), bumping yfinance immediately is sanctioned OUTSIDE the ritual:
quarantine venv → contract test → promote. If the compiled `curl_cffi` wheel is the
blocker (e.g. at an interpreter bump), reinstall yfinance without it (≥1.4.0 has a
plain-requests fallback).

## 4. Event-spool recovery (§1.5)
A poison spool file is moved to `spool/failed/` and the unit degrades to an OnFailure
alert — it never tight-loops. To recover: fix or delete the file, then

    systemctl reset-failed agentcy-event

## 5. Restore drill (standalone, also step 1 above)
Latest backup is under `/var/lib/stock-agentcy/backups` and mirrored to
`/mnt/agentcy-backup`. Open it read-only, run `PRAGMA integrity_check` (expect `ok`),
sanity-check row counts, and confirm the toolchain artifacts (uv binary, wheelhouse,
python-build-standalone tarball) exist and hash-match — a year-8 rebuild on a fresh
machine needs only the second disk.

## 6. eToro auto-ingest (optional — blank keys = manual snapshot mode)
The weekly review can pull holdings straight from eToro's official **read-only** API
(advises/monitors, never trades). It runs only when BOTH keys are set; blank keeps the
box in manual-snapshot mode.

- **Create a read-only key** — in eToro: *Settings → Trading → API Key Management →
  Create New Key*. Set **Environment = Real**, **Scope = Read**, confirm via SMS. You
  get back a public **API key** and a **user key**.
- **Install** — put them in `/etc/stock-agentcy/agentcy.env`:

      AGENTCY_ETORO_API_KEY=<public api key>
      AGENTCY_ETORO_USER_KEY=<user key>

  then re-run the weekly unit (`systemctl start agentcy-weekly.service`, or wait for
  Saturday). The unit already inherits this EnvironmentFile.
- **Rotate** — edit the env file and restart; nothing else. The key is Read scope only,
  so a leak cannot move money.
- **First run / a new holding currency** — the FX pairs self-prime (`{CUR}EUR=X` is
  fetched on cache-miss). A transient eToro/FX failure emits a one-line notice and keeps
  the **last** snapshot; it never crashes the weekly letter.
- **Test manually** — `agentcy snapshot etoro --dry-run` prints the resolved holdings
  and writes nothing.

## 7. Fundamentals populator (background, set-and-forget)
The `agentcy-populate.timer` fires nightly at 01:30 Amsterdam and time-boxes a paced walk of
the universe (`populate_nightly_minutes`, default 90), filling the append-only archive so
`agentcy scout run grade` grades from cache. The starter set (top `populate_starter_size`
liquidity names, default 500) completes on night 1; the first full pass takes ~11 nights.
One Telegram note marks starter-set-ready and one marks first-full-pass-complete; sustained
rate-limiting stops the night early (DEGRADED) and the cursor resumes the next night.

- **Manual slice:** `agentcy run populate --minutes 30` or `--budget 100` (desk/SSH).
- **Progress:** the `universe_fetch` table logs one row per attempt; `v_universe_fetch` is the
  latest outcome per ticker. Delisted/data-thin names dead-list after
  `populate_dead_after_failures` (default 3) failures, retried after a 90-day backstop.
- **Disable:** `agentcy config set populate_enabled false --reason "..."` (advisory flag) and
  `systemctl disable --now agentcy-populate.timer`.

## LTS obligation (dated)
Ubuntu Pro ESM covers to May 2034; the 10-year clock runs to mid-2036, so the LTS hop is
a scheduled obligation — ~2030 recommended, May 2034 at the latest, unless Legacy is paid.
