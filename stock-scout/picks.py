"""The picks report — the shortlist, with fragility standing beside every score.

`datasheet.py` is the audit sheet: one name, every number, recomputed. This is the other
half — the whole universe reduced to what is worth a Gate session, in a page a newcomer can
read without knowing the codebase.

The one structural rule it exists to honour is SCORECARD-DESIGN §1.6 / INVERSION-DESIGN §2:
**the two judgements stay in separate columns.** The card says how good the business is; the
inversion layer says how it breaks. They are never added, averaged, or reconciled — a name
can be Exceptional and Fragile at once, and that pairing gets its own section rather than
being resolved into a single comforting number.

Self-contained by construction: no external CSS, fonts, scripts or images, so the file works
from a mail attachment, a USB stick, or a strict content-security policy.

    python picks.py                                     # from the yfinance cache
    python picks.py --sec-data <dir> --prices <dir>     # from a bulk SEC CSV export
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import sys
from pathlib import Path

import inversion
import scorecard
import scoring

# --- What reaches the shortlist ----------------------------------------------------------
# Declared here rather than buried in the renderer, because these two lines ARE the report's
# editorial position and a reader is entitled to see them stated.
#
# `SHORTLIST_BANDS` is the card's own top two bands (§5 of the scorecard design).
#
# The fragility rule is TWO tests, and it is two on purpose. Asking only "is the verdict
# good?" lets a name through with one severe probe, because the calibrated ladder puts a
# single severe finding inside Ordinary — and a named way to lose money is exactly what a
# shortlist must not carry silently. Asking only "no severe probe?" lets through a name
# carrying four separate cautions, which the ladder calls Fragile precisely because that is
# clear ways this breaks you. Either test alone contradicts the heading above the table, so
# a pick has to pass both.
#
# `Unknown` is deliberately NOT excluded. It means the layer could not certify, which is a
# fact about the evidence rather than about the business, and a research shortlist is the
# right place for "worth a look, and we could not test it" — labelled, never quietly.
SHORTLIST_BANDS = ("Exceptional", "Strong")
SHORTLIST_MAX_SEVERE = 0
SHORTLIST_EXCLUDE_VERDICTS = ("Fragile", "Ruinous")

# How many picks get a detail card. A cap, and therefore something the page must SAY — see
# _detail_note. Everything above the cap is still in the shortlist table with its score and
# its findings; only the block breakdown is omitted.
DETAIL_CARDS = 24

BAND_ORDER = ("Exceptional", "Strong", "Mixed", "Weak", "Pass",
              scorecard.VETOED_BAND, scorecard.NO_PRICE_BAND)
VERDICT_ORDER = ("Robust", "Ordinary", "Fragile", "Ruinous", "Unknown")

# Semantic tone per verdict, kept separate from the page accent (they mean different things).
VERDICT_TONE = {"Robust": "clear", "Ordinary": "quiet", "Fragile": "caution",
                "Ruinous": "severe", "Unknown": "unknown"}
SEVERITY_TONE = {"none": "clear", "caution": "caution", "severe": "severe"}
EVIDENCE_NOTE = {
    "full": "most of the 100 points could be measured",
    "partial": "a meaningful part of the card could not be measured",
    "thin": "only a small part of the card could be measured — read the percentage with care",
}


# --- Assembling the rows ------------------------------------------------------------------

def build_rows(bundles: list[dict], *, prices=None, meta: dict | None = None) -> list[dict]:
    """Bundles -> the report's row shape, running the three readings once each.

    `scored_row` is threaded from scoring into BOTH consumers on purpose: the scorecard's
    vetoes and the inversion layer's SHARE_CLASS suppression must agree with the grader
    rather than each re-deciding, which is how two layers start disagreeing about one name.
    """
    meta = meta or {}
    scored = {row["symbol"]: row for row in scoring.score_universe(bundles)}
    rows = []
    for bundle in bundles:
        symbol = bundle.get("symbol")
        row = scored.get(symbol)
        info = meta.get(symbol) or {}
        rows.append({
            "symbol": symbol,
            "name": info.get("name") or bundle.get("name"),
            "sector": info.get("sector") or bundle.get("sector"),
            "card": scorecard.scorecard(bundle, scored_row=row),
            "inversion": inversion.inversion(bundle, prices=prices, scored_row=row),
        })
    return rows


def shortlist(rows: list[dict]) -> list[dict]:
    """The picks: a top-two band on the card, no probe naming a failure mode, and a verdict
    that is not itself a warning. See SHORTLIST_* above for why it takes both tests."""
    out = [r for r in rows
           if r["card"].get("pct") is not None
           and r["card"]["band"] in SHORTLIST_BANDS
           and r["inversion"]["coverage"]["severe"] <= SHORTLIST_MAX_SEVERE
           and r["inversion"]["verdict"] not in SHORTLIST_EXCLUDE_VERDICTS]
    return sorted(out, key=_rank_key)


def strong_but_fragile(rows: list[dict]) -> list[dict]:
    """The pairing INVERSION-DESIGN §5 calls the most useful thing the layer produces: a
    business the card rates highly and the probes have something specific to say about.

    Exactly the top-band names the shortlist turned away, so the two sections partition the
    top bands between them and no highly-rated name can quietly fall out of both."""
    out = [r for r in rows
           if r["card"].get("pct") is not None
           and r["card"]["band"] in SHORTLIST_BANDS
           and (r["inversion"]["coverage"]["severe"] > SHORTLIST_MAX_SEVERE
                or r["inversion"]["verdict"] in SHORTLIST_EXCLUDE_VERDICTS)]
    return sorted(out, key=lambda r: (-r["inversion"]["coverage"]["severe"], _rank_key(r)))


def _rank_key(row: dict):
    """Evidence tier first, then percentage — scorecard §4.2's rule, restated here because a
    report that sorts on the percentage alone re-creates the very trap the tier exists to
    close: 97% of 64 measurable points is not a better business than 94% of 87."""
    return scorecard.rank_key(row["card"])


def tally(rows: list[dict], key) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[key(row)] = counts.get(key(row), 0) + 1
    return [(k, counts[k]) for k in counts]


# --- Small formatting helpers -------------------------------------------------------------

def e(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _pct(value, digits: int = 1) -> str:
    return "—" if value is None else f"{100.0 * value:.{digits}f}%"


def _points(card: dict) -> str:
    return f"{card['score']:.1f} / {card['available_max']}"


def _probe_value(probe: dict) -> str:
    """A probe's headline number in the units its own section reads, or an em dash. Kept
    tiny and total: an unmeasured probe has no number and must not be given one."""
    if not probe.get("measured") or probe.get("value") is None:
        return "—"
    pid, value = probe["id"], probe["value"]
    if pid in ("price_drawdown", "cash_engine", "stress"):
        return _pct(value, 0)
    if pid == "predictability":
        return f"{100.0 * value:.0f} pts"
    if pid == "financing":
        return f"{value:.2f}x" if abs(value) < 1e6 else "no cover"
    if pid == "concentration":
        return f"{value:.0f}%"
    return f"{value:.2f}"


# --- The page -----------------------------------------------------------------------------

CSS = """
:root{
  --paper:#FBFAF7; --surface:#FFFFFF; --sunken:#F4F2EC;
  --ink:#1A1D1B; --ink-soft:#585E59; --ink-faint:#8A908A;
  --rule:#E3E0D8; --rule-strong:#CFCBBF;
  --accent:#0F5C56; --accent-soft:#E4EFED;
  --severe:#8F2C2C; --severe-soft:#F6E7E5;
  --caution:#8C6D1F; --caution-soft:#F6EFDD;
  --clear:#3F6B4A; --clear-soft:#E6EFE7;
  --unknown:#6C6A78; --unknown-soft:#EDECEF;
  --measure:64ch;
}
@media (prefers-color-scheme:dark){
  :root{
    --paper:#141614; --surface:#1C201D; --sunken:#22271F;
    --ink:#E9E7DF; --ink-soft:#A8AEA6; --ink-faint:#767C76;
    --rule:#2E332E; --rule-strong:#3E453D;
    --accent:#57B8AB; --accent-soft:#16302D;
    --severe:#E0857D; --severe-soft:#32201F;
    --caution:#D6B45F; --caution-soft:#2C2718;
    --clear:#88BE93; --clear-soft:#1B2A1D;
    --unknown:#A6A3B4; --unknown-soft:#24232A;
  }
}
:root[data-theme="dark"]{
  --paper:#141614; --surface:#1C201D; --sunken:#22271F;
  --ink:#E9E7DF; --ink-soft:#A8AEA6; --ink-faint:#767C76;
  --rule:#2E332E; --rule-strong:#3E453D;
  --accent:#57B8AB; --accent-soft:#16302D;
  --severe:#E0857D; --severe-soft:#32201F;
  --caution:#D6B45F; --caution-soft:#2C2718;
  --clear:#88BE93; --clear-soft:#1B2A1D;
  --unknown:#A6A3B4; --unknown-soft:#24232A;
}
:root[data-theme="light"]{
  --paper:#FBFAF7; --surface:#FFFFFF; --sunken:#F4F2EC;
  --ink:#1A1D1B; --ink-soft:#585E59; --ink-faint:#8A908A;
  --rule:#E3E0D8; --rule-strong:#CFCBBF;
  --accent:#0F5C56; --accent-soft:#E4EFED;
  --severe:#8F2C2C; --severe-soft:#F6E7E5;
  --caution:#8C6D1F; --caution-soft:#F6EFDD;
  --clear:#3F6B4A; --clear-soft:#E6EFE7;
  --unknown:#6C6A78; --unknown-soft:#EDECEF;
}

