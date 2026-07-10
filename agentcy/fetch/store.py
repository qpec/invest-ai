"""Cache-is-archive read/write surface (tech-arch §7.5; contracts §3.7).

Writes go through agentcy.db append helpers only; freshness/TTL stamps are
computed here at READ time. Frame shapes are the fetch/yf.py normalized ones."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from agentcy import db
from agentcy.freshness import DataState, Stamped

PRICE_STALE_WEEKDAYS = 2            # §7.5: STALE after 2 trading days without a new bar (plan note 2)
STATEMENT_EARNINGS_GRACE_DAYS = 14  # §7.5 "14 failed days" after a passed earnings date (plan note 1)
STATEMENT_MAX_AGE_DAYS = 135        # no-calendar fallback: quarter + reporting lag + slack (plan note 1)
SHARES_GAP_DAYS = 90                # §7.4 gap tolerance
CALENDAR_PREVIEW_DAYS = 21          # D.1 check 5 (MA-7)


@dataclass(frozen=True)
class PriceBar:
    bar_date: str
    close: float
    adj_close: float
    dividend: float
    currency: str


def store_price_bars(conn, yf_ticker: str, frame: pd.DataFrame, *, run_id: int | None, fetched_at: str) -> int:
    """Append bars (re-fetches append, never overwrite; v_price serves latest); returns rows written."""
    rows = [
        {
            "yf_ticker": yf_ticker,
            "bar_date": pd.Timestamp(idx).date().isoformat(),
            "close": float(r["close"]),
            "adj_close": float(r["adj_close"]),
            "dividend": float(r["dividend"]),
            "currency": str(r["currency"]),
            "fetched_at": fetched_at,
            "run_id": run_id,
        }
        for idx, r in frame.iterrows()
    ]
    return db.append_price_rows(conn, rows)


def _weekdays_between(d0: date, d1: date) -> int:
    """Weekdays strictly between d0 and d1 — the calendar-free trading-day proxy (plan note 2)."""
    n, d = 0, d0 + timedelta(days=1)
    while d < d1:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def _bar_state(bar_date: str, as_of: datetime) -> DataState:
    behind = _weekdays_between(date.fromisoformat(bar_date), as_of.date())
    return DataState.STALE if behind >= PRICE_STALE_WEEKDAYS else DataState.FRESH


def latest_close(conn, yf_ticker: str, *, as_of: datetime) -> Stamped[PriceBar] | None:
    """Latest bar at/before as_of, stamped; STALE after 2 trading days without refresh (§7.5)."""
    rows = db.fetch_v_price(conn, yf_ticker, end=as_of.date().isoformat())
    if not rows:
        return None
    row = max(rows, key=lambda r: r["bar_date"])
    state = _bar_state(row["bar_date"], as_of)
    note = None
    if state is DataState.STALE:
        note = f"last bar {row['bar_date']} — stale at {as_of.date().isoformat()} (§7.5 ladder)"
    bar = PriceBar(row["bar_date"], float(row["close"]), float(row["adj_close"]),
                   float(row["dividend"]), row["currency"])
    return Stamped(bar, db.from_iso(row["fetched_at"]), state, note)


def price_state(conn, yf_ticker: str, *, as_of: datetime) -> DataState:
    """FRESH/STALE per the §7.5 ladder; no bars at all is STALE."""
    stamped = latest_close(conn, yf_ticker, as_of=as_of)
    return DataState.STALE if stamped is None else stamped.state


def fx_rate_eur(conn, currency: str, *, as_of: datetime) -> Stamped[float] | None:
    """{CUR}EUR=X latest close, stamped; EUR itself returns 1.0 FRESH."""
    cur = currency.upper()
    if cur == "EUR":
        return Stamped(1.0, as_of, DataState.FRESH)
    stamped = latest_close(conn, f"{cur}EUR=X", as_of=as_of)
    if stamped is None:
        return None
    return Stamped(float(stamped.value.close), stamped.fetched_at, stamped.state, stamped.note)


def _fingerprint(payload_json: str) -> str:
    """Stable content hash over one period's payload — a revision changes it, an
    identical re-fetch does not (drives fundamentals_period dedup + the D.3 feed)."""
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:16]


def store_statements(conn, yf_ticker: str, statements: dict[str, pd.DataFrame], *,
                     run_id: int | None, fetched_at: str) -> list[str]:
    """Append per-period rows on unseen fingerprint only; returns NEW fingerprint tags
    '{statement_type}:{period_end}:{fp}' (the D.3 earnings-detector feed, §3.7)."""
    new: list[str] = []
    for stype in ("income", "balance", "cashflow"):
        frame = statements.get(stype)
        if frame is None or frame.shape[1] == 0:
            continue
        for col in frame.columns:
            period_end = pd.Timestamp(col).date().isoformat()
            # canonical per-period payload: {row_label: value}, NaN preserved as null, sorted keys
            col_series = frame[col]
            payload = {str(k): (None if pd.isna(v) else float(v)) for k, v in col_series.items()}
            payload_json = json.dumps(payload, sort_keys=True)
            fp = _fingerprint(payload_json)
            wrote = db.append_fundamentals_period(
                conn, yf_ticker=yf_ticker, statement_type=stype, period_end=period_end,
                payload_json=payload_json, fingerprint=fp, fetched_at=fetched_at, run_id=run_id,
            )
            if wrote:
                new.append(f"{stype}:{period_end}:{fp}")
    return new


def _statement_state(rows: list, as_of: datetime, next_earnings: str | None) -> DataState:
    """§7.5 TTL (plan note 1): STALE when a passed calendar earnings (newer than the newest
    archived period) is >14 days old with no new data, OR — with no such signal — the newest
    period_end is older than 135 days. FRESH otherwise. Empty archive is STALE."""
    if not rows:
        return DataState.STALE
    newest_period = max(date.fromisoformat(r["period_end"]) for r in rows)
    if next_earnings:
        exp = date.fromisoformat(next_earnings)
        if exp > newest_period and exp <= as_of.date() and (as_of.date() - exp).days > STATEMENT_EARNINGS_GRACE_DAYS:
            return DataState.STALE
    if (as_of.date() - newest_period).days > STATEMENT_MAX_AGE_DAYS:
        return DataState.STALE
    return DataState.FRESH


def statement_history(conn, yf_ticker: str, statement_type: str, *, as_of: datetime) -> Stamped[list]:
    """Accumulated archive (latest fingerprint per period_end, ascending); STALE after 14
    failed days past a passed earnings date or a 135-day-old newest period (§7.5)."""
    rows = db.fetch_statement_periods(conn, yf_ticker, statement_type)
    cal = db.fetch_earnings_calendar(conn, yf_ticker)
    next_earnings = cal["expected_date"] if cal else None
    state = _statement_state(rows, as_of, next_earnings)
    if not rows:
        return Stamped([], as_of, DataState.STALE, f"{yf_ticker} {statement_type}: no statements archived")
    fetched_at = db.from_iso(max(r["fetched_at"] for r in rows))
    note = None
    if state is DataState.STALE:
        newest = max(r["period_end"] for r in rows)
        note = f"{yf_ticker} {statement_type}: newest period {newest} stale at {as_of.date().isoformat()} — suspended, not passed (§7.5)"
    return Stamped(list(rows), fetched_at, state, note)


def store_shares(conn, yf_ticker: str, series: pd.Series, *, fetched_at: str) -> int:
    """Append raw observations (duplicates included; dedup happens at read, §7.4); returns rows."""
    rows = [
        {
            "yf_ticker": yf_ticker,
            "obs_date": pd.Timestamp(idx).date().isoformat(),
            "shares": float(val),
            "fetched_at": fetched_at,
        }
        for idx, val in series.items()
    ]
    return db.append_shares_rows(conn, rows)


def shares_history(conn, yf_ticker: str, *, as_of: datetime) -> Stamped[pd.Series]:
    """Deduped last-value-per-date at read; 90-day gap tolerance before STALE (§7.4)."""
    raw = db.fetch_shares_raw(conn, yf_ticker)   # ordered obs_date, fetched_at, rowid ascending
    if not raw:
        return Stamped(pd.Series(dtype=float), as_of, DataState.STALE,
                       f"{yf_ticker}: no shares series (§7.4)")
    # last row per obs_date wins (ascending order => later rows overwrite in the dict)
    by_date: dict[str, float] = {}
    fetched: dict[str, str] = {}
    for r in raw:
        by_date[r["obs_date"]] = float(r["shares"])
        fetched[r["obs_date"]] = r["fetched_at"]
    idx = pd.to_datetime(sorted(by_date))
    series = pd.Series([by_date[d.date().isoformat()] for d in idx], index=idx, dtype=float)
    newest = max(date.fromisoformat(d) for d in by_date)
    state = DataState.STALE if (as_of.date() - newest).days > SHARES_GAP_DAYS else DataState.FRESH
    note = None
    if state is DataState.STALE:
        note = f"{yf_ticker}: shares last observed {newest.isoformat()} — >{SHARES_GAP_DAYS}d gap at {as_of.date().isoformat()} (§7.4)"
    fetched_at = db.from_iso(max(fetched.values()))
    return Stamped(series, fetched_at, state, note)


def store_officers(conn, yf_ticker: str, officers: list[dict], *, fetched_at: str) -> bool:
    """Append snapshot; True when the fingerprint CHANGED vs the previous snapshot (queues
    the B.2 officer-diff question). First-ever snapshot is a baseline -> False (plan note 6)."""
    normalized = sorted(
        ({"name": str(o.get("name", "")), "title": str(o.get("title", ""))} for o in officers),
        key=lambda o: o["name"],
    )
    officers_json = json.dumps(normalized, sort_keys=True)
    fp = _fingerprint(officers_json)
    prev = db.fetch_latest_officers(conn, yf_ticker)
    db.append_officer_snapshot(conn, yf_ticker=yf_ticker, officers_json=officers_json,
                               fingerprint=fp, fetched_at=fetched_at)
    if prev is None:
        return False                     # baseline: no tripwire on first observation
    return prev["fingerprint"] != fp


def store_calendar(conn, yf_ticker: str, expected_date: str, *, run_id: int | None, fetched_at: str) -> None:
    """Append a best-effort calendar-estimate row (MA-7; preview only, never triggers)."""
    db.append_earnings_calendar(conn, yf_ticker=yf_ticker, expected_date=expected_date,
                                fetched_at=fetched_at, run_id=run_id)


def next_expected_earnings(conn, yf_ticker: str, *, as_of: datetime) -> str | None:
    """Preview-only 'calendar estimate' date within 21 days of as_of (D.1 check 5); else None."""
    cal = db.fetch_earnings_calendar(conn, yf_ticker)
    if not cal:
        return None
    expected = date.fromisoformat(cal["expected_date"])
    delta = (expected - as_of.date()).days
    return cal["expected_date"] if 0 <= delta <= CALENDAR_PREVIEW_DAYS else None


@dataclass(frozen=True)
class OwnerEarnings:
    """MA-11 pinned construction, all-or-STALE."""
    fcf_ttm: float
    sbc_ttm: float
    owner_fcf_ttm: float
    owner_fcf_per_share_ttm: float
    owner_fcf_margin_ttm: float
    periods_used: tuple[str, ...]


def _period_payloads(rows: list) -> dict[str, dict]:
    """period_end -> decoded payload dict (latest fingerprint per period, from the archive)."""
    return {r["period_end"]: json.loads(r["payload_json"]) for r in rows}


def owner_fcf_ttm(conn, yf_ticker: str, *, as_of: datetime) -> Stamped[OwnerEarnings] | None:
    """Sum of last 4 quarterly (OCF - |CapEx|) - SBC; ANY empty/missing period -> None (not
    computable), any stale input -> Stamped(STALE); never a partial sum (MA-11/BUF-5)."""
    cf = statement_history(conn, yf_ticker, "cashflow", as_of=as_of)
    inc = statement_history(conn, yf_ticker, "income", as_of=as_of)
    cf_pay = _period_payloads(cf.value)
    inc_pay = _period_payloads(inc.value)
    periods = sorted(cf_pay, reverse=True)[:4]               # newest 4 quarters
    if len(periods) < 4:
        return None                                          # too short -> not computable (MA-1/MA-11)
    fcf = sbc = revenue = 0.0
    for p in periods:
        cell = cf_pay[p]
        ocf = cell.get("Operating Cash Flow")
        capex = cell.get("Capital Expenditure")
        if ocf is None or capex is None:
            return None                                      # a required pinned value missing -> not computable
        fcf += float(ocf) - abs(float(capex))
        sbc += float(cell.get("Stock Based Compensation") or 0.0)  # SBC-free filer -> 0 (plan note 4)
        rev = inc_pay.get(p, {}).get("Total Revenue")
        revenue += float(rev) if rev is not None else 0.0
    owner_fcf = fcf - sbc

    shares = shares_history(conn, yf_ticker, as_of=as_of)
    if len(shares.value) == 0:
        return None                                          # no share count -> per-share not computable
    # latest observation at/before as_of; shares_history is not as_of-filtered so iloc[-1]
    # would overshoot to a post-as_of print (plan typo fix — matches the healthy test's
    # "deduped last-per-date shares near as_of (7.434e9 on 2026-04-01)").
    at_or_before = shares.value[shares.value.index <= pd.Timestamp(as_of.date())]
    if len(at_or_before) == 0:
        return None                                          # no share count at/before as_of
    share_count = float(at_or_before.iloc[-1])
    if share_count <= 0:
        return None
    per_share = owner_fcf / share_count
    margin = (owner_fcf / revenue) if revenue > 0 else 0.0

    # all-or-STALE: any stale input degrades the whole figure (never a partial-fresh sum)
    state = DataState.FRESH
    notes = []
    for s in (cf, inc, shares):
        if s.state is not DataState.FRESH:
            state = DataState.STALE
            if s.note:
                notes.append(s.note)
    fetched_at = min(cf.fetched_at, inc.fetched_at, shares.fetched_at)
    oe = OwnerEarnings(fcf, sbc, owner_fcf, per_share, margin, tuple(sorted(periods)))
    return Stamped(oe, fetched_at, state, "; ".join(notes) or None)


def denominator_per_share(conn, yf_ticker: str, *, as_of: datetime) -> Stamped[float] | None:
    """Owner-FCF per share for E.4; stale/empty/non-positive -> not usable() -> that ticker's
    checks SUSPENDED with a printed note (MA-3). None only when not computable at all."""
    oe = owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if oe is None:
        return None
    per_share = oe.value.owner_fcf_per_share_ttm
    if per_share <= 0:
        note = (oe.note + "; " if oe.note else "") + \
            f"{yf_ticker}: owner-FCF per share {per_share:.4f} non-positive — checks suspended (MA-3)"
        return Stamped(per_share, oe.fetched_at, DataState.STALE, note)
    return Stamped(per_share, oe.fetched_at, oe.state, oe.note)


# --- P3 derived series (pure functions of the append-only archive; no fetch) ---
import json as _json


def revenue_yoy_series(conn, yf_ticker, *, as_of):
    """Per-period revenue YoY % from the income 'Total Revenue' row (same-quarter-prior-year lag)."""
    hist = statement_history(conn, yf_ticker, "income", as_of=as_of)
    if hist is None or not hist.usable():
        return hist
    periods = [(r["period_end"], _json.loads(r["payload_json"]).get("Total Revenue"))
               for r in hist.value]
    periods = [(pe, v) for pe, v in periods if v]
    # Match each period to the observation one year earlier by date (month+day), so gapped or
    # irregular archives still line up the correct comparison quarter (index-4-back breaks on gaps).
    by_key = {pe[5:]: [] for pe, _ in periods}
    for pe, v in periods:
        by_key[pe[5:]].append((pe, v))
    out = []
    for pe, rev in periods:
        prior_year = str(int(pe[:4]) - 1)
        prior = next(((p, pv) for p, pv in by_key[pe[5:]] if p[:4] == prior_year and pv), None)
        if prior:
            out.append((pe, 100.0 * (rev - prior[1]) / prior[1]))
    return _restamp(hist, out)


def margin_series(conn, yf_ticker, *, as_of):
    """Owner-FCF margin % TTM per period; delegates to owner_fcf_ttm's per-period construction."""
    oe = owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    if oe is None or not oe.usable():
        return oe
    return _restamp(oe, [(oe.value.periods_used[-1], 100.0 * oe.value.owner_fcf_margin_ttm)])


