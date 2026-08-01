"""secsv.py — the SEC CSV export -> §4.1 Bundle loader (§3.6/§5.9).

Everything here runs offline on tiny synthetic CSVs written into tmp_path. The real export
(418 MB / 3.07M rows) is never touched by the suite: what has to be proven is the
RESHAPING (companyfacts structure, namespace routing, instants, chunk-boundary merging,
the tag-index fold) and the wiring into pit.py — not pit's own arithmetic, which
tests/test_pit.py already pins.
"""
import csv
import json

import pytest

import pit
import scoring
import secsv

OBS_HEADER = ["symbol", "namespace", "tag", "label", "unit", "start", "end", "filed",
              "form", "fy", "fp", "frame", "value"]
TAG_INDEX_HEADER = ["symbol", "namespace", "tag", "label", "description", "units",
                    "observation_count", "latest_unit", "latest_end", "latest_filed",
                    "latest_form", "latest_value"]


# ------------------------------------------------------------------ fixture builders

def obs(symbol, tag, end, filed, value, *, start="", namespace="us-gaap", unit="USD",
        form="10-Q"):
    """One row of selected_sec_fact_observations.csv (blank start == instant)."""
    return {"symbol": symbol, "namespace": namespace, "tag": tag, "label": tag,
            "unit": unit, "start": start, "end": end, "filed": filed, "form": form,
            "fy": end[:4], "fp": "Q1", "frame": "", "value": value}


def idx(symbol, tag, end, filed, value, *, namespace="us-gaap", unit="USD", form="10-Q",
        count=1):
    """One row of sec_facts_tag_index_partN.csv (latest observation only)."""
    return {"symbol": symbol, "namespace": namespace, "tag": tag, "label": tag,
            "description": "", "units": unit, "observation_count": count,
            "latest_unit": unit, "latest_end": end, "latest_filed": filed,
            "latest_form": form, "latest_value": value}


def _write(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_export(tmp_path, observations, tag_index=None, name="export"):
    """A miniature export directory: the observation CSV plus optional tag-index parts."""
    data_dir = tmp_path / name
    data_dir.mkdir(exist_ok=True)
    _write(data_dir / secsv.OBSERVATIONS_FILE, OBS_HEADER, observations)
    if tag_index is not None:
        _write(data_dir / "sec_facts_tag_index_part1.csv", TAG_INDEX_HEADER, tag_index)
    return data_dir


def write_prices(tmp_path, rows, columns=("symbol", "date", "close", "adj_close"),
                 name="weekly_prices.csv"):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    return path


# A complete filer: 3 fiscal years of quarterly + annual flows, quarter-end balances and a
# flat dei share count — enough for every §4.6 REQUIRED metric once a price exists.
QUARTERS = [("01-01", "03-31"), ("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31")]
Q_VALUES = {"Revenues": 1000, "GrossProfit": 700, "OperatingIncomeLoss": 300,
            "NetIncomeLoss": 250, "NetCashProvidedByUsedInOperatingActivities": 350,
            "PaymentsToAcquirePropertyPlantAndEquipment": 50, "ShareBasedCompensation": 30,
            "DepreciationDepletionAndAmortization": 60}
BALANCE = {"Assets": 5000, "CashAndCashEquivalentsAtCarryingValue": 500,
           "StockholdersEquity": 2500, "LongTermDebt": 1000}


def full_filer(symbol="SYN", years=(2023, 2024, 2025), shares=100):
    """(observation rows, tag-index rows) for a healthy, fully-tagged filer.

    Current assets/liabilities live ONLY in the tag index — exactly as in the real export —
    so this fixture also proves the fold is load-bearing: without it ROIC (a §4.6 REQUIRED
    metric, computed off Working Capital and Current Assets) cannot be computed at all.
    """
    rows, last_end, last_filed = [], None, None
    for year in years:
        for start_md, end_md in QUARTERS:
            start, end = f"{year}-{start_md}", f"{year}-{end_md}"
            filed = f"{year + (end_md == '12-31')}-{'02' if end_md == '12-31' else '11'}-10"
            for tag, value in Q_VALUES.items():
                rows.append(obs(symbol, tag, end, filed, value, start=start))
            for tag, value in BALANCE.items():
                rows.append(obs(symbol, tag, end, filed, value))
            rows.append(obs(symbol, "EntityCommonStockSharesOutstanding", end, filed,
                            shares, namespace="dei", unit="shares"))
            last_end, last_filed = end, filed
        fy_start, fy_end = f"{year}-01-01", f"{year}-12-31"
        fy_filed = f"{year + 1}-02-10"
        for tag, value in Q_VALUES.items():
            rows.append(obs(symbol, tag, fy_end, fy_filed, value * 4, start=fy_start,
                            form="10-K"))
    tag_index = [idx(symbol, "AssetsCurrent", last_end, last_filed, 2000),
                 idx(symbol, "LiabilitiesCurrent", last_end, last_filed, 800)]
    return rows, tag_index


# ------------------------------------------------- observations -> companyfacts shape

def test_observation_rows_become_the_raw_companyfacts_shape(tmp_path):
    """namespace routing, unit keys, instants without a start, val as a float."""
    data_dir = write_export(tmp_path, [
        obs("AAA", "Revenues", "2024-12-31", "2025-02-10", 100, start="2024-01-01"),
        obs("AAA", "Assets", "2024-12-31", "2025-02-10", 900),          # instant
        obs("AAA", "EntityCommonStockSharesOutstanding", "2024-12-31", "2025-02-10",
            42, namespace="dei", unit="shares"),
        obs("BBB", "Revenues", "2024-12-31", "2025-02-10", 7, start="2024-01-01"),
    ])
    facts = secsv.load_facts(data_dir)

    assert sorted(facts) == ["AAA", "BBB"]
    payload = facts["AAA"]
    assert pit.facts_symbol(payload) == "AAA"          # §3.6 true-symbol annotation
    assert set(payload["facts"]) == {"us-gaap", "dei"}
    assert payload["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"] \
        == [{"end": "2024-12-31", "filed": "2025-02-10", "form": "10-Q", "val": 42.0}]

    revenue = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    assert revenue == [{"start": "2024-01-01", "end": "2024-12-31",
                        "filed": "2025-02-10", "form": "10-Q", "val": 100.0}]
    assets = payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]
    assert "start" not in assets                       # instant: no start key, never "nan"
    assert isinstance(assets["val"], float)

    # ...and pit reads it exactly as it reads a bt_cache/facts payload.
    assert pit._unit_entries(payload, "us-gaap", "Revenues") == revenue