body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
  font-size:15px; line-height:1.55; -webkit-text-size-adjust:100%;
}
.wrap{max-width:1120px; margin:0 auto; padding:2.5rem 1.25rem 5rem; display:flex;
      flex-direction:column; gap:3rem;}
/* A flex item defaults to min-width:auto, so a wide TABLE inside a column flex container
   pushes the container past the viewport and the page scrolls sideways as a whole — which
   then clips the prose rather than scrolling the table. Zeroing the floor is what lets
   .scroll do its job and keeps the body itself from ever scrolling horizontally. */
.wrap>*,section>*,.sechead>*{min-width:0;}
h1,h2,h3{font-family:Georgia,"Iowan Old Style","Palatino Linotype",Palatino,serif;
         font-weight:600; text-wrap:balance; margin:0; letter-spacing:-0.01em;}
h1{font-size:2.1rem; line-height:1.15;}
h2{font-size:1.4rem;}
h3{font-size:1.02rem;}
/* min(), not the bare measure: 64ch is wider than a phone, and prose overflowing its
   column widens the BODY, which is what puts a horizontal scrollbar under the whole page. */
p{margin:0; max-width:min(var(--measure),100%); overflow-wrap:break-word;}
a{color:var(--accent);}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent); outline-offset:3px;}

