from agentcy import db

import coverage
import thesis


def _conn(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    return conn


def _bundle():
    balance = {
        "Total Debt": 100e6, "Cash And Cash Equivalents": 300e6,
        "Stockholders Equity": 1e9, "Total Assets": 2e9,
    }
    income = {
        "Total Revenue": 320e6, "EBIT": 65e6, "EBITDA": 80e6,
        "Gross Profit": 192e6, "Operating Income": 65e6,
        "Net Income": 55e6,
        "Net Income Including Noncontrolling Interests": 55e6,
    }
    cashflow = {
        "Operating Cash Flow": 70e6, "Capital Expenditure": -12e6,
        "Stock Based Compensation": 5e6, "Depreciation And Amortization": 15e6,
    }
    periods = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
    return {
        "symbol": "ACME", "market_cap": 10e9, "price": 100.0,
        "price_as_of": "2026-08-06", "shares_as_of": "2025-12-15",
        "shares_basis": "series", "market_cap_split_unadjusted": False,
        "shares_series": [["2025-12-15", 100e6]],
        "annual": {"income": {}, "balance": {}, "cashflow": {}},
        "quarterly": {
            "income": {period: dict(income) for period in periods},
            "balance": {"2025-12-31": balance},
            "cashflow": {period: dict(cashflow) for period in periods},
        },
    }


def _price(conn):
    conn.execute(
        "INSERT INTO market_price_refresh_run"
        " (scheduled_for, attempt, started_at, finished_at, status, selected_count,"
        " ok_count, terminal_count, failed_count, promoted) VALUES"
        " ('2026-08-07', 1, '2026-08-07T10:00:00Z', '2026-08-07T10:01:00Z',"
        " 'SUCCEEDED', 1, 1, 0, 0, 1)"
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO market_price_observation"
        " (refresh_run_id, security_key, provider, provider_symbol, bar_date, raw_close,"
        " adjusted_close, dividend, currency, fetched_at, payload_hash) VALUES"
        " (?, 'cik:0000000001', 'yahoo', 'ACME', '2026-08-06', 100, 99, 0, 'USD',"
        " '2026-08-07T10:01:00Z', 'price-hash')",
        (run_id,),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_owner_yield_reuses_registry_formula_and_links_all_inputs(tmp_path):
    conn = _conn(tmp_path)
    price_id = _price(conn)
    bundle = _bundle()

    metric_id = coverage.store_owner_fcf_yield(
        conn, bundle=bundle, companyfacts_hash="facts-hash",
        price_observation_id=price_id, as_of="2026-08-07",
        calculated_at="2026-08-07T12:00:00Z",
    )

    row = conn.execute(
        "SELECT * FROM metric_observation WHERE metric_observation_id=?", (metric_id,)
    ).fetchone()
    assert row["value"] == thesis.metric_value("owner_fcf_yield_pct", bundle)
    assert row["reason_code"] == "VALUE_AVAILABLE"
    assert len(conn.execute(
        "SELECT * FROM metric_input WHERE metric_observation_id=?", (metric_id,)
    ).fetchall()) == 5


def test_missing_price_writes_reason_without_value(tmp_path):
    conn = _conn(tmp_path)
    bundle = _bundle()
    bundle["price"] = None
    bundle["market_cap"] = None

    metric_id = coverage.store_owner_fcf_yield(
        conn, bundle=bundle, companyfacts_hash="facts-hash",
        price_observation_id=None, as_of="2026-08-07",
        calculated_at="2026-08-07T12:00:00Z",
    )
    row = conn.execute(
        "SELECT * FROM metric_observation WHERE metric_observation_id=?", (metric_id,)
    ).fetchone()
    assert row["value"] is None
    assert row["status"] == "MISSING"
    assert row["reason_code"] == "MISSING_PRICE"


def test_price_grid_exports_raw_basis_and_splits(tmp_path):
    conn = _conn(tmp_path)
    _price(conn)
    prices, splits, basis, observation_ids = coverage.price_grid(conn)
    assert prices["ACME"]["2026-08-06"]["close"] == 100.0
    assert splits["ACME"] == {}
    assert basis["ACME"] == "raw"
    assert observation_ids["ACME"] > 0


def test_compare_coverage_reports_metric_and_total_gains():
    baseline = {
        "eligible_bundles": 2,
        "metric_count": 2,
        "measured": 2,
        "possible": 4,
        "per_metric": {"alpha": 2, "beta": 0},
        "symbols_by_metric": {"alpha": ["A", "B"], "beta": []},
    }
    candidate = {
        "eligible_bundles": 2,
        "metric_count": 2,
        "measured": 3,
        "possible": 4,
        "per_metric": {"alpha": 2, "beta": 1},
        "symbols_by_metric": {"alpha": ["A", "B"], "beta": ["B"]},
    }

    result = coverage.compare_coverage(baseline, candidate)

    assert result["coverage_delta_percentage_points"] == 25.0
    assert result["per_metric"]["beta"] == {
        "old": 0, "new": 1, "delta": 1, "gained": ["B"], "lost": []
    }


def test_release_gates_require_prices_yields_and_total_gain():
    passing = coverage.release_gates(
        eligible=100, fresh_prices=96, terminal_prices=4,
        fresh_owner_fcf_yields=55, minimum_yields=50,
        coverage_delta_percentage_points=2.0,
        lineage_complete=True, parity_mismatches=0,
    )
    failing = coverage.release_gates(
        eligible=100, fresh_prices=94, terminal_prices=6,
        fresh_owner_fcf_yields=49, minimum_yields=50,
        coverage_delta_percentage_points=1.4,
        lineage_complete=False, parity_mismatches=1,
    )

    assert passing["passed"] is True
    assert all(passing["checks"].values())
    assert failing["passed"] is False
    assert failing["checks"] == {
        "fresh_price_coverage_at_least_95pct": False,
        "terminal_outcomes_explicit": True,
        "owner_fcf_yields_at_least_minimum": False,
        "coverage_gain_at_least_1_5pp": False,
        "lineage_complete": False,
        "zero_parity_mismatches": False,
    }
