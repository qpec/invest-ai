"""The desk site — Scout · Thesis · Monitor as one interactive page (owner-directed,
2026-08-03: "an interface for three parts … highly intuitive … filter possibilities and a
lot of metrics visible through drill down").

One generator, one output: `docs/index.html` at the repo root (GitHub Pages serves the
`docs/` folder), plus lazy detail shards under `docs/data/`. The page is a static,
dependency-free HTML file — hand-rolled CSS and JS, system fonts, no CDN — because the
repo's reports have always worked from a mail attachment or a strict CSP, and the site
keeps that property: the shards are an optimisation, and the page degrades honestly when
they cannot be fetched (file://, offline) rather than breaking.

The three tabs ARE the architecture, numbered the way the pipeline flows:

    1 · The Scout      the whole screened universe, filterable, drill-down per name
    2 · The Thesis Desk  the top 1%, the three-beat seam, any drafts in full
    3 · The Monitor    committed theses vs their own triggers, weekly

Two standing rules carried into the rendering, because a page is where they are easiest
to quietly break:

- **The two judgements stay in separate columns.** Scorecard band and inversion verdict
  are never merged, averaged or reconciled anywhere on the page — a name can be
  Exceptional and Fragile at once and the table shows exactly that.
- **Owner-only fields never reach the page.** Conviction and circle-of-competence are
  FR9 fields; the builder strips them if they ever appear in a source file, so a public
  site cannot leak a judgement that belongs to the Gate.

Metric provenance is first-class: every registry metric in the drill-down carries the
tier that produced it (`sec-export` / `edgar-live` / refined), because the enrichment
chain (enrich.py) means "where did this number come from" now has more than one answer.

    python webapp.py --sec-data <dir> --prices <dir> --enrich-cache <dir> \\
        --theses-dir <dir> --out-dir ../docs
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

import deskwork
import inversion  # noqa: F401 — build_rows runs it via picks
import picks
import pit
import scorecard
import scoring
import secsv
import thesis as thesis_mod

OWNER_ONLY_FIELDS = ("conviction", "circle_of_competence")
QUALITY_BANDS = ("Exceptional", "Strong", "Mixed", "Weak", "Pass")
SUPPRESSED_BANDS = (scorecard.VETOED_BAND, scorecard.NO_PRICE_BAND)
VERDICTS = ("Robust", "Ordinary", "Fragile", "Ruinous", "Unknown")

SRC_EXPORT = "sec-export"
SRC_EDGAR = "edgar-live"
SRC_REFINED = "refined"          # export value present, edgar-live changed the series


# --- Markdown, small and safe -------------------------------------------------------------

def md_html(text: str) -> str:
    """The subset of markdown the desk's own artifacts use — headings, bold, links,
    lists, tables, blockquotes — escaped FIRST so nothing in a source file can inject
    markup. Not a general renderer and not trying to be one."""
    out, lines = [], text.splitlines()
    i, in_ul, in_ol = 0, False, False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def inline(s: str) -> str:
        s = html.escape(s, quote=False)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

        # The URL goes into an ATTRIBUTE, so it gets its own quote-escaping pass —
        # quote=False above protects the prose, not the href.
        def link(match):
            href = html.escape(match.group(2), quote=True)
            return (f'<a href="{href}" target="_blank" rel="noopener">'
                    f'{match.group(1)}</a>')

        return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", link, s)

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("|") and i + 1 < len(lines) \
                and set(lines[i + 1].strip()) <= set("|-: "):
            close_lists()
            split_cells = lambda row: re.split(  # noqa: E731 — a pipe inside a
                r"\|(?=(?:[^`]*`[^`]*`)*[^`]*$)", row.strip().strip("|"))  # `code` span
            header = [inline(c.strip()) for c in split_cells(stripped)]
            out.append("<div class='tblwrap'><table><thead><tr>"
                       + "".join(f"<th>{c}</th>" for c in header) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [inline(c.strip()) for c in split_cells(lines[i])]
                out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</tbody></table></div>")
            continue
        if not stripped:
            close_lists()
            out.append("")          # paragraph break marker; stripped before joining
        elif stripped.startswith("#"):
            close_lists()
            level = min(len(stripped) - len(stripped.lstrip("#")), 4)
            out.append(f"<h{level + 1}>{inline(stripped.lstrip('#').strip())}"
                       f"</h{level + 1}>")
        elif stripped.startswith(("- ", "* ")):
            if not in_ul:
                close_lists()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            if not in_ol:
                close_lists()
                out.append("<ol>")
                in_ol = True
            cleaned = re.sub(r"^\d+\.\s*", "", stripped)
            out.append(f"<li>{inline(cleaned)}</li>")
        elif stripped.startswith("> "):
            close_lists()
            out.append(f"<blockquote>{inline(stripped[2:])}</blockquote>")
        elif stripped in ("---", "***"):
            close_lists()
            out.append("<hr>")
        elif (in_ul or in_ol) and out and out[-1].endswith("</li>"):
            # The desk's markdown is hard-wrapped at ~90 columns; a wrapped list item's
            # continuation line is part of the item, not a new paragraph.
            out[-1] = out[-1][:-len("</li>")] + " " + inline(stripped) + "</li>"
        else:
            # Ditto for paragraphs: consecutive plain lines are ONE paragraph, split
            # only by a blank line — otherwise every source line renders as its own <p>
            # and sentences arrive chopped mid-clause.
            if out and out[-1].endswith("</p>"):
                out[-1] = out[-1][:-len("</p>")] + " " + inline(stripped) + "</p>"
            else:
                out.append(f"<p>{inline(stripped)}</p>")
        i += 1
    close_lists()
    return "\n".join(part for part in out if part)


# --- Data assembly ------------------------------------------------------------------------

def _round(value, digits=2):
    return None if value is None else round(float(value), digits)


def registry_map(bundle: dict) -> dict[str, float | None]:
    evaluated = thesis_mod.registry_evaluate(bundle)
    return {name: thesis_mod.metric_value(name, bundle, evaluated)
            for name in thesis_mod.METRICS}


def provenance(pre: dict | None, post: dict) -> dict[str, str | None]:
    """Per registry metric, which tier produced the number the page shows. `pre` is the
    registry BEFORE tier 2 merged (None for names that were never enrichment targets)."""
    out = {}
    for name, value in post.items():
        if value is None:
            out[name] = None
        elif pre is None or pre.get(name) is not None and pre.get(name) == value:
            out[name] = SRC_EXPORT
        elif pre.get(name) is None:
            out[name] = SRC_EDGAR
        else:
            out[name] = SRC_REFINED
    return out


def trigger_eval(doc: dict, registry: dict) -> list[dict]:
    """A thesis draft's triggers against the CURRENT registry — the monitor's arithmetic,
    run once at build time so the page can show distance-to-trigger. Judgement triggers
    are shown as exactly what they are: questions the weekly agent answers."""
    rows = []
    for t in doc.get("triggers") or []:
        row = {"id": t.get("id"), "kind": t.get("kind"), "action": t.get("action"),
               "statement": t.get("statement"), "metric": t.get("metric"),
               "op": t.get("op"), "threshold": t.get("threshold"),
               "checks": t.get("consecutive_checks"), "question": t.get("question"),
               "current": None, "hit": None, "distance_pct": None}
        if t.get("kind") == "metric" and t.get("metric") in registry:
            current = registry.get(t["metric"])
            row["current"] = _round(current)
            if current is not None and isinstance(t.get("threshold"), (int, float)):
                op, thr = t["op"], t["threshold"]
                compare = {"<": current < thr, "<=": current <= thr,
                           ">": current > thr, ">=": current >= thr}.get(op)
                if compare is None:
                    # A refused draft can carry a malformed op — record keeps refusals
                    # on disk by design, and the site renders them as refusals rather
                    # than crashing the whole build on one bad file.
                    rows.append(row)
                    continue
                row["hit"] = compare
                # Safety margin, signed so that POSITIVE always means "away from the
                # line" whichever direction the trigger fires in; a zero threshold is
                # measured in the metric's own points (percent of zero is nonsense).
                raw = current - thr if op in ("<", "<=") else thr - current
                if abs(thr) > 1e-9:
                    row["distance_pct"] = _round(raw / abs(thr) * 100.0, 1)
                    row["margin_kind"] = "pct"
                else:
                    row["distance_pct"] = _round(raw, 1)
                    row["margin_kind"] = "points"
        rows.append(row)
    return rows


def strip_owner_fields(doc: dict) -> dict:
    """FR9 belt-and-braces: a draft can never carry these, but a committed thesis does —
    and the site must not publish them even when asked to render committed state."""
    return {k: v for k, v in doc.items() if k not in OWNER_ONLY_FIELDS}


PUBLIC_THESIS_FIELDS = (
    "business_model", "moat", "owner_earnings_picture", "valuation_anchor",
    "ten_year_statement", "bear_case", "sources",
)


def _finite_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def relative_percentile(value: float, values: list[float]) -> int:
    """Return the rounded midrank percentile, including ties symmetrically."""
    measured = [v for item in values if (v := _finite_number(item)) is not None]
    target = _finite_number(value)
    if target is None or not measured:
        raise ValueError("finite valuation cohort required")
    below = sum(item < target for item in measured)
    equal = sum(item == target for item in measured)
    return round(100 * (below + equal / 2) / len(measured))


def valuation_signal(percentile: int) -> str:
    if percentile >= 80:
        return "Appears inexpensive on current owner cash flow"
    if percentile >= 60:
        return "Looks somewhat inexpensive on current owner cash flow"
    if percentile >= 40:
        return "Sits near the middle on current owner cash flow"
    if percentile >= 20:
        return "Looks somewhat demanding on current owner cash flow"
    return "Appears demanding on current owner cash flow"


def public_valuation_lens(row: dict, detail: dict, rows: list[dict],
                          *, caveat: str) -> dict:
    """Build public valuation context from one point-in-time Scout measurement."""
    price = _finite_number(detail.get("px"))
    yield_pct = _finite_number((row.get("reg") or {}).get("owner_fcf_yield_pct"))
    price_as_of = detail.get("pxd")
    if price is None or not price_as_of:
        raise ValueError(f"{row.get('s')}: dated price required for valuation lens")
    if yield_pct is None or yield_pct <= 0:
        raise ValueError(f"{row.get('s')}: positive owner-cash yield required")
    sector = str(row.get("sec") or "").strip()
    sector_values = [
        (candidate.get("reg") or {}).get("owner_fcf_yield_pct")
        for candidate in rows if sector and candidate.get("sec") == sector
    ]
    sector_values = [v for v in sector_values if _finite_number(v) is not None]
    if len(sector_values) >= 20:
        values = sector_values
        scope, label = "sector", f"{sector} sector"
    else:
        values = [(candidate.get("reg") or {}).get("owner_fcf_yield_pct")
                  for candidate in rows]
        values = [v for v in values if _finite_number(v) is not None]
        scope, label = "universe", "measured Scout universe"
    percentile = relative_percentile(yield_pct, values)
    return {
        "price": round(price, 2), "price_as_of": str(price_as_of),
        "owner_cash_yield_pct": round(yield_pct, 2),
        "owner_cash_multiple_x": round(100 / yield_pct, 1),
        "comparison_scope": scope, "comparison_label": label,
        "comparison_count": len(values), "percentile": percentile,
        "signal": valuation_signal(percentile), "caveat": caveat.strip(),
    }


def public_portfolio_thesis(doc: dict, registry: dict,
                            *, next_run: str) -> dict:
    """Construct the public holding view from an allowlist, never by redaction."""
    body = doc.get("thesis") or {}
    public_body = {key: body.get(key) for key in PUBLIC_THESIS_FIELDS if key in body}
    triggers = trigger_eval({"triggers": body.get("triggers") or []}, registry)
    return {
        "symbol": doc.get("symbol"),
        "status": doc.get("status"),
        "version": doc.get("version"),
        "ratified_at": doc.get("ratified_at"),
        "last_monitored": doc.get("last_monitored"),
        "next_run": next_run,
        "target_weight": doc.get("target_weight"),
        "thesis": public_body,
        "trigger_state": doc.get("trigger_state") or {},
        "triggers": triggers,
    }


def public_thesis_reader(draft: dict, row: dict, detail: dict,
                         cohort_rows: list[dict] | None = None) -> dict:
    """Join one accepted draft to its two independent Scout judgements.

    This is a public allowlist projection: the reader never receives arbitrary
    top-level or thesis keys from an agent-authored record.
    """
    if not draft.get("accepted"):
        raise ValueError("accepted thesis required for public reader")
    symbol = str(row.get("s") or "")
    if draft.get("symbol") != symbol:
        raise ValueError("thesis symbol mismatch")
    if not row.get("top"):
        raise ValueError("Top 48 rank required for public reader")
    body = draft.get("thesis") or {}
    if not body.get("business_model"):
        raise ValueError(f"{symbol}: business model required for public reader")
    valuation = body.get("valuation_anchor") or {}
    if not valuation.get("statement"):
        raise ValueError(f"{symbol}: valuation statement required for public reader")
    public_body = {key: body.get(key) for key in PUBLIC_THESIS_FIELDS if key in body}
    why = (detail.get("card") or {}).get("why") or []
    if isinstance(why, dict):
        strongest = why.get("strongest") or {}
        quality_explanation = strongest.get("sentence") or ""
    elif isinstance(why, list):
        quality_explanation = str(why[0]) if why else ""
    else:
        quality_explanation = str(why) if why else ""
    failure_modes = (detail.get("inv") or {}).get("failure_modes") or []
    leading = next((mode.get("detail") for mode in failure_modes
                    if isinstance(mode, dict) and mode.get("severity") == "severe"
                    and mode.get("detail")), None)
    if leading is None:
        leading = next((mode.get("detail") for mode in failure_modes
                        if isinstance(mode, dict) and mode.get("detail")), "")
    reader = {
        "symbol": symbol, "name": row.get("n") or symbol,
        "rank": int(row["top"]),
        "quality": {"score": row.get("pct"), "grade": row.get("band"),
                    "explanation": quality_explanation},
        "risk": {"verdict": row.get("verdict"), "leading_fragility": leading},
        "thesis": public_body,
        "summary_html": draft.get("summary_html") or "",
        "report_html": draft.get("report_html") or "",
        "triggers": draft.get("triggers") or [],
    }
    if cohort_rows is not None:
        caveat = str(body.get("bear_case") or "").strip()
        if not caveat:
            caveat = ("This indication depends on current owner cash flow being "
                       "representative of normal earning power.")
        reader["valuation_lens"] = public_valuation_lens(
            row, detail, cohort_rows, caveat=caveat)
    return reader


def load_thesis_dir(theses_dir: Path, registry_by_symbol: dict) -> dict:
    """Everything the Thesis and Monitor tabs need from theses/: drafts in full (owner-
    field-stripped), committed statuses, evaluated triggers."""
    drafts = []
    if (theses_dir / "drafts").exists():
        for path in sorted((theses_dir / "drafts").iterdir()):
            record = path / "record.json"
            if not record.exists():
                continue
            doc = json.loads(record.read_text(encoding="utf-8"))
            body = strip_owner_fields(doc.get("thesis") or {})
            symbol = doc.get("symbol") or path.name
            summary = (path / "summary.md")
            report = (path / "report.md")
            drafts.append({
                "symbol": symbol,
                "built_at": doc.get("built_at"),
                "agent": doc.get("agent") or {},
                "accepted": not doc.get("validation_problems"),
                "thesis": body,
                "summary_html": md_html(summary.read_text(encoding="utf-8"))
                if summary.exists() else "",
                "report_html": md_html(report.read_text(encoding="utf-8"))
                if report.exists() else "",
                "packet": (doc.get("metrics_snapshot") or {}).get("metrics") or {},
                "triggers": trigger_eval(body, registry_by_symbol.get(symbol) or {}),
            })
    committed = []
    if (theses_dir / "committed").exists():
        for path in sorted((theses_dir / "committed").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            committed.append(public_portfolio_thesis(
                doc, registry_by_symbol.get(doc.get("symbol")) or {}, next_run=""))
    return {"drafts": drafts, "committed": committed}


def next_saturday(as_of: str) -> str:
    day = _dt.date.fromisoformat(as_of)
    return (day + _dt.timedelta(days=(5 - day.weekday()) % 7 or 7)).isoformat()


def assemble(*, sec_data: str, prices_dir: str | None, universe: str, as_of: str,
             enrich_cache: str | None, theses_dir: str | None, log=print) -> dict:
    """The whole site model: rows, details, charts, thesis, monitor — one dict."""
    meta = picks._load_meta(Path(universe))
    prices = picks._load_prices(Path(prices_dir) if prices_dir else None)
    log(f"facts: loading export ({sec_data}) …")
    facts = secsv.load_facts(sec_data)
    secsv.merge_tag_index(facts, sec_data)

    def build(symbol):
        return pit.as_of_bundle(facts[symbol], symbol, meta.get(symbol), as_of, prices)

    # Tier-2 enrichment (cache-first). Pre-enrichment registry is kept for the targets so
    # every number on the page can say which tier produced it.
    pre_registry: dict[str, dict] = {}
    enriched: dict[str, list] = {}
    vendor_display: dict[str, dict] = {}
    if enrich_cache and Path(enrich_cache).exists():
        import enrich
        try:
            vendor_display = enrich.load_vendor(Path(enrich_cache))
            cached = {p.name for p in Path(enrich_cache).glob("CIK*.json")}
            ciks = enrich.cik_map_cached(Path(enrich_cache))
        except Exception as error:  # noqa: BLE001 — enrichment is a bonus, never a gate
            log(f"enrichment unavailable ({type(error).__name__}: {error}) — "
                f"building on export facts only")
            enrich_cache = None
    bootstrap_bundles: list[dict] = []
    pending = 0
    if enrich_cache and Path(enrich_cache).exists():
        # Cache bootstrap (additive only, STREAMING): universe names the export never
        # carried become bundles straight from their cached companyfacts — one payload
        # in memory at a time, because thousands of parsed payloads (~370 KB resident
        # each) must never coexist with the export on the box. cache-only: a site
        # build needs zero network, and a name no refresh job has fetched yet stays
        # absent and is counted, not guessed. Every metric of a bootstrapped name is
        # edgar-live, which the all-None pre_registry makes the provenance labels say.
        missing = [s for s in meta if s not in facts]
        bootstrap_bundles, pending = enrich.bootstrap_bundles(
            missing, cache_dir=Path(enrich_cache), ciks=ciks, as_of=as_of,
            meta=meta, prices=prices, log=log)
        if bootstrap_bundles or pending:
            log(f"bootstrap: {len(bootstrap_bundles)} cache-only name(s) joined the "
                f"universe; {pending} awaiting their first refresh fetch")
        for bundle in bootstrap_bundles:
            pre_registry[bundle["symbol"]] = {name: None for name in thesis_mod.METRICS}
    if enrich_cache and Path(enrich_cache).exists():
        # Ticker-first, not CIK-first: share classes (FOX/FOXA) map two tickers onto one
        # CIK, and a cik->ticker dict would keep only the dict-race winner and silently
        # un-enrich the other. Every ticker in the export with a cached payload gets the
        # merge; two classes of one filer share the same facts, which is correct.
        # (Bootstrapped names never enter `facts`, so this targets export names only.)
        symbols = sorted(t for t, c in ciks.items()
                         if t in facts and f"CIK{c:010d}.json" in cached)
        log(f"enrichment: tier 2 from cache for {len(symbols)} name(s)")
        for symbol in symbols:
            bundle = build(symbol)
            if bundle is not None:
                pre_registry[symbol] = registry_map(bundle)
        enriched = enrich.enrich_payloads(facts, symbols,
                                          cache_dir=Path(enrich_cache), ciks=ciks)

    log("rows: scoring + scorecard + inversion over the universe …")
    bundles = ([b for b in (build(s) for s in sorted(facts)) if b is not None]
               + bootstrap_bundles)
    rows = picks.build_rows(bundles, prices=prices, meta=meta)
    by_symbol = {row["symbol"]: row for row in rows}
    bundle_by_symbol = {b["symbol"]: b for b in bundles}
    scored = {row["symbol"]: row for row in scoring.score_universe(bundles)}

    pick_set = {r["symbol"] for r in picks.shortlist(rows)}
    top_rows = thesis_mod.top_symbols(
        [{"symbol": r["symbol"], "card": r["card"]} for r in rows], len(rows))
    top_rank = {r["symbol"]: i + 1 for i, r in enumerate(top_rows)}

    import registry as registry_mod
    registry_by_symbol, prov_by_symbol, composites_by_symbol = {}, {}, {}
    for bundle in bundles:
        symbol = bundle["symbol"]
        registry_by_symbol[symbol] = registry_map(bundle)
        prov_by_symbol[symbol] = provenance(pre_registry.get(symbol),
                                            registry_by_symbol[symbol])
        composites_by_symbol[symbol] = registry_mod.composites(bundle)

    compact, details = [], {}
    rank_order = sorted(rows, key=lambda r: (
        0 if r["card"].get("pct") is not None else 1,
        scorecard.rank_key(r["card"]) if r["card"].get("pct") is not None else 0))
    rank_index = {r["symbol"]: i for i, r in enumerate(rank_order)}
    for row in rows:
        symbol = row["symbol"]
        card, inv = row["card"], row["inversion"]
        registry = registry_by_symbol.get(symbol, {})
        coverage = inv.get("coverage") or {}
        srow = scored.get(symbol) or {}
        bundle = bundle_by_symbol.get(symbol) or {}
        compact.append({
            "s": symbol, "n": row.get("name") or "", "sec": row.get("sector") or "",
            "mc": _round(bundle.get("market_cap"), 0),
            "pct": card.get("pct"), "band": card.get("band"),
            "ev": card.get("evidence"), "verdict": inv.get("verdict"),
            "sev": coverage.get("severe", 0), "cau": coverage.get("caution", 0),
            "pick": symbol in pick_set, "top": top_rank.get(symbol),
            "rk": rank_index.get(symbol, 10 ** 6), "grade": srow.get("grade"),
            "reg": {k: _round(v) for k, v in registry.items()},
        })
        probes = {pid: {x: probe.get(x) for x in
                        ("severity", "measured", "value", "detail", "provenance")}
                  for pid, probe in (inv.get("probes") or {}).items()}
        details[symbol] = {
            "card": {k: card.get(k) for k in
                     ("score", "available_max", "pct", "band", "band_meaning",
                      "evidence", "blocks", "metrics", "why")},
            "inv": {"verdict": inv.get("verdict"),
                    "verdict_meaning": inv.get("verdict_meaning"),
                    "verdict_rule": inv.get("verdict_rule"),
                    "failure_modes": inv.get("failure_modes"),
                    "coverage": coverage, "probes": probes},
            "scored": {k: srow.get(k) for k in
                       ("grade", "flags", "veto", "ev", "ttm", "note")},
            "reg": {k: {"v": _round(v), "src": prov_by_symbol.get(symbol, {}).get(k)}
                    for k, v in registry.items()},
            "vendor": {k: v for k, v in (vendor_display.get(symbol) or {}).items()
                       if registry.get(k) is None},
            "composites": composites_by_symbol.get(symbol),
            "mc": _round(bundle.get("market_cap"), 0),
            "shb": bundle.get("shares_basis"), "shn": bundle.get("shares_note"),
            "shd": bundle.get("shares_as_of"),
            "px": _round(bundle.get("price"), 2),
            "pxd": bundle.get("price_as_of"), "pxa": bundle.get("price_age_days"),
            "pxn": bundle.get("price_note"),
        }

    # Charts. Coverage before/after is measured across the ENRICHED names only, and the
    # chart says so — a delta across names tier 2 never touched would flatter the chain.
    bands = [{"label": b, "count": sum(1 for c in compact if c["band"] == b)}
             for b in QUALITY_BANDS + SUPPRESSED_BANDS]
    verdicts = [{"label": v, "count": sum(1 for c in compact if c["verdict"] == v)}
                for v in VERDICTS]
    cov = []
    if pre_registry:
        for name in thesis_mod.METRICS:
            before = sum(1 for s in pre_registry
                         if pre_registry[s].get(name) is not None)
            after = sum(1 for s in pre_registry
                        if registry_by_symbol.get(s, {}).get(name) is not None)
            cov.append({"metric": name, "before": before, "after": after})

    theses = load_thesis_dir(Path(theses_dir), registry_by_symbol) \
        if theses_dir and Path(theses_dir).exists() else {"drafts": [], "committed": []}
    drafts_by_symbol = {d["symbol"]: d for d in theses["drafts"]}
    compact_by_symbol = {row["s"]: row for row in compact}
    top_list = [{"rank": top_rank[r["symbol"]], "sym": r["symbol"],
                 "name": by_symbol[r["symbol"]].get("name") or "",
                 "band": r["card"].get("band"), "pct": r["card"].get("pct"),
                 "status": ("draft accepted" if drafts_by_symbol.get(
                     r["symbol"], {}).get("accepted")
                     else "draft refused" if r["symbol"] in drafts_by_symbol
                     else "no work order yet")}
                for r in top_rows]
    readers = [public_thesis_reader(
        drafts_by_symbol[r["symbol"]], compact_by_symbol[r["symbol"]],
        details[r["symbol"]], compact)
        for r in top_rows if r["symbol"] in drafts_by_symbol
        and drafts_by_symbol[r["symbol"]].get("accepted")]

    # Coverage is stated, not implied: a universe bigger than what has been fetched is
    # the normal state while the nightly sweep converges, and a page that showed only
    # the scored names would quietly read as "this is everything".
    universe_size = len(meta) or len(bundles)
    source = (f"SEC filings · {len(bundles)} filers scored"
              + (f" of {universe_size} in the universe" if universe_size > len(bundles)
                 else "")
              + (f" · {len(bootstrap_bundles)} from live EDGAR" if bootstrap_bundles
                 else "")
              + (f" · {pending} awaiting first fetch" if pending else "")
              + f" · prices for {len(prices)} names")
    return {
        "as_of": as_of,
        "generated": _dt.date.today().isoformat(),
        "source": source,
        "counts": {"screened": len(compact), "picks": len(pick_set),
                   "top": len(top_rows), "drafts": len(theses["drafts"]),
                   "committed": len(theses["committed"]),
                   "enriched": len(pre_registry),
                   "universe": universe_size,
                   "bootstrapped": len(bootstrap_bundles), "pending": pending,
                   "enriched_filled": sum(1 for s in enriched.values() if s)},
        "rows": compact, "details": details,
        "charts": {"bands": bands, "verdicts": verdicts, "coverage": cov},
        "units": {k: v[1] for k, v in thesis_mod.METRICS.items()},
        "thesis": {"top": top_list, "drafts": theses["drafts"], "readers": readers},
        "portfolio_monitor": {
            "committed": [dict(item, next_run=next_saturday(as_of))
                          for item in theses["committed"]],
            "next_run": next_saturday(as_of),
            "preview": theses["drafts"][0] if theses["drafts"] else None,
        },
        "snapshot_id": f"legacy-{as_of}",
    }


# --- Rendering ----------------------------------------------------------------------------
# The CSS implements the reference design language researched 2026-08-03: Linear's
# 4-step dark surface ladder with border-only elevation, Tabler's card-table and cool-gray
# light page, shadcn's token pairs and sortable headers, Tremor's pill/KPI anatomy. Chart
# colors are the validated dataviz reference palette (see docs/plans notes), NOT the UI
# accent — series identity and UI chrome are different jobs.

CSS = r"""
:root{
  --page:#f6f7f9; --surface:#ffffff; --raised:#f3f4f6; --overlay:#ffffff;
  --border:#e4e6eb; --hair:#eceef1;
  --text:#16181d; --text2:#5f636b; --faint:#9095a0;
  --accent:#2563eb; --accent-tint:rgba(37,99,235,.08);
  --good:#0a7a0a; --warn:#8a5d00; --serious:#a04a20; --crit:#b32d2d;
  --good-bg:rgba(12,163,12,.12); --warn-bg:rgba(250,178,25,.16);
  --serious-bg:rgba(236,131,90,.15); --crit-bg:rgba(208,59,59,.12);
  --chart-1:#2a78d6; --chart-2:#eb6834;
  --ord-1:#1c5cab; --ord-2:#2a78d6; --ord-3:#5598e7; --ord-4:#6da7ec; --ord-5:#86b6ef;
  --shadow:0 1px 2px rgba(16,24,40,.06);
  --mono:ui-monospace,'SF Mono','Cascadia Mono','Segoe UI Mono',Menlo,Consolas,monospace;
  color-scheme:light;
}
:root[data-theme="dark"]{
  --page:#0b0c0e; --surface:#15171b; --raised:#1d2025; --overlay:#22252b;
  --border:rgba(255,255,255,.09); --hair:rgba(255,255,255,.06);
  --text:#ededf0; --text2:#9ba0a8; --faint:#6e7178;
  --accent:#3b82f6; --accent-tint:rgba(59,130,246,.12);
  --good:#34d399; --warn:#fbbf24; --serious:#ec835a; --crit:#f87171;
  --good-bg:rgba(52,211,153,.14); --warn-bg:rgba(251,191,36,.14);
  --serious-bg:rgba(236,131,90,.16); --crit-bg:rgba(248,113,113,.14);
  --chart-1:#3987e5; --chart-2:#d95926;
  --ord-1:#3987e5; --ord-2:#2a78d6; --ord-3:#256abf; --ord-4:#1c5cab; --ord-5:#184f95;
  --shadow:none;
  color-scheme:dark;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --page:#0b0c0e; --surface:#15171b; --raised:#1d2025; --overlay:#22252b;
    --border:rgba(255,255,255,.09); --hair:rgba(255,255,255,.06);
    --text:#ededf0; --text2:#9ba0a8; --faint:#6e7178;
    --accent:#3b82f6; --accent-tint:rgba(59,130,246,.12);
    --good:#34d399; --warn:#fbbf24; --serious:#ec835a; --crit:#f87171;
    --good-bg:rgba(52,211,153,.14); --warn-bg:rgba(251,191,36,.14);
    --serious-bg:rgba(236,131,90,.16); --crit-bg:rgba(248,113,113,.14);
    --chart-1:#3987e5; --chart-2:#d95926;
    --ord-1:#3987e5; --ord-2:#2a78d6; --ord-3:#256abf; --ord-4:#1c5cab; --ord-5:#184f95;
    --shadow:none;
    color-scheme:dark;
  }
}
*{box-sizing:border-box;min-width:0}
@media (prefers-reduced-motion:reduce){*{transition:none !important}}
html{scrollbar-gutter:stable}
body{margin:0;background:var(--page);color:var(--text);
  font:400 14px/1.55 system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
code{font-family:var(--mono);font-size:.92em;background:var(--raised);
  padding:1px 5px;border-radius:4px}
.num,td.r,.kpi b{font-variant-numeric:tabular-nums}
.wrap{max-width:1280px;margin:0 auto;padding:0 20px 64px}

/* ---- header + stepper -------------------------------------------------- */
header.top{position:sticky;top:0;z-index:30;background:var(--page);
  border-bottom:1px solid var(--border)}
.masthead{display:flex;align-items:center;gap:14px;padding:12px 20px 8px;
  max-width:1280px;margin:0 auto}
.masthead h1{font-size:15px;font-weight:600;margin:0;letter-spacing:.01em}
.demobar{padding:7px 20px;font-size:12px;background:var(--accent);color:#fff;
  display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.demobar b{font-weight:600}
.demobar a{color:#fff;text-decoration:underline}
.notice{padding:5px 20px;font-size:11.5px;color:var(--text2);
  border-top:1px solid var(--border);background:var(--page)}
.notice b{color:var(--text)}
.masthead .sub{color:var(--text2);font-size:12px}
.masthead .right{margin-left:auto;display:flex;gap:8px;align-items:center}
.btn{border:1px solid var(--border);background:var(--surface);color:var(--text2);
  border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer}
.btn:hover{background:var(--raised);color:var(--text)}
/* --- desk actions: live under `webapp.py --serve`, inert on the published site --- */
.desk{margin:14px 0 4px;padding:10px 12px;border:1px solid var(--border);
  border-radius:8px;background:var(--page)}
.desk h4{margin:0 0 7px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--text2);font-weight:600}
.desk .acts{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.act{border:1px solid var(--border);background:var(--surface);color:var(--text);
  border-radius:6px;padding:5px 11px;font:inherit;font-size:12px;cursor:pointer}
.act:hover:not([disabled]){background:var(--raised);border-color:var(--accent)}
.act[disabled]{opacity:.45;cursor:not-allowed}
.act.busy{opacity:.7;cursor:progress}
.desk .why{margin-top:7px;font-size:11.5px;color:var(--text2);line-height:1.55}
.desk .why code{font-size:11px}
.desklog{margin-top:9px;max-height:230px;overflow:auto;background:var(--surface);
  border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-size:11.5px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;
  line-height:1.5;color:var(--text2)}
.desklog b{color:var(--text)}
.desklog .bad{color:var(--crit)}
.edit textarea{width:100%;box-sizing:border-box;min-height:90px;resize:vertical;
  background:var(--surface);color:var(--text);border:1px solid var(--border);
  border-radius:6px;padding:8px 10px;font:inherit;font-size:12.5px;line-height:1.55}
.edit textarea.code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:11.5px;min-height:260px}
.edit .row{display:flex;gap:8px;align-items:center;margin-top:7px;flex-wrap:wrap}
.edit .msg{font-size:11.5px;color:var(--text2)}
.edit .msg.bad{color:var(--crit)}
.edit .msg.good{color:var(--good)}
.stepper{display:flex;align-items:stretch;gap:0;max-width:1280px;margin:0 auto;
  padding:0 12px;overflow-x:auto}
.step{display:flex;align-items:center;gap:10px;padding:10px 14px 12px;cursor:pointer;
  border:0;background:none;color:var(--text2);position:relative;white-space:nowrap;
  font:inherit;text-align:left;flex-shrink:0}
.step .circ{width:24px;height:24px;border-radius:50%;border:1.5px solid var(--border);
  display:inline-flex;align-items:center;justify-content:center;font-size:12px;
  font-weight:600;font-variant-numeric:tabular-nums;color:var(--text2);flex:none}
.step .lbl{font-size:13px;font-weight:600;color:var(--text2)}
.step .cnt{display:block;font-size:11px;color:var(--faint);font-weight:400}
.step.active{color:var(--text)}
.step.active .circ{background:var(--accent);border-color:var(--accent);color:#fff}
.step.active .lbl{color:var(--text)}
.step.active::after{content:"";position:absolute;left:14px;right:14px;bottom:0;
  height:2px;background:var(--accent);border-radius:2px}
.chev{align-self:center;color:var(--faint);padding:0 2px;flex:none}

/* ---- cards + KPIs ------------------------------------------------------- */
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  box-shadow:var(--shadow);margin-top:16px;overflow:hidden}
/* an open filter menu must escape the card's corner-clipping, or a heavily filtered
   (short) card would cut the menu off at its own edge */
.card:has(details.dd[open]){overflow:visible}
.card>.hd{display:flex;align-items:center;gap:10px;padding:12px 16px;
  border-bottom:1px solid var(--hair);flex-wrap:wrap}
.card>.hd h2{font-size:13px;font-weight:600;margin:0}
.card>.hd .muted{color:var(--text2);font-size:12px}
.card>.bd{padding:14px 16px}
.card>.ft{padding:8px 16px;border-top:1px solid var(--hair);color:var(--text2);
  font-size:12px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
  margin-top:16px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:10px 14px;box-shadow:var(--shadow)}
.kpi label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--text2);font-weight:600}
.kpi b{font-size:24px;font-weight:600}
.kpi .d{font-size:11px;color:var(--faint)}
.intro{color:var(--text2);font-size:13px;margin:14px 2px 0;max-width:70em}

