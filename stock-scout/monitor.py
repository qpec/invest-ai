"""The Weekly Monitor — committed theses validated against their own triggers
(THESIS-DESIGN.md §7; FR4/FR7/FR9/FR11).

    python monitor.py --sec-data <dir> --prices <dir> [--no-llm]

The constitution's core principle made executable: the thesis drives the monitoring. This
runs ONLY the pre-committed triggers of ratified theses — never open-ended news scanning.

- `metric` triggers are evaluated mechanically from the fresh bundle via the same
  scoring.evaluate the live grader uses (thesis.metric_value). A trigger demanding
  persistence keeps its streak in the thesis's own trigger_state, so one noisy week
  cannot fire a rule that asked for two.
- `event`/`narrative` triggers are one LLM call each: web search on, a strict
  record_verdict tool. An event may break only on HIGH confidence; a narrative trigger
  can only send the thesis to review — judgement summons the owner to the desk, it never
  fires the sell rule alone.
- No API key -> those triggers are reported UNCHECKED, loudly. Absent evidence is not
  safety; a thesis is never called intact because its questions could not be asked.

Statuses per FR7: intact / under_review / broken. Broken means sell advice that ignores
cost basis; the report says so, and nothing here executes anything (FR11). "No action
needed" is printed as the first-class outcome it is (FR4).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

import llm
import scoring
import thesis as thesis_mod

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "tripped": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tripped", "confidence", "evidence", "sources"],
    "additionalProperties": False,
}

RECORD_VERDICT_TOOL = {
    "name": "record_verdict",
    "description": "Record the verdict on the trigger question. Call exactly once.",
    "strict": True,
    "input_schema": VERDICT_SCHEMA,
}

VERDICT_SYSTEM = """You answer ONE pre-committed invalidation-trigger question about a
company, for a portfolio monitor. Search the web for evidence, then call record_verdict
exactly once. Rules: answer only the question asked — no broader opinion on the stock;
"tripped" means the question's condition IS met by the evidence standard stated in the
question; confidence "high" only for documented public facts (filings, company
statements, major outlets), "medium" for credible but unconfirmed reporting, "low" for
inference. Quote the decisive evidence and list source URLs. If you find nothing
relevant, tripped=false with confidence "low" and evidence saying exactly that.
"""


def check_trigger(trigger: dict, *, symbol: str, bundle=None, evaluated=None,
                  state=None, client=None, as_of: str = "") -> dict:
    """One trigger -> {tripped, checked, detail, ...}. Pure over its inputs; the caller
    owns persistence of the returned state."""
    state = dict(state or {})
    kind = trigger.get("kind")

    if kind == "metric":
        if bundle is None and evaluated is None:
            return {"checked": False, "tripped": False, "state": state,
                    "detail": "no fresh fundamentals bundle — metric not evaluated"}
        value = thesis_mod.metric_value(trigger["metric"], bundle or {}, evaluated)
        if value is None:
            return {"checked": False, "tripped": False, "state": state,
                    "detail": f"{trigger['metric']} not computable from the fresh bundle "
                              f"— reported, never read as safety"}
        op, threshold = trigger["op"], trigger["threshold"]
        hit = {"<": value < threshold, "<=": value <= threshold,
               ">": value > threshold, ">=": value >= threshold}[op]
        needed = trigger.get("consecutive_checks") or 1
        streak = (state.get("streak") or 0) + 1 if hit else 0
        state.update({"streak": streak, "last_value": value, "last_checked": as_of})
        tripped = hit and streak >= needed
        detail = (f"{trigger['metric']} = {value:,.2f} {op} {threshold:,.2f}"
                  f"{' HIT' if hit else ' ok'} (streak {streak}/{needed})")
        return {"checked": True, "tripped": tripped, "state": state, "detail": detail,
                "value": value}

    # event / narrative: one LLM call with web search
    if client is None:
        return {"checked": False, "tripped": False, "state": state,
                "detail": "UNCHECKED — no LLM available to ask the question; this is "
                          "not safety"}
    question = trigger.get("question") or trigger.get("statement")
    user = (f"Company: {symbol}. As of {as_of}.\n"
            f"Trigger ({kind}, pre-committed at ratification): {trigger.get('statement')}\n"
            f"Question to answer now: {question}")
    tools = [dict(llm.WEB_SEARCH_TOOL, max_uses=thesis_mod.MONITOR_SEARCH_BUDGET),
             RECORD_VERDICT_TOOL]
    # 8k, not less: max_tokens caps thinking + text together on claude-opus-5, and a
    # verdict starved of thinking room truncates instead of answering.
    result = client.run(system=VERDICT_SYSTEM, user=user, tools=tools,
                        capture_tool="record_verdict", max_tokens=8000)
    verdict = result.get("captured")
    if verdict is None:
        return {"checked": False, "tripped": False, "state": state,
                "detail": f"UNCHECKED — the verdict run ended "
                          f"({result.get('stop_reason')}) without recording"}
    tripped = bool(verdict.get("tripped"))
    confidence = verdict.get("confidence")
    # An event may break only on documented fact; below that it summons, not fires (§7).
    demoted = (tripped and kind == "event" and trigger.get("action") == "break"
               and confidence != "high")
    state.update({"last_checked": as_of, "last_confidence": confidence})
    detail = (f"{'TRIPPED' if tripped else 'not tripped'} ({confidence} confidence): "
              f"{verdict.get('evidence', '')[:300]}")
    if demoted:
        detail += " [confidence below 'high': demoted from break to review this week]"
    return {"checked": True, "tripped": tripped, "state": state, "detail": detail,
            "confidence": confidence, "demoted_to_review": demoted,
            "sources": verdict.get("sources") or [], "usage": result.get("usage")}


def check_thesis(doc: dict, *, bundle=None, client=None, as_of: str = "") -> dict:
    """All triggers of one committed thesis -> the FR7 status plus per-trigger results.
    Mutates doc's trigger_state and status (the caller writes the file)."""
    symbol = doc["symbol"]
    evaluated = scoring.evaluate(bundle) if bundle else None
    trigger_state = doc.setdefault("trigger_state", {})
    results, broken_by, review_by, unchecked = [], [], [], []

    for trigger in (doc.get("thesis") or {}).get("triggers", []):
        tid = trigger.get("id") or trigger.get("statement", "?")[:40]
        outcome = check_trigger(trigger, symbol=symbol, bundle=bundle,
                                evaluated=evaluated, state=trigger_state.get(tid),
                                client=client, as_of=as_of)
        trigger_state[tid] = outcome["state"]
        results.append({"id": tid, "kind": trigger.get("kind"),
                        "action": trigger.get("action"), **{k: v for k, v in
                        outcome.items() if k != "state"}})
        if not outcome["checked"]:
            unchecked.append(tid)
        elif outcome["tripped"]:
            effective_break = (trigger.get("action") == "break"
                               and not outcome.get("demoted_to_review"))
            (broken_by if effective_break else review_by).append(tid)

    # BROKEN IS STICKY. Once a pre-committed break trigger has fired, the standing advice
    # is sell — a metric drifting back over its line next week does not un-say that, and
    # letting it would be the sunk-cost trap wearing a lab coat. Only the owner at the
    # desk resurrects a thesis (retire it, or re-ratify a new version through the Gate).
    if doc.get("status") == "broken":
        status = "broken"
    else:
        status = ("broken" if broken_by else
                  "under_review" if review_by else "intact")
    doc["status"] = "committed" if status == "intact" else status
    doc["last_monitored"] = as_of
    return {"symbol": symbol, "status": status, "broken_by": broken_by,
            "review_by": review_by, "unchecked": unchecked, "triggers": results}


