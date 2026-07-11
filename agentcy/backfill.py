"""agentcy/backfill.py - backfill-thesis onboarding (deterministic scaffolding).

Detects held positions with no live thesis, computes a fundamentals baseline as of the
invested moment, auto-derives the four Moderate invalidation triggers, creates an
origin='backfill' DRAFT thesis anchored to the invested moment, and mints a Telegram
ratification ask (approve -> intact + armed; edit -> stays draft). The Claude qualitative
drafting is Part B (out of scope); until then the NOT-NULL qualitative fields carry explicit
DRAFT placeholders and the thesis stays draft (UNmonitored) until ratified. Cost basis is
RECORD-KEEPING only and never enters positions_advice (invariant 4)."""
from __future__ import annotations

from dataclasses import dataclass

from agentcy import db, gate, mirror, register
from agentcy.clock import Clock
from agentcy.fetch import store
from agentcy.register import ThesisFields


@dataclass(frozen=True)
class HeldWithoutThesis:
    symbol: str
    yf_ticker: str | None
    instrument_type: str
    quantity: float
    opened_at: str | None
    invested_eur: float | None


def detect_thesis_less(conn, *, as_of) -> list[HeldWithoutThesis]:
    """Non-cash holdings in the latest snapshot with no live thesis, joined to their
    invested-moment position_detail (opened_at, invested_eur). Backed by advice_positions
    (invariant 4) + fetch_position_details (record-keeping companion)."""
    snap = db.fetch_latest_snapshot(conn)
    if snap is None:
        return []
    details = {d["symbol"]: d for d in db.fetch_position_details(conn, snap["snapshot_id"])}
    out: list[HeldWithoutThesis] = []
    for p in mirror.advice_positions(conn, snap["snapshot_id"]):
        if p.instrument_type == "cash":
            continue
        if register.live_thesis_for(conn, p.symbol) is not None:
            continue
        d = details.get(p.symbol)
        out.append(HeldWithoutThesis(
            symbol=p.symbol, yf_ticker=p.yf_ticker, instrument_type=p.instrument_type,
            quantity=p.quantity,
            opened_at=(d["opened_at"] if d else None),
            invested_eur=(d["invested_eur"] if d else None)))
    return out


@dataclass(frozen=True)
class Baseline:
    """The invested-moment fundamentals anchor for a backfill thesis. Every leg is None when
    its underlying series/scalar is absent/stale/thin -> that leg is skipped downstream
    (BOOTSTRAPPING), never faked."""
    yf_ticker: str
    revenue_yoy: float | None
    owner_fcf_margin: float | None
    net_debt_ebitda: float | None
    shares_yoy: float | None
    owner_earnings_json: str


def _last_series_value(stamped) -> float | None:
    """Last (period_end, value) value of a usable series Stamped, else None."""
    if stamped is None or not stamped.usable():
        return None
    series = stamped.value
    if not series:
        return None
    return series[-1][1]


def _scalar_value(stamped) -> float | None:
    """Scalar of a usable Stamped (None value / stale / absent -> None)."""
    if stamped is None or not stamped.usable():
        return None
    return stamped.value


def compute_baseline(conn, yf_ticker, *, as_of) -> Baseline:
    """The invested-moment fundamentals anchor. Every leg is None-safe: a leg with no
    computable/usable series is None (skipped / BOOTSTRAPPING downstream, never faked)."""
    rev = _last_series_value(store.revenue_yoy_series(conn, yf_ticker, as_of=as_of))
    margin = _last_series_value(store.margin_series(conn, yf_ticker, as_of=as_of))
    ndte = _last_series_value(store.balance_safety_series(conn, yf_ticker, as_of=as_of))
    shares = _scalar_value(store.shares_yoy(conn, yf_ticker, as_of=as_of))
    oe = store.owner_fcf_ttm(conn, yf_ticker, as_of=as_of)
    # Reuse the Gate's canonical serializer so both origins emit the identical six fields
    # PLUS the fetched_at provenance stamp (MA-11; "a value never sheds provenance").
    oe_json = gate._oe_json(oe) if (oe is not None and oe.usable()) else "{}"
    return Baseline(yf_ticker=yf_ticker, revenue_yoy=rev, owner_fcf_margin=margin,
                    net_debt_ebitda=ndte, shares_yoy=shares, owner_earnings_json=oe_json)


_PLACEHOLDER_MOAT = "switching_costs"   # links margin_erosion for BUF-4 until Part B


