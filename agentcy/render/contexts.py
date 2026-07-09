"""Frozen render contexts — the only inputs the render/* functions accept (contract §3.16).

Structural rule (invariant 7 wall 3 + invariant 4): Daily/Weekly/Event/Alert/Status
contexts define NO benchmark field and NO cost-basis field; Daily/Status additionally
define NO euro-amount field (cash is band-% only, FS-F8). Only QuarterlyContext carries
benchmark + records-appendix data. A template author cannot reference what does not exist.

StudyContext is defined once in agentcy.study (contract §3.15 → P3.22 reconciliation) and
re-exported here so both import paths resolve to the same frozen dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from agentcy.study import StudyContext  # re-export (P3.22): single definition, two import paths

__all__ = [
    "RenderedOutput",
    "HeaderBlock",
    "OpportunityLine",
    "OpenLoopLine",
    "DailyContext",
    "PortfolioRow",
    "DecisionBlock",
    "StudyContext",
    "WeeklyContext",
    "AlertItemContext",
    "AlertContext",
    "EventContext",
    "QuarterlyContext",
    "StatusContext",
    "GateContext",
]


@dataclass(frozen=True)
class RenderedOutput:
    """One rendered artifact: two skins from ONE computed context (§8)."""
    telegram_html: str
    markdown: str
    output_class: str                 # 'daily'|'weekly_msg'|'weekly_doc'|'quarterly_msg'|'quarterly_doc'|'alert'|'event'|'gate'|'study'|'status'|'notice'
    owner_spans: tuple[str, ...] = ()  # exact owner-quoted substrings — lint-exempt (§8 scoping)
    ask_id: str | None = None
    reply_markup_json: str | None = None


@dataclass(frozen=True)
class HeaderBlock:
    """G.1 header lines. No euro fields exist."""
    date_label: str
    snapshot_line: str
    prices_line: str
    cash_pct: float
    cash_band_low: float
    cash_band_high: float
    cash_in_band: bool
    n_framework: int
    n_backfill: int
    n_outside: int


@dataclass(frozen=True)
class OpportunityLine:
    """E.4 line; kind 'on_sale' (held intact) or 'fair_entry' (WATCH); suspension stated, never silent (MA-3)."""
    ticker: str
    multiple: float | None
    band_low: float
    band_high: float
    thesis_version: int
    triggers_pass: int
    triggers_total: int
    kind: str                          # 'on_sale' (held intact) | 'fair_entry' (WATCH)
    suspended_note: str | None


@dataclass(frozen=True)
class OpenLoopLine:
    ask_id: str
    label: str
    age_days: int


@dataclass(frozen=True)
class DailyContext:
    """G.1. kind: 'full' | 'pulse' (Sun/Mon) | 'degraded' | 'total_failure'.
    No value/P&L/euro/benchmark fields exist."""
    kind: str
    as_of: datetime
    header: HeaderBlock | None          # None only for total_failure
    verdict_line: str
    opportunities: tuple[OpportunityLine, ...]   # renderer caps at 3 by weight + tail line
    more_opportunities: int
    events_line: str | None             # 'expected …, calendar estimate' (MA-7)
    data_lines: tuple[str, ...]
    open_loops: tuple[OpenLoopLine, ...]         # alert_ignored heads the letter (B.3.3)
    open_items_count: int               # pulse: '{n} open items'
    generated_at: datetime
    late_banner: str | None             # 'generated {t} — delivered {t}'


@dataclass(frozen=True)
class PortfolioRow:
    """G.2 §2 row — EUR value allowed weekly; NO P/L, NO cost-basis field exists."""
    ticker: str
    weight_pct: float
    mv_eur: float
    framework_status: str
    thesis_status: str | None
    thesis_version: int | None
    conviction: str | None
    sector_label: str | None
    anchor_multiple: float | None
    band_low: float | None
    band_high: float | None
    trigger_scorecard: str


@dataclass(frozen=True)
class DecisionBlock:
    """Weekly msg 2 item — the only weekly message carrying decision keyboards."""
    ask_id: str
    heading: str
    body: str
    reply_markup_json: str


@dataclass(frozen=True)
class WeeklyContext:
    """G.2 nine sections; message series (1-4) and document skins render from THIS one context. No benchmark field exists."""
    as_of: datetime
    headline_verdict: str
    celebrated: bool
    decisions: tuple[DecisionBlock, ...]
    portfolio: tuple[PortfolioRow, ...]
    total_eur: float                    # weekly carries value (§15 A3)
    revalidations: tuple[str, ...]
    backfill_queue_line: str | None
    broken_but_held: tuple[str, ...]
    reaffirmations_due: tuple[str, ...]
    balance: "BalanceReport"            # forward ref (mirror.py); annotation only
    clusters: "ClusterResult"           # forward ref (cluster.py)
    dividend_lines: tuple[str, ...]
    reinvest_reminder: bool             # BUF-2
    loosening_echoes: tuple[str, ...]
    outside_framework_line: str
    watchlist_lines: tuple[str, ...]
    prompted_questions: tuple[DecisionBlock, ...]
    study: StudyContext
    data_health: tuple[str, ...]        # suspended listed as suspended, not passed
    generated_at: datetime


@dataclass(frozen=True)
class AlertItemContext:
    """One G.3 card; owner-quoted fields land in owner_spans."""
    ticker: str
    weight_pct: float
    trigger_label: str
    committed_statement_owner: str
    committed_version: int
    committed_at: str
    what_happened: str
    baseline_note: str | None
    price_move_pct: str                 # stated flatly, disowned by the verbatim block
    ten_year_excerpt_owner: str
    ask_id: str


@dataclass(frozen=True)
class AlertContext:
    """G.3 — single (len==1) or storm (B.3.5: ranked by weight, one shared deadline). No cost-basis/benchmark fields exist."""
    deadline_label: str
    items: tuple[AlertItemContext, ...]
    generated_at: datetime


@dataclass(frozen=True)
class EventContext:
    """D.3 report; quiet outcome also folds into the next daily letter as one line."""
    ticker: str
    event_kind: str
    owner_initiated: bool
    triggers_pass: int
    triggers_total: int
    data_lag: bool
    retry_note: str | None
    prompted_ask_ids: tuple[str, ...]
    generated_at: datetime


@dataclass(frozen=True)
class QuarterlyContext:
    """G.4 — the ONLY context with benchmark + records-appendix (cost basis) fields (FR13, quarantine)."""
    period: str
    honest_question: Mapping            # portfolio EUR vs SP500TR EUR: since-inception, ttm, quarter (last+smallest)
    honest_answer_sentence: str
    caveats: tuple[str, ...]            # flow approximation, unpriced weight, indicative-stats label
    drawdown_context: tuple[str, ...]
    process_review: Mapping             # F.2 matrix output
    framework_audit: Mapping
    records_appendix: Mapping           # cost basis / realized gains / trade-date FX — HERE ONLY
    verdict_and_exit_clause: str
    generated_at: datetime


@dataclass(frozen=True)
class StatusContext:
    """/status card — G.1 header + open loops; reports last RunLog state, never runs checks. No euro fields exist."""
    now_label: str
    header: HeaderBlock
    verdict_line: str
    open_loops: tuple[OpenLoopLine, ...]
    next_scheduled_line: str


@dataclass(frozen=True)
class GateContext:
    """Gate verdict document (C.6): verdict, reason class, sizing advice from E.3 conviction table, standing questions."""
    ticker: str
    verdict: str
    reason_class: str | None
    dossier_summary: Mapping
    suggested_max_weight_pct: float | None
    standing_questions: tuple[str, ...]
    generated_at: datetime
