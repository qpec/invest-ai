# stock-agentcy — Operations Runbook (one page)

The system runs itself. This page is for the four things a human ever does.

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

## LTS obligation (dated)
Ubuntu Pro ESM covers to May 2034; the 10-year clock runs to mid-2036, so the LTS hop is
a scheduled obligation — ~2030 recommended, May 2034 at the latest, unless Legacy is paid.