/* ---- pills -------------------------------------------------------------- */
.pill{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;
  padding:2px 8px;border-radius:999px;white-space:nowrap}
.pill .dot{width:7px;height:7px;border-radius:50%;flex:none}
.p-good{background:var(--good-bg);color:var(--good)}
.p-warn{background:var(--warn-bg);color:var(--warn)}
.p-serious{background:var(--serious-bg);color:var(--serious)}
.p-crit{background:var(--crit-bg);color:var(--crit)}
.p-quiet{background:var(--raised);color:var(--text2)}
.p-ghost{background:none;border:1px dashed var(--border);color:var(--faint)}
.p-acc{background:var(--accent-tint);color:var(--accent)}
.src{font-size:10px;border-radius:4px;padding:0 5px;border:1px solid var(--border);
  color:var(--faint);white-space:nowrap}
.src.edgar{color:var(--accent);border-color:var(--accent);opacity:.9}
.src.refined{color:var(--serious);border-color:var(--serious);opacity:.9}
.src.vendor{color:var(--warn);border-color:var(--warn);opacity:.9}

/* ---- filter toolbar ------------------------------------------------------ */
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-left:auto}
.search{position:relative}
.search input{background:var(--raised);border:1px solid var(--border);color:var(--text);
  border-radius:6px;padding:5px 10px 5px 28px;font-size:13px;width:220px}