.eyebrow{font-size:.7rem; letter-spacing:.14em; text-transform:uppercase;
         color:var(--ink-faint); font-weight:600;}
.lede{color:var(--ink-soft); font-size:1.02rem;}
.mono{font-family:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
      font-variant-numeric:tabular-nums;}
.num{font-variant-numeric:tabular-nums;}

header.masthead{display:flex; flex-direction:column; gap:1rem;
                border-bottom:2px solid var(--ink); padding-bottom:1.5rem;}
.runline{display:flex; flex-wrap:wrap; gap:.5rem 1.5rem; font-size:.82rem;
         color:var(--ink-soft);}
.runline b{color:var(--ink); font-weight:600;}
.standfirst{background:var(--accent-soft); border-left:3px solid var(--accent);
            padding:.85rem 1rem; font-size:.9rem; color:var(--ink); max-width:none;}

section{display:flex; flex-direction:column; gap:1.1rem; min-width:0;}
.sechead{display:flex; flex-direction:column; gap:.35rem;
         border-bottom:1px solid var(--rule-strong); padding-bottom:.6rem;}

.scroll{overflow-x:auto; -webkit-overflow-scrolling:touch; max-width:100%; min-width:0;
        border:1px solid var(--rule); border-radius:2px; background:var(--surface);}
table{border-collapse:collapse; width:100%; font-size:.85rem;}
caption{text-align:left; padding:.6rem .8rem; color:var(--ink-soft); font-size:.8rem;
        border-bottom:1px solid var(--rule);}
th,td{padding:.5rem .7rem; text-align:left; border-bottom:1px solid var(--rule);
      vertical-align:top; white-space:nowrap;}
