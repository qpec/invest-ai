"""Stage-2 badges: the four axes -> ASCII display glyphs (design Part A). ASCII-only, so a
badge can never trip the render lint's red-glyph ban."""
from agentcy import scout_review as sr


def test_badges_map_present_axes():
    v = sr.Verdict(moat="confirmed", mgmt="red-flag", fad="clear", tier="correction:Adjacent")
    b = sr.badges(v)
    assert b["moat"] == "[+]"
    assert b["mgmt"] == "[x]"
    assert b["fad"] == "[+]"
    assert b["tier"] == "[t]"


def test_pending_axes_have_no_badge():
    b = sr.badges(sr.Verdict(moat="confirmed"))
    assert set(b) == {"moat"}                       # the other three are pending -> no badge


def test_badges_are_ascii_only():
    b = sr.badges(sr.Verdict(moat="not-evident", mgmt="neutral", fad="flag", tier="ok"))
    for glyph in b.values():
        assert glyph.isascii()
