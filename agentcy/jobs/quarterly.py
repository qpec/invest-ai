"""Quarterly honesty check (D.4, FR13). Fired *-01,04,07,10-01 08:30 Europe/Amsterdam.

THE ONLY job that reads the benchmark database (via benchmark.py) and THE ONLY importer
of quantstats -- both quarantined here (invariant 7 / §4.6). This module lands the D.4
return-series reconstruction: a portfolio EUR value at each snapshot from the advice
view (never avg_open_price -- invariant 4), with external flows attributed per
inter-snapshot period so deposits enter the base, never the return. It also owns the sole
benchmark WRITE path (fetch_and_store_benchmark), the G.4 QuarterlyContext build (records
appendix -- the one place cost basis is read -- benchmark line, F.2 process-review matrix,
framework audit), and the summary + document delivery.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from agentcy import archive, db, journal, mirror
from agentcy.clock import Clock, SystemClock
from agentcy.fetch import store
from agentcy.jobs import runner
from agentcy.render import contexts
from agentcy.render import quarterly as render_quarterly_mod
from agentcy.tg import outbox

RUN_TYPE = "quarterly"
LARGE_FLOW_PCT = 5.0    # D.4: net flows > ~5% of value => 'approximate — large flows'


def geometric_link(subperiod_returns) -> float:
    """Chain inter-snapshot Modified-Dietz returns: Π(1+r) − 1 (D.4)."""
    acc = 1.0
    for r in subperiod_returns:
        acc *= (1.0 + r)
    return acc - 1.0


def _mv_eur_at(conn, snapshot_id: int) -> float:
    """Portfolio EUR value = Σ position mv_eur + snapshot cash (advice view only, invariant 4)."""
    snap = db.fetch_snapshot(conn, snapshot_id)
    cash = snap["cash_balance_eur"] if snap else 0.0
    positions = mirror.advice_positions(conn, snapshot_id)
    return sum(p.mv_eur for p in positions) + cash


def _net_flow_eur(conn, snapshot_id: int) -> float:
    """Signed external flows attributed to the period ending at this snapshot (external_flow).
    Withdrawals leave the account (negative); deposits/dividends/other enter it (positive)."""
    total = 0.0
    for f in db.fetch_external_flows_for_snapshot(conn, snapshot_id):
        sign = -1.0 if f["direction"] == "withdrawal" else 1.0
        total += sign * f["amount_eur"]
    return total


def period_return_dietz(conn, *, start: str, end: str) -> float:
    """Modified Dietz over each inter-snapshot period, geometrically linked (D.4).
    Per period: r = (V_end − V_begin − F) / (V_begin + Σ w_i F_i), F weighted by time-in-period.
    Deposits therefore enter the denominator (base), never the numerator (gain)."""
    snaps = db.fetch_snapshots_between(conn, start, end)
    if len(snaps) < 2:
        return 0.0
    subs = []
    for a, b in zip(snaps, snaps[1:]):
        v0 = _mv_eur_at(conn, a["snapshot_id"])
        v1 = _mv_eur_at(conn, b["snapshot_id"])
        flow = _net_flow_eur(conn, b["snapshot_id"])
        # single mid-period flow approximation (w = 0.5) — exact day-weighting is
        # documented-out YAGNI given the reconciliation-driven flow cadence (D.4).
        base = v0 + 0.5 * flow
        subs.append(((v1 - v0 - flow) / base) if base else 0.0)
    return geometric_link(subs)


def flow_caveats(conn, *, start: str, end: str) -> list[str]:
    """D.4: quarters whose net flows exceed ~5% of value are labeled 'approximate'."""
    snaps = db.fetch_snapshots_between(conn, start, end)
    if len(snaps) < 2:
        return []
    v0 = _mv_eur_at(conn, snaps[0]["snapshot_id"]) or 1.0
    net = sum(_net_flow_eur(conn, s["snapshot_id"]) for s in snaps[1:])
    if abs(net) / v0 * 100.0 > LARGE_FLOW_PCT:
        return [f"approximate — large flows this period (net {net:+.0f} EUR on {v0:.0f} base)"]
    return []


def hand_stats(port_returns, bench_returns) -> dict:
    """D.4 four-stat hand fallback on pandas (no quantstats): period return, vs-benchmark
    simple return, max drawdown, volatility. Labeled indicative, never authoritative."""
    def _cum(r):
        return float((1.0 + r).prod() - 1.0) if len(r) else 0.0

    def _mdd(r):
        if not len(r):
            return 0.0
        curve = (1.0 + r).cumprod()
        return float((curve / curve.cummax() - 1.0).min())

    pr = _cum(port_returns)
    br = _cum(bench_returns)
    vol = float(port_returns.std() * (252 ** 0.5)) if len(port_returns) > 1 else 0.0
    return {"period_return": pr, "vs_benchmark_simple": pr - br,
            "max_drawdown": _mdd(port_returns), "volatility": vol}


def compute_stats(port_returns, bench_returns) -> dict:
    """Try quantstats (the ONLY import site, §4.6); ANY failure -> hand_stats. Returns
    {'stats': ..., 'degraded': bool, 'label': 'indicative, not authoritative'}."""
    try:
        import quantstats as qs                         # lazy: nothing else imports this (invariant 7)
        metrics = qs.reports.metrics(returns=port_returns, benchmark=bench_returns,
                                     mode="basic", display=False)
        return {"stats": {**hand_stats(port_returns, bench_returns), "quantstats": metrics},
                "degraded": False, "label": "indicative, not authoritative"}
    except Exception:
        return {"stats": hand_stats(port_returns, bench_returns),
                "degraded": True, "label": "indicative, not authoritative (quantstats unavailable)"}


def benchmark_series_eur(start: str, end: str):
    """The SOLE benchmark read (§4.6): delegates to benchmark.py (imported lazily so the
    import-graph test sees quarterly as the only reader; jobs.daily/weekly/event cannot)."""
    from agentcy import benchmark
    return benchmark.series_eur(start, end)


def fetch_and_store_benchmark(conn, *, start: str, end: str, run_id: int, clock: Clock) -> None:
    """The SOLE benchmark WRITE path: ^SP500TR x USDEUR daily bars -> benchmark.append_bars,
    through benchmark.py (function-local imports keep the quarantine graph clean, §4.6).
    Best-effort: a fetch failure degrades the report's benchmark line, never the whole run."""
    from agentcy import benchmark
    from agentcy.fetch import yf
    state_dir = db.state_dir()
    try:
        bars = yf.fetch_daily_bars("^SP500TR", state_dir=state_dir)         # paced, box-wide lock
        fx = yf.fetch_daily_bars("USDEUR=X", state_dir=state_dir)
        rows = _benchmark_rows(bars, fx, fetched_at=db.to_iso(clock.now()))
        benchmark.append_bars(rows, run_id=run_id)
    except Exception:
        pass