thead th{font-size:.68rem; letter-spacing:.09em; text-transform:uppercase;
         color:var(--ink-faint); font-weight:600; background:var(--sunken);
         position:sticky; top:0; z-index:1;}
tbody tr:last-child td{border-bottom:none;}
tbody tr:hover{background:var(--sunken);}
td.wrapcell,th.wrapcell{white-space:normal; min-width:11rem;}
/* The findings column carries the sentences, so it gets the slack: without a width the
   nowrap columns take what they need and the one column a reader came for is the one that
   ends up past the scroll edge, cut mid-word. */
td.finding,th.finding{white-space:normal; min-width:17rem; width:34%;}
td.scorecol{min-width:5.5rem;}
.right{text-align:right;}

/* The two judgements are two column GROUPS with a rule between them: the design's
   "different columns" made literal, so no reader adds them up by eye. */
.split{border-left:2px solid var(--rule-strong);}
thead th.grouphead{background:var(--surface); border-bottom:1px solid var(--rule-strong);
                   color:var(--accent); letter-spacing:.11em; position:static;}

.pill{display:inline-block; padding:.1rem .45rem; border-radius:2px; font-size:.72rem;
      font-weight:600; letter-spacing:.02em; white-space:nowrap;}
.t-clear{background:var(--clear-soft); color:var(--clear);}
.t-quiet{background:var(--sunken); color:var(--ink-soft);}
.t-caution{background:var(--caution-soft); color:var(--caution);}
.t-severe{background:var(--severe-soft); color:var(--severe);}
.t-unknown{background:var(--unknown-soft); color:var(--unknown);}
.tier{font-size:.68rem; color:var(--ink-faint); letter-spacing:.04em;}

.bar{display:block; width:100%; height:4px; background:var(--rule); border-radius:2px;
     margin-top:.3rem; overflow:hidden;}
.bar i{display:block; height:100%; background:var(--accent);}

.cards{display:grid; gap:1rem; grid-template-columns:repeat(auto-fill,minmax(19rem,1fr));}
.card{border:1px solid var(--rule); border-radius:2px; background:var(--surface);
      padding:1rem; display:flex; flex-direction:column; gap:.7rem;}
.card.flagged{border-left:3px solid var(--severe);}
.card h3{display:flex; justify-content:space-between; align-items:baseline; gap:.6rem;}
.card .sub{font-size:.78rem; color:var(--ink-faint);}
.blocks{display:flex; flex-direction:column; gap:.3rem; font-size:.78rem;}
.blocks div{display:flex; justify-content:space-between; gap:.5rem;}
.modes{margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:.45rem;
       font-size:.82rem; color:var(--ink-soft);}
.modes li{padding-left:.7rem; border-left:2px solid var(--rule-strong);}
.modes li.severe{border-left-color:var(--severe);}
.modes li.caution{border-left-color:var(--caution);}

.dist{display:grid; gap:.5rem; grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));}
.tile{border:1px solid var(--rule); border-radius:2px; background:var(--surface);
      padding:.7rem .8rem; display:flex; flex-direction:column; gap:.15rem;}
.tile b{font-size:1.5rem; font-weight:600; font-variant-numeric:tabular-nums;}
.tile span{font-size:.74rem; color:var(--ink-faint); letter-spacing:.05em;
           text-transform:uppercase;}

details{border-top:1px solid var(--rule); padding-top:.7rem;}
summary{cursor:pointer; font-size:.82rem; color:var(--accent); font-weight:600;}
.caveats{display:flex; flex-direction:column; gap:.6rem; font-size:.88rem;
         color:var(--ink-soft);}
.caveats b{color:var(--ink);}
footer{border-top:1px solid var(--rule); padding-top:1.2rem; font-size:.78rem;
       color:var(--ink-faint); display:flex; flex-direction:column; gap:.4rem;}
