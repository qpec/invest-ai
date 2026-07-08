# stock-agentcy — Technology & Runtime Architecture

**Status:** Approved-candidate design, 2026-07-08 — resolves open item 5 of the functional baseline ("technology/runtime choice"). Synthesized from a **three-draft / three-judge panel over a live-verified fact pack** (all license, systemd, Telegram Bot API, packaging, and yfinance facts verified against primary sources on 2026-07-08; nothing below rests on model memory). The judges converged: the stdlib-maximalist spine won on fidelity and minimalism, hardened with the ops draft's supervision mechanisms and exactly two mechanisms from the framework draft (the logical-run sweep and the outbox dedupe key). Synthesis rulings are recorded in §16.

**Owner-locked decisions (2026-07-08, technology phase):**
1. Runtime host: an always-on **Ubuntu box**; posture "stable so it can run for 10 years"; no inbound ports.
2. **No LLM anywhere in the scheduled runtime** — every scheduled output is a deterministic template; qualitative work happens in desk sessions (Claude Code) and enters as owner-typed data.
3. **Everything via one private Telegram chat** locked to the owner's chat-id; email is not used.
4. **SQLite is the single source of truth**; reports/theses/journal additionally render to markdown auto-committed to the local git repo (NFR4 twice over).
5. Python, with the locked analysis stack: hardened yfinance, pandas+scipy, quantstats (pinned, quarterly-quarantined), TradingView-Screener (human-run only), FinanceDatabase equities file (direct read).
6. NFR7 license wall, absolute: permissive only; **the GPL family including LGPL is out of the runtime stack**.

**Binding functional spec:** `2026-07-08-architecture-elaboration.md` (components A–H, 8 global invariants) and `2026-07-08-functional-design-baseline.md` (FR1–14, NFR1–7). **Companion:** `2026-07-08-telegram-interaction-spec.md` (message layouts, keyboards, ask flows — amended per panel).

---

## 0. Shape of the system

- **One tiny always-on daemon** (Telegram long-poll in, outbox out, synchronous, single-threaded) plus **short-lived jobs fired by systemd timers** (daily/weekly/quarterly/backup) and a **path-unit-triggered event job**. Nothing else runs. The init system — not Python — owns time and supervision: catch-up after downtime, watchdog, restart, and failure notification are all systemd *configuration*, guaranteed for the OS lifetime, not code we must keep correct for ten years.
- **Four pip packages in the runtime, all in the analysis layer, all owner-locked:** yfinance, pandas, scipy, quantstats. The spine — scheduling, supervision, storage, Telegram, rendering, git, validation — is **stdlib + systemd + the git binary, zero pip packages**. Target property: a person can read the entire codebase in an afternoon in 2033 and fix it.
- **Jobs never talk to Telegram.** They render, archive, and enqueue into a durable `outbox` table in one transaction, then exit; only the daemon holds the token and delivers. Alerts survive any network or Telegram outage; the letter is at worst late, never lost.
- **The cache is the archive.** PriceCache/FundamentalsCache/shares live as append-only tables with `fetched_at` stamps — NFR6 hardening and NFR4 auditability are the same tables.
- **The forbidden inputs are physically absent.** The benchmark lives in a separate database file the daily/weekly/event code never opens (invariant 7); cost basis is excluded from the only view advice code may read (invariant 4).

---

## 1. Process & deployment model

### 1.1 Topology — system-level units, one dedicated user

Everything runs as **system-level systemd units with `User=agentcy`** (a dedicated no-login user). *Rejected: user units + `loginctl enable-linger` — if the linger bit is ever lost (OS upgrade, admin cleanup), the user manager never starts at boot and every timer silently never runs, with no unit in a failed state anywhere: a total-silence single point of failure. System units eliminate the class.* Code at `/opt/stock-agentcy` (a clone of this repo); state at `/var/lib/stock-agentcy` (never in git).

| Unit | Kind | Fires | Does |
|---|---|---|---|
| `agentcy-bot.service` | daemon, `Type=notify` | always | long-poll loop; routes callbacks/replies to Ask objects; drains outbox; watchdog pings |
| `agentcy-daily.timer/.service` | oneshot | `OnCalendar=*-*-* 07:00:00 Europe/Amsterdam`, `Persistent=true` | D.1 daily loop → letter to outbox + archive (7 days/week, §1.4) |
| `agentcy-weekly.timer/.service` | oneshot | `Sat 08:00 Europe/Amsterdam`, `Persistent=true` | D.2 weekly loop; statement-fingerprint event detection → event spool |
| `agentcy-quarterly.timer/.service` | oneshot | `*-01,04,07,10-01 08:30 Europe/Amsterdam`, `Persistent=true` | D.4 honesty check — the only process that opens `benchmark.db` |
| `agentcy-event.path` + `.service` | path-triggered oneshot | `DirectoryNotEmpty=/var/lib/stock-agentcy/spool/events` | drains the event spool: one D.3 check per spooled request (§1.5) |
| `agentcy-backup.timer/.service` | oneshot | daily 03:30, `Persistent=true` | `Connection.backup()` both DBs + integrity checks + second-disk sync (§11.5) |
| `agentcy-fail@.service` | templated oneshot | via `OnFailure=` on every unit above | direct-send "unit %i FAILED" to Telegram, **bypassing the DB and outbox** (§11.2) |

### 1.2 Load-bearing unit lines

```ini
# agentcy-bot.service
[Unit]
OnFailure=agentcy-fail@%n.service
StartLimitIntervalSec=600
StartLimitBurst=5
[Service]
Type=notify
User=agentcy
WatchdogSec=90
Restart=always
RestartSec=10
EnvironmentFile=/etc/stock-agentcy/agentcy.env
ExecStart=/opt/stock-agentcy/.venv/bin/agentcy bot
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/stock-agentcy
PrivateTmp=true
[Install]
WantedBy=multi-user.target
```

```ini
# agentcy-daily.service (weekly/quarterly/event/backup identical in shape)
[Unit]
Wants=network-online.target
After=network-online.target
OnFailure=agentcy-fail@%n.service
[Service]
Type=oneshot
User=agentcy
TimeoutStartSec=30min
EnvironmentFile=/etc/stock-agentcy/agentcy.env
Environment=MPLBACKEND=Agg
ExecStart=/opt/stock-agentcy/.venv/bin/agentcy run daily
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/stock-agentcy
PrivateTmp=true
```

