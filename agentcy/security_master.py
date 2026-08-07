"""Deterministic identity and eligibility rules for the local Scout universe."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum


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


_SEC_PRIMARY_EXCHANGES = frozenset({"NYSE", "NASDAQ", "NYSE AMERICAN"})
_DUTCH_PRIMARY_EXCHANGES = frozenset({"AMS", "EURONEXT AMSTERDAM"})
_DEBT = re.compile(
    r"\b(first mortgage bonds?|senior notes?|subordinated notes?|debentures?)\b|"
    r"\bnotes?\s+due\s+\d{4}\b",
    re.IGNORECASE,
)
_FUND = re.compile(
    r"\b(fund|exchange[- ]traded fund|closed[- ]end|investment company)\b",
    re.IGNORECASE,
)
_WARRANT_UNIT = re.compile(r"\b(warrants?|units?)\b", re.IGNORECASE)
_PREFERRED = re.compile(r"\bpreferred(?: stock| shares?| securities)?\b", re.IGNORECASE)
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
    if _PREFERRED.search(name) or symbol_upper.endswith("-P"):
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
