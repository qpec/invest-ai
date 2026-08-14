"""The Low-Cap Desk's thesis builder — Pillar 3 of the lane's constitution
(docs/plans/2026-08-14-low-cap-desk-design.md): the scuttlebutt beat.

Run BY an agent harness, exactly like the main desk's thesis.py — same three beats,
same seam, its own tree:

    python lowcap_thesis.py brief SYM --sec-data <dir> --prices <dir>   # 1. work order
    <the agent researches; writes report.md / summary.md / scuttlebutt.md / thesis.json>
    python lowcap_thesis.py record SYM                                  # 2. validation
    python thesis.py ratify SYM --theses-dir theses-lowcap              # 3. the Gate

    python lowcap_thesis.py batch --sec-data <dir> --prices <dir>       # the shortlists

What is DIFFERENT from the main desk, and why:

- **The candidates come from the lane**, not the scorecard rank: names inside the
  $50M–$2B band that pass the Forge and on which at least one lens speaks
  (`lowcap.shortlists`). A Forged-out name is refused at `record` even if someone
  hand-writes it a work order — the Hell-No ordering holds mechanically.
- **The work order carries the lane packet**: the Forge verdict with its findings and
  the four lens verdicts SIDE BY SIDE, never merged — the agent argues with lenses, it
  never averages them.
- **`scuttlebutt.md` is a required artifact** (Fisher's field work, Cassel's edge): the
  qualitative half no XBRL tag carries — owner-operator evidence, insider alignment,
  share-structure cleanliness, promotion red flags, niche dominance. Missing or empty
  is a refusal, exactly like the other artifacts.
- **Everything else is deliberately identical.** Same thesis.json schema, same trigger
  discipline (registry metrics only, no price triggers, narrative can only review),
  same `record` mechanics, same human-only CLI Gate, and the same weekly monitor over
  `theses-lowcap/committed` via `python monitor.py run --theses-dir theses-lowcap ...`.
  A different philosophy earns a different packet, never a weaker contract.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

import deskwork
import lowcap
import thesis as thesis_mod

LOWCAP_THESES_DIR = Path("theses-lowcap")

# Pillar 3 — the questions the agent must answer from field work, not from the packet.
SCUTTLEBUTT_QUESTIONS = (
    "Owner-operators: who runs this, do they own a meaningful stake bought with their "
    "own money (DEF 14A beneficial-ownership table, Form 4 open-market purchases), and "
    "is there a founder still at the wheel?",
    "Share structure: one class of common? Options/warrants/converts outstanding vs "
    "the share count (10-K cover and notes)? Any S-3 shelf or 424B activity — the "
    "quiet dilution machinery — in the last two years?",
    "Promotion check: paid stock promotion, newsletter pumping, reverse-merger or "
    "shell history, an auditor nobody has heard of, SEC trading suspensions. Absence "
    "of red flags is a finding; say what you checked.",
    "Niche dominance: does this company dominate a small but expanding market, and "
    "what do customers/competitors/suppliers say (reviews, trade press, job boards)?",
    "Why is it mispriced: no analyst coverage, index exclusion, forced selling, an "
    "'ick' story — name the reason the opportunity exists, or say plainly that you "
    "could not find one (which is itself a warning).",
)

LANE_FRAMEWORK = """## The lane's constitution (what makes this desk different)

- **There is no size premium.** Small caps are a hunting ground, not a factor: the
  edge is neglect plus patient small capital, and it is real only where nobody is
  looking. Your job is to find WHY nobody is looking and whether they are wrong.
- **Survive first.** The Forge has already probed dilution, runway, distress and
  delisting. Your bear case must address, BY NAME, every Forge finding in the packet —
  argue with one if the evidence supports it; never ignore one.
- **The lenses are voices, not votes.** Graham, GARP, Downside and Compounder each
  spoke, stayed silent, or refused — the packet shows all four. Engage the ones that
  spoke; explain what the silent ones are seeing; NEVER combine them into a score.
- **Dilution is the enemy.** In this universe the company that funds itself with your
  ownership is the default, not the exception. Treat any financing dependency as a
  first-order risk, not a footnote.
- **Illiquidity is the toll, the balance sheet is the insurance.** Exit takes weeks
  down here; only a business that cannot be forced into distress is safe to hold
  through that. Position sizing stays the owner's — never advise an amount."""