.search::before{content:"⌕";position:absolute;left:9px;top:3px;color:var(--faint);
  font-size:15px}
details.dd{position:relative}
details.dd>summary{list-style:none;cursor:pointer;border:1px solid var(--border);
  background:var(--surface);border-radius:6px;padding:4px 10px;font-size:12px;
  color:var(--text2);display:inline-flex;gap:6px;align-items:center;user-select:none}
details.dd>summary::-webkit-details-marker{display:none}
details.dd[open]>summary{border-color:var(--accent);color:var(--text)}
details.dd .badge{background:var(--accent);color:#fff;border-radius:999px;font-size:10px;
  padding:0 6px;font-weight:600}
details.dd>.menu{position:absolute;z-index:40;top:calc(100% + 6px);left:0;
  background:var(--overlay);border:1px solid var(--border);border-radius:8px;
  min-width:190px;padding:6px;box-shadow:0 8px 24px rgba(0,0,0,.18);max-height:300px;
  overflow:auto}
.menu label{display:flex;gap:8px;align-items:center;font-size:12.5px;padding:5px 8px;
  border-radius:6px;cursor:pointer;color:var(--text)}
.menu label:hover{background:var(--raised)}
.chips{display:flex;gap:6px;flex-wrap:wrap;padding:8px 16px 0}
.chip{display:inline-flex;gap:6px;align-items:center;border:1px solid var(--border);
  background:var(--raised);border-radius:6px;font-size:12px;padding:2px 8px;
  color:var(--text2)}
.chip button{all:unset;cursor:pointer;color:var(--faint);font-size:13px;line-height:1}
.chip button:hover{color:var(--crit)}
table.data th button:focus-visible,.chip button:focus-visible,
.linkbtn:focus-visible,table.data tbody tr:focus-visible{
  outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}
.linkbtn{all:unset;cursor:pointer;color:var(--accent);font-size:12px}
.linkbtn:hover{text-decoration:underline}
label.tog{display:inline-flex;gap:6px;align-items:center;font-size:12px;
  color:var(--text2);cursor:pointer;border:1px solid var(--border);border-radius:6px;
  padding:4px 10px;background:var(--surface)}
label.tog:has(input:checked){border-color:var(--good);color:var(--good)}
label.tog input{accent-color:var(--good)}

/* ---- table --------------------------------------------------------------- */
.tscroll{max-height:70vh;overflow:auto}
table.data{width:100%;border-collapse:collapse;font-size:13px}
table.data th{position:sticky;top:0;z-index:5;background:var(--surface);
  border-bottom:2px solid var(--border);padding:7px 10px;text-align:left;
  font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--text2);
  font-weight:600;white-space:nowrap}
table.data th.r{text-align:right}
table.data th button{all:unset;cursor:pointer;display:inline-flex;gap:4px;
  align-items:center}
table.data th .arr{opacity:0;font-size:10px}
table.data th:hover .arr{opacity:.5}
table.data th.sorted{color:var(--accent)}
table.data th.sorted .arr{opacity:1}
table.data td{border-bottom:1px solid var(--hair);padding:0 10px;height:36px;
  white-space:nowrap}
table.data td.r{text-align:right}
table.data td.na{color:var(--faint)}
table.data tbody tr{cursor:pointer}
table.data tbody tr:hover{background:var(--raised)}
table.data tbody tr.open{background:var(--accent-tint);
  box-shadow:inset 2px 0 0 var(--accent)}
.tick{font-family:var(--mono);font-weight:600}
.nm{max-width:230px;overflow:hidden;text-overflow:ellipsis;color:var(--text2)}
.scorebar{display:inline-flex;align-items:center;gap:8px}
.scorebar .track{width:52px;height:5px;border-radius:3px;background:var(--raised);
  overflow:hidden}
.scorebar .fill{height:100%;border-radius:3px;background:var(--chart-1)}
@media (max-width:900px){
  .hide-m{display:none}
  .search input{width:130px}
  .wrap{padding:0 10px 48px}
  .masthead{flex-wrap:wrap;gap:6px 10px}
  .masthead h1{white-space:nowrap}
  .masthead .right .sub{display:none}
  .step{padding:8px 8px 10px}
  .chev{display:none}
  .btn,details.dd>summary,label.tog{min-height:40px;align-items:center;display:inline-flex}
  .panel .phd .btn{min-width:40px;justify-content:center}
  .chip button{padding:6px;margin:-6px}
}

/* ---- side panel ----------------------------------------------------------- */
.panel{position:fixed;top:0;right:0;bottom:0;width:min(480px,100vw);z-index:50;
  background:var(--surface);border-left:1px solid var(--border);
  transform:translateX(102%);transition:transform .15s ease;display:none;
  flex-direction:column;box-shadow:-12px 0 32px rgba(0,0,0,.18)}
.panel.open{transform:none;display:flex}
.panel .phd{display:flex;gap:10px;align-items:center;padding:14px 16px;
  border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--surface)}
.panel .phd .tick{font-size:16px}
.panel .phd .pn{font-size:12px;color:var(--text2);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.panel .pbody{overflow:auto;padding:0 16px 32px;flex:1}
.panel h3{font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--text2);margin:20px 0 8px;font-weight:600}
.metric-row{display:flex;gap:8px;align-items:baseline;padding:5px 0;
  border-bottom:1px solid var(--hair);font-size:12.5px}
.metric-row .k{color:var(--text2);flex:1}
.metric-row .v{font-family:var(--mono);font-weight:600}
.blockbar{margin:6px 0}
.blockbar .row{display:flex;justify-content:space-between;font-size:12px;
  color:var(--text2)}
.blockbar .track{height:6px;border-radius:3px;background:var(--raised);margin-top:3px;
  overflow:hidden}
.blockbar .fill{height:100%;background:var(--chart-1);border-radius:3px}
.probe{padding:8px 0;border-bottom:1px solid var(--hair);font-size:12.5px}
.probe .ph{display:flex;gap:8px;align-items:center;margin-bottom:2px}
.probe .pd{color:var(--text2)}
.mdet{font-size:12px;color:var(--text2);padding:4px 0 8px 0;border-bottom:1px solid var(--hair)}
.mdet b{color:var(--text);font-weight:600}
.overlay-bg{position:fixed;inset:0;z-index:45;background:rgba(0,0,0,.28);opacity:0;
  pointer-events:none;transition:opacity .15s}
.overlay-bg.on{opacity:1;pointer-events:auto}
@media (min-width:1100px){.overlay-bg{display:none}}

/* ---- charts --------------------------------------------------------------- */
.chartrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:12px;margin-top:16px;align-items:start}
.chart .cv{padding:6px 16px 14px}
.chart svg{display:block;width:100%;height:auto}
.chart .bar{cursor:default}
#tip{position:fixed;z-index:99;background:var(--overlay);border:1px solid var(--border);
  border-radius:6px;padding:6px 9px;font-size:12px;pointer-events:none;opacity:0;
  box-shadow:0 6px 18px rgba(0,0,0,.2);max-width:280px}
#tip b{font-family:var(--mono)}
.legend{display:flex;gap:14px;padding:0 16px;font-size:12px;color:var(--text2)}
.legend .sw{display:inline-block;width:10px;height:10px;border-radius:3px;
  margin-right:5px;vertical-align:-1px}

/* ---- thesis + monitor ------------------------------------------------------ */
.beats{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;
  padding:14px 16px}
.beat{border:1px solid var(--border);border-radius:8px;padding:12px;
  background:var(--raised)}
.beat .bn{width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;
  display:inline-flex;align-items:center;justify-content:center;font-size:12px;
  font-weight:600;margin-bottom:6px}
.beat h4{margin:0 0 4px;font-size:13px}
.beat p{margin:0;font-size:12px;color:var(--text2)}
.beat code{font-size:11px}
.prose{max-width:72em;font-size:13.5px}
.prose h2,.prose h3,.prose h4{margin:18px 0 6px;line-height:1.3}
.prose h2{font-size:16px}.prose h3{font-size:14px}.prose h4{font-size:13px}
.prose p{margin:8px 0}
.prose blockquote{border-left:3px solid var(--border);margin:8px 0;padding:2px 12px;
  color:var(--text2)}
.prose .tblwrap{overflow-x:auto;margin:10px 0}
.prose table{border-collapse:collapse;font-size:12.5px;min-width:480px}
.prose th,.prose td{border:1px solid var(--hair);padding:5px 9px;text-align:left}
.prose th{background:var(--raised);font-size:11px;text-transform:uppercase;
  letter-spacing:.04em;color:var(--text2)}
details.fold{border:1px solid var(--border);border-radius:8px;margin:10px 0}
details.fold>summary{cursor:pointer;padding:9px 14px;font-size:13px;font-weight:600;
  list-style:none;display:flex;gap:8px;align-items:center;color:var(--text2)}
details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary::before{content:"▸";transition:transform .12s}
details.fold[open]>summary::before{transform:rotate(90deg)}
details.fold>.fbody{padding:2px 16px 14px;border-top:1px solid var(--hair)}
.trig{border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin:8px 0}
.trig .th{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.trig .tid{font-family:var(--mono);font-weight:600;font-size:12.5px}
.trig .ts{font-size:12.5px;color:var(--text2);margin:6px 0 0}
.trig .dist{display:flex;align-items:center;gap:10px;margin-top:8px;font-size:12px;
  flex-wrap:wrap}
.trig .dtrack{flex:1;min-width:90px;max-width:260px;height:6px;background:var(--raised);
  border-radius:3px;overflow:hidden}
.trig .dfill{height:100%;border-radius:3px}
.thesis-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 16px}
.thesis-tools input,.thesis-tools select{min-height:42px;border:1px solid var(--border);
  border-radius:8px;background:var(--surface);color:var(--text);padding:8px 11px}
.thesis-tools input{flex:1;min-width:220px}
.thesis-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.thesis-card{border:1px solid var(--border);border-radius:12px;background:var(--surface);
  padding:16px;display:flex;flex-direction:column;gap:12px;box-shadow:var(--shadow)}
.thesis-card:focus-within{outline:3px solid var(--accent-tint);border-color:var(--accent)}
.company-head{display:flex;gap:11px;align-items:center}
.company-logo,.company-initials{width:44px;height:44px;border-radius:10px;flex:0 0 44px;
  object-fit:contain;background:var(--raised);border:1px solid var(--hair)}
.company-initials{display:flex;align-items:center;justify-content:center;font-family:var(--mono);
  font-weight:700;color:var(--accent)}
.company-title{min-width:0}.company-title b{display:block;font-size:16px}.company-title span{color:var(--text2)}
.card-judgements{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.valuation-summary{border-left:3px solid var(--accent);background:var(--accent-tint)}
.valuation-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;
  margin:12px 0}.valuation-metric{background:var(--raised);padding:12px;border-radius:8px;
  overflow-wrap:anywhere}.valuation-metric label{display:block;color:var(--faint);font-size:10px;
  text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}.valuation-metric b{font-size:17px}
.valuation-caveat{border-left:3px solid var(--warn);padding:9px 12px;background:var(--warn-bg);
  border-radius:0 8px 8px 0}
.judgement{background:var(--raised);border-radius:8px;padding:9px;overflow-wrap:anywhere}.judgement label{display:block;
  color:var(--faint);font-size:10px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}
.thesis-cta{width:100%;justify-content:center;min-height:42px;background:var(--accent);color:#fff;
  border:0;border-radius:8px;font-weight:650;cursor:pointer}
.thesis-reader{max-width:820px;margin:0 auto}.reader-back{position:sticky;top:8px;z-index:20;
  min-height:42px;margin-bottom:12px}.reader-hero{padding:20px}.reader-hero h1{margin:5px 0}
.glance{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:16px}
.reader-section{padding:20px;margin-top:12px}.reader-section h2{font-size:20px;margin:0 0 10px}
.watch-item{border-left:3px solid var(--warn);padding:8px 12px;margin:8px 0;background:var(--raised)}
.scout-thesis{display:block;margin-top:4px;border:0;background:none;color:var(--accent);
  padding:0;font-size:10px;cursor:pointer;text-decoration:underline}
@media(max-width:900px){.thesis-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:620px){.thesis-grid{grid-template-columns:1fr}.glance{grid-template-columns:1fr}
  .reader-section,.reader-hero{padding:15px}.valuation-metrics{grid-template-columns:1fr}}
.empty{padding:34px 16px;text-align:center;color:var(--text2);font-size:13px}
.empty b{display:block;font-size:15px;color:var(--text);margin-bottom:6px}
.cmd{background:var(--raised);border:1px solid var(--hair);border-radius:8px;
  padding:10px 14px;font-family:var(--mono);font-size:12px;overflow-x:auto;
  white-space:pre;margin:8px 0;color:var(--text2)}
footer{margin-top:40px;color:var(--faint);font-size:12px;line-height:1.7}
.skel{color:var(--faint);padding:20px;text-align:center}
"""


def _payload_json(model: dict, embed: dict) -> str:
    payload = dict(model)
    payload["details"] = embed
    return json.dumps(payload, ensure_ascii=False,
                      separators=(",", ":")).replace("</", "<\\/")


JS = r"""
'use strict';
const S = window.__SITE__;
const DESK = S.desk || {enabled: false};
const $ = (q, el) => (el || document).querySelector(q);
const $$ = (q, el) => Array.from((el || document).querySelectorAll(q));
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ---------- formatting ---------- */
const fmtMc = v => {
  if (v == null) return '—';
  const sign = v < 0 ? '-' : '';
  const a = Math.abs(v);
  return sign + (a >= 1e12 ? '$' + (a / 1e12).toFixed(2) + 'T'
    : a >= 1e9 ? '$' + (a / 1e9).toFixed(1) + 'B'
    : a >= 1e6 ? '$' + (a / 1e6).toFixed(0) + 'M' : '$' + Math.round(a));
};
const fmtV = (v, unit) => {
  if (v == null) return '—';
  if (unit && unit.startsWith('USD/share')) return '$' + v.toFixed(2);
  if (unit && unit.startsWith('USD')) return fmtMc(v);
  if (unit && unit.startsWith('x')) return v.toFixed(2) + '×';
  if (unit && (unit.startsWith('pts') || unit.startsWith('margin pts')))
    return v.toFixed(1) + ' pts';
  return (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)) + '%';
};
const REG_COLS = ['owner_fcf_yield_pct', 'roic_pct', 'revenue_growth_pct',
                  'gross_margin_pct', 'net_debt_to_ebitda'];
