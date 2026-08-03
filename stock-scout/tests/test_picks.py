"""The picks report: the rules that decide what a reader sees, and the promises the page
makes about itself.

These are not "does it render" tests. Every case below is a claim the page makes in its own
prose — that the two judgements are never combined, that the shortlist means what its
heading says, that nothing highly-rated falls quietly out of both tables, that the file
needs nothing from the network — and a test that lets one of those drift is worse than none.
"""
import html
import json
import re

import pytest

import inversion
import picks
import scorecard


# --- Row fixtures --------------------------------------------------------------------------
# The report only ever reads a row's shape, never a Bundle, so the fixtures are rows. That
# keeps these tests about the REPORT and lets the scorecard/inversion suites own their own
# semantics.

def card(pct=80, band="Exceptional", evidence="full", score=None, available_max=100):
    score = pct * available_max / 100.0 if score is None else score
    return {
        "score": score, "available_max": available_max, "pct": pct, "band": band,
        "band_meaning": "…", "evidence": evidence,
        "blocks": {"quality": {"points": 20.0, "max": 24, "metrics": []},
                   "price": {"points": 18.0, "max": 25, "metrics": []},
                   "safety": {"points": 14.0, "max": 15, "metrics": []},
                   "stewardship": {"points": 10.0, "max": 12, "metrics": []}},
        "metrics": {}, "coverage": {"available_max": available_max, "missing": []},
        "why": {"strongest": {"sentence": "carried by owner-FCF yield on EV at 9.1%"},
                "weakest": {"sentence": "held back by accruals at 3% of revenue"}},
        "consensus": {"green": 2, "of": 3, "label": "2 of 3", "lenses": {}, "evidence": {}},
        "veto": None, "notes": [],
    }


def inv(verdict="Robust", severe=0, caution=0, modes=None):
    modes = modes if modes is not None else (
        [f"severe sentence {i}" for i in range(severe)]
        + [f"caution sentence {i}" for i in range(caution)])
    return {
        "verdict": verdict, "verdict_meaning": inversion.VERDICTS[verdict]["meaning"],
        "verdict_rule": inversion.VERDICTS[verdict]["rule"], "counted_verdict": verdict,
        "failure_modes": modes,
        "probes": {pid: {"id": pid, "severity": "none", "measured": True, "value": None,
                         "detail": "…", "evidence": {}} for pid in inversion.PROBES},
        "coverage": {"severe": severe, "caution": caution, "flagged": [],
                     "measured": list(inversion.COUNTING_PROBES),
                     "counting": list(inversion.COUNTING_PROBES),
                     "measured_counting": 6, "counting_total": 6,
                     "unmeasured": [], "required_missing": [], "thin": False},
        "notes": [],
    }


def row(symbol="AAA", name="Alpha Corp.", sector="Information Technology", **kwargs):
    return {"symbol": symbol, "name": name, "sector": sector,
            "card": kwargs.get("card") or card(),
            "inversion": kwargs.get("inversion") or inv()}


# --- Who reaches the shortlist -------------------------------------------------------------

class TestShortlistRule:
    @pytest.mark.parametrize("band,expected", [
        ("Exceptional", True), ("Strong", True),
        ("Mixed", False), ("Weak", False), ("Pass", False),
        (scorecard.VETOED_BAND, False), (scorecard.NO_PRICE_BAND, False),
    ])
    def test_only_the_top_two_bands(self, band, expected):
        rows = [row(card=card(band=band))]
        assert bool(picks.shortlist(rows)) is expected

    def test_one_severe_probe_keeps_a_name_off_it(self):
        """The calibrated ladder puts a single severe finding inside Ordinary, so a rule
        that only read the verdict would let a named way to lose money onto a page headed
        'nothing severe against them'."""
        rows = [row(inversion=inv("Ordinary", severe=1))]
        assert picks.shortlist(rows) == []
        assert [r["symbol"] for r in picks.strong_but_fragile(rows)] == ["AAA"]

    def test_a_fragile_verdict_keeps_a_name_off_it_even_with_no_severe(self):
        """Four cautions and no severe IS Fragile — 'clear ways this breaks you' — so the
        severe count alone is not enough either. Both tests, or the heading lies."""
        rows = [row(inversion=inv("Fragile", severe=0, caution=4))]
        assert picks.shortlist(rows) == []
        assert [r["symbol"] for r in picks.strong_but_fragile(rows)] == ["AAA"]

    def test_cautions_alone_do_not_disqualify(self):
        rows = [row(inversion=inv("Ordinary", severe=0, caution=3))]
        assert [r["symbol"] for r in picks.shortlist(rows)] == ["AAA"]

    def test_unknown_is_shortlisted_and_never_silently_dropped(self):
        """Unknown is a fact about the evidence, not about the business. A research
        shortlist is exactly where 'worth a look, could not be tested' belongs — labelled."""
        rows = [row(inversion=inv("Unknown"))]
        assert [r["symbol"] for r in picks.shortlist(rows)] == ["AAA"]

    def test_the_two_tables_partition_the_top_bands(self):
        """Nothing highly rated may fall out of both — that would be a silent drop, and a
        silent drop is how a screen quietly stops screening."""
        rows = [
            row("AAA", inversion=inv("Robust")),
            row("BBB", inversion=inv("Ordinary", severe=1)),
            row("CCC", inversion=inv("Fragile", caution=4)),
            row("DDD", inversion=inv("Ruinous", severe=3)),
            row("EEE", inversion=inv("Unknown")),
            row("FFF", card=card(band="Weak")),          # not a top band at all
        ]
        top = {r["symbol"] for r in rows if r["card"]["band"] in picks.SHORTLIST_BANDS}
        listed = {r["symbol"] for r in picks.shortlist(rows)}
        paired = {r["symbol"] for r in picks.strong_but_fragile(rows)}
        assert listed | paired == top
        assert listed & paired == set()