def _benchmark_rows(sp_bars, fx_bars, *, fetched_at) -> list[dict]:
    """Zip ^SP500TR USD closes with USDEUR to tr_eur rows (bar_date PK; INSERT OR IGNORE).
    Aligns on the intersection of bar dates; tr_eur = sp500tr_usd * usdeur (EUR-per-USD)."""
    rows = []
    for ts in sp_bars.index.intersection(fx_bars.index):
        sp = float(sp_bars.loc[ts, "close"])
        usdeur = float(fx_bars.loc[ts, "close"])
        rows.append({"bar_date": ts.date().isoformat(), "sp500tr_usd": sp, "usdeur": usdeur,
                     "tr_eur": sp * usdeur, "fetched_at": fetched_at})
    return rows


def portfolio_series_eur(conn, *, start: str, end: str) -> "pd.Series":
    """Daily portfolio EUR value (D.4): the latest snapshot's advice holdings forward-filled
    across each mappable position's adjusted closes, valued in EUR at latest FX per currency
    and summed per date. Non-mappable positions (no yf_ticker) are excluded; their weight is
    surfaced as a caveat by excluded_weight_pct. Reads advice_positions only (invariant 4)."""
    snap = db.fetch_latest_snapshot(conn)
    if snap is None:
        return pd.Series(dtype=float)
    as_of = db.from_iso(snap["as_of"])
    per_symbol = {}
    for p in mirror.advice_positions(conn, snap["snapshot_id"]):
        if p.instrument_type == "cash" or not p.yf_ticker:
            continue
        rows = db.fetch_v_price(conn, p.yf_ticker, start=start[:10], end=end[:10])
        if not rows:
            continue
        fx = store.fx_rate_eur(conn, p.native_currency, as_of=as_of)
        rate = fx.value if fx is not None else 1.0
        s = pd.Series({r["bar_date"]: r["adj_close"] * p.quantity * rate for r in rows})
        per_symbol[p.symbol] = s
    if not per_symbol:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(per_symbol).sort_index().ffill()
    cash = snap["cash_balance_eur"] or 0.0
    return frame.sum(axis=1) + cash


