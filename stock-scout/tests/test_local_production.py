import csv

import local_production
from agentcy import db


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
