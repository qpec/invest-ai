import csv
import json
from pathlib import Path

import local_production
from agentcy import db
from agentcy import production as production_state


def test_eligible_universe_excludes_ineligible_and_review_rows(tmp_path):
    conn = db.open_db(tmp_path / "state")
    db.migrate(conn)
    conn.execute(
        "INSERT INTO security_master_run(source_vintage,input_hash,started_at,finished_at,"
        "status,input_rows,eligible_rows,ineligible_rows,review_rows)"
        " VALUES ('test','hash','2026-08-07T00:00:00Z','2026-08-07T00:00:01Z',"
        "'SUCCEEDED',3,1,1,1)"
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for symbol, eligibility in (("AAA", "ELIGIBLE"), ("BBB", "INELIGIBLE"),
                                ("CCC", "REVIEW")):
        conn.execute(
            "INSERT INTO security_observation(run_id,security_key,symbol,name,"
            "country,exchange,instrument_type,eligibility,reason_code,source,source_hash,"
            "observed_at,currency) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, symbol, symbol, symbol, "US", "NASDAQ", "ORDINARY_SHARE",
             eligibility, "PRIMARY_ORDINARY_SHARE" if eligibility == "ELIGIBLE" else
             "FUND" if eligibility == "INELIGIBLE" else "UNKNOWN_INSTRUMENT",
             "test", "hash", "2026-08-07T00:00:00Z", "USD"),
        )
    conn.commit()
    source = tmp_path / "universe.csv"
    source.write_text("symbol,name,exchange\nAAA,A,NASDAQ\nBBB,B,NASDAQ\nCCC,C,NASDAQ\n")
    target = tmp_path / "eligible.csv"

    count = local_production.write_eligible_universe(conn, source, target)

    assert count == 1
    assert list(csv.DictReader(target.open())) == [
        {"symbol": "AAA", "name": "A", "exchange": "NASDAQ"}
    ]


def test_execute_thesis_runner_invokes_isolated_runner_then_records(tmp_path, monkeypatch):
    theses = tmp_path / "theses"
    order = theses / "drafts" / "AAA" / "WORK-ORDER.md"
    order.parent.mkdir(parents=True)
    order.write_text("research AAA", encoding="utf-8")
    runner = tmp_path / "runner.sh"
    runner.write_text("#!/bin/sh\n", encoding="utf-8")
    calls = []
    recorded = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    def fake_record(symbol, *, theses_dir, model):
        recorded.append((symbol, theses_dir, model))
        return {"symbol": symbol, "version": 0}

    monkeypatch.setattr(local_production.thesis, "record", fake_record)
    config = local_production.LocalProductionConfig(
        artifact_root=tmp_path / "artifacts", sec_data=tmp_path / "sec",
        price_grid=tmp_path / "prices", universe=tmp_path / "universe.csv",
        enrich_cache=tmp_path / "cache", theses_dir=theses,
        reports_dir=tmp_path / "reports", as_of="2026-08-07",
        thesis_runner=runner, thesis_model="gpt-5.6-sol",
    )

    doc = local_production.execute_thesis_runner(
        config, "AAA", "run-123", run_command=fake_run)

    assert calls == [([str(runner), "AAA", str(order.resolve()), "run-123"],
                      {"check": True})]
    assert recorded == [("AAA", theses, "gpt-5.6-sol")]
    assert doc["symbol"] == "AAA"


