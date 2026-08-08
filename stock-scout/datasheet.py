"""Audit datasheet (spec §5.7, chat msgs 11-13) — one self-contained HTML file.

Reads a reports/scout-grades-<date>.json (schema §3.3; default = newest in
reports/), optionally the cache dir (§3.2 — per-period statement-row evidence
+ fast_info snapshot; a missing cache entry degrades that name's evidence
sections, never the build), and the Stage-2 layer (§3.5 — the file matching
the run date, else the newest ≤ run date; msg 39). Emits an expandable card
per top-N graded name that LEADS with the Owner's Scorecard (the absolute,
anchored composite — docs/SCORECARD-DESIGN.md §5: headline pct/100 + band,
the four block bars, the "why" sentences, the consensus badge with per-lens
evidence and a coverage line naming every metric that was not computable and
why), then per metric the raw value, the floor→target ramp it was scored on
and the points earned — so a point can be audited exactly the way a
percentile already could. Below that the card keeps its whole existing
evidence chain: Stage-2 analysis, score build-up per leg (raw → sector-
percentiel met cohortgrootte → legscore), pijlers × gewichten → composite,
veto/straf-checks met werkelijke waarden, flags met uitleg, eigen EV vs
Yahoo-EV, owner-FCF per periode, de exact gematchte jaarrekening-regels,
fast_info, MoS-blok en de Buffett-checklist (msgs 17-19, 27, 33, 38-39).

The page's JS RE-DERIVES both composites (JSON island, zero external
requests, works from file://) and renders "✓ komt overeen" / "✗ afwijking"
per card: the percentile composite from the embedded legs + weights +
penalty (msg 13), and the scorecard from the embedded per-metric points —
block sums, available maximum, total, plus each metric's own §2 ramp. A
scorecard the reader cannot verify is no better than the number it replaces.
Inline CSS/JS only; light + dark via prefers-color-scheme; "Alles
uitklappen" button; first card pre-opened.

Stdlib only apart from `scorecard.ANCHORS`, which is imported rather than
copied: it is the anchor TABLE (label, floor, target, points, unit,
provenance), not the computation under audit. Every number on the page still
comes from the grades JSON, and the re-derivation still happens in the
page's own JS — the anchors only say which line each point was earned
against, and a metric id the table does not know degrades to its stored
detail string instead of failing the build.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

from scorecard import ANCHORS, BLOCKS, FULL_MAX, NO_PRICE_BAND, NOISE_FLOOR, VETOED_BAND

# Composite weights + neutral-G, mirrored from the scoring layer (spec §4.6;
# vendored grader W_V..W_M / NEUTRAL_G). Duplicated BY DESIGN: the datasheet
# must audit the run without importing the code under audit.
W_COMPOSITE = {"v": 0.25, "q": 0.25, "g": 0.20, "d": 0.15, "m": 0.15}
W_QUALITY = {"q": 0.40, "g": 0.25, "d": 0.20, "m": 0.15}   # v3 engine B (§4.7)
NEUTRAL_G = 50.0
RECHECK_TOLERANCE = 0.05          # legs are stored rounded; §4.6 composite rounds to 4

# Veto/penalty reference lines (spec §4.4) — shown next to the actual values.
LEVERAGE_VETO = 4.0
CASH_QUALITY_VETO = 0.25
DILUTION_VETO_PCT = 20.0
DILUTION_PENALTY_PCT = 5.0
DILUTION_PENALTY = -15

LEG_ORDER = ("v_yield", "q_roic", "q_gm", "q_ofcf_margin", "g_revenue", "g_ps_ofcf",
             "d_net_debt", "d_self_funding", "d_sbc", "m_shares", "m_accruals")
LEG_LABELS = {
    "v_yield": "Owner-FCF-yield (eigen EV)",
    "q_roic": "ROIC (Greenblatt)",
    "q_gm": "Brutomarge niveau × stabiliteit",
    "q_ofcf_margin": "Owner-FCF-marge (TTM)",
    "g_revenue": "Omzet-CAGR (jaarbasis)",
    "g_ps_ofcf": "Owner-FCF/aandeel-CAGR (jaarbasis)",
    "d_net_debt": "Nettoschuld/EBITDA (TTM)",
    "d_self_funding": "Zelffinancierend (owner-FCF > 0)",
    "d_sbc": "SBC/omzet (TTM)",
    "m_shares": "Aandelentrend %/jr",
    "m_accruals": "Accrual-divergentie (incl. NCI)",
}
PILLAR_LABELS = {"v": "V · Waardering", "q": "Q · Kwaliteit", "g": "G · Groei",
                 "d": "D · Degelijkheid", "m": "M · Management"}
# The scorecard's four blocks (design §2) in their scoring order, with the NL heading and
# the question each block answers. Maxima come from scorecard.BLOCKS, never from here.
BLOCK_LABELS = (
    ("quality", "Kwaliteit", "Wil ik deze onderneming bezitten?"),
    ("price", "Prijs", "Betaal ik een faire prijs?"),
    ("safety", "Veiligheid", "Kan dit permanent stuklopen?"),
    ("stewardship", "Rentmeesterschap", "Staat het management aan mijn kant?"),
)
LENS_LABELS = {"scorecard": "Scorecard", "margin_of_safety": "DCF-veiligheidsmarge",
               "buffett": "Buffett-checklist", "survival": "Overleving (inversielaag)"}

# --- the inversion layer (docs/INVERSION-DESIGN.md) ---------------------------------------
# NL labels for the §3 probes. A probe id this table does not know renders under its own id
# rather than being dropped: the layer owns its probe set, this page only shows it.
# Keyed on the probe ids inversion.PROBES actually emits — nothing else. A key the layer
# never produces is not a harmless spare: it hides the one id that IS wrong (§3.3 shipped
# as "owner_fcf_drawdown" here while the layer calls it "cash_engine", so the probe §3.3
# calls "the one that matters most to an owner" was the only unlabelled row on the page).
PROBE_LABELS = {
    "price_drawdown": "Ruïne al aangetoond — koersdrawdown (§3.1)",
    "return_asymmetry": "Rendementsasymmetrie — scheefheid & staartverhouding (§3.2)",
    "cash_engine": "De kasmotor breekt — owner-FCF-drawdown (§3.3)",
    "stress": "Gedrag onder stress — 2020 en 2022 (§3.4)",
    "predictability": "Voorspelbaarheid — Munger's eigen filter (§3.5)",
    "financing": "Financieringsfragiliteit — herfinancieringsmuur & verwatering (§3.6)",
    "concentration": "Concentratie — alleen een vlag (§3.7)",
}
# §3 severities. "unknown"/absent is its own state and is NEVER rendered as "none": the
# whole point of §7 is that thin evidence is said out loud instead of read as safety.
SEVERITY_LABELS = {"severe": "ernstig", "caution": "let op", "none": "geen",
                   "unknown": "niet gemeten", "not_scored": "niet gemeten",
                   "unmeasured": "niet gemeten"}
UNMEASURED_SEVERITIES = {"unknown", "not_scored", "unmeasured", "", "none_measured"}
# Verdict -> chip class. Unknown deliberately gets the neutral chip, not the calm one.
VERDICT_CLASS = {"ruinous": "sev", "fragile": "sev", "ordinary": "mid", "robust": "calm"}
# NL renderers per scorecard unit, one per ANCHORS[*]["unit"]. Presentation lives here (the
# scorecard's own sentences are English); the datasheet shows MORE precision than the
# report on purpose — this is the surface on which the ramp arithmetic gets checked by hand.
UNIT_RENDER = {
    "pct": lambda v: f"{v:.2f}%",
    "pct_of_revenue": lambda v: f"{v:.2f}% van omzet",
    "pct_per_year": lambda v: f"{v:+.2f}%/jr",
    "yield_pct": lambda v: f"{100.0 * v:.2f}%",
    "mos_pct": lambda v: f"{100.0 * v:+.1f}%",
    "ratio": lambda v: f"{v:.3f}",
    "share_of_periods": lambda v: f"{100.0 * v:.0f}% van de jaarperioden",
}
# Optional §3.3 ev.yahoo_source (absent in older grades JSON -> the neutral label).
EV_SOURCE_LABELS = {"field": "Yahoo-EV (fast_info)",
                    "derived": "Referentie-EV (afgeleid: koers × aandelen + schuld − kas)"}
FLAG_EXPLAIN = {   # v2.1/v2.2 flag glossary (spec §4.5, msg 19)
    "EV_GAP": "Eigen EV (mcap + schuld − kas) wijkt >15% af van Yahoo's enterpriseValue; "
              "de yield rekent op de eigen EV.",
    "SHARE_CLASS": "Share-class/Up-C-structuur (NCI >10% én EV-gat >15%): aandelentrend-leg "
                   "telt neutraal (50), dilutiestraf uit.",
    "FLOAT_ROIC": "Vooruitontvangen omzet >30% van omzet: ROIC is float-gedreven — "
                  "niet op face value lezen.",
    "LOW_BASE": "Basisjaar-owner-FCF <2% van omzet: OFCF/aandeel-CAGR-leg vervalt "
                "(lage-basis-vloer).",
    "ROIC_CAPPED": "Kapitaalbasis ≤ 0: ROIC afgekapt op 1000%.",
    "REINVESTOR": "Owner-FCF elke periode negatief, maar gespaard als herinvesteerder "
                  "(ROIC >15% én omzetgroei >10%/jr).",
}

# Row-label fallback chains (spec §4.1) — the evidence tables show which label matched.
INCOME_CHAINS = (
    ("Omzet", ("Total Revenue", "Operating Revenue")),
    ("EBITDA", ("EBITDA", "Normalized EBITDA")),
    ("EBIT", ("EBIT", "Operating Income")),
    ("Nettowinst", ("Net Income",)),
    ("Nettowinst incl. NCI", ("Net Income Including Noncontrolling Interests",
                              "Net Income Continuous Operations", "Net Income")),
    ("Brutowinst", ("Gross Profit",)),
    ("Bedrijfsresultaat", ("Operating Income", "EBIT")),
)
BALANCE_CHAINS = (
    ("Totale schuld", ("Total Debt",)),
    ("Kas", ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")),
    ("Werkkapitaal", ("Working Capital",)),
    ("Totale activa", ("Total Assets",)),
    ("Vlottende activa", ("Current Assets",)),
    ("Kortlopende verplichtingen", ("Current Liabilities",)),
    ("Eigen vermogen", ("Stockholders Equity", "Common Stock Equity")),
    ("Minderheidsbelang (NCI)", ("Minority Interest",)),
    ("Vooruitontvangen omzet", ("Current Deferred Revenue", "Deferred Revenue")),
)
CASHFLOW_CHAINS = (
    ("Operationele kasstroom", ("Operating Cash Flow",)),
    ("CapEx", ("Capital Expenditure",)),
    ("SBC", ("Stock Based Compensation",)),
    ("D&A", ("Depreciation And Amortization", "Depreciation Amortization Depletion")),
)
CREDIT_LOSS_LABELS = ("Provision For Doubtful Accounts", "Provisionand Write Offof Assets",
                      "Change In Loss Reserves", "Provision For Loan Lease And Other Losses",
                      "Allowance For Funds Used During Construction")

_STAGE2_RE = re.compile(r"^stage2-(\d{4}-\d{2}-\d{2})\.json$")
_GRADES_RE = re.compile(r"^scout-grades-(\d{4}-\d{2}-\d{2})\.json$")


# ---------------------------------------------------------------- input resolution

def newest_grades(reports_dir: Path) -> Path | None:
    """Newest reports/scout-grades-<date>.json by filename date (the §5.7 default)."""
    hits = sorted(p for p in Path(reports_dir).glob("scout-grades-*.json")
                  if _GRADES_RE.match(p.name))
    return hits[-1] if hits else None


def find_stage2(data_dir: Path, run_date: str) -> Path | None:
    """Stage-2 file per §3.5: data/stage2-<run_date>.json, else the NEWEST file whose
    date is ≤ run_date (msg 39: 'de datasheet pikt automatisch het stage2-bestand van
    de rundatum op ... oude blijven bewaard'). None when nothing qualifies."""
    data_dir = Path(data_dir)
    exact = data_dir / f"stage2-{run_date}.json"
    if exact.is_file():
        return exact
    best = None
    for p in data_dir.glob("stage2-*.json"):
        m = _STAGE2_RE.match(p.name)
        if m and m.group(1) <= run_date and (best is None or m.group(1) > best[0]):
            best = (m.group(1), p)
    return best[1] if best else None


def load_cache_entry(cache_dir: Path | None, symbol: str) -> dict | None:
    """cache/<SYMBOL>.json per §3.2 (dots kept, '/' → '-'); None on absent/corrupt —
    the card then degrades its evidence sections per-name (task contract)."""
    if cache_dir is None:
        return None
    path = Path(cache_dir) / f"{symbol.replace('/', '-')}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- evidence derivations

def owner_fcf_rows(cashflow: dict) -> list[dict]:
    """Per-period normalized owner-FCF build-up (§4.2, vendored grader lines 34-76):
    OCF − min(|CapEx|, D&A) − SBC; D&A absent → maintenance proxy = |CapEx|. Periods
    missing OCF or CapEx keep a row with ofcf None (shown as '—', never dropped
    silently). Newest first."""
    rows = []
    for pe in sorted(cashflow or {}, reverse=True):
        cell = cashflow[pe]
        ocf = cell.get("Operating Cash Flow")
        capex = cell.get("Capital Expenditure")
        da = cell.get("Depreciation And Amortization")
        if da is None:
            da = cell.get("Depreciation Amortization Depletion")
        sbc = cell.get("Stock Based Compensation") or 0.0
        if ocf is None or capex is None:
            rows.append({"period": pe, "ocf": ocf, "capex": capex, "da": da,
                         "maint": None, "sbc": sbc, "ofcf": None})
            continue
        maint = min(abs(capex), da) if da is not None else abs(capex)
        rows.append({"period": pe, "ocf": ocf, "capex": capex, "da": da,
                     "maint": maint, "sbc": sbc, "ofcf": ocf - maint - sbc})
    return rows


def cash_quality(entry: dict | None, ttm: dict | None) -> dict | None:
    """Actual value behind the cash-flow-quality veto (§4.4 item 2): credit-loss /
    write-off add-backs vs positive TTM OCF, on the run's TTM basis (§4.2 — newest
    4 quarters when basis 'quarterly', else the newest annual period). None without
    usable cache data."""
    if not entry:
        return None
    basis = (ttm or {}).get("basis")
    q_cf = (entry.get("quarterly") or {}).get("cashflow") or {}
    if basis == "quarterly" and q_cf:
        cf, periods = q_cf, sorted(q_cf, reverse=True)[:4]
    else:
        cf = (entry.get("annual") or {}).get("cashflow") or {}
        periods = sorted(cf, reverse=True)[:1]
    if not periods:
        return None
    ocf = addbacks = 0.0
    seen = False
    for pe in periods:
        cell = cf[pe]
        o = cell.get("Operating Cash Flow")
        if o is not None:
            ocf += o
            seen = True
        for lbl in CREDIT_LOSS_LABELS:
            v = cell.get(lbl)
            if v is not None:
                addbacks += v
    if not seen:
        return None
    return {"addbacks": addbacks, "ocf": ocf,
            "pct": (addbacks / ocf) if ocf > 0 else None}


def matched_label(payloads: dict, chain: tuple) -> str | None:
    """First label in the §4.1 fallback chain present (non-null) in any period."""
    for label in chain:
        for pe in payloads:
            if payloads[pe].get(label) is not None:
                return label
    return None


# ---------------------------------------------------------------- formatting helpers

_e = lambda x: html.escape(str(x), quote=True)   # noqa: E731 — the one templating escape


def _money(x) -> str:
    if x is None:
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return _e(x)
    a = abs(x)
    if a >= 1e9:
        return f"{x / 1e9:.2f} mld"
    if a >= 1e6:
        return f"{x / 1e6:.1f} mln"
    if a >= 1e3:
        return f"{x / 1e3:.1f} k"
    return f"{x:.2f}"


def _num(x, dec: int = 1) -> str:
    return "—" if x is None else f"{float(x):.{dec}f}"


def _raw(x) -> str:
    """Generic raw-metric cell: bools as ja/nee, big magnitudes as money, small as-is."""
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "ja" if x else "nee"
    if isinstance(x, str):
        return _e(x)
    a = abs(float(x))
    if a >= 1e5:
        return _money(x)
    return f"{float(x):.4f}" if 0 < a < 1 else f"{float(x):.2f}"


def _pct(x, *, stored: str, signed: bool = False) -> str:
    """Percentage cell. `stored` names the unit the FIELD carries, per §3.3 — "percent"
    for values already in percent (`ev.gap_pct`) and "fraction" for fractions of 1
    (`mos.mos_pct`, `mos.growth`, `mos.wacc`). Never guessed from magnitude: a −0.8%
    EV gap and a +180% margin of safety are both ordinary values that a magnitude
    guess renders 100× off in opposite directions."""
    if stored not in ("percent", "fraction"):
        raise ValueError(f"stored must be 'percent' or 'fraction', got {stored!r}")
    if x is None:
        return "—"
    v = float(x) * 100.0 if stored == "fraction" else float(x)
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def _weight_formula(weights: dict) -> str:
    """'0.40·Q + 0.25·G + 0.20·D + 0.15·M' rendered FROM the weight constant, so the
    page can never advertise weights the constant no longer holds."""
    return " + ".join(f"{w:.2f}·{p.upper()}" for p, w in weights.items())


# ---------------------------------------------------------------- HTML fragments

_CSS = """
:root { --bg:#f5f6f8; --fg:#1a1e22; --card:#ffffff; --line:#d8dde3; --muted:#5c6670;
        --ok:#0a7a4f; --bad:#b3261e; --warn:#8a6d00; --chip:#e9edf2; --accent:#0a5c7a; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#101418; --fg:#e4e7ea; --card:#181e24; --line:#2c343c; --muted:#98a2ac;
          --ok:#4cc38a; --bad:#ff8177; --warn:#e0c36e; --chip:#232b33; --accent:#6db3d1; } }
* { box-sizing:border-box; }
body { margin:0; padding:1rem; background:var(--bg); color:var(--fg);
       font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
header, main, footer { max-width:1100px; margin:0 auto; }
h1 { font-size:1.35rem; margin:.2rem 0; }
h3 { font-size:.95rem; margin:.9rem 0 .25rem; }
.muted { color:var(--muted); }
button { background:var(--accent); color:#fff; border:0; border-radius:6px;
         padding:.45rem .9rem; font:inherit; cursor:pointer; margin:.6rem 0; }
.chip { display:inline-block; background:var(--chip); border-radius:10px;
        padding:.05rem .55rem; margin:.1rem .15rem; font-size:.85em; }
.ok { color:var(--ok); } .bad { color:var(--bad); } .flag { color:var(--warn); }
details.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
               margin:.6rem 0; }
details.card > summary { padding:.7rem .9rem; cursor:pointer; list-style:none; }
details.card > summary::-webkit-details-marker { display:none; }
details.card > summary:before { content:"\\25B8  "; color:var(--muted); }
details.card[open] > summary:before { content:"\\25BE  "; }
.cardbody { padding:0 .9rem .9rem; }
details.sec { border-top:1px dashed var(--line); padding:.35rem 0; }
details.sec > summary { cursor:pointer; color:var(--accent); }
.stage2 { border-left:3px solid var(--accent); background:var(--chip);
          padding:.5rem .8rem; border-radius:0 8px 8px 0; margin:.4rem 0 .6rem; }
.stage2 .verdict { font-weight:600; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; margin:.35rem 0; }
th, td { border:1px solid var(--line); padding:.25rem .55rem; text-align:right;
         white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
thead th { background:var(--chip); }
td.txt { text-align:left; white-space:normal; }
.recheck-ok { color:var(--ok); } .recheck-bad { color:var(--bad); font-weight:600; }
footer { margin-top:1.2rem; color:var(--muted); font-size:.85em; }
/* --- Owner's Scorecard (design par. 5) — the top block of every card --- */
.scorecard { border:1px solid var(--line); border-left:4px solid var(--accent);
             border-radius:0 8px 8px 0; padding:.55rem .8rem .7rem; margin:.5rem 0 .8rem; }
.sc-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:.5rem; }
.sc-score { font-size:1.6rem; font-weight:700; }
.sc-max { color:var(--muted); font-size:1rem; }
.sc-band { background:var(--accent); color:#fff; border-radius:10px;
           padding:.1rem .6rem; font-weight:600; font-size:.9em; }
.sc-band.noverdict { background:var(--warn); color:#1a1e22; }
.sc-why { margin:.35rem 0; }
.bar { display:block; width:150px; height:.55rem; background:var(--chip);
       border-radius:4px; overflow:hidden; }
.bar > i { display:block; height:100%; background:var(--accent); }
td.barcell { width:170px; }
.lens-yes { color:var(--ok); } .lens-no { color:var(--bad); } .lens-unknown { color:var(--muted); }
/* --- the inversion layer (docs/INVERSION-DESIGN.md) — BESIDE the points, never in them */
.inversion { border:1px solid var(--line); border-left:4px solid var(--warn);
             border-radius:0 8px 8px 0; padding:.55rem .8rem .7rem; margin:.5rem 0 .8rem; }
.iv-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:.5rem; }
.iv-verdict { border-radius:10px; padding:.1rem .6rem; font-weight:600; font-size:.9em;
              background:var(--chip); }
.iv-verdict.sev { background:var(--bad); color:#fff; }
.iv-verdict.mid { background:var(--warn); color:#1a1e22; }
.iv-verdict.calm { background:var(--ok); color:#fff; }
.sev-severe { color:var(--bad); font-weight:600; }
.sev-caution { color:var(--warn); }
.sev-none { color:var(--ok); }
.sev-unknown { color:var(--muted); }
"""

# The independent client-side recompute (msg 13): composite re-derived from the
# embedded legs + weights + penalty — genuinely recomputed, never a baked string.
# The scorecard gets the same treatment (design par. 5): block sums, available maximum,
# total AND every metric's own par. 2 ramp, all re-derived from the embedded per-metric
# points. The ramp check compares against the UNROUNDED ramp, so it can never disagree
# with the stored value merely over a rounding mode.
_JS = """
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("scout-data").textContent);

  function recomputeScorecard(sc) {
    var blocks = {}, total = 0, available = 0, offRamp = [];
    Object.keys(sc.metrics).forEach(function (id) {
      var m = sc.metrics[id];
      if (m.points === null || m.points === undefined) { return; }
      if (m.value !== null && m.value !== undefined && m.target !== m.floor) {
        var frac = (m.value - m.floor) / (m.target - m.floor);
        frac = Math.max(0, Math.min(1, frac));
        if (Math.abs(frac * m.max - m.points) > data.tolerance) { offRamp.push(id); }
      }
      blocks[m.block] = (blocks[m.block] || 0) + m.points;
      total += m.points;
      available += m.max;
    });
    return { blocks: blocks, total: total, available: available, offRamp: offRamp };
  }

  function checkScorecard(sc) {
    var re = recomputeScorecard(sc), problems = re.offRamp.slice();
    Object.keys(sc.blocks).forEach(function (b) {
      var got = re.blocks[b] || 0;
      if (Math.abs(got - sc.blocks[b].points) > data.tolerance) { problems.push(b); }
    });
    if (Math.abs(re.available - sc.available_max) > data.tolerance) {
      problems.push("beschikbaar maximum");
    }
    if (sc.score !== null && sc.score !== undefined &&
        Math.abs(re.total - sc.score) > data.tolerance) { problems.push("totaal"); }
    return { total: re.total, available: re.available, problems: problems };
  }

  function recomputeComposite(card, weights, neutralG) {
    var groups = { v: [], q: [], g: [], d: [], m: [] };
    Object.keys(card.legs).forEach(function (id) {
      var s = card.legs[id];
      if (s !== null && s !== undefined && groups.hasOwnProperty(id.charAt(0))) {
        groups[id.charAt(0)].push(s);
      }
    });
    var raw = 0;
    ["v", "q", "g", "d", "m"].forEach(function (p) {
      var legs = groups[p], pillar;
      if (legs.length) {
        pillar = legs.reduce(function (a, b) { return a + b; }, 0) / legs.length;
      } else if (p === "g") {
        pillar = neutralG;   /* dunne groeidata -> neutraal 50 (spec par. 4.3) */
      } else {
        pillar = card.pillars && card.pillars[p] != null ? card.pillars[p] : 0;
      }
      raw += weights[p] * pillar;
    });
    raw += card.penalty || 0;
    return Math.max(0, Math.min(100, raw));
  }

  data.cards.forEach(function (card) {
    var comp = recomputeComposite(card, data.weights, data.neutral_g);
    var match = Math.abs(comp - card.composite) <= data.tolerance;
    ["recheck-", "recheck2-"].forEach(function (prefix) {
      var el = document.getElementById(prefix + card.symbol);
      if (!el) { return; }
      if (match) {
        el.textContent = "\\u2713 komt overeen (herberekend " + comp.toFixed(2) + ")";
        el.className = "recheck-ok";
      } else {
        el.textContent = "\\u2717 afwijking (herberekend " + comp.toFixed(2) + ")";
        el.className = "recheck-bad";
      }
    });

    var el2 = document.getElementById("sc-recheck-" + card.symbol);
    if (!el2) { return; }
    if (!card.scorecard) {
      el2.textContent = "geen scorecard in deze grades-JSON";
      el2.className = "muted";
      return;
    }
    var check = checkScorecard(card.scorecard);
    var sums = "blokken + totaal " + check.total.toFixed(1) + "/" + check.available +
               " uit de punten per metriek";
    if (check.problems.length === 0) {
      el2.textContent = "\\u2713 komt overeen (" + sums + ")";
      el2.className = "recheck-ok";
    } else {
      el2.textContent = "\\u2717 afwijking (" + sums + "; wijkt af: " +
                        check.problems.join(", ") + ")";
      el2.className = "recheck-bad";
    }
  });

  var btn = document.getElementById("expand-all");
  var allOpen = false;
  btn.addEventListener("click", function () {
    allOpen = !allOpen;
    document.querySelectorAll("details").forEach(function (d) { d.open = allOpen; });
    btn.textContent = allOpen ? "Alles inklappen" : "Alles uitklappen";
  });
})();
"""


def _unit(metric_id: str, value) -> str:
    """One scorecard value in its own unit (design's units are NOT uniform, §3.3). An
    anchor id the table does not know renders as a plain number rather than crashing."""
    if value is None:
        return "—"
    unit = (ANCHORS.get(metric_id) or {}).get("unit")
    render = UNIT_RENDER.get(unit)
    return render(float(value)) if render else f"{float(value):.4g}"


def _ramp_text(metric_id: str) -> str:
    """'0 bij 5.00% · vol bij 25.00%' — the floor→target ramp the metric was scored on,
    rendered FROM scorecard.ANCHORS so the page can never advertise a line the scorecard
    no longer holds (design §3: the code is the source of truth)."""
    a = ANCHORS.get(metric_id)
    if not a:
        return "—"
    return (f"0 bij {_unit(metric_id, a['floor'])} · "
            f"vol bij {_unit(metric_id, a['target'])}")


def _sc_pts(value) -> str:
    return "—" if value is None else f"{float(value):g}"


def _scorecard_headline(card: dict) -> str:
    """§5's five-second headline. A numeric pct/100 verdict is printed ONLY for a real
    band: a VETOED card has no score to show (§4.3) and a NO PRICE card shows its points
    out of what was available with the disclaimer attached, never a verdict (§4.1)."""
    band = card.get("band") or "—"
    meaning = card.get("band_meaning") or ""
    pts = f"{_sc_pts(card.get('score'))}/{card.get('available_max', '?')} pt"
    if band == VETOED_BAND:
        head = ("<span class='sc-score bad'>—</span>"
                "<span class='sc-max'>score onderdrukt</span>")
        cls = "sc-band noverdict"
    elif band == NO_PRICE_BAND:
        head = f"<span class='sc-score'>{_e(pts)}</span>"
        cls = "sc-band noverdict"
    else:
        head = (f"<span class='sc-score'>{_e(card.get('pct'))}</span>"
                f"<span class='sc-max'>/100</span>")
        cls = "sc-band"
    return (f"<div class='sc-head'>{head}<span class='{cls}'>{_e(band)}</span></div>"
            f"<p class='muted'>{_e(meaning)}</p>")


def _sc_blocks_table(card: dict) -> str:
    """The four block bars (design §5). The denominator is the block's AVAILABLE maximum;
    when a metric dropped out the full block maximum is named next to it (§4.2)."""
    blocks = card.get("blocks") or {}
    rows = []
    for key, label, question in BLOCK_LABELS:
        b = blocks.get(key) or {}
        got, avail, full = b.get("points"), b.get("max") or 0, BLOCKS[key]
        share = (100.0 * got / avail) if (avail and got is not None) else 0.0
        short = (f" <span class='muted'>(van {full} — "
                 f"{full - avail} pt niet meetelbaar)</span>" if avail < full else "")
        rows.append(
            f"<tr><td>{_e(label)} <span class='muted'>{_e(question)}</span></td>"
            f"<td>{_sc_pts(got)}/{_e(avail)}{short}</td>"
            f"<td class='barcell'><span class='bar'><i style='width:{share:.0f}%'></i>"
            f"</span></td><td>{share:.0f}%</td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>Blok</th><th>Punten</th>"
            "<th></th><th>Aandeel</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def _sc_why(card: dict) -> str:
    why = card.get("why") or {}
    parts = [why.get(k) or {} for k in ("strongest", "weakest")]
    said = " · ".join(_e(p["sentence"]) for p in parts if p.get("sentence"))
    return f"<p class='sc-why'><b>Waarom:</b> {said}</p>" if said else ""


def _sc_consensus(card: dict) -> str:
    """§5 consensus: how many of three INDEPENDENT lenses call the name good, each with
    the evidence that decided it. Three-of-three is the signal, not the first place."""
    c = card.get("consensus") or {}
    if not c:
        return ""
    lenses, evidence = c.get("lenses") or {}, c.get("evidence") or {}
    items = []
    for lens, note in evidence.items():
        state = lenses.get(lens)
        mark, cls = ({True: ("✓", "lens-yes"), False: ("✗", "lens-no")}
                     .get(state, ("?", "lens-unknown")))
        items.append(f"<li><span class='{cls}'>{mark}</span> "
                     f"{_e(LENS_LABELS.get(lens, lens))} — {_e(note)}</li>")
    return (f"<p><span class='chip'>Consensus {_e(c.get('green'))}/{_e(c.get('of'))}"
            f"</span> {_e(c.get('label') or '')}</p><ul>{''.join(items)}</ul>")


def _sc_coverage(card: dict) -> str:
    """§4.2 made visible: what was NOT computable, worth how many points, and why."""
    cov = card.get("coverage") or {}
    missing = cov.get("missing") or []
    avail, full = cov.get("available_max"), cov.get("full_max", FULL_MAX)
    if not missing:
        return (f"<p class='muted'>Dekking: alle {len(cov.get('scored') or [])} metrieken "
                f"gescoord — {_e(avail)} van {_e(full)} punten beschikbaar.</p>")
    items = "".join(f"<li><b>{_e(m.get('label') or m.get('metric'))}</b> "
                    f"({_e(m.get('points'))} pt, blok {_e(m.get('block'))}) — "
                    f"{_e(m.get('reason') or 'geen reden vastgelegd')}</li>"
                    for m in missing)
    return (f"<p>Dekking: <b>{_e(avail)} van {_e(full)}</b> punten beschikbaar; "
            f"{len(missing)} metriek(en) niet meetelbaar — geen stille nul, een kleinere "
            f"noemer (§4.2):</p><ul>{items}</ul>")


def _sc_metrics_table(card: dict) -> str:
    """Every metric auditable the way a percentile already was: raw value in its own unit,
    the floor→target ramp it was scored on, and the points earned. Rows come from
    scorecard.ANCHORS (order, label, ramp, unit, provenance); values and points come from
    the run's grades JSON — the two are never mixed."""
    metrics = card.get("metrics") or {}
    ids = [m for m in ANCHORS if m in metrics] + [m for m in metrics if m not in ANCHORS]
    rows = []
    for mid in ids:
        m = metrics.get(mid) or {}
        anchor = ANCHORS.get(mid) or {}
        got = m.get("points")
        earned = ("<span class='muted'>—</span>" if got is None
                  else f"<b>{_sc_pts(got)}</b>/{_e(m.get('max', anchor.get('points', '?')))}")
        note = "" if got is not None else _e(m.get("detail") or "")
        rows.append(
            f"<tr title=\"{_e(anchor.get('provenance', ''))}\">"
            f"<td>{_e(anchor.get('label', mid))} <span class='muted'>{_e(mid)}</span></td>"
            f"<td>{_e(_unit(mid, m.get('value')))}</td>"
            f"<td class='txt'>{_e(_ramp_text(mid))}</td>"
            f"<td>{earned}</td>"
            f"<td>{_e(m['pct']) if m.get('pct') is not None else '—'}</td>"
            f"<td class='txt muted'>{note}</td></tr>")
    return ("<h3>Punten per metriek (absolute ankers)</h3><div class='scroll'><table>"
            "<thead><tr><th>Metriek</th><th>Waarde</th><th>Ramp (§2, lineair, geen "
            "klif)</th><th>Punten</th><th>%</th><th>Notitie</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def _scorecard_block(row: dict) -> str:
    """The Owner's Scorecard as the TOP block of the card (design §5) — the interpretable
    number first, its build-up under it, and an independent JS recheck at the bottom."""
    card = row.get("scorecard")
    head = "<h3>Owner's Scorecard — absolute punten</h3>"
    if not card:
        return (head + "<p class='muted'>Geen scorecard in deze grades-JSON (oudere run) "
                       "— de sectorrelatieve opbouw hieronder is volledig.</p>")
    sym = _e(row.get("symbol", ""))
    notes = "".join(f"<li>{_e(n)}</li>" for n in card.get("notes") or [])
    return (head + "<div class='scorecard'>"
            + _scorecard_headline(card)
            + _sc_blocks_table(card)
            + _sc_why(card)
            + _sc_consensus(card)
            + _sc_coverage(card)
            + f"<p class='muted'>Onafhankelijke hercheck (JS): <span id='sc-recheck-{sym}'"
              f" class='muted'>JavaScript vereist</span></p>"
            + (f"<details class='sec'><summary>Run-notities</summary><ul>{notes}</ul>"
               f"</details>" if notes else "")
            + "</div>" + _sc_metrics_table(card))


# ------------------------------------------- the inversion layer (INVERSION-DESIGN §5)

def _inversion_of(row: dict) -> dict | None:
    """The verdict attached to one §3.3 row. The scorecard's normalized projection is read
    first (its "verdict" key is guaranteed, §5), the raw row key second — a grades JSON
    written before this layer existed has neither and renders nothing at all."""
    card = (row.get("scorecard") or {}).get("inversion")
    for source in (card, row.get("inversion")):
        if isinstance(source, dict) and source:
            return source
    return None


def _iv_verdict(inv: dict) -> str:
    """The verdict as the layer worded it; a result that names none is Unknown, never
    blank (§4: "said out loud, never read as safe")."""
    return str(inv.get("verdict") or "Unknown")


def _iv_sentence(mode) -> str:
    """One failure mode as plain language (§4), whether the layer hands over the sentence
    or a probe record carrying one. Never a repr."""
    if isinstance(mode, dict):
        for key in ("sentence", "detail", "note", "reason", "label"):
            if mode.get(key):
                return str(mode[key])
        return ""
    return str(mode or "")


def _iv_probe_rows(probes) -> list[tuple[str, dict]]:
    """The probes as (id, record) pairs from either shape the layer may hand over: a
    {probe_id: record} map or a list of records carrying their own id."""
    if isinstance(probes, dict):
        return [(str(pid), p if isinstance(p, dict) else {"value": p})
                for pid, p in probes.items()]
    if isinstance(probes, (list, tuple)):
        out = []
        for i, p in enumerate(probes):
            p = p if isinstance(p, dict) else {"value": p}
            out.append((str(p.get("probe") or p.get("id") or p.get("name") or i), p))
        return out
    return []


def _iv_value(probe: dict) -> str:
    """One probe's measured value. The layer's own rendering wins when it supplied one;
    otherwise the raw number is shown at four significant digits — a drawdown of -0.716
    is printed as -0.716, not rounded into looking harmless."""
    for key in ("display", "text", "rendered"):
        if probe.get(key):
            return str(probe[key])
    value = probe.get("value", probe.get("raw"))
    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return f"{float(value):.4g}"


def _iv_severity(probe: dict) -> tuple[str, str]:
    """(label, css class) for one probe's §3 severity. An absent severity is 'niet gemeten'
    — the honest state — and never 'geen'.

    The producer's own COVERAGE BIT decides that, not the severity string. inversion.py
    returns severity "none" together with measured=False on purpose (a probe with no
    evidence must not invent a finding), so reading the severity alone paints every
    unmeasured probe green — and §3.7's concentration probe is unmeasured for ~89% of
    filers. A `measured` of False therefore wins over whatever severity rides with it."""
    if probe.get("measured") is False:
        return SEVERITY_LABELS["unmeasured"], "sev-unknown"
    raw = str(probe.get("severity") or "unknown").strip().lower()
    if raw in UNMEASURED_SEVERITIES:
        return SEVERITY_LABELS.get(raw, "niet gemeten"), "sev-unknown"
    return SEVERITY_LABELS.get(raw, raw), f"sev-{raw}"


def _iv_unmeasured(inv: dict) -> list[str]:
    """Which probes were NOT measured, by label AND by reason. Taken from whatever the
    layer named in its coverage block, else derived from the probes that report themselves
    unmeasured. §3.7 is the reason this exists at all: where the evidence is absent the
    page says so, because silence there is not safety.

    A coverage entry is a record, so the PROBE is named first and its reason follows. The
    layer keys those entries on "id" (and carries "label"/"section" of its own); listing
    the bare English reason — two near-identical "only 0 weekly return(s)" lines the reader
    cannot attribute to §3.1 or §3.2 — names the gap without naming what has the gap."""
    coverage = inv.get("coverage") or {}
    named = []
    for key in ("missing", "unmeasured", "not_scored", "absent"):
        for item in coverage.get(key) or []:
            if not isinstance(item, dict):
                named.append(PROBE_LABELS.get(str(item), str(item)))
                continue
            probe_id = item.get("id", item.get("probe", item.get("metric")))
            label = PROBE_LABELS.get(str(probe_id)) or item.get("label") or str(probe_id)
            if item.get("section") and not PROBE_LABELS.get(str(probe_id)):
                label = f"{label} (§{item['section']})"
            reason = _iv_sentence(item)
            named.append(f"{label} — {reason}" if reason and reason != label else label)
    if named:
        return named
    return [PROBE_LABELS.get(pid, pid) for pid, probe in _iv_probe_rows(inv.get("probes"))
            if probe.get("measured") is False
            or str(probe.get("severity") or "unknown").strip().lower()
            in UNMEASURED_SEVERITIES]


def _iv_coverage(inv: dict) -> str:
    """The coverage line: how many of the §3 COUNTING probes could be measured, and the
    NAME of every one that could not. A coverage block that counts without naming says so
    instead of implying the gap is unimportant.

    The keys read are the ones inversion.py writes — `measured_counting` of
    `counting_total`, plus `thin`/`required_missing`, which are what actually decide the
    collapse to Unknown. The older `scored`/`of`/`total` spellings stay as fallbacks for a
    result written by anything else; reading only those printed "dekking niet vastgelegd
    door de laag" over a layer that had recorded it, and blamed the layer for the gap."""
    coverage = inv.get("coverage") or {}
    scored = coverage.get("measured_counting", coverage.get("scored"))
    of = coverage.get("counting_total",
                      coverage.get("of", coverage.get("total")))
    unmeasured = _iv_unmeasured(inv)
    if isinstance(scored, (list, tuple)):
        scored = len(scored)
    counted = (f"<b>{_e(scored)} van {_e(of)}</b> tellende probes gemeten"
               if scored is not None and of is not None
               else "dekking niet vastgelegd door de laag")
    missing = [PROBE_LABELS.get(str(pid), str(pid))
               for pid in coverage.get("required_missing") or []]
    if missing:
        thin = (f"<p class='muted'>Zonder {_e(', '.join(missing))} kan dit oordeel niet "
                f"bevestigd worden — het verdict valt terug op Unknown (§4).</p>")
    elif coverage.get("thin"):
        thin = ("<p class='muted'>Te weinig gemeten probes om veiligheid te bevestigen — "
                "het verdict valt terug op Unknown (§4).</p>")
    else:
        thin = ""
    if unmeasured:
        items = "".join(f"<li>{_e(u)}</li>" for u in unmeasured)
        return (f"<p>Dekking: {counted} — niet gemeten, en daarom niet als veilig te "
                f"lezen (§3.7/§7):</p><ul>{items}</ul>{thin}")
    if scored is not None and of is not None and scored < of:
        return (f"<p>Dekking: {counted} — welke probes ontbreken is niet vastgelegd; "
                f"onbekend is niet hetzelfde als veilig (§7).</p>{thin}")
    return f"<p class='muted'>Dekking: {counted}.</p>{thin}"


def _iv_probe_table(inv: dict) -> str:
    """Every probe with its measured value and its §3 severity — the evidence under the
    verdict, so a fragility judgement is auditable the way a point already is."""
    rows = _iv_probe_rows(inv.get("probes"))
    if not rows:
        return ("<p class='muted'>Deze laag leverde geen probes bij dit verdict — alleen "
                "het verdict zelf.</p>")
    cells = []
    for pid, probe in rows:
        label, cls = _iv_severity(probe)
        note = _iv_sentence(probe)
        cells.append(
            f"<tr><td>{_e(PROBE_LABELS.get(pid, pid))} "
            f"<span class='muted'>{_e(pid)}</span></td>"
            f"<td>{_e(_iv_value(probe))}</td>"
            f"<td class='{cls}'>{_e(label)}</td>"
            f"<td class='txt muted'>{_e(note)}</td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>Probe</th><th>Waarde</th>"
            "<th>Ernst</th><th>Notitie</th></tr></thead><tbody>"
            + "".join(cells) + "</tbody></table></div>")


def _inversion_block(row: dict) -> str:
    """Munger's lens for one name (INVERSION-DESIGN §5): the verdict, the failure modes in
    plain language, every probe with its value and severity, and the coverage line naming
    what was not measured.

    It sits directly under the Owner's Scorecard and it moves not one point (§2): the two
    answer different questions — how good is this business, and how does it break — and a
    card that reconciled them would let a high score paper over fragility. A name with no
    verdict renders nothing: for the ~470 price-less names that is the norm, not a gap."""
    inv = _inversion_of(row)
    if not inv:
        return ""
    verdict = _iv_verdict(inv)
    cls = VERDICT_CLASS.get(verdict.strip().lower(), "")
    modes = [s for s in (_iv_sentence(m) for m in inv.get("failure_modes") or []) if s]
    if modes:
        modes_html = ("<p><b>Hoe dit je geld kost:</b></p><ul>"
                      + "".join(f"<li>{_e(m)}</li>" for m in modes) + "</ul>")
    elif verdict.strip().lower() == "unknown":
        modes_html = ("<p class='muted'>Te weinig bewijs om te zeggen hoe dit breekt. Dat "
                      "staat hier hardop en wordt niet als veilig gelezen (§4/§7).</p>")
    else:
        modes_html = "<p class='muted'>Geen faalmodus benoemd bij dit verdict.</p>"
    notes = "".join(f"<li>{_e(n)}</li>" for n in inv.get("notes") or [])
    return ("<h3>Inversie — hoe zou dit mijn geld verliezen?</h3>"
            "<div class='inversion'>"
            f"<div class='iv-head'><span class='iv-verdict {cls}'>{_e(verdict)}</span>"
            "<span class='muted'>staat NAAST de score en verschuift geen enkel punt "
            "(INVERSION-DESIGN §2)</span></div>"
            + modes_html + _iv_probe_table(inv) + _iv_coverage(inv)
            + (f"<details class='sec'><summary>Notities van de laag</summary>"
               f"<ul>{notes}</ul></details>" if notes else "")
            + "<p class='muted'>Deze laag onderdrukt niets en rangschikt niets: hij "
              "benoemt de faalmodus, de mens beslist. Wat hij niet ziet — rechtszaken, "
              "regelgeving, fraude die nog niet in de cijfers zit — blijft onzichtbaar "
              "(§7).</p>"
            "</div>")


def _anchor_reference() -> str:
    """The anchored metrics and where each ramp comes from (design §3 — 14 metrics, 28
    endpoints), rendered ONCE per page from scorecard.ANCHORS rather than per card: the
    provenance ledger the anti-complexity rule (HN2) demands, without 10× duplication."""
    rows = "".join(
        f"<tr><td>{_e(a['label'])} <span class='muted'>{_e(mid)}</span></td>"
        f"<td>{_e(a['block'])}</td><td>{_e(_unit(mid, a['floor']))}</td>"
        f"<td>{_e(_unit(mid, a['target']))}</td><td>{_e(a['points'])}</td>"
        f"<td class='txt'>{_e(a['provenance'])}</td></tr>"
        for mid, a in ANCHORS.items())
    return ("<details class='sec'><summary>De ankers en hun herkomst "
            f"(§3) — {len(ANCHORS)} metrieken, {FULL_MAX} punten</summary>"
            "<div class='scroll'><table><thead><tr><th>Metriek</th><th>Blok</th>"
            "<th>Vloer (0 pt)</th><th>Doel (vol)</th><th>Punten</th><th>Herkomst</th>"
            "</tr></thead><tbody>" + rows + "</tbody></table></div>"
            f"<p class='muted'>Verschillen onder {NOISE_FLOOR:.0f} punten zijn niet "
            f"betekenisvol (§4.4). {NO_PRICE_BAND} is een kwaliteitsprofiel, geen oordeel "
            f"(§4.1); een veto onderdrukt de score, het rangschikt niet (§4.3).</p>"
            "</details>")


def _stage2_block(analysis: dict | None) -> str:
    if not analysis:
        return ""
    src = []
    for s in analysis.get("sources") or []:
        title = _e(s.get("title") or "bron")
        url = s.get("url")
        src.append(f'<a href="{_e(url)}">{title}</a>' if url else title)
    sources = f'<div class="muted">Bronnen: {" · ".join(src)}</div>' if src else ""
    return (f'<div class="stage2"><span class="verdict">{_e(analysis.get("verdict", ""))}'
            f'</span> — Stage-2-analyse<p>{_e(analysis.get("analysis", ""))}</p>{sources}</div>')


def _legs_table(legs: dict) -> str:
    order = [k for k in LEG_ORDER if k in legs] + sorted(set(legs) - set(LEG_ORDER))
    rows = []
    for lid in order:
        leg = legs.get(lid) or {}
        pct = leg.get("percentile")
        cohort = f" (n={leg['cohort_n']})" if leg.get("cohort_n") is not None else ""
        rows.append(
            f"<tr><td>{_e(LEG_LABELS.get(lid, lid))} <span class='muted'>{_e(lid)}</span></td>"
            f"<td>{_raw(leg.get('raw'))}</td>"
            f"<td>{_num(pct)}{_e(cohort)}</td>"
            f"<td>{_num(leg.get('score'))}</td>"
            f"<td class='txt'>{_e(leg.get('note') or '')}</td></tr>")
    return ("<h3>Score-opbouw per leg <span class='muted'>— sectorrelatief, rang binnen "
            "sector, geen oordeel</span></h3><div class='scroll'><table><thead><tr>"
            "<th>Leg</th><th>Ruw</th><th>Sectorpercentiel</th><th>Legscore</th><th>Notitie</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def _pillar_table(row: dict) -> str:
    pillars = row.get("pillars") or {}
    penalty = (row.get("veto") or {}).get("penalty") or 0
    body, subtotal = [], 0.0
    for p in "vqgdm":
        val = pillars.get(p)
        w = W_COMPOSITE[p]
        contrib = None if val is None else w * val
        subtotal += contrib or 0.0
        body.append(f"<tr><td>{_e(PILLAR_LABELS[p])}</td><td>{_num(val)}</td>"
                    f"<td>{w:.2f}</td><td>{_num(contrib, 2)}</td></tr>")
    body.append(f"<tr><td>Subtotaal</td><td></td><td></td><td>{subtotal:.2f}</td></tr>")
    body.append(f"<tr><td>Straf (dilutie)</td><td></td><td></td><td>{penalty:+d}</td></tr>")
    body.append(f"<tr><th>Composite (run)</th><th></th><th></th>"
                f"<th>{_num(row.get('composite'), 2)}</th></tr>")
    body.append("<tr><td>Onafhankelijke hercheck (JS)</td><td colspan='3'>"
                f"<span id='recheck2-{_e(row.get('symbol', ''))}' class='muted'>"
                "JavaScript vereist</span></td></tr>")
    quality = row.get("quality_score")
    tail = (f"<p class='muted'>v3-kwaliteitsscore ({_e(_weight_formula(W_QUALITY))}): "
            f"{_num(quality)}</p>" if quality is not None else "")
    return ("<h3>Pijlers × gewichten → composite <span class='muted'>— context; nog "
            "steeds de motor onder De Formatie en de walk-forward-validatie</span></h3>"
            "<div class='scroll'><table><thead><tr>"
            "<th>Pijler</th><th>Score</th><th>Gewicht</th><th>Bijdrage</th></tr></thead>"
            "<tbody>" + "".join(body) + "</tbody></table></div>" + tail)


def _veto_table(row: dict, entry: dict | None) -> str:
    legs = row.get("legs") or {}
    veto = row.get("veto") or {}
    flags = {f.get("code") for f in row.get("flags") or []}
    penalty = veto.get("penalty") or 0
    nd = (legs.get("d_net_debt") or {}).get("raw")
    sh = (legs.get("m_shares") or {}).get("raw")
    cq = cash_quality(entry, row.get("ttm"))
    ofcf = [r["ofcf"] for r in owner_fcf_rows(((entry or {}).get("annual") or {})
                                              .get("cashflow") or {}) if r["ofcf"] is not None]
    neg = sum(1 for v in ofcf if v < 0)

    def _status(hit: bool, hit_txt: str) -> str:
        return f"<span class='bad'>{_e(hit_txt)}</span>" if hit else "<span class='ok'>OK</span>"

    if cq is None:
        cq_val, cq_hit = "geen cachegegevens", False
    elif cq["pct"] is None:
        cq_val, cq_hit = f"add-backs {_money(cq['addbacks'])} · OCF ≤ 0", False
    else:
        cq_val = (f"add-backs {_money(cq['addbacks'])} = {100 * cq['pct']:.1f}% "
                  f"van OCF {_money(cq['ocf'])}")
        cq_hit = cq["pct"] >= CASH_QUALITY_VETO
    if "SHARE_CLASS" in flags:
        dil_val, dil_stat = "leg neutraal (SHARE_CLASS)", "<span class='ok'>uit (SHARE_CLASS)</span>"
    else:
        dil_val = "—" if sh is None else f"aandelen {float(sh):+.1f}%/jr"
        dil_stat = _status(sh is not None and float(sh) > DILUTION_VETO_PCT, "VETO")
    destr_val = (f"owner-FCF negatief in {neg}/{len(ofcf)} jaren" if ofcf
                 else "geen cachegegevens")
    destr_stat = ("<span class='flag'>gespaard (REINVESTOR)</span>" if "REINVESTOR" in flags
                  else _status(bool(ofcf) and neg == len(ofcf), "VETO"))
    rows = [
        ("1. Leverage-veto", "—" if nd is None else f"nettoschuld/EBITDA = {float(nd):.2f}",
         f"&gt; {LEVERAGE_VETO:.0f}, of EBITDA ≤ 0 met nettoschuld",
         _status(nd is not None and float(nd) > LEVERAGE_VETO, "VETO")),
        ("2. Cashflow-kwaliteit-veto", cq_val,
         f"add-backs ≥ {100 * CASH_QUALITY_VETO:.0f}% van OCF", _status(cq_hit, "VETO")),
        ("3. Dilutie-veto", dil_val, f"&gt; {DILUTION_VETO_PCT:.0f}%/jr", dil_stat),
        ("4. Cash-destructie-veto", destr_val, "negatief in élke periode én TTM ≤ 0",
         destr_stat),
        ("5. Dilutiestraf", f"straf {penalty:+d}",
         f"{DILUTION_PENALTY_PCT:.0f}–{DILUTION_VETO_PCT:.0f}%/jr → {DILUTION_PENALTY}",
         f"<span class='flag'>{DILUTION_PENALTY} toegepast</span>" if penalty
         else "<span class='ok'>geen straf</span>"),
    ]
    body = "".join(f"<tr><td>{_e(n)}</td><td class='txt'>{v}</td>"
                   f"<td class='txt'>{t}</td><td>{s}</td></tr>" for n, v, t, s in rows)
    reason = veto.get("reason")
    note = f"<p class='muted'>Run-notitie: {_e(reason)}</p>" if reason else ""
    return ("<h3>Veto/straf-checks (werkelijke waarden)</h3><div class='scroll'>"
            "<table><thead><tr><th>Check</th><th>Werkelijke waarde</th><th>Drempel</th>"
            "<th>Uitkomst</th></tr></thead><tbody>" + body + "</tbody></table></div>" + note)


def _flags_block(row: dict) -> str:
    flags = row.get("flags") or []
    if not flags:
        return "<h3>Flags</h3><p class='muted'>Geen flags.</p>"
    items = "".join(
        f"<li><span class='flag'>{_e(f.get('code', ''))}</span> — {_e(f.get('message') or '')} "
        f"<span class='muted'>{_e(FLAG_EXPLAIN.get(f.get('code', ''), ''))}</span></li>"
        for f in flags)
    return f"<h3>Flags</h3><ul>{items}</ul>"


def _ev_block(row: dict) -> str:
    """Own EV vs the reference EV (§4.5). `ev.gap_pct` is stored in PERCENT (§3.3).
    `ev.yahoo_source` ("field" = Yahoo's own enterpriseValue, "derived" = reconstructed
    from price × shares + debt − cash) is optional: an older grades JSON without the key
    renders the neutral label."""
    ev = row.get("ev") or {}
    gap = ev.get("gap_pct")
    gap_txt = _pct(gap, stored="percent")
    cls = " class='flag'" if gap is not None and abs(float(gap)) > 15 else ""
    source = EV_SOURCE_LABELS.get(ev.get("yahoo_source"), "Yahoo-EV")
    return (f"<h3>Eigen EV vs Yahoo-EV</h3><p>Eigen EV (mcap + schuld − kas): "
            f"<b>{_money(ev.get('own'))}</b> · {_e(source)}: {_money(ev.get('yahoo'))} · "
            f"gat: <span{cls}>{_e(gap_txt)}</span></p>")


def _ofcf_table(entry: dict | None) -> str:
    head = "<h3>Owner-FCF per periode</h3>"
    if not entry:
        return head + "<p class='muted'>Geen cache-gegevens voor dit aandeel — bewijstabel overgeslagen.</p>"

    def table(cashflow: dict, title: str, limit: int) -> str:
        rows = owner_fcf_rows(cashflow)[:limit]
        if not rows:
            return ""
        body = "".join(
            f"<tr><td>{_e(r['period'])}</td><td>{_money(r['ocf'])}</td>"
            f"<td>{_money(r['capex'])}</td><td>{_money(r['da'])}</td>"
            f"<td>{_money(r['maint'])}</td><td>{_money(r['sbc'])}</td>"
            f"<td><b>{_money(r['ofcf'])}</b></td></tr>" for r in rows)
        return (f"<p class='muted'>{_e(title)} — OCF − min(|CapEx|, D&amp;A) − SBC</p>"
                "<div class='scroll'><table><thead><tr><th>Periode</th><th>OCF</th>"
                "<th>CapEx</th><th>D&amp;A</th><th>Onderhouds-proxy</th><th>SBC</th>"
                "<th>Owner-FCF</th></tr></thead><tbody>" + body + "</tbody></table></div>")

    out = table(((entry.get("annual") or {}).get("cashflow")) or {}, "Jaarbasis", 5)
    out += table(((entry.get("quarterly") or {}).get("cashflow")) or {},
                 "TTM-kwartalen (nieuwste 4)", 4)
    return head + (out or "<p class='muted'>Geen kasstroomregels in de cache.</p>")


def _stmt_tables(entry: dict | None) -> str:
    if not entry:
        return ("<details class='sec'><summary>Jaarrekening-regels (gematchte labels)</summary>"
                "<p class='muted'>Geen cache-gegevens voor dit aandeel.</p></details>")

    def one(payloads: dict, chains, extra_rows=()) -> str:
        if not payloads:
            return ""
        periods = sorted(payloads, reverse=True)[:5]
        rows = []
        for nl, chain in list(chains) + list(extra_rows):
            hit = matched_label(payloads, chain)
            shown = " → ".join(f"<b>{_e(c)} ✓</b>" if c == hit else
                               f"<span class='muted'>{_e(c)}</span>" for c in chain)
            cells = "".join(f"<td>{_money(payloads[pe].get(hit)) if hit else '—'}</td>"
                            for pe in periods)
            rows.append(f"<tr><td>{_e(nl)}</td><td class='txt'>{shown}</td>{cells}</tr>")
        heads = "".join(f"<th>{_e(pe)}</th>" for pe in periods)
        return ("<div class='scroll'><table><thead><tr><th>Grootheid</th>"
                f"<th>Labelketen (gematcht ✓)</th>{heads}</tr></thead><tbody>"
                + "".join(rows) + "</tbody></table></div>")

    def extras(payloads: dict, labels) -> list:
        return [(lbl, (lbl,)) for lbl in labels
                if any(payloads.get(pe, {}).get(lbl) is not None for pe in payloads)]

    parts = []
    for basis, title in (("annual", "Jaarbasis"), ("quarterly", "Kwartaalbasis")):
        stmts = entry.get(basis) or {}
        inc, bal, cf = (stmts.get(k) or {} for k in ("income", "balance", "cashflow"))
        if not (inc or bal or cf):
            continue
        blocks = [
            one(inc, INCOME_CHAINS),
            one(bal, BALANCE_CHAINS, extras(bal, ("Non Current Deferred Revenue",))),
            one(cf, CASHFLOW_CHAINS, extras(cf, CREDIT_LOSS_LABELS)),
        ]
        parts.append(f"<h3>{_e(title)}</h3>" + "".join(b for b in blocks if b))
    return ("<details class='sec'><summary>Jaarrekening-regels (gematchte labels)</summary>"
            + ("".join(parts) or "<p class='muted'>Geen statements in de cache.</p>")
            + "</details>")


def _fast_info_block(entry: dict | None) -> str:
    fi = (entry or {}).get("fast_info") or {}
    if not fi:
        return ("<details class='sec'><summary>fast_info-snapshot</summary>"
                "<p class='muted'>Geen cache-gegevens voor dit aandeel.</p></details>")
    rows = "".join(
        f"<tr><td>{_e(k)}</td><td>{_money(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1e5 else _e(v)}</td></tr>"
        for k, v in sorted(fi.items()))
    return ("<details class='sec'><summary>fast_info-snapshot</summary><div class='scroll'>"
            "<table><tbody>" + rows + "</tbody></table></div></details>")


def _mos_block(row: dict) -> str:
    mos = row.get("mos")
    head = "<h3>Veiligheidsmarge (schaduw-DCF, telt nooit mee in de score)</h3>"
    if not mos:
        return head + "<p class='muted'>Geen MoS berekend (basis-FCF ≤ 0 of data ontbreekt).</p>"
    pct = mos.get("mos_pct")
    cls = "ok" if (pct or 0) > 0 else "bad"
    return (head + "<div class='scroll'><table><tbody>"
            f"<tr><td>Basis-FCF (max(TTM, 0.85 × 3-jr gem.))</td><td>{_money(mos.get('base_fcf'))}</td></tr>"
            f"<tr><td>Groei (omzet-CAGR, afgekapt)</td>"
            f"<td>{_pct(mos.get('growth'), stored='fraction')}</td></tr>"
            f"<tr><td>Disconteringsvoet (cost of equity — owner-FCF is na rente)</td>"
            f"<td>{_pct(mos.get('discount_rate', mos.get('wacc')), stored='fraction')}</td></tr>"
            f"<tr><td>WACC (geklemd 6–20%, ter referentie — verdisconteert niets)</td>"
            f"<td>{_pct(mos.get('wacc'), stored='fraction')}</td></tr>"
            f"<tr><td>Intrinsieke waarde (3-traps DCF)</td><td>{_money(mos.get('intrinsic_value'))}</td></tr>"
            f"<tr><td>Marktkapitalisatie</td><td>{_money(mos.get('market_cap'))}</td></tr>"
            f"<tr><th>Margin of safety</th>"
            f"<th class='{cls}'>{_pct(pct, stored='fraction', signed=True)}</th></tr>"
            "</tbody></table></div>")


def _buffett_block(row: dict) -> str:
    b = row.get("buffett")
    head = "<h3>Buffett-checklist</h3>"
    if not b:
        return head + "<p class='muted'>Geen checklist berekend.</p>"
    items = "".join(
        f"<tr><td>{'<span class=ok>✓</span>' if it.get('pass') else '<span class=bad>✗</span>'}</td>"
        f"<td class='txt'>{_e(it.get('name', ''))}</td>"
        f"<td>{_e(it.get('points', 0))}/{_e(it.get('max', 0))}</td>"
        f"<td class='txt'>{_e(it.get('detail') or '')}</td></tr>"
        for it in b.get("items") or [])
    return (head + f"<p><b>{_e(b.get('score', 0))}/{_e(b.get('max', 13))}</b> punten</p>"
            "<div class='scroll'><table><thead><tr><th></th><th>Item</th><th>Punten</th>"
            "<th>Detail</th></tr></thead><tbody>" + items + "</tbody></table></div>")


def _card(rank: int, row: dict, entry: dict | None, stage2: dict | None,
          is_open: bool) -> str:
    sym = _e(row.get("symbol", ""))
    ttm = row.get("ttm") or {}
    ttm_txt = (f"TTM: {ttm.get('quarters', '?')} kwartalen t/m {ttm.get('through', '?')} "
               f"({ttm.get('basis', '?')})" if ttm else "")
    price = (entry or {}).get("price") or {}
    price_txt = (f" · koers {price.get('close')} {(entry or {}).get('currency', '')} "
                 f"({price.get('date', '')})" if price.get("close") is not None else "")
    flags = " ".join(f"<span class='chip flag'>{_e(f.get('code', ''))}</span>"
                     for f in row.get("flags") or [])
    mos = (row.get("mos") or {}).get("mos_pct")
    card = row.get("scorecard") or {}
    band = card.get("band")
    if not card:
        sc_chip = ""
    elif band in (VETOED_BAND, NO_PRICE_BAND):     # never a numeric verdict (§4.1/§4.3)
        sc_chip = (f"<span class='chip'><b>{_e(band)}</b> · {_sc_pts(card.get('score'))}/"
                   f"{_e(card.get('available_max'))} pt</span>")
    else:
        sc_chip = (f"<span class='chip'><b>{_e(card.get('pct'))}/100</b> · "
                   f"{_e(band)}</span>")
    cons = card.get("consensus") or {}
    cons_chip = (f"<span class='chip'>consensus {_e(cons.get('green'))}/"
                 f"{_e(cons.get('of'))}</span>" if cons else "")
    inv = _inversion_of(row)
    # The §5 pairing, visible before anything is expanded: a name can be Exceptional AND
    # Fragile, and the summary line must show both rather than only the flattering one.
    iv_chip = ("" if not inv else
               f"<span class='chip iv-verdict "
               f"{VERDICT_CLASS.get(_iv_verdict(inv).strip().lower(), '')}'>"
               f"fragiliteit: {_e(_iv_verdict(inv))}</span>")
    summary = (
        f"<b>{rank}. {sym}</b> — {_e(row.get('name', ''))} {sc_chip}{cons_chip}{iv_chip}"
        f"<span class='chip muted'>rang in sector: {_e(row.get('grade', ''))} "
        f"{_num(row.get('composite'))}</span>"
        f"<span class='chip'>{_e(row.get('tier', ''))}</span>"
        f"<span class='chip'>MoS {_pct(mos, stored='fraction', signed=True)}</span>{flags} "
        f"<span id='recheck-{sym}' class='muted'>hercheck: JavaScript vereist</span>")
    meta = (f"<p class='muted'>{_e(row.get('sector') or '')} · {_e(row.get('industry') or '')}"
            f" · {_e(ttm_txt)}{_e(price_txt)}</p>")
    body = (
        meta
        + _scorecard_block(row)
        + _inversion_block(row)
        + _stage2_block(stage2)
        + _legs_table(row.get("legs") or {})
        + _pillar_table(row)
        + _veto_table(row, entry)
        + _flags_block(row)
        + _ev_block(row)
        + _ofcf_table(entry)
        + _stmt_tables(entry)
        + _fast_info_block(entry)
        + _mos_block(row)
        + _buffett_block(row))
    return (f"<details class='card'{' open' if is_open else ''}><summary>{summary}</summary>"
            f"<div class='cardbody'>{body}</div></details>")


def _header(grades: dict, stage2_path: Path | None) -> str:
    names = grades.get("names") or []
    grade_counts = Counter(n.get("grade") for n in names)
    chips = "".join(f"<span class='chip'>{_e(g)} × {grade_counts[g]}</span>"
                    for g in ("A", "B", "C", "D", "F", "VETOED", "INSUFFICIENT")
                    if grade_counts.get(g))
    veto_counts = Counter(((n.get("veto") or {}).get("reason") or "onbekend").split(":")[0].strip()
                          for n in names if n.get("grade") == "VETOED")
    veto_txt = " · ".join(f"{_e(r)} × {c}" for r, c in veto_counts.most_common())
    veto_line = f"<p>Veto-verdeling: {veto_txt}</p>" if veto_txt else ""
    formation = grades.get("formation") or {}
    fline = ""
    if formation:
        squad = formation.get("squad") or []
        bench = formation.get("bench") or []
        slots = formation.get("slots", 15)
        transfers = [t for t in formation.get("transfers") or []
                     if t.get("date") == grades.get("run_date")]
        fline = (f"<p>De Formatie {_e(formation.get('quarter', ''))}: {len(squad)}/{_e(slots)} "
                 f"opgesteld · {len(bench)} op de bank · {len(transfers)} transfers deze run · "
                 f"{max(0, int(slots) - len(squad))} slots open (cash)</p>")
    s2 = (f" · Stage-2-laag: {_e(stage2_path.name)}" if stage2_path else "")
    bands = Counter((n.get("scorecard") or {}).get("band") for n in names
                    if n.get("scorecard"))
    band_chips = "".join(f"<span class='chip'>{_e(b)} × {c}</span>"
                         for b, c in bands.most_common())
    band_line = (f"<p>Banden (Owner's Scorecard): {band_chips}</p>" if band_chips else "")
    # Fragility occupancy, only when this run produced verdicts at all — a run without
    # price grids must render the header it has always rendered.
    verdicts = Counter(_iv_verdict(inv) for inv in
                       (_inversion_of(n) for n in names) if inv)
    iv_chips = "".join(f"<span class='chip'>{_e(v)} × {c}</span>"
                       for v, c in verdicts.most_common())
    iv_line = (f"<p>Fragiliteit (inversielaag, naast de score): {iv_chips}</p>"
               if iv_chips else "")
    return (
        "<header><h1>Stock Scout · audit-datasheet</h1>"
        f"<p class='muted'>Run {_e(grades.get('run_date', '?'))} · versie "
        f"{_e(grades.get('version', '?'))} · universum {_e(grades.get('universe', '?'))} · "
        f"gegradeerd {_e(grades.get('graded', '?'))} · veto {_e(grades.get('vetoed', '?'))} · "
        f"onvoldoende data {_e(grades.get('insufficient', '?'))}{s2}</p>"
        f"{band_line}{iv_line}<p class='muted'>Rang in sector (context) — {chips}</p>"
        f"{veto_line}{fline}"
        + _anchor_reference()
        + "<button id='expand-all' type='button'>Alles uitklappen</button></header>")


# ---------------------------------------------------------------- builder + CLI

def _island_scorecard(card: dict | None) -> dict | None:
    """The scorecard reduced to exactly what the page's JS needs to re-derive it: the
    stored per-metric points (the block sums and the total come from these) plus each
    metric's raw value and ramp endpoints (so the §2 ramp itself is re-checked too).
    Nothing derived is baked in — the totals travel only as the values to compare against."""
    if not card:
        return None
    return {
        "score": card.get("score"), "available_max": card.get("available_max"),
        "pct": card.get("pct"), "band": card.get("band"),
        "blocks": {b: {"points": (v or {}).get("points"), "max": (v or {}).get("max")}
                   for b, v in (card.get("blocks") or {}).items()},
        "metrics": {mid: {"points": m.get("points"), "max": m.get("max"),
                          "value": m.get("value"),
                          "block": (ANCHORS.get(mid) or {}).get("block"),
                          "floor": (ANCHORS.get(mid) or {}).get("floor"),
                          "target": (ANCHORS.get(mid) or {}).get("target")}
                    for mid, m in (card.get("metrics") or {}).items()},
    }


def build(grades_path: Path | str, *, cache_dir: Path | str | None = None,
          stage2_dir: Path | str | None = None, top: int = 10,
          out: Path | str | None = None) -> Path:
    """Assemble the datasheet HTML for the top-N graded names (§5.7) and write it.
    Returns the written path (default reports/datasheet-<run_date>.html next to the
    grades file)."""
    grades_path = Path(grades_path)
    grades = json.loads(grades_path.read_text(encoding="utf-8"))
    run_date = grades.get("run_date", "unknown")
    stage2_path = find_stage2(stage2_dir, run_date) if stage2_dir else None
    stage2 = (json.loads(stage2_path.read_text(encoding="utf-8"))
              if stage2_path else {})
    analyses = stage2.get("analyses") or {}

    ranked = sorted((n for n in grades.get("names") or []
                     if n.get("composite") is not None),
                    key=lambda n: n["composite"], reverse=True)[:top]
    cards = []
    for i, row in enumerate(ranked):
        entry = load_cache_entry(cache_dir, row.get("symbol", ""))
        cards.append(_card(i + 1, row, entry, analyses.get(row.get("symbol")), i == 0))

    island = {   # JSON island for the client-side recompute (msg 13)
        "weights": W_COMPOSITE, "neutral_g": NEUTRAL_G, "tolerance": RECHECK_TOLERANCE,
        "cards": [{"symbol": n.get("symbol"), "composite": n.get("composite"),
                   "penalty": (n.get("veto") or {}).get("penalty") or 0,
                   "legs": {lid: (leg or {}).get("score")
                            for lid, leg in (n.get("legs") or {}).items()},
                   "pillars": n.get("pillars") or {},
                   "scorecard": _island_scorecard(n.get("scorecard"))}
                  for n in ranked],
    }
    island_json = json.dumps(island, ensure_ascii=False).replace("</", "<\\/")

    doc = (
        "<!doctype html>\n<html lang='nl'>\n<head>\n<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        f"<title>Stock Scout — audit-datasheet {_e(run_date)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        + _header(grades, stage2_path)
        + "<main>" + "".join(cards) + "</main>"
        "<footer>Een grade is een research-shortlist, geen kooplijst — het model "
        "adviseert en monitort, het handelt nooit.</footer>\n"
        f"<script type=\"application/json\" id=\"scout-data\">{island_json}</script>\n"
        f"<script>{_JS}</script>\n</body>\n</html>\n")

    out = Path(out) if out else grades_path.parent / f"datasheet-{run_date}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stock Scout audit-datasheet (spec §5.7)")
    ap.add_argument("--grades", default=None,
                    help="grades JSON (§3.3); default: newest reports/scout-grades-*.json")
    ap.add_argument("--cache", default="cache", help="fundamentals cache dir (§3.2)")
    ap.add_argument("--stage2-dir", default="data", help="dir with stage2-<date>.json (§3.5)")
    ap.add_argument("--top", type=int, default=10, help="number of cards (default 10)")
    ap.add_argument("--out", default=None,
                    help="output HTML (default reports/datasheet-<run_date>.html)")
    args = ap.parse_args(argv)

    grades_path = Path(args.grades) if args.grades else newest_grades(Path("reports"))
    if grades_path is None or not grades_path.is_file():
        print("geen scout-grades-*.json gevonden (draai eerst grade.py)", file=sys.stderr)
        return 2
    cache_dir = Path(args.cache) if args.cache and Path(args.cache).is_dir() else None
    stage2_dir = Path(args.stage2_dir) if args.stage2_dir and Path(args.stage2_dir).is_dir() else None
    out = build(grades_path, cache_dir=cache_dir, stage2_dir=stage2_dir,
                top=args.top, out=args.out)
    print(f"datasheet: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