def lane_packet(lane: dict) -> str:
    """The lane's half of the grounding: the Forge with its findings, the four lens
    verdicts side by side, and the lane metrics — assembled, never combined."""
    forge = lane.get("forge") or {}
    coverage = forge.get("coverage") or {}
    lines = ["== The Forge (survive first) ==",
             f"verdict: {forge.get('verdict')} — {forge.get('verdict_meaning')}",
             f"probes measured: {coverage.get('measured_count')}/{coverage.get('total')}"
             + (" — evidence is THIN, said out loud" if coverage.get("thin") else "")]
    findings = forge.get("findings") or []
    if findings:
        lines.append("findings — the bear case MUST address each by name:")
        lines += [f"  - {finding}" for finding in findings]
    else:
        lines.append("findings: none.")
    lines += ["", "== The four lenses (side by side — voices, never votes) =="]
    for name in lowcap.LENS_ORDER:
        lens_result = (lane.get("lenses") or {}).get(name) or {}
        lines.append(f"  {name.upper()}: {lens_result.get('verdict')} — "
                     f"{lens_result.get('detail')}")
    lines += ["", "== Lane metrics =="]
    metrics = lane.get("metrics") or {}
    for key in ("ncav", "mcap_to_ncav", "graham_number", "price_to_graham", "pe",
                "eps_cagr_pct", "peg", "norm_fcf_yield_pct", "ev_ebit", "net_cash",
                "share_trend_pct", "current_ratio", "de_ratio"):
        lines.append(f"  {key} = {thesis_mod._fmt(metrics.get(key))}")
    return "\n".join(lines)


