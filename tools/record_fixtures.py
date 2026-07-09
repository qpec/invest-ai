# tools/record_fixtures.py
"""Desk-only recorder for the tests/fixtures/yf/ pack (tech-arch §13).

Run at the desk / quarterly ritual to re-record live yfinance shapes; NEVER in the
offline suite (the socket guard blocks it, and the fetch is the whole point). The
serialization helpers below are pure and tested offline; `main()` is the desk entry
point that pairs them with fetch/yf.py fetchers.

Usage (desk): python -m tools.record_fixtures --state-dir /tmp/rec --ticker MSFT
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def frame_to_fixture(frame: pd.DataFrame, *, currency: str | None) -> dict:
    """History/FX/benchmark frame -> split-orient JSON dict with a top-level currency."""
    return {
        "currency": currency,
        "columns": [str(c) for c in frame.columns],
        "index": [pd.Timestamp(i).date().isoformat() for i in frame.index],
        "data": frame.astype(object).where(pd.notna(frame), None).values.tolist(),
    }


def series_to_fixture(series: pd.Series) -> dict:
    """Shares series -> split-orient JSON, DUPLICATE dates preserved (§7.4)."""
    return {
        "index": [pd.Timestamp(i).date().isoformat() for i in series.index],
        "data": [float(v) for v in series.values],
    }


def statements_to_fixture(statements: dict[str, pd.DataFrame]) -> dict:
    """{income|balance|cashflow: frame} -> nested split-orient (period columns as ISO dates)."""
    out = {}
    for stype, frame in statements.items():
        out[stype] = {
            "columns": [pd.Timestamp(c).date().isoformat() for c in frame.columns],
            "index": [str(i) for i in frame.index],
            "data": frame.astype(object).where(pd.notna(frame), None).values.tolist(),
        }
    return out


def write_fixture(dest_dir: Path, name: str, payload: dict) -> Path:
    """Write <dest_dir>/<name>.json (pretty, stable)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - desk-only, network-touching
    parser = argparse.ArgumentParser(description="Record live yfinance fixtures (desk only).")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--ticker", default="MSFT")
    parser.add_argument("--out", type=Path, default=Path("tests/fixtures/yf"))
    args = parser.parse_args(argv)

    from agentcy.fetch import yf as yfd

    # Record the RAW yfinance shapes (not the normalized public-fetcher outputs) so the
    # fixtures round-trip through their loaders — but route every raw seam through the
    # box-wide pacing lock (_paced_call -> yahoo_pacing), so the desk re-record obeys the
    # same >=2s+jitter spacing and 30s/5m/30m rate-limit backoff as production (§7.2). The
    # public fetchers can't be used here: fetch_daily_bars/fetch_officers reshape the raw
    # data the fixtures must capture verbatim.
    sd = args.state_dir
    tk = args.ticker
    hist_raw, cur = yfd._paced_call(sd, lambda: yfd._raw_history(tk, "10d"))
    write_fixture(args.out, f"{tk.lower()}_history", frame_to_fixture(hist_raw, currency=cur))
    write_fixture(
        args.out,
        f"{tk.lower()}_statements",
        statements_to_fixture(yfd._paced_call(sd, lambda: yfd._raw_statements(tk))),
    )
    write_fixture(
        args.out,
        f"{tk.lower()}_shares_full",
        series_to_fixture(yfd._paced_call(sd, lambda: yfd._raw_shares_full(tk))),
    )
    write_fixture(args.out, f"officers_{tk.lower()}", yfd._paced_call(sd, lambda: yfd._raw_officers(tk)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