def test_non_usd_and_ifrs_rows_keep_their_own_keys(tmp_path):
    """The unit and namespace columns are passed through verbatim, so pit's USD-then-shares
    preference and its 'us-gaap only' reading behave as on a real companyfacts payload."""
    data_dir = write_export(tmp_path, [
        obs("EUR1", "Revenues", "2024-12-31", "2025-02-10", 5, start="2024-01-01",
            unit="EUR"),
        obs("EUR1", "Revenue", "2024-12-31", "2025-02-10", 5, start="2024-01-01",
            namespace="ifrs-full", unit="EUR"),
    ])
    facts = secsv.load_facts(data_dir)
    assert set(facts["EUR1"]["facts"]) == {"us-gaap", "ifrs-full"}
    assert list(facts["EUR1"]["facts"]["us-gaap"]["Revenues"]["units"]) == ["EUR"]
    assert pit._unit_entries(facts["EUR1"], "us-gaap", "Revenues")[0]["val"] == 5.0


def test_symbols_filter_and_file_order(tmp_path):
    data_dir = write_export(tmp_path, [
        obs("ZZZ", "Revenues", "2024-12-31", "2025-02-10", 1, start="2024-01-01"),
        obs("AAA", "Revenues", "2024-12-31", "2025-02-10", 2, start="2024-01-01"),
    ])
    assert secsv.symbols_in(data_dir) == ["ZZZ", "AAA"]          # file order, not sorted
    assert list(secsv.load_facts(data_dir, symbols=["AAA"])) == ["AAA"]


def test_unparseable_and_incomplete_rows_are_dropped(tmp_path):
    data_dir = write_export(tmp_path, [
        obs("AAA", "Revenues", "2024-12-31", "2025-02-10", "", start="2024-01-01"),
        obs("AAA", "Revenues", "2024-09-30", "2025-02-10", "n/a", start="2024-07-01"),
        obs("AAA", "Assets", "", "2025-02-10", 5),
        obs("AAA", "Assets", "2024-12-31", "", 5),
        obs("AAA", "Assets", "2024-12-31", "2025-02-10", 900),
    ])
    facts = secsv.load_facts(data_dir)
    assert list(facts["AAA"]["facts"]["us-gaap"]) == ["Assets"]
    assert len(facts["AAA"]["facts"]["us-gaap"]["Assets"]["units"]["USD"]) == 1


