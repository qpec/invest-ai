"""The Thesis Builder — the Scout's top 1% becomes draft theses for the Gate
(THESIS-DESIGN.md; thesis content per FR2).

    python thesis.py build CROX --sec-data <dir> --prices <dir>
    python thesis.py batch --sec-data <dir> --prices <dir>       # the current top 1%
    python thesis.py ratify CROX                                 # the Gate step (FR9)

Three rules carried from the design, enforced here rather than hoped for:

- **Draft, never committed.** The builder's schema has no conviction and no circle-of-
  competence field; those are asked of the owner at `ratify` (FR9), and only a ratified
  thesis reaches `theses/committed/` where the monitor looks.
- **Every trigger machine-validatable.** A `metric` trigger may reference only the
  METRICS registry below (the same scoring.evaluate values the live grader uses); an
  `event`/`narrative` trigger must be one yes/no question answerable from public
  information. `validate()` refuses anything else, at build AND at ratify.
- **No price triggers.** The registry deliberately carries no quote-derived metric: a
  falling price with an intact thesis is an opportunity (FR4), and the stock does not
  know what you paid (FR7). Triggers are about the business.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

import inversion
import llm
import scorecard
import scoring

THESES_DIR = Path("theses")
TOP_FRACTION = 0.01                  # "the best 1%" — of the whole screened universe
WEB_SEARCH_BUDGET = 20               # searches per deep-research run
MONITOR_SEARCH_BUDGET = 5            # searches per weekly trigger check

# --- The metric registry (§3 of the design) ----------------------------------------------
# name -> (key in scoring.evaluate()'s metrics dict, unit, transform). These are the ONLY
# quantities a metric trigger may test. All owner-facing units are what the name says;
# v_yield is a fraction in scoring and is normalized to percent here.

METRICS = {
    "owner_fcf_margin_pct": ("ofcf_margin", "% of TTM revenue", None),
    "owner_fcf_yield_pct": ("v_yield", "% of own EV", lambda v: v * 100.0),
    "revenue_growth_pct": ("rev_growth", "%/yr (annual CAGR)", None),
    "roic_pct": ("roic", "% (Greenblatt)", None),
    "gross_margin_pct": ("gm_level", "% of TTM revenue", None),
    "net_debt_to_ebitda": ("nd2e", "x (TTM)", None),
    "sbc_pct_of_revenue": ("sbc_pct", "% of TTM revenue", None),
    "share_count_trend_pct_per_year": ("share_trend", "%/yr (split-adjusted)", None),
    "accrual_divergence_pct": ("accrual", "% of TTM revenue (NI incl NCI - OCF)", None),
    "owner_fcf_usd": ("owner_fcf", "USD (TTM)", None),
}

TRIGGER_KINDS = ("metric", "event", "narrative")
TRIGGER_OPS = ("<", "<=", ">", ">=")
TRIGGER_ACTIONS = ("break", "review")
MIN_TRIGGERS = 3                    # FR2: testable invalidation triggers, plural and real
CONVICTION_LEVELS = ("low", "medium", "high")

# --- The strict tool schema (the thesis draft, FR2 minus the owner-only fields) ----------

_TRIGGER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": list(TRIGGER_KINDS)},
        "statement": {"type": "string"},
        "action": {"type": "string", "enum": list(TRIGGER_ACTIONS)},
        "metric": {"type": ["string", "null"]},
        # No enum here on purpose: a null-bearing enum is exactly the shape strict-mode
        # schema compilers dislike, and validate() already refuses any op outside
        # TRIGGER_OPS — the code-level check is the contract, the schema stays plain.
        "op": {"type": ["string", "null"],
               "description": f"One of {', '.join(TRIGGER_OPS)} for metric triggers; "
                              f"null otherwise."},
        "threshold": {"type": ["number", "null"]},
        "consecutive_checks": {"type": ["integer", "null"]},
        "question": {"type": ["string", "null"]},
    },
    "required": ["id", "kind", "statement", "action", "metric", "op", "threshold",
                 "consecutive_checks", "question"],
    "additionalProperties": False,
}

THESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "business_model": {"type": "string",
                           "description": "Two sentences. If it needs more, PASS."},
        "moat": {
            "type": "object",
            "properties": {
                "kind": {"type": "string",
                         "enum": ["network_effects", "switching_costs", "cost_advantage",
                                  "brand_trust", "regulatory", "none"]},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["kind", "evidence"],
            "additionalProperties": False,
        },
        "owner_earnings_picture": {"type": "string"},
        "valuation_anchor": {
            "type": "object",
            "properties": {
                "metric": {"type": "string"},
                "value": {"type": ["number", "null"]},
                "statement": {"type": "string"},
            },
            "required": ["metric", "value", "statement"],
            "additionalProperties": False,
        },
        "horizon_years": {"type": "integer"},
        "ten_year_statement": {"type": "string"},
        "bear_case": {"type": "string",
                      "description": "Must address every severe fragility finding by name."},
        "triggers": {"type": "array", "items": _TRIGGER_SCHEMA},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["symbol", "business_model", "moat", "owner_earnings_picture",
                 "valuation_anchor", "horizon_years", "ten_year_statement", "bear_case",
                 "triggers", "sources"],
    "additionalProperties": False,
}

RECORD_THESIS_TOOL = {
    "name": "record_thesis",
    "description": "Record the finished draft thesis. Call exactly once, after the "
                   "extensive report and the executive summary have been written as text.",
    "strict": True,
    "input_schema": THESIS_SCHEMA,
}

SUMMARY_HEADING = "## Executive summary"

SYSTEM_PROMPT = """You are the thesis builder inside stock-agentcy, a Buffett/Munger/Naval
portfolio-oversight system. You write DRAFT investment theses for the owner's Gate session.
The owner — not you — decides conviction, circle-of-competence fit, and whether to buy.
The system advises and monitors; it never executes trades.