@media (max-width:640px){ h1{font-size:1.65rem;} .wrap{padding:1.5rem 1rem 3rem; gap:2.2rem;} }
@media (prefers-reduced-motion:reduce){ *{animation:none !important; transition:none !important;} }
"""


def _pill(text: str, tone: str) -> str:
    return f'<span class="pill t-{e(tone)}">{e(text)}</span>'


def _verdict_pill(inv: dict) -> str:
    return _pill(inv["verdict"], VERDICT_TONE.get(inv["verdict"], "quiet"))


def _score_cell(card: dict) -> str:
    pct = card.get("pct")
    if pct is None:
        return '<td class="right scorecol">—</td>'
    width = max(0, min(100, int(pct)))
    return (f'<td class="right num scorecol"><b>{pct}%</b>'
            f'<span class="bar"><i style="width:{width}%"></i></span></td>')


def _shortlist_table(rows: list[dict]) -> str:
    head = (
        '<thead>'
        '<tr>'
        '<th colspan="4" class="grouphead">The business — Buffett</th>'
        '<th colspan="4" class="grouphead split">How it breaks — Munger</th>'
        '</tr>'
        '<tr>'
        '<th>Ticker</th><th class="wrapcell">Name &amp; sector</th>'
        '<th class="right">Score</th><th>Points / evidence</th>'
        '<th class="split">Verdict</th><th class="right">Cautions</th>'
        '<th>Survives?</th><th class="finding">Nearest thing to a worry</th>'
        '</tr></thead>')
    body = []
    for row in rows:
        card, inv = row["card"], row["inversion"]
        lens = inversion.consensus_lens(inv)
        lens_text, lens_tone = ({True: ("yes", "clear"), False: ("no", "severe")}
                                .get(lens, ("won't say", "unknown")))
        worry = inv["failure_modes"][0] if inv["failure_modes"] else \
            "Nothing found by any probe that could be measured."
        body.append(
            f'<tr><td class="mono"><b>{e(row["symbol"])}</b></td>'
            f'<td class="wrapcell">{e(row["name"])}<br><span class="tier">'
            f'{e(row["sector"])}</span></td>'
            + _score_cell(card) +
            f'<td class="num">{e(_points(card))}<br><span class="tier">'
            f'{e(card.get("evidence", ""))}</span></td>'
            f'<td class="split">{_verdict_pill(inv)}</td>'
            f'<td class="right num">{inv["coverage"]["caution"]}</td>'
            f'<td>{_pill(lens_text, lens_tone)}</td>'
            f'<td class="finding">{e(worry)}</td></tr>')
    return ('<div class="scroll"><table>'
            '<caption>Sorted by evidence tier first, then score — a percentage of a small '
            'measurable base is not a better business than a slightly lower percentage of '
            'a large one.</caption>'
            + head + '<tbody>' + "".join(body) + '</tbody></table></div>')


def _fragile_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        card, inv = row["card"], row["inversion"]
        severe = inv["coverage"]["severe"]
        # Severe sentences when there are any; otherwise the cautions, because a name can
        # reach this table on four cautions alone and a blank cell would read as "no reason
        # given" for a verdict that has four of them.
        shown = inv["failure_modes"][:severe] if severe else inv["failure_modes"][:4]
        modes = "".join(
            f'<li class="{"severe" if severe else "caution"}">{e(mode)}</li>'
            for mode in shown)
        count = (f'{severe} severe' if severe
                 else f'{inv["coverage"]["caution"]} cautions')
        body.append(
            f'<tr><td class="mono"><b>{e(row["symbol"])}</b></td>'
            f'<td class="wrapcell">{e(row["name"])}</td>'
            f'<td class="right num"><b>{card["pct"]}%</b><br>'
            f'<span class="tier">{e(card["band"])}</span></td>'
            f'<td class="split">{_verdict_pill(inv)}<br>'
            f'<span class="tier">{e(count)}</span></td>'
            f'<td class="finding"><ul class="modes">{modes}</ul></td></tr>')
    return ('<div class="scroll"><table><thead><tr>'
            '<th>Ticker</th><th class="wrapcell">Name</th><th class="right">Card</th>'
            '<th class="split">Verdict</th>'
            '<th class="finding">What the probes actually found</th>'
            '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>')


def _pick_card(row: dict) -> str:
    card, inv = row["card"], row["inversion"]
    blocks = "".join(
        f'<div><span>{e(name.replace("_", " "))}</span>'
        f'<span class="mono">{block["points"]:.1f}/{block["max"]}</span></div>'
        for name, block in card["blocks"].items())
    why = card.get("why") or {}
    lines = [why.get(part, {}).get("sentence") for part in ("strongest", "weakest")]
    modes = "".join(
        f'<li class="{"severe" if i < inv["coverage"]["severe"] else "caution"}">{e(mode)}</li>'
        for i, mode in enumerate(inv["failure_modes"][:3]))
    if not modes:
        modes = ('<li>No probe that could be measured found anything — which is a statement '
                 'about the evidence held, not a promise.</li>')
    return (
        f'<article class="card{" flagged" if inv["coverage"]["severe"] else ""}">'
        f'<h3><span class="mono">{e(row["symbol"])}</span>'
        f'<span class="num">{card["pct"]}%</span></h3>'
        f'<div class="sub">{e(row["name"])} · {e(row["sector"])}</div>'
        f'<div>{_pill(card["band"], "quiet")} {_verdict_pill(inv)} '
        f'<span class="tier">{e(card.get("evidence", ""))} evidence · '
        f'consensus {e(card["consensus"]["label"])}</span></div>'
        f'<div class="blocks">{blocks}</div>'
        + "".join(f'<p class="tier">{e(line)}</p>' for line in lines if line) +
        f'<ul class="modes">{modes}</ul></article>')


def _detail_note(picks_rows: list[dict]) -> str:
    """Says out loud when the detail grid is showing fewer cards than there are picks.

    A truncated list that does not admit it reads as the whole list — the same silent-cap
    problem the fragility layer's provenance rules exist to prevent, one layer up."""
    if len(picks_rows) <= DETAIL_CARDS:
        return ('<p>Every pick above, with the blocks its points came from and the mildest '
                'thing the probes had to say.</p>')
    return (f'<p>The first <b>{DETAIL_CARDS}</b> of <b>{len(picks_rows)}</b> picks, in the '
            f'same order as the table — the remaining {len(picks_rows) - DETAIL_CARDS} are '
            f'in the table above with their scores and findings intact. This section is '
            f'capped so the page stays readable, and the cap is stated rather than left to '
            f'be noticed.</p>')


