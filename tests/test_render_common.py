from agentcy.render import common as cm


def test_esc_escapes_only_amp_lt_gt():
    assert cm.esc("A & B < C > D") == "A &amp; B &lt; C &gt; D"
    # & must be escaped FIRST so &lt; is not double-escaped
    assert cm.esc("<b>") == "&lt;b&gt;"
    # owner text with ! and € and S&P survives escaping intact except the &
    assert cm.esc("will outgrow the S&P! (€4,200)") == "will outgrow the S&amp;P! (€4,200)"


def test_pre_table_html_is_pre_wrapped_and_escaped():
    out = cm.pre_table([["DDOG", "24x"], ["CRWD", "31x"]], header=["Ticker", "P/FCF"])
    assert out.startswith("<pre>") and out.endswith("</pre>")
    assert "Ticker" in out and "DDOG" in out
    # columns are space-padded to align (monospace)
    lines = out.replace("<pre>", "").replace("</pre>", "").strip("\n").split("\n")
    assert len({len(l) for l in lines}) == 1  # every row same width


def test_pre_table_markdown_is_fenced():
    out = cm.pre_table([["A", "1"]], header=["X", "Y"], skin="md")
    assert out.startswith("```") and out.rstrip().endswith("```")
    assert "<pre>" not in out


def test_verbatim_constants_present_and_immutable_wording():
    assert "not a price alarm" in cm.WHAT_THIS_IS_NOT
    # phrase present modulo the G.3 line wrap (newline falls after "Cost basis is")
    assert "Cost basis is\nnot shown and will not be considered." in cm.WHAT_THIS_IS_NOT
    assert "{pct}" in cm.WHAT_THIS_IS_NOT            # only substitution
    # G.3 verbatim: line wrap is byte-exact per elaboration/telegram-spec — the
    # internal newline falls after "Cost basis is", not after "what follows."
    assert cm.WHAT_THIS_IS_NOT == (
        "WHAT THIS IS NOT: not a price alarm. The stock is {pct} this month; that is not\n"
        "why you are reading this and it plays no part in what follows. Cost basis is\n"
        "not shown and will not be considered."
    )
    assert cm.INVITATION_CLOSER == "this is an invitation, not an instruction."
    assert cm.DEGRADED_LINE == "Nothing is wrong; I just can't see."
    assert "decision by {date}" in cm.DEADLINE_FRAMING and "{n} days" in cm.DEADLINE_FRAMING
    assert "index" in cm.INDEXING_EXIT_CLAUSE.lower()


def test_ams_date_label_uses_europe_amsterdam():
    from datetime import datetime, timezone
    # 2026-07-08 05:00 UTC == 07:00 CEST Wed... verify weekday+tz rendering
    dt = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)
    assert cm.ams_date_label(dt) == "Wed 8 Jul 2026"
    assert cm.ams_datetime_label(dt) == "Wed 8 Jul 2026, 07:00 CET"
