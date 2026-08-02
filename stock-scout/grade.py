"""Live grading run (spec §5.5): universe + cache -> scoring -> reports + formation.

The live half of the decoupling seam (§4, msg 44): cache/<SYM>.json entries (§3.2)
are mapped to §4.1 Bundles by build_bundle() — own market_cap from fast_info,
yahoo_ev from fast_info when present, shares dict -> ascending series, statements
straight through — and fed to scoring.score_universe, the same pure code the
backtests use. Then per graded name the §4.8 shadow layers (margin of safety +
Buffett checklist — never in the composite), the Owner's Scorecard (the absolute
anchored composite, docs/SCORECARD-DESIGN.md), the proposal portfolio, and the v3
formation update (§5.6, the live mode per msg 58) unless --no-formation.

A cache file that cannot be read (torn JSON, missing "ticker") is skipped like an
uncached one and named with its reason in the report — one bad file never takes
the run down.

The inversion layer (docs/INVERSION-DESIGN.md) rides beside the score: where a §3.6
weekly price grid exists for a graded name, `inversion.inversion()` is asked how that
name breaks, the verdict is stored on the §3.3 row under "inversion" and handed to
scorecard() as its fourth (survival) lens. It is OPTIONAL in both directions — no
prices, or no inversion.py at all, degrades to the three-lens card this run has always
produced (the normal case for the ~470 price-less names), and it moves not one point
(INVERSION-DESIGN §2).

Outputs (§3.3): reports/scout-run-<date>.md + reports/scout-grades-<date>.json.
The md LEADS with the scorecard, because that is the interpretable number: a
"hoe je dit leest" block, then the banded scorecard tables (score/band/fragility/
consensus/blocks, with grade+composite demoted to a rank-within-sector context
column), then — per INVERSION-DESIGN §5, the most useful thing that layer produces —
the names that are Exceptional or Strong YET Fragile or Ruinous under their own
heading, then the names that carry no band at all (NO PRICE, VETOED) in their own
section — never mixed into the ordering (§4.1/§4.3). Behind that the report keeps
everything it had: the veto breakdown by distinct sub-reason, the tier-sectioned A-F
tables (now labelled as sector-relative context), the NL-names call-out, "De Formatie"
and the honest-evidence footer. --telegram sends the md summary head via tg.py and
attaches the newest datasheet when present.
"""
from __future__ import annotations

import argparse
import html
import inspect
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

import formation
import pit
import scorecard
import scoring
import tg
from populate import cache_filename

VERSION = "v2.3+v3"
GRADE_LETTERS = ("A", "B", "C", "D", "F")
TIERS = ("Core", "Adjacent", "Outside")
_DATASHEET_RE = re.compile(r"^datasheet-(\d{4}-\d{2}-\d{2})\.html$")

# The §5 band table drives the report's grouping. Only the bands with a numeric floor
# are ordered against each other; the two special bands (VETOED, NO PRICE) get their own
# section so nothing without a verdict is ever sorted next to something with one.
BAND_ORDER = tuple(e["band"] for e in scorecard.BANDS if e["floor"] is not None)
BAND_FLOOR = {e["band"]: e["floor"] for e in scorecard.BANDS}
BAND_MEANING = {e["band"]: e["meaning"] for e in scorecard.BANDS}
# Block -> the short column head in the main table (design §5 "Blocks").
BLOCK_COLS = (("quality", "Q"), ("price", "P"), ("safety", "S"), ("stewardship", "St"))
VETOED_LIST_MAX = 25          # a 2k-name universe vetoes hundreds; the tail is counted

# --- the inversion layer (docs/INVERSION-DESIGN.md) ---------------------------------------
PRICES_DIR = "bt_cache/prices"   # §3.6 weekly grids; absent -> no inversion, no complaint

# The verdicts that name a way this loses your money, DERIVED from the published §4 verdict
# table rather than copied: whichever verdicts that table calls non-survivors are the ones
# §5's call-out section is about. A renamed verdict moves with the table.
FRAGILE_VERDICTS = tuple(sorted(v for v, survives in scorecard.INVERSION_SURVIVES.items()
                                if survives is False))
# The bands §5 pairs fragility against ("A name can be Exceptional and Fragile at once").
# The two richest bands, read off the band table — never a second copy of their names.
TOP_BANDS = BAND_ORDER[:2]
# Which of inversion.inversion()'s parameters takes the §3.6 weekly bars, when it takes
# them by keyword at all. The other module owns its own signature; this is the seam.
PRICE_PARAM_NAMES = ("bars", "prices", "weekly", "grid", "price_grid", "weekly_prices",
                     "price_bars", "price_history")
# ...and which one takes the §3.3 row this runner already scored. inversion.inversion()
# documents `scored_row` as how the two layers agree about a SHARE_CLASS name instead of
# deciding separately; without it the layer re-runs scoring.evaluate() per priced name, so
# the agreement is a coincidence of recomputation rather than the shared computation.
ROW_PARAM_NAMES = ("scored_row", "row", "scored")


# ---------------------------------------------------------------- cache -> Bundle

