"""Live grading run (spec §5.5): universe + cache -> scoring -> reports + formation.

The live half of the decoupling seam (§4, msg 44): cache/<SYM>.json entries (§3.2)
are mapped to §4.1 Bundles by build_bundle() — own market_cap from fast_info,
yahoo_ev from fast_info when present, shares dict -> ascending series, statements
straight through — and fed to scoring.score_universe, the same pure code the
backtests use. Then per graded name the §4.8 shadow layers (margin of safety +
Buffett checklist — never in the composite), the proposal portfolio, and the v3
formation update (§5.6, the live mode per msg 58) unless --no-formation.

Outputs (§3.3): reports/scout-run-<date>.md + reports/scout-grades-<date>.json.
The md carries the §5.5 sections: header counts by grade + veto breakdown by
reason, tier-sectioned A-F tables (V/Q/G/D/M, MoS%, flags), the NL-names
call-out, "De Formatie" (squad/transfers/bench/open slots — replacing the old
top-15 ranking) and the honest-evidence footer. --telegram sends the md summary
head via tg.py and attaches the newest datasheet when present.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

import formation
import scoring
import tg
from populate import cache_filename

VERSION = "v2.3+v3"
GRADE_LETTERS = ("A", "B", "C", "D", "F")
TIERS = ("Core", "Adjacent", "Outside")
_DATASHEET_RE = re.compile(r"^datasheet-(\d{4}-\d{2}-\d{2})\.html$")


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
        "annual": cache_entry.get("annual") or {},
        "quarterly": cache_entry.get("quarterly") or {},
    }


def load_bundles(universe_path: str | Path, cache_dir: str | Path
                 ) -> tuple[list[dict], int, int]:
    """Universe rows -> (bundles in universe order, universe size, uncached count).
    Uncached symbols are skipped and counted (§5.5 step 1), never fabricated."""
    rows = pd.read_csv(universe_path).to_dict("records")
    cache_dir = Path(cache_dir)
    bundles, uncached = [], 0
    for row in rows:
        path = cache_dir / cache_filename(str(row["symbol"]))
        if not path.exists():
            uncached += 1
            continue
        bundles.append(build_bundle(json.loads(path.read_text(encoding="utf-8"))))
    return bundles, len(rows), uncached


# ------------------------------------------------------------------- report pieces

def _fmt(value, spec: str = ".1f", suffix: str = "") -> str:
    return "—" if value is None else f"{value:{spec}}{suffix}"


def _mos_pct(row: dict) -> str:
    mos = row.get("mos")
    return "—" if not mos else f"{100.0 * mos['mos_pct']:+.0f}%"


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


def _veto_breakdown(scored: list[dict]) -> list[str]:
    """Veto counts grouped by reason family (the text before the first ':', §5.5)."""
    counts = Counter(r["veto"]["reason"].split(":")[0].strip()
                     for r in scored if r["veto"]["vetoed"])
    if not counts:
        return ["Veto-verdeling: geen veto's deze run."]
    return ["Veto-verdeling:"] + [f"- {reason}: {n}"
                                  for reason, n in counts.most_common()]


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
              for b in state["bench"]] or ["- leeg"]
    open_slots = state["slots"] - len(state["squad"])
    lines += ["", f"Open plekken: {open_slots} — liever cash dan een kandidaat "
                  f"zonder bewijs."]
    return lines


def render_report(doc: dict, transfers: list[dict], uncached: int,
                  formation_updated: bool) -> str:
    """The §5.5 report md from a §3.3 grades document (pure)."""
    scored = doc["names"]
    graded = [r for r in scored if r["grade"] in GRADE_LETTERS]
    grade_counts = Counter(r["grade"] for r in graded)
    lines = [
        f"# Stock Scout — run {doc['run_date']} ({doc['version']})", "",
        f"Universum {doc['universe']} · gegraded {doc['graded']} · veto "
        f"{doc['vetoed']} · insufficient {doc['insufficient']} · niet in cache {uncached}",
        "Grades: " + " · ".join(f"{g} {grade_counts.get(g, 0)}" for g in GRADE_LETTERS),
        "",
    ]
    lines += _veto_breakdown(scored)
    for tier in TIERS:
        tier_names = sorted((r for r in graded if r["tier"] == tier),
                            key=lambda r: (-r["composite"], r["symbol"]))
        if not tier_names:
            continue
        lines += ["", f"## {tier} ({len(tier_names)})", ""]
        lines += _grade_table(tier_names)
    nl = [r for r in scored if str(r["symbol"]).endswith(".AS")]
    lines += ["", "## NL-namen", ""]
    lines += [f"- {r['symbol']} — {r['grade']}" +
              (f" (composite {r['composite']:.1f})" if r["composite"] is not None else "")
              for r in nl] or ["Geen NL-namen in deze run."]
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
        no_formation: bool, state_path: str | Path, reports_dir: str | Path
        ) -> tuple[dict, Path, Path]:
    """§5.5 steps 1-6 -> (grades doc, md path, json path). Formation state is read
    from and written back to `state_path` unless no_formation (then the existing
    state is embedded read-only, §3.3 formation key)."""
    bundles, universe_n, uncached = load_bundles(universe_path, cache_dir)
    scored = scoring.score_universe(bundles)

    by_symbol = {b["symbol"]: b for b in bundles}
    for row in scored:                       # §4.8 shadow layers for every graded name
        graded = row["grade"] in GRADE_LETTERS
        bundle = by_symbol[row["symbol"]]
        row["mos"] = scoring.margin_of_safety(bundle) if graded else None
        row["buffett"] = scoring.buffett_checklist(bundle) if graded else None

    portfolio = scoring.build_portfolio(scored)

    if no_formation:
        state, transfers, updated = formation.load_state(state_path), [], False
    else:
        state, transfers = formation.update(formation.load_state(state_path),
                                            scored, run_date)
        formation.save_state(state, state_path)
        updated = True

    doc = {
        "run_date": run_date, "version": VERSION, "universe": universe_n,
        "graded": sum(r["grade"] in GRADE_LETTERS for r in scored),
        "vetoed": sum(r["grade"] == "VETOED" for r in scored),
        "insufficient": sum(r["grade"] == "INSUFFICIENT" for r in scored),
        "names": scored, "portfolio": portfolio, "formation": state,
    }
    report_md = render_report(doc, transfers, uncached, updated)

    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / f"scout-run-{run_date}.md"
    json_path = reports_dir / f"scout-grades-{run_date}.json"
    md_path.write_text(report_md, encoding="utf-8")
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False),
                         encoding="utf-8")
    return doc, md_path, json_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stock Scout grading run (spec §5.5)")
    ap.add_argument("--universe", default="universe.csv")
    ap.add_argument("--cache", default="cache", help="fundamentals cache dir (§3.2)")
    ap.add_argument("--date", default=None, help="run date YYYY-MM-DD (default: today)")
    ap.add_argument("--no-formation", action="store_true",
                    help="skip the v3 formation update (§5.6)")
    ap.add_argument("--telegram", action="store_true",
                    help="send the md summary head + newest datasheet via tg.py")
    args = ap.parse_args(argv)
    run_date = args.date or date.today().isoformat()

    doc, md_path, json_path = run(
        universe_path=args.universe, cache_dir=args.cache, run_date=run_date,
        no_formation=args.no_formation, state_path=formation.STATE_FILE,
        reports_dir="reports")

    print(f"graded {doc['graded']} · vetoed {doc['vetoed']} · insufficient "
          f"{doc['insufficient']} of universe {doc['universe']}")
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
