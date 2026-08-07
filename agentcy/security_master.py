"""Deterministic identity and eligibility rules for the local Scout universe."""
from __future__ import annotations

import hashlib
import csv
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from agentcy import db


class InstrumentType(StrEnum):
    ORDINARY_SHARE = "ORDINARY_SHARE"
    FUND = "FUND"
    LISTED_DEBT = "LISTED_DEBT"
    WARRANT_OR_UNIT = "WARRANT_OR_UNIT"
    PREFERRED_SHARE = "PREFERRED_SHARE"
    ROYALTY_TRUST = "ROYALTY_TRUST"
    UNKNOWN = "UNKNOWN"


class Eligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class Classification:
    instrument_type: InstrumentType
    eligibility: Eligibility
    reason_code: str


@dataclass(frozen=True)
class ImportSummary:
    run_id: int
    input_rows: int
    eligible: int
    ineligible: int
    review: int


_SEC_PRIMARY_EXCHANGES = frozenset({"NYSE", "NASDAQ", "NYSE AMERICAN"})
_DUTCH_PRIMARY_EXCHANGES = frozenset({"AMS", "EURONEXT AMSTERDAM"})
_DEBT = re.compile(
    r"\b(first mortgage bonds?|senior notes?|subordinated notes?|debentures?)\b|"
    r"\bnotes?\s+due\s+\d{4}\b|\bsr\s+nt\b",
    re.IGNORECASE,
)
_FUND = re.compile(
    r"\b(fund|exchange[- ]traded fund|closed[- ]end|investment company)\b",
    re.IGNORECASE,
)
_WARRANT_UNIT = re.compile(r"\b(warrants?|units?)\b", re.IGNORECASE)
_PREFERRED = re.compile(
    r"\bpreferred(?: stock| shares?| securities)?\b|\bpreference shares?\b|"
    r"\bcum(?:ulative)?\s+pfd\b|\bdepositary shares?\b",
    re.IGNORECASE,
)
_ROYALTY_TRUST = re.compile(r"\broyalty trust\b", re.IGNORECASE)


def security_key(*, cik: str | int | None, normalized_name: str,
                 primary_symbol: str) -> str:
    """Return a stable issuer key, preferring the regulator identity."""
    if cik not in (None, ""):
        return f"cik:{int(cik):010d}"
    material = normalized_name.strip().casefold() or primary_symbol.strip().upper()
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"name:{digest}"


def classify(*, symbol: str, name: str, country: str | None,
             exchange: str | None, cik: str | None, sec_primary: bool) -> Classification:
    """Classify one listing conservatively; uncertainty always requires review."""
    symbol_upper = symbol.strip().upper()
    exchange_upper = (exchange or "").strip().upper()
    country_upper = (country or "").strip().upper()

    if _DEBT.search(name):
        return Classification(InstrumentType.LISTED_DEBT, Eligibility.INELIGIBLE,
                              "LISTED_DEBT")
    if _FUND.search(name):
        return Classification(InstrumentType.FUND, Eligibility.INELIGIBLE, "FUND")
    if _WARRANT_UNIT.search(name) or symbol_upper.endswith(("-WS", "-WU", "-W", "-U")):
        return Classification(InstrumentType.WARRANT_OR_UNIT, Eligibility.INELIGIBLE,
                              "WARRANT_OR_UNIT")
    if _PREFERRED.search(name) or re.search(r"-P[A-Z]?$", symbol_upper):
        return Classification(InstrumentType.PREFERRED_SHARE, Eligibility.INELIGIBLE,
                              "PREFERRED_SHARE")
    if _ROYALTY_TRUST.search(name):
        return Classification(InstrumentType.ROYALTY_TRUST, Eligibility.INELIGIBLE,
                              "ROYALTY_TRUST")
    if sec_primary and cik and exchange_upper in _SEC_PRIMARY_EXCHANGES:
        return Classification(InstrumentType.ORDINARY_SHARE, Eligibility.ELIGIBLE,
                              "PRIMARY_ORDINARY_SHARE")
    if country_upper in {"NETHERLANDS", "NL"} and exchange_upper in _DUTCH_PRIMARY_EXCHANGES:
        return Classification(InstrumentType.ORDINARY_SHARE, Eligibility.ELIGIBLE,
                              "DUTCH_PRIMARY_ORDINARY_SHARE")
    if country_upper in {"UNITED STATES", "US", "USA"} and not sec_primary:
        return Classification(InstrumentType.UNKNOWN, Eligibility.REVIEW,
                              "UNRESOLVED_SECONDARY_LISTING")
    return Classification(InstrumentType.UNKNOWN, Eligibility.REVIEW, "UNKNOWN_INSTRUMENT")