const REG_SHORT = {owner_fcf_yield_pct:'FCF yield', roic_pct:'ROIC',
  revenue_growth_pct:'Growth', gross_margin_pct:'Gross margin',
  net_debt_to_ebitda:'Net debt/EBITDA', owner_fcf_margin_pct:'FCF margin',
  sbc_pct_of_revenue:'SBC', share_count_trend_pct_per_year:'Share trend',
  accrual_divergence_pct:'Accruals', owner_fcf_usd:'Owner FCF',
  owner_fcf_per_share_usd:'FCF / share', fcf_conversion_pct:'FCF conversion',
  cash_conversion_pct:'Cash conversion', owner_fcf_per_share_growth_pct:'FCF/sh growth',
  incremental_roic_pct:'Incremental ROIC', capex_intensity_pct:'Capex intensity',
  rd_intensity_pct:'R&D intensity', operating_margin_pct:'Operating margin',
  operating_margin_mad_pts:'Op-margin stability', interest_coverage_x:'Interest cover',
  current_ratio:'Current ratio', goodwill_pct_assets:'Goodwill + intang.',
  tax_gap_pts:'Tax gap', dividends_pct_of_ocf:'Dividends / OCF',
  buybacks_pct_of_ocf:'Buybacks / OCF', acquisition_spend_pct_of_ocf:'Acquisitions / OCF'};

const VERDICT_CLS = {Robust:'p-good', Ordinary:'p-quiet', Fragile:'p-serious',
  Ruinous:'p-crit', Unknown:'p-ghost'};
const BAND_CLS = {Exceptional:'p-good', Strong:'p-acc', Mixed:'p-quiet',
  Weak:'p-warn', Pass:'p-quiet', 'VETOED':'p-crit', 'NO PRICE':'p-ghost'};
const pill = (txt, cls) => `<span class="pill ${cls || 'p-quiet'}">${esc(txt)}</span>`;
const srcBadge = src => src == null ? '' :
  src === 'edgar-live' ? '<span class="src edgar" title="filled by live EDGAR companyfacts (tier 2) — as-filed data the bulk export did not carry">EDGAR live</span>' :
  src === 'refined' ? '<span class="src refined" title="the export had a value; the fuller EDGAR series refined it (still as-filed)">refined</span>' :
  '<span class="src" title="from the bulk SEC export (tier 1)">export</span>';

/* ---------- state ---------- */
const state = {tab:'scout', q:'', sec:new Set(), band:new Set(), verdict:new Set(),
  ev:new Set(), picksOnly:false, minPct:0, sort:{col:'rk', dir:1}, open:null, view:[],
  thesisOpen:null, thesisQuery:'', thesisQuality:'', thesisRisk:'', thesisScroll:0};
const detailCache = Object.assign({}, S.details);

/* ---------- filtering + sorting ---------- */
function applyFilters(){
  const q = state.q.trim().toUpperCase();
  state.view = S.rows.filter(r =>
    (!q || r.s.toUpperCase().includes(q) || (r.n||'').toUpperCase().includes(q)) &&
    (!state.sec.size || state.sec.has(r.sec)) &&
    (!state.band.size || state.band.has(r.band)) &&
    (!state.verdict.size || state.verdict.has(r.verdict)) &&
    (!state.ev.size || state.ev.has(r.ev)) &&
    (!state.picksOnly || r.pick) &&
    (!state.minPct || (r.pct != null && r.pct >= state.minPct)));
  const {col, dir} = state.sort;
  const key = r => col === 'rk' ? r.rk
    : col === 's' ? r.s : col === 'n' ? (r.n||'') : col === 'sec' ? (r.sec||'')
    : col === 'mc' ? (r.mc ?? (dir === 1 ? Infinity : -Infinity))
    : col === 'pct' ? (r.pct ?? (dir === 1 ? Infinity : -Infinity))
    : col === 'verdict' ? ['Robust','Ordinary','Unknown','Fragile','Ruinous'].indexOf(r.verdict)
    : col === 'sev' ? r.sev * 10 + r.cau
    : (r.reg[col] ?? (dir === 1 ? Infinity : -Infinity));
  state.view.sort((a, b) => {
    const ka = key(a), kb = key(b);
    return (ka < kb ? -1 : ka > kb ? 1 : 0) * dir || a.rk - b.rk;
  });
  renderChips(); renderCount(); renderRows(true);
}

/* ---------- windowed table ---------- */
const ROWH = 36, OVERSCAN = 14;
function renderRows(reset){
  const scroller = $('#tscroll');
  if (reset) scroller.scrollTop = 0;
  const start = Math.max(0, Math.floor(scroller.scrollTop / ROWH) - OVERSCAN);
  const count = Math.ceil(scroller.clientHeight / ROWH) + OVERSCAN * 2;
  const slice = state.view.slice(start, start + count);
  $('#padTop').style.height = (start * ROWH) + 'px';
  $('#padBot').style.height =
    Math.max(0, (state.view.length - start - slice.length) * ROWH) + 'px';
  $('#tbody').innerHTML = slice.map(r => `
    <tr data-s="${esc(r.s)}" class="${state.open === r.s ? 'open' : ''}" tabindex="0">
      <td class="tick">${esc(r.s)}${r.pick ? ' <span class="pill p-good" title="passes the shortlist rules: top-two band, zero severe findings, verdict not Fragile/Ruinous">pick</span>' : ''}${r.top ? ` <span class="pill p-acc" title="top 1% by scorecard rank — thesis desk candidate">#${r.top}</span><button class="scout-thesis" data-thesis-symbol="${esc(r.s)}">View assessment & thesis</button>` : ''}</td>
      <td class="nm hide-m">${esc(r.n)}</td>
      <td class="hide-m">${esc(r.sec || '—')}</td>
      <td class="r num">${fmtMc(r.mc)}</td>
      <td>${r.pct == null ? pill(r.band || '—', BAND_CLS[r.band])
        : `<span class="scorebar"><span class="track"><span class="fill" style="width:${r.pct}%"></span></span><span class="num">${r.pct}</span>&nbsp;${pill(r.band, BAND_CLS[r.band])}</span>`}</td>
      <td>${pill(r.verdict || '—', VERDICT_CLS[r.verdict])}</td>
      <td class="r num">${r.sev || r.cau ? `${r.sev}·${r.cau}` : '0'}</td>
      ${REG_COLS.map(c => `<td class="r num ${r.reg[c] == null ? 'na' : ''}">${fmtV(r.reg[c], S.units[c])}</td>`).join('')}
    </tr>`).join('');
}

function renderCount(){
  $('#count').textContent = state.view.length === S.rows.length
    ? `${S.rows.length.toLocaleString()} names`
    : `${state.view.length.toLocaleString()} after filters · of ${S.rows.length.toLocaleString()}`;
  $('#ftCount').textContent = `Showing ${Math.min(state.view.length, 1).toLocaleString()}–${state.view.length.toLocaleString()} of ${S.rows.length.toLocaleString()} screened`;
}

/* ---------- filter UI ---------- */
function ddInit(id, values, set, label){
  const el = $(id);
  el.querySelector('.menu').innerHTML = values.map(v => `
    <label><input type="checkbox" value="${esc(v)}"> ${esc(v || '—')}</label>`).join('');
  el.addEventListener('change', () => {
    set.clear();
    $$('input:checked', el).forEach(i => set.add(i.value));
    const n = set.size;
    el.querySelector('summary').innerHTML =
      `${label} ${n ? `<span class="badge">${n}</span>` : ''} <span style="opacity:.5">▾</span>`;
    applyFilters();
  });
}
function renderChips(){
  const chips = [];
  const add = (txt, undo) => chips.push({txt, undo});
  state.sec.forEach(v => add('Sector: ' + v, () => state.sec.delete(v)));
  state.band.forEach(v => add('Band: ' + v, () => state.band.delete(v)));
  state.verdict.forEach(v => add('Verdict: ' + v, () => state.verdict.delete(v)));
  state.ev.forEach(v => add('Evidence: ' + v, () => state.ev.delete(v)));
  if (state.picksOnly) add('Picks only', () => { state.picksOnly = false; $('#picksOnly').checked = false; });
  if (state.minPct) add('Score ≥ ' + state.minPct, () => { state.minPct = 0; $('#minPct').value = 0; $('#minPctOut').textContent = '0'; });
  if (state.q) add('“' + state.q + '”', () => { state.q = ''; $('#q').value = ''; });
  const host = $('#chips');
  host.innerHTML = chips.map((c, i) =>
    `<span class="chip">${esc(c.txt)} <button data-i="${i}" aria-label="remove filter">×</button></span>`).join('')
    + (chips.length ? ' <button class="linkbtn" id="clearAll">Clear all</button>' : '');
  host.style.display = chips.length ? 'flex' : 'none';
  $$('.chip button', host).forEach(b => b.onclick = () => { chips[+b.dataset.i].undo(); syncDD(); applyFilters(); });
  const ca = $('#clearAll');
  if (ca) ca.onclick = () => { state.sec.clear(); state.band.clear(); state.verdict.clear();
    state.ev.clear(); state.picksOnly = false; $('#picksOnly').checked = false;
    state.minPct = 0; $('#minPct').value = 0; $('#minPctOut').textContent='0';
    state.q = ''; $('#q').value = ''; syncDD(); applyFilters(); };
}
function syncDD(){
  [['#ddSec', state.sec, 'Sector'], ['#ddBand', state.band, 'Band'],
   ['#ddVerdict', state.verdict, 'Verdict'], ['#ddEv', state.ev, 'Evidence']]
  .forEach(([id, set, label]) => {
    const el = $(id);
    $$('input', el).forEach(i => i.checked = set.has(i.value));
    el.querySelector('summary').innerHTML =
      `${label} ${set.size ? `<span class="badge">${set.size}</span>` : ''} <span style="opacity:.5">▾</span>`;
  });
}

/* ---------- detail panel ---------- */
const shardInflight = {};
async function getDetail(sym){
  if (detailCache[sym]) return detailCache[sym];
  if (!S.sharded) return null;
  const shard = /^[A-Z]/.test(sym[0]) ? sym[0].toLowerCase() : '0';
  try {
    // One fetch per shard even under re-entrant opens — shards run to ~1.5MB.
    shardInflight[shard] = shardInflight[shard] || fetch('data/d-' + shard + '.json')
      .then(res => { if (!res.ok) throw new Error(res.status); return res.json(); })
      .then(chunk => Object.assign(detailCache, chunk));
    await shardInflight[shard];
    return detailCache[sym] || null;
  } catch (e) { delete shardInflight[shard]; return null; }
}
function openPanel(sym){
  state.open = sym;
  location.hash = '#' + state.tab + '/' + sym;
  $('#panel').classList.add('open'); $('#ovbg').classList.add('on');
  const row = S.rows.find(r => r.s === sym);
  $('#pTick').textContent = sym;
  $('#pName').textContent = row ? `${row.n || ''}${row.sec ? ' · ' + row.sec : ''}` : '';
  $('#pBody').innerHTML = '<div class="skel">loading detail…</div>';
  renderRows(false);
  getDetail(sym).then(d => { if (state.open === sym) renderPanel(sym, row, d); });
}
function closePanel(push){
  state.open = null;
  $('#panel').classList.remove('open'); $('#ovbg').classList.remove('on');
  if (push !== false) location.hash = '#' + state.tab;
  renderRows(false);
}
function renderPanel(sym, row, d){
  if (!d){
    $('#pBody').innerHTML = `<div class="empty"><b>Full detail not loaded</b>
      This build carries drill-down shards next to the page (data/). Opening the page
      from the hosted site (or a local server) enables them; the compact numbers in the
      table are unaffected.</div>`;
    return;
  }
  const card = d.card || {}, inv = d.inv || {}, sc = d.scored || {};
  const blocks = card.blocks || {};
  const regRows = Object.entries(d.reg || {}).map(([k, o]) => {
    const vend = o.v == null && d.vendor && d.vendor[k];
    return `
    <div class="metric-row"><span class="k">${esc(REG_SHORT[k] || k)}
      <span style="color:var(--faint)"> · ${esc(S.units[k] || '')}</span></span>
      ${vend ? '<span class="src vendor" title="' + esc(vend.note) + '">vendor</span>' : srcBadge(o.src)}
      <span class="v">${o.v != null ? fmtV(o.v, S.units[k])
        : vend ? `<span style="color:var(--warn)">${fmtV(vend.v, S.units[k])}</span>` : '—'}</span></div>`;
  }).join('');
  const blockRows = Object.entries(blocks).map(([name, b]) => `
    <div class="blockbar" data-tip="${esc((b.metrics || []).join(', '))}">
      <div class="row"><span>${esc(name)}</span>
        <span class="num">${b.points ?? '—'}/${b.max}</span></div>
      <div class="track"><div class="fill" style="width:${b.max ? Math.round(100 * (b.points || 0) / b.max) : 0}%"></div></div>
    </div>`).join('');
  const metricRows = Object.entries(card.metrics || {}).map(([k, m]) => `
    <div class="mdet"><b>${esc(k)}</b> · ${m.points == null ? 'not measured' : `${m.points}/${m.max} pts`}
      <div>${esc(m.detail || '')}</div></div>`).join('');
  const sevPill = s => s === 'severe' ? pill('severe', 'p-crit')
    : s === 'caution' ? pill('caution', 'p-warn') : pill(s || 'clear', 'p-good');
  const probes = Object.entries(inv.probes || {}).map(([pid, p]) => `
    <div class="probe"><div class="ph">${sevPill(p.severity)}
      <b style="font-size:12px">${esc(pid)}</b>
      ${p.measured === false ? '<span class="src" title="the probe could not measure this name">unmeasured</span>' : ''}</div>
      <div class="pd">${esc(p.detail || '')}</div></div>`).join('');
  const failures = (inv.failure_modes || []).map(f => `<blockquote>${esc(f)}</blockquote>`).join('');
  const veto = sc.veto && sc.veto.vetoed ? `<div class="probe">${pill('VETOED', 'p-crit')}
    <span class="pd"> ${esc(sc.veto.reason || '')}</span></div>` : '';
  const flags = (sc.flags && Object.keys(sc.flags).length)
    ? Object.entries(sc.flags).map(([k, v]) => v ? pill(k, 'p-warn') : '').join(' ') : '';
  $('#pBody').innerHTML = `
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px">
      ${pill(card.band || '—', BAND_CLS[card.band])}
      ${pill((inv.verdict || '—') + ' — inversion', VERDICT_CLS[inv.verdict])}
      ${pill('evidence: ' + (card.evidence || '—'), 'p-quiet')}
      ${d.mc != null ? pill(fmtMc(d.mc), 'p-quiet') : pill('market cap refused', 'p-warn')}
      ${d.shb ? pill('shares: ' + esc(d.shb) + (d.shd ? ' · ' + esc(d.shd) : ''),
                     d.shb === 'stale-refused' ? 'p-crit'
                     : d.shb === 'weighted-average' ? 'p-warn' : 'p-ghost') : ''}
      ${d.pxd ? pill('price: ' + esc(d.pxd) + (d.pxa != null ? ` · ${d.pxa}d` : ''),
                     d.pxn ? 'p-crit' : 'p-ghost') : ''}
    </div>
    ${d.shn ? `<div style="font-size:11.5px;color:var(--text2);margin-top:6px">${esc(d.shn)}</div>` : ''}
    ${d.pxn ? `<div style="font-size:11.5px;color:var(--text2);margin-top:6px">${esc(d.pxn)}</div>` : ''}
    ${deskBlock([
      {id: 'refresh', symbol: sym, label: '↻ Refresh filings',
       hint: 'refetch this name from EDGAR now'},
      {id: 'thesis', symbol: sym, label: '✎ Draft thesis',
       hint: 'work order → your agent researches → mechanical validation'},
    ], `Drafting writes <code>theses/drafts/${esc(sym)}/</code>. Ratifying stays at the
        Gate, on purpose: <code>python thesis.py ratify ${esc(sym)}</code> asks you for
        conviction and circle-of-competence (FR9).`)}
    ${editBlock('note', sym, (S.notes || {})[sym] || '', {
      title: 'Desk note', placeholder: 'why this name is on the desk…',
      hint: 'yours; never scored, never published'})}
    <h3>Registry metrics <span style="text-transform:none;letter-spacing:0">(what a thesis trigger may test)</span></h3>
    ${regRows}
    <h3>The Owner's Scorecard — ${card.score ?? '—'}/${card.available_max ?? '—'} = ${card.pct ?? '—'}%</h3>
    <div style="font-size:12px;color:var(--text2);margin-bottom:4px">${esc(card.band_meaning || '')}</div>
    ${blockRows}
    <details class="fold"><summary>Every scored metric, with its sentence</summary>
      <div class="fbody">${metricRows || '<div class="mdet">nothing measured</div>'}</div></details>
    <h3>The Inversion Layer — ${esc(inv.verdict || '')}</h3>
    <div style="font-size:12px;color:var(--text2)">${esc(inv.verdict_meaning || '')}${inv.verdict_rule ? ' · ' + esc(inv.verdict_rule) : ''}</div>
    <div class="prose">${failures}</div>
    ${veto}
    <details class="fold"><summary>All seven probes</summary><div class="fbody">${probes}</div></details>
    ${flags ? `<h3>Flags</h3><div>${flags}</div>` : ''}
    ${compositesBlock(d.composites)}
    <h3>Sources</h3>
    <div style="font-size:12.5px">
      <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=${encodeURIComponent(sym)}&type=10-K&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR filings ↗</a>
      · TTM ${esc((sc.ttm && sc.ttm.basis) || '—')} through ${esc((sc.ttm && sc.ttm.through) || '—')}
      ${sc.note ? `<div style="color:var(--text2);margin-top:4px">${esc(sc.note)}</div>` : ''}
    </div>`;
  bindDeskActions($('#pBody'));
  bindEdits($('#pBody'));
}

/* ---------- editing (production desk only) ----------
   Desk CONTENT is editable — notes and draft prose/triggers — through the same
   validation the CLIs use: `save_thesis_draft` runs thesis.validate and refuses an
   untestable trigger from a human exactly as it does from an agent. Conviction and
   ratification are not here, and cannot be: that is the Gate (FR9). */
function editBlock(kind, symbol, value, opts){
  const o = opts || {};
  if (!DESK.enabled){
    return DESK.demo
      ? `<div class="edit"><h4 style="margin:14px 0 6px;font-size:11px;
          letter-spacing:.08em;text-transform:uppercase;color:var(--text2)">${esc(o.title || 'Edit')}</h4>
         <textarea class="${o.code ? 'code' : ''}" readonly>${esc(value || '')}</textarea>
         <div class="row"><span class="msg">Read-only in the demo — editing writes to
           your own desk's files.</span></div></div>`
      : '';
  }
  return `<div class="edit" data-kind="${esc(kind)}" data-symbol="${esc(symbol)}">
    <h4 style="margin:14px 0 6px;font-size:11px;letter-spacing:.08em;
        text-transform:uppercase;color:var(--text2)">${esc(o.title || 'Edit')}</h4>
    <textarea class="${o.code ? 'code' : ''}" placeholder="${esc(o.placeholder || '')}"
      >${esc(value || '')}</textarea>
    <div class="row"><button class="act" data-save="1">Save</button>
      <span class="msg">${esc(o.hint || '')}</span></div></div>`;
}