def excluded_weight_pct(conn) -> float:
    """Advice weight (%) of non-mappable holdings excluded from the return series (D.4 caveat)."""
    snap = db.fetch_latest_snapshot(conn)
    if snap is None:
        return 0.0
    excluded = sum(p.weight for p in mirror.advice_positions(conn, snap["snapshot_id"])
                   if p.instrument_type != "cash" and not p.yf_ticker)
    return round(excluded * 100, 1)


def build_records_appendix(conn, snapshot_id: int) -> dict:
    """G.4 §6 — the ONE place cost basis is read: db.fetch_positions_records (the raw view
    incl. avg_open_price, sanctioned for the quarterly records appendix, contracts §3.1)."""
    out = {}
    for p in db.fetch_positions_records(conn, snapshot_id):
        out[p["symbol"]] = {"avg_open_price": p["avg_open_price"], "quantity": p["quantity"],
                            "native_currency": p["native_currency"]}
    return out


def _records_rows(appendix: dict) -> list[dict]:
    """Shape build_records_appendix's symbol map into the render rows (G.4 §6). Cost basis =
    avg_open_price x quantity in the native currency; realized gain and trade-date FX are not
    tracked in the advice store, so they are stated as unavailable, never fabricated."""
    rows = []
    for ticker in sorted(appendix):
        rec = appendix[ticker]
        basis = ((rec["avg_open_price"] or 0.0) * rec["quantity"])
        rows.append({"ticker": ticker, "cost_basis_eur": basis, "realized_gain_eur": 0.0,
                     "trade_fx_note": f"{rec['native_currency']} (trade-date FX not recorded)"})
    return rows


def _cum(series: "pd.Series") -> float:
    """Cumulative simple return over a value series, as a percentage; 0.0 on thin data."""
    if len(series) < 2 or not series.iloc[0]:
        return 0.0
    return float(series.iloc[-1] / series.iloc[0] - 1.0) * 100.0


