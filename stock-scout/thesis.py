"""The Thesis Builder — the Scout's top 1% becomes draft theses for the Gate
(THESIS-DESIGN.md; thesis content per FR2).

Run BY an agent harness (Claude Code, OpenClaw), not by calling an API:

    python thesis.py brief CROX --sec-data <dir> --prices <dir>   # 1. the work order
    <the agent researches and writes thesis.json / report.md / summary.md>
    python thesis.py record CROX                                  # 2. mechanical validation
    python thesis.py ratify CROX                                  # 3. the Gate (FR9, human)

    python thesis.py batch --sec-data <dir> --prices <dir>        # briefs for the top 1%

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

import deskwork
import inversion
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
    # --- the engine (cash) ---------------------------------------------------------
    "owner_fcf_margin_pct": ("ofcf_margin", "% of TTM revenue", None),
    "owner_fcf_usd": ("owner_fcf", "USD (TTM)", None),
    "owner_fcf_per_share_usd": ("fcf_per_share", "USD/share (TTM, split-adjusted)", None),
    "fcf_conversion_pct": ("fcf_conversion", "% of net income (incl NCI)", None),
    "cash_conversion_pct": ("cash_conversion", "% of TTM EBITDA", None),
    # --- growth & reinvestment ------------------------------------------------------
    "revenue_growth_pct": ("rev_growth", "%/yr (annual CAGR)", None),
    "owner_fcf_per_share_growth_pct": ("ps_growth", "%/yr (per-share CAGR)", None),
    "roic_pct": ("roic", "% (Greenblatt)", None),
    "incremental_roic_pct": ("incremental_roic", "% (3y dNOPAT/dIC)", None),
    "capex_intensity_pct": ("capex_intensity", "% of TTM revenue", None),
    "rd_intensity_pct": ("rd_intensity", "% of TTM revenue", None),
    # --- pricing power --------------------------------------------------------------
    "gross_margin_pct": ("gm_level", "% of TTM revenue", None),
    "operating_margin_pct": ("op_margin", "% of TTM revenue", None),
    "operating_margin_mad_pts": ("op_margin_mad", "margin pts (annual MAD)", None),
    # --- balance sheet --------------------------------------------------------------
    "owner_fcf_yield_pct": ("v_yield", "% of own EV", lambda v: v * 100.0),
    "net_debt_to_ebitda": ("nd2e", "x (TTM)", None),
    "interest_coverage_x": ("interest_coverage", "x (TTM EBIT/interest)", None),
    "current_ratio": ("current_ratio", "x (latest balance)", None),
    "goodwill_pct_assets": ("goodwill_pct", "% of total assets (incl intangibles)", None),
    # --- stewardship & integrity ----------------------------------------------------
    "sbc_pct_of_revenue": ("sbc_pct", "% of TTM revenue", None),
    "share_count_trend_pct_per_year": ("share_trend", "%/yr (split-adjusted)", None),
    "accrual_divergence_pct": ("accrual", "% of TTM revenue (NI incl NCI - OCF)", None),
    "tax_gap_pts": ("tax_gap", "pts of pretax (effective - cash tax)", None),
    "dividends_pct_of_ocf": ("dividends_pct_ocf", "% of TTM OCF", None),
    "buybacks_pct_of_ocf": ("buybacks_pct_ocf", "% of TTM OCF", None),
    "acquisition_spend_pct_of_ocf": ("acquisitions_pct_ocf", "% of TTM OCF", None),
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

SUMMARY_HEADING = "## Executive summary"

# The framework the agent must apply, stated once and injected into every work order.
# This is the Constitution in the form a researching agent can act on.
FRAMEWORK = """## The framework you must apply (the Constitution)

- **Buffett — what to buy.** Wonderful businesses at fair prices. A moat with EVIDENCE,
  owner earnings (the cash the owner could actually extract) over reported EPS, and the
  10-year test. If the business model and its moat cannot be explained in two sentences,
  say so plainly rather than writing three.
- **Munger — what to avoid.** Inversion: how would this lose the owner's money? Your bear
  case must address, BY NAME, every severe fragility finding in the packet. You may argue
  against one; you may never ignore one.
- **Honesty.** Cite a source for every factual claim from your research. No price targets.
  A weakness stated plainly beats a strength oversold. Ignore cost basis and entry timing
  entirely — the stock does not know what anyone paid.
- **Not yours to decide.** Conviction, circle-of-competence fit, and whether to buy belong
  to the owner at the Gate. The schema has no field for them; do not editorialise them
  into the prose either."""

TRIGGER_RULES = """## Trigger discipline (this is the part the machine holds you to)