function bindEdits(root){
  $$('.edit[data-kind]', root).forEach(box => {
    const btn = $('[data-save]', box), area = $('textarea', box), msg = $('.msg', box);
    if (!btn) return;
    btn.addEventListener('click', async () => {
      const kind = box.dataset.kind, symbol = box.dataset.symbol;
      let body = {kind, symbol};
      if (kind === 'thesis'){
        try { body.thesis = JSON.parse(area.value); }
        catch (err){
          msg.className = 'msg bad';
          msg.textContent = 'not valid JSON: ' + err.message;
          return;
        }
      } else {
        body.text = area.value;
      }
      btn.disabled = true; msg.className = 'msg'; msg.textContent = 'saving…';
      try {
        const res = await fetch('api/edit', {
          method: 'POST', headers: {'Content-Type': 'application/json',
                                    'X-Desk-Token': DESK.token},
          body: JSON.stringify(body)});
        const out = await res.json().catch(() => ({error: `HTTP ${res.status}`}));
        if (out.error){
          msg.className = 'msg bad';
          msg.textContent = (out.problems || []).length
            ? 'refused: ' + out.problems.join(' · ') : out.error;
        } else {
          msg.className = 'msg good';
          msg.textContent = kind === 'thesis'
            ? `saved · ${out.triggers} trigger(s) validated · Rebuild site to re-render`
            : `saved (${out.chars} chars)`;
        }
      } catch (err){
        msg.className = 'msg bad'; msg.textContent = String(err.message || err);
      } finally { btn.disabled = false; }
    });
  });
}

/* The demo replays a recording at reading speed. It is deliberately the SAME code path
   the live desk uses to paint output — a demo that renders differently from the thing
   it demonstrates is a brochure, not a demo. */
async function replayAction(btn, action, symbol){
  const key = jobKey(action, symbol);
  const lines = (DESK.playback || {})[action] || ['(nothing recorded for this action)'];
  const others = $$('.act', btn.closest('.desk'));
  others.forEach(b => { b.disabled = true; });
  btn.classList.add('busy');
  JOBLOG.set(key, {lines: [{text: `${action}${symbol ? ' ' + symbol : ''} · replay`}],
                   live: true});
  paintLog(key);
  for (const line of lines){
    await new Promise(r => setTimeout(r, 420));
    JOBLOG.get(key).lines.push({text: line});
    paintLog(key);
  }
  await new Promise(r => setTimeout(r, 300));
  JOBLOG.get(key).lines.push({text: '— end of recording · nothing was executed —'});
  JOBLOG.get(key).live = false;
  paintLog(key);
  btn.classList.remove('busy');
  others.forEach(b => { b.disabled = false; });
}

/* ---------- desk actions ----------
   The published site is a READ-ONLY mirror: every action is rendered disabled with
   the reason, because running the thesis desk spends the operator's own agent
   budget and machine. `webapp.py --serve` builds the same page with DESK.enabled
   and a per-run token, and there the buttons drive the real CLIs. Ratifying is
   deliberately absent from the HTTP surface: conviction is asked of a human at the
   Gate (FR9), and a browser button is exactly the wrong door for it. */
function deskBlock(actions, note){
  const clickable = DESK.enabled || DESK.demo;
  const acts = actions.map(a => `<button class="act" data-act="${esc(a.id)}"
      ${a.symbol ? `data-symbol="${esc(a.symbol)}"` : ''}
      ${clickable ? '' : 'disabled'}
      title="${esc(clickable ? (DESK.demo ? 'replays a recording — nothing executes'
                                          : (a.hint || ''))
                             : 'local setup required')}">${esc(a.label)}</button>`).join('');
  const why = DESK.demo
    ? `<b>Visual demo — nothing is executing.</b> These buttons replay the real output
       each action printed when it was last run${DESK.captured ? ' (recorded ' +
       esc(DESK.captured) + ')' : ''}; a published page has nothing to run, and running
       the desk spends its operator's own subscription and machine. To drive it for real,
       set up your own in a few minutes — see
       <a href="https://github.com/qpec/invest-ai/blob/main/QUICKSTART.md"
       target="_blank" rel="noopener">QUICKSTART.md</a>.`
    : DESK.enabled
    ? (note || '')
    : `<b>Local setup required.</b> These run the desk on your own machine with your
       own subscription agent (Claude Code / OpenClaw, or the Codex CLI) — this public
       page is a read-only mirror, so nobody spends anyone else's tokens or compute.
       See <a href="https://github.com/qpec/invest-ai/blob/main/QUICKSTART.md"
       target="_blank" rel="noopener">QUICKSTART.md</a>.`;
  // One log element per action, keyed so a job that outlives this render (the operator
  // opened another symbol) repaints into the new DOM instead of shouting into a
  // detached node.
  const logs = actions.map(a => `<div class="desklog" data-job="${
    esc(jobKey(a.id, a.symbol))}" style="display:none"></div>`).join('');
  return `<div class="desk"><h4>Desk actions</h4><div class="acts">${acts}</div>
    <div class="why">${why}</div>${logs}</div>`;
}

function bindDeskActions(root){
  $$('.act', root).forEach(btn => {
    const key = jobKey(btn.dataset.act, btn.dataset.symbol || null);
    const entry = JOBLOG.get(key);
    if (entry){
      paintLog(key);                       // replay a job's output after a re-render
      if (entry.live){ btn.classList.add('busy'); btn.disabled = true; }
    }
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      const symbol = btn.dataset.symbol || null;
      if (DESK.demo) return replayAction(btn, btn.dataset.act, symbol);
      if (!DESK.enabled) return;
      runAction(btn, btn.dataset.act, symbol);
    });
  });
}

/* A running job's log lives here, not in the DOM: opening another symbol replaces the
   panel's innerHTML, and output written to a detached node — including the failure — is
   output the operator never sees. deskBlock() replays this on every render. */
const JOBLOG = new Map();
const jobKey = (action, symbol) => action + '|' + (symbol || '');

function paintLog(key){
  const el = $(`.desklog[data-job="${CSS.escape(key)}"]`);
  const entry = JOBLOG.get(key);
  if (!el || !entry) return;
  el.style.display = 'block';
  el.innerHTML = entry.lines.map(l =>
    l.bad ? `<span class="bad">${esc(l.text)}</span>` : esc(l.text)).join('\n');
  el.scrollTop = el.scrollHeight;
}

async function runAction(btn, action, symbol){
  const box = btn.closest('.desk');
  const key = jobKey(action, symbol);
  const others = $$('.act', box);
  others.forEach(b => { b.disabled = true; });
  btn.classList.add('busy');
  JOBLOG.set(key, {lines: [{text: `${action}${symbol ? ' ' + symbol : ''}`}], live: true});
  const write = (line, bad) => {
    JOBLOG.get(key).lines.push({text: line, bad: !!bad});
    paintLog(key);
  };
  paintLog(key);
  try {
    const started = await fetch('api/run', {
      method: 'POST', headers: {'Content-Type': 'application/json',
                                'X-Desk-Token': DESK.token},
      body: JSON.stringify({action, symbol})});
    const job = await started.json();
    if (!started.ok || job.error){ write(job.error || 'refused', true); return; }
    let seen = 0;
    for (;;){
      await new Promise(r => setTimeout(r, 900));
      const res = await fetch(`api/job?id=${encodeURIComponent(job.id)}`,
                              {headers: {'X-Desk-Token': DESK.token}});
      const st = await res.json().catch(() => ({error: `HTTP ${res.status}`}));
      if (!res.ok || st.error){
        write(`${st.error || 'HTTP ' + res.status} — the job may still be running; ` +
              `check the terminal running --serve`, true);
        break;
      }
      (st.lines || []).slice(seen).forEach(l => write(l));
      seen = (st.lines || []).length;
      if (st.done){
        write(st.ok ? '— finished —' : `— exited ${st.code} —`, !st.ok);
        if (st.ok && (action === 'refresh' || action === 'thesis'))
          write('Rebuild the page (Rebuild site) to see the new numbers.');
        break;
      }
    }
  } catch (err){
    write(String(err && err.message || err), true);
  } finally {
    const entry = JOBLOG.get(key);
    if (entry) entry.live = false;
    btn.classList.remove('busy');
    others.forEach(b => { b.disabled = !DESK.enabled; });
  }
}

function compositesBlock(c){
  if (!c) return '';
  const p = c.piotroski || {}, a = c.altman || {};
  const zoneCls = {safe: 'p-good', grey: 'p-warn', distress: 'p-crit'}[a.zone] || 'p-ghost';
  const checks = Object.entries(p.checks || {}).map(([k, v]) => `
    <div class="metric-row"><span class="k">${esc(k.replace(/_/g, ' '))}</span>
      <span class="v">${v == null ? '<span style="color:var(--faint)">unmeasured</span>'
        : v ? '✓' : '✗'}</span></div>`).join('');
  return `<h3>Composites <span style="text-transform:none;letter-spacing:0">(display-only — a composite never fires a trigger)</span></h3>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px">
      ${pill('Piotroski F ' + (p.score ?? '—') + ' of ' + (p.measured ?? 0) + ' measured (9 tests)', 'p-acc')}
      ${pill('Altman Z ' + (a.z == null ? 'unmeasured' : a.z + ' · ' + a.zone), zoneCls)}
    </div>
    <details class="fold"><summary>The nine Piotroski tests</summary>
      <div class="fbody">${checks}</div></details>`;
}

/* ---------- charts ---------- */
function chartColors(){
  const cs = getComputedStyle(document.documentElement);
  const v = n => cs.getPropertyValue(n).trim();
  return {c1: v('--chart-1'), c2: v('--chart-2'), text: v('--text2'),
    hair: v('--hair'), good: v('--good'), warn: v('--warn'),
    serious: v('--serious'), crit: v('--crit'), faint: v('--faint'),
    ord: [v('--ord-1'), v('--ord-2'), v('--ord-3'), v('--ord-4'), v('--ord-5')],
    quiet: v('--raised')};
}
function hbar(host, data, colorFn, tipFn){
  const C = chartColors();
  const max = Math.max(...data.map(d => d.count), 1);
  const bh = 22, gap = 8, lw = 88, vw = 46;
  // viewBox width follows the actual card so 11px means ~11px on screen — a fixed 460
  // shrank labels to ~8px in three-column layouts.
  const W = Math.max(300, ($(host).clientWidth || 460)), H = data.length * (bh + gap);
  $(host).innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">` + data.map((d, i) => {
    const y = i * (bh + gap);
    const w = Math.max(2, (W - lw - vw) * d.count / max);
    return `<text x="${lw - 8}" y="${y + bh / 2 + 4}" text-anchor="end"
        font-size="11" fill="${C.text}">${esc(d.label)}</text>
      <rect class="bar" data-tip="${esc(tipFn(d))}" x="${lw}" y="${y}" width="${w}"
        height="${bh}" rx="4" fill="${colorFn(d, i, C)}"></rect>
      <text x="${lw + w + 6}" y="${y + bh / 2 + 4}" font-size="11"
        fill="${C.text}" font-weight="600">${d.count.toLocaleString()}</text>`;
  }).join('') + '</svg>';
}
function coverageChart(){
  const host = $('#chCoverage'); if (!host) return;
  const C = chartColors();
  const data = S.charts.coverage;
  if (!data.length){ host.closest('.card').style.display = 'none'; return; }
  const n = S.counts.enriched;
  const bh = 9, pair = 26, lw = 118, vw = 60,
    W = Math.max(300, (host.clientWidth || 460)), H = data.length * pair + 6;
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">` + data.map((d, i) => {
    const y = i * pair;
    const w1 = Math.max(1.5, (W - lw - vw) * d.before / n);
    const w2 = Math.max(1.5, (W - lw - vw) * d.after / n);
    return `<text x="${lw - 8}" y="${y + 13}" text-anchor="end" font-size="10.5"
        fill="${C.text}">${esc(REG_SHORT[d.metric] || d.metric)}</text>
      <rect class="bar" data-tip="${esc('before enrichment: ' + d.before + ' of ' + n)}"
        x="${lw}" y="${y + 2}" width="${w1}" height="${bh}" rx="3" fill="${C.c1}"></rect>
      <rect class="bar" data-tip="${esc('after tier 2 (EDGAR live): ' + d.after + ' of ' + n)}"
        x="${lw}" y="${y + 3 + bh}" width="${w2}" height="${bh}" rx="3" fill="${C.c2}"></rect>
      <text x="${lw + Math.max(w1, w2) + 6}" y="${y + 15}" font-size="10.5"
        fill="${C.text}" font-weight="600">${d.before}→${d.after}</text>`;
  }).join('') + '</svg>';
  $('#covLegend').innerHTML = `<span><span class="sw" style="background:${C.c1}"></span>export only</span>
    <span><span class="sw" style="background:${C.c2}"></span>+ EDGAR live (tier 2)</span>
    <span style="color:var(--faint)">across the ${n} enriched names</span>`;
}
function drawCharts(){
  const C = chartColors();
  hbar('#chBands', S.charts.bands,
    (d, i, c) => d.label === 'VETOED' || d.label === 'NO PRICE' ? c.quiet : c.ord[i] || c.quiet,
    d => d.label === 'VETOED' ? 'suppressed by the Munger veto layer — never ranked'
      : d.label === 'NO PRICE' ? 'no market cap — quality profile only, not a verdict'
      : `${d.count} of ${S.counts.screened} score in the ${d.label} band`);
  hbar('#chVerdicts', S.charts.verdicts,
    (d, i, c) => ({Robust: c.good, Ordinary: c.quiet, Fragile: c.serious,
                   Ruinous: c.crit, Unknown: c.quiet}[d.label]),
    d => `${d.count} names — ${({Robust:'no probe found a named failure mode',
      Ordinary:'normal business risk', Fragile:'clear ways this breaks you',
      Ruinous:'a named way to lose most of the money',
      Unknown:'the layer could not certify — evidence, not safety'}[d.label])}`);
  coverageChart();
}