def _probe_legend() -> str:
    body = "".join(
        f'<tr><td class="mono">§{e(spec["section"])}</td>'
        f'<td>{e(spec["label"])}</td>'
        f'<td class="wrapcell">{e(spec["question"])}</td>'
        f'<td class="wrapcell">{e(spec["reads"])}</td>'
        f'<td>{"counts" if spec["counts"] else "flag only"}</td></tr>'
        for spec in inversion.PROBES.values())
    return ('<div class="scroll"><table><thead><tr><th>§</th><th>Probe</th>'
            '<th class="wrapcell">Question</th><th class="wrapcell">Reads</th>'
            '<th>Role</th></tr></thead><tbody>' + body + '</tbody></table></div>')


def _verdict_legend() -> str:
    body = "".join(
        f'<tr><td>{_pill(name, VERDICT_TONE[name])}</td>'
        f'<td class="mono">{e(spec["rule"])}</td>'
        f'<td class="wrapcell">{e(spec["meaning"])}</td></tr>'
        for name, spec in ((v, inversion.VERDICTS[v]) for v in VERDICT_ORDER))
    return ('<div class="scroll"><table><thead><tr><th>Verdict</th><th>Rule</th>'
            '<th class="wrapcell">Meaning</th></tr></thead><tbody>'
            + body + '</tbody></table></div>')


def _distribution(rows: list[dict]) -> str:
    counts = {v: 0 for v in VERDICT_ORDER}
    for row in rows:
        counts[row["inversion"]["verdict"]] = counts.get(row["inversion"]["verdict"], 0) + 1
    total = max(len(rows), 1)
    return '<div class="dist">' + "".join(
        f'<div class="tile"><b>{counts[v]}</b>'
        f'<span>{e(v)} · {100 * counts[v] // total}%</span></div>'
        for v in VERDICT_ORDER) + '</div>'


def render(rows: list[dict], *, as_of: str, source: str = "") -> str:
    picks = shortlist(rows)
    fragile = strong_but_fragile(rows)
    scoreable = [r for r in rows if r["card"].get("pct") is not None]
    source_line = f'<span>from <b>{e(source)}</b></span>' if source else ""

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Scout — picks, {e(as_of)}</title>
<style>{CSS}</style>
</head><body><div class="wrap">