- At least {min_triggers} triggers, of which at least one is `kind: "metric"`.
- A **metric** trigger tests ONE registry metric against a threshold. The registry is
  fixed — see the packet for the metrics, their units, and their current values. No other
  quantity is checkable; do not invent one, and do not reference a metric the packet shows
  as `n/a`.
- An **event** or **narrative** trigger is ONE yes/no question about public information,
  with its evidence standard inside the question. Events are facts (a contract lost, a CEO
  departure). Narratives are judgements, and their `action` MUST be `"review"`.
- **No price-based triggers.** A falling quote with an intact thesis is an opportunity,
  not an invalidation.
- `action: "break"` only where the pre-committed answer is sell. `"review"` where the
  owner should re-examine.
- Metric thresholds should demand persistence (`consecutive_checks` >= 2) unless a single
  reading is genuinely conclusive. Set thresholds against the CURRENT values in the
  packet, so a trigger is neither already-fired nor unreachable."""


# --- Metric evaluation (shared with monitor.py) ------------------------------------------

def registry_evaluate(bundle: dict) -> dict:
    """scoring.evaluate() plus the Registry-v2 extras (registry.py), merged — the ONE
    dict `metric_value` reads. The decision layer's own keys are computed first and the
    extras can never shadow them (the merge order guarantees it), so the grader's
    arithmetic remains the authority wherever the two could disagree."""
    import registry
    evaluated = scoring.evaluate(bundle)
    return {**registry.extras(bundle, evaluated), **evaluated}


def metric_value(name: str, bundle: dict, evaluated: dict | None = None):
    """The current value of a registry metric for one Bundle, via scoring.evaluate — the
    same code path the grader runs, so the monitor cannot disagree with the live run."""
    spec = METRICS.get(name)
    if spec is None:
        raise KeyError(f"not a registry metric: {name}")
    key, _, transform = spec
    metrics = evaluated if evaluated is not None else registry_evaluate(bundle)
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
        # A non-empty id is REQUIRED because monitor.py keys trigger_state by it. With an
        # empty id the monitor falls back to a statement prefix while this loop deduped on
        # a placeholder, so two triggers could quietly share one streak entry.
        tid = (t.get("id") or "").strip()
        if not tid:
            problems.append("a trigger has no id; the monitor keys its evidence by id")
            tid = (t.get("statement") or "?")[:40]
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
    evaluated = registry_evaluate(bundle)
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

def brief(symbol: str, bundle: dict, card: dict, inv: dict, *,
          theses_dir: Path = THESES_DIR, name=None, sector=None,
          with_filings: bool = True) -> Path:
    """Beat 1: write the work order the agent executes. Returns the order's path.

    Everything the agent needs is in one file — the packet, the schema, the framework,
    the rules, and the command that will judge the result. Nothing about the run depends
    on a credential or a network call from this process."""
    out = Path(theses_dir) / "drafts" / symbol
    body = "\n\n".join([
        "## The research packet (both judgements, unmerged)", "```",
        packet(bundle, card, inv, name=name, sector=sector), "```",
        "## Filings text", "```",
        _grounding(symbol) if with_filings else "[filings text skipped by --no-filings]",
        "```",
        FRAMEWORK,
        TRIGGER_RULES.format(min_triggers=MIN_TRIGGERS),
        deskwork.schema_block(THESIS_SCHEMA, title="The thesis schema (thesis.json)"),
    ])
    text = deskwork.order(
        title=f"Draft investment thesis — {symbol}"
              + (f" ({name})" if name else ""),
        why=f"{symbol} is in the Scout's top {TOP_FRACTION:.0%}. Write the DRAFT thesis "
            f"the owner will take to the Gate. You are researching and writing; the "
            f"owner decides conviction and whether to buy (FR9), and this system never "
            f"executes trades (FR11).",
        artifacts=[
            (f"{out}/report.md", "the extensive research: business model, moat evidence, "
                                 "owner-earnings history and quality, valuation work "
                                 "anchored on the packet's metrics, competitive "
                                 "landscape, the bear case, and what you could NOT "
                                 "verify"),
            (f"{out}/summary.md", f"one page for a NON-TECHNICAL reader, opening with "
                                  f"the heading `{SUMMARY_HEADING}`: what the business "
                                  f"does, why it might compound, what would make us "
                                  f"leave, what it costs to be wrong. No jargon, no "
                                  f"ratio without a translation"),
            (f"{out}/thesis.json", "the structured draft matching the schema below"),
        ],
        steps=[
            "Read the packet below in full — especially the fragility findings.",
            "Research the company with your own web tools: competitive landscape, "
            "management, recent events, anything the filings and metrics cannot show. "
            f"Budget roughly {WEB_SEARCH_BUDGET} searches; depth beats breadth.",
            "Write `report.md`, then `summary.md`, then `thesis.json`.",
            f"Run the validation command below and fix anything it reports.",
        ],
        rules=[
            "Every factual claim from research carries a source URL in `sources`.",
            "The bear case names every severe fragility finding from the packet.",
            "No conviction, no circle-of-competence, no price target, no buy "
            "recommendation — none of those are yours to write.",
            "If the business cannot be explained in two sentences, say so in the report "
            "and let the owner PASS rather than padding the thesis.",
        ],
        body=body,
        finish=f"python thesis.py record {symbol} --theses-dir {theses_dir}"
               f" --model <the model id you are running>",
    )
    path = out / deskwork.ORDER_NAME
    deskwork.write_atomic(path, text)
    deskwork.write_json(out / "packet.json", {
        "symbol": symbol, "name": name, "sector": sector,
        "prepared_at": _dt.date.today().isoformat(),
        "scorecard": {"pct": card.get("pct"), "band": card.get("band"),
                      "evidence": card.get("evidence")},
        "inversion": {"verdict": inv.get("verdict"),
                      "severe": (inv.get("coverage") or {}).get("severe"),
                      "failure_modes": inv.get("failure_modes")},
        "metrics": {m: metric_value(m, bundle) for m in METRICS},
        "market_cap": bundle.get("market_cap"),
    })
    return path


def record(symbol: str, *, theses_dir: Path = THESES_DIR, model: str | None = None,
           transcript: Path | None = None) -> dict:
    """Beat 3: accept or refuse what the agent wrote.

    This is the seam's whole point. The agent is trusted for research and prose; it is
    never trusted for the contract, so every rule that makes a thesis monitorable is
    re-checked here against the file on disk. A missing artifact is a refusal, not a
    warning — a thesis without its report is not a thesis."""
    out = Path(theses_dir) / "drafts" / symbol
    # Which model wrote this is part of the contract, not metadata: the owner's rule is
    # best-available only, and a year from now the record is the only thing that can say
    # whether that rule was kept.
    agent, problems = deskwork.resolve_model(model, transcript=transcript)
    for filename in ("report.md", "summary.md"):
        path = out / filename
        if not path.exists():
            problems.append(f"{filename} was not written")
        elif not path.read_text(encoding="utf-8").strip():
            problems.append(f"{filename} is empty")
    summary_path = out / "summary.md"
    if summary_path.exists() and SUMMARY_HEADING not in summary_path.read_text(
            encoding="utf-8"):
        problems.append(f"summary.md does not carry the required heading "
                        f"{SUMMARY_HEADING!r}")

    draft = deskwork.read_json(out / "thesis.json")
    problems += validate(draft, symbol=symbol)
    packet_path = out / "packet.json"
    snapshot = deskwork.read_json(packet_path) if packet_path.exists() else {}
    # A metric trigger on a metric the packet could not compute is unmonitorable from day
    # one: the monitor would report it UNCHECKED forever. Catch it here, not in week one.
    for trigger in draft.get("triggers") or []:
        if trigger.get("kind") == "metric":
            current = (snapshot.get("metrics") or {}).get(trigger.get("metric"))
            if packet_path.exists() and current is None:
                problems.append(
                    f"trigger {trigger.get('id')}: {trigger.get('metric')} is not "
                    f"computable for this name, so the monitor could never check it")

    doc = {"symbol": symbol, "status": "draft", "version": 0,
           "built_at": _dt.date.today().isoformat(),
           "agent": agent,
           "metrics_snapshot": snapshot,
           "thesis": draft, "validation_problems": problems}
    deskwork.write_json(out / "record.json", doc)
    if problems:
        raise deskwork.OrderError(
            f"{symbol}: the draft is NOT accepted:\n  - " + "\n  - ".join(problems))
    return doc


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
    # Ratify reads the RECORD, not the agent's raw file: the record only exists once
    # `record` accepted the draft, so the Gate cannot be reached around the validation.
    record_path = Path(theses_dir) / "drafts" / symbol / "record.json"
    if not record_path.exists():
        raise FileNotFoundError(
            f"no accepted draft for {symbol} — run `python thesis.py record {symbol}` "
            f"first (it validates what the agent wrote)")
    doc = json.loads(record_path.read_text(encoding="utf-8"))
    problems = validate(doc.get("thesis") or {}, symbol=symbol)
    if problems:
        raise ValueError(f"{symbol}: not ratifiable until fixed (edit the draft): "
                         + "; ".join(problems))

    # The Gate is where a draft becomes a thing the monitor acts on, so the model that
    # wrote it is re-checked here rather than trusted from a record written earlier —
    # a record.json edited by hand between beats would otherwise sail straight through.
    agent = doc.get("agent") or {}
    if not agent.get("approved"):
        raise ValueError(
            f"the draft was written by {agent.get('id') or 'an unrecorded model'}, which "
            f"is not approved for desk work (best available only: "
            f"{', '.join(deskwork.APPROVED_MODELS)}). Re-run the work order on an "
            f"approved model.")
    print(f"  {deskwork.model_note(agent)}")

    conviction = ask(f"Conviction for {symbol} ({'/'.join(CONVICTION_LEVELS)}): ").strip().lower()
    if conviction not in CONVICTION_LEVELS:
        raise ValueError(f"conviction must be one of {CONVICTION_LEVELS}")
    circle = ask("Inside your circle of competence? Explain in one line (empty = no): ").strip()
    if not circle:
        raise ValueError("outside the circle of competence -> PASS (the framework wins)")

    committed = Path(theses_dir) / "committed"
    path = committed / f"{symbol}.json"
    version, carried_state = 1, {}
    if path.exists():
        version, carried_state = _goalpost_guard(path, doc, ask=ask)

    doc.update({"status": "committed", "version": version,
                "ratified_at": _dt.date.today().isoformat(),
                "conviction": conviction, "circle_of_competence": circle,
                "trigger_state": carried_state})
    committed.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    import os
    os.replace(tmp, path)
    return doc


def _loosened(old: dict, new: dict) -> list[str]:
    """Triggers that got easier to satisfy, or vanished, between two theses. This is the
    goalpost move the architecture's guard exists to catch: rewriting the rule you were
    about to fail is how a thesis becomes unfalsifiable."""
    def by_id(thesis_doc):
        return {t.get("id"): t for t in (thesis_doc.get("triggers") or [])}
    before, after = by_id(old.get("thesis") or {}), by_id(new.get("thesis") or {})
    moved = [f"{tid} was REMOVED ({t.get('statement')!r})"
             for tid, t in before.items() if tid not in after]
    for tid, old_t in before.items():
        new_t = after.get(tid)
        if not new_t or old_t.get("kind") != "metric" or new_t.get("kind") != "metric":
            continue
        if old_t.get("metric") != new_t.get("metric"):
            moved.append(f"{tid} now tests {new_t.get('metric')} instead of "
                         f"{old_t.get('metric')}")
            continue
        o_thr, n_thr = old_t.get("threshold"), new_t.get("threshold")
        op = old_t.get("op")
        if isinstance(o_thr, (int, float)) and isinstance(n_thr, (int, float)):
            easier = (n_thr < o_thr) if op in ("<", "<=") else (n_thr > o_thr)
            if easier:
                moved.append(f"{tid} threshold moved {o_thr} -> {n_thr} (easier to pass)")
        o_ck, n_ck = old_t.get("consecutive_checks") or 1, new_t.get("consecutive_checks") or 1
        if n_ck > o_ck:
            moved.append(f"{tid} now needs {n_ck} consecutive checks, was {o_ck} "
                         f"(slower to fire)")
    return moved


def _goalpost_guard(path: Path, new_doc: dict, *, ask) -> tuple[int, dict]:
    """Re-ratifying over an existing committed thesis. Returns (version, trigger_state
    to carry) and refuses quietly-destructive rewrites.

    Three things the naive overwrite destroyed: the version history, the monitor's
    accumulated streaks, and — worst — a standing `broken` status, i.e. live sell advice.
    Re-arming a broken thesis is exactly the sunk-cost move the Constitution names, so it
    takes an explicit typed acknowledgement rather than a silent file write."""
    old = json.loads(path.read_text(encoding="utf-8"))
    version = int(old.get("version") or 1) + 1
    status = old.get("status")

    moved = _loosened(old, new_doc)
    if moved:
        print(f"GOALPOST WARNING — triggers got easier since v{old.get('version')}:")
        for line in moved:
            print(f"  - {line}")

    if status in ("broken", "under_review"):
        answer = ask(
            f"{path.stem}'s committed thesis is {status.upper()}"
            + (" — that is standing sell advice. " if status == "broken" else " — ")
            + "Re-ratifying re-arms it and clears that state. Type 're-arm' to proceed: ")
        if answer.strip().lower() != "re-arm":
            raise ValueError(f"{path.stem}: re-ratification declined; the {status} "
                             f"thesis stands")

    archive = path.parent / "history"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / f"{path.stem}.v{old.get('version') or 1}.json").write_text(
        json.dumps(old, indent=2), encoding="utf-8")
    # Streaks are carried ONLY for triggers that survived unchanged; a rewritten trigger
    # starts its evidence over rather than inheriting a streak it never earned.
    old_triggers = {t.get("id"): t for t in ((old.get("thesis") or {}).get("triggers") or [])}
    new_triggers = {t.get("id"): t for t in ((new_doc.get("thesis") or {}).get("triggers") or [])}
    carried = {tid: state for tid, state in (old.get("trigger_state") or {}).items()
               if tid in new_triggers and old_triggers.get(tid) == new_triggers.get(tid)}
    return version, carried


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
    for cmd in ("brief", "batch"):
        p = sub.add_parser(cmd, help="write the agent's work order(s)")
        if cmd == "brief":
            p.add_argument("symbols", nargs="+")
        p.add_argument("--sec-data", required=True)
        p.add_argument("--prices")
        p.add_argument("--universe", default="universe.csv")
        p.add_argument("--as-of", default=_dt.date.today().isoformat())
        p.add_argument("--theses-dir", default=str(THESES_DIR))
        p.add_argument("--no-filings", action="store_true")
    for cmd, help_text in (("record", "validate what the agent wrote"),
                           ("ratify", "the Gate: the owner commits it (FR9)")):
        p = sub.add_parser(cmd, help=help_text)
        p.add_argument("symbols", nargs="+")
        p.add_argument("--theses-dir", default=str(THESES_DIR))
        if cmd == "record":
            p.add_argument("--model", help="the model id you are running. Ignored when "
                                           "the harness keeps a readable transcript — "
                                           "that is read instead, and a mismatch is "
                                           "refused")
    args = parser.parse_args(argv)

    if args.command == "record":
        failures = 0
        for symbol in args.symbols:
            try:
                doc = record(symbol, theses_dir=Path(args.theses_dir),
                             model=args.model)
                print(f"  {deskwork.model_note(doc['agent'])}")
                print(f"{symbol}: draft ACCEPTED — ready for the Gate "
                      f"(`python thesis.py ratify {symbol}`)")
            except deskwork.OrderError as error:
                failures += 1
                print(str(error), file=sys.stderr)
        return 1 if failures else 0

    if args.command == "ratify":
        failures = 0
        for symbol in args.symbols:
            # A refused ratification is an ordinary desk outcome — an unanswered FR9
            # question, a draft that was never recorded — so it prints like one. A
            # traceback here would read as a broken tool rather than a closed Gate.
            try:
                doc = ratify(symbol, theses_dir=Path(args.theses_dir))
            except (ValueError, FileNotFoundError, deskwork.OrderError) as error:
                failures += 1
                print(f"{symbol}: not committed — {error}", file=sys.stderr)
                continue
            print(f"{symbol}: committed v{doc['version']} "
                  f"(conviction={doc['conviction']}) — the weekly monitor now owns "
                  f"its triggers")
        return 1 if failures else 0

    rows, _ = _load_rows(args)
    if args.command == "brief":
        chosen = [r for r in rows if r["symbol"] in set(args.symbols)]
        missing = set(args.symbols) - {r["symbol"] for r in chosen}
        if missing:
            print(f"not in the screened universe: {', '.join(sorted(missing))}",
                  file=sys.stderr)
    else:
        chosen = top_symbols(rows, len(rows))
        print(f"top {TOP_FRACTION:.0%} of {len(rows)} screened = {len(chosen)} names: "
              + ", ".join(r["symbol"] for r in chosen))

    for row in chosen:
        path = brief(row["symbol"], row["bundle"], row["card"], row["inversion"],
                     theses_dir=Path(args.theses_dir), name=row["name"],
                     sector=row["sector"], with_filings=not args.no_filings)
        print(f"{row['symbol']}: work order -> {path}")
    print(f"\n{len(chosen)} work order(s) written. Execute each one (read it, research, "
          f"write the three artifacts), then `python thesis.py record <SYM>`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