Three lines are convictions from the judge panel, not style: **`TimeoutStartSec=30min`** (Type=oneshot defaults to an *infinite* start timeout — without it a wedged HTTPS call hangs the daily job forever with no exception, no OnFailure, no letter); **`StartLimitIntervalSec=600` + `StartLimitBurst=5`** on the daemon (with `Restart=always`+`RestartSec=10`, systemd's default 10s/5 window never trips, so a crashlooping daemon would never enter `failed` and `OnFailure` would never fire — letters would queue undelivered forever while jobs "succeed"); and the sandbox block (free at deploy time, shrinks blast radius for a decade). The daemon sends `READY=1`/`WATCHDOG=1` datagrams to `$NOTIFY_SOCKET` from a ~15-line stdlib `sdnotify.py` (the man page explicitly sanctions reimplementation).

### 1.3 Misfire / catch-up — "the letter is never skipped" as a checked property

- `Persistent=true` stores each timer's last-trigger stamp on disk; after downtime (including power loss) systemd fires **one coalesced catch-up run** per timer (verified semantics).
- Jobs are **date-aware and idempotent**: every run has a logical key `(run_type, scheduled_for)`; `run_log` has `UNIQUE(run_type, scheduled_for)`; a job computes which letter/review date it is producing from the DB, never from `now()`; re-fired jobs that find their key finished exit 0.
- **The due-run sweep** (adopted from the framework draft — the one mechanism `Persistent=true` cannot replace): ~15 lines executed at daemon startup and at the start of every job — *for every logical key due by now, a `run_log` row with `finished_at` must exist*; any key absent **or started-but-never-finished** (a job that crashed mid-run, which the stamp file cannot see) is re-run, marked `late=true`. This turns the D.1/NFR1 guarantee into an enforced property rather than a hope.
- **Degraded letter on exception:** every job's top-level handler writes the D.1 honesty letter ("Data sources unavailable since {t}; last known state; no checks performed. Nothing is wrong; I just can't see.") to the outbox **before re-raising** — so `OnFailure=` fires *and* the letter still ships.
- A multi-day outage produces **one catch-up letter that names the gap** ("no letters were sent {dates} — box offline"), never backdated pseudo-letters; on outbox flush the daemon collapses stale undelivered daily letters (newest sent as current, one line "N earlier letters are in the archive"; the archive keeps all), and every late delivery carries a "generated {t} — delivered {t}" banner.

### 1.4 Timezones, DST, market days

- All timers carry the IANA suffix `Europe/Amsterdam`; DST resolves from the tz database — no Python timezone code in the scheduling path. 07:00 Amsterdam is ≥8h after the 16:00 America/New_York close in every DST combination, so G.1's "prices fresh 07:00 CET" holds year-round. Job-internal date math uses stdlib `zoneinfo`.
- **The daily timer fires 7 days a week.** The full G.1 letter is produced per US market day; Sunday/Monday mornings (no preceding US close) send a two-line heartbeat ("markets closed — nothing to check; {n} open items; data health ✓"). This is a recorded amendment to the loop spine's "once per market day" (§15 A1): the dead-man contract is "absence of the morning message IS the alarm", and a Tue–Sat cadence leaves a ~71-hour weekend blind window. *Rejected: an external ping service as the weekend patch (invariant 8) — the 2-line pulse costs nothing and keeps the letter the only heartbeat.*
- **Market-day detection is empirical, not calendrical** — no exchange-calendar dependency — with the two outcomes kept strictly apart: *fetch succeeded, no new bar* → "US markets closed {date}" (holiday); *fetch failed/empty/exception* → STALE, "I just can't see". A Yahoo outage must never be reported as a market holiday.

### 1.5 Event checks — one path, fully supervised

All three D.3 sources write a **spool file** (`/var/lib/stock-agentcy/spool/events/{ticker}.{reason}.json`): the weekly job on a statement-fingerprint change (the authoritative detector), the daemon on owner `/event` (FR6 — the owner as first-class sensor), and the daily job's 7-day post-earnings retry sweep. `agentcy-event.path` (`DirectoryNotEmpty=`) starts `agentcy-event.service`, which drains the spool sequentially — fresh paced statements (bypass cache, appended to archive), all armed triggers for that thesis, prompted questions queued with the event named, each request its own RunLog row.

*Rejected:* the daemon spawning event checks as subprocesses (dies unsupervised with the daemon — no OnFailure, no timeout, no RunLog finish on a daemon restart) and `systemctl start` from the daemon (needs a polkit/sudoers rule that rots). A path unit is supervision-as-configuration: zero privileges, `TimeoutStartSec`, `OnFailure`, and natural serialization of Yahoo access, for one extra unit pair.

---

## 2. Dependency manifest

### 2.1 Runtime (installed in the single locked venv; exact versions frozen in `uv.lock`)

| Package | Pin | License (fact-pack verified) | NFR7 justification |
|---|---|---|---|
| `yfinance` | `==1.5.1` exact | Apache-2.0 | Owner-locked sole price/fundamentals source; confined to `fetch/yf.py`; emergency-bump lane §12.5. |
| `pandas` | lock-frozen | BSD-3 (deps: numpy, dateutil) | Owner-locked; statement frames, return series, clustering input. |
| `scipy` | lock-frozen | BSD-3 (dep: numpy) | Owner-locked; `cluster.hierarchy` for FR12 — the verified 5-line recipe. |
| `quantstats` | `==0.0.81` exact | Apache-2.0 | Owner-locked, quarterly-quarantined: imported only inside `jobs/quarterly.py` under try/except with the D.4 four-stat hand-computed fallback; its matplotlib/seaborn weight loads in a process that exists four times a year (`MPLBACKEND=Agg`); removable at any ritual without redesign. |

**The spine imports nothing outside the standard library:**

| Need | Implementation | Displaced |
|---|---|---|
| Telegram Bot API | hand-rolled `urllib.request`+`json`+`ssl` client, ~300 lines (§5) | python-telegram-bot (**LGPL-3.0 — banned**), pyTelegramBotAPI (**GPL-2.0 — banned**), aiogram (MIT, but §2.3), httpx (BSD but pre-1.0, 19 months release-silent, pulls certifi) |
| Scheduling & supervision | systemd timers/path/watchdog (§1) | APScheduler (3.x healthy but strictly more owned moving parts; 4.x "do NOT use in production" per its own README), `schedule` (no persistence/catch-up, dormant since 2024) |
| sd_notify | ~15-line stdlib datagram | libsystemd bindings |
| Storage | stdlib `sqlite3` (WAL, triggers, backup API, user functions — all verified stdlib) | any ORM |
| Templates | f-string render functions (§8) | jinja2 (BSD and fine — but two skins × seven outputs do not justify a template language) |
| Validation | stdlib frozen `dataclasses` + one `validate()` | pydantic (MIT, but exact-pinned compiled Rust core = binary coupling to the interpreter across a decade) |
| Git auto-commit | `subprocess` → system git (Ubuntu-maintained for the OS lifetime) | dulwich (healthy, but dual Apache/GPL-2.0+ and a wire-format burden we don't need) |
| TLS trust | Ubuntu `ca-certificates` via `ssl.create_default_context()` | certifi in anything we author |

### 2.2 The one license exception — certifi (MPL-2.0), named and journaled

The locked yfinance tree pulls `requests`→`certifi` and `curl_cffi`→`certifi`; **certifi is MPL-2.0** — not GPL-family (the hard ban), but not on the permissive allowlist either. It cannot be excised from a locked dependency, our code never imports it, and unmodified use of a CA *data file* imposes zero practical obligations. Ruling: **one standing exception, owner-signed at bootstrap, journaled as `config_or_designation`, covering the whole venv** — named, not hidden. It is deliberately *not* usable to re-argue aiogram: certifi rides the locked tree either way, while aiogram's real cost is elective churn (§2.3).

`tools/license_gate.py` — a stdlib `importlib.metadata` walk over the full installed set — enforces the wall mechanically: allowlist `{MIT, Apache-2.0, BSD-2/3-Clause, 0BSD, ISC, PSF-2.0}` ∪ the journaled certifi exception; **any other license fails the install**. PSF-class is explicitly whitelisted (else CPython itself is banned). The gate runs at bootstrap, at every deploy, and in every quarterly ritual, and prints the full audit table for the repo record. Verified transitives today: numpy/websockets/protobuf BSD-3, curl_cffi MIT; the remainder (peewee, bs4, multitasking, platformdirs, pytz, matplotlib's tree) are gated at lock time — the audit is the enforcement, not memory.

### 2.3 aiogram, rejected on churn (the license case alone would be overstated)

aiogram is MIT and excellent. It is rejected because it releases every 4–6 weeks tracking each Bot API version, hard-pins pydantic/aiohttp/typing-extensions ranges (pydantic exact-pins a compiled Rust core), and would make the ~2028 interpreter bump contingent on that whole lattice publishing compatible wheels inside aiogram's ranges — the single most likely multi-day maintenance event in the design, on the one channel that must never break. The verified Bot API surface we need is five methods whose required parameters have **no backwards-incompatible change on record**; ~300 lines of stdlib is honest code, not hair-shirt minimalism.

### 2.4 Dev / desk only (never imported by runtime modules; enforced by import-graph test §13)

`pytest` (MIT, dev) · `uv` binary (MIT/Apache dual; version-pinned, archived on-box) · `tradingview-screener` (MIT; `[scout]` extra, Scout sessions only, FR14) · FinanceDatabase `equities.bz2` (MIT; not a package — pinned-commit file, direct bz2 read, cached under `/var/lib/stock-agentcy/universe/`).

---

## 3. Module map

```
agentcy/
  db.py            # THE sqlite door for agentcy.db: WAL, busy_timeout, foreign_keys,
                   #   migration runner, append/fetch API; never opens benchmark.db
  sdnotify.py      # READY=1 / WATCHDOG=1 datagram (~15 lines)
  config.py        # config reads + journaled changes (journal-FK, §4.5)
  clock.py         # injected as_of; effective_deadline() absence arithmetic (D.6, §6)
  schema/          # 000_init.sql … NNN_*.sql — forward-only migrations (§12.6)
  fetch/
    yf.py          # THE ONLY yfinance importer: fail-loud config, flock pacing,
                   #   emptiness detection, rate-limit backoff (§7)
    store.py       # price_cache / fundamentals_period / shares_series append + freshness reads
  mirror.py        # Portfolio Mirror (E): ingest, reconciliation, designations, balance
                   #   bands, leverage tripwire; advice reads via positions_advice only
  cluster.py       # E.5 local-currency correlation clustering, N_eff (pandas+scipy)
  register.py      # Thesis Register (A): versioning, status log, goalpost guard
  triggers.py      # Trigger taxonomy (B): five evaluators, STALE/BOOTSTRAPPING, headroom
  journal.py       # Decision Journal (F.1): immutable entries; grades in journal_grade
  study.py         # The Study (F.3)
  gate.py          # The Gate (C.2–C.6) state machine driven by the CLI
  scout.py         # The Scout (H); lazy [scout]-extra import inside the function
  asks.py          # D.5 contract: Ask objects, option schemas, re-prompt, escalation
  events.py        # event spool write/drain (§1.5)
  jobs/
    daily.py weekly.py quarterly.py event.py backup.py
  benchmark.py     # quarantined: the only module knowing benchmark.db's path (§4.6)
  tg/
    client.py      # hand-rolled Bot API client (§5.1)
    outbox.py      # durable queue: enqueue (jobs) / drain+retry+collapse (daemon)
    daemon.py      # long-poll loop, owner lock, callback routing, watchdog pings
  render/
    common.py      # HTML escaper, <pre> tables, markdown helpers
    lint.py        # pre-send register lint, fail-closed (§8)
    daily.py weekly.py alert.py event.py quarterly.py gate.py study.py
  archive.py       # report rows + markdown files + git commit
  gitio.py         # subprocess git (plumbing-stable porcelain)
  cli.py           # argparse: run {daily,weekly,quarterly,event}, bot, gate, scout,
                   #   snapshot, journal, config, absence, ask, render --rebuild (§10)
tools/license_gate.py  tools/record_fixtures.py
deploy/systemd/    # the §1 unit files, linked by install.sh
```

Component homes: **Mirror**→`mirror.py`/`cluster.py` · **Gate**→`gate.py`+`cli.py` · **Register**→`register.py` · **Watchdog**→`jobs/*`+`triggers.py`+`asks.py` · **Journal**→`journal.py` · **Study**→`study.py` · **Scout**→`scout.py`+`cli.py`.

---

## 4. SQLite schema

Two files under `/var/lib/stock-agentcy/`: **`agentcy.db`** (everything) and **`benchmark.db`** (BenchmarkSeries only). WAL, `busy_timeout=30000`, `foreign_keys=ON`, opened identically by every process through `db.py` (WAL's many-readers/one-writer, same-host model is exactly this topology — verified).

### 4.1 Table inventory (key columns)

**Append-only, trigger-enforced** (any UPDATE/DELETE aborts — §4.2):

| Table | Key columns |
|---|---|
| `snapshot` | `snapshot_id PK, as_of, source {api_pull,manual_export,manual_entry}, cash_balance_eur, created_at` |
| `position` | `snapshot_id FK, symbol, yf_ticker, instrument_type, quantity, avg_open_price, native_currency, mv_native, mv_eur, weight, leverage` — **no `framework_status`/`thesis_id` columns**: both are derived at read time (§4.4), so a designation or backfill answered after ingest is reflected immediately without touching immutable rows *(panel fix — stamping status into per-snapshot rows misclassified holdings for up to a week)* |
| `designation` | `symbol, framework_status {framework, backfill_pending, outside_framework}, valid_from, journal_ref NOT NULL` — latest wins (E.2) |
| `external_flow` | `flow_id PK, snapshot_id, date, amount_eur, direction, ask_ref` (MA-12) |
| `symbol_map` | `symbol, yf_ticker, valid_from, journal_ref` — latest wins |
| `price_cache` | `yf_ticker, bar_date, close, adj_close, currency, fetched_at, run_id` — re-fetches (splits/dividends revise adjusted closes) **append**; view `v_price` = latest `fetched_at` per (ticker, date); FX pairs (`{CUR}EUR=X`) live here. *(Panel conviction on the ops draft: a mutable price cache destroys data-as-fetched and hollows B.3.6 revision pinning — append-with-latest-wins costs nothing.)* |
| `fundamentals_period` | `yf_ticker, statement_type, period_end, payload_json, fingerprint, fetched_at, run_id` — the MA-1 append-only archive; a new row only on unseen fingerprint; the same fingerprint drives D.3 earnings detection |
| `shares_series` | `yf_ticker, obs_date, shares, fetched_at` — raw as-fetched; last-per-date dedup applied at read |
| `officer_snapshot` | `yf_ticker, officers_json, fingerprint, fetched_at` (B.2 tripwire) |
| `earnings_calendar` | `yf_ticker, expected_date, fetched_at, run_id` — weekly best-effort fetch; feeds only the D.1 "expected" preview line, always labeled "calendar estimate" (MA-7); never triggers anything |
| `thesis` | `thesis_id PK, ticker, origin, created_at` (immutable identity) |
| `thesis_version` | `thesis_id, version, <all A.1 fields>, diff_json, reason, actor, journal_ref NOT NULL, created_at` — current = max(version) |
| `thesis_status_log` | `thesis_id, status, changed_at, cause, cause_ref` — current status = latest row; A.2 transitions validated in `register.py` |
| `trigger` | `trigger_id PK, thesis_id, introduced_version, type, statement, metric, comparator, threshold, moat_link, persistence, check_method, data_source, cadence, retired_at` — definition rows immutable; **loosening = retire + new row** (goalpost guard reads status from `thesis_status_log`); `retired_at` is the sole column-guarded UPDATE. **No `last_checked`/`last_result`/`fired_at` columns — current trigger state is derived from `trigger_check`** *(panel fix: duplicated state columns were a second source of truth)* |
| `trigger_check` | `trigger_id, run_id, checked_at, result {PASS,FIRE,STALE,BOOTSTRAPPING,UNVERIFIABLE}, observed_value, headroom, evaluable_from` |
| `journal_entry` | full F.1 schema; `inputs_ref → run_log`; **no grade columns** |
| `journal_grade` | `entry_id FK, graded_at, outcome_grade, note` — grading appends, never mutates (F.1 "filled only at review", structurally) |
| `report` | `report_id PK, run_id, type, generated_at, period, freshness_json, content_md, archive_path, git_sha` (G.5) |
| `config` | `key, value, valid_from, journal_ref NOT NULL FK` — current = latest per key; **an unjournaled config change is a foreign-key violation, not a code-review finding**; migration 000 seeds the E.3 defaults against a single "bootstrap 2026-07-08" journal entry |
| `absence` | `absence_id PK, start_at, end_at, journal_ref` (D.6) |
| `event` | `event_id PK, yf_ticker, source {fingerprint, owner, officer_diff}, note, detected_at, detected_late, run_id` |
| `schema_migration` | `version, applied_at, sha256` |

**Operational tables** (UPDATE restricted to named state columns by column-guard triggers; identity/history columns immutable): `alert` (resolution fields), `ask` (`status, answer_json, answered_at, tg_message_id`), `outbox` (`status, attempts, next_attempt_at, tg_message_id`; **`dedupe_key UNIQUE`** = `run_type:scheduled_for:section`), `watchlist_item` (stage/expiry), `run_log` (finish fields; `UNIQUE(run_type, scheduled_for)`, `late` flag), `bot_state` (single row: `last_update_id`), `gate_session` (resumable C.2–C.6 state).

**`benchmark.db`:** one table, `benchmark_series (bar_date PK, sp500tr_usd, usdeur, tr_eur, fetched_at, run_id)` — append-only.

*Ruling — no generic `state_transition` ledger:* the transitions that are decisions already journal (ask answers, alert resolutions, watchlist verdicts); outbox state churn is delivery mechanics visible in its own columns and RunLog. A parallel transition table was two sources of truth for trigger state and ten years of bloat for outbox sends. The column-guard triggers deliver what NFR4 actually requires: history can never be mutated.

### 4.2 Append-only enforcement — both mechanisms, deliberately redundant

```sql
CREATE TRIGGER journal_entry_no_update BEFORE UPDATE ON journal_entry
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
CREATE TRIGGER journal_entry_no_delete BEFORE DELETE ON journal_entry
  BEGIN SELECT RAISE(ABORT, 'append-only (invariant 1)'); END;
```

Stamped onto every table in the first block of §4.1; column-guard variants (`BEFORE UPDATE OF <protected columns>`) on the operational tables. The triggers live in migration SQL, so even a stray manual `sqlite3` session cannot destroy history. `db.py` is the ergonomic layer: `append_*()`/`fetch()` functions only, no generic `execute()` escapes the module. A test executes a raw UPDATE against every protected table and asserts the ABORT fires (§13).

### 4.3 Versioning mechanics

`register.py` writes `thesis_version` rows with per-field `diff_json` and a mandatory `journal_ref` (invariant 2 as a NOT NULL FK). Goalpost guard (A.3): loosening requires current status `intact` (from `thesis_status_log`), never during `under_review`; headroom-at-loosening is captured into the diff for the 4-week weekly echo; fair-band re-anchoring only at anniversary/event review — all enforced in `register.py` *before* the append, for CLI and bot alike.

### 4.4 Derivations, not stamps

`framework_status` = latest `designation` row per symbol (default: equity without designation → `backfill_pending`; crypto/copyportfolio/ETF prompt once for `outside_framework` — E.1/E.2). `thesis_id` = live thesis for the ticker from `thesis`+`thesis_status_log`. Current trigger state = latest `trigger_check` per armed trigger. Balance views and advice paths read these derivations; nothing re-writes history to change today's classification.

### 4.5 Invariant 4 — cost basis structurally out of advice

```sql
CREATE VIEW positions_advice AS SELECT snapshot_id, symbol, yf_ticker, instrument_type,
  quantity, native_currency, mv_native, mv_eur, weight, leverage
  FROM position;  -- avg_open_price deliberately absent
```

`positions_advice` is the **only** read surface for `mirror.py` balance code, `jobs/daily|weekly|event`, and `render/*`; the advice dataclasses have no such field; the raw column is touched only by snapshot ingest (writer) and the quarterly records-appendix accessor (G.4 §6). AST + grep tests enforce (§13).

### 4.6 Invariant 7 — benchmark quarantine, four independent walls

1. **Separate database file** — `agentcy.db` contains no benchmark table; the daily/weekly/event generators cannot read what is physically absent from the only database `db.py` opens.
2. **Single importer** — `benchmark.py` alone knows the file path; `jobs/quarterly.py` is its only importer.
3. **Frozen template contexts** — the G.1/G.2/G.3 context dataclasses have no benchmark (and no cost-basis) field; a template author cannot reference what does not exist.
4. **Tests** — import-graph walk (benchmark/quantstats reachable only from `jobs.quarterly`) plus a source scan asserting no `ATTACH` exists outside `benchmark.py` (§13).

`^SP500TR` is fetched only inside the quarterly job (through the same paced adapter, written only to `benchmark.db`). Daily `{CUR}EUR=X` FX in `agentcy.db` is E.1 portfolio-conversion data, not benchmark data.

---

## 5. Telegram integration (hand-rolled, stdlib)

### 5.1 Client — `tg/client.py`, ~300 lines

The verified surface is five HTTPS+JSON methods: `getUpdates`, `sendMessage`, `editMessageText`, `answerCallbackQuery`, `sendDocument` (the one hand-built multipart body, ~30 lines; 50 MB cap vs our kilobyte files). JSON POST via `urllib.request` with `ssl.create_default_context()` (Ubuntu system CA store — no certifi in anything we author). Built tolerant: unknown JSON fields ignored; 429 honors `retry_after`; 5xx/timeouts retry with backoff; no optional parameters that have ever been renamed. The Bot API changelog shows **no backwards-incompatible change on record to these five methods' required parameters** (the rare breaks — thumb→thumbnail, ReplyParameters — hit optional surface a minimal client never sends).

**`parse_mode=HTML`, locked.** MarkdownV2 requires escaping 18 characters including `.` and `-` — the verified silent-failure footgun for generated financial text. HTML needs one `& < >` escaper in `render/common.py`; tables ship in `<pre>`.

### 5.2 Daemon loop — synchronous, single-threaded, watchdog-budgeted

```
loop:  sd_notify("WATCHDOG=1")
       drain_outbox()                       # WATCHDOG=1 between sends; send timeout 10s
       updates = getUpdates(offset=last_update_id+1, timeout=25)   # HTTP read timeout 35s
       for u in updates: handle(u); persist last_update_id (bot_state)
```

No asyncio, no threads: one owner, one chat, daily cadence — a sync loop a person can read in 2033. `WatchdogSec=90` is sized against the computed worst-case iteration (25s poll + bounded sends), and `WATCHDOG=1` is emitted between outbox sends so a bad-network night degrades sends without a SIGABRT restart storm. A genuinely hung HTTPS connection is killed by the watchdog (SIGABRT + `Restart=always`) — supervision is configuration. `last_update_id` is persisted (a crash after `handle()` never replays already-processed updates — free-text answers cannot double-journal); only the daemon ever calls `getUpdates`; any process may send (the fail@ notifier does).

### 5.3 Owner lock

`OWNER_CHAT_ID` is **pre-provisioned in the 0600 EnvironmentFile** at install — there is no in-chat bind step (the panel killed the spec's first-come-first-served `/start` Confirm as a hijack race; the spec is amended). Every update is checked at the top of `handle()`; non-owner traffic is logged and never answered.

### 5.4 Durable outbox — alerts are never lost, letters at worst late

Jobs render + archive + **enqueue in one transaction** (`dedupe_key UNIQUE` makes a crash between Telegram's `ok:true` and the mark-sent write unable to double-deliver — at-least-once transport, exactly-once effect). The daemon drains FIFO with backoff (30s → 2m → 10m → 30m → hourly); `sent` only on `ok:true` with `message_id` stored; **alerts have no dead-letter state** — they retry until delivered. Telegram or network down for a day: everything queues in SQLite and delivers on reconnect, oldest first, stale daily letters collapsed (§1.3), each stamped with generation time.

### 5.5 D.5 asks ↔ inline keyboards

Per the companion spec: every ask is a DB row first (stable `ask_id`), `callback_data = "{domain}:{action}:{ask_id}[:{value}]"` (≤64 bytes); every callback validated server-side against the ask row (exists, open, owner, option in the enumerated set) before any effect; every callback answered (`answerCallbackQuery` — clients spin a progress bar otherwise); resolution edits the message and strips the keyboard (idempotent double-taps: "already recorded"). Alert keyboards show `[Confirm broken] [Refute]` only — **Revise materializes only after a recorded refute** (goalpost guard as UI affordance), confirm-broken takes a second explicit tap, and revise itself is journaled intent routed to the desk, never a phone-typed threshold. Free text (refute evidence, can't-verify notes, close reasoning) uses ForceReply reply-to correlation with the pending-ask state machine as backstop: exactly-one-open-ask attribution, a disambiguation keyboard when several are open, and **text resolving to no open ask is never parsed and never stored**.

---

## 6. Scheduler design

- **What fires what:** §1.1 table; event spool §1.5; post-earnings data-lag retries ride the daily job (no extra timer).
- **Catch-up:** `Persistent=true` (OS guarantee, on-disk stamps surviving power loss) + date-aware idempotent jobs + the due-run sweep (§1.3).
- **Pause mode (D.6) — freeze by arithmetic, not mutation:** deadlines are stored once as anchors and never edited; `clock.effective_deadline()` adds the overlap of declared absence windows at every evaluation. All counters — alert windows, prompted-question skips, UNVERIFIABLE weeks, re-affirmation lapses — go through this one function: a vacation freezes everything with zero writes and zero fake `alert_ignored` entries, and the audit trail reconstructs truthfully. `daily_letter_mode=quiet` suppresses letter delivery only; runs still execute and write RunLog daily; alerts still deliver.
- **Concurrency:** Saturday's 07:00 daily and 08:00 weekly are staggered by clock; collisions after catch-up are absorbed by WAL + `busy_timeout` + short write transactions; Yahoo access is serialized box-wide by the fetch lock (§7.2).

---

## 7. Data-layer hardening (NFR6) — `fetch/yf.py`, the only yfinance door

Calibrated to yfinance 1.5.1 per the live-verified fact pack:

1. **Fail loud at import:** `yf.config.debug.hide_exceptions = False` (the default silently returns None) and `yf.config.network.retries = 2`; `YFRateLimitError` propagates and is caught only here.
2. **Cross-process pacing — one mechanism:** every Yahoo call acquires `flock` on `/run/stock-agentcy/yahoo.lock` and **holds the ≥2s + 0.5–1.5s jitter spacing inside the lock** *(panel fix: the drafts' flock + separate timestamp store was two mechanisms for one job)*. This serializes the daily job, the Saturday batch, event checks, and a desk Gate run box-wide. Never parallel `yf.download`; **never `.info`** (heaviest, most 429-prone) — `fast_info` + statements only. Daily ≈ 17 requests (~1 min); Saturday ≈ 90 (~5 min). On `YFRateLimitError`: 30s → 5min → 30min, then the run is marked DEGRADED and stops — no retry storms.
3. **Empty-is-failure:** empty/None/zero-row frames and NaN/non-positive closes are fetch failures (verified: missing fundamentals arrive as `(0,0)` frames with no exception) — keep last-known-good, stamp STALE with age, never write zeros. Statement sanity (plausible row count, recent `period_end`, pinned MA-2 rows present) before any `fundamentals_period` append.
4. **Shares:** prefer the quarterly balance-sheet count; `get_shares_full` fallback stored raw and deduped last-value-per-date at read (verified today: 27/166 duplicate dates on MSFT, 1.3% conflicts, gaps to 85 days); 90-day gap tolerance before STALE.
5. **Cache = archive** (§4.1 tables; core yfinance still has no response cache — issue #2486 open): prices/FX daily, STALE after 2 trading days without refresh; statements refreshed Saturdays, FRESH for a week, STALE after 14 failed days or a passed earnings date; yfinance's own cookie/tz cache left alone (prevents crumb storms). *Rejected: `yfinance-cache` — a ~200-line owned store keeps STALE semantics sovereign.*
6. **Propagation:** every derived figure carries its inputs' `fetched_at`; STALE/BOOTSTRAPPING are first-class trigger results; a stale/empty/non-positive denominator suspends that ticker's opportunity/fair-entry lines with a printed note — suppression is stated, silence never means "no opportunity" (MA-3); renderers build the G.2 data-health appendix from the same stamps.
7. **Three alarm states** (feeding §11): single ticker STALE → letter data note; rate-limited → DEGRADED banner + backoff; **all tickers failing 2 consecutive runs → "probable upstream breakage — check yfinance releases for a hotfix"** alert opening the emergency lane (§12.5) — matches every historical breakage episode without single-day false alarms.

---

## 8. Rendering & archive

- **f-string render functions**, one module per output; each returns `(telegram_html, markdown)` **from the same computed context dataclass** — one content pipeline, two skins, no parallel template duals. Deterministic by construction (locked decision 2), which is what makes byte-exact golden tests possible. *Rejected: jinja2 — a dependency to interpolate strings Python already interpolates.*
- **Pre-send register lint (`render/lint.py`), fail-closed** — adopted from the companion spec §8 and applied to *both* skins: rejects `!` in alert/question/reconciliation classes, red-alarm glyphs, €-with-digits tokens in daily output, benchmark tokens outside the quarterly document class; verifies the mandatory verbatim blocks (WHAT THIS IS NOT, the invitation closer, "Nothing is wrong; I just can't see."). A message failing lint is never sent as-is *and never silently dropped*: a safe minimal template ships instead and the failure surfaces in data-health. The constitution's register as structure, not author discretion.
- **Repo layout (committed):** `archive/letters|weekly|quarterly|alerts|events|gate/…` + `theses/TH-XXXX-NNN.md` (regenerated view: current fields + version log) + `journal/YYYY/JE-NNNN.md` (immutable file per entry; grades appended as dated sections).
- **Git mechanics:** `gitio.py` shells out (`git add <paths>` → `git commit` → `rev-parse HEAD` into `report.git_sha`). Commit failure is **non-fatal to delivery** (the letter already sits in the outbox; SQLite is the source of truth) — logged and surfaced as a data-health line. No push to any remote; `git push backup` targets the bare mirror on the second disk (§11.5). **The archive is derived data:** `agentcy render --rebuild` regenerates every file from the DB — archive corruption is never data loss.

---

## 9. Config & secrets

- **Secrets:** `/etc/stock-agentcy/agentcy.env`, mode 0600, exactly two entries — `AGENTCY_BOT_TOKEN`, `AGENTCY_OWNER_CHAT_ID` — injected via `EnvironmentFile=`. Never in the DB, git, or logs. Rotation = edit + restart the bot unit. Re-binding the owner chat is a desk operation, journaled.
- **Operational config lives in the `config` table, not a file** (§4.1): E.3 balance defaults, alert window, correlation threshold, `daily_letter_mode`, universe pin SHA, screen recipe. One write path (`agentcy config set … --reason`), journal-entry-first in one transaction — journaling is a foreign-key constraint, not a habit. *Rejected: a YAML/TOML tunables file — a second source of truth whose edits bypass FR8.* Static machine facts (paths) stay in code/units.
- Every `run_log.inputs_json` embeds the effective config, so "what defaults did this run use" is auditable forever.

---

## 10. Interactive sessions (the desk)

All qualitative/owner-typed work enters through the `agentcy` CLI (argparse, stdlib), run on the box (locally or over SSH) — data never leaves it:

| Command | Does |
|---|---|
| `agentcy gate start TICKER` / `resume` / `--backfill` | C.2→C.6 state machine: 2-sentence hard limit, Hell-No binaries, dossier (paced fetch; pauses on absent fundamentals), C.5 owner-judgment prompts verbatim (no defaults), trigger commitment (2–5, ≥1 moat-linked), verdict + journal + archive; backfill = same Gate minus price verdict, weight-ordered queue |
| `agentcy scout run qv` | H.2 recipe via the `[scout]` extra; results human-read, honest evidence note printed, never stored |
| `agentcy snapshot import <csv>` / `enter` | E.1 adapters → canonical contract; reconciliation prompts |
| `agentcy journal grade` | quarterly F.2 grading (appends `journal_grade`) |
| `agentcy absence start/end` · `config set` · `thesis show/revise` · `ask answer` · `event TICKER` · `render --rebuild` | D.6, §9, A.3 (goalpost guard enforced in `register.py`, not the UI), D.5 desk fallback, §8 |

**FR9, structurally:** conviction, mgmt_trust, circle_fit, and the ten-year statement are **interactive-prompt-only** — no flag, no stdin-JSON, no import path can supply them; the actor is journaled. `--json` exists on read/output surfaces only, so a desk Claude Code session can *inspect* state programmatically but qualitative fields enter solely as owner-typed answers. *(Panel conviction on the framework draft: `--json` input made FR9 fields machine-injectable, indistinguishable from owner-typed input.)*

**How a Claude Code session plugs in:** it is a drafting environment — it discusses the dossier, sharpens `business_model_2s` and the ten-year statement, reads `--json` output and the git archive. What enters the system is what the owner types at CLI prompts, through the same `register.py`/`journal.py` doors as everything else, so every invariant binds identically. The runtime contains zero LLM imports, endpoints, or hooks.

---

## 11. Failure modes & the dead-man switch

Layered; each layer independent of the ones below:

1. **Layer 0 — nothing hangs silently:** `TimeoutStartSec=30min` on every oneshot; the daemon watchdog (§5.2). A wedge becomes a failure, and failures have handlers.
2. **Layer 1 — the letter degrades before anything fails:** fetch retries → STALE stamping → degraded-letter-on-exception written to the outbox before re-raise (§1.3).
3. **Layer 2 — every failure notifies:** `OnFailure=agentcy-fail@%n` on every unit → a standalone script that direct-sends "unit %i FAILED — letter may be delayed; journalctl -u %i" via stdlib urllib + the env token, **deliberately bypassing the DB and the outbox** (the failure being reported may *be* the DB); if even that send fails it writes to journald and exits.
4. **Layer 3 — the human dead-man contract:** the 7-day 07:00 pulse (§1.4). Runbook, verbatim: *"No message by 08:00 Amsterdam = the box is down. SSH in; `systemctl status 'agentcy-*'`."* The letter's absence is the alarm — the letter must exist regardless, so its silence is loud.
5. **The one hole, named honestly:** during a declared absence with `daily_letter_mode=quiet`, letter absence is *expected* — a box death then means alerts (which quiet mode still promises) silently stop for the whole vacation. The only coverage is an **external content-free heartbeat** (healthchecks.io class: an HTTPS GET at the end of each successful daily run; ~26h alert window, valid year-round given the 7-day cadence; zero portfolio data leaves the box). Ruling: **default OFF** — a third-party liveness touchpoint sits against invariant 8 and is the owner's call, not a default (§15 S2). If ratified: journaled as the sole external touchpoint.
6. **Backups (§11.5), integrity, disk:** nightly `Connection.backup()` of both DBs (online, WAL-safe), retention 14 daily + 12 monthly; nightly `PRAGMA quick_check`, weekly full `integrity_check` → failure alerts; **rsync of backups + a bare git mirror to a second physical disk by default** (an untested single-disk backup dies with the disk); quarterly restore drill (§12.4 step 1). The daily job checks free disk and prints a DATA-section warning below 2 GB — disk-full is the classic multi-month silent killer of an append-only WAL + git box.
7. **Logs:** stdout/stderr → journald (rotation is the OS's problem; `SystemMaxUse=500M`). `run_log` is the audit trail; journald is the ops trail; no Python log files.

---

## 12. Ten-year upgrade posture

1. **OS:** Ubuntu 24.04 LTS + Ubuntu Pro (free personal tier) — security to May 2029 standard, **May 2034 ESM**, Legacy add-on to 2039 (verified). One optional planned hop (~2030) in a quarterly window.
2. **Interpreter — never the system Python** (apt 3.12 is upstream-EOL Oct 2028 and mutates under apt): **uv-managed CPython pinned to an exact 3.13.x patch** (`.python-version` + `requires-python`); deliberate bump every ~2–3 years (3.13 → 3.15 around 2028) inside a ritual window.
3. **Packaging:** one `pyproject.toml`, committed `uv.lock`, deploys via `uv sync --locked` — byte-identical environments. The pinned uv binary and a **full wheelhouse** are archived on-box, so a year-8 rebuild needs neither PyPI nor Astral to exist.
4. **Quarterly ritual — a numbered runbook (~1 hour), not hand-waving:** (1) restore drill — open newest backup, `integrity_check`, row-count sanity (also yields the rehearsal copy for any pending migration); (2) `uv lock --upgrade` into a quarantine venv (quantstats moves only here); (3) `tools/license_gate.py` — blocks on any violation; (4) offline suite + the network-marked **golden yfinance contract test** (EURUSD=X/^SP500TR history schema, MSFT quarterly statements non-empty with pinned rows, shares-dedup behavior); (5) promote lockfile, `uv sync --locked`, refresh wheelhouse, `systemd-analyze verify deploy/systemd/*`; (6) commit; journal `config_or_designation` if anything behavior-affecting moved.
5. **Emergency lane (yfinance only), pre-authorized:** history shows Yahoo breaks *old pinned versions in place* 1–2×/year (the 2025 429 wave permanently broke pre-curl_cffi pins). When the two-run all-fail alarm fires (§7.7), bumping yfinance immediately — quarantine venv → contract test → promote — is the sanctioned first remediation, outside the ritual. Insurance the panel flagged: **yfinance ≥1.4.0 makes curl_cffi optional with a plain-requests fallback** — if the compiled wheel is ever the blocker (e.g. at an interpreter bump), reinstall without it.
6. **Schema migrations:** numbered forward-only SQL applied at open, recorded in `schema_migration`; append-only tables are never destructively ALTERed (new columns/tables/views only); every migration is rehearsed against the ritual's restored backup first.
7. **When quantstats breaks** (0.0.x, bursty): the quarterly job's D.4 fallback — four hand-computed stats on pandas — is implemented code, not a promise; quantstats is removable at any ritual. **When Telegram breaks** (it measurably doesn't, for these five methods): a one-file fix, surfaced by the dead-man contract.

---

## 13. Testing strategy

- **Deterministic core:** analysis/render functions are pure (dataframes/dataclasses in, rows/strings out); every job takes the injected `clock.py` — which is also what makes catch-up and pause arithmetic testable.
- **No network, structurally:** an autouse fixture replaces socket connects with a raiser; the default suite runs fully offline. Live fixtures are recorded at the desk by `tools/record_fixtures.py` (healthy MSFT, the `(0,0)` empty frame, the duplicate-ridden shares series, 429 shapes).
- **Golden-report tests:** byte-compare both skins of G.1–G.4/alert/event against golden files for the canonical scenarios — all-clear, opportunity day, degraded data, alert storm, pause mode, catch-up morning, weekend pulse, holiday-vs-outage. The no-LLM decision makes these tests the output-format spec.
- **Freshness-gate tests (invariant 6):** stale/empty/non-positive fixtures must yield STALE/BOOTSTRAPPING/suspended wording — suspension printed, never silent; UNVERIFIABLE escalation at 3 weeks.
- **Structural-invariant tests:** raw UPDATE/DELETE aborts on every protected table; benchmark import-graph + ATTACH scan; `avg_open_price` grep over advice paths; import-graph proving quantstats/tradingview reachable only from their one module; register-lint unit tests; FR9 fields unreachable from any non-interactive input path.
- **Telegram client tests:** against an in-process stdlib `http.server` fake — request shapes, 429 retry_after, 4096 splitting, multipart encoding, owner-lock rejection, callback idempotence.
- **Deploy checks:** `systemd-analyze verify` + the license gate run in `install.sh`/ritual — there is no CI server to rot; the suite is a desk command.

---

## 14. Anti-complexity ledger (technology) — deliberately absent

**No web UI/dashboard** (one channel — locked 3) · **no webhooks/inbound ports/reverse proxy/TLS certs to renew** (long-poll only) · **no Docker/K8s** (systemd + uv already give reproducibility; a container runtime is a second OS to patch) · **no message broker/Redis** (the outbox table is the queue) · **no ORM** (SQL behind one door) · **no pydantic** (compiled-core coupling) · **no jinja2** (f-strings) · **no Telegram framework, no httpx/requests in our code** (five stdlib methods; the alert path has zero third-party dependencies) · **no scheduler library** (systemd timers; the due-run sweep is ~15 lines, not a scheduler) · **no asyncio/threads** (one owner, one chat, daily cadence) · **no libsystemd** (15-line datagram) · **no dulwich** (system git) · **no yfinance-cache** (owned store keeps STALE semantics sovereign) · **no exchange-calendar package** (market days read from the data, holiday≠outage) · **no external uptime service by default** (the letter is the heartbeat; the pause-mode hole is §15 S2, owner's call) · **no metrics stack** (journald + RunLog + the letter) · **no LLM calls in runtime** (locked 2) · **no email path** (locked 3) · **no second database engine** (the quarantine is a second *file*, not a second engine) · **no cloud backup/remote push** (local disks — NFR2). Every runtime import outside the stdlib traces to four owner-locked packages; each exclusion carries its NFR or constitution rule.

---

## 15. Spec amendments recorded & owner sign-off items

**Amendments to the functional elaboration (technology-phase, recorded here):**
- **A1 — Daily cadence:** the daily timer fires 7 days/week; the **full G.1 letter remains per US market day**; Sunday/Monday send a two-line heartbeat variant. Reason: the dead-man contract (§11.4) — a weekend blind window would gut "absence of the letter is the alarm". Amends the loop-spine's "once per market day" wording only in this narrow sense.
- **A2 — Delivery channel:** invariant 8's "owner's private mailbox" is implemented as the owner-locked Telegram chat; the email path is deleted (owner decision 2026-07-08).
- **A3 — Weekly EUR value transits Telegram** inside the weekly review document (owner accepted 2026-07-08); all stores remain local-only.

**Owner sign-off items (journaled as `config_or_designation` when decided):**
- **S1 — certifi MPL-2.0 exception** (§2.2): unavoidable via the locked yfinance tree; recommended **accept**, signed once at bootstrap, covering the venv.
- **S2 — external dead-man ping** (§11.5): default **OFF**; the only coverage for box-death during a quiet-mode absence. Recommended: decide before the first multi-week absence.
- **S3 — second-disk backup target** (§11.6): on by default; a physical second disk must be designated at install.

---

## 16. Panel provenance — synthesis rulings

Three drafts (stdlib-maximalist · proven-framework single-process · ops-durability-first) + a Telegram UX spec, judged by three lenses (constitution/NFR fidelity · Munger minimalism · 10-year durability) over a live-verified fact pack. Fidelity and minimalism ranked the stdlib draft first; durability ranked ops first; convergence across drafts was ~80% (two-DB quarantine, append-only triggers, outbox, HTML mode, stdlib sd_notify, uv posture, yfinance parameters, quantstats fallback — settled by convergence).

| # | Ruling | Basis |
|---|---|---|
| 1 | Stdlib spine (timers + oneshots + sync daemon + hand-rolled Telegram client) | won fidelity + minimalism; zero third-party code on the alert path |
| 2 | System units `User=agentcy`, not user units + linger | durability conviction: lost linger = total silence with no failed unit |
| 3 | `TimeoutStartSec=30min` everywhere; StartLimit + sandbox on the daemon | durability convictions on the winning draft itself |
| 4 | Due-run sweep + outbox `dedupe_key` grafted from the framework draft | the only mechanisms making "never skipped" checked and "at-least-once" exactly-once |
| 5 | Framework draft rejected as architecture | monolith fault domain; aiogram churn/coupling; `--json` FR9 breach — identity, not curable |
| 6 | 7-day letter pulse; external ping default-OFF | invariant-8-clean dead-man; ops draft's default-ON ping + Tue–Sat cadence was internally inconsistent (guaranteed weekend false alarms) |
| 7 | Event checks via spool + path unit | cures both the unsupervised-subprocess conviction and the polkit objection |
| 8 | Price cache append-only latest-wins; trigger state derived; no stamped `framework_status`; no `state_transition` ledger; single flock pacing | invariant-1 conviction + minimalism deletions applied to the merged schema |
| 9 | certifi exception journaled once, venv-wide; PSF whitelisted; license gate executable | fidelity ruling: NFR7 as a gate, not memory; the exception must not re-argue aiogram |
| 10 | UX spec adopted with three amendments (pre-provisioned chat-id; headline-first weekly; HTML locked) | fidelity convictions on the spec; applied in the companion file |

**Parked, unchanged:** eToro API verification (E.1 contract keeps it a swap-in adapter); SEC EDGAR fallback; TradingView ToS posture. **Next step:** implementation plan (repo scaffold, migration 000, the §12.4 install runbook).