def _normalize_name(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", name.casefold())
    suffixes = {"inc", "incorporated", "corp", "corporation", "company", "co", "plc",
                "nv", "sa", "se", "ag", "ltd", "limited", "holdings", "group", "the"}
    while words and words[-1] in suffixes:
        words.pop()
    return " ".join(words)


def _input_hash(universe_path: Path, sec_exchange_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (universe_path, sec_exchange_path):
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _summary_for_run(conn: sqlite3.Connection, run_id: int) -> ImportSummary:
    row = conn.execute(
        "SELECT input_rows, eligible_rows, ineligible_rows, review_rows"
        " FROM security_master_run WHERE run_id=?",
        (run_id,),
    ).fetchone()
    return ImportSummary(run_id, int(row["input_rows"]), int(row["eligible_rows"]),
                         int(row["ineligible_rows"]), int(row["review_rows"]))


def import_snapshot(conn: sqlite3.Connection, universe_path: Path,
                    sec_exchange_path: Path, *, source_vintage: str,
                    observed_at: str) -> ImportSummary:
    """Import one complete local identity snapshot, or replay its existing result."""
    universe_path = Path(universe_path)
    sec_exchange_path = Path(sec_exchange_path)
    fingerprint = _input_hash(universe_path, sec_exchange_path)
    replay = conn.execute(
        "SELECT run_id FROM security_master_run"
        " WHERE source_vintage=? AND input_hash=? AND status='SUCCEEDED'",
        (source_vintage, fingerprint),
    ).fetchone()
    if replay:
        return _summary_for_run(conn, int(replay["run_id"]))

    payload = json.loads(sec_exchange_path.read_text(encoding="utf-8"))
    fields = payload.get("fields") or []
    sec_rows = [dict(zip(fields, values)) for values in payload.get("data") or []]
    sec_by_symbol = {
        str(row.get("ticker") or "").upper(): row
        for row in sec_rows if row.get("ticker")
    }
    with universe_path.open(newline="", encoding="utf-8") as handle:
        universe_rows = list(csv.DictReader(handle))

    # A reused ticker can point at a new issuer/security while the free universe still
    # carries the old company. When another row for the same CIK agrees with the SEC
    # issuer name, keep the disagreeing alias in review instead of silently promoting it.
    cik_names: dict[str, list[str]] = {}
    for row in universe_rows:
        sec = sec_by_symbol.get(str(row.get("symbol") or "").strip().upper())
        if sec and sec.get("cik") not in (None, ""):
            cik_names.setdefault(str(sec["cik"]), []).append(
                _normalize_name(str(row.get("name") or ""))
            )

    counts = Counter()
    with conn:
        run_id = db.append_security_master_run(conn, {
            "source_vintage": source_vintage,
            "input_hash": fingerprint,
            "started_at": observed_at,
            "status": "RUNNING",
            "input_rows": len(universe_rows),
        })
        for row in universe_rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            sec = sec_by_symbol.get(symbol)
            cik = str(sec["cik"]) if sec and sec.get("cik") not in (None, "") else None
            exchange = str(sec.get("exchange") or "") if sec else str(row.get("exchange") or "")
            classification = classify(
                symbol=symbol,
                name=name,
                country=row.get("country"),
                exchange=exchange,
                cik=cik,
                sec_primary=sec is not None,
            )
            if sec and len(cik_names.get(cik or "", [])) > 1:
                sec_name = _normalize_name(str(sec.get("name") or ""))
                universe_name = _normalize_name(name)
                peers = cik_names[cik]
                peer_agrees = any(
                    set(sec_name.split()) & set(peer.split()) for peer in peers
                    if peer != universe_name
                )
                this_agrees = bool(set(sec_name.split()) & set(universe_name.split()))
                if peer_agrees and not this_agrees:
                    classification = Classification(
                        InstrumentType.UNKNOWN, Eligibility.REVIEW, "IDENTITY_CONFLICT"
                    )
            key = security_key(cik=cik, normalized_name=_normalize_name(name),
                               primary_symbol=symbol)
            source_hash = hashlib.sha256(json.dumps(
                row, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            db.append_security_observation(conn, {
                "run_id": run_id,
                "security_key": key,
                "cik": f"{int(cik):010d}" if cik else None,
                "symbol": symbol,
                "name": name,
                "country": row.get("country") or None,
                "exchange": exchange or None,
                "currency": row.get("currency") or None,
                "instrument_type": classification.instrument_type.value,
                "eligibility": classification.eligibility.value,
                "reason_code": classification.reason_code,
                "source": "universe+sec",
                "source_hash": source_hash,
                "observed_at": observed_at,
            })
            db.append_security_alias(conn, {
                "run_id": run_id,
                "security_key": key,
                "provider": "universe",
                "symbol": symbol,
                "exchange": str(row.get("exchange") or "") or None,
                "valid_from": source_vintage,
                "valid_until": None,
                "observed_at": observed_at,
            })
            counts[classification.eligibility.value] += 1
        db.finish_security_master_run(
            conn,
            run_id,
            finished_at=observed_at,
            status="SUCCEEDED",
            eligible_rows=counts[Eligibility.ELIGIBLE.value],
            ineligible_rows=counts[Eligibility.INELIGIBLE.value],
            review_rows=counts[Eligibility.REVIEW.value],
        )
    return _summary_for_run(conn, run_id)


def audit_summary(conn: sqlite3.Connection) -> dict:
    """Return a machine-readable summary of the latest successful identity snapshot."""
    run = conn.execute(
        "SELECT * FROM security_master_run WHERE status='SUCCEEDED'"
        " ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return {"schema_version": 1, "input_rows": 0, "eligible": 0,
                "ineligible": 0, "review": 0, "reasons": {}, "exchanges": {}}
    reasons = {row["reason_code"]: row["n"] for row in conn.execute(
        "SELECT reason_code, COUNT(*) AS n FROM v_current_security GROUP BY reason_code"
    )}
    exchanges = {(row["exchange"] or "UNKNOWN"): row["n"] for row in conn.execute(
        "SELECT exchange, COUNT(*) AS n FROM v_current_security GROUP BY exchange"
    )}
    return {
        "schema_version": 1,
        "run_id": int(run["run_id"]),
        "source_vintage": run["source_vintage"],
        "input_rows": int(run["input_rows"]),
        "eligible": int(run["eligible_rows"]),
        "ineligible": int(run["ineligible_rows"]),
        "review": int(run["review_rows"]),
        "reasons": dict(sorted(reasons.items())),
        "exchanges": dict(sorted(exchanges.items())),
    }
