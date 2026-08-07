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
        "thesis": {"top": [], "drafts": ["AAA"]},
    }
    monkeypatch.setattr(local_production.webapp, "assemble", lambda **kwargs: refreshed)
    written = []
    monkeypatch.setattr(local_production.webapp, "write_site",
                        lambda model, docs: written.append(model))
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

    assert written[0]["thesis"]["drafts"] == ["AAA"]
    assert result["public_model"]["snapshot_id"] == "snap-1"


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