def balance_safety_series(conn, yf_ticker, *, as_of):
    """Net-debt / EBITDA per period (MA-2 pinned rows; drop periods with any absent row)."""
    inc = statement_history(conn, yf_ticker, "income", as_of=as_of)
    bal = statement_history(conn, yf_ticker, "balance", as_of=as_of)
    if inc is None or bal is None or not (inc.usable() and bal.usable()):
        return inc if inc is not None else bal
    bal_by_pe = {r["period_end"]: _json.loads(r["payload_json"]) for r in bal.value}
    out = []
    for r in inc.value:
        b = bal_by_pe.get(r["period_end"], {})
        income = _json.loads(r["payload_json"])
        debt, cash, ebitda = b.get("Total Debt"), b.get("Cash And Cash Equivalents"), income.get("EBITDA")
        if None in (debt, cash, ebitda) or not ebitda:
            continue                                       # any absent row -> drop (never a silent zero)
        out.append((r["period_end"], (debt - cash) / ebitda))
    return _restamp(inc, out)


def shares_yoy(conn, yf_ticker, *, as_of):
    """Trailing-12m share-count growth % (B.2 type 4). The baseline is the observation ~365
    days before the latest — nearest on/before (latest_date - 365d) — NOT the earliest row in
    the append-only archive (that stretches the '12-month' window over years as history
    accumulates, silently inflating the dilution figure). No ~1y-ago observation -> STALE."""
    sh = shares_history(conn, yf_ticker, as_of=as_of)
    if sh is None or not sh.usable():
        return sh
    series = sh.value                                      # pd.Series indexed by date, deduped ascending
    # anchor on the latest observation at/before as_of (the series is not as_of-filtered, so a
    # post-as_of print would otherwise leak into "the latest").
    at_or_before = series[series.index <= pd.Timestamp(as_of.date())]
    if len(at_or_before) < 2:
        return _restamp(sh, None)
    latest_ts = at_or_before.index[-1]
    latest = float(at_or_before.iloc[-1])
    window_start = latest_ts - pd.Timedelta(days=365)
    baseline_window = at_or_before[at_or_before.index <= window_start]   # nearest on/before -365d
    if len(baseline_window) == 0:
        note = (f"{yf_ticker}: no shares observation ~1y before {latest_ts.date().isoformat()} "
                f"— trailing-12m dilution not measurable (B.2 type 4)")
        return Stamped(value=None, fetched_at=sh.fetched_at, state=DataState.STALE, note=note)
    year_ago = float(baseline_window.iloc[-1])
    return _restamp(sh, 100.0 * (latest - year_ago) / year_ago if year_ago else None)


def _restamp(src, value):
    from agentcy.freshness import Stamped
    return Stamped(value=value, fetched_at=src.fetched_at, state=src.state, note=src.note)
