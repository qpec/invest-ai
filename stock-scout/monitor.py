"""The Weekly Monitor — committed theses validated against their own triggers
(THESIS-DESIGN.md §7; FR4/FR7/FR9/FR11).

    python monitor.py brief --theses-dir <dir>              # 1. the week's open questions
    <the agent answers them into verdicts.json>
    python monitor.py run --sec-data <dir> --prices <dir> \
        --verdicts <path> --model <model id>                # 2. evaluate everything

The constitution's core principle made executable: the thesis drives the monitoring. This
runs ONLY the pre-committed triggers of ratified theses — never open-ended news scanning.

- `metric` triggers are evaluated mechanically from the fresh bundle via the same
  scoring.evaluate the live grader uses (thesis.metric_value). A trigger demanding
  persistence keeps its streak in the thesis's own trigger_state, so one noisy week
  cannot fire a rule that asked for two.
- `event`/`narrative` triggers need judgement, so they go to the AGENT: the run writes a
  work order listing every open question, the agent answers it with its own web tools,
  and `record` ingests the verdicts. An event may break only on HIGH confidence; a
  narrative trigger can only send the thesis to review — judgement summons the owner to
  the desk, it never fires the sell rule alone.
- A question with no verdict is reported UNCHECKED, loudly. Absent evidence is not
  safety; a thesis is never called intact because its questions went unanswered.

Statuses per FR7: intact / under_review / broken. Broken means sell advice that ignores
cost basis; the report says so, and nothing here executes anything (FR11). "No action
needed" is printed as the first-class outcome it is (FR4).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

import deskwork
import scoring
import thesis as thesis_mod

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "trigger_id": {"type": "string"},
        "symbol": {"type": "string"},
        "tripped": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["trigger_id", "symbol", "tripped", "confidence", "evidence", "sources"],
    "additionalProperties": False,
}

VERDICT_RULES = """## How to answer

Answer ONLY the question asked. You are not forming a view on the stock — you are
checking one pre-committed invalidation trigger the owner wrote at the Gate.

- `tripped` means the question's condition IS met by the evidence standard stated in the
  question itself.
- `confidence` is `"high"` ONLY for documented public fact (a filing, a company
  statement, a major outlet). `"medium"` for credible but unconfirmed reporting.
  `"low"` for inference. This matters: a `break`-action event trigger is DEMOTED to
  review unless confidence is high, because an inference must not fire a sell rule.
- Quote the decisive evidence in `evidence`, and list source URLs in `sources`.
- Found nothing relevant? `tripped: false`, `confidence: "low"`, and say exactly that in
  `evidence`. Do not pad it into a judgement you did not make.
- Answer every question in the list. A question you skip is reported UNCHECKED, which is
  a gap in the owner's monitoring — not a pass."""


def check_trigger(trigger: dict, *, symbol: str, bundle=None, evaluated=None,
                  state=None, verdicts: dict | None = None, as_of: str = "") -> dict:
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
        # IDEMPOTENT PER as_of. A second run on the same date — a manual re-run, a systemd
        # retry, crash recovery — re-reads the SAME unchanged filings, and counting that as
        # another "consecutive check" would let one week's data satisfy a rule that asked
        # for two. A repeat hit on a date already counted holds the streak where it is; a
        # repeat that now misses still resets, because a miss is new information.
        previous = state.get("streak") or 0
        if not hit:
            streak = 0
        elif state.get("last_checked") == as_of and previous > 0:
            streak = previous
        else:
            streak = previous + 1
        state.update({"streak": streak, "last_value": value, "last_checked": as_of})
        tripped = hit and streak >= needed
        detail = (f"{trigger['metric']} = {value:,.2f} {op} {threshold:,.2f}"
                  f"{' HIT' if hit else ' ok'} (streak {streak}/{needed})")
        return {"checked": True, "tripped": tripped, "state": state, "detail": detail,
                "value": value}

    # event / narrative: judgement, so the verdict comes from the agent (via `verdicts`),
    # not from this process. No verdict is UNCHECKED — never a pass.
    verdict = (verdicts or {}).get(trigger.get("id"))
    if verdict is None:
        return {"checked": False, "tripped": False, "state": state,
                "detail": "UNCHECKED — no verdict was supplied for this question; that "
                          "is a gap in the monitoring, not an all-clear"}
    tripped = bool(verdict.get("tripped"))
    confidence = verdict.get("confidence")
    # An event may break only on documented fact; below that it summons, not fires (§7).
    demoted = (tripped and kind == "event" and trigger.get("action") == "break"
               and confidence != "high")
    state.update({"last_checked": as_of, "last_confidence": confidence})
    detail = (f"{'TRIPPED' if tripped else 'not tripped'} ({confidence} confidence): "
              f"{str(verdict.get('evidence', ''))[:300]}")
    if demoted:
        detail += " [confidence below 'high': demoted from break to review this week]"
    return {"checked": True, "tripped": tripped, "state": state, "detail": detail,
            "confidence": confidence, "demoted_to_review": demoted,
            "sources": verdict.get("sources") or []}


