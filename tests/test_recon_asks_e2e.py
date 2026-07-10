"""FIX.2 end-to-end: ingesting a snapshot through the production entry points mints
reconciliation R-asks (E.1/§3.4), and answering one routes through FIX.1's dispatcher
to a JournalEntry (global invariant 2 / MA-12).

These tests drive the REAL mirror + asks (only the DB/clock seams are wired to the
fixtures) — no hand-stitched delta minting."""
from __future__ import annotations

from agentcy import asks, db, mirror


def _seed_prior_snapshot(conn, clock):
    """One prior snapshot: MSFT held, cash 8000 EUR — the reconciliation baseline."""
    now = db.to_iso(clock.now())
    sid = db.append_snapshot(conn, as_of="2026-07-01T20:00:00Z", source="manual_export",
                             cash_balance_eur=8000.0, created_at=now)
    db.append_positions(conn, sid, [dict(
        symbol="MSFT", yf_ticker="MSFT", instrument_type="stock", quantity=40.0,
        avg_open_price=300.0, native_currency="USD", mv_native=10000.0, mv_eur=8500.0,
        weight=1.0, leverage=1.0)])
    conn.commit()
    return sid


# A new snapshot: MSFT unchanged (40 shares) + a NEW ticker ASML (appeared) and cash that
# moved by +1200 EUR with no matching position move (unexplained_cash).
_ETORO_CSV = (
    "symbol,instrument_type,quantity,avg_open_price,native_currency,"
    "market_value_native,market_value_eur,leverage\n"
    "MSFT,stock,40,300,USD,10000,8500,1\n"
    "ASML,stock,12,600,EUR,7200,7200,1\n"
    "CASH,cash,0,,EUR,9200,9200,1\n"
)


def _cli(monkeypatch, conn, clock):
    from agentcy import cli
    monkeypatch.setattr(cli, "_open", lambda: conn)
    monkeypatch.setattr(cli, "_clock", lambda: clock)
    return cli


def test_cli_snapshot_mints_recon_asks_and_answer_journals(tmp_path, tmp_db, fixed_clock,
                                                           monkeypatch, capsys):
    conn, clock = tmp_db, fixed_clock
    _seed_prior_snapshot(conn, clock)
    csv = tmp_path / "export.csv"
    csv.write_text(_ETORO_CSV, encoding="utf-8")

    cli = _cli(monkeypatch, conn, clock)
    assert cli.main(["snapshot", "import", str(csv)]) == 0

    # The snapshot is accepted append-only regardless (deltas are open loops).
    assert db.fetch_latest_snapshot(conn)["cash_balance_eur"] == 9200.0

    # Reconciliation R-asks now exist as OPEN loops with the §3.4 option sets.
    open_r = {a.ask_id: a for a in asks.open_asks(conn, kind="R")}
    assert open_r, "ingest must mint reconciliation R-asks (E.1/D.5)"
    by_choices = {tuple(a.options) for a in open_r.values()}
    assert ("backfill", "outside", "ignore") in by_choices          # appeared (ASML)
    assert any(set(o) == {"deposit", "withdrawal", "dividend", "other"}
               for o in by_choices)                                  # unexplained_cash (MA-12)

    # Answer the unexplained-cash R-ask -> FIX.1 dispatcher -> JournalEntry + external_flow.
    cash_ask = next(a for a in open_r.values()
                    if set(a.options) == {"deposit", "withdrawal", "dividend", "other"})
    je_before = len(db.fetch_journal_entries(conn))
    outcome = asks.answer(conn, cash_ask.ask_id, choice="deposit", clock=clock)
    assert outcome.accepted and outcome.consequence == "recon.deposit"
    asks.apply_consequence(conn, outcome, clock=clock)

    entries = db.fetch_journal_entries(conn)
    assert len(entries) == je_before + 1, "every owner decision produces a JournalEntry (inv 2)"
    mine = [e for e in entries if e["ask_ref"] == cash_ask.ask_id]
    assert len(mine) == 1 and mine[0]["decision_subtype"] == "external_flow"
    flows = db.fetch_external_flows_for_snapshot(conn, db.fetch_latest_snapshot(conn)["snapshot_id"])
    assert [f["direction"] for f in flows] == ["deposit"]            # MA-12 flow recorded
    assert flows[0]["ask_ref"] == cash_ask.ask_id


_LEVERAGED_CSV = (
    "symbol,instrument_type,quantity,avg_open_price,native_currency,"
    "market_value_native,market_value_eur,leverage\n"
    "MSFT,stock,40,300,USD,10000,8500,1\n"
    "OILX,stock,5,100,EUR,500,500,3\n"
    "CASH,cash,0,,EUR,8000,8000,1\n"
)


def test_leverage_violation_is_a_tripwire_notice_not_an_r_ask(tmp_path, tmp_db, fixed_clock,
                                                             monkeypatch):
    """A leveraged position fires the immediate Hell-No leverage tripwire (an outbox notice),
    NOT a reconciliation R-ask (E.1)."""
    conn, clock = tmp_db, fixed_clock
    _seed_prior_snapshot(conn, clock)
    csv = tmp_path / "lev.csv"
    csv.write_text(_LEVERAGED_CSV, encoding="utf-8")

    cli = _cli(monkeypatch, conn, clock)
    assert cli.main(["snapshot", "import", str(csv)]) == 0

    notices = [r for r in db.fetch_outbox_queued(conn) if r["kind"] == "notice"
               and "leverage tripwire" in r["payload_html"]]
    assert notices and "OILX" in notices[0]["payload_html"]
    # the leverage violation is NOT one of the R-asks
    r_prompts = " ".join(a.prompt for a in asks.open_asks(conn, kind="R"))
    assert "leverage" not in r_prompts.lower()


def test_daemon_document_ingest_mints_recon_asks(tmp_db, fixed_clock, monkeypatch):
    """The bot's document path mints the SAME reconciliation R-asks (shared producer)."""
    from agentcy.tg import daemon
    conn, clock = tmp_db, fixed_clock
    _seed_prior_snapshot(conn, clock)

    class _Client:
        def __init__(self):
            self.sent = []
        def send_message(self, chat_id, html, *, reply_markup=None):
            self.sent.append((html, reply_markup)); return {"message_id": 1}
        def send_chat_action(self, chat_id, action="typing"): pass
        def get_file(self, file_id): return {"file_path": "documents/export.csv"}
        def download_file(self, file_path): return _ETORO_CSV.encode("utf-8")
        def answer_callback_query(self, *a, **k): pass
        def edit_message_text(self, *a, **k): return {"message_id": 1}

    c = _Client()
    # 1) owner taps "Upload export file" -> pending snap:file N-ask
    daemon.handle(conn, {"update_id": 1, "callback_query": {
        "id": "CB", "from": {"id": 555}, "message": {"chat": {"id": 555}, "message_id": 5},
        "data": "snap:mode:file"}}, client=c, clock=clock, owner_chat_id=555)
    # 2) owner sends the CSV document -> ingest + mint
    daemon.handle(conn, {"update_id": 2, "message": {"chat": {"id": 555},
        "document": {"file_id": "FID1", "file_name": "export.csv"}}},
        client=c, clock=clock, owner_chat_id=555)

    open_r = [a for a in asks.open_asks(conn, kind="R")]
    assert open_r, "the document ingest path must mint reconciliation R-asks too"
    choicesets = {tuple(a.options) for a in open_r}
    assert ("backfill", "outside", "ignore") in choicesets
    assert any(set(o) == {"deposit", "withdrawal", "dividend", "other"} for o in choicesets)
