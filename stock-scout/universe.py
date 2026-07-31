"""FinanceDatabase -> universe.csv builder (RECONSTRUCTION.md §3.1, §5.1).

Default filter (msg 2/4): country in {United States, Netherlands} x sector in
{Information Technology, Health Care} x market_cap in {Mega, Large, Mid} Cap.
``--broad`` (msg 64): all sectors EXCEPT Financials and Real Estate (cash-flow
metrics are misleading for banks/REITs), and Small Cap joins the pool.

Cross-listing dedupe rule (§3.1, msg 4 — "the only_primary_listing pitfall
solved properly"): rows are grouped by normalized company name (lowercase,
listing decorations after " - " and parentheticals cut, punctuation stripped,
trailing corporate/ADR suffix tokens and single letters dropped); within a
group the home-market listing wins — a Dutch company keeps its Euronext
Amsterdam ``.AS`` symbol, a US company its bare US symbol.

A company that lists ONLY away from home keeps its primary line, never an
alphabetical accident: the preference is (0) home market, (1) a bare, dot-free
symbol on a major US venue, (2) any other bare symbol, (3) the rest — ties
broken by the shortest, then alphabetically first symbol. argenx SE and NXP
Semiconductors NV are Dutch companies without an Amsterdam listing: they must
resolve to ``ARGX`` and ``NXPI`` (Nasdaq), not to ``1AE.BE`` (Berlin) or
``N1XP34.SA`` (a São Paulo BDR) — a wrong-currency ghost that would then be
graded in place of the real company.

Warrant/unit lines are dropped before grouping (a warrant is not an ordinary
share and must never survive as its own "company"): names carrying a
warrant/unit decoration — except an MLP's "common units", which ARE the
ordinary line — and, inside a group, a symbol that is an ordinary sibling's
symbol plus the US ``W``/``U`` suffix. FinanceDatabase symbols are already
yfinance symbols, so the ``.AS`` suffix is kept as-is.

The equities database is downloaded ONCE in main() (never at import time) to
data/equities.bz2; ``--equities-file`` accepts a local copy.
"""
from __future__ import annotations

import argparse
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

# §3.1 pins `compression/` — the `database/` path 404s, which would hard-fail a fresh
# checkout's default `python universe.py` (data/equities.bz2 is gitignored).
EQUITIES_URL = "https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/compression/equities.bz2"
DEFAULT_EQUITIES = Path("data") / "equities.bz2"

COUNTRIES = ("United States", "Netherlands")
CORE_SECTORS = ("Information Technology", "Health Care")
BROAD_EXCLUDED_SECTORS = ("Financials", "Real Estate")
CAPS_DEFAULT = ("Mega Cap", "Large Cap", "Mid Cap")
CAPS_BROAD = CAPS_DEFAULT + ("Small Cap",)
COLUMNS = ["symbol", "name", "sector", "industry", "country", "market_cap", "exchange", "currency"]

# Trailing tokens that mark a corporate form or a listing vehicle, not the company.
_SUFFIX_TOKENS = {
    "inc", "incorporated", "corp", "corporation", "company", "co", "plc", "nv", "sa",
    "se", "ag", "ab", "ltd", "limited", "holding", "holdings", "group", "the",
    "adr", "ads", "adss", "sponsored", "unsponsored", "registry", "shs", "shares",
}

# Yahoo exchange codes of the major US venues. A dot-free symbol quoted here is the
# company's primary line; OTC (PNK/OTC) is deliberately NOT primary, so argenx's
# ARGNF pink sheet can never beat its Nasdaq ARGX line.
US_PRIMARY_EXCHANGES = frozenset({"NMS", "NYQ", "NGM", "NCM", "NGS", "NAS", "ASE",
                                  "AMX", "PCX", "BTS"})

_WARRANT_RE = re.compile(r"\bwarrants?\b", re.IGNORECASE)
_UNIT_RE = re.compile(r"\bunits?\b", re.IGNORECASE)
_COMMON_UNIT_RE = re.compile(r"\bcommon units?\b", re.IGNORECASE)


def is_derivative_line(name: str) -> bool:
    """True for a warrant/unit listing — a derivative of the company, not the company.

    Warrants always qualify ("Rigetti Computing Inc. Warrants", "Expand Energy
    Corporation Class C Warrants"). "Unit" lines qualify too (SPAC units, "Tangible
    Equity Units", "Corporate Units") EXCEPT an MLP/LP "Common Units representing
    limited partner interests", which is that partnership's ordinary line (TXO, XIFR)."""
    s = str(name)
    if _WARRANT_RE.search(s):
        return True
    return bool(_UNIT_RE.search(s)) and not _COMMON_UNIT_RE.search(s)


def normalize_name(name: str) -> str:
    """Normalized grouping key for cross-listing dedupe (§3.1): lowercase, cut at
    ' - ' (listing decoration) and parentheticals, strip punctuation, then drop
    trailing suffix tokens / single letters (so 'ASML Holding N.V.' and
    'ASML Holding N.V. - New York Registry Shs' both normalize to 'asml')."""
    s = str(name).lower().split(" - ")[0]
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = s.split()
    while len(tokens) > 1 and (tokens[-1] in _SUFFIX_TOKENS or len(tokens[-1]) == 1):
        tokens.pop()
    return " ".join(tokens)


