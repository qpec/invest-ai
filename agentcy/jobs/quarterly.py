"""Quarterly honesty check (D.4, FR13). Fired *-01,04,07,10-01 08:30 Europe/Amsterdam.

THE ONLY job that reads the benchmark database (via benchmark.py) and THE ONLY importer
of quantstats -- both quarantined here (invariant 7 / §4.6). This module lands the D.4
return-series reconstruction: a portfolio EUR value at each snapshot from the advice
view (never avg_open_price -- invariant 4), with external flows attributed per
inter-snapshot period so deposits enter the base, never the return. Benchmark read +
quantstats degradation land in P6.16; the G.4 letter build in P6.17.
"""
from __future__ import annotations

from agentcy import db, mirror

RUN_TYPE = "quarterly"
LARGE_FLOW_PCT = 5.0    # D.4: net flows > ~5% of value => 'approximate — large flows'


def geometric_link(subperiod_returns) -> float:
    """Chain inter-snapshot Modified-Dietz returns: Π(1+r) − 1 (D.4)."""
    acc = 1.0
    for r in subperiod_returns:
        acc *= (1.0 + r)
    return acc - 1.0


def _mv_eur_at(conn, snapshot_id: int) -> float:
    """Portfolio EUR value = Σ position mv_eur + snapshot cash (advice view only, invariant 4)."""
    snap = db.fetch_snapshot(conn, snapshot_id)
    cash = snap["cash_balance_eur"] if snap else 0.0
    positions = mirror.advice_positions(conn, snapshot_id)
    return sum(p.mv_eur for p in positions) + cash


def _net_flow_eur(conn, snapshot_id: int) -> float:
    """Signed external flows attributed to the period ending at this snapshot (external_flow).
    Withdrawals leave the account (negative); deposits/dividends/other enter it (positive)."""
    total = 0.0
    for f in db.fetch_external_flows_for_snapshot(conn, snapshot_id):
        sign = -1.0 if f["direction"] == "withdrawal" else 1.0
        total += sign * f["amount_eur"]
    return total


def period_return_dietz(conn, *, start: str, end: str) -> float:
    """Modified Dietz over each inter-snapshot period, geometrically linked (D.4).
    Per period: r = (V_end − V_begin − F) / (V_begin + Σ w_i F_i), F weighted by time-in-period.
    Deposits therefore enter the denominator (base), never the numerator (gain)."""
    snaps = db.fetch_snapshots_between(conn, start, end)
    if len(snaps) < 2:
        return 0.0
    subs = []
    for a, b in zip(snaps, snaps[1:]):
        v0 = _mv_eur_at(conn, a["snapshot_id"])
        v1 = _mv_eur_at(conn, b["snapshot_id"])
        flow = _net_flow_eur(conn, b["snapshot_id"])
        # single mid-period flow approximation (w = 0.5) — exact day-weighting is
        # documented-out YAGNI given the reconciliation-driven flow cadence (D.4).
        base = v0 + 0.5 * flow
        subs.append(((v1 - v0 - flow) / base) if base else 0.0)
    return geometric_link(subs)


def flow_caveats(conn, *, start: str, end: str) -> list[str]:
    """D.4: quarters whose net flows exceed ~5% of value are labeled 'approximate'."""
    snaps = db.fetch_snapshots_between(conn, start, end)
    if len(snaps) < 2:
        return []
    v0 = _mv_eur_at(conn, snaps[0]["snapshot_id"]) or 1.0
    net = sum(_net_flow_eur(conn, s["snapshot_id"]) for s in snaps[1:])
    if abs(net) / v0 * 100.0 > LARGE_FLOW_PCT:
        return [f"approximate — large flows this period (net {net:+.0f} EUR on {v0:.0f} base)"]
    return []