# ------------------------------------------------------------------ chunk boundaries

def test_one_symbol_split_across_two_chunks_merges_into_one_entry(tmp_path):
    """The classic streaming bug: a symbol whose rows straddle a chunk boundary must end
    up as ONE payload carrying ALL of its observations, not two half-filled ones."""
    rows = [obs("AAA", "Revenues", f"{year}-12-31", f"{year + 1}-02-10", year,
                start=f"{year}-01-01") for year in (2020, 2021, 2022, 2023)]
    rows.append(obs("AAA", "Assets", "2023-12-31", "2024-02-10", 900))
    rows.append(obs("BBB", "Revenues", "2023-12-31", "2024-02-10", 1, start="2023-01-01"))
    data_dir = write_export(tmp_path, rows)

    whole = secsv.load_facts(data_dir, chunksize=1_000_000)
    for chunksize in (1, 2, 3, 4, 5):                  # every possible split point
        streamed = secsv.load_facts(data_dir, chunksize=chunksize)
        assert streamed == whole, f"chunksize={chunksize} lost or duplicated observations"
    assert len(whole["AAA"]["facts"]["us-gaap"]["Revenues"]["units"]["USD"]) == 4
    assert set(whole["AAA"]["facts"]["us-gaap"]) == {"Revenues", "Assets"}
    assert set(whole) == {"AAA", "BBB"}


# ---------------------------------------------------------------- tag-index folding

def test_tag_index_adds_only_genuinely_missing_tags(tmp_path):
    data_dir = write_export(
        tmp_path,
        [obs("AAA", "Assets", "2024-12-31", "2025-02-10", 900),
         obs("AAA", "Assets", "2024-09-30", "2024-11-10", 800)],
        tag_index=[idx("AAA", "Assets", "2024-12-31", "2025-02-10", 12345),   # clobber try
                   idx("AAA", "AssetsCurrent", "2024-12-31", "2025-02-10", 2000),
                   idx("ZZZ", "AssetsCurrent", "2024-12-31", "2025-02-10", 1)])
    facts = secsv.merge_tag_index(secsv.load_facts(data_dir), data_dir)

    series = facts["AAA"]["facts"]["us-gaap"]["Assets"]["units"]["USD"]
    assert len(series) == 2 and {e["val"] for e in series} == {900.0, 800.0}  # untouched
    folded = facts["AAA"]["facts"]["us-gaap"]["AssetsCurrent"]["units"]["USD"]
    assert folded == [{"end": "2024-12-31", "filed": "2025-02-10",
                       "form": "10-Q", "val": 2000.0}]
    assert "ZZZ" not in facts            # a symbol with no series is never invented


def test_tag_index_fold_is_idempotent_and_readable_by_pit(tmp_path):
    """A folded row is a legal companyfacts entry: pit reads it as an INSTANT (it has no
    start), so it reaches the balance sheet — and only the balance sheet."""
    observations, tag_index = full_filer("SYN")
    observations = [row for row in observations
                    if row["tag"] != "DepreciationDepletionAndAmortization"]
    tag_index.append(idx("SYN", "DepreciationDepletionAndAmortization",
                         "2025-12-31", "2026-02-10", 240))
    data_dir = write_export(tmp_path, observations, tag_index=tag_index)

    facts = secsv.merge_tag_index(secsv.load_facts(data_dir), data_dir)
    once = json.dumps(facts, sort_keys=True)
    assert json.dumps(secsv.merge_tag_index(facts, data_dir), sort_keys=True) == once

    bundle = pit.as_of_bundle(facts["SYN"], "SYN", None, "2026-06-30", {})
    latest = bundle["quarterly"]["balance"][max(bundle["quarterly"]["balance"])]
    assert latest["Current Assets"] == 2000.0 and latest["Current Liabilities"] == 800.0
    assert latest["Working Capital"] == 1200.0            # derived by pit, not here
    # The flow tag is not reachable from a startless point, so the default fold skips it...
    assert "DepreciationDepletionAndAmortization" not in facts["SYN"]["facts"]["us-gaap"]

    # ...and folding it anyway (tags=None) changes nothing: it is inert, not wrong.
    everything = secsv.merge_tag_index(secsv.load_facts(data_dir), data_dir, tags=None)
    assert "DepreciationDepletionAndAmortization" in everything["SYN"]["facts"]["us-gaap"]
    assert pit.as_of_bundle(everything["SYN"], "SYN", None, "2026-06-30", {}) == bundle


