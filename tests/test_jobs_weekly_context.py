"""P6.11: D.2 checks 3-8 — dividends-received from price_cache dividend column (BUF-2),
re-affirmation F asks, backfill line, UNVERIFIABLE headline, study block."""
from datetime import datetime, timezone

from agentcy import db, runlog
from agentcy.clock import FixedClock

SAT = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc))


def test_dividend_lines_from_price_cache_dividend_column(seeded_portfolio):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    db.append_price_rows(conn, [dict(yf_ticker="MSFT", bar_date="2026-07-09", close=500.0,
                                     adj_close=500.0, dividend=0.75, currency="USD",
                                     fetched_at="2026-07-11T06:00:00Z", run_id=None)])
    lines, reinvest = weekly.dividend_lines(conn, as_of=SAT.now())
    assert len(lines) == 1
    # 20 shares x 0.75 USD x 0.85 EUR/USD = 12.75 EUR
    assert "MSFT" in lines[0] and "12.75" in lines[0]
    assert reinvest is True     # cash 8000/16500 = 48% > band floor 5% -> reminder (BUF-2)


def test_no_dividends_no_lines(seeded_portfolio):
    from agentcy.jobs import weekly
    lines, reinvest = weekly.dividend_lines(seeded_portfolio["conn"], as_of=SAT.now())
    assert lines == () and reinvest is False


def test_reaffirmation_f_ask_minted_once_for_anniversary(seeded_portfolio, monkeypatch):
    from agentcy import register
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    tid = seeded_portfolio["thesis_id"]
    monkeypatch.setattr(register, "anniversaries_due", lambda c, *, as_of: [tid])
    rh = runlog.start(conn, "weekly", "2026-07-11f", clock=SAT)
    minted = weekly.reaffirmation_asks(conn, run_id=rh.run_id, clock=SAT)
    assert len(minted) == 1
    ask = db.fetch_ask(conn, minted[0])
    assert ask["kind"] == "F" and ask["thesis_ref"] == tid
    assert weekly.reaffirmation_asks(conn, run_id=rh.run_id, clock=SAT) == []   # no duplicate


def test_unverifiable_headline_escalation_at_three_weeks(seeded_portfolio, monkeypatch):
    from agentcy import triggers
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    monkeypatch.setattr(triggers, "unverifiable_weeks", lambda c, trig_id, *, as_of: 3)
    lines = weekly.unverifiable_headlines(conn, as_of=SAT.now())
    assert lines and "3 weeks" in lines[0] and "UNVERIFIABLE" in lines[0]  # B.3.4: never green


def test_study_block_mints_circle_note_ask_and_advances_rotation(seeded_portfolio, monkeypatch):
    from agentcy import study
    from agentcy.jobs import weekly
    from agentcy.render.contexts import StudyContext
    conn = seeded_portfolio["conn"]
    base = StudyContext(restudy_ticker="MSFT", restudy_excerpt="…", restudy_question="q?",
                        mental_model_prompt="Invert.", journal_previews=(), reading_line="10-K §1A",
                        circle_note_ask_id=None)
    monkeypatch.setattr(study, "build_digest", lambda c, *, as_of: base)
    advanced = []
    monkeypatch.setattr(study, "advance_rotation",
                        lambda c, *, thesis_id, model_index, clock: advanced.append(thesis_id))
    rh = runlog.start(conn, "weekly", "2026-07-11s", clock=SAT)
    ctx = weekly.study_block(conn, run_id=rh.run_id, clock=SAT)
    assert ctx.circle_note_ask_id is not None
    assert db.fetch_ask(conn, ctx.circle_note_ask_id)["kind"] == "N"       # §3.9 zero-consequence
    assert advanced                                                        # rotation moved