def listing_tier(d: pd.DataFrame) -> pd.Series:
    """Listing preference per row (lower wins), the §3.1 dedupe order:

    0 home market — NL company on a `.AS` line, US company on a bare US primary line;
    1 primary venue away from home — a bare, dot-free symbol on a major US exchange
      (this is what makes argenx resolve to ARGX and NXP to NXPI instead of to their
      Berlin/São Paulo secondary lines);
    2 any other bare, dot-free symbol (OTC pink sheets, unknown venues);
    3 everything else (foreign secondary lines, BDRs, registry shares)."""
    sym = d["symbol"].astype(str)
    dot_free = ~sym.str.contains(".", regex=False)
    primary = dot_free & d["exchange"].astype(str).str.upper().isin(US_PRIMARY_EXCHANGES)
    home = (((d["country"] == "Netherlands") & sym.str.endswith(".AS"))
            | ((d["country"] == "United States") & primary))
    tier = pd.Series(3, index=d.index, dtype="int64")
    tier[dot_free] = 2
    tier[primary] = 1
    tier[home] = 0
    return tier


def _drop_group_warrant_symbols(d: pd.DataFrame) -> pd.DataFrame:
    """Drop a symbol that is an ordinary sibling's symbol plus the US warrant/unit
    suffix (`RGTI` -> `RGTIW`, `BTSG` -> `BTSGU`) WITHIN the same company group —
    the belt to the name-based `is_derivative_line` braces, for feeds that give the
    warrant line the company's own name. Never drops a symbol whose stem is absent."""
    stems = set(zip(d["_norm"], d["symbol"]))
    derivative = [len(s) > 1 and s[-1] in "WU" and (n, s[:-1]) in stems
                  for n, s in zip(d["_norm"], d["symbol"])]
    return d[~pd.Series(derivative, index=d.index)]


def filter_universe(df: pd.DataFrame, *, broad: bool = False) -> pd.DataFrame:
    """Pure filter+dedupe over a FinanceDatabase-shaped frame -> the pinned
    universe.csv columns (§3.1), sorted by symbol. Rows without a symbol, name,
    or (in --broad) a sector are dropped — an unclassified name cannot join a
    sector percentile cohort anyway."""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"equities frame missing columns: {missing}")
    d = df.loc[df["symbol"].notna() & df["name"].notna(), COLUMNS].copy()
    d["symbol"] = d["symbol"].astype(str).str.strip()
    d = d[(d["symbol"] != "") & d["country"].isin(COUNTRIES)]
    if broad:
        d = d[d["sector"].notna() & ~d["sector"].isin(BROAD_EXCLUDED_SECTORS)]
        d = d[d["market_cap"].isin(CAPS_BROAD)]
    else:
        d = d[d["sector"].isin(CORE_SECTORS) & d["market_cap"].isin(CAPS_DEFAULT)]
    d = d[~d["name"].map(is_derivative_line)]          # warrants/units are not companies
    d = d.drop_duplicates(subset="symbol", keep="first").reset_index(drop=True)
    d["_norm"] = d["name"].map(normalize_name)
    d = _drop_group_warrant_symbols(d)
    if d.empty:
        return pd.DataFrame(columns=COLUMNS)

    # One row per company: the best listing tier, ties to the shortest (most canonical)
    # then alphabetically first symbol. Unnormalizable names never merge with each other.
    d["_tier"] = listing_tier(d)
    d["_len"] = d["symbol"].str.len()
    d = d.sort_values(["_tier", "_len", "symbol"], kind="stable")
    named = d[d["_norm"] != ""].groupby("_norm", sort=False).head(1)
    out = pd.concat([named, d[d["_norm"] == ""]])[COLUMNS]
    return out.sort_values("symbol").reset_index(drop=True)


def load_equities(path: Path) -> pd.DataFrame:
    """Read the FinanceDatabase equities.bz2 (bz2 CSV, symbol index) into a frame
    with a plain `symbol` column."""
    df = pd.read_csv(path, compression="bz2", index_col=0)
    df.index.name = "symbol"
    return df.reset_index()


def download_equities(dest: Path) -> None:
    """One-time download of the FinanceDatabase equities.bz2 (§5.1) — atomic write,
    clear offline error. Called from main() ONLY, never at import time."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(EQUITIES_URL, timeout=180) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(
            f"could not download FinanceDatabase equities.bz2\n  url: {EQUITIES_URL}\n"
            f"  reason: {e}\n  offline? pass a local copy via --equities-file PATH"
        ) from e
    tmp = Path(str(dest) + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build universe.csv from FinanceDatabase (§5.1).")
    ap.add_argument("--broad", action="store_true",
                    help="all sectors except Financials/Real Estate, Small Cap included (msg 64)")
    ap.add_argument("--out", default="universe.csv", help="output CSV path")
    ap.add_argument("--equities-file", default=None, help="local equities.bz2 copy (skips download)")
    args = ap.parse_args(argv)

    if args.equities_file:
        eq_path = Path(args.equities_file)
        if not eq_path.exists():
            raise SystemExit(f"--equities-file {eq_path} does not exist")
    else:
        eq_path = DEFAULT_EQUITIES
        if not eq_path.exists():
            print(f"downloading FinanceDatabase equities -> {eq_path} ...")
            download_equities(eq_path)

    uni = filter_universe(load_equities(eq_path), broad=args.broad)
    uni.to_csv(args.out, index=False)
    nl = sorted(uni.loc[uni["country"] == "Netherlands", "symbol"])
    us_n = int((uni["country"] == "United States").sum())
    mode = "broad" if args.broad else "default"
    print(f"universe ({mode}): {len(uni)} names -> {args.out} ({us_n} US, {len(nl)} NL)")
    print("NL kept: " + (", ".join(nl) if nl else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