def test_prepare_thesis_orders_batches_only_requested_symbols(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(local_production.thesis, "main", lambda args: calls.append(args) or 0)
    config = local_production.LocalProductionConfig(
        artifact_root=tmp_path / "artifacts", sec_data=tmp_path / "sec",
        price_grid=tmp_path / "prices", universe=tmp_path / "universe.csv",
        enrich_cache=tmp_path / "cache", theses_dir=tmp_path / "theses",
        reports_dir=tmp_path / "reports", as_of="2026-08-07",
        thesis_runner=tmp_path / "runner.sh",
    )
    eligible = tmp_path / "eligible.csv"

    local_production.prepare_thesis_orders(config, eligible, ["BBB", "AAA"])

    assert calls[0][:4] == ["brief", "AAA", "BBB", "--sec-data"]
    assert "--no-filings" in calls[0]
    assert calls[0][calls[0].index("--universe") + 1] == str(eligible)


def test_public_model_is_reassembled_after_new_thesis_artifacts(tmp_path, monkeypatch):
    refreshed = {
        "counts": {"screened": 1}, "rows": [],
        "thesis": {"top": [], "drafts": ["AAA"],
                   "readers": [{"symbol": "AAA"}]},
    }
    monkeypatch.setattr(local_production.webapp, "assemble", lambda **kwargs: refreshed)
    written = []
    logo_calls = []
    monkeypatch.setattr(
        local_production.company_logos, "sync",
        lambda symbols, root: logo_calls.append((symbols, root)) or
        {"AAA": "logos/AAA.png"},
    )
    monkeypatch.setattr(
        local_production.webapp, "write_site",
        lambda model, docs, **kwargs: written.append((model, kwargs)),
    )
    config = local_production.LocalProductionConfig(
        artifact_root=tmp_path / "artifacts", sec_data=tmp_path / "sec",
        price_grid=tmp_path / "prices", universe=tmp_path / "universe.csv",
        enrich_cache=tmp_path / "cache", theses_dir=tmp_path / "theses",
        reports_dir=tmp_path / "reports", as_of="2026-08-07",
    )
    context = type("Context", (), {
        "run_id": "run-1", "snapshot_id": "snap-1", "source_commit": "abc",
        "runtime": {
            "eligible_universe": tmp_path / "eligible.csv",
            "model": {"thesis": {"top": [], "drafts": []}},
        },
    })()
    stages = local_production.make_local_stages(None, config)

    result = stages.build_site(context)

    assert written[0][0]["thesis"]["drafts"] == ["AAA"]
    assert result["public_model"]["snapshot_id"] == "snap-1"
    assert logo_calls[0][0] == ["AAA"]
    assert written[0][1]["logo_assets"] == {"AAA": "logos/AAA.png"}


def test_evaluate_theses_runs_missing_draft_then_reuses_unchanged_acceptance(
        tmp_path, monkeypatch):
    conn = db.open_db(tmp_path / "state")
    db.migrate(conn)
    theses = tmp_path / "theses"
    config = local_production.LocalProductionConfig(
        artifact_root=tmp_path / "artifacts", sec_data=tmp_path / "sec",
        price_grid=tmp_path / "prices", universe=tmp_path / "universe.csv",
        enrich_cache=tmp_path / "cache", theses_dir=theses,
        reports_dir=tmp_path / "reports", as_of="2026-08-07",
        thesis_runner=tmp_path / "runner.sh",
    )
    prepared = []
    executed = []
    monkeypatch.setattr(
        local_production, "prepare_thesis_orders",
        lambda _config, _universe, symbols: prepared.append(symbols),
    )

    def fake_execute(_config, symbol, run_id):
        executed.append((symbol, run_id))
        record = theses / "drafts" / symbol / "record.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({
            "symbol": symbol, "version": 0, "validation_problems": [],
            "agent": {"approved": True},
        }), encoding="utf-8")
        return {"symbol": symbol, "version": 0}

    monkeypatch.setattr(local_production, "execute_thesis_runner", fake_execute)
    context = type("Context", (), {
        "run_id": "run-1", "started_at": "2026-08-07T00:00:00Z", "deep": False,
        "runtime": {
            "eligible_universe": tmp_path / "eligible.csv",
            "model": {"rows": [{
                "s": "AAA", "pct": 91.0, "band": "A", "ev": "strong",
            }]},
        },
        "results": {"select_top": {"members": [{
            "security_key": "AAA", "symbol": "AAA", "rank": 1, "score": 91.0,
        }]}},
    })()
    stage = local_production.make_local_stages(conn, config).evaluate_theses

    first = stage(context)["evaluations"][0]
    assert first["outcome"] == "CREATED"
    assert prepared == [["AAA"]]
    assert executed == [("AAA", "run-1")]

    production_state.start_run(
        conn, run_id="run-old", mode="manual", source_commit="abc",
        started_at="2026-08-07T00:00:00Z",
    )
    db.append_production_thesis_evaluation(conn, {
        "run_id": "run-old", "security_key": "AAA", "symbol": "AAA",
        "input_fingerprint": first["input_fingerprint"], "outcome": "CREATED",
        "evaluated_at": "2026-08-07T00:00:00Z", "reason_code": "NEW_TOP_MEMBER",
        "thesis_version": None,
    })
    conn.commit()
    prepared.clear()
    executed.clear()
    context.run_id = "run-2"

    second = stage(context)["evaluations"][0]
    assert second["outcome"] == "REUSED"
    assert second["reason_code"] == "INPUTS_UNCHANGED"
    assert prepared == []
    assert executed == []