def build_bundle(cache_entry: dict) -> dict:
    """One §3.2 cache entry -> one §4.1 Bundle (pure). market_cap and yahoo_ev come
    from fast_info (yahoo_ev absent -> None: the EV_GAP flag then never fires, §4.5);
    both snake_case (§3.2) and raw yfinance camelCase keys are accepted. The shares
    dict becomes the ascending, deduped [["date", n], ...] series; statement payloads
    pass through untouched (row-label mapping is scoring's job, §4.1)."""
    fi = cache_entry.get("fast_info") or {}
    meta = cache_entry.get("meta") or {}
    return {
        "symbol": cache_entry["ticker"],
        "name": meta.get("name"),
        "sector": meta.get("sector"),
        "industry": meta.get("industry"),
        "market_cap": fi.get("market_cap", fi.get("marketCap")),
        "yahoo_ev": fi.get("enterprise_value", fi.get("enterpriseValue")),
        "price": (cache_entry.get("price") or {}).get("close"),
        "shares_series": [[d, v] for d, v in sorted((cache_entry.get("shares") or {}).items())],
        "splits": cache_entry.get("splits") or {},   # §3.2 — a split is not dilution (§4.3)
        "annual": cache_entry.get("annual") or {},
        "quarterly": cache_entry.get("quarterly") or {},
    }