# ------------------------------------------------------------- bundles + PIT wiring

def test_bundles_use_pit_and_drop_names_without_an_annual_period(tmp_path):
    observations, tag_index = full_filer("SYN")
    observations.append(obs("NEW", "Revenues", "2025-03-31", "2025-05-10", 5,
                            start="2025-01-01"))          # quarters only, no 10-K yet
    data_dir = write_export(tmp_path, observations, tag_index=tag_index)

    rows = secsv.bundles(data_dir, "2026-06-30", symbols=["NEW", "SYN"])
    assert [row["symbol"] for row in rows] == ["SYN"]      # order preserved, NEW dropped
    assert rows[0] == pit.as_of_bundle(
        secsv.merge_tag_index(secsv.load_facts(data_dir, symbols=["SYN"]), data_dir)["SYN"],
        "SYN", None, "2026-06-30", {})


def test_filed_date_discipline_survives_the_round_trip(tmp_path):
    """A row filed after as_of does not exist — and the pre-first-filing tick has no
    bundle at all (§5.9), straight through the CSV serialization."""
    data_dir = write_export(tmp_path, [
        obs("AAA", "Revenues", "2024-12-31", "2025-02-15", 100, start="2024-01-01",
            form="10-K"),
        obs("AAA", "Revenues", "2024-12-31", "2025-06-01", 120, start="2024-01-01",
            form="10-K/A"),
        obs("AAA", "Assets", "2024-12-31", "2025-02-15", 900),
    ])
    before = secsv.bundles(data_dir, "2025-03-01", use_tag_index=False)
    after = secsv.bundles(data_dir, "2025-07-01", use_tag_index=False)
    assert before[0]["annual"]["income"]["2024-12-31"]["Total Revenue"] == 100.0
    assert after[0]["annual"]["income"]["2024-12-31"]["Total Revenue"] == 120.0
    assert secsv.bundles(data_dir, "2025-01-01", use_tag_index=False) == []


def test_priceless_bundle_scores_insufficient(tmp_path):
    """The export ships no prices, so market_cap is None and the name is INSUFFICIENT —
    correct and expected: a quality profile is not a verdict (SCORECARD-DESIGN.md §4.1)."""
    observations, tag_index = full_filer("SYN")
    data_dir = write_export(tmp_path, observations, tag_index=tag_index)

    rows = secsv.bundles(data_dir, "2026-06-30")
    assert [row["market_cap"] for row in rows] == [None]
    assert [row["price"] for row in rows] == [None]
    scored = scoring.score_universe(rows)
    assert scored[0]["grade"] == "INSUFFICIENT"
    assert "owner-FCF yield" in scored[0]["note"]


# -------------------------------------------------------------------- prices (§3.6)

def test_prices_make_market_cap_computable_and_the_name_grades(tmp_path):
    """With the owner's own weekly_prices.csv the Price block becomes computable: market
    cap appears and the name gets a real grade instead of suspending."""
    observations, tag_index = full_filer("SYN")
    data_dir = write_export(tmp_path, observations, tag_index=tag_index)
    prices = write_prices(tmp_path, [("SYN", "2026-06-26", 50.0, 48.0),
                                     ("SYN", "2026-07-03", 60.0, 58.0)])   # after as_of

    grid = secsv.load_prices(prices)
    assert grid == {"SYN": {"2026-06-26": {"close": 50.0, "adj_close": 48.0},
                            "2026-07-03": {"close": 60.0, "adj_close": 58.0}}}
    assert secsv.degraded_price_symbols(grid) == []

    rows = secsv.bundles(data_dir, "2026-06-30", prices=prices)
    assert rows[0]["price"] == 50.0                      # RAW close, never the adjusted one
    assert rows[0]["market_cap"] == 5000.0               # 100 shares x 50.0
    scored = scoring.score_universe(rows)
    assert scored[0]["grade"] not in (None, "INSUFFICIENT", "VETOED"), scored[0]["note"]
    assert scored[0]["composite"] is not None

    # ...and the tag-index fold is what makes ROIC (a §4.6 REQUIRED metric) computable at
    # all: current assets exist nowhere else in the export.
    without_fold = scoring.score_universe(
        secsv.bundles(data_dir, "2026-06-30", prices=prices, use_tag_index=False))
    assert without_fold[0]["grade"] == "INSUFFICIENT"
    assert without_fold[0]["note"].endswith("ROIC")