The framework you must apply (the Constitution):
- Buffett: wonderful businesses at fair prices. Moat with evidence, owner earnings (free
  cash flow the owner could extract) over reported EPS, the 10-year test. If the business
  model and its moat cannot be explained in two sentences, say so plainly.
- Munger: inversion. How would this lose the owner's money? Your bear case must address,
  by name, every severe fragility finding in the packet — you may argue against one, but
  never ignore one.
- Honesty rules: cite sources for factual claims from your research; no price targets; a
  weakness stated plainly beats a strength oversold. Ignore cost basis and entry timing.

Your deliverable, in this exact order:
1. THE EXTENSIVE REPORT as ordinary text: business model, moat evidence, owner-earnings
   history and quality, valuation work anchored on the metrics provided, competitive
   landscape from your research, the bear case, and what you could not verify.
2. A final text section headed exactly "{summary_heading}" — one page, for a
   non-technical reader: what the business does, why it might compound, what would make
   us leave, what it costs to be wrong. No jargon, no ratios without translation.
3. ONE call to record_thesis with the structured draft.

Trigger discipline (the part the machine holds you to):
- At least {min_triggers} triggers, at least one of kind "metric".
- A "metric" trigger tests ONE registry metric against a threshold. The registry, with
  units, is: {registry}. No other quantity is checkable — do not invent one.
- An "event" or "narrative" trigger is ONE yes/no question about public information,
  with its evidence standard inside the question. Events are facts (a contract lost, a
  CEO departure); narratives are judgements and their action MUST be "review".
- No price-based triggers: a falling quote with an intact thesis is an opportunity, not
  an invalidation. Triggers test the business.
- Set "action": "break" only where the pre-committed answer is sell; "review" where the
  owner should re-examine. Metric thresholds should demand persistence
  (consecutive_checks >= 2) unless a single reading is genuinely conclusive.
