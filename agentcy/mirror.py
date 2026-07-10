"""agentcy/mirror.py — Portfolio Mirror (E): ingest, reconciliation, designations, balance."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta

from agentcy import db
from agentcy.clock import Clock


@dataclass(frozen=True)
class PositionIn:
    symbol: str
    yf_ticker: str | None
    instrument_type: str
    quantity: float
    avg_open_price: float | None
    native_currency: str
    mv_native: float
    mv_eur: float
    weight: float
    leverage: float = 1.0


@dataclass(frozen=True)
class PositionDetailIn:
    """Rich per-position record for the position_detail table (api_pull source only).

    All optional except symbol; column-for-column with schema/001_position_detail.sql.
    NEVER read by positions_advice / the balance path (invariant 4) — record-keeping only.
    """
    symbol: str
    opened_at: str | None = None
    invested_native: float | None = None
    invested_eur: float | None = None
    unrealized_pnl_native: float | None = None
    unrealized_pnl_pct: float | None = None
    current_rate: float | None = None
    direction: str | None = None
    lot_count: int | None = None
    raw_json: str | None = None


@dataclass(frozen=True)
class SnapshotIn:
    as_of: str
    source: str
    cash_balance_eur: float
    positions: tuple[PositionIn, ...]
    details: tuple[PositionDetailIn, ...] = ()


def _yf_for(symbol: str, instrument_type: str) -> str | None:
    """MA-4: crypto/copyportfolio are non-mappable; stock/etf fall back to the symbol itself."""
    if instrument_type in ("crypto", "copyportfolio"):
        return None
    return symbol


def parse_etoro_csv(text: str) -> SnapshotIn:
    """E.1 CSV adapter -> canonical contract; ValueError with a line-level message on bad input."""
    reader = csv.DictReader(io.StringIO(text))
    rows, cash = [], 0.0
    for i, row in enumerate(reader, start=1):
        try:
            itype = row["instrument_type"].strip()
            mv_eur = float(row["market_value_eur"])
            if itype == "cash" or row["symbol"].strip().upper() == "CASH":
                cash += mv_eur
                continue
            rows.append({
                "symbol": row["symbol"].strip(), "instrument_type": itype,
                "quantity": float(row["quantity"]),
                "avg_open_price": float(row["avg_open_price"]) if row["avg_open_price"] else None,
                "native_currency": row["native_currency"].strip(),
                "mv_native": float(row["market_value_native"]), "mv_eur": mv_eur,
                "leverage": float(row.get("leverage") or 1.0),
            })
        except (KeyError, ValueError) as e:
            raise ValueError(f"malformed snapshot CSV at line {i}: {e}") from e
    total = sum(r["mv_eur"] for r in rows) or 1.0
    positions = tuple(
        PositionIn(symbol=r["symbol"], yf_ticker=_yf_for(r["symbol"], r["instrument_type"]),
                   instrument_type=r["instrument_type"], quantity=r["quantity"],
                   avg_open_price=r["avg_open_price"], native_currency=r["native_currency"],
                   mv_native=r["mv_native"], mv_eur=r["mv_eur"], weight=r["mv_eur"] / total,
                   leverage=r["leverage"])
        for r in rows)
    return SnapshotIn(as_of=datetime.now().date().isoformat(), source="manual_export",
                      cash_balance_eur=cash, positions=positions)


def parse_manual_text(text: str) -> SnapshotIn:
    """Manual-entry adapter (the /snapshot text paste): 'SYMBOL QTY MV_EUR [CCY]' + 'cash: N'."""
    rows, cash = [], 0.0
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("cash:"):
            cash = float(line.split(":", 1)[1])
            continue
        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"malformed manual line {i}: expected 'SYMBOL QTY MV_EUR [CCY]'")
        sym, qty, mv = parts[0], float(parts[1]), float(parts[2])
        ccy = parts[3] if len(parts) > 3 else "EUR"
        rows.append((sym, qty, mv, ccy))
    total = sum(mv for _, _, mv, _ in rows) or 1.0
    positions = tuple(
        PositionIn(symbol=s, yf_ticker=_yf_for(s, "stock"), instrument_type="stock", quantity=q,
                   avg_open_price=None, native_currency=ccy, mv_native=mv, mv_eur=mv,
                   weight=mv / total, leverage=1.0)
        for s, q, mv, ccy in rows)
    return SnapshotIn(as_of=datetime.now().date().isoformat(), source="manual_entry",
                      cash_balance_eur=cash, positions=positions)


@dataclass(frozen=True)
class Delta:
    kind: str            # appeared | disappeared | quantity_change | unexplained_cash | leverage_violation
    symbol: str | None
    detail: str
    old_value: float | None
    new_value: float | None


def ingest_snapshot(conn, snap: SnapshotIn, *, clock: Clock) -> tuple[int, list[Delta]]:
    """Append snapshot+positions; reconcile vs previous; caller mints one R ask per Delta."""
    prev = db.fetch_latest_snapshot(conn)
    prev_positions = (db.fetch_positions_records(conn, prev["snapshot_id"]) if prev else [])
    prev_by_sym = {p["symbol"]: p for p in prev_positions}
    snapshot_id = db.append_snapshot(conn, as_of=snap.as_of, source=snap.source,
                                     cash_balance_eur=snap.cash_balance_eur,
                                     created_at=db.to_iso(clock.now()))
    # Persist the E.1/MA-4 invariants regardless of how the PositionIn was built:
    # weight = fraction of invested MV; yf_ticker mappability = f(instrument_type).
    total_mv = sum(p.mv_eur for p in snap.positions) or 1.0
    db.append_positions(conn, snapshot_id, [{
        "symbol": p.symbol, "yf_ticker": _yf_for(p.symbol, p.instrument_type),
        "instrument_type": p.instrument_type,
        "quantity": p.quantity, "avg_open_price": p.avg_open_price,
        "native_currency": p.native_currency, "mv_native": p.mv_native, "mv_eur": p.mv_eur,
        "weight": p.mv_eur / total_mv, "leverage": p.leverage} for p in snap.positions])
    deltas: list[Delta] = []
    now_by_sym = {p.symbol: p for p in snap.positions}
    # leverage tripwire — every snapshot, regardless of previous state (E.1 continuous Hell-No)
    for p in snap.positions:
        if p.leverage > 1.0:
            deltas.append(Delta("leverage_violation", p.symbol,
                                f"leverage {p.leverage} on {p.instrument_type}", 1.0, p.leverage))
    if prev is None:
        return snapshot_id, deltas                        # baseline: no appeared/disappeared
    for sym, p in now_by_sym.items():
        if sym not in prev_by_sym:
            deltas.append(Delta("appeared", sym, f"new position {sym}", None, p.quantity))
        elif p.quantity != prev_by_sym[sym]["quantity"]:
            deltas.append(Delta("quantity_change", sym, "quantity changed",
                                prev_by_sym[sym]["quantity"], p.quantity))
    for sym in prev_by_sym:
        if sym not in now_by_sym:
            deltas.append(Delta("disappeared", sym, f"{sym} no longer present",
                                prev_by_sym[sym]["quantity"], None))
    cash_delta = snap.cash_balance_eur - prev["cash_balance_eur"]
    position_moved = any(d.kind in ("disappeared", "quantity_change") for d in deltas)
    if abs(cash_delta) > 1.0 and not position_moved:
        deltas.append(Delta("unexplained_cash", None, f"cash moved by {cash_delta:+.1f}",
                            prev["cash_balance_eur"], cash_delta))
    return snapshot_id, deltas


# --- reconciliation R-ask minting (E.1/§3.4, MA-12) ------------------------------
# The ingest contract says "caller mints one R ask per Delta". This is that shared
# producer, called by BOTH the desk (cli._cmd_snapshot) and the bot
# (daemon._handle_document) after ingest_snapshot. Each non-trivial Delta becomes an
# open R-ask loop (jobs/daily.open_loop_lines surfaces + escalates it); leverage_violation
# is instead the immediate Hell-No leverage tripwire notice, not an R-ask (E.1).
# Function-level imports keep mirror free of the tg/asks import weight at module load.

_LEVERAGE_TRIPWIRE_HTML = (
    "Hell-No leverage tripwire: {sym} carries leverage {lev} ({detail}). The Constitution's "
    "leverage veto is enforced continuously — borrowing against a volatile position is off-path. "
    "Deleverage is the standing advice; I never trade.")


def _recon_ask_spec(d: "Delta") -> tuple[str, list[str], bool] | None:
    """(prompt, options, expects_freetext) for a delta, or None for leverage_violation
    (handled as a tripwire notice) — enumerated per §3.4."""
    if d.kind == "appeared":
        return (f"Reconciliation — new position: {d.symbol}, {d.detail}, not previously seen. "
                "How should I treat it?",
                ["backfill", "outside", "ignore"], False)
    if d.kind == "disappeared":
        return (f"Reconciliation — {d.symbol} no longer appears in the snapshot. "
                "Did you close it? A close needs the one-line reasoning-at-the-moment.",
                ["close", "gap"], True)
    if d.kind == "quantity_change":
        opts = ["add"]
        if d.new_value is not None and d.old_value is not None and d.new_value < d.old_value:
            opts.append("trim")                               # trim shown only when qty fell
        opts.append("gap")
        return (f"Reconciliation — {d.symbol} quantity changed {d.old_value} → {d.new_value}. "
                "Add or trim? A change needs the one-line reasoning-at-the-moment.",
                opts, True)
    if d.kind == "unexplained_cash":
        # The full MA-12 external-flow set (matches external_flow.direction CHECK); 'other'
        # takes a ForceReply note.
        return (f"Reconciliation — {d.detail} with no matching position change. "
                "What was it? ('other' takes a note.)",
                ["deposit", "withdrawal", "dividend", "other"], True)
    return None


def mint_reconciliation_asks(conn, snapshot_id: int, deltas: "list[Delta]", *,
                             clock: Clock) -> list:
    """Mint one open R-ask per non-trivial Delta (E.1/§3.4); enqueue the Hell-No leverage
    tripwire notice for each leverage_violation. Returns the minted Ask objects.

    The snapshot is already accepted append-only — these are open loops that do not block
    ingest (§3.4). The symbol rides on thesis_ref so the answer-time consequence can act on
    it; the unexplained-cash flow attaches to snapshot_id (MA-12)."""
    from agentcy import asks
    from agentcy.tg import outbox
    minted = []
    for d in deltas:
        if d.kind == "leverage_violation":
            outbox.enqueue(
                conn, dedupe_key=f"leverage:{snapshot_id}:{d.symbol}", kind="notice",
                payload_html=_LEVERAGE_TRIPWIRE_HTML.format(
                    sym=d.symbol, lev=d.new_value, detail=d.detail),
                clock=clock)
            continue
        spec = _recon_ask_spec(d)
        if spec is None:
            continue
        prompt, options, expects_freetext = spec
        minted.append(asks.mint(
            conn, kind="R", prompt=prompt, options=options, expects_freetext=expects_freetext,
            thesis_ref=d.symbol, clock=clock))
    return minted


@dataclass(frozen=True)
class AdvicePosition:
    snapshot_id: int
    symbol: str
    yf_ticker: str | None
    instrument_type: str
    quantity: float
    native_currency: str
    mv_native: float
    mv_eur: float
    weight: float
    leverage: float


def advice_positions(conn, snapshot_id: int | None = None) -> list[AdvicePosition]:
    """The ONLY position read for balance/jobs/render — backed by positions_advice (invariant 4)."""
    if snapshot_id is None:
        latest = db.fetch_latest_snapshot(conn)
        if latest is None:
            return []
        snapshot_id = latest["snapshot_id"]
    return [AdvicePosition(
        snapshot_id=r["snapshot_id"], symbol=r["symbol"], yf_ticker=r["yf_ticker"],
        instrument_type=r["instrument_type"], quantity=r["quantity"],
        native_currency=r["native_currency"], mv_native=r["mv_native"], mv_eur=r["mv_eur"],
        weight=r["weight"], leverage=r["leverage"])
        for r in db.fetch_positions_advice(conn, snapshot_id)]


_OUTSIDE_TYPES = frozenset({"crypto", "copyportfolio", "etf"})


def framework_status(conn, symbol: str, *, as_of: datetime) -> str:
    """Derived from latest designation; equity default backfill_pending; etf/crypto -> outside (E.2)."""
    designations = db.fetch_latest_designations(conn)
    if symbol in designations:
        return designations[symbol]["framework_status"]
    positions = advice_positions(conn)
    itype = next((p.instrument_type for p in positions if p.symbol == symbol), "stock")
    return "outside_framework" if itype in _OUTSIDE_TYPES else "backfill_pending"


def designate(conn, symbol: str, status: str, *, journal_ref: int, valid_from: str) -> None:
    """Append a designation (latest wins)."""
    db.append_designation(conn, symbol=symbol, framework_status=status, valid_from=valid_from,
                          journal_ref=journal_ref)


def backfill_queue(conn, *, as_of: datetime) -> list[str]:
    """backfill_pending symbols by weight desc, largest first (C.6)."""
    # weight is a fraction of invested MV (adapter-computed); mv_eur breaks ties
    # deterministically for equal/absent weights (both are monotonic within a snapshot).
    ranked = sorted(advice_positions(conn), key=lambda p: (p.weight, p.mv_eur), reverse=True)
    return [p.symbol for p in ranked if framework_status(conn, p.symbol, as_of=as_of) == "backfill_pending"]


def snapshot_age(conn, *, as_of: datetime) -> "timedelta | None":
    """Age of the latest snapshot (E.1 staleness ladder)."""
    latest = db.fetch_latest_snapshot(conn)
    if latest is None or as_of is None:
        return None
    return as_of - db.from_iso(latest["as_of"]) if "T" in latest["as_of"] else \
        as_of - datetime.fromisoformat(latest["as_of"]).replace(tzinfo=as_of.tzinfo)


from agentcy import cluster as _cluster, config as _config


@dataclass(frozen=True)
class BalanceReport:
    cash_pct: float
    cash_in_band: bool
    n_framework: int
    n_backfill: int
    n_outside: int
    position_count_in_band: bool
    soft_cap_breaches: tuple[str, ...]
    hard_cap_breaches: tuple[str, ...]
    cluster_weight_breaches: tuple[str, ...]
    n_eff: float | None
    n_eff_ok: bool | None
    outside_framework_pct: float
    outside_cap_ok: bool
    unpriced_weight_pct: float
    leverage_violations: tuple[str, ...]


def balance(conn, *, as_of: datetime, returns_local=None) -> BalanceReport:
    """Compute E.3 balance from advice_positions + config + cluster.py; never touches avg_open_price."""
    cfg = _config.effective(conn)
    def f(key: str) -> float:
        return float(cfg[key])
    positions = advice_positions(conn)
    latest = db.fetch_latest_snapshot(conn)
    cash = latest["cash_balance_eur"] if latest else 0.0
    invested = sum(p.mv_eur for p in positions) or 0.0
    total = cash + invested
    cash_pct = 100.0 * cash / total if total else 0.0
    cash_in_band = f("cash_band_low_pct") <= cash_pct <= f("cash_band_high_pct")
    status = {p.symbol: framework_status(conn, p.symbol, as_of=as_of) for p in positions}
    n_framework = sum(1 for s in status.values() if s == "framework")
    n_backfill = sum(1 for s in status.values() if s == "backfill_pending")
    n_outside = sum(1 for s in status.values() if s == "outside_framework")
    count_ok = f("position_count_low") <= n_framework <= f("position_count_high")
    soft = tuple(p.symbol for p in positions if p.weight * 100 > f("max_position_soft_pct"))
    hard = tuple(p.symbol for p in positions if p.weight * 100 > f("max_position_hard_pct"))
    outside_pct = 100.0 * sum(p.weight for p in positions
                              if status[p.symbol] == "outside_framework")
    outside_ok = outside_pct <= f("outside_framework_cap_pct")
    unpriced_of_invested = sum(p.mv_eur for p in positions if p.yf_ticker is None)
    unpriced_pct = 100.0 * unpriced_of_invested / invested if invested else 0.0
    leverage = tuple(p.symbol for p in positions if p.leverage > 1.0)
    n_eff, n_eff_ok, cluster_breaches = None, None, ()
    if returns_local is not None:
        weights = {p.symbol: (p.mv_eur / invested if invested else 0.0)
                   for p in positions if p.yf_ticker is not None}
        cr = _cluster.compute_clusters(returns_local, weights, threshold=f("correlation_threshold"))
        if not cr.stale:
            n_eff = cr.n_eff
            n_eff_ok = n_eff >= f("min_effective_bets")
            cluster_breaches = tuple(str(cid) for cid, w in cr.cluster_weights.items()
                                     if w * 100 > f("max_cluster_weight_pct"))
    return BalanceReport(
        cash_pct=cash_pct, cash_in_band=cash_in_band, n_framework=n_framework,
        n_backfill=n_backfill, n_outside=n_outside, position_count_in_band=count_ok,
        soft_cap_breaches=soft, hard_cap_breaches=hard, cluster_weight_breaches=cluster_breaches,
        n_eff=n_eff, n_eff_ok=n_eff_ok, outside_framework_pct=outside_pct,
        outside_cap_ok=outside_ok, unpriced_weight_pct=unpriced_pct, leverage_violations=leverage)