<header class="masthead">
  <span class="eyebrow">Stock Scout · research shortlist</span>
  <h1>What is worth a Gate session</h1>
  <p class="lede">Two independent readings of the same filings. One asks how good the
  business is. The other asks how it would lose your money. They are never added together.</p>
  <div class="runline">
    <span>as of <b>{e(as_of)}</b></span>
    <span><b>{len(rows)}</b> names screened</span>
    <span><b>{len(scoreable)}</b> scoreable</span>
    <span><b>{len(picks)}</b> on the shortlist</span>
    {source_line}
  </div>
  <p class="standfirst"><b>This advises and monitors. It never executes trades.</b> A place
  on this list is a research shortlist, not a buy list — every name still has to pass the
  Gate, which is a human step. Nothing here is a price target or a recommendation.</p>
</header>

<section>
  <div class="sechead">
    <span class="eyebrow">How to read this page</span>
    <h2>Two columns, deliberately not one number</h2>
  </div>
  <p>The <b>score</b> is an absolute 100-point card — points against fixed lines the owner
  declared, not a ranking against whatever else happened to be listed. Where a metric could
  not be computed the card <i>shrinks its own denominator</i> rather than scoring a zero,
  which is why the points column shows what was actually available and an evidence tier
  beside it.</p>
  <p>The <b>verdict</b> is a separate count of seven fragility probes over the price and
  cash record. It adds no points and suppresses nothing on its own — it names the failure
  mode and leaves the decision to you. Severities are counted, never averaged, because an
  average lets a good probe cancel a fatal one.</p>
  <p>A business can be <b>Exceptional and Fragile at once.</b> That pairing has its own
  section below, and it is the most useful thing on this page.</p>
</section>

<section>
  <div class="sechead">
    <span class="eyebrow">The shortlist · {len(picks)} names</span>
    <h2>Strong on the card, with nothing severe against them</h2>
  </div>
  <p>A name reaches this table by passing three tests: {e(" or ".join(SHORTLIST_BANDS))} on
  the card, <b>no probe returning a severe finding</b>, and a verdict that is not itself a
  warning. Milder findings still appear — the last column carries the nearest thing to a
  worry each name has, in the layer's own words, because a shortlist that hid them would be
  doing the averaging this system refuses to do.</p>
  <p>"Survives?" is the fragility layer answering as a fourth consensus lens. It says
  <b>won't say</b> rather than yes whenever a flag or a severe probe stands, because a green
  tick beside a sentence naming a risk is the exact failure this layer exists to prevent.</p>
  {_shortlist_table(picks)}
</section>

<section>
  <div class="sechead">
    <span class="eyebrow">The pairing · {len(fragile)} names</span>
    <h2>Rated highly, and the probes have something to say</h2>
  </div>
  <p>These scored just as well on the business card, and are off the shortlist for what the
  probes found: a severe finding, or enough milder ones that the ladder calls it clear ways
  this breaks you. Shown in full, in the layer's own words, rather than folded into a
  number. Together with the table above this accounts for every
  {e(" and ".join(SHORTLIST_BANDS))} name — none drops quietly out of both.</p>
  {_fragile_table(fragile)}
</section>

<section>
  <div class="sechead">
    <span class="eyebrow">The shortlist in detail</span>
    <h2>Where each pick's points came from</h2>
  </div>
  {_detail_note(picks)}
  <div class="cards">{"".join(_pick_card(r) for r in picks[:DETAIL_CARDS])}</div>
</section>

<section>
  <div class="sechead">
    <span class="eyebrow">The whole universe</span>
    <h2>How the {len(rows)} screened names fall out</h2>
  </div>
  {_distribution(rows)}
  <details><summary>The seven probes, and what each one reads</summary>
    {_probe_legend()}
  </details>
  <details><summary>The verdict ladder</summary>
    <p class="tier">Rungs are calibrated against the measured firing rates of the six
    counting probes, not assumed. See <span class="mono">docs/INVERSION-DESIGN.md</span> §4
    and §8.</p>
    {_verdict_legend()}
  </details>
</section>