"""


def _system_prompt() -> str:
    registry = "; ".join(f"{name} ({unit})" for name, (_, unit, _) in METRICS.items())
    return SYSTEM_PROMPT.format(summary_heading=SUMMARY_HEADING,
                                min_triggers=MIN_TRIGGERS, registry=registry)


# --- Metric evaluation (shared with monitor.py) ------------------------------------------

def metric_value(name: str, bundle: dict, evaluated: dict | None = None):
    """The current value of a registry metric for one Bundle, via scoring.evaluate — the
    same code path the grader runs, so the monitor cannot disagree with the live run."""
    spec = METRICS.get(name)
    if spec is None:
        raise KeyError(f"not a registry metric: {name}")
    key, _, transform = spec
    metrics = evaluated if evaluated is not None else scoring.evaluate(bundle)
    value = metrics.get(key)
    if value is None:
        return None
    return transform(value) if transform else float(value)


# --- Validation (build AND ratify refuse what the monitor could not check) ---------------

def validate(doc: dict, *, symbol: str | None = None) -> list[str]:
    """Problems with a thesis draft, empty when it is monitorable. Checks the cross-field
    rules the strict schema cannot express."""
    problems: list[str] = []
    if symbol and doc.get("symbol") != symbol:
        problems.append(f"symbol mismatch: thesis says {doc.get('symbol')!r}")
    for field in ("conviction", "circle_of_competence"):
        if field in doc:
            problems.append(f"{field} is owner-only (FR9) and may not come from the builder")

    triggers = doc.get("triggers") or []
    if len(triggers) < MIN_TRIGGERS:
        problems.append(f"only {len(triggers)} trigger(s); FR2 demands testable "
                        f"invalidation, minimum {MIN_TRIGGERS}")
    if not any(t.get("kind") == "metric" for t in triggers):
        problems.append("no metric trigger; at least one must be mechanically checkable")

    seen_ids = set()
    for t in triggers:
        tid = t.get("id") or "?"
        if tid in seen_ids:
            problems.append(f"duplicate trigger id {tid!r}")
        seen_ids.add(tid)
        kind = t.get("kind")
        if kind not in TRIGGER_KINDS:
            problems.append(f"trigger {tid}: unknown kind {kind!r}")
            continue
        if t.get("action") not in TRIGGER_ACTIONS:
            problems.append(f"trigger {tid}: unknown action {t.get('action')!r}")
        if kind == "metric":
            if t.get("metric") not in METRICS:
                problems.append(f"trigger {tid}: metric {t.get('metric')!r} is not in "
                                f"the registry, so no machine can check it")
            if t.get("op") not in TRIGGER_OPS:
                problems.append(f"trigger {tid}: op {t.get('op')!r} invalid")
            if not isinstance(t.get("threshold"), (int, float)):
                problems.append(f"trigger {tid}: threshold missing")
            checks = t.get("consecutive_checks")
            if checks is not None and (not isinstance(checks, int) or checks < 1):
                problems.append(f"trigger {tid}: consecutive_checks must be >= 1")
        else:
            question = t.get("question") or ""
            if not question.strip():
                problems.append(f"trigger {tid}: {kind} trigger needs a yes/no question")
            if kind == "narrative" and t.get("action") != "review":
                problems.append(f"trigger {tid}: a narrative trigger may only send to "
                                f"review — judgement never fires the sell rule alone")
    return problems


# --- The research packet ------------------------------------------------------------------

def _fmt(value, digits=1):
    return "n/a" if value is None else f"{value:,.{digits}f}"


def packet(bundle: dict, card: dict, inv: dict, *, name=None, sector=None) -> str:
    """The metrics half of the builder's grounding: both judgements, unmerged, plus the
    registry's current values so trigger thresholds are set against known numbers."""
    evaluated = scoring.evaluate(bundle)
    lines = [f"SYMBOL: {bundle.get('symbol')}  ({name or 'name unknown'} — "
             f"{sector or 'sector unknown'})",
             f"market cap: {_fmt(bundle.get('market_cap'), 0)} USD",
             "",
             "== The Owner's Scorecard (Buffett: how good is the business) ==",
             f"score: {card.get('score')}/{card.get('available_max')} = {card.get('pct')}% "
             f"-> band {card.get('band')} (evidence: {card.get('evidence')})"]
    why = card.get("why") or {}
    for part in ("strongest", "weakest"):
        sentence = (why.get(part) or {}).get("sentence")
        if sentence:
            lines.append(f"  {part}: {sentence}")
    lines += ["", "== The Inversion Layer (Munger: how it breaks) ==",
              f"verdict: {inv.get('verdict')} — {inv.get('verdict_meaning')}"]
    for mode in inv.get("failure_modes", [])[:6]:
        lines.append(f"  - {mode}")
    severe = (inv.get("coverage") or {}).get("severe", 0)
    lines.append(f"severe findings: {severe} — the bear case MUST address each by name."
                 if severe else "severe findings: none.")
    lines += ["", "== Current registry metrics (set trigger thresholds against these) =="]
    for metric_name in METRICS:
        value = metric_value(metric_name, bundle, evaluated)
        unit = METRICS[metric_name][1]
        lines.append(f"  {metric_name} = {_fmt(value)}  [{unit}]")
    return "\n".join(lines)