def _promoted_price_run(conn, *, bar_date, close, scheduled_for, split_ratio=None):
    """One promoted price-refresh run carrying a single bar for AAA.

    Deliberately one bar: `market_prices._append_frame` retains only the newest bar of
    the fetched frame plus split events, so this is exactly what production sees.
    """
    run_id = db.append_market_price_run(conn, {
        "scheduled_for": scheduled_for, "attempt": 1,
        "started_at": f"{scheduled_for}T00:00:00Z", "status": "RUNNING",
        "selected_count": 1,
    })
    db.append_market_price_observation(conn, {
        "refresh_run_id": run_id, "security_key": "AAA", "provider": "yahoo",
        "provider_symbol": "AAA", "bar_date": bar_date, "raw_close": close,
        "adjusted_close": close, "dividend": 0.0, "split_ratio": split_ratio,
        "currency": "USD", "fetched_at": f"{scheduled_for}T00:00:01Z",
        "payload_hash": f"hash-{bar_date}",
    })
    db.finish_market_price_run(
        conn, run_id, finished_at=f"{scheduled_for}T00:00:02Z", status="SUCCEEDED",
        ok_count=1, terminal_count=0, failed_count=0, promoted=True)
    conn.commit()
    return run_id


def test_price_grid_export_extends_history_instead_of_replacing_it(tmp_path):
    """2026-08-08 regression. The export used to write the promoted bar over the grid
    file, leaving a ONE-BAR history. inversion.probe_price_drawdown needs 52 weekly bars
    and is a REQUIRED probe, so an unmeasurable one collapses every verdict to Unknown —
    and the grid also looked frozen, because each run replaced it rather than extending
    it. The grid file IS the history; the export appends to it."""
    conn = db.open_db(tmp_path / "state")
    db.migrate(conn)
    grid = tmp_path / "prices"
    grid.mkdir()
    # A seeded history, as prices.py refresh would leave it.
    (grid / "AAA.json").write_text(json.dumps({
        "symbol": "AAA",
        "bars": {"2026-07-27": {"close": 90.0, "adj_close": 90.0},
                 "2026-08-03": {"close": 95.0, "adj_close": 95.0}},
        "splits": {"2026-07-27": 2.0},
        "source": "yahoo", "price_basis": "raw",
    }), encoding="utf-8")

    _promoted_price_run(conn, bar_date="2026-08-10", close=100.0,
                        scheduled_for="2026-08-10")
    assert local_production.export_price_grid(conn, grid) == 1

    payload = json.loads((grid / "AAA.json").read_text(encoding="utf-8"))
    assert sorted(payload["bars"]) == ["2026-07-27", "2026-08-03", "2026-08-10"]
    assert payload["bars"]["2026-08-10"]["adj_close"] == 100.0
    assert payload["bars"]["2026-07-27"]["adj_close"] == 90.0   # history survives
    assert payload["splits"] == {"2026-07-27": 2.0}             # and so do splits


def test_price_grid_export_is_idempotent_and_accumulates_across_runs(tmp_path):
    conn = db.open_db(tmp_path / "state")
    db.migrate(conn)
    grid = tmp_path / "prices"

    _promoted_price_run(conn, bar_date="2026-08-10", close=100.0,
                        scheduled_for="2026-08-10")
    local_production.export_price_grid(conn, grid)
    local_production.export_price_grid(conn, grid)          # same run twice
    payload = json.loads((grid / "AAA.json").read_text(encoding="utf-8"))
    assert sorted(payload["bars"]) == ["2026-08-10"]

    # A later promoted run adds its bar rather than replacing the previous one.
    _promoted_price_run(conn, bar_date="2026-08-17", close=110.0,
                        scheduled_for="2026-08-17", split_ratio=3.0)
    local_production.export_price_grid(conn, grid)
    payload = json.loads((grid / "AAA.json").read_text(encoding="utf-8"))
    assert sorted(payload["bars"]) == ["2026-08-10", "2026-08-17"]
    assert payload["splits"] == {"2026-08-17": 3.0}


def test_price_grid_export_survives_a_corrupt_grid_file(tmp_path):
    """A half-written grid file must not abort the run: the export rebuilds from the
    promoted bar rather than raising."""
    conn = db.open_db(tmp_path / "state")
    db.migrate(conn)
    grid = tmp_path / "prices"
    grid.mkdir()
    (grid / "AAA.json").write_text("{not json", encoding="utf-8")
    _promoted_price_run(conn, bar_date="2026-08-10", close=100.0,
                        scheduled_for="2026-08-10")
    assert local_production.export_price_grid(conn, grid) == 1
    payload = json.loads((grid / "AAA.json").read_text(encoding="utf-8"))
    assert sorted(payload["bars"]) == ["2026-08-10"]