<section class="caveats">
  <div class="sechead">
    <span class="eyebrow">Before you act on any of this</span>
    <h2>What this page cannot see</h2>
  </div>
  <p><b>It reads what already happened</b> to the cash and the price. Lawsuits, regulation,
  a competitor's roadmap, a fraud not yet in the numbers, key-person risk — none of it is
  here, and no probe returning "nothing found" is a statement that nothing is there.</p>
  <p><b>An unmeasured probe is not a passed one.</b> Where the filer never tagged the
  figure, the layer says so. Customer concentration is the sharpest case: only about a
  tenth of these filers tag it at all, and the median disclosure is years old.</p>
  <p><b>The card's percentage is of what could be measured.</b> Two names with the same
  percentage can rest on very different amounts of evidence — that is what the tier beside
  each score is for, and why this page sorts on it first.</p>
  <p><b>None of this has been validated as a strategy.</b> The scorecard's anchors and the
  fragility lines are declared and reasoned, not walk-forward tested. The only rules in this
  repo that survived a blind walk-forward are the v3 formation's entry and exit rules, and
  they are a different question from this page.</p>
</section>

<footer>
  <span>Generated by <span class="mono">picks.py</span> · Stock Scout · as of {e(as_of)}</span>
  <span>Self-contained: no external fonts, scripts, styles or images.</span>
</footer>

</div></body></html>
"""


# --- CLI ------------------------------------------------------------------------------------

def _load_prices(directory: Path | None) -> dict:
    """A directory of §3.6 price files -> {symbol: {day: bar}}. Only `adj_close` is ever
    read downstream, but the whole bar is passed through unchanged."""
    if directory is None:
        return {}
    grid = {}
    for path in sorted(Path(directory).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        bars = payload.get("bars") or {}
        if bars:
            grid[payload.get("symbol") or path.stem] = bars
    return grid


def _load_meta(path: Path) -> dict:
    """universe.csv -> {symbol: {name, sector, industry}}, with NaN-ish cells dropped so a
    float NaN never reaches a formatter (or a sector percentile) as a label."""
    import csv
    out = {}
    if not Path(path).exists():
        return out
    with open(path, newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            symbol = (record.get("symbol") or "").strip()
            if symbol:
                out[symbol] = {key: (record.get(key) or None)
                               for key in ("name", "sector", "industry")}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sec-data", help="bulk SEC CSV export directory (secsv)")
    parser.add_argument("--prices", help="directory of weekly price files")
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--as-of", default=_dt.date.today().isoformat())
    parser.add_argument("--enrich-cache", help="tier-2 companyfacts cache: gap-fill for "
                                               "export names, cache-only bootstrap for "
                                               "universe names beyond the export")
    parser.add_argument("--out", help="output path (default reports/picks-<as-of>.html)")
    args = parser.parse_args(argv)

    if not args.sec_data:
        parser.error("--sec-data is required (the yfinance-cache path runs through grade.py)")

    import pit
    import secsv
    meta = _load_meta(Path(args.universe))
    prices = _load_prices(Path(args.prices) if args.prices else None)
    facts = secsv.load_facts(args.sec_data)
    secsv.merge_tag_index(facts, args.sec_data)
    if args.enrich_cache and Path(args.enrich_cache).exists():
        import enrich
        try:
            ciks = enrich.cik_map_cached(Path(args.enrich_cache))
            made = enrich.bootstrap_payloads(
                facts, [s for s in meta if s not in facts],
                cache_dir=Path(args.enrich_cache), ciks=ciks, cache_only=True)
            enrich.enrich_payloads(
                facts, sorted(t for t, c in ciks.items()
                              if t in facts and t not in made
                              and (Path(args.enrich_cache) / f"CIK{c:010d}.json").exists()),
                cache_dir=Path(args.enrich_cache), ciks=ciks)
        except Exception as error:  # noqa: BLE001 — enrichment is a bonus, never a gate
            print(f"enrichment unavailable ({type(error).__name__}: {error}) — "
                  f"screening on export facts only")
    bundles = [b for b in (pit.as_of_bundle(facts[s], s, meta.get(s), args.as_of,
                                            prices or {})
                           for s in sorted(facts)) if b is not None]
    rows = build_rows(bundles, prices=prices, meta=meta)

    out = Path(args.out) if args.out else Path("reports") / f"picks-{args.as_of}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(rows, as_of=args.as_of,
                          source=f"SEC export · {len(bundles)} filers"), encoding="utf-8")
    print(f"{out}  ({len(shortlist(rows))} picks of {len(rows)} screened)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
