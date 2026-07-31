"""Offline tests for the data/acquisition layer (RECONSTRUCTION.md §3.1, §3.2, §5.1-§5.4):
universe filtering + cross-listing dedupe, cache-entry JSON round-trip, the
progress.json contract, reporter line formatting, and tg.py dev-mode fallback.
Synthetic fixtures only — no network, no real caches."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import populate
import reporter
import tg
import universe

# ------------------------------------------------------------------ universe.py

NL_SIX = ["ADYEN.AS", "ASM.AS", "ASML.AS", "BESI.AS", "PHIA.AS", "TWEKA.AS"]


def _row(symbol, name, sector, cap, country, exchange="NYQ", currency="USD", industry="X"):
    return {"symbol": symbol, "name": name, "sector": sector, "industry": industry,
            "country": country, "market_cap": cap, "exchange": exchange,
            "currency": currency, "summary": "-", "market": "-"}


@pytest.fixture()
def equities_df():
    rows = [
        # The six Dutch names (msg 4 sanity anchor).
        _row("ADYEN.AS", "Adyen N.V.", "Information Technology", "Large Cap", "Netherlands", "AMS", "EUR"),
        _row("ASML.AS", "ASML Holding N.V.", "Information Technology", "Mega Cap", "Netherlands", "AMS", "EUR"),
        _row("ASM.AS", "ASM International N.V.", "Information Technology", "Large Cap", "Netherlands", "AMS", "EUR"),
        _row("BESI.AS", "BE Semiconductor Industries N.V.", "Information Technology", "Mid Cap", "Netherlands", "AMS", "EUR"),
        _row("PHIA.AS", "Koninklijke Philips N.V.", "Health Care", "Large Cap", "Netherlands", "AMS", "EUR"),
        _row("TWEKA.AS", "TKH Group N.V.", "Information Technology", "Mid Cap", "Netherlands", "AMS", "EUR"),
        # US cross-listings of the Dutch names — the dedupe must drop these.
        _row("ASML", "ASML Holding N.V. - New York Registry Shs", "Information Technology", "Mega Cap", "Netherlands", "NMS"),
        _row("ADYEY", "Adyen N.V. ADR", "Information Technology", "Large Cap", "Netherlands", "PNK"),
        # Regular US names.
        _row("ADBE", "Adobe Inc.", "Information Technology", "Large Cap", "United States", "NMS"),
        _row("JPM", "JPMorgan Chase & Co.", "Financials", "Mega Cap", "United States"),
        _row("O", "Realty Income Corporation", "Real Estate", "Large Cap", "United States"),
        _row("XOM", "Exxon Mobil Corporation", "Energy", "Mega Cap", "United States"),
        _row("PLUS", "ePlus inc.", "Information Technology", "Small Cap", "United States", "NMS"),
        _row("NOSEC", "No Sector Corp.", float("nan"), "Mid Cap", "United States"),
        # Wrong country: never in the universe.
        _row("SAP.DE", "SAP SE", "Information Technology", "Mega Cap", "Germany", "GER", "EUR"),
    ]
    return pd.DataFrame(rows)


def test_default_filter_keeps_nl_six_and_dedupes_cross_listings(equities_df):
    out = universe.filter_universe(equities_df)
    symbols = list(out["symbol"])
    for sym in NL_SIX:
        assert sym in symbols
    assert "ASML" not in symbols          # home market .AS wins over the NY registry line
    assert "ADYEY" not in symbols         # ADR loses to ADYEN.AS
    assert "ADBE" in symbols              # bare US symbol is the US home listing
    assert symbols == sorted(symbols)
    assert list(out.columns) == universe.COLUMNS


def test_default_filter_excludes_sector_cap_country(equities_df):
    symbols = set(universe.filter_universe(equities_df)["symbol"])
    assert "JPM" not in symbols           # Financials outside IT/HC
    assert "XOM" not in symbols           # Energy outside IT/HC
    assert "PLUS" not in symbols          # Small Cap outside Mega/Large/Mid
    assert "SAP.DE" not in symbols        # Germany outside US+NL


def test_broad_filter_adds_small_cap_all_sectors_but_never_financials_or_real_estate(equities_df):
    symbols = set(universe.filter_universe(equities_df, broad=True)["symbol"])
    assert "XOM" in symbols               # other sectors join
    assert "PLUS" in symbols              # Small Cap joins
    assert "JPM" not in symbols           # Financials stay out (msg 64)
    assert "O" not in symbols             # Real Estate stays out (msg 64)
    assert "NOSEC" not in symbols         # sectorless rows cannot join a cohort
    for sym in NL_SIX:
        assert sym in symbols
    assert "ASML" not in symbols and "ADYEY" not in symbols   # dedupe applies in broad too


def test_lone_away_from_home_listing_is_kept(equities_df):
    # A Dutch company with only a US listing keeps its only listing (§3.1).
    df = pd.concat([equities_df, pd.DataFrame([_row(
        "ELV?", "Elastic Ventures N.V.", "Information Technology", "Mid Cap", "Netherlands", "NMS")])],
        ignore_index=True)
    df.loc[df["symbol"] == "ELV?", "symbol"] = "ELVN"
    out = universe.filter_universe(df)
    assert "ELVN" in set(out["symbol"])


# ------------------------------------------------------------------ populate.py

def _stmt(cols: dict) -> pd.DataFrame:
    return pd.DataFrame({pd.Timestamp(k): v for k, v in cols.items()})


@pytest.fixture()
def synthetic_fetch():
    bars = pd.DataFrame(
        {"close": [10.0, 11.5], "adj_close": [10.0, 11.5], "dividend": [0.0, 0.0],
         "currency": ["USD", "USD"]},
        index=pd.DatetimeIndex(["2026-07-29", "2026-07-30"]))
    shares = pd.Series(
        [100.0, 101.0, 102.0],
        index=pd.DatetimeIndex(["2026-07-01 00:00", "2026-07-01 12:00", "2026-07-02 00:00"]))
    annual = {
        "income": _stmt({"2025-12-31": {"Total Revenue": 100.0, "EBITDA": float("nan")},
                         "2024-12-31": {"Total Revenue": 90.0, "EBITDA": 20.0}}),
        "balance": _stmt({"2025-12-31": {"Total Debt": 5.0, "Cash And Cash Equivalents": 30.0}}),
        "cashflow": _stmt({"2025-12-31": {"Operating Cash Flow": 40.0, "Capital Expenditure": -8.0}}),
    }
    fast = {"last_price": 11.5, "market_cap": 1_000.0, "shares": 102, "currency": "USD",
            "year_high": float("nan")}
    meta = {"name": "Testco", "sector": "Information Technology", "industry": float("nan"),
            "country": "United States"}
    return meta, fast, bars, shares, annual


def test_build_cache_entry_round_trip(synthetic_fetch):
    meta, fast, bars, shares, annual = synthetic_fetch
    fetched_at = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    entry = populate.build_cache_entry("TST", meta, fast, bars, shares, annual,
                                       fetched_at=fetched_at)
    # §3.2: strictly JSON-serializable, NaN -> null (allow_nan=False must not raise).
    round_tripped = json.loads(json.dumps(entry, allow_nan=False))
    assert round_tripped == entry
    assert entry["ticker"] == "TST"
    assert entry["fetched_at"] == "2026-07-31T10:00:00+00:00"
    assert entry["meta"] == {"name": "Testco", "sector": "Information Technology",
                             "industry": None, "country": "United States"}
    assert entry["currency"] == "USD"
    assert entry["price"] == {"close": 11.5, "date": "2026-07-30"}
    assert entry["fast_info"]["year_high"] is None            # NaN scalar -> null
    assert entry["fast_info"]["last_price"] == 11.5
    # Shares deduped last-per-date, ISO keys.
    assert entry["shares"] == {"2026-07-01": 101.0, "2026-07-02": 102.0}
    # Statement payloads: ISO period ends, every row kept, NaN -> null.
    assert entry["annual"]["income"]["2025-12-31"]["EBITDA"] is None
    assert entry["annual"]["income"]["2024-12-31"]["Total Revenue"] == 90.0
    assert "quarterly" not in entry                            # pre-augment shape


def test_build_cache_entry_with_quarterly(synthetic_fetch):
    meta, fast, bars, shares, annual = synthetic_fetch
    quarterly = {st: annual[st] for st in populate.STATEMENT_TYPES}
    entry = populate.build_cache_entry("TST", meta, fast, bars, shares, annual, quarterly)
    assert set(entry["quarterly"]) == {"income", "balance", "cashflow"}
    assert entry["quarterly"]["cashflow"]["2025-12-31"]["Operating Cash Flow"] == 40.0


def test_build_cache_entry_empty_shares(synthetic_fetch):
    meta, fast, bars, _, annual = synthetic_fetch
    entry = populate.build_cache_entry("TST", meta, fast, bars, None, annual)
    assert entry["shares"] == {}


def test_cache_filename_keeps_dots_maps_slash():
    assert populate.cache_filename("ASML.AS") == "ASML.AS.json"
    assert populate.cache_filename("BF/B") == "BF-B.json"


def test_progress_json_contract(tmp_path):
    path = tmp_path / "progress.json"
    started = "2026-07-31T10:00:00+00:00"
    populate.write_progress(path, task="populate", total=589, done=1, failed=0,
                            started_at=started)
    data = json.loads(path.read_text())
    assert data == {"task": "populate", "total": 589, "done": 1, "failed": 0,
                    "started_at": started, "finished": False, "finished_at": None}
    populate.write_progress(path, task="populate", total=589, done=443, failed=146,
                            started_at=started, finished=True,
                            finished_at="2026-07-31T11:00:00+00:00")
    data = json.loads(path.read_text())
    assert data["finished"] is True and data["finished_at"] == "2026-07-31T11:00:00+00:00"
    assert set(data) == {"task", "total", "done", "failed", "started_at", "finished", "finished_at"}


def test_is_fresh(tmp_path, synthetic_fetch):
    meta, fast, bars, shares, annual = synthetic_fetch
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "TST.json"
    entry = populate.build_cache_entry("TST", meta, fast, bars, shares, annual,
                                       fetched_at=now - timedelta(days=1))
    populate.atomic_write_json(path, entry)
    assert populate.is_fresh(path, max_age_days=3, need_quarterly=False, now=now)
    assert not populate.is_fresh(path, max_age_days=3, need_quarterly=True, now=now)   # no quarterly yet
    assert not populate.is_fresh(path, max_age_days=0.5, need_quarterly=False, now=now)  # too old
    assert not populate.is_fresh(tmp_path / "GONE.json", max_age_days=3,
                                 need_quarterly=False, now=now)


def test_append_failure_line(tmp_path):
    log = tmp_path / "failures.log"
    populate.append_failure(log, "DEAD", "404\nnot found")
    assert log.read_text() == "DEAD\t404 not found\n"


# ------------------------------------------------------------------ reporter.py

def _progress(**over):
    base = {"task": "populate", "total": 589, "done": 300, "failed": 34,
            "started_at": "2026-07-31T11:30:00+00:00", "finished": False, "finished_at": None}
    base.update(over)
    return base


def test_format_progress_line_exact():
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)   # 30 min in -> 10.0/min
    line = reporter.format_progress_line(_progress(), now=now)
    assert line == ("⏳ Stock Scout populate: 300/589 gecached (51%) · "
                    "34 dode tickers · 10.0/min · ETA ~26 min")


def test_format_progress_line_before_first_success():
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    line = reporter.format_progress_line(_progress(done=0, failed=0), now=now)
    assert line == "⏳ Stock Scout populate: 0/589 gecached (0%) · 0 dode tickers · ?/min · ETA ~? min"


def test_format_finished_line_exact():
    line = reporter.format_finished_line(_progress(done=443, failed=146, finished=True))
    assert line == "✅ Stock Scout populate KLAAR: 443/589 gecached, 146 dode tickers overgeslagen."


def test_load_progress_tolerates_missing_partial_junk(tmp_path):
    assert reporter.load_progress(tmp_path / "nope.json") is None
    partial = tmp_path / "partial.json"
    partial.write_text('{"task": "populate"}')
    assert reporter.load_progress(partial) is None
    junk = tmp_path / "junk.json"
    junk.write_text('{"task": "popul')                        # torn write
    assert reporter.load_progress(junk) is None
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_progress()))
    assert reporter.load_progress(ok)["done"] == 300


# ------------------------------------------------------------------------ tg.py

def test_tg_dev_mode_without_config(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert tg.send_message("hallo <b>wereld</b>") is False
    doc = tmp_path / "report.md"
    doc.write_text("# rapport")
    assert tg.send_document(doc, caption="run") is False
    out = capsys.readouterr().out
    assert "hallo <b>wereld</b>" in out
    assert "report.md" in out