def check_thesis(doc: dict, *, bundle=None, verdicts: dict | None = None,
                 as_of: str = "") -> dict:
    """All triggers of one committed thesis -> the FR7 status plus per-trigger results.
    Mutates doc's trigger_state and status (the caller writes the file)."""
    symbol = doc["symbol"]
    evaluated = thesis_mod.registry_evaluate(bundle) if bundle else None
    trigger_state = doc.setdefault("trigger_state", {})
    results, broken_by, review_by, unchecked = [], [], [], []

    for trigger in (doc.get("thesis") or {}).get("triggers", []):
        tid = trigger.get("id") or trigger.get("statement", "?")[:40]
        outcome = check_trigger(trigger, symbol=symbol, bundle=bundle,
                                evaluated=evaluated, state=trigger_state.get(tid),
                                verdicts=verdicts, as_of=as_of)
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

def _save(path: Path, doc: dict):
    """Atomic write. A committed thesis is portfolio data living OUTSIDE the code repo
    (NFR2) — its file is the only copy, so a truncate-then-write interrupted by a crash
    destroys it. Write beside it, then rename: the rename is atomic, so the file is
    either the old thesis or the new one, never half of each."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _render(report: list[dict], as_of: str, *, provenance: str = "") -> str:
    lines = [f"# Weekly thesis monitor — {as_of}", ""]
    # Named at the top, not in a footer: whoever reads a BROKEN verdict is about to act on
    # it, and "which model answered the judgement questions" is part of how much weight
    # that verdict carries.
    if provenance:
        lines += [f"_{provenance}_", ""]
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
        if entry["status"] == "error":
            lines.append(f"**This thesis could not be read or checked: "
                         f"{entry.get('error')}. Nothing about it was verified — that is "
                         f"a gap, not an all-clear.**")
            continue
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


def run(*, theses_dir: Path, bundles_by_symbol: dict, verdicts: dict | None = None,
        as_of: str, reports_dir: Path = Path("reports"), model: str | None = None,
        transcript: Path | None = None) -> list[dict]:
    # The model gate applies to JUDGEMENT, not to arithmetic. A metric-only run needs no
    # agent at all and is never blocked; the moment agent verdicts are ingested — the
    # answers that can send a thesis to review or let a break trigger fire — the owner's
    # best-available rule binds, and an unapproved model is refused before it can write
    # a status into a committed thesis.
    agent = {"id": None, "provenance": None, "approved": False}
    if verdicts:
        agent, problems = deskwork.resolve_model(model, transcript=transcript)
        if problems:
            raise deskwork.OrderError(
                "refusing to ingest agent verdicts:\n  - " + "\n  - ".join(problems))
    committed = sorted(Path(theses_dir, "committed").glob("*.json"))
    report = []
    for path in committed:
        # One bad thesis must not silence the whole monitor. Without this, a corrupt file
        # raises out of the loop, every later thesis goes unchecked, and no report is
        # written at all — the failure mode that looks exactly like "nothing to report".
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            entry = check_thesis(doc, bundle=bundles_by_symbol.get(doc["symbol"]),
                                 verdicts=(verdicts or {}).get(doc["symbol"]),
                                 as_of=as_of)
            _save(path, doc)
        except Exception as error:  # noqa: BLE001 — every failure must still be reported
            report.append({"symbol": path.stem, "status": "error", "broken_by": [],
                           "review_by": [], "unchecked": ["(whole thesis)"],
                           "triggers": [], "error": f"{type(error).__name__}: {error}"})
            continue
        report.append(entry)
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / f"monitor-{as_of}.md"
    provenance = (deskwork.model_note(agent) if verdicts else
                  "metric triggers only — no agent judgement was used this run")
    out.write_text(_render(report, as_of, provenance=provenance), encoding="utf-8")
    return report


def open_questions(theses_dir: Path) -> list[dict]:
    """Every event/narrative trigger of every committed thesis — the questions that need
    judgement this week. Metric triggers are absent by design: they are answered by
    arithmetic, and sending them to an agent would be inviting an opinion about a fact."""
    questions = []
    for path in sorted(Path(theses_dir, "committed").glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for trigger in (doc.get("thesis") or {}).get("triggers", []):
            if trigger.get("kind") in ("event", "narrative"):
                questions.append({
                    "symbol": doc["symbol"], "trigger_id": trigger.get("id"),
                    "kind": trigger.get("kind"), "action": trigger.get("action"),
                    "statement": trigger.get("statement"),
                    "question": trigger.get("question") or trigger.get("statement"),
                })
    return questions


def brief(theses_dir: Path, *, as_of: str, out_dir: Path | None = None) -> Path | None:
    """The weekly work order: the open questions, the rules, and the file to write.
    Returns None when no committed thesis carries a judgement trigger — there is nothing
    to ask, and inventing a question would be the open-ended news scanning the design
    forbids."""
    questions = open_questions(theses_dir)
    if not questions:
        return None
    out = Path(out_dir or Path(theses_dir) / f"monitor-{as_of}")
    lines = []
    for q in questions:
        lines += [f"### {q['symbol']} / {q['trigger_id']}  "
                  f"({q['kind']}, action `{q['action']}`)",
                  f"- Pre-committed trigger: {q['statement']}",
                  f"- **Question:** {q['question']}", ""]
    body = "\n".join(["## The open questions", ""] + lines + [
        VERDICT_RULES, "",
        deskwork.schema_block({"type": "array", "items": VERDICT_SCHEMA},
                              title="verdicts.json — an ARRAY, one entry per question")])
    text = deskwork.order(
        title=f"Weekly thesis monitor — judgement triggers, {as_of}",
        why=f"{len(questions)} pre-committed invalidation question(s) across the "
            f"committed theses need answering. These are the owner's OWN triggers, "
            f"written at the Gate — you are not scanning for news, you are checking "
            f"exactly these.",
        artifacts=[(f"{out}/verdicts.json",
                    "one verdict per question, in the schema below")],
        steps=["Read each question below.",
               "Research it with your own web tools — recent, sourced, specific. Budget "
               f"about {thesis_mod.MONITOR_SEARCH_BUDGET} searches per question.",
               "Write every verdict into the one array file.",
               "Run the command below to ingest them."],
        rules=["Answer the question asked, nothing broader.",
               "`high` confidence means documented public fact — it is what lets a "
               "break trigger actually break.",
               "Never leave a question out; a missing verdict is reported UNCHECKED.",
               "The owner's rule is best-available models only. Your verdicts are refused "
               "outright if the model answering them is not approved — this is checked "
               "against the harness, not against what you say."],
        body=body,
        finish=f"python monitor.py run --theses-dir {theses_dir} --as-of {as_of} "
               f"--verdicts {out}/verdicts.json --sec-data <dir> --prices <dir> "
               f"--model <the model id you are running>",
    )
    path = out / deskwork.ORDER_NAME
    deskwork.write_atomic(path, text)
    deskwork.write_json(out / "questions.json", questions)
    return path


def load_verdicts(path: Path | None) -> dict:
    """verdicts.json -> {symbol: {trigger_id: verdict}}. A verdict missing its ids is
    dropped rather than guessed at — an unattributable answer is not an answer."""
    if not path:
        return {}
    payload = deskwork.read_json(Path(path))
    if not isinstance(payload, list):
        raise deskwork.OrderError(f"{path} must be a JSON ARRAY of verdicts")
    out: dict = {}
    for entry in payload:
        symbol, trigger_id = entry.get("symbol"), entry.get("trigger_id")
        if symbol and trigger_id:
            out.setdefault(symbol, {})[trigger_id] = entry
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("brief", help="write the agent's work order for this week")
    p.add_argument("--theses-dir", default=str(thesis_mod.THESES_DIR))
    p.add_argument("--as-of", default=_dt.date.today().isoformat())
    p = sub.add_parser("run", help="evaluate every trigger and write the report")
    p.add_argument("--sec-data", required=True)
    p.add_argument("--prices")
    p.add_argument("--universe", default="universe.csv")
    p.add_argument("--as-of", default=_dt.date.today().isoformat())
    p.add_argument("--theses-dir", default=str(thesis_mod.THESES_DIR))
    p.add_argument("--verdicts", help="verdicts.json from the agent's work order")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--enrich-cache", help="tier-2 companyfacts cache dir (enrich.py); "
                                          "cache-first, so no network is needed weekly")
    p.add_argument("--model", help="the model id you are running. Ignored when the "
                                   "harness keeps a readable transcript — that is read "
                                   "instead, and a mismatch is refused")
    args = parser.parse_args(argv)

    theses_dir = Path(args.theses_dir)
    if args.command == "brief":
        path = brief(theses_dir, as_of=args.as_of)
        if path is None:
            print("no judgement triggers among the committed theses — nothing to ask. "
                  "Run `monitor.py run` for the mechanical checks.")
        else:
            print(f"work order -> {path}")
        return 0

    symbols = [json.loads(p.read_text(encoding="utf-8"))["symbol"]
               for p in sorted(Path(theses_dir, "committed").glob("*.json"))]
    bundles_by_symbol = {}
    if symbols:
        import picks
        import pit
        import secsv
        meta = picks._load_meta(Path(args.universe))
        prices = picks._load_prices(Path(args.prices) if args.prices else None)
        facts = secsv.load_facts(args.sec_data, symbols=symbols)
        secsv.merge_tag_index(facts, args.sec_data, symbols=symbols)
        if args.enrich_cache:
            # Tier 2 (cache-first, so a weekly run without network still monitors): the
            # export is a SELECTION of tags, and a trigger on a metric only the fuller
            # companyfacts carries — net debt / EBITDA was the canonical case — would
            # otherwise be UNCHECKED every week by construction.
            import enrich
            try:
                ciks = enrich.cik_map_cached(Path(args.enrich_cache))
                # A committed thesis on a name the export never carried (the expanded
                # universe) monitors from its cached companyfacts — cache_only keeps
                # the weekly run network-free; the 12:00 pre-refresh already fetched
                # the monitored names minutes earlier.
                enrich.bootstrap_payloads(facts, [s for s in symbols if s not in facts],
                                          cache_dir=Path(args.enrich_cache), ciks=ciks,
                                          cache_only=True)
                enrich.enrich_payloads(facts, [s for s in symbols if s in facts
                                               and enrich.ENRICHMENT_KEY not in facts[s]],
                                       cache_dir=Path(args.enrich_cache), ciks=ciks)
            except Exception as error:  # noqa: BLE001 — enrichment is a bonus, never a gate
                print(f"enrichment unavailable ({type(error).__name__}: {error}) — "
                      f"monitoring on export facts only", file=sys.stderr)
        for symbol in symbols:
            if symbol in facts:
                bundle = pit.as_of_bundle(facts[symbol], symbol, meta.get(symbol),
                                          args.as_of, prices)
                if bundle is not None:
                    bundles_by_symbol[symbol] = bundle

    verdicts = load_verdicts(Path(args.verdicts) if args.verdicts else None)
    if not verdicts:
        print("no verdicts supplied: event/narrative triggers will be UNCHECKED "
              "(`python monitor.py brief` writes the work order that produces them)")

    try:
        report = run(theses_dir=theses_dir, bundles_by_symbol=bundles_by_symbol,
                     verdicts=verdicts, as_of=args.as_of,
                     reports_dir=Path(args.reports_dir), model=args.model)
    except deskwork.OrderError as error:
        print(str(error), file=sys.stderr)
        return 1
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