/* ---------- thesis + portfolio monitor tabs ---------- */
function distBar(t){
  if (t.kind !== 'metric' || t.current == null || t.distance_pct == null) return '';
  const away = t.distance_pct;
  const unit = t.margin_kind === 'points' ? ' pts' : '%';
  const tone = t.hit ? 'var(--crit)' : away < 10 ? 'var(--serious)'
    : away < 30 ? 'var(--warn)' : 'var(--good)';
  const w = t.hit ? 100 : Math.max(3, Math.min(100, away));
  const label = t.hit ? 'TRIPPED at the current value'
    : `${away.toFixed(0)}${unit} of safety margin`;
  return `<div class="dist"><span class="num">now ${fmtV(t.current, S.units[t.metric])}</span>
    <div class="dtrack"><div class="dfill" style="width:${w}%;background:${tone}"></div></div>
    <span class="num">${esc(t.op)} ${fmtV(t.threshold, S.units[t.metric])}</span>
    <span style="color:var(--text2)">${esc(label)}${t.checks ? ` · needs ${t.checks} consecutive weekly checks` : ''}</span></div>`;
}
function trigCard(t){
  const kindCls = {metric:'p-acc', event:'p-warn', narrative:'p-quiet'}[t.kind];
  const actCls = t.action === 'break' ? 'p-crit' : 'p-warn';
  return `<div class="trig"><div class="th">
      <span class="tid">${esc(t.id)}</span>
      ${pill(t.kind, kindCls)} ${pill(t.action === 'break' ? 'break — pre-committed sell' : 'review — summons the owner', actCls)}
      ${t.kind !== 'metric' ? pill('answered weekly by the agent', 'p-ghost') : ''}
    </div>
    <p class="ts">${esc(t.statement)}</p>
    ${distBar(t)}
    ${t.question ? `<p class="ts" style="color:var(--faint)">Q: ${esc(t.question)}</p>` : ''}
  </div>`;
}
const thesisReaders = () => S.thesis.readers || [];
const readerBySymbol = symbol => thesisReaders().find(r => r.symbol === symbol);
const initials = reader => (reader.name || reader.symbol).split(/\s+/).slice(0, 2)
  .map(word => word[0] || '').join('').toUpperCase();
const companyMark = reader => reader.logo
  ? `<img class="company-logo" src="${esc(reader.logo)}" alt="" loading="lazy">`
  : `<span class="company-initials" aria-hidden="true">${esc(initials(reader))}</span>`;

function renderThesisIndex(){
  state.thesisOpen = null;
  const q = state.thesisQuery.trim().toUpperCase();
  const readers = thesisReaders().filter(reader =>
    (!q || reader.symbol.toUpperCase().includes(q)
      || reader.name.toUpperCase().includes(q))
    && (!state.thesisQuality || reader.quality.grade === state.thesisQuality)
    && (!state.thesisRisk || reader.risk.verdict === state.thesisRisk));
  $('#thesisIndex').style.display = '';
  $('#thesisReader').style.display = 'none';
  $('#thesisResultCount').textContent = `${readers.length} of ${thesisReaders().length} companies`;
  $('#thesisGrid').innerHTML = readers.map(reader => {
    const th = reader.thesis || {}, valuation = th.valuation_anchor || {}, lens = reader.valuation_lens || {};
    return `<article class="thesis-card" data-thesis-symbol="${esc(reader.symbol)}">
      <div class="company-head">${companyMark(reader)}<div class="company-title">
        <b>#${reader.rank} · ${esc(reader.name)}</b><span>${esc(reader.symbol)}</span></div></div>
      <p class="ts">${esc(th.business_model || '')}</p>
      <div class="card-judgements">
        <div class="judgement"><label>Business quality</label>
          <b>${reader.quality.score == null ? '—' : esc(reader.quality.score) + '/100'}</b><br>
          ${pill(reader.quality.grade || 'Unknown', BAND_CLS[reader.quality.grade])}</div>
        <div class="judgement"><label>Downside risk</label>
          ${pill(reader.risk.verdict || 'Unknown', VERDICT_CLS[reader.risk.verdict])}</div>
      </div>
      <div class="judgement valuation-summary"><label>Current price</label>
        <b>${lens.price == null ? 'Unavailable' : '$' + Number(lens.price).toFixed(2)}</b>
        <span class="ts"> · ${esc(lens.price_as_of || 'date unavailable')}</span>
        <p class="ts"><b>${esc(lens.signal || 'Valuation context unavailable')}</b></p>
        <p class="ts">Owner cash yield ${lens.owner_cash_yield_pct == null ? '—' : esc(lens.owner_cash_yield_pct) + '%'} · ${lens.percentile == null ? '—' : esc(lens.percentile) + 'th percentile'} in ${esc(lens.comparison_label || 'the measured universe')}</p></div>
      <button class="thesis-cta" data-thesis-symbol="${esc(reader.symbol)}">View assessment &amp; thesis</button>
    </article>`;
  }).join('') || '<div class="empty"><b>No companies match these filters</b>Clear one or more filters.</div>';
  $$('#thesisGrid .thesis-cta').forEach(button =>
    button.onclick = () => openThesisReader(button.dataset.thesisSymbol));
}

function watchItem(trigger){
  const condition = trigger.kind === 'metric' && trigger.metric
    ? `Watch ${REG_SHORT[trigger.metric] || trigger.metric}: review if it is ${esc(trigger.op)} ${fmtV(trigger.threshold, S.units[trigger.metric])}.`
    : (trigger.question || trigger.statement || 'Watch for a material change.');
  return `<div class="watch-item"><b>${trigger.action === 'break' ? 'Thesis-breaking signal' : 'Review signal'}</b>
    <p class="ts">${esc(trigger.statement || '')}</p><p class="ts">${esc(condition)}</p></div>`;
}

function openThesisReader(symbol, push = true){
  const reader = readerBySymbol(symbol);
  if (!reader) return;
  state.thesisScroll = window.scrollY;
  state.thesisOpen = symbol;
  setTab('thesis', false);
  const th = reader.thesis || {}, moat = th.moat || {}, valuation = th.valuation_anchor || {},
    lens = reader.valuation_lens || {};
  $('#thesisIndex').style.display = 'none';
  const host = $('#thesisReader'); host.style.display = '';
  host.innerHTML = `<div class="thesis-reader">
    <button class="btn reader-back" id="readerBack">← Back to Top 48</button>
    <header class="card reader-hero"><div class="company-head">${companyMark(reader)}
      <div class="company-title"><span>#${reader.rank} · ${esc(reader.symbol)}</span>
      <h1>${esc(reader.name)}</h1></div></div>
      <div class="glance" aria-label="At a glance"><div class="judgement"><label>What is it?</label>${esc(th.business_model || '')}</div>
      <div class="judgement"><label>How strong is the business?</label><b>${esc(reader.quality.grade || 'Unknown')} · ${esc(reader.quality.score ?? '—')}/100</b><p class="ts">${esc(reader.quality.explanation || '')}</p></div>
      <div class="judgement"><label>How can it hurt you?</label><b>${esc(reader.risk.verdict || 'Unknown')}</b><p class="ts">${esc(reader.risk.leading_fragility || '')}</p></div>
      <div class="judgement"><label>What does valuation imply?</label><b>${esc(lens.signal || 'Unavailable')}</b><p class="ts">${esc(valuation.statement || '')}</p></div></div></header>
    <section class="card reader-section prose"><h2>The case in one minute</h2>${reader.summary_html || '<p>No summary available.</p>'}</section>
    <section class="card reader-section"><h2>Why might this be a strong business?</h2><p>${esc(th.business_model || '')}</p>
      <h3>${esc((moat.kind || 'Potential moat').replaceAll('_', ' '))}</h3><ul>${(moat.evidence || []).map(item => `<li>${esc(item)}</li>`).join('')}</ul>
      ${th.ten_year_statement ? `<p>${esc(th.ten_year_statement)}</p>` : ''}</section>
    <section class="card reader-section"><h2>What do the cash economics say?</h2><p>${esc(th.owner_earnings_picture || 'The available filings do not support a reliable conclusion.')}</p></section>
    <section class="card reader-section"><h2>What does the valuation imply?</h2><h3>Valuation context</h3>
      <p><b>${esc(lens.signal || 'Valuation context unavailable')}</b></p>
      <div class="valuation-metrics">
        <div class="valuation-metric"><label>Current price</label><b>${lens.price == null ? '—' : '$' + Number(lens.price).toFixed(2)}</b><p class="ts">Quote dated ${esc(lens.price_as_of || 'unavailable')}</p></div>
        <div class="valuation-metric"><label>Owner cash yield</label><b>${lens.owner_cash_yield_pct == null ? '—' : esc(lens.owner_cash_yield_pct) + '%'}</b><p class="ts">Equivalent to roughly ${lens.owner_cash_multiple_x == null ? '—' : esc(lens.owner_cash_multiple_x) + '×'} current owner cash flow</p></div>
        <div class="valuation-metric"><label>Relative position</label><b>${lens.percentile == null ? '—' : esc(lens.percentile) + 'th percentile'}</b><p class="ts">Among ${esc(lens.comparison_count ?? '—')} companies in the ${esc(lens.comparison_label || 'measured Scout universe')}</p></div>
      </div>
      <p>${esc(valuation.statement || '')}</p>
      <p class="valuation-caveat"><b>What could distort this signal?</b><br>${esc(lens.caveat || 'Current owner cash flow may not represent normal earning power.')}</p>
      <p class="ts">Relative valuation context only; current cash flow may not be normal.</p></section>
    <section class="card reader-section"><h2>What could go wrong?</h2><p>${esc(th.bear_case || '')}</p></section>
    <section class="card reader-section"><h2>What would change the thesis?</h2>${(reader.triggers || []).map(watchItem).join('') || '<p>No monitor conditions recorded.</p>'}</section>
    <details class="card reader-section"><summary><b>Sources and full research</b></summary>
      <div class="prose">${reader.report_html || ''}</div><ul>${(th.sources || []).map(source =>
        /^https?:\/\//.test(source) ? `<li><a href="${esc(source)}" target="_blank" rel="noopener">${esc(source)}</a></li>` : `<li>${esc(source)}</li>`).join('')}</ul></details>
  </div>`;
  $('#readerBack').onclick = () => closeThesisReader();
  if (push) location.hash = '#thesis/' + encodeURIComponent(symbol);
  window.scrollTo(0, 0);
}

function closeThesisReader(push = true){
  state.thesisOpen = null;
  renderThesisIndex();
  if (push) location.hash = '#thesis';
  requestAnimationFrame(() => window.scrollTo(0, state.thesisScroll));
}

function renderThesisTab(){
  renderThesisIndex();
  $('#thesisSearch').value = state.thesisQuery;
  $('#thesisSearch').oninput = event => { state.thesisQuery = event.target.value; renderThesisIndex(); };
  $('#thesisQuality').onchange = event => { state.thesisQuality = event.target.value; renderThesisIndex(); };
  $('#thesisRisk').onchange = event => { state.thesisRisk = event.target.value; renderThesisIndex(); };
}
const md_inline = s => {
  let out = esc(s);
  out = out.replace(/(https?:\/\/[^\s]+)$/,'<a href="$1" target="_blank" rel="noopener">source ↗</a>');
  return out;
};
function renderPortfolioMonitorTab(){
  const deskHost = $('#monitorDesk');
  if (deskHost){
    deskHost.innerHTML = deskBlock([
      {id: 'monitor-brief', label: '📝 Write the work order',
       hint: 'the week\'s judgement questions from the committed theses'},
      {id: 'monitor-run', label: '▶ Run the monitor',
       hint: 'refresh monitored names, then evaluate every trigger'},
    ], `The run refreshes each monitored name from EDGAR first, then tests only the
        pre-committed triggers. A question your agent has not answered is reported
        UNCHECKED — never guessed.`);
    bindDeskActions(deskHost);
  }
  const host = $('#committedHost');
  if (!S.portfolio_monitor.committed.length){
    host.innerHTML = `<div class="empty"><b>No committed theses yet</b>
      The monitor reads only <code>theses/committed/</code>, and only the owner's
      ratification at the Gate puts a thesis there — conviction and circle-of-competence
      are asked, never generated (FR9).</div>`;
  } else {
    host.innerHTML = S.portfolio_monitor.committed.map(c => `
      <div class="trig"><div class="th"><span class="tid">${esc(c.symbol)}</span>
        ${pill(c.status, c.status === 'intact' ? 'p-good' : c.status === 'broken' ? 'p-crit' : 'p-warn')}
        <span class="muted">v${c.version} · ratified ${esc(c.ratified_at || '')} · monitored ${esc(c.last_monitored || '')}</span></div>
        ${c.target_weight != null ? `<p class="ts">Target weight: <span class="num">${(100*c.target_weight).toFixed(1)}%</span></p>` : ''}
        ${c.thesis && c.thesis.business_model ? `<p class="ts">${esc(c.thesis.business_model)}</p>` : ''}
        ${(c.triggers || []).map(trigCard).join('')}</div>`).join('');
  }
  const pv = S.portfolio_monitor.preview;
  const pvHost = $('#previewHost');
  if (pv && !S.portfolio_monitor.committed.length){
    pvHost.innerHTML = `<div class="hd"><h2>Preview — what the first weekly run will check</h2>
      ${pill('draft, NOT committed — the monitor will not act on it', 'p-warn')}</div>
      <div class="bd">
      <p class="intro" style="margin-top:0">${esc(pv.symbol)}'s six triggers evaluated
      against today's registry, exactly as <code>monitor.py run</code> will do every
      Saturday once the owner ratifies. Metric triggers are pure arithmetic; event and
      narrative questions go to the agent, and an unanswered question is reported
      <b>UNCHECKED</b> — a gap in the monitoring, never a pass.</p>
      ${(pv.triggers || []).map(trigCard).join('')}</div>`;
  } else { pvHost.style.display = 'none'; }
  $('#nextRun').textContent = S.portfolio_monitor.next_run;
}

/* ---------- tabs + routing + keyboard + theme ---------- */
function setTab(tab, push){
  state.tab = tab;
  $$('.step').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $$('.tabpane').forEach(p => p.style.display = p.id === 'tab-' + tab ? '' : 'none');
  if (push !== false) location.hash = tab === 'thesis' && state.thesisOpen
    ? '#thesis/' + encodeURIComponent(state.thesisOpen)
    : '#' + tab + (tab === 'scout' && state.open ? '/' + state.open : '');
}
function route(){
  const h = location.hash.replace(/^#/, '');
  const [tab, sym] = h.split('/');
  if (['scout', 'thesis', 'portfolio_monitor'].includes(tab)) setTab(tab, false);
  if (tab === 'thesis' && sym && readerBySymbol(sym)) {
    if (state.thesisOpen !== sym) openThesisReader(sym, false);
    if (state.open) closePanel(false);
  } else if (tab === 'thesis' && state.thesisOpen) {
    closeThesisReader(false);
  } else if (sym && S.rows.some(r => r.s === sym)) {
    if (state.open !== sym) openPanel(sym);   // re-entrancy guard: hash writes loop back here
  } else if (state.open) {
    closePanel(false);                        // browser Back with the panel open closes it
  }
}
function initTheme(){
  const saved = localStorage.getItem('agentcy-theme');
  if (saved) document.documentElement.dataset.theme = saved;
  $('#themeBtn').onclick = () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('agentcy-theme', next);
    drawCharts();
  };
}
function initTip(){
  const tip = $('#tip');
  document.addEventListener('scroll', () => { tip.style.opacity = 0; }, true);
  document.addEventListener('mousemove', e => {
    const t = e.target.closest('[data-tip]');
    if (!t){ tip.style.opacity = 0; return; }
    tip.textContent = t.dataset.tip;
    tip.style.opacity = 1;
    const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 10);
    const y = Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 10);
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  });
}
function initKeys(){
  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea')) {
      if (e.key === 'Escape') {
        // Chromium's native clear on type=search empties the pixels without firing
        // input — the filter would silently stay applied to an empty-looking box.
        e.preventDefault();
        if (e.target.id === 'q'){ state.q = ''; e.target.value = ''; applyFilters(); }
        e.target.blur();
      }
      return;
    }
    if (e.key === '/'){ e.preventDefault(); setTab('scout'); $('#q').focus(); }
    else if (e.key === 'Escape') closePanel();
    else if (e.key === '1') setTab('scout');
    else if (e.key === '2') setTab('thesis');
    else if (e.key === '3') setTab('portfolio_monitor');
    else if (e.key === 't') $('#themeBtn').click();
    else if ((e.key === 'j' || e.key === 'k') && state.open){
      const i = state.view.findIndex(r => r.s === state.open);
      const next = state.view[i + (e.key === 'j' ? 1 : -1)];
      if (next) openPanel(next.s);
    }
  });
  document.addEventListener('click', e => {
    $$('details.dd[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; });
  });
}