def _grounding(symbol: str, max_chars: int = 12000) -> str:
    """Filings text via edgartools (MIT; desk-side only, guarded import — the design's
    §4). Absent or failing, the packet says so instead of failing the run."""
    try:
        from edgar import Company, set_identity  # type: ignore
    except ImportError:
        return ("[filings text unavailable: edgartools not installed — research rests on "
                "the metrics packet and web search. `pip install -r "
                "requirements-research.txt` enables it.]")
    try:
        import os
        set_identity(os.environ.get("EDGAR_IDENTITY", "stock-agentcy thesis builder"))
        tenk = Company(symbol).latest("10-K").obj()
        parts = []
        for item, label in (("Item 1", "BUSINESS"), ("Item 1A", "RISK FACTORS"),
                            ("Item 7", "MD&A")):
            text = tenk[item]
            if text:
                parts.append(f"== 10-K {label} (clipped) ==\n{text[:max_chars // 3]}")
        return "\n\n".join(parts) or "[10-K sections came back empty]"
    except Exception as error:  # noqa: BLE001 — grounding must degrade, never fail a run
        return f"[filings text unavailable: {type(error).__name__}: {error}]"


# --- Build --------------------------------------------------------------------------------

def build(symbol: str, bundle: dict, card: dict, inv: dict, *, client=None,
          theses_dir: Path = THESES_DIR, name=None, sector=None,
          with_filings: bool = True) -> dict:
    """One deep-research run -> theses/drafts/<SYM>/{thesis.json,report.md,summary.md}."""
    client = client or llm.Client()
    grounding = _grounding(symbol) if with_filings else "[filings text skipped]"
    user = (f"Write the draft thesis for {symbol}.\n\n"
            f"{packet(bundle, card, inv, name=name, sector=sector)}\n\n{grounding}\n\n"
            f"Research the company on the web before judging: competitive landscape, "
            f"management, anything the filings and metrics cannot show. Then deliver the "
            f"report, the executive summary, and the record_thesis call.")
    tools = [dict(llm.WEB_SEARCH_TOOL, max_uses=WEB_SEARCH_BUDGET), RECORD_THESIS_TOOL]
    result = client.run(system=_system_prompt(), user=user, tools=tools,
                        capture_tool="record_thesis")
    draft = result.get("captured")
    if draft is None:
        raise llm.LLMError(f"{symbol}: the run ended ({result.get('stop_reason')}) "
                           f"without calling record_thesis — no thesis was recorded")
    problems = validate(draft, symbol=symbol)

    doc = {
        "symbol": symbol, "status": "draft", "version": 0,
        "built_at": _dt.date.today().isoformat(),
        "metrics_snapshot": {"scorecard_pct": card.get("pct"), "band": card.get("band"),
                             "inversion_verdict": inv.get("verdict"),
                             "market_cap": bundle.get("market_cap")},
        "thesis": draft,
        "validation_problems": problems,
        "usage": result.get("usage"),
    }
    out = Path(theses_dir) / "drafts" / symbol
    out.mkdir(parents=True, exist_ok=True)
    (out / "thesis.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    report, summary = _split_report(result.get("text") or "")
    (out / "report.md").write_text(report, encoding="utf-8")
    (out / "summary.md").write_text(summary, encoding="utf-8")
    return doc


def _split_report(text: str) -> tuple[str, str]:
    """The report text and the executive summary, split on the demanded heading. A run
    that skipped the heading still yields both files — with the gap named, not hidden."""
    index = text.find(SUMMARY_HEADING)
    if index < 0:
        return (text or "[no report text was produced]",
                "[the run produced no executive-summary section — read report.md]")
    return text[:index].rstrip() or "[report text was empty]", text[index:].strip()


def top_symbols(rows: list[dict], universe_size: int) -> list[dict]:
    """The best 1% of the screened universe: scoreable names ranked the scorecard's own
    way (evidence tier first, then percentage)."""
    import math
    scoreable = [r for r in rows if r["card"].get("pct") is not None
                 and r["card"]["band"] not in (scorecard.VETOED_BAND,
                                               scorecard.NO_PRICE_BAND)]
    count = max(1, math.ceil(universe_size * TOP_FRACTION))
    return sorted(scoreable, key=lambda r: scorecard.rank_key(r["card"]))[:count]


# --- Ratify (the Gate step, FR9) ----------------------------------------------------------

def ratify(symbol: str, *, theses_dir: Path = THESES_DIR, ask=input) -> dict:
    """Owner ratification: the FR9 questions are ASKED, the triggers re-validated, and
    only then does the thesis move to committed/ where the monitor reads it."""
    draft_path = Path(theses_dir) / "drafts" / symbol / "thesis.json"
    if not draft_path.exists():
        raise FileNotFoundError(f"no draft thesis for {symbol} at {draft_path}")
    doc = json.loads(draft_path.read_text(encoding="utf-8"))
    problems = validate(doc.get("thesis") or {}, symbol=symbol)
    if problems:
        raise ValueError(f"{symbol}: not ratifiable until fixed (edit the draft): "
                         + "; ".join(problems))

    conviction = ask(f"Conviction for {symbol} ({'/'.join(CONVICTION_LEVELS)}): ").strip().lower()
    if conviction not in CONVICTION_LEVELS:
        raise ValueError(f"conviction must be one of {CONVICTION_LEVELS}")
    circle = ask("Inside your circle of competence? Explain in one line (empty = no): ").strip()
    if not circle:
        raise ValueError("outside the circle of competence -> PASS (the framework wins)")

    doc.update({"status": "committed", "version": 1,
                "ratified_at": _dt.date.today().isoformat(),
                "conviction": conviction, "circle_of_competence": circle,
                "trigger_state": {}})
    committed = Path(theses_dir) / "committed"
    committed.mkdir(parents=True, exist_ok=True)
    path = committed / f"{symbol}.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


# --- CLI ----------------------------------------------------------------------------------

def _load_rows(args) -> tuple[list[dict], dict]:
    import picks
    import secsv
    meta = picks._load_meta(Path(args.universe))
    prices = picks._load_prices(Path(args.prices) if args.prices else None)
    bundles = secsv.bundles(args.sec_data, args.as_of, meta=meta, prices=prices)
    scored = {r["symbol"]: r for r in scoring.score_universe(bundles)}
    rows = []
    for bundle in bundles:
        sym = bundle["symbol"]
        info = meta.get(sym) or {}
        rows.append({"symbol": sym, "bundle": bundle, "name": info.get("name"),
                     "sector": info.get("sector"),
                     "card": scorecard.scorecard(bundle, scored_row=scored.get(sym)),
                     "inversion": inversion.inversion(bundle, prices=prices,
                                                      scored_row=scored.get(sym))})
    return rows, prices


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("build", "batch"):
        p = sub.add_parser(cmd)
        if cmd == "build":
            p.add_argument("symbols", nargs="+")
        p.add_argument("--sec-data", required=True)
        p.add_argument("--prices")
        p.add_argument("--universe", default="universe.csv")
        p.add_argument("--as-of", default=_dt.date.today().isoformat())
        p.add_argument("--theses-dir", default=str(THESES_DIR))
        p.add_argument("--no-filings", action="store_true")
    p = sub.add_parser("ratify")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--theses-dir", default=str(THESES_DIR))
    args = parser.parse_args(argv)

    if args.command == "ratify":
        for symbol in args.symbols:
            doc = ratify(symbol, theses_dir=Path(args.theses_dir))
            print(f"{symbol}: committed (conviction={doc['conviction']}) — "
                  f"the weekly monitor now owns its triggers")
        return 0

    rows, _ = _load_rows(args)
    if args.command == "build":
        chosen = [r for r in rows if r["symbol"] in set(args.symbols)]
        missing = set(args.symbols) - {r["symbol"] for r in chosen}
        if missing:
            print(f"not in the screened universe: {', '.join(sorted(missing))}",
                  file=sys.stderr)
    else:
        chosen = top_symbols(rows, len(rows))
        print(f"top {TOP_FRACTION:.0%} of {len(rows)} screened = {len(chosen)} names: "
              + ", ".join(r["symbol"] for r in chosen))

    total_cost = 0.0
    for row in chosen:
        doc = build(row["symbol"], row["bundle"], row["card"], row["inversion"],
                    theses_dir=Path(args.theses_dir), name=row["name"],
                    sector=row["sector"], with_filings=not args.no_filings)
        cost = (doc.get("usage") or {}).get("estimated_cost_usd") or 0.0
        total_cost += cost
        state = "OK" if not doc["validation_problems"] else \
            f"NEEDS EDITS ({len(doc['validation_problems'])} problem(s))"
        print(f"{row['symbol']}: draft written [{state}] ~${cost:.2f}")
    print(f"batch estimated cost ~${total_cost:.2f}. Drafts await the Gate: "
          f"`python thesis.py ratify <SYM>`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