# --- The weekly run -----------------------------------------------------------------------

def _render(report: list[dict], as_of: str) -> str:
    lines = [f"# Weekly thesis monitor — {as_of}", ""]
    if not report:
        lines.append("No committed theses. The monitor reads only `theses/committed/` — "
                     "ratify a draft at the Gate first.")
        return "\n".join(lines) + "\n"
    attention = [r for r in report if r["status"] != "intact" or r["unchecked"]]
    if not attention:
        lines.append("**No action needed.** Every committed thesis is intact and every "
                     "trigger was checked. Doing nothing is the plan working (FR4).")
    for entry in report:
        lines += ["", f"## {entry['symbol']} — {entry['status'].upper()}"]
        if entry["status"] == "broken":
            lines.append("**A pre-committed break trigger fired: the thesis is broken. "
                         "The standing advice is to sell, ignoring cost basis (FR7). "
                         "This system executes nothing (FR11).**")
        elif entry["status"] == "under_review":
            lines.append("A review trigger fired — bring this to the next desk session.")
        if entry["unchecked"]:
            lines.append(f"UNCHECKED triggers (not safety): {', '.join(entry['unchecked'])}")
        for t in entry["triggers"]:
            mark = ("BROKE" if t["id"] in entry["broken_by"] else
                    "REVIEW" if t["id"] in entry["review_by"] else
                    "unchecked" if not t["checked"] else "ok")
            lines.append(f"- [{mark}] ({t['kind']}/{t['action']}) {t['id']}: {t['detail']}")
    return "\n".join(lines) + "\n"