/* ---------- boot ---------- */
function boot(){
  $('#asOf').textContent = S.as_of;
  $('#srcNote').textContent = S.source;
  $('#cScout').textContent = S.counts.screened.toLocaleString() + ' screened';
  $('#cThesis').textContent = `${S.counts.top} candidates · ${S.counts.drafts} draft${S.counts.drafts === 1 ? '' : 's'}`;
  $('#cMonitor').textContent = S.counts.committed + ' committed';
  const secs = [...new Set(S.rows.map(r => r.sec).filter(Boolean))].sort();
  ddInit('#ddSec', secs, state.sec, 'Sector');
  ddInit('#ddBand', ['Exceptional','Strong','Mixed','Weak','Pass','VETOED','NO PRICE'], state.band, 'Band');
  ddInit('#ddVerdict', ['Robust','Ordinary','Fragile','Ruinous','Unknown'], state.verdict, 'Verdict');
  ddInit('#ddEv', ['full','partial','thin'], state.ev, 'Evidence');
  $('#q').addEventListener('input', e => { state.q = e.target.value; applyFilters(); });
  $('#picksOnly').addEventListener('change', e => { state.picksOnly = e.target.checked; applyFilters(); });
  $('#minPct').addEventListener('input', e => { state.minPct = +e.target.value;
    $('#minPctOut').textContent = e.target.value; applyFilters(); });
  $('#tscroll').addEventListener('scroll', () => renderRows(false));
  $('#tbody').addEventListener('click', e => {
    const thesis = e.target.closest('[data-thesis-symbol]');
    if (thesis){ e.stopPropagation(); closePanel(false); openThesisReader(thesis.dataset.thesisSymbol); return; }
    const tr = e.target.closest('tr[data-s]');
    if (tr) openPanel(tr.dataset.s);
  });
  // Rows sit in the tab order (tabindex=0), so the keyboard affordance must be real.
  $('#tbody').addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const tr = e.target.closest('tr[data-s]');
    if (tr){ e.preventDefault(); openPanel(tr.dataset.s); }
  });
  $$('#thead th[data-col]').forEach(th => th.onclick = () => {
    const col = th.dataset.col;
    const first = (col === 's' || col === 'n' || col === 'sec') ? 1 : -1;
    // A full cycle per column: first click its natural direction, second the reverse,
    // third back to scorecard rank. (The first cut reset on the second click, which
    // made ascending unreachable for every numeric column.)
    if (state.sort.col !== col) state.sort = {col, dir: first};
    else if (state.sort.dir === first) state.sort = {col, dir: -first};
    else state.sort = {col: 'rk', dir: 1};
    $$('#thead th').forEach(t => { t.classList.toggle('sorted', t.dataset.col === state.sort.col);
      t.querySelector('.arr').textContent = t.dataset.col === state.sort.col
        ? (state.sort.dir === 1 ? '↑' : '↓') : '↕'; });
    applyFilters();
  });
  $$('.step').forEach(b => b.onclick = () => setTab(b.dataset.tab));
  $('#pClose').onclick = closePanel;
  $('#ovbg').onclick = closePanel;
  initTheme(); initTip(); initKeys();
  let rsz; addEventListener('resize', () => { clearTimeout(rsz); rsz = setTimeout(drawCharts, 200); });
  renderThesisTab(); renderPortfolioMonitorTab();
  applyFilters(); drawCharts();
  addEventListener('hashchange', route);
  route();
}
boot();
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%93%88%3C/text%3E%3C/svg%3E">
<title>Invest AI — Scout · Thesis · Portfolio monitor</title>
<style>__CSS__</style>
</head>
<body>
<header class="top">
  __DEMOBAR__
  <div class="masthead">
    <h1>Invest AI</h1>
    <span class="sub">the desk · as of <b id="asOf" class="num"></b> · snapshot <b class="num">__SNAPSHOT_ID__</b></span>
    <div class="right">
      <span class="sub" id="srcNote"></span>
      <button class="btn" id="themeBtn" title="toggle theme (t)">◐ theme</button>
    </div>
  </div>
  <nav class="stepper" aria-label="pipeline">
    <button class="step active" data-tab="scout"><span class="circ">1</span>
      <span><span class="lbl">The Scout</span><span class="cnt" id="cScout"></span></span></button>
    <span class="chev">›</span>
    <button class="step" data-tab="thesis"><span class="circ">2</span>
      <span><span class="lbl">The Thesis Desk</span><span class="cnt" id="cThesis"></span></span></button>
    <span class="chev">›</span>
    <button class="step" data-tab="portfolio_monitor"><span class="circ">3</span>
      <span><span class="lbl">Model portfolio &amp; monitor</span><span class="cnt" id="cMonitor"></span></span></button>
  </nav>
  <div class="notice"><b>Illustratieve modelportefeuille, geen financieel advies.</b></div>
</header>

<div class="wrap">

<!-- ============ 1 · SCOUT ============ -->
<section class="tabpane" id="tab-scout">
  <p class="intro"><b>1 · The Scout finds what is worth a look.</b> The whole screened
  universe graded twice, independently: the <b>Owner's Scorecard</b> asks how good the
  business is (Buffett); the <b>Inversion Layer</b> asks how it would lose your money
  (Munger). The two verdicts are never merged — a name can be Exceptional and Fragile at
  once, and that tension is the information. Click any row for the full drill-down.</p>
  <div class="kpis">
    <div class="kpi"><label>Screened</label><b>__KPI_SCREENED__</b><div class="d">US filers, bulk SEC export</div></div>
    <div class="kpi"><label>Picks</label><b>__KPI_PICKS__</b><div class="d">top-two band · zero severe findings</div></div>
    <div class="kpi"><label>Thesis candidates</label><b>__KPI_TOP__</b><div class="d">top 1% by scorecard rank</div></div>
    <div class="kpi"><label>Metric hardening</label><b>__KPI_ENRICHED__</b><div class="d">names enriched from live EDGAR (tier 2)</div></div>
  </div>
  <div class="chartrow">
    <div class="card chart"><div class="hd"><h2>Scorecard bands</h2><span class="muted">how good is the business</span></div><div class="cv" id="chBands"></div></div>
    <div class="card chart"><div class="hd"><h2>Inversion verdicts</h2><span class="muted">how it breaks you</span></div><div class="cv" id="chVerdicts"></div></div>
    <div class="card chart"><div class="hd"><h2>Registry coverage — the fallback chain at work</h2><span class="muted">metrics computable before → after tier 2</span></div><div class="cv" id="chCoverage"></div><div class="legend" id="covLegend" style="padding-bottom:12px"></div></div>
  </div>
  <div class="card">
    <div class="hd">
      <h2>Universe</h2><span class="muted" id="count"></span>
      <div class="toolbar">
        <span class="search"><input id="q" type="search" placeholder="ticker or name — press /" aria-label="search"></span>
        <details class="dd" id="ddSec"><summary>Sector <span style="opacity:.5">▾</span></summary><div class="menu"></div></details>
        <details class="dd" id="ddBand"><summary>Band <span style="opacity:.5">▾</span></summary><div class="menu"></div></details>
        <details class="dd" id="ddVerdict"><summary>Verdict <span style="opacity:.5">▾</span></summary><div class="menu"></div></details>
        <details class="dd" id="ddEv"><summary>Evidence <span style="opacity:.5">▾</span></summary><div class="menu"></div></details>
        <label class="tog"><input type="checkbox" id="picksOnly"> picks only</label>
        <label class="tog" style="border:none">score ≥ <output id="minPctOut">0</output>
          <input type="range" id="minPct" min="0" max="100" step="5" value="0" style="width:90px;accent-color:var(--accent)"></label>
      </div>
    </div>
    <div class="chips" id="chips" style="display:none"></div>
    <div class="tscroll" id="tscroll">
      <table class="data">
        <thead id="thead"><tr>
          <th data-col="s"><button>Ticker <span class="arr">↕</span></button></th>
          <th class="hide-m" data-col="n"><button>Name <span class="arr">↕</span></button></th>
          <th class="hide-m" data-col="sec"><button>Sector <span class="arr">↕</span></button></th>
          <th class="r" data-col="mc"><button>Mkt cap <span class="arr">↕</span></button></th>
          <th data-col="pct"><button>Scorecard <span class="arr">↕</span></button></th>
          <th data-col="verdict"><button>Inversion <span class="arr">↕</span></button></th>
          <th class="r" data-col="sev" title="severe · caution findings"><button>Sev·Cau <span class="arr">↕</span></button></th>
          <th class="r" data-col="owner_fcf_yield_pct"><button>FCF yield <span class="arr">↕</span></button></th>
          <th class="r" data-col="roic_pct"><button>ROIC <span class="arr">↕</span></button></th>
          <th class="r" data-col="revenue_growth_pct"><button>Growth <span class="arr">↕</span></button></th>
          <th class="r" data-col="gross_margin_pct"><button>Gross m. <span class="arr">↕</span></button></th>
          <th class="r" data-col="net_debt_to_ebitda"><button>ND/EBITDA <span class="arr">↕</span></button></th>
        </tr></thead>
        <tbody><tr id="padTop" aria-hidden="true"><td colspan="12" style="padding:0;border:0;height:0"></td></tr></tbody>
        <tbody id="tbody"></tbody>
        <tbody><tr id="padBot" aria-hidden="true"><td colspan="12" style="padding:0;border:0;height:0"></td></tr></tbody>
      </table>
    </div>
    <div class="ft"><span id="ftCount"></span>
      <span>· sorted by scorecard rank unless a column is chosen · a dash is a number the
      filings could not certify, shown as absent rather than guessed</span></div>
  </div>
</section>

<!-- ============ 2 · THESIS ============ -->
<section class="tabpane" id="tab-thesis" style="display:none">
  <div id="thesisIndex">
    <p class="intro"><b>2 · 48 companies worth deeper research.</b> Each company has
    a separate business-quality assessment, downside-risk verdict, valuation anchor and
    evidence-led thesis. Open any card for the plain-English walkthrough.</p>
    <div class="thesis-tools">
      <input id="thesisSearch" type="search" placeholder="Search company or ticker" aria-label="Search the Top 48">
      <select id="thesisQuality" aria-label="Filter by business quality"><option value="">All quality grades</option><option>Exceptional</option><option>Strong</option><option>Mixed</option><option>Weak</option><option>Pass</option></select>
      <select id="thesisRisk" aria-label="Filter by downside risk"><option value="">All risk verdicts</option><option>Robust</option><option>Ordinary</option><option>Fragile</option><option>Ruinous</option><option>Unknown</option></select>
      <span class="muted" id="thesisResultCount"></span>
    </div>
    <div class="thesis-grid" id="thesisGrid"></div>
  </div>
  <div id="thesisReader" aria-live="polite" style="display:none"></div>
</section>

<!-- ============ 3 · MODEL PORTFOLIO + MONITOR ============ -->
<section class="tabpane" id="tab-portfolio_monitor" style="display:none">
  <p class="intro"><b>3 · The model portfolio and monitor keep every chosen thesis together.</b>
  The monitor checks each committed thesis against its own
  triggers, weekly.</b> Never open-ended news scanning: the thesis drives the monitoring.
  Metric triggers are pure arithmetic on fresh filings (with the tier-2 enrichment cache,
  so a leverage trigger stays checkable); judgement questions go to the agent and an
  unanswered one is reported <b>UNCHECKED</b>, loudly. A tripped break trigger means the
  standing advice is to sell, ignoring cost basis (FR7) — and nothing here ever executes
  a trade (FR11). “No action needed” is the celebrated outcome (FR4).</p>
  <div id="monitorDesk"></div>
  <div class="kpis">
    <div class="kpi"><label>Committed theses</label><b>__KPI_COMMITTED__</b><div class="d">only the Gate puts them here</div></div>
    <div class="kpi"><label>Next weekly run</label><b class="num" style="font-size:18px" id="nextRun"></b><div class="d">Saturdays, with the Watchdog</div></div>
    <div class="kpi"><label>Broken is sticky</label><b>∞</b><div class="d">a broken thesis stays broken until the owner acts at the desk</div></div>
  </div>
  <div class="card">
    <div class="hd"><h2>Committed theses</h2><span class="muted">intact / under review / broken · per their own triggers</span></div>
    <div class="bd" id="committedHost"></div>
  </div>
  <div class="card" id="previewHost"></div>
  <div class="card">
    <div class="hd"><h2>The weekly loop</h2><span class="muted">three commands, one report</span></div>
    <div class="bd">
      <div class="cmd">python monitor.py brief --theses-dir theses            # 1 · the open judgement questions
# the agent answers them into theses/monitor-&lt;date&gt;/verdicts.json
python monitor.py run --sec-data &lt;dir&gt; --prices &lt;dir&gt; \\
    --enrich-cache enrich_cache \\
    --verdicts theses/monitor-&lt;date&gt;/verdicts.json      # 2 · evaluate everything → reports/monitor-&lt;date&gt;.md</div>
      <p class="intro" style="margin-top:8px">Confidence is mechanical: only <b>high</b>
      (documented public fact) lets a break trigger actually break — anything less demotes
      to review, because an inference must never fire a sell rule. A narrative trigger can
      only summon the owner to the desk.</p>
    </div>
  </div>
</section>

<footer>
  <b>The system never executes trades.</b> (FR11) · Conviction and
  circle-of-competence never appear on this page — they are the owner's, asked at the Gate
  (FR9) · Data: bulk SEC export + live EDGAR companyfacts (tier 2, as-filed) · generated
  __GENERATED__ by <code>python webapp.py</code> ·
  <a href="site/index.html">system explainer</a> · keyboard: <code>/</code> search ·
  <code>1 2 3</code> tabs · <code>j k</code> walk rows · <code>t</code> theme
</footer>
</div>

<div class="overlay-bg" id="ovbg"></div>
<aside class="panel" id="panel" aria-label="detail">
  <div class="phd"><span class="tick" id="pTick"></span>
    <span class="pn" id="pName"></span>
    <button class="btn" id="pClose" style="margin-left:auto" title="close (Esc)">✕</button></div>
  <div class="pbody" id="pBody"></div>
</aside>
<div id="tip"></div>