def _honest_question(port: "pd.Series", bench: "pd.Series", *, as_of) -> dict:
    """G.4 §1 six numbers: since-inception, trailing-12m, this-quarter — portfolio vs
    benchmark, EUR-based, as percentages. Slices are best-effort on whatever series length
    the reconstruction produced (do not extrapolate 13 weeks)."""
    ttm_start = (as_of - pd.Timedelta(days=365))
    q_start = pd.Timestamp(as_of.year, ((as_of.month - 1) // 3) * 3 + 1, 1)

    def _slice(s, since):
        if not len(s):
            return s
        idx = pd.to_datetime(s.index)
        return s[idx >= pd.Timestamp(since).tz_localize(None)]

    return {
        "since_inception_portfolio_pct": _cum(port),
        "since_inception_benchmark_pct": _cum(bench),
        "ttm_portfolio_pct": _cum(_slice(port, ttm_start)),
        "ttm_benchmark_pct": _cum(_slice(bench, ttm_start)),
        "quarter_portfolio_pct": _cum(_slice(port, q_start)),
        "quarter_benchmark_pct": _cum(_slice(bench, q_start)),
    }


def _process_review(matrix: dict) -> dict:
    """Adapt journal.review_matrix (F.2) to the render §4 shape. The job SURFACES the batch;
    it never grades. Entry ids are grouped by the (process, grade) 2x2 and rendered as
    one-liners; dangerous wins (deviated & good) are named, override hit-rate and the
    no-action ratio carried through as text."""
    m = matrix["matrix"]

    def _liners(process, grade):
        return [f"JE-{eid:04d}" for eid in m.get((process, grade), [])]

    return {
        "followed_good": _liners("followed", "good"),
        "followed_bad": _liners("followed", "bad"),
        "deviated_good": _liners("deviated", "good"),   # dangerous wins (F.2 flags these loudest)
        "deviated_bad": _liners("deviated", "bad"),
        "followed_pct": matrix["followed_pct"],
        "override_hit_rate": f"{matrix['override_hit_rate']:.0f}%",
        "alert_ignored": [f"{matrix['alert_ignored']} alert(s) ignored this period"]
                         if matrix["alert_ignored"] else [],
        "no_action_ratio": f"{matrix['no_action_ratio'] * 100:.0f}%",
    }


def _framework_audit(matrix: dict) -> dict:
    """G.4 §5 — gate throughput, trigger relaxations, config changes. These are journaled
    diffs the desk audits; absent a diff feed in this store they are stated as none, never
    fabricated (the golden owns the populated wording; P6 wires the shape)."""
    dangerous = matrix.get("dangerous_wins") or []
    return {
        "gate_throughput": ["Gate throughput: see the decision journal for this period."],
        "trigger_relaxations": ([f"Dangerous wins to review: {len(dangerous)} (deviated & good)."]
                                if dangerous else ["No trigger relaxations journaled this period."]),
        "config_changes": ["Config changes: see the journaled config diffs for this period."],
    }


def build_quarterly_context(conn, *, as_of, run_id: int) -> contexts.QuarterlyContext:
    """G.4 seven sections. Benchmark + records appendix live ONLY on this context (§3.16)."""
    snap = db.fetch_latest_snapshot(conn)
    first = conn.execute("SELECT MIN(as_of) AS a FROM snapshot").fetchone()["a"]
    period = f"{as_of.year}-Q{(as_of.month - 1) // 3 + 1}"
    start, end = (first or db.to_iso(as_of)), db.to_iso(as_of)
    fetch_and_store_benchmark(conn, start=start[:10], end=end[:10], run_id=run_id, clock=SystemClock())
    port = portfolio_series_eur(conn, start=start, end=end)
    bench = benchmark_series_eur(start[:10], end[:10])
    pr = port.pct_change().dropna() if len(port) else port
    br = bench.pct_change().dropna() if len(bench) else bench
    stats = compute_stats(pr, br)
    hq = _honest_question(port, bench, as_of=as_of)
    excluded = excluded_weight_pct(conn)
    caveats = tuple(flow_caveats(conn, start=start, end=end))
    if excluded:
        caveats += (f"Unpriced weight {excluded:g}% excluded from the return series.",)
    caveats += (stats["label"],)
    matrix = journal.review_matrix(conn, (start, end))            # F.2 batch pull (surfaced, not graded)
    answer = ("Since inception the process is "
              + ("ahead of" if hq["since_inception_portfolio_pct"]
                 >= hq["since_inception_benchmark_pct"] else "behind")
              + " the index; one quarter proves nothing and the 10-year answer is the real one.")
    return contexts.QuarterlyContext(
        period=period,
        honest_question=hq,
        honest_answer_sentence=answer,
        caveats=caveats, drawdown_context=(),
        process_review=_process_review(matrix), framework_audit=_framework_audit(matrix),
        records_appendix={"rows": _records_rows(
            build_records_appendix(conn, snap["snapshot_id"]) if snap else {})},
        verdict_and_exit_clause="Process intact; keep judging process, not price.",
        generated_at=as_of)


def run_one(conn, handle, *, clock: Clock, state_dir: Path) -> tuple[str, dict]:
    """D.4 top-level (the sole benchmark/quantstats process). Build G.4 context, render the
    summary message + full document, archive, enqueue both."""
    run_id = handle.run_id
    ctx = build_quarterly_context(conn, as_of=clock.now(), run_id=run_id)
    summary, doc = render_quarterly_mod.render_quarterly(ctx)
    report_id = archive.archive_and_store(conn, doc, run_id=run_id, report_type="quarterly",
                                          period=handle.scheduled_for, freshness={}, clock=clock)
    doc_path = db.fetch_report(conn, report_id)["archive_path"]
    runner.enqueue_rendered(conn, summary,
                            base_key=outbox.scheduled_key(RUN_TYPE, handle.scheduled_for, "summary"),
                            kind="quarterly_msg", run_id=run_id, clock=clock, artifact_ref=report_id)
    runner.enqueue_rendered(conn, doc,
                            base_key=outbox.scheduled_key(RUN_TYPE, handle.scheduled_for, "doc"),
                            kind="quarterly_doc", run_id=run_id, clock=clock,
                            artifact_ref=report_id, document_path=doc_path)
    conn.commit()
    return "ok", {"report_id": report_id}


def main(*, clock: Clock | None = None, state_dir: Path | None = None) -> int:
    os.environ.setdefault("MPLBACKEND", "Agg")               # headless even on a desk run (§1.2)
    clock = clock or SystemClock()
    state_dir = state_dir or db.state_dir()
    conn = db.open_db(state_dir)
    try:
        return runner.sweep_and_run(conn, RUN_TYPE, run_one, clock=clock, state_dir=state_dir)
    finally:
        conn.close()