def load_bundles(universe_path: str | Path, cache_dir: str | Path
                 ) -> tuple[list[dict], int, int, list[dict]]:
    """Universe rows -> (bundles in universe order, universe size, uncached count,
    unreadable entries).

    Uncached symbols are skipped and counted (§5.5 step 1), never fabricated. A cache
    file that cannot be turned into a Bundle — torn/corrupt JSON, a missing "ticker",
    the wrong shape — is treated exactly like an uncached one: skipped, and recorded as
    {"symbol", "reason"} so the run's report names it. One bad file out of hundreds
    must never take the whole grading run down (the datasheet already tolerates the
    identical file, §5.7)."""
    rows = pd.read_csv(universe_path).to_dict("records")
    cache_dir = Path(cache_dir)
    bundles, uncached, unreadable = [], 0, []
    for row in rows:
        symbol = str(row["symbol"])
        path = cache_dir / cache_filename(symbol)
        if not path.exists():
            uncached += 1
            continue
        try:
            bundles.append(build_bundle(json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError as e:
            unreadable.append({"symbol": symbol, "reason": f"corrupte JSON: {e}"})
        except KeyError as e:
            unreadable.append({"symbol": symbol, "reason": f"ontbrekend veld {e}"})
        except (OSError, ValueError, TypeError, AttributeError) as e:
            unreadable.append({"symbol": symbol,
                               "reason": f"{type(e).__name__}: {e}"})
    return bundles, len(rows), uncached, unreadable


# -------------------------------------------------------- the inversion layer's seam

def load_price_bars(prices_dir: str | Path | None, symbols
                    ) -> tuple[dict[str, dict], list[dict]]:
    """§3.6 prices/<SYM>.json -> ({symbol: {date: bar}}, unreadable entries).

    Only the run's own symbols are read, and only when the directory exists: a checkout
    without a price cache is the ~470-name norm (INVERSION-DESIGN §7 / SCORECARD §4.1),
    not an error. A torn or unparsable price file is skipped and named with its reason,
    exactly like an unreadable cache entry — one bad file never takes a run down."""
    if not prices_dir:
        return {}, []
    root = Path(prices_dir)
    if not root.is_dir():
        return {}, []
    bars, unreadable = {}, []
    for symbol in symbols:
        path = root / cache_filename(symbol)
        if not path.exists():
            continue
        try:
            _sym, grid, _splits = pit.load_price_file(
                json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            unreadable.append({"symbol": symbol, "reason": f"corrupte JSON: {e}"})
            continue
        except (OSError, ValueError, TypeError, AttributeError) as e:
            unreadable.append({"symbol": symbol, "reason": f"{type(e).__name__}: {e}"})
            continue
        if grid:
            bars[symbol] = grid
    return bars, unreadable


def _inversion_module():
    """`inversion.py`, imported lazily and here only. The layer ships separately from this
    runner: a checkout without it must still grade, report and form a squad."""
    try:
        import inversion
    except ImportError:
        return None
    return inversion


def _price_parameter(fn):
    """How this `inversion()` wants the §3.6 weekly bars: a keyword name, True for a second
    positional slot, or None when it takes the Bundle alone.

    The other module owns its own signature (it is written and shipped separately), so the
    shape is READ off the function rather than assumed; an unreadable signature falls back
    to the positional call, and a bundle-only function is called with the bundle alone
    rather than with an argument it never asked for."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return True
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) >= 2:
        return True
    for p in params:
        if p.kind is p.KEYWORD_ONLY and p.name in PRICE_PARAM_NAMES:
            return p.name
    return None


def _row_parameter(fn):
    """The keyword-only parameter this `inversion()` takes the §3.3 scored row on, or None.

    Offered, never forced: a layer that does not ask for the row is called exactly as
    before. Same discipline as _price_parameter — the other module owns its signature."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return None
    for p in params:
        if p.kind is p.KEYWORD_ONLY and p.name in ROW_PARAM_NAMES:
            return p.name
    return None


def _json_safe(result: dict) -> bool:
    """Whether a verdict can survive the §3.3 write. The grades JSON is written with
    allow_nan=False, and a NaN out of a probe on a flat series would otherwise take down
    the whole run at its very last step — so a result that cannot be serialized is dropped
    and NAMED, never silently repaired into a comforting number."""
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def inversion_for(bundle: dict, bars: dict | None,
                  row: dict | None = None) -> tuple[dict | None, str | None]:
    """One name's inversion verdict -> (result, skip reason). Both None-able on purpose.

    Absent layer, absent prices, a layer that raises, or a result that will not serialize:
    all degrade to no verdict plus a reason the report prints. Silence about a name's
    fragility is honest here — INVERSION-DESIGN §7 — as long as it is stated; what is
    forbidden is inventing a comforting one.

    `row` is this name's already-scored §3.3 row, handed over when the layer asks for it by
    keyword, so the two layers read ONE computation of the flags instead of each running
    scoring.evaluate() over the same Bundle."""
    if not bars:
        return None, None                     # the price-less norm: nothing to say, no noise
    module = _inversion_module()
    fn = getattr(module, "inversion", None)
    if fn is None:
        return None, ("inversion.py niet geïnstalleerd" if module is None
                      else "inversion.py heeft geen inversion()")
    wants = _price_parameter(fn)
    extra = {}
    if row is not None and (row_kw := _row_parameter(fn)):
        extra[row_kw] = row
    try:
        if wants is True:
            result = fn(bundle, bars, **extra)
        elif wants:
            result = fn(bundle, **{wants: bars}, **extra)
        else:
            result = fn(bundle, **extra)
    except Exception as e:                    # a probe must never take the run down
        return None, f"{type(e).__name__}: {e}"
    if not isinstance(result, dict):
        return None, (f"inversion() gaf {type(result).__name__} terug, geen dict")
    if not _json_safe(result):
        return None, "verdict niet serialiseerbaar (NaN/inf of niet-JSON waarde)"
    return result, None


def inversion_of(row: dict) -> dict | None:
    """The verdict attached to a §3.3 row — the normalized projection on the card first
    (its verdict key is guaranteed, §5), the raw row key second."""
    card = (row.get("scorecard") or {}).get("inversion")
    if isinstance(card, dict):
        return card
    raw = row.get("inversion")
    return raw if isinstance(raw, dict) else None


def verdict_of(row: dict) -> str | None:
    """The row's inversion verdict as text, or None when the layer had no answer."""
    result = inversion_of(row)
    verdict = (result or {}).get("verdict")
    return str(verdict) if verdict else None


def is_fragile(row: dict) -> bool:
    """Whether this name carries one of the §4 non-survivor verdicts (Fragile / Ruinous)."""
    verdict = verdict_of(row)
    return bool(verdict) and verdict.strip().lower() in FRAGILE_VERDICTS


def failure_sentence(mode) -> str:
    """One failure mode as plain language (§4), whether the layer hands over the sentence
    itself or a probe record carrying one. Never a repr."""
    if isinstance(mode, dict):
        for key in ("sentence", "detail", "note", "reason", "label"):
            if mode.get(key):
                return str(mode[key])
        return ""
    return str(mode or "")


def failure_modes(row: dict) -> list[str]:
    return [s for s in (failure_sentence(m)
                        for m in (inversion_of(row) or {}).get("failure_modes") or []) if s]


# ------------------------------------------------------------------- report pieces

def _fmt(value, spec: str = ".1f", suffix: str = "") -> str:
    return "—" if value is None else f"{value:{spec}}{suffix}"


def _mos_pct(row: dict) -> str:
    mos = row.get("mos")
    return "—" if not mos else f"{100.0 * mos['mos_pct']:+.0f}%"


def _pts(value) -> str:
    """Points without false precision: 29 stays 29, 9.6 stays 9.6, None is an em dash."""
    return "—" if value is None else f"{value:g}"


def _band_range(band: str) -> str:
    """'80–100', '65–79' — derived from the §5 floors themselves, so the report can never
    advertise a band boundary the scorecard no longer holds."""
    i = BAND_ORDER.index(band)
    top = 100 if i == 0 else BAND_FLOOR[BAND_ORDER[i - 1]] - 1
    return f"{BAND_FLOOR[band]}–{top}"


def _how_to_read(has_inversion: bool = False) -> list[str]:
    """The §5 interpretation layer in five lines, rendered from the scorecard's own
    constants. It sits above the first '## ' so it rides along in the Telegram head.

    The fragility line joins ONLY when this run actually produced verdicts: a run with no
    price grids would otherwise explain a column that is not there."""
    lenses = len(scorecard.CONSENSUS_LENSES)
    inversion = [
        "- Fragiliteit staat NAAST de score, niet erin: Munger's bril zegt hoe een naam "
        "breekt, niet hoe goed hij is, en verschuift geen enkel punt "
        "(INVERSION-DESIGN §2). Een naam kan tegelijk Exceptional én Fragile zijn — "
        "dat paar is juist de opbrengst van deze laag.",
        f"- Waar die laag een antwoord had, telt hij mee als "
        f"{len(scorecard.CONSENSUS_LENSES_ALL)}e bril — overleving "
        f"(\"{scorecard.CONSENSUS_SURVIVAL_LENS}\"): overleeft dit? Dan staat er consensus "
        f"n/{len(scorecard.CONSENSUS_LENSES_ALL)} in plaats van "
        f"n/{len(scorecard.CONSENSUS_LENSES)}. Beide getallen zijn eerlijk; het tweede is "
        "geen afgekapte versie van het eerste.",
        "- \"Unknown\" betekent te weinig bewijs om te zeggen hoe iets breekt. Het is "
        "hardop gezegd en wordt nooit als veilig gelezen (§4/§7). Een streepje betekent "
        "iets anders: die naam is niet eens onderzocht (geen koershistorie).",
    ] if has_inversion else []
    return [
        "Hoe je dit leest:",
        f"- De score is absoluut: {scorecard.FULL_MAX} punten tegen vaste ankers, niet "
        "tegen wie er toevallig meedraait. Dezelfde onderneming scoort morgen hetzelfde.",
        f"- Lees banden, geen rangen. Verschillen onder ±{scorecard.NOISE_FLOOR:.0f} punten "
        "zijn niet betekenisvol — binnen één band is de volgorde ruis.",
        f"- Consensus n/{lenses}: hoeveel van {lenses} onafhankelijke brillen deze naam goed "
        f"noemen (scorecard ≥ {scorecard.CONSENSUS_SCORECARD_PCT:.0f}%, DCF-veiligheidsmarge "
        f"> 0, Buffett-checklist ≥ {scorecard.CONSENSUS_BUFFETT_SCORE}). "
        f"{lenses} van {lenses} is het signaal, niet de eerste plek.",
        f"- {scorecard.NO_PRICE_BAND} is géén oordeel maar een kwaliteitsprofiel: zonder "
        "prijsdata zegt de scorecard niets over kopen (§4.1). Een veto onderdrukt de "
        "score, het rangschikt niet (§4.3).",
        "- \"rang in sector\" (grade + composite) staat er als context — waar een naam "
        "tussen zijn sectorgenoten staat — en is nadrukkelijk niet het oordeel.",
    ] + inversion


def _score_cell(card: dict) -> str:
    """The headline score for one banded name. `pct` is a percentage of the AVAILABLE
    maximum, so a name with an unavailable metric shows both (§4.2: 48/75, never 48/100)."""
    if card.get("pct") is None:
        return "—"
    if card["available_max"] >= scorecard.FULL_MAX:
        return f"{card['pct']}/100"
    return f"{card['pct']}/100 · {_pts(card['score'])}/{card['available_max']} pt"


def _block_cells(card: dict) -> list[str]:
    """Quality/Price/Safety/Stewardship as points-of-available-points (design §5)."""
    blocks = card.get("blocks") or {}
    out = []
    for block, _ in BLOCK_COLS:
        b = blocks.get(block) or {}
        out.append("—" if not b.get("max") else f"{_pts(b['points'])}/{b['max']}")
    return out


def _consensus_cell(card: dict) -> str:
    c = card.get("consensus") or {}
    return "—" if not c else f"{c['green']}/{c['of']}"


def _context_cell(row: dict) -> str:
    """grade + composite — the sector-relative rank, kept as context, never as verdict."""
    grade = row.get("grade") or "—"
    return f"{grade} {_fmt(row.get('composite'))}"


def _fragility_cell(row: dict) -> str:
    """The §4 verdict, printed as the inversion layer worded it. No verdict at all is an em
    dash — an absent lens, which is not the same as a clean one; "Unknown" is printed as
    "Unknown", because too little evidence is said out loud and never read as safe."""
    return verdict_of(row) or "—"


def has_inversion(rows: list[dict]) -> bool:
    """Whether any of these rows carries a verdict — the switch for the fragility column
    and for its "hoe je dit leest" line. A run without price grids must render exactly the
    report it rendered before this layer existed, not a column full of em dashes."""
    return any(inversion_of(r) for r in rows)


def _scorecard_table(rows: list[dict], *, banded: bool = True,
                     fragility: bool = False) -> list[str]:
    """The main table: score and band first, blocks and consensus next to them, the
    percentile composite last and labelled. No rank column — §1.2 is the whole reason the
    scorecard exists, and a '#' invites reading #9 against #11 as if it meant something.

    `fragility` adds the INVERSION-DESIGN §5 column beside the score: how this name breaks,
    right next to how good it is, so the two are read together and neither is reconciled
    away. It is off unless the run produced verdicts (see has_inversion)."""
    head = "score" if banded else "punten"
    frag_head, frag_rule = ("fragiliteit | ", "-------------|") if fragility else ("", "")
    lines = [f"| symbool | naam | {head} | band | {frag_head}consensus | Q | P | S | St "
             "| flags | rang in sector (context) |",
             "|---|------|-------|------|" + frag_rule
             + "-----------|---|---|---|----|-------|--------|"]
    for r in rows:
        card = r.get("scorecard") or {}
        flags = ", ".join(f["code"] for f in r.get("flags") or []) or "—"
        score = (_score_cell(card) if banded
                 else f"{_pts(card.get('score'))}/{card.get('available_max', '—')} pt")
        frag = f"{_fragility_cell(r)} | " if fragility else ""
        lines.append(
            f"| {r['symbol']} | {r.get('name') or '—'} | {score} | {card.get('band', '—')} "
            f"| {frag}{_consensus_cell(card)} | " + " | ".join(_block_cells(card)) +
            f" | {flags} | {_context_cell(r)} |")
    return lines


def _band_counts(graded: list[dict]) -> Counter:
    return Counter((r.get("scorecard") or {}).get("band") for r in graded
                   if r.get("scorecard"))


def _scorecard_section(graded: list[dict]) -> list[str]:
    """§5's banded groups: sorted by pct descending, but printed per band so the output
    never invites reading rank 9 against rank 11 (design §1.2). Empty bands are skipped;
    the header line above already reports the full band occupancy."""
    fragility = has_inversion(graded)
    banded = {band: [] for band in BAND_ORDER}
    for r in graded:
        card = r.get("scorecard")
        if card and card.get("band") in banded:
            banded[card["band"]].append(r)
    total = sum(len(v) for v in banded.values())
    lines = ["", f"## Scorecard — absolute punten ({total})", "",
             "Gesorteerd op score, gegroepeerd in banden. Binnen een band is de volgorde "
             f"ruis (±{scorecard.NOISE_FLOOR:.0f} punten); tussen banden zit het verschil."]
    if not total:
        return lines + ["", "_Geen naam met een band deze run._"]
    for band in BAND_ORDER:
        rows = sorted(banded[band], key=lambda r: (-r["scorecard"]["pct"], r["symbol"]))
        if not rows:
            continue
        lines += ["", f"### {band} {_band_range(band)} ({len(rows)}) — "
                      f"{BAND_MEANING[band]}", ""]
        lines += _scorecard_table(rows, fragility=fragility)
    return lines


def _fragile_section(graded: list[dict]) -> list[str]:
    """INVERSION-DESIGN §5's own heading: the names that are Exceptional or Strong YET
    Fragile or Ruinous.

    §2 calls this pairing "the most useful thing this layer produces", so it gets a
    section rather than a cell somewhere in a wide table — a high score is exactly what
    stops a reader from looking any further. Nothing is reconciled here: the score stays
    what it is, the verdict stays what it is, and both are printed side by side with the
    failure modes that decided the verdict.

    Absent entirely when the run produced no verdicts. Present-but-empty is a first-class
    outcome and says so in words: no name in the top bands has a named way of breaking you
    is a result, not a blank."""
    if not has_inversion(graded):
        return []
    hits = [r for r in graded
            if (r.get("scorecard") or {}).get("band") in TOP_BANDS and is_fragile(r)]
    lines = ["", f"## Sterk maar fragiel ({len(hits)})", "",
             f"Namen in de banden {' en '.join(TOP_BANDS)} die tegelijk een "
             f"{'- of '.join(v.capitalize() for v in FRAGILE_VERDICTS)}-verdict dragen. "
             "De score zegt hoe goed het bedrijf is, het verdict hoe het breekt; hier "
             "staan ze naast elkaar in plaats van dat er één wint (INVERSION-DESIGN §2)."]
    if not hits:
        return lines + ["", "_Geen enkele naam in de topbanden draagt deze run een "
                            "fragiliteitsverdict — dat is een uitkomst, geen leegte._"]
    lines += [""]
    for r in sorted(hits, key=lambda r: (-r["scorecard"]["pct"], r["symbol"])):
        card = r["scorecard"]
        modes = failure_modes(r)
        lines.append(f"- **{r['symbol']}** — {r.get('name') or '—'} · "
                     f"{_score_cell(card)} · {card.get('band')} · **{_fragility_cell(r)}**")
        lines += [f"  - {m}" for m in modes] or [
            "  - het verdict noemt geen faalmodus in woorden — zie de datasheet voor de "
            "probes zelf"]
    lines += ["", "Dit onderdrukt niets en rangschikt niets: de inversielaag benoemt de "
                  "faalmodus, de mens beslist (INVERSION-DESIGN §2)."]
    return lines


def _unbanded_section(scored: list[dict], graded: list[dict]) -> list[str]:
    """Everything the scorecard refuses to band, kept out of the ordering on purpose:
    NO PRICE names (a quality profile, explicitly not a verdict — §4.1), VETOED names
    (score suppressed, never ranked — §4.3) and any graded name whose card is absent."""
    no_price = [r for r in graded
                if (r.get("scorecard") or {}).get("band") == scorecard.NO_PRICE_BAND]
    vetoed = [r for r in scored if (r.get("veto") or {}).get("vetoed")]
    cardless = [r for r in graded if not r.get("scorecard")]
    lines = ["", "## Zonder band (geen oordeel)", ""]
    if not (no_price or vetoed or cardless):
        return lines + ["Geen namen buiten de banden deze run."]

    if no_price:
        lines += [f"### {scorecard.NO_PRICE_BAND} ({len(no_price)})", "",
                  scorecard.NO_PRICE_MEANING.rstrip(".") + ". Deze namen staan bewust "
                  "buiten de bandvolgorde: er valt niets te rangschikken.", ""]
        lines += _scorecard_table(sorted(no_price, key=lambda r: r["symbol"]),
                                  banded=False, fragility=has_inversion(no_price))
        lines += [""]
    if vetoed:
        lines += [f"### {scorecard.VETOED_BAND} ({len(vetoed)})", "",
                  BAND_MEANING[scorecard.VETOED_BAND].rstrip(".") + ".", ""]
        lines += [f"- {r['symbol']} — {r.get('name') or '—'} — "
                  f"{(r.get('veto') or {}).get('reason') or 'geen reden opgegeven'}"
                  for r in vetoed[:VETOED_LIST_MAX]]
        if len(vetoed) > VETOED_LIST_MAX:
            lines.append(f"- … en {len(vetoed) - VETOED_LIST_MAX} meer — zie de "
                         "veto-verdeling hierboven.")
        lines += [""]
    if cardless:
        lines += [f"### Geen scorecard ({len(cardless)})", "",
                  "Gegradeerd, maar zonder scorecard in deze run:",
                  ", ".join(r["symbol"] for r in cardless), ""]
    while lines and not lines[-1]:            # the next section supplies its own blank
        lines.pop()
    return lines


def _nl_line(row: dict) -> str:
    """One NL call-out line, scorecard first and the sector rank in brackets behind it."""
    card = row.get("scorecard") or {}
    band = card.get("band")
    if not card:
        return f"- {row['symbol']} — {row.get('grade') or '—'} (geen scorecard)"
    if band in BAND_ORDER:
        head = f"{_score_cell(card)} · {band}"
    else:                                     # NO PRICE / VETOED carry no verdict (§4.1)
        head = f"{band} — {_pts(card.get('score'))}/{card.get('available_max')} pt"
    return (f"- {row['symbol']} — {head} · consensus {_consensus_cell(card)} "
            f"(rang in sector: {_context_cell(row)})")


def _grade_table(names: list[dict]) -> list[str]:
    lines = ["| # | symbool | naam | grade | comp | V | Q | G | D | M | MoS% | flags |",
             "|---|---------|------|-------|------|---|---|---|---|---|------|-------|"]
    for i, r in enumerate(names, 1):
        p = r["pillars"]
        flags = ", ".join(f["code"] for f in r["flags"]) or "—"
        lines.append(
            f"| {i} | {r['symbol']} | {r['name'] or '—'} | {r['grade']} "
            f"| {_fmt(r['composite'])} | {_fmt(p['v'], '.0f')} | {_fmt(p['q'], '.0f')} "
            f"| {_fmt(p['g'], '.0f')} | {_fmt(p['d'], '.0f')} | {_fmt(p['m'], '.0f')} "
            f"| {_mos_pct(r)} | {flags} |")
    return lines


_MEASURED_NUMBER_RE = re.compile(r"(?P<cmp>[<>=≤≥]+\s*)?[+-]?\d+(?:[.,]\d+)?")


def canonical_veto_reason(reason: str) -> str:
    """One §4.4 veto reason -> its distinct SUB-reason key, for the §5.5 breakdown.

    scoring.py owns the wording; this only elides the measured values ("net debt/EBITDA
    6.1" -> "net debt/EBITDA …") while leaving thresholds — the numbers behind a
    comparison operator — in place. So every instance of one branch collapses onto one
    key, and the two leverage branches stay APART: "leverage veto: net debt/EBITDA … >
    4.0" vs "leverage veto: EBITDA <= 0 while carrying net debt" (msg 10's split:
    41x the first, 15x the second). Wording-agnostic: no reason string is hard-coded."""
    canon = _MEASURED_NUMBER_RE.sub(lambda m: m.group(0) if m.group("cmp") else "…",
                                    str(reason or ""))
    return re.sub(r"\s+", " ", canon).strip() or "veto zonder opgegeven reden"


def _veto_breakdown(scored: list[dict]) -> list[str]:
    """Veto counts per reason family (the text before the first ':'), split into their
    distinct sub-reasons whenever a family has more than one (§5.5). The family total
    stays on top so the header reads like the chat's; the sub-lines are what msg 10
    reports ("41x net debt/EBITDA > 4; 15x EBITDA <= 0 met netto schuld")."""
    families: dict[str, Counter] = {}
    for r in scored:
        if not r["veto"]["vetoed"]:
            continue
        canon = canonical_veto_reason(r["veto"]["reason"])
        family, _, detail = canon.partition(":")
        families.setdefault(family.strip(), Counter())[detail.strip() or family.strip()] += 1
    if not families:
        return ["Veto-verdeling: geen veto's deze run."]
    lines = ["Veto-verdeling:"]
    for family, subs in sorted(families.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        lines.append(f"- {family}: {sum(subs.values())}")
        if len(subs) > 1:                     # one sub-reason adds nothing to the family
            lines += [f"  - {sub}: {n}" for sub, n in subs.most_common()]
    return lines


def _formation_section(state: dict | None, transfers: list[dict],
                       updated: bool) -> list[str]:
    """§5.5 "De Formatie": squad (since/streak/rank), this run's transfers with
    reasons, bench with needed-quarters, open slots as cash."""
    if state is None:
        return ["## De Formatie", "",
                "Formatie-update overgeslagen (--no-formation), geen bestaande state."]
    lines = [f"## De Formatie ({state['quarter']})", ""]
    if not updated:
        lines.append("_Formatie-update overgeslagen (--no-formation); "
                     "dit is de bestaande opstelling._")
        lines.append("")
    lines.append(f"Opstelling — {len(state['squad'])}/{state['slots']} plekken bezet:")
    lines.append("")
    if state["squad"]:
        lines += ["| # | symbool | rang | in sinds | streak |",
                  "|---|---------|------|----------|--------|"]
        for i, m in enumerate(state["squad"], 1):
            lines.append(f"| {i} | {m['symbol']} | {_fmt(m['quality_rank'], 'd')} "
                         f"| {m['since']} | {m['streak']} |")
    else:
        lines.append("_(leeg)_")
    lines += ["", "Transfers deze run:"]
    lines += [f"- {t['date']} · {t['symbol']}: {t['reason']}" for t in transfers] \
        or ["- geen"]
    lines += ["", "Bank:"]
    lines += [f"- {b['symbol']} — {b['streak']}/{b['needed']} kwartalen bewijs"
              + (f" · geblokkeerd door de fragiliteitspoort ({b['blocked']})"
                 if b.get("blocked") else "")
              for b in state["bench"]] or ["- leeg"]
    open_slots = state["slots"] - len(state["squad"])
    lines += ["", f"Open plekken: {open_slots} — liever cash dan een kandidaat "
                  f"zonder bewijs."]
    if state.get("fragility_gate"):
        lines += ["", "_Fragiliteitspoort AAN (--fragility-gate, INVERSION-DESIGN §6): een "
                      "Ruinous-verdict blokkeert toetreding. Standaard staat deze uit — de "
                      "v3-regels zijn walk-forward gevalideerd, deze laag niet._",
                  "", f"_Poortdekking: {formation.gate_coverage_line(state)}_"]
    return lines


def _unreadable_block(unreadable: list[dict]) -> list[str]:
    """The §5.5 honest-counting block for cache entries that could not be read: named,
    with their reason, never silently swallowed."""
    if not unreadable:
        return []
    return ["", "Onleesbare cache-entries (overgeslagen als niet-gecached):"] + [
        f"- {u['symbol']} — {u['reason']}" for u in unreadable]


def _inversion_line(graded: list[dict], skipped: list[dict] | None) -> list[str]:
    """One counting line for the inversion layer: how many graded names got a verdict, the
    verdict mix, and — grouped by reason — the names that had price data but no answer.

    A name with no price file at all is not counted as a failure: it is the documented
    norm (§7). A torn price file, a probe that raised, or a verdict that will not
    serialize IS counted with its reason, because each of those is a gap that could have
    been filled."""
    skipped = list(skipped or [])
    verdicts = Counter(verdict_of(r) for r in graded if inversion_of(r))
    if not verdicts and not skipped:
        return []
    lines = [""]
    if verdicts:
        lines.append(f"Inversielaag (INVERSION-DESIGN): {sum(verdicts.values())} van "
                     f"{len(graded)} gegradeerde namen kregen een verdict — "
                     + " · ".join(f"{v} {n}" for v, n in verdicts.most_common()))
    else:
        lines.append(f"Inversielaag (INVERSION-DESIGN): geen enkel verdict deze run — "
                     f"0 van {len(graded)} gegradeerde namen.")
    if skipped:
        reasons = Counter(s["reason"] for s in skipped)
        lines.append(f"- namen met prijsdata maar zonder verdict: {len(skipped)} — "
                     + " · ".join(f"{r} ({n}×)" for r, n in reasons.most_common()))
        lines.append("  " + ", ".join(sorted(s["symbol"] for s in skipped)[:VETOED_LIST_MAX]))
    return lines


def render_report(doc: dict, transfers: list[dict], uncached: int,
                  formation_updated: bool, unreadable: list[dict] | None = None,
                  inversion_skipped: list[dict] | None = None) -> str:
    """The §5.5 report md from a §3.3 grades document (pure).

    Order matters here: the scorecard leads, because it is the number that means the same
    thing tomorrow (design §2). The percentile composite keeps its tier tables further
    down, explicitly labelled as sector-relative context — it is still the engine under
    the formation and the only validated ranking this system owns (design §6)."""
    unreadable = list(unreadable or [])
    scored = doc["names"]
    graded = [r for r in scored if r["grade"] in GRADE_LETTERS]
    grade_counts = Counter(r["grade"] for r in graded)
    bands = _band_counts(graded)
    lines = [
        f"# Stock Scout — run {doc['run_date']} ({doc['version']})", "",
        f"Universum {doc['universe']} · gegraded {doc['graded']} · veto "
        f"{doc['vetoed']} · insufficient {doc['insufficient']} · niet in cache {uncached}"
        f" · onleesbaar in cache {len(unreadable)}",
        "Banden: " + " · ".join(f"{b} {bands.get(b, 0)}" for b in BAND_ORDER)
        + (f" · {scorecard.NO_PRICE_BAND} {bands[scorecard.NO_PRICE_BAND]}"
           if bands.get(scorecard.NO_PRICE_BAND) else ""),
        "Rang in sector (context) — grades: "
        + " · ".join(f"{g} {grade_counts.get(g, 0)}" for g in GRADE_LETTERS),
        "",
    ]
    lines += _how_to_read(has_inversion(graded))
    lines += [""]
    lines += _veto_breakdown(scored)
    lines += _unreadable_block(unreadable)
    lines += _inversion_line(graded, inversion_skipped)
    lines += _scorecard_section(graded)
    lines += _fragile_section(graded)
    lines += _unbanded_section(scored, graded)
    lines += ["", "## Sectorrelatieve context (rang binnen sector)", "",
              "De percentielmotor: waar een naam staat tussen zijn sectorgenoten. Context, "
              "geen oordeel — en nog steeds de motor onder De Formatie en de enige "
              "walk-forward-gevalideerde rangschikking die dit systeem heeft."]
    for tier in TIERS:
        tier_names = sorted((r for r in graded if r["tier"] == tier),
                            key=lambda r: (-r["composite"], r["symbol"]))
        if not tier_names:
            continue
        lines += ["", f"### {tier} ({len(tier_names)})", ""]
        lines += _grade_table(tier_names)
    nl = [r for r in scored if str(r["symbol"]).endswith(".AS")]
    lines += ["", "## NL-namen", ""]
    lines += [_nl_line(r) for r in nl] or ["Geen NL-namen in deze run."]
    lines += [""]
    lines += _formation_section(doc.get("formation"), transfers, formation_updated)
    lines += ["", "---",
              "*Een grade is een research-shortlist, geen kooplijst — het model "
              "adviseert en monitort, het handelt nooit.*", ""]
    return "\n".join(lines)


def summary_head(report_md: str) -> str:
    """The md up to the first '## ' section — the --telegram message body (§5.5)."""
    return report_md.split("\n## ", 1)[0].strip()


def newest_datasheet(reports_dir: str | Path) -> Path | None:
    """Newest reports/datasheet-<date>.html by filename date, None when absent."""
    hits = sorted(p for p in Path(reports_dir).glob("datasheet-*.html")
                  if _DATASHEET_RE.match(p.name))
    return hits[-1] if hits else None


# ------------------------------------------------------------------------ the run

def run(*, universe_path: str | Path, cache_dir: str | Path, run_date: str,
        no_formation: bool, state_path: str | Path, reports_dir: str | Path,
        prices_dir: str | Path | None = None, fragility_gate: bool = False
        ) -> tuple[dict, Path, Path, list[dict]]:
    """§5.5 steps 1-6 -> (grades doc, md path, json path, unreadable cache entries).
    Formation state is read from and written back to `state_path` unless no_formation
    (then the existing state is embedded read-only, §3.3 formation key).

    `prices_dir` is the §3.6 weekly-grid directory the inversion layer needs. Without it —
    or without inversion.py, or for a name with no grid — the run is exactly the run it
    was before that layer existed: no verdict on the row, no fourth lens, no fragility
    column. `fragility_gate` hands INVERSION-DESIGN §6's optional gate to the formation;
    it is off by default and the v3 rules are unchanged when it is."""
    bundles, universe_n, uncached, unreadable = load_bundles(universe_path, cache_dir)
    scored = scoring.score_universe(bundles)
    bars, price_unreadable = load_price_bars(prices_dir,
                                             [b["symbol"] for b in bundles])

    by_symbol = {b["symbol"]: b for b in bundles}
    # A torn price file is not an unreadable CACHE entry — the name grades exactly as it
    # would have; only its verdict is missing. It is counted where a reader looks for it.
    inversion_skipped = [{"symbol": u["symbol"],
                          "reason": f"prijsbestand onleesbaar — {u['reason']}"}
                         for u in price_unreadable]
    for row in scored:                       # §4.8 shadow layers for every graded name
        graded = row["grade"] in GRADE_LETTERS
        bundle = by_symbol[row["symbol"]]
        row["mos"] = scoring.margin_of_safety(bundle) if graded else None
        row["buffett"] = scoring.buffett_checklist(bundle) if graded else None
        # Munger's lens, beside the points and never inside them (INVERSION-DESIGN §2).
        # A name with no weekly grid simply has no verdict — the ~470-name norm (§7).
        result, skip = (inversion_for(bundle, bars.get(row["symbol"]), row) if graded
                        else (None, None))
        if skip:
            inversion_skipped.append({"symbol": row["symbol"], "reason": skip})
        row["inversion"] = result
        # The Owner's Scorecard is built from THIS row, so the absolute card and the
        # percentile legs read one computation and can never disagree (§3.3).
        row["scorecard"] = (scorecard.scorecard(bundle, scored_row=row,
                                                inversion_result=result) if graded
                            else None)

    portfolio = scoring.build_portfolio(scored)

    if no_formation:
        state, transfers, updated = formation.load_state(state_path), [], False
    else:
        state, transfers = formation.update(formation.load_state(state_path),
                                            scored, run_date,
                                            fragility_gate=fragility_gate)
        formation.save_state(state, state_path)
        updated = True

    doc = {
        "run_date": run_date, "version": VERSION, "universe": universe_n,
        "graded": sum(r["grade"] in GRADE_LETTERS for r in scored),
        "vetoed": sum(r["grade"] == "VETOED" for r in scored),
        "insufficient": sum(r["grade"] == "INSUFFICIENT" for r in scored),
        "names": scored, "portfolio": portfolio, "formation": state,
    }
    report_md = render_report(doc, transfers, uncached, updated, unreadable,
                              inversion_skipped)

    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / f"scout-run-{run_date}.md"
    json_path = reports_dir / f"scout-grades-{run_date}.json"
    md_path.write_text(report_md, encoding="utf-8")
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False),
                         encoding="utf-8")
    return doc, md_path, json_path, unreadable


def iso_date(value: str) -> str:
    """argparse type for --date: a real calendar date in exactly YYYY-MM-DD.

    Anything else is rejected at parse time instead of poisoning the run: both
    discovery seams match on that literal shape (datasheet.newest_grades and
    newest_datasheet), so a report named e.g. 'scout-grades-30-07-2026.json' would be
    silently invisible, and formation.quarter_of would only blow up on the NEXT
    default-dated run, far from the typo."""
    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise argparse.ArgumentTypeError(
            f"--date must be YYYY-MM-DD (ISO), got {value!r}")
    try:
        date.fromisoformat(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--date {value!r} is not a real date: {e}") from e
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stock Scout grading run (spec §5.5)")
    ap.add_argument("--universe", default="universe.csv")
    ap.add_argument("--cache", default="cache", help="fundamentals cache dir (§3.2)")
    ap.add_argument("--date", default=None, type=iso_date,
                    help="run date YYYY-MM-DD (default: today)")
    ap.add_argument("--no-formation", action="store_true",
                    help="skip the v3 formation update (§5.6)")
    ap.add_argument("--prices", default=PRICES_DIR,
                    help="§3.6 weekly price grids for the inversion layer "
                         "(docs/INVERSION-DESIGN.md); absent dir = no verdicts")
    ap.add_argument("--fragility-gate", action="store_true",
                    help="INVERSION-DESIGN §6 (OFF by default): let a Ruinous verdict "
                         "block formation entry. The v3 rules are walk-forward "
                         "validated; this layer is not.")
    ap.add_argument("--telegram", action="store_true",
                    help="send the md summary head + newest datasheet via tg.py")
    args = ap.parse_args(argv)
    run_date = args.date or date.today().isoformat()

    doc, md_path, json_path, unreadable = run(
        universe_path=args.universe, cache_dir=args.cache, run_date=run_date,
        no_formation=args.no_formation, state_path=formation.STATE_FILE,
        reports_dir="reports", prices_dir=args.prices,
        fragility_gate=args.fragility_gate)

    print(f"graded {doc['graded']} · vetoed {doc['vetoed']} · insufficient "
          f"{doc['insufficient']} of universe {doc['universe']}")
    for u in unreadable:                     # never silent: the operator sees each one
        print(f"onleesbare cache-entry {u['symbol']}: {u['reason']}", file=sys.stderr)
    print(f"-> {md_path}\n-> {json_path}")
    if doc["formation"] is not None:
        print(formation.render(doc["formation"]))

    if args.telegram:
        head = summary_head(md_path.read_text(encoding="utf-8"))
        tg.send_message(html.escape(head))
        sheet = newest_datasheet(md_path.parent)
        if sheet is not None:
            tg.send_document(sheet, caption=f"Audit-datasheet {run_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
