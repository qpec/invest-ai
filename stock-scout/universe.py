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
Amsterdam ``.AS`` symbol, a US company its bare US symbol; a company that only
lists away from home keeps its only listing. FinanceDatabase symbols are
already yfinance symbols, so the ``.AS`` suffix is kept as-is.

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

EQUITIES_URL = "https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/database/equities.bz2"
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


def _pick_home_listing(group: pd.DataFrame) -> pd.Series:
    """Home-market preference within one normalized-name group (§3.1): NL company ->
    `.AS` listing, US company -> bare US symbol, else the (alphabetically first)
    only listing away from home."""
    g = group.sort_values("symbol")
    nl = g[(g["country"] == "Netherlands") & g["symbol"].str.endswith(".AS")]
    if len(nl):
        return nl.iloc[0]
    us = g[(g["country"] == "United States") & ~g["symbol"].str.contains(".", regex=False)]
    if len(us):
        return us.iloc[0]
    return g.iloc[0]


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
    d = d.drop_duplicates(subset="symbol", keep="first")
    d["_norm"] = d["name"].map(normalize_name)

    rows = []
    for norm, group in d.groupby("_norm", sort=False):
        if norm == "":  # unnormalizable names never merge with each other
            rows.extend(r for _, r in group.iterrows())
        else:
            rows.append(_pick_home_listing(group))
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.DataFrame(rows)[COLUMNS]
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