def test_price_column_spellings_and_the_degraded_single_column_grid(tmp_path):
    both = secsv.load_prices(write_prices(
        tmp_path, [("SYN", "2026-06-26", 50.0, 48.0)],
        columns=("Ticker", "Date", "Close", "Adj Close"), name="a.csv"))
    assert both["SYN"]["2026-06-26"] == {"close": 50.0, "adj_close": 48.0}

    adj_only = secsv.load_prices(write_prices(
        tmp_path, [("SYN", "2026-06-26 00:00:00", 48.0)],
        columns=("symbol", "date", "adjusted_close"), name="b.csv"))
    assert adj_only["SYN"]["2026-06-26"] == {"adj_close": 48.0}
    assert secsv.degraded_price_symbols(adj_only) == ["SYN"]      # disclosed, §3.6
    assert pit.price_at(adj_only, "SYN", "2026-06-30", "close") == 48.0   # stands for both


def test_unrecognisable_price_columns_fail_loudly(tmp_path):
    path = write_prices(tmp_path, [("SYN", "2026-06-26", 50.0)],
                        columns=("instrument", "when", "quote"))
    with pytest.raises(ValueError) as excinfo:
        secsv.load_prices(path)
    message = str(excinfo.value)
    assert "instrument" in message and "when" in message and "quote" in message
    assert "no symbol column" in message and "no date column" in message


# ------------------------------------------------------------------ universe / meta

def test_universe_join_attaches_sector_and_industry(tmp_path):
    observations, tag_index = full_filer("SYN")
    data_dir = write_export(tmp_path, observations, tag_index=tag_index)
    universe = tmp_path / "universe.csv"
    _write(universe, ["symbol", "name", "sector", "industry", "country", "market_cap",
                      "exchange", "currency"],
           [{"symbol": "SYN", "name": "Synthetic Corp", "sector": "Information Technology",
             "industry": "Software", "country": "United States", "market_cap": "Large Cap",
             "exchange": "NMS", "currency": "USD"}])

    meta = secsv.load_universe_meta(universe)
    assert meta["SYN"] == {"name": "Synthetic Corp", "sector": "Information Technology",
                           "industry": "Software"}
    joined = secsv.bundles(data_dir, "2026-06-30", meta=meta)[0]
    assert (joined["sector"], joined["industry"]) == ("Information Technology", "Software")

    bare = secsv.bundles(data_dir, "2026-06-30")[0]       # no --universe -> stated, never guessed
    assert bare["sector"] is None and bare["industry"] is None and bare["name"] is None


# ------------------------------------------------------------------------------ CLI

def test_cli_writes_jsonl_and_honours_limit(tmp_path, capsys):
    observations, tag_index = full_filer("SYN")
    other, other_index = full_filer("TWO")
    data_dir = write_export(tmp_path, observations + other, tag_index=tag_index + other_index)
    out = tmp_path / "bundles.jsonl"

    assert secsv.main(["--data-dir", str(data_dir), "--as-of", "2026-06-30",
                       "--limit", "1", "--out", str(out)]) == 0
    rows = secsv.read_jsonl(out)
    assert [row["symbol"] for row in rows] == ["SYN"]
    assert rows == secsv.bundles(data_dir, "2026-06-30", symbols=["SYN"])
    assert "KWALITEITSPROFIEL" in capsys.readouterr().err   # §4.1 no-price disclosure


def test_cli_with_prices_reports_market_caps(tmp_path, capsys):
    observations, tag_index = full_filer("SYN")
    data_dir = write_export(tmp_path, observations, tag_index=tag_index)
    prices = write_prices(tmp_path, [("SYN", "2026-06-26", 50.0, 48.0)])

    assert secsv.main(["--data-dir", str(data_dir), "--as-of", "2026-06-30",
                       "--prices", str(prices)]) == 0
    captured = capsys.readouterr()
    assert "1 met market_cap" in captured.out
    assert "KWALITEITSPROFIEL" not in captured.err