def run(*, theses_dir: Path, bundles_by_symbol: dict, client=None, as_of: str,
        reports_dir: Path = Path("reports")) -> list[dict]:
    committed = sorted(Path(theses_dir, "committed").glob("*.json"))
    report = []
    for path in committed:
        doc = json.loads(path.read_text(encoding="utf-8"))
        entry = check_thesis(doc, bundle=bundles_by_symbol.get(doc["symbol"]),
                             client=client, as_of=as_of)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        report.append(entry)
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / f"monitor-{as_of}.md"
    out.write_text(_render(report, as_of), encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sec-data", required=True)
    parser.add_argument("--prices")
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--as-of", default=_dt.date.today().isoformat())
    parser.add_argument("--theses-dir", default=str(thesis_mod.THESES_DIR))
    parser.add_argument("--no-llm", action="store_true",
                        help="skip event/narrative triggers (reported UNCHECKED)")
    args = parser.parse_args(argv)

    theses_dir = Path(args.theses_dir)
    symbols = [json.loads(p.read_text(encoding="utf-8"))["symbol"]
               for p in sorted(Path(theses_dir, "committed").glob("*.json"))]
    bundles_by_symbol = {}
    if symbols:
        import picks
        import secsv
        meta = picks._load_meta(Path(args.universe))
        prices = picks._load_prices(Path(args.prices) if args.prices else None)
        for bundle in secsv.bundles(args.sec_data, args.as_of, symbols=symbols,
                                    meta=meta, prices=prices):
            bundles_by_symbol[bundle["symbol"]] = bundle

    client = None
    if not args.no_llm:
        try:
            client = llm.Client()
            llm._credentials()
        except llm.NoAPIKeyError:
            client = None
            print("no ANTHROPIC_API_KEY: event/narrative triggers will be UNCHECKED")

    report = run(theses_dir=theses_dir, bundles_by_symbol=bundles_by_symbol,
                 client=client, as_of=args.as_of)
    for entry in report:
        print(f"{entry['symbol']}: {entry['status']}"
              + (f"  (unchecked: {len(entry['unchecked'])})" if entry["unchecked"] else ""))
    if not report:
        print("no committed theses — nothing to monitor")
    elif all(e["status"] == "intact" and not e["unchecked"] for e in report):
        print("No action needed — the plan is working (FR4).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
