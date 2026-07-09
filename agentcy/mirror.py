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
class SnapshotIn:
    as_of: str
    source: str
    cash_balance_eur: float
    positions: tuple[PositionIn, ...]


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
    db.append_positions(conn, snapshot_id, [{
        "symbol": p.symbol, "yf_ticker": p.yf_ticker, "instrument_type": p.instrument_type,
        "quantity": p.quantity, "avg_open_price": p.avg_open_price,
        "native_currency": p.native_currency, "mv_native": p.mv_native, "mv_eur": p.mv_eur,
        "weight": p.weight, "leverage": p.leverage} for p in snap.positions])
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