def derive_triggers(baseline: Baseline) -> list[register.TriggerSpec]:
    """The four Moderate invalidation triggers, each relative to the baseline (design section
    'Auto-derive'). A leg with no computable baseline value is OMITTED (not faked). Persistence
    matches the Gate type defaults; data_source/cadence are resolved by register.commit_trigger."""
    specs: list[register.TriggerSpec] = []
    if baseline.revenue_yoy is not None:
        floor = baseline.revenue_yoy - 10.0
        specs.append(register.TriggerSpec(
            type="growth_floor",
            statement=(f"If revenue YoY falls to or below {floor:.1f}% "
                       f"(more than 10pp under the {baseline.revenue_yoy:.1f}% baseline), "
                       "the growth story that anchors this holding is gone."),
            metric="revenue_yoy", comparator="<", threshold=floor, moat_link=None,
            persistence="2_consecutive_quarters"))
    if baseline.owner_fcf_margin is not None:
        floor = baseline.owner_fcf_margin * 0.75
        specs.append(register.TriggerSpec(
            type="margin_erosion",
            statement=(f"If owner-FCF margin TTM falls to or below {floor:.1f}% "
                       f"(a quarter below the {baseline.owner_fcf_margin:.1f}% baseline), "
                       "the moat is leaking."),
            metric="owner_fcf_margin", comparator="<", threshold=floor,
            moat_link=_PLACEHOLDER_MOAT, persistence="2_consecutive_quarters"))
    if baseline.net_debt_ebitda is not None:
        ceiling = min(baseline.net_debt_ebitda + 1.0, 4.0)
        specs.append(register.TriggerSpec(
            type="balance_sheet_safety",
            statement=(f"If net-debt/EBITDA rises to or above {ceiling:.1f}x, "
                       "the balance sheet is no longer the one I underwrote."),
            metric="net_debt_ebitda", comparator=">", threshold=ceiling, moat_link=None,
            persistence="2_consecutive_quarters"))
    if baseline.shares_yoy is not None:
        specs.append(register.TriggerSpec(
            type="dilution",
            statement=("If the share count grows 5%/yr or more, dilution is eating the "
                       "per-share compounding."),
            metric="shares_yoy", comparator=">", threshold=5.0, moat_link=None,
            persistence="ttm"))
    return specs


def _triggers_form_a_thesis(specs) -> bool:
    """register._validate_triggers requires 2-5 triggers with >=1 moat_link (BUF-4). When the
    moat-linked margin_erosion leg is absent, non-moat legs alone can NOT form a thesis: the
    onboarding is reported BOOTSTRAPPING rather than minting a moat-linkless thesis (RF5)."""
    return len(specs) >= 2 and any(s.moat_link for s in specs)


# Documented DRAFT placeholders for the NOT-NULL qualitative fields (Plan notes). The thesis
# stays draft (UNmonitored) until the owner ratifies via Telegram; these are placeholders, not
# fabricated convictions - RF1 bars activating them as owner judgment.
_DRAFT_TEXT = "(draft - pending ratification)"


def _draft_fields(baseline: Baseline) -> ThesisFields:
    """The NOT-NULL qualitative columns filled with explicit, documented DRAFT placeholders. The
    owner-earnings JSON is the real pinned value from the baseline; every judgment field is a
    neutral default the owner types over at ratification (FR9). value_at_purchase stays None -
    create_thesis pins v1 None for every origin, so cost basis never enters the thesis."""
    return ThesisFields(
        business_model_2s=_DRAFT_TEXT,
        moat_types=(_PLACEHOLDER_MOAT,),
        moat_evidence=_DRAFT_TEXT,
        owner_earnings_json=baseline.owner_earnings_json,
        owner_earnings_narrative=_DRAFT_TEXT,
        value_at_purchase=None,                 # record-keeping only; create_thesis pins v1 None
        fair_band_low=0.0, fair_band_high=0.0,  # no price verdict for backfill (BUF-12)
        denominator_note="P/owner-FCF",
        conviction="medium", mgmt_trust="neutral", mgmt_trust_note=None,
        circle_fit="edge", circle_fit_note=None,
        ten_year_statement=_DRAFT_TEXT,
        status_buy_flag=False, status_buy_note=None)


def create_backfill_draft(conn, held: HeldWithoutThesis, baseline: Baseline, *,
                          journal_ref: int, clock: Clock) -> str | None:
    """Create the origin='backfill' DRAFT thesis anchored to the invested moment. Returns the
    thesis_id, or None when too few triggers could be derived (reported BOOTSTRAPPING; never a
    malformed thesis). The thesis stays draft (UNmonitored) until the owner ratifies (RF1/RF2).
    value_at_purchase stays None at v1 - cost basis is record-keeping only and never enters
    positions_advice (invariant 4)."""
    specs = derive_triggers(baseline)
    if not _triggers_form_a_thesis(specs):
        return None
    return register.create_thesis(conn, ticker=held.symbol, origin="backfill",
                                  fields=_draft_fields(baseline), triggers=specs,
                                  journal_ref=journal_ref, clock=clock)


def entry_price(held: HeldWithoutThesis) -> float | None:
    """RECORD-KEEPING ONLY: invested_eur / quantity, for the ratify prompt / letter. This value
    is NEVER written to positions_advice or used by any invalidation trigger (the triggers fire
    on the business deteriorating, never on price-vs-entry)."""
    if held.invested_eur is None or not held.quantity:
        return None
    return held.invested_eur / held.quantity
