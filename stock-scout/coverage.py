"""Reliable coverage bridge over the existing Scout formulas and local evidence ledger."""
from __future__ import annotations

import hashlib

import scoring
import thesis

from agentcy import metric_ledger as ledger


def compare_coverage(baseline: dict, candidate: dict) -> dict:
    """Compare two deterministic coverage snapshots without changing their denominator."""
    old_possible = int(baseline["possible"])
    new_possible = int(candidate["possible"])
    if old_possible != new_possible:
        raise ValueError("coverage snapshots must use the same denominator")
    old_pct = 100.0 * int(baseline["measured"]) / old_possible if old_possible else 0.0
    new_pct = 100.0 * int(candidate["measured"]) / new_possible if new_possible else 0.0
    metrics = sorted(set(baseline["per_metric"]) | set(candidate["per_metric"]))
    per_metric = {}
    for metric in metrics:
        old_symbols = set(baseline.get("symbols_by_metric", {}).get(metric, []))
        new_symbols = set(candidate.get("symbols_by_metric", {}).get(metric, []))
        old_count = int(baseline["per_metric"].get(metric, 0))
        new_count = int(candidate["per_metric"].get(metric, 0))
        per_metric[metric] = {
            "old": old_count,
            "new": new_count,
            "delta": new_count - old_count,
            "gained": sorted(new_symbols - old_symbols),
            "lost": sorted(old_symbols - new_symbols),
        }
    return {
        "baseline_coverage_pct": old_pct,
        "candidate_coverage_pct": new_pct,
        "coverage_delta_percentage_points": new_pct - old_pct,
        "per_metric": per_metric,
    }


def release_gates(*, eligible: int, fresh_prices: int, terminal_prices: int,
                  fresh_owner_fcf_yields: int, minimum_yields: int,
                  coverage_delta_percentage_points: float,
                  lineage_complete: bool, parity_mismatches: int) -> dict:
    """Return explicit release decisions; terminal reasons never count as fresh prices."""
    checks = {
        "fresh_price_coverage_at_least_95pct": (
            eligible > 0 and fresh_prices / eligible >= 0.95
        ),
        "terminal_outcomes_explicit": fresh_prices + terminal_prices == eligible,
        "owner_fcf_yields_at_least_minimum": fresh_owner_fcf_yields >= minimum_yields,
        "coverage_gain_at_least_1_5pp": coverage_delta_percentage_points >= 1.5,
        "lineage_complete": bool(lineage_complete),
        "zero_parity_mismatches": int(parity_mismatches) == 0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def price_grid(conn):
    """Return promoted SQLite prices in the exact PIT adapter shape."""
    run = conn.execute(
        "SELECT refresh_run_id FROM market_price_refresh_run"
        " WHERE status='SUCCEEDED' AND promoted=1"
        " ORDER BY scheduled_for DESC, attempt DESC, refresh_run_id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return {}, {}, {}, {}
    prices, splits, basis, observation_ids = {}, {}, {}, {}
    rows = conn.execute(
        "SELECT * FROM market_price_observation WHERE refresh_run_id=?"
        " ORDER BY provider_symbol, bar_date, price_observation_id",
        (run["refresh_run_id"],),
    )
    for row in rows:
        symbol, day = row["provider_symbol"], row["bar_date"]
        prices.setdefault(symbol, {})[day] = {
            "close": float(row["raw_close"]),
            "adj_close": float(row["adjusted_close"]),
        }
        splits.setdefault(symbol, {})
        if row["split_ratio"] is not None and float(row["split_ratio"]) != 1.0:
            splits[symbol][day] = float(row["split_ratio"])
        basis[symbol] = "raw"
        observation_ids[symbol] = int(row["price_observation_id"])
    return prices, splits, basis, observation_ids


def _component_hash(payload_hash: str, key: str, value: float) -> str:
    material = f"{payload_hash}:{key}:{float(value):.17g}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _missing_reason(bundle: dict, price_observation_id: int | None) -> tuple[str, str]:
    if price_observation_id is None or bundle.get("price") is None:
        return "MISSING", "MISSING_PRICE"
    if bundle.get("price_note"):
        return "STALE", "STALE_PRICE"
    if bundle.get("shares_basis") == "stale-refused":
        return "STALE", "STALE_SHARES"
    if bundle.get("shares_as_of") is None:
        return "MISSING", "MISSING_SHARES"
    evaluated = thesis.registry_evaluate(bundle)
    if (evaluated.get("ttm") or {}).get("owner_fcf") is None:
        return "MISSING", "MISSING_OWNER_FCF"
    return "MISSING", "MISSING_EV_INPUT"


def store_owner_fcf_yield(conn, *, bundle: dict, companyfacts_hash: str,
                          price_observation_id: int | None, as_of: str,
                          calculated_at: str) -> int:
    """Store the canonical Scout yield with exact local price and source-artifact inputs."""
    definition_id = ledger.define_metric(
        conn, metric_key="owner_fcf_yield_pct", formula_version="scout-v1",
        unit="%", requirement="OPTIONAL", freshness_policy="trading_day",
        active_from=as_of, created_at=calculated_at,
    )
    value = thesis.metric_value("owner_fcf_yield_pct", bundle)
    if value is None or price_observation_id is None:
        status, reason = _missing_reason(bundle, price_observation_id)
        return ledger.append_metric_observation(
            conn, metric_definition_id=definition_id, ticker=bundle["symbol"],
            value=None, status=status, reason_code=reason, confidence=0.0,
            as_of=as_of, calculated_at=calculated_at, input_ids=[],
        )

    price = conn.execute(
        "SELECT * FROM market_price_observation WHERE price_observation_id=?",
        (price_observation_id,),
    ).fetchone()
    if price is None:
        raise ValueError("price observation does not exist")
    price_source = ledger.append_source_observation(
        conn, ticker=bundle["symbol"], source=price["provider"],
        source_key="raw_close", value=float(price["raw_close"]), unit="currency/share",
        currency=price["currency"], period_end=price["bar_date"],
        fetched_at=price["fetched_at"], payload_hash=price["payload_hash"],
    )

    evaluated = thesis.registry_evaluate(bundle)
    ttm = evaluated["ttm"]
    balance = scoring._latest_balance(bundle)
    components = {
        "owner_fcf_ttm": float(ttm["owner_fcf"]),
        "market_cap": float(bundle["market_cap"]),
        "total_debt": float(scoring._row(balance, "total_debt")),
        "cash": float(scoring._row(balance, "cash")),
    }
    period_end = str(ttm.get("through") or as_of)
    source_ids = [price_source]
    for key, component in components.items():
        source_ids.append(ledger.append_source_observation(
            conn, ticker=bundle["symbol"], source="sec-companyfacts-derived",
            source_key=key, value=component, unit="USD", period_end=period_end,
            fetched_at=calculated_at,
            payload_hash=_component_hash(companyfacts_hash, key, component),
        ))
    return ledger.append_metric_observation(
        conn, metric_definition_id=definition_id, ticker=bundle["symbol"], value=value,
        status="FRESH", reason_code="VALUE_AVAILABLE", confidence=1.0,
        as_of=as_of, calculated_at=calculated_at, input_ids=source_ids,
    )