def brief(symbol: str, bundle: dict, card: dict, inv: dict, lane: dict, *,
          theses_dir: Path = LOWCAP_THESES_DIR, name=None, sector=None,
          with_filings: bool = True) -> Path:
    """Beat 1: the lane's work order — the main desk's grounding PLUS the lane packet
    and the scuttlebutt beat. Refuses to brief a Forged-out name: the Hell-No ordering
    is mechanical here, not editorial."""
    forge_verdict = (lane.get("forge") or {}).get("verdict")
    if forge_verdict == "Forged-out":
        findings = (lane.get("forge") or {}).get("findings") \
            or ["a named severe finding"]
        raise deskwork.OrderError(
            f"{symbol}: Forged-out — {'; '.join(findings)} A forged-out name never "
            f"consumes a lane work order.")
    out = Path(theses_dir) / "drafts" / symbol
    questions = "\n".join(f"{i}. {q}" for i, q in enumerate(SCUTTLEBUTT_QUESTIONS, 1))
    body = "\n\n".join([
        "## The lane packet (the Forge + four lenses, side by side)", "```",
        lane_packet(lane), "```",
        "## The research packet (both main-desk judgements, unmerged)", "```",
        thesis_mod.packet(bundle, card, inv, name=name, sector=sector), "```",
        "## Filings text", "```",
        thesis_mod._grounding(symbol) if with_filings
        else "[filings text skipped by --no-filings]",
        "```",
        LANE_FRAMEWORK,
        thesis_mod.FRAMEWORK,
        "## The scuttlebutt questions (answer ALL of these in scuttlebutt.md)\n\n"
        + questions,
        thesis_mod.TRIGGER_RULES.format(min_triggers=thesis_mod.MIN_TRIGGERS),
        deskwork.schema_block(thesis_mod.THESIS_SCHEMA,
                              title="The thesis schema (thesis.json)"),
    ])
    text = deskwork.order(
        title=f"Draft LOW-CAP investment thesis — {symbol}"
              + (f" ({name})" if name else ""),
        why=f"{symbol} is on the Low-Cap Desk: inside the $50M–$2B band, past the "
            f"Forge, and at least one lens speaks. Small caps are a different game — "
            f"the edge is neglect, the risk is dilution, and the qualitative half "
            f"(scuttlebutt) is where the work is. You research and write; the owner "
            f"decides conviction and whether to buy (FR9); nothing here executes "
            f"trades (FR11).",
        artifacts=[
            (f"{out}/report.md", "the research: business model, why the mispricing "
                                 "exists, owner-earnings quality, the lens cases "
                                 "engaged one by one, the bear case naming every "
                                 "Forge finding, and what you could NOT verify"),
            (f"{out}/scuttlebutt.md", "the field work: every scuttlebutt question "
                                      "answered with sources — owner-operators, share "
                                      "structure, promotion check, niche, why it is "
                                      "mispriced. 'Could not verify' is an answer; "
                                      "silence is not"),
            (f"{out}/summary.md", f"one page for a NON-TECHNICAL reader, opening with "
                                  f"the heading `{thesis_mod.SUMMARY_HEADING}`, and "
                                  f"stating plainly that this is an illiquid small "
                                  f"cap: what it does, why it might be mispriced, "
                                  f"what would make us leave, what being wrong costs"),
            (f"{out}/thesis.json", "the structured draft matching the schema below"),
        ],
        steps=[
            "Read the lane packet first — the Forge findings and which lenses spoke.",
            "Do the scuttlebutt work with your own web tools: the five questions, "
            f"roughly {thesis_mod.WEB_SEARCH_BUDGET} searches; primary sources "
            "(filings, proxies, Form 4s) beat commentary.",
            "Write `report.md`, then `scuttlebutt.md`, then `summary.md`, then "
            "`thesis.json`.",
            "Run the validation command below and fix anything it reports.",
        ],
        rules=[
            "Every factual claim from research carries a source URL in `sources`.",
            "The bear case names every Forge finding AND every severe fragility "
            "finding from the packets.",
            "Engage each lens that spoke by name; never average or combine lenses.",
            "No conviction, no circle-of-competence, no price target, no buy "
            "recommendation, no position size — none of those are yours to write.",
            "If the mispricing has no findable reason, say so in the report — a "
            "cheap-looking name with no neglect story is usually priced right.",
        ],
        body=body,
        finish=f"python lowcap_thesis.py record {symbol} --theses-dir {theses_dir}"
               f" --model <the model id you are running>",
    )
    path = out / deskwork.ORDER_NAME
    deskwork.write_atomic(path, text)
    deskwork.write_json(out / "packet.json", {
        "symbol": symbol, "name": name, "sector": sector, "lane": "lowcap",
        "prepared_at": _dt.date.today().isoformat(),
        "scorecard": {"pct": card.get("pct"), "band": card.get("band"),
                      "evidence": card.get("evidence")},
        "inversion": {"verdict": inv.get("verdict"),
                      "severe": (inv.get("coverage") or {}).get("severe"),
                      "failure_modes": inv.get("failure_modes")},
        "lowcap": {"eligibility": lane.get("eligibility"),
                   "forge": {"verdict": forge_verdict,
                             "findings": (lane.get("forge") or {}).get("findings"),
                             "coverage": (lane.get("forge") or {}).get("coverage")},
                   "lenses": {n: {"verdict": (lane["lenses"].get(n) or {}).get("verdict"),
                                  "detail": (lane["lenses"].get(n) or {}).get("detail")}
                              for n in lowcap.LENS_ORDER},
                   "metrics": lane.get("metrics")},
        "metrics": {m: thesis_mod.metric_value(m, bundle)
                    for m in thesis_mod.METRICS},
        "market_cap": bundle.get("market_cap"),
    })
    return path


def record(symbol: str, *, theses_dir: Path = LOWCAP_THESES_DIR, model=None,
           transcript: Path | None = None) -> dict:
    """Beat 2: the main desk's whole mechanical contract PLUS the lane's rules —
    scuttlebutt.md exists and is non-empty, and a Forged-out packet is a refusal even
    if someone hand-wrote the order. A different philosophy never means a weaker
    contract."""
    out = Path(theses_dir) / "drafts" / symbol
    lane_problems = []
    scuttlebutt = out / "scuttlebutt.md"
    if not scuttlebutt.exists():
        lane_problems.append("scuttlebutt.md was not written — Pillar 3 is the lane's "
                             "research half, not an optional extra")
    elif not scuttlebutt.read_text(encoding="utf-8").strip():
        lane_problems.append("scuttlebutt.md is empty")
    packet_path = out / "packet.json"
    packet_doc = deskwork.read_json(packet_path) if packet_path.exists() else {}
    if ((packet_doc.get("lowcap") or {}).get("forge") or {}).get("verdict") \
            == "Forged-out":
        lane_problems.append("the packet records a Forged-out verdict — a named severe "
                             "finding closed this door before the research began")
    try:
        doc = thesis_mod.record(symbol, theses_dir=theses_dir, model=model,
                                transcript=transcript)
    except deskwork.OrderError as error:
        if lane_problems:
            raise deskwork.OrderError(
                str(error) + "\n  - " + "\n  - ".join(lane_problems)) from None
        raise
    doc["lane"] = "lowcap"
    if lane_problems:
        doc["validation_problems"] = lane_problems
        deskwork.write_json(out / "record.json", doc)
        raise deskwork.OrderError(
            f"{symbol}: the draft is NOT accepted (lane rules):\n  - "
            + "\n  - ".join(lane_problems))
    deskwork.write_json(out / "record.json", doc)
    return doc


