"""P6.15: D.4 Modified Dietz per inter-snapshot period, geometrically linked; flows from
external_flow so deposits never masquerade as alpha."""
from datetime import datetime, timezone

from agentcy import db
from agentcy.clock import FixedClock

Q = FixedClock(datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc))


def _two_snaps_one_deposit(conn):
    """t0: MV 10000. A 5000 deposit lands. t1: MV 16000 (=> +1000 real gain on the base+flow)."""
    now = db.to_iso(Q.now())
    s0 = db.append_snapshot(conn, as_of="2026-07-01T20:00:00Z", source="manual_export",
                            cash_balance_eur=0.0, created_at=now)
    db.append_positions(conn, s0, [dict(symbol="MSFT", yf_ticker="MSFT", instrument_type="stock",
        quantity=20.0, avg_open_price=300.0, native_currency="EUR", mv_native=10000.0,
        mv_eur=10000.0, weight=1.0, leverage=1.0)])
    s1 = db.append_snapshot(conn, as_of="2026-09-30T20:00:00Z", source="manual_export",
                            cash_balance_eur=0.0, created_at=now)
    db.append_positions(conn, s1, [dict(symbol="MSFT", yf_ticker="MSFT", instrument_type="stock",
        quantity=32.0, avg_open_price=300.0, native_currency="EUR", mv_native=16000.0,
        mv_eur=16000.0, weight=1.0, leverage=1.0)])
    db.append_external_flow(conn, snapshot_id=s1, date="2026-08-15", amount_eur=5000.0,
                            direction="deposit", ask_ref=None)
    conn.commit()
    return s0, s1


def test_modified_dietz_excludes_deposit_from_return(tmp_db):
    from agentcy.jobs import quarterly
    conn = tmp_db
    _two_snaps_one_deposit(conn)
    r = quarterly.period_return_dietz(conn, start="2026-07-01T20:00:00Z", end="2026-09-30T20:00:00Z")
    # gain = 16000 - 10000 - 5000 = 1000; weighted base ~ 10000 + w*5000; return ~ 1000/12300 ≈ 8.1%
    assert 0.05 < r < 0.11                                   # NOT 60% (would be the flow masquerading)


def test_geometric_link_chains_subperiods():
    from agentcy.jobs import quarterly
    linked = quarterly.geometric_link([0.10, -0.05, 0.02])
    assert abs(linked - ((1.10 * 0.95 * 1.02) - 1)) < 1e-12


def test_large_flow_quarter_flagged_approximate(tmp_db):
    from agentcy.jobs import quarterly
    conn = tmp_db
    _two_snaps_one_deposit(conn)                             # 5000 flow on ~10000 base >> 5%
    caveats = quarterly.flow_caveats(conn, start="2026-07-01T20:00:00Z", end="2026-09-30T20:00:00Z")
    assert any("approximate" in c and "large flows" in c for c in caveats)