class TestOrdering:
    def test_evidence_tier_outranks_the_percentage(self):
        """scorecard §4.2's rule, restated in the report because sorting on the percentage
        alone re-creates the trap the tier exists to close: 97% of 64 measurable points is
        not a better business than 94% of 87."""
        thin = row("KLAC", card=card(pct=97, evidence="partial", score=62.1,
                                     available_max=64))
        full = row("CROX", card=card(pct=94, evidence="full", score=82.0,
                                     available_max=87))
        assert [r["symbol"] for r in picks.shortlist([thin, full])] == ["CROX", "KLAC"]

    def test_the_pairing_leads_with_the_most_broken(self):
        rows = [row("AAA", inversion=inv("Ordinary", severe=1)),
                row("BBB", inversion=inv("Ruinous", severe=3)),
                row("CCC", inversion=inv("Fragile", severe=2))]
        assert [r["symbol"] for r in picks.strong_but_fragile(rows)] == ["BBB", "CCC", "AAA"]


# --- What the page promises about itself -----------------------------------------------------

class TestPageIsSelfContained:
    @pytest.fixture
    def page(self):
        return picks.render([row()], as_of="2026-08-01")

    @pytest.mark.parametrize("needle", ["http://", "https://", "<script", "@import",
                                        " src=", "url("])
    def test_nothing_is_fetched(self, page, needle):
        """A strict content-security policy, a mail attachment and a USB stick are all the
        same test: the file must render with no network and no sibling files."""
        assert needle not in page

    def test_both_themes_are_designed(self, page):
        assert "prefers-color-scheme:dark" in page
        assert '[data-theme="dark"]' in page and '[data-theme="light"]' in page

    def test_wide_content_scrolls_inside_itself(self, page):
        """The body must never scroll sideways; every table carries its own scroll box."""
        assert page.count('<div class="scroll">') == page.count("<table>")
        assert "overflow-x:auto" in page

    @pytest.mark.parametrize("tag", ["html", "head", "body", "table", "thead", "tbody",
                                     "section", "header", "footer", "div", "tr", "td",
                                     "article", "ul", "li", "details"])
    def test_every_element_is_closed(self, page, tag):
        """Matched with a boundary, not a substring: `<header` starts with `<head`, and a
        naive count says the document has an unclosed head."""
        opened = len(re.findall(rf"<{tag}[\s>]", page))
        closed = len(re.findall(rf"</{tag}>", page))
        assert opened == closed, f"{tag}: {opened} open, {closed} closed"

    def test_it_is_one_document(self, page):
        assert page.startswith("<!doctype html>")
        assert page.rstrip().endswith("</html>")