def _lane_rows(rows: list[dict], prices) -> list[dict]:
    """thesis._load_rows output -> lane candidate rows carrying the lowcap analysis."""
    out = []
    for row in rows:
        bundle = row["bundle"]
        if not lowcap.eligible(bundle)[0]:
            continue
        out.append({**row, "lowcap": lowcap.analyze(bundle, prices=prices)})
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("brief", "batch"):
        p = sub.add_parser(cmd, help="write the lane's work order(s)")
        if cmd == "brief":
            p.add_argument("symbols", nargs="+")
        p.add_argument("--sec-data", required=True)
        p.add_argument("--prices")
        p.add_argument("--universe", default="universe.csv")
        p.add_argument("--as-of", default=_dt.date.today().isoformat())
        p.add_argument("--theses-dir", default=str(LOWCAP_THESES_DIR))
        p.add_argument("--enrich-cache", help="tier-2 companyfacts cache: lets names "
                                              "beyond the bulk export be drafted too")
        p.add_argument("--no-filings", action="store_true")
    p = sub.add_parser("record", help="validate what the agent wrote (lane rules too)")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--theses-dir", default=str(LOWCAP_THESES_DIR))
    p.add_argument("--model", help="the model id you are running; a readable harness "
                                   "transcript wins, and a mismatch is refused")
    args = parser.parse_args(argv)

    if args.command == "record":
        failures = 0
        for symbol in args.symbols:
            try:
                doc = record(symbol, theses_dir=Path(args.theses_dir), model=args.model)
                print(f"  {deskwork.model_note(doc['agent'])}")
                print(f"{symbol}: lane draft ACCEPTED — ready for the Gate "
                      f"(`python thesis.py ratify {symbol} "
                      f"--theses-dir {args.theses_dir}`)")
            except deskwork.OrderError as error:
                failures += 1
                print(str(error), file=sys.stderr)
        return 1 if failures else 0

    rows, prices = thesis_mod._load_rows(args)
    lane_rows = _lane_rows(rows, prices)
    by_symbol = {row["symbol"]: row for row in lane_rows}
    if args.command == "brief":
        chosen = [by_symbol[s] for s in args.symbols if s in by_symbol]
        missing = set(args.symbols) - set(by_symbol)
        if missing:
            print(f"not in the lane's band (or not screened): "
                  f"{', '.join(sorted(missing))}", file=sys.stderr)
    else:
        lists = lowcap.shortlists(lane_rows)
        picked = {entry["symbol"] for entries in lists.values() for entry in entries}
        chosen = [by_symbol[s] for s in sorted(picked)]
        spoke = {lens: [e["symbol"] for e in entries]
                 for lens, entries in lists.items() if entries}
        print(f"lane shortlists over {len(lane_rows)} in-band names: "
              + ("; ".join(f"{lens}: {', '.join(symbols)}"
                           for lens, symbols in spoke.items()) or "no lens speaks"))

    failures = 0
    for row in chosen:
        try:
            path = brief(row["symbol"], row["bundle"], row["card"], row["inversion"],
                         row["lowcap"], theses_dir=Path(args.theses_dir),
                         name=row["name"], sector=row["sector"],
                         with_filings=not args.no_filings)
        except deskwork.OrderError as error:
            failures += 1
            print(str(error), file=sys.stderr)
            continue
        print(f"{row['symbol']}: lane work order -> {path}")
    print(f"\n{len(chosen) - failures} lane work order(s) written. Execute each one, "
          f"then `python lowcap_thesis.py record <SYM>`. Ratified lane theses are "
          f"monitored weekly with `python monitor.py run --theses-dir "
          f"{args.theses_dir} ...`.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