<script>window.__SITE__ = __PAYLOAD__;</script>
<script>__JS__</script>
</body>
</html>
"""


def render(model: dict, embed_details: dict) -> str:
    counts = model["counts"]
    demo = (model.get("desk") or {}).get("demo")
    demobar = ("" if not demo else
               '<div class="demobar"><b>Public read-only snapshot; actions are disabled.</b></div>')
    page = (TEMPLATE
            .replace("__DEMOBAR__", demobar)
            .replace("__CSS__", CSS)
            .replace("__KPI_SCREENED__", f"{counts['screened']:,}")
            .replace("__KPI_PICKS__", str(counts["picks"]))
            .replace("__KPI_TOP__", str(counts["top"]))
            .replace("__KPI_ENRICHED__", str(counts["enriched"]))
            .replace("__KPI_COMMITTED__", str(counts["committed"]))
            .replace("__SNAPSHOT_ID__", str(model.get("snapshot_id") or "unknown"))
            .replace("__GENERATED__", model["generated"])
            .replace("__PAYLOAD__", _payload_json(
                {k: v for k, v in model.items() if k != "details"}
                | {"sharded": model.get("sharded", False)}, embed_details))
            .replace("__JS__", JS))
    return page


def write_site(model: dict, out_dir: Path, *, shard: bool = True,
               logo_assets: dict[str, str | None] | None = None,
               logo_cache_root: Path | None = None) -> Path:
    """docs/index.html + docs/data/d-<letter>.json. Details for picks and thesis
    candidates are embedded inline (the common drill-downs work from a single file);
    everything else lazy-loads from the shards."""
    out_dir.mkdir(parents=True, exist_ok=True)
    logo_assets = logo_assets or {}
    if logo_assets:
        if logo_cache_root is None:
            raise ValueError("logo_cache_root required with logo assets")
        target_dir = out_dir / "data" / "logos"
        target_dir.mkdir(parents=True, exist_ok=True)
        for reader in model.get("thesis", {}).get("readers", []):
            relative = logo_assets.get(reader.get("symbol"))
            reader["logo"] = None
            if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                continue
            source = logo_cache_root / relative
            if not source.is_file():
                continue
            target = target_dir / source.name
            shutil.copy2(source, target)
            reader["logo"] = f"data/logos/{target.name}"
    details = model["details"]
    inline = {c["s"]: details[c["s"]] for c in model["rows"]
              if (c["pick"] or c["top"]) and c["s"] in details}
    model["sharded"] = shard
    if shard:
        data_dir = out_dir / "data"
        data_dir.mkdir(exist_ok=True)
        shards: dict[str, dict] = {}
        for symbol, detail in details.items():
            key = symbol[0].lower() if symbol[:1].isalpha() else "0"
            shards.setdefault(key, {})[symbol] = detail
        for key, chunk in shards.items():
            shard_tmp = data_dir / f".d-{key}.json.tmp"
            try:
                shard_tmp.write_text(
                    json.dumps(chunk, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
                os.replace(shard_tmp, data_dir / f"d-{key}.json")
            except BaseException:
                shard_tmp.unlink(missing_ok=True)
                raise
    # Atomic: the desk server serves this very directory while a `rebuild` rewrites it,
    # and a truncate-then-write would hand a reader a blank page. The temp name is
    # dot-prefixed and removed on failure so a crashed build can never be rsynced into
    # the published site by deploy/scout/publish.sh.
    out = out_dir / "index.html"
    tmp = out_dir / ".index.html.tmp"
    try:
        tmp.write_text(render(model, inline), encoding="utf-8")
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return out


# --- the desk server: the SAME page, with its actions live (owner-directed 2026-08-05) ---
#
# The published site is a read-only mirror on purpose — running the desk spends the
# operator's own agent budget and machine, so a stranger's click must never start a
# job. `--serve` is the other half: identical HTML, plus a capability token, bound to
# loopback, driving the very CLIs the QUICKSTART documents.
#
# What this surface deliberately CANNOT do: ratify. Conviction and circle-of-competence
# are asked of a human at the Gate (FR9), and a browser button — reachable by a stray
# click or a cross-origin request — is the wrong door for the one irreversible step.

DESK_ACTIONS = {
    # id: (argv builder, needs a symbol)
    "refresh": (lambda a, sym: [sys.executable, "enrich.py", "--force-refresh",
                                "--symbols", sym, "--cache", a.enrich_cache or ""], True),
    "thesis": (lambda a, sym: [sys.executable, "thesis.py", "brief", sym,
                               "--sec-data", a.sec_data, "--universe", a.universe,
                               "--as-of", a.as_of, "--theses-dir", a.theses_dir or "theses"]
               + (["--prices", a.prices] if a.prices else [])
               + (["--enrich-cache", a.enrich_cache] if a.enrich_cache else []), True),
    "thesis-batch": (lambda a, sym: [sys.executable, "thesis.py", "batch",
                                     "--sec-data", a.sec_data, "--universe", a.universe,
                                     "--as-of", a.as_of,
                                     "--theses-dir", a.theses_dir or "theses"]
                     + (["--prices", a.prices] if a.prices else [])
                     + (["--enrich-cache", a.enrich_cache] if a.enrich_cache else []), False),
    "monitor-brief": (lambda a, sym: [sys.executable, "monitor.py", "brief",
                                      "--theses-dir", a.theses_dir or "theses",
                                      "--as-of", a.as_of], False),
    "monitor-run": (lambda a, sym: [sys.executable, "monitor.py", "run",
                                    "--sec-data", a.sec_data, "--universe", a.universe,
                                    "--as-of", a.as_of,
                                    "--theses-dir", a.theses_dir or "theses"]
                    + (["--prices", a.prices] if a.prices else [])
                    + (["--enrich-cache", a.enrich_cache] if a.enrich_cache else [])
                    + (["--reports-dir", str(Path(a.theses_dir or "theses").parent
                                             / "reports")]), False),
    "rebuild": (None, False),          # handled in-process, no subprocess
}


def desk_command(action: str, symbol, args, known) -> tuple[list | None, str | None]:
    """(argv, error) for one desk action — the whole validation surface, at module level
    so it is testable without a socket. A symbol must be one THIS build screened: the
    argv is executed without a shell, but an unvalidated string in an argument list is
    still an unvalidated string, and 'refuse what you cannot check' is the house rule."""
    spec = DESK_ACTIONS.get(action)
    if spec is None:
        return None, f"unknown action {action!r}"
    builder, needs_symbol = spec
    if needs_symbol and (not symbol or symbol not in known):
        return None, "unknown symbol"
    if action == "refresh" and not getattr(args, "enrich_cache", None):
        return None, "--enrich-cache was not given to --serve"
    if builder is None:
        return None, None                      # in-process action (rebuild)
    return builder(args, symbol), None


def notes_dir(theses_dir) -> Path:
    """Where desk notes live: a SIBLING of theses/, never inside it.

    Inside, they would ride the weekly `rsync $SCOUT/theses/ state/theses/` straight into
    the state archive the owner elected to make public — free-form portfolio prose, in
    git history, forever (preflight review 2026-08-05). Outside, no publish path can
    reach them and no reviewer has to remember an exclude."""
    return Path(theses_dir or "theses").resolve().parent / "desk-notes"


def load_notes(theses_dir: Path | None) -> dict[str, str]:
    """Desk notes, {SYMBOL: text}. Loaded ONLY by the served build, and stored outside the
    theses tree — so neither the published page nor the state archive can carry them."""
    base = notes_dir(theses_dir)
    if not base.exists():
        return {}
    out = {}
    for path in sorted(base.glob("*.md")):
        try:
            out[path.stem.upper()] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return out


_SYMBOL_OK = re.compile(r"\A[A-Z0-9][A-Z0-9.\-]{0,15}\Z")


def _safe_symbol(symbol) -> str | None:
    """A symbol that may become a path component. The API already checks membership of
    the screened set, but universe.csv is user-supplied: two independent checks, because
    a path built from unvalidated text is the oldest bug there is."""
    symbol = str(symbol or "").upper()
    return symbol if _SYMBOL_OK.match(symbol) and ".." not in symbol else None


def save_note(theses_dir: Path, symbol: str, text: str) -> dict:
    """A free-text note beside a name. Owner prose, never scored, never published: it
    lives in the state tree with the theses and is exactly what a desk needs for
    'why I keep looking at this'."""
    symbol = _safe_symbol(symbol)
    if not symbol:
        return {"error": "unusable symbol"}
    path = notes_dir(theses_dir) / f"{symbol}.md"
    deskwork.write_atomic(path, text.strip() + "\n" if text.strip() else "")
    return {"saved": str(path), "chars": len(text.strip())}


def save_thesis_draft(theses_dir: Path, symbol: str, payload: dict) -> dict:
    """Edit a DRAFT thesis through the same gate the agent's work goes through.

    The owner may rewrite prose and re-tune triggers — that is what a desk is for — but
    the rules do not soften for a human: `thesis.validate` refuses an untestable
    trigger, an unknown metric or a forbidden field exactly as it does for the agent,
    and nothing here can touch `theses/committed/` (ratification stays the interactive
    Gate, FR9). A refused edit is reported and NOT written."""
    symbol = _safe_symbol(symbol)
    if not symbol:
        return {"error": "unusable symbol"}
    draft = Path(theses_dir) / "drafts" / symbol / "thesis.json"
    if not draft.exists():
        return {"error": f"no draft for {symbol}"}
    if not isinstance(payload, dict):
        return {"error": "the edited thesis must be a JSON object"}
    forbidden = [k for k in ("conviction", "circle_of_competence") if k in payload]
    if forbidden:
        # The one thing a browser must never write (FR9), said plainly rather than
        # silently dropped — a silent drop teaches the wrong lesson about the seam.
        return {"error": f"{', '.join(forbidden)} is the owner's at the Gate, never an "
                         f"edit: run `python thesis.py ratify {symbol}`"}
    payload = {**payload, "symbol": symbol}
    problems = thesis_mod.validate(payload, symbol=symbol)
    if problems:
        return {"error": "refused", "problems": problems}
    deskwork.write_atomic(draft, json.dumps(payload, indent=2))
    # thesis.json is the agent's raw file; the page and `ratify` both read record.json.
    # Writing only the former made an edit look saved and change nothing (preflight
    # review 2026-08-05) -- so re-run the same `record` the agent's work goes through,
    # which re-validates, re-stamps the model, and regenerates the record.
    try:
        doc = thesis_mod.record(symbol, theses_dir=Path(theses_dir))
    except Exception as error:  # noqa: BLE001 -- record refusing IS the answer
        return {"error": "saved but record refused it", "problems": [str(error)]}
    return {"saved": str(draft), "triggers": len(payload.get("triggers") or []),
            "recorded": doc.get("status")}


def serve(args) -> int:
    """Serve the desk locally with its actions enabled. Loopback only, token-gated."""
    import http.server
    import secrets
    import subprocess
    import tempfile
    import threading
    import urllib.parse

    token = secrets.token_urlsafe(24)
    jobs: dict[str, dict] = {}
    inflight: dict[str, str] = {}          # at most one entry: job_id -> action
    lock = threading.Lock()
    here = Path(__file__).resolve().parent

    # A served build carries a live capability and MUST NOT land in the tree that gets
    # published — `--out-dir` defaults to the publish path for the static build, and a
    # served page written there would commit a token and flip the public mirror's
    # buttons to enabled (found by preflight review, reproduced).
    published = (here.parent / "docs").resolve()
    if args.out_dir is None:
        args.out_dir = tempfile.mkdtemp(prefix="desk-site-")
        print(f"building into {args.out_dir} (scratch; pass --out-dir to choose)")
    out_dir = Path(args.out_dir).resolve()
    if out_dir == published:
        print("refusing to serve into the published docs/ tree: a served build carries "
              "a live capability token. Pass --out-dir <scratch dir>.", file=sys.stderr)
        return 2

    # The page is assembled in THIS process (resolved against the shell's cwd) while the
    # action subprocesses run with cwd=here, so every path argument is pinned to an
    # absolute path once — otherwise a server started from anywhere else would read one
    # directory and write another.
    for field in ("sec_data", "prices", "universe", "enrich_cache", "theses_dir"):
        value = getattr(args, field, None)
        if value:
            setattr(args, field, str(Path(value).resolve()))

    def build():
        # A Restart=always desk would otherwise freeze as_of at the date it booted.
        if not getattr(args, "as_of_pinned", False):
            args.as_of = _dt.date.today().isoformat()
        model = assemble(sec_data=args.sec_data, prices_dir=args.prices,
                         universe=args.universe, as_of=args.as_of,
                         enrich_cache=args.enrich_cache, theses_dir=args.theses_dir)
        model["desk"] = {"enabled": True, "token": token}
        model["notes"] = load_notes(Path(args.theses_dir) if args.theses_dir else None)
        write_site(model, out_dir, shard=not args.no_shards)
        return model

    model = build()
    known = {row["s"] for row in model["rows"]}

    def start(action: str, symbol: str | None) -> dict:
        argv, error = desk_command(action, symbol, args, known)
        if error:
            return {"error": error}
        job_id = secrets.token_urlsafe(8)
        with lock:
            # One desk job at a time: every action mutates the same theses/, cache and
            # build directory, and two concurrent writers is a corrupted state, not a
            # faster desk. (Two browser tabs each have their own disabled-button state.)
            if inflight:
                return {"error": f"busy: {next(iter(inflight.values()))} is still running"}
            inflight[job_id] = action
            jobs[job_id] = {"lines": [], "done": False, "ok": False, "code": None}

        def run():
            try:
                if action == "rebuild":
                    build()
                    with lock:
                        jobs[job_id].update(lines=["site rebuilt from disk"],
                                            done=True, ok=True, code=0)
                    return
                with lock:
                    jobs[job_id]["lines"].append("$ " + " ".join(
                        Path(part).name if part == sys.executable else part
                        for part in argv))
                proc = subprocess.Popen(argv, cwd=here, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        bufsize=1)
                for line in proc.stdout:
                    with lock:
                        jobs[job_id]["lines"].append(line.rstrip())
                code = proc.wait()
                with lock:
                    jobs[job_id].update(done=True, ok=(code == 0), code=code)
            except Exception as error:  # noqa: BLE001 — a failed job must report, not vanish
                with lock:
                    jobs[job_id]["lines"].append(f"{type(error).__name__}: {error}")
                    jobs[job_id].update(done=True, ok=False, code=-1)
            finally:
                with lock:
                    inflight.pop(job_id, None)

        threading.Thread(target=run, daemon=True).start()
        return {"id": job_id}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(out_dir), **kw)

        def log_message(self, fmt, *a):        # quiet: this is a desk tool, not a server
            pass

        def _json(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            """DNS-rebinding guard, applied to EVERY request before a byte is served:
            index.html carries the capability token, so a static GET is a
            secret-bearing GET and must be gated exactly like /api/*."""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in ("localhost", "127.0.0.1", "::1")

        def _authorized(self) -> bool:
            # What the token actually defends: a page on ANOTHER ORIGIN in this browser
            # cannot read the response of a loopback GET, so it cannot learn the token,
            # so it cannot forge an /api/ call (a custom header also forces a preflight
            # this server never approves). It is deliberately NOT a defence against
            # another process running as this same user — such a process can already run
            # `python thesis.py` directly, so there is no boundary there to defend.
            return secrets.compare_digest(self.headers.get("X-Desk-Token") or "", token)

        def do_POST(self):
            if not self._host_ok():
                return self._json({"error": "bad host"}, 421)
            route = self.path.split("?")[0].rstrip("/")
            if route not in ("/api/run", "/api/edit"):
                return self._json({"error": "not found"}, 404)
            if not self._authorized():
                return self._json({"error": "not authorized"}, 403)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 <= length <= 2 * 1024 * 1024:   # negative => read() to EOF
                    return self._json({"error": "bad length"}, 413)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._json({"error": "bad request"}, 400)
            if route == "/api/edit":
                symbol = payload.get("symbol")
                if symbol not in known:
                    return self._json({"error": "unknown symbol"}, 400)
                theses = Path(args.theses_dir or "theses")
                kind = payload.get("kind")
                # Serialised with the action jobs: both mutate the same files, and
                # write_atomic's fixed .tmp sibling makes concurrent writers a race.
                with lock:
                    if kind == "note":
                        result = save_note(theses, symbol, str(payload.get("text") or ""))
                    elif kind == "thesis":
                        result = save_thesis_draft(theses, symbol, payload.get("thesis"))
                    else:
                        result = {"error": f"unknown edit kind {kind!r}"}
                return self._json(result, 400 if result.get("error") else 200)
            result = start(str(payload.get("action") or ""),
                           (payload.get("symbol") or None))
            return self._json(result, 200 if "id" in result else 400)

        def do_GET(self):
            if not self._host_ok():
                return self._json({"error": "bad host"}, 421)
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.rstrip("/") == "/api/job":
                if not self._authorized():
                    return self._json({"error": "not authorized"}, 403)
                job_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
                with lock:
                    job = jobs.get(job_id)
                    snapshot = dict(job, lines=list(job["lines"])) if job else None
                return self._json(snapshot or {"error": "unknown job"},
                                  200 if snapshot else 404)
            return super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.serve), Handler)
    print(f"desk → http://127.0.0.1:{args.serve}/   (loopback only; actions are live)")
    print("     ctrl-c to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sec-data", required=True)
    parser.add_argument("--prices")
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--as-of", default=_dt.date.today().isoformat())
    parser.add_argument("--enrich-cache", help="tier-2 companyfacts cache (enrich.py)")
    parser.add_argument("--theses-dir", help="theses/ for the Thesis + Monitor tabs")
    # No shared default: the static build publishes into ../docs, while --serve (which
    # bakes a live capability token into the page) must never inherit that path.
    parser.add_argument("--out-dir", help="static build: default ../docs; "
                                          "--serve: a scratch dir unless given")
    parser.add_argument("--no-shards", action="store_true",
                        help="single-file build: embed pick/top details only")
    parser.add_argument("--demo", action="store_true",
                        help="public-demo build: a persistent 'nothing is executing' "
                             "banner, and desk actions that REPLAY the recorded output "
                             "in sample-data/demo-playback.json instead of running")
    parser.add_argument("--serve", type=int, metavar="PORT", nargs="?", const=8899,
                        help="run the desk locally on 127.0.0.1:PORT with its actions "
                             "ENABLED (default 8899). Without this the build is a "
                             "read-only mirror: every action renders disabled.")
    args = parser.parse_args(argv)

    if args.serve:
        return serve(args)

    model = assemble(sec_data=args.sec_data, prices_dir=args.prices,
                     universe=args.universe, as_of=args.as_of,
                     enrich_cache=args.enrich_cache, theses_dir=args.theses_dir)
    # A published build never carries a capability token: the actions exist in the DOM
    # so a reader can see what the desk does, and are inert because this page is a
    # mirror of someone else's machine.
    if args.demo:
        # A recording, labelled as one. Missing/corrupt playback is not fatal: the demo
        # still renders, and an action simply says nothing was recorded for it.
        playback = {}
        captured = None
        book = Path(__file__).resolve().parent / "sample-data" / "demo-playback.json"
        try:
            loaded = json.loads(book.read_text(encoding="utf-8"))
            playback, captured = loaded.get("actions") or {}, loaded.get("captured")
        except (OSError, json.JSONDecodeError) as error:
            print(f"no demo playback ({type(error).__name__}) — buttons will say so",
                  file=sys.stderr)
        model["desk"] = {"enabled": False, "demo": True,
                         "playback": playback, "captured": captured}
    else:
        model["desk"] = {"enabled": False}
    out = write_site(model, Path(args.out_dir or "../docs"), shard=not args.no_shards)
    size = out.stat().st_size / 1024
    print(f"{out}  ({size:,.0f} KB; {model['counts']['screened']} names, "
          f"{model['counts']['picks']} picks, {model['counts']['drafts']} draft(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