class TestPageTellsTheTruth:
    def test_the_two_judgements_are_never_summed(self):
        """The one structural rule this report exists to honour. A card percentage and a
        severity count are different questions in different units; any arithmetic across
        them is the error SCORECARD-DESIGN §1.6 forbids."""
        source = open(picks.__file__, encoding="utf-8").read()
        body = source.split('CSS = """')[0] + source.split('"""\n\n\ndef _pill')[-1]
        for pattern in (r'\["pct"\]\s*[-+*/]', r'severe"\]\s*[-+*/]\s*\w*\["pct"\]',
                        r'pct.*\+.*severe', r'severe.*\+.*pct'):
            assert not re.search(pattern, body), pattern

    def test_it_says_it_does_not_trade(self):
        page = picks.render([row()], as_of="2026-08-01")
        assert "never executes trades" in page
        assert "not a buy list" in page

    def test_a_clean_name_is_not_reported_as_a_promise(self):
        """'No probe found anything' is a statement about the evidence held. The page has to
        say so, because the alternative is a reader hearing 'safe'."""
        page = picks.render([row(inversion=inv("Robust"))], as_of="2026-08-01")
        assert "not a promise" in page
        assert "cannot see" in page

    def test_every_failure_mode_reaches_the_page_in_its_own_words(self):
        sentence = "The cash engine fell 89% and has not come back"
        page = picks.render(
            [row(inversion=inv("Fragile", severe=2, modes=[sentence, "second finding"]))],
            as_of="2026-08-01")
        assert html.escape(sentence, quote=True) in page

    def test_a_capped_detail_section_says_it_is_capped(self):
        """A truncated list that does not admit it reads as the whole list. No silent caps
        — the same rule the fragility layer's provenance applies one layer up."""
        many = [row(f"S{i:03d}", card=card(pct=90 - i % 40))
                for i in range(picks.DETAIL_CARDS + 9)]
        page = picks.render(many, as_of="2026-08-01")
        assert page.count('<article class="card') == picks.DETAIL_CARDS
        assert f"<b>{picks.DETAIL_CARDS}</b> of <b>{len(many)}</b> picks" in page
        assert "remaining 9" in page

    def test_an_uncapped_detail_section_makes_no_such_claim(self):
        page = picks.render([row()], as_of="2026-08-01")
        assert "capped" not in page
        assert page.count('<article class="card') == 1

    def test_the_counts_in_the_prose_match_the_tables(self):
        rows = [row("AAA", inversion=inv("Robust")),
                row("BBB", inversion=inv("Ruinous", severe=3)),
                row("CCC", card=card(band="Weak"))]
        page = picks.render(rows, as_of="2026-08-01")
        assert f"The shortlist · {len(picks.shortlist(rows))} names" in page
        assert f"The pairing · {len(picks.strong_but_fragile(rows))} names" in page
        assert f"<b>{len(rows)}</b> names screened" in page


class TestEscaping:
    def test_a_hostile_company_name_cannot_inject_markup(self):
        """A universe file is third-party data. The word "onerror" surviving as TEXT is
        fine and expected — what must not survive is a real tag or a real attribute, so the
        assertions are about the delimiters rather than about the vocabulary."""
        nasty = '<img src=x onerror="alert(1)">Ácme & Sons'
        page = picks.render([row(name=nasty)], as_of="2026-08-01")
        assert "<img" not in page
        assert 'onerror="' not in page               # escaped to onerror=&quot;
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in page
        assert "Ácme &amp; Sons" in page

    def test_a_missing_name_or_sector_never_prints_the_word_none(self):
        page = picks.render([row(name=None, sector=None)], as_of="2026-08-01")
        assert ">None<" not in page and "None</" not in page


class TestEmptyAndDegenerate:
    def test_an_empty_universe_still_renders(self):
        page = picks.render([], as_of="2026-08-01")
        assert "<b>0</b> names screened" in page
        assert "<table>" in page              # the legends still stand

    def test_a_vetoed_or_price_less_name_is_never_a_pick(self):
        rows = [row("AAA", card={**card(band=scorecard.NO_PRICE_BAND), "pct": None}),
                row("BBB", card=card(band=scorecard.VETOED_BAND))]
        assert picks.shortlist(rows) == []
        assert picks.render(rows, as_of="2026-08-01")

    def test_probe_values_are_formatted_in_their_own_units(self):
        assert picks._probe_value(
            {"id": "price_drawdown", "measured": True, "value": -0.716}) == "-72%"
        assert picks._probe_value(
            {"id": "financing", "measured": True, "value": 1.25}) == "1.25x"
        assert picks._probe_value(
            {"id": "price_drawdown", "measured": False, "value": None}) == "—"
        assert picks._probe_value(
            {"id": "cash_engine", "measured": True, "value": None}) == "—"


class TestRowAssembly:
    def test_the_scored_row_is_shared_with_both_readers(self, monkeypatch):
        """scoring decides SHARE_CLASS and the vetoes once; the scorecard and the inversion
        layer must both be handed that decision rather than each re-deriving it, or the two
        halves of the page can disagree about one name."""
        seen = {}
        monkeypatch.setattr(picks.scoring, "score_universe",
                            lambda bundles: [{"symbol": "AAA", "flags": [], "grade": "A"}])
        monkeypatch.setattr(picks.scorecard, "scorecard",
                            lambda b, scored_row=None: seen.setdefault("card", scored_row)
                            or card())
        monkeypatch.setattr(picks.inversion, "inversion",
                            lambda b, prices=None, scored_row=None:
                            seen.setdefault("inv", scored_row) or inv())
        picks.build_rows([{"symbol": "AAA"}], prices={}, meta={"AAA": {"name": "Alpha"}})
        assert seen["card"] is seen["inv"]
        assert seen["card"]["symbol"] == "AAA"
