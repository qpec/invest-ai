"""Streaming SEC Financial Statement Data Set importer with conservative semantics."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from pathlib import Path


_TAG_LABELS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": ("Total Revenue",),
    "Revenues": ("Total Revenue",), "SalesRevenueNet": ("Total Revenue",),
    "OperatingIncomeLoss": ("EBIT", "Operating Income"),
    "GrossProfit": ("Gross Profit",), "CostOfRevenue": ("Cost Of Revenue",),
    "CostOfGoodsAndServicesSold": ("Cost Of Revenue",),
    "NetIncomeLoss": ("Net Income",), "ProfitLoss": ("Net Income Including Noncontrolling Interests",),
    "NetCashProvidedByUsedInOperatingActivities": ("Operating Cash Flow",),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("Capital Expenditure",),
    "ShareBasedCompensation": ("Stock Based Compensation",),
    "DepreciationDepletionAndAmortization": ("Depreciation And Amortization",),
    "DepreciationAndAmortization": ("Depreciation And Amortization",),
    "PaymentsOfDividendsCommonStock": ("Cash Dividends Paid",),
    "PaymentsOfDividends": ("Cash Dividends Paid",),
    "PaymentsForRepurchaseOfCommonStock": ("Repurchase Of Capital Stock",),
    "CashAndCashEquivalentsAtCarryingValue": ("Cash And Cash Equivalents",),
    "StockholdersEquity": ("Stockholders Equity",), "Assets": ("Total Assets",),
    "AssetsCurrent": ("Current Assets",), "LiabilitiesCurrent": ("Current Liabilities",),
    "Liabilities": ("Total Liabilities",), "Goodwill": ("Goodwill",),
    "IntangibleAssetsNetExcludingGoodwill": ("Intangible Assets",),
    "RetainedEarningsAccumulatedDeficit": ("Retained Earnings",),
    "DebtAndCapitalLeaseObligations": ("Total Debt",),
    "DebtLongtermAndShorttermCombinedAmount": ("Total Debt",),
    "InterestExpense": ("Interest Expense",), "InterestExpenseNonoperating": ("Interest Expense",),
    "ResearchAndDevelopmentExpense": ("Research And Development",),
    "IncomeTaxExpenseBenefit": ("Income Tax Expense",),
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": ("Pretax Income",),
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments": ("Pretax Income",),
    "IncomeTaxesPaidNet": ("Income Taxes Paid",), "IncomeTaxesPaid": ("Income Taxes Paid",),
    "PaymentsToAcquireBusinessesNetOfCashAcquired": ("Acquisitions",),
    "PaymentsToAcquireBusinessesGross": ("Acquisitions",),
}


def _norm(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(label).lower()).strip()


_CUSTOM_LABELS = {
    "total revenue": ("Total Revenue",), "total revenues": ("Total Revenue",),
    "net revenue": ("Total Revenue",), "net revenues": ("Total Revenue",),
    "net sales": ("Total Revenue",), "revenue": ("Total Revenue",),
    "revenues": ("Total Revenue",),
    "operating income": ("EBIT", "Operating Income"),
    "operating income loss": ("EBIT", "Operating Income"),
    "gross profit": ("Gross Profit",), "cost of revenue": ("Cost Of Revenue",),
    "net income": ("Net Income",), "net cash provided by operating activities": ("Operating Cash Flow",),
    "net cash provided by used in operating activities": ("Operating Cash Flow",),
    "capital expenditures": ("Capital Expenditure",),
    "payments to acquire property plant and equipment": ("Capital Expenditure",),
    "stock based compensation": ("Stock Based Compensation",),
    "depreciation and amortization": ("Depreciation And Amortization",),
    "research and development expense": ("Research And Development",),
    "income tax expense benefit": ("Income Tax Expense",),
    "income taxes paid": ("Income Taxes Paid",),
    "cash and cash equivalents": ("Cash And Cash Equivalents",),
    "total assets": ("Total Assets",), "total liabilities": ("Total Liabilities",),
    "stockholders equity": ("Stockholders Equity",),
    "current assets": ("Current Assets",), "current liabilities": ("Current Liabilities",),
    "goodwill": ("Goodwill",), "retained earnings": ("Retained Earnings",),
}


def canonical_labels(tag: str, presentation_label: str) -> tuple[str, ...]:
    return _TAG_LABELS.get(tag) or _CUSTOM_LABELS.get(_norm(presentation_label), ())


def _rows(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
        yield from csv.DictReader(text, delimiter="\t")


def _date(value: str) -> str:
    value = str(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_archive(conn, path: Path, *, eligible_ciks: set[str], imported_at: str) -> dict:
    path = Path(path)
    archive_hash = _file_hash(path)
    existing = conn.execute(
        "SELECT import_run_id,status,fact_count FROM sec_statement_import_run"
        " WHERE archive_name=? AND archive_hash=?", (path.name, archive_hash)
    ).fetchone()
    if existing and existing["status"] == "SUCCEEDED":
        return {"facts": int(existing["fact_count"]), "status": "SUCCEEDED"}
    with conn:
        if existing:
            run_id = int(existing["import_run_id"])
            conn.execute(
                "UPDATE sec_statement_import_run SET started_at=?,finished_at=NULL,"
                " status='RUNNING',failure_summary=NULL WHERE import_run_id=?",
                (imported_at, run_id),
            )
        else:
            conn.execute(
                "INSERT INTO sec_statement_import_run"
                " (archive_name,archive_hash,started_at,status) VALUES (?,?,?,'RUNNING')",
                (path.name, archive_hash, imported_at),
            )
            run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    count = 0
    try:
        with zipfile.ZipFile(path) as archive:
            submissions = {}
            for row in _rows(archive, "sub.txt"):
                cik = str(row.get("cik") or "").zfill(10)
                if cik in eligible_ciks:
                    submissions[row["adsh"]] = {
                        "cik": cik, "filed_at": _date(row["filed"]), "form": row["form"],
                        "report_period": _date(row["period"]),
                    }
            presentation = {}
            for row in _rows(archive, "pre.txt"):
                if row["adsh"] not in submissions or row.get("stmt") not in {"BS", "IS", "CF", "EQ", "CI", "CP"}:
                    continue
                labels = canonical_labels(row["tag"], row.get("plabel") or "")
                if labels:
                    presentation[(row["adsh"], row["tag"], row["version"])] = (
                        row["stmt"], labels
                    )
            batch = []
            for row in _rows(archive, "num.txt"):
                key = (row["adsh"], row["tag"], row["version"])
                if key not in presentation or row.get("segments") or row.get("coreg"):
                    continue
                try:
                    quarters = int(row["qtrs"])
                    value = float(row["value"])
                except (TypeError, ValueError):
                    continue
                if quarters not in {0, 1, 4}:
                    continue
                meta = submissions[row["adsh"]]
                statement, labels = presentation[key]
                for label in labels:
                    if label == "Capital Expenditure":
                        value = -abs(value)
                    material = "|".join((path.name, row["adsh"], row["tag"], row["version"],
                                         label, row["ddate"], str(quarters), row["uom"], str(value)))
                    batch.append((run_id, row["adsh"], meta["cik"], meta["filed_at"],
                                  meta["form"], meta["report_period"], statement, row["tag"],
                                  row["version"], label, _date(row["ddate"]), quarters,
                                  row["uom"], value, hashlib.sha256(material.encode()).hexdigest(),
                                  imported_at))
                if len(batch) >= 5000:
                    conn.executemany(
                        "INSERT OR IGNORE INTO sec_statement_fact"
                        " (import_run_id,accession,cik,filed_at,form,report_period,statement,"
                        " taxonomy_tag,taxonomy_version,canonical_label,period_end,quarters,"
                        " unit,value,source_hash,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        batch,
                    )
                    count += len(batch); batch.clear(); conn.commit()
            if batch:
                conn.executemany(
                    "INSERT OR IGNORE INTO sec_statement_fact"
                    " (import_run_id,accession,cik,filed_at,form,report_period,statement,"
                    " taxonomy_tag,taxonomy_version,canonical_label,period_end,quarters,"
                    " unit,value,source_hash,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                count += len(batch); conn.commit()
        count = int(conn.execute(
            "SELECT COUNT(*) FROM sec_statement_fact WHERE import_run_id=?", (run_id,)
        ).fetchone()[0])
        with conn:
            conn.execute(
                "UPDATE sec_statement_import_run SET finished_at=?,status='SUCCEEDED',fact_count=?"
                " WHERE import_run_id=?", (imported_at, count, run_id)
            )
        return {"facts": count, "status": "SUCCEEDED"}
    except Exception as error:
        with conn:
            conn.execute(
                "UPDATE sec_statement_import_run SET finished_at=?,status='FAILED',failure_summary=?"
                " WHERE import_run_id=?", (imported_at, str(error), run_id)
            )
        raise


_INCOME = {"Total Revenue", "EBIT", "Operating Income", "Gross Profit",
           "Cost Of Revenue", "Net Income", "Net Income Including Noncontrolling Interests"}
_CASHFLOW = {"Operating Cash Flow", "Capital Expenditure", "Stock Based Compensation",
             "Depreciation And Amortization", "Cash Dividends Paid",
             "Repurchase Of Capital Stock"}
_BALANCE = {"Cash And Cash Equivalents", "Stockholders Equity", "Total Assets",
            "Current Assets", "Current Liabilities", "Total Debt", "Total Liabilities"}
_SUPPLEMENT_FLOWS = {"Interest Expense", "Research And Development",
                     "Income Tax Expense", "Pretax Income", "Income Taxes Paid",
                     "Acquisitions", "Cash Dividends Paid", "Repurchase Of Capital Stock"}
_SUPPLEMENT_POINTS = {"Goodwill", "Intangible Assets", "Total Liabilities",
                      "Retained Earnings"}
_UNSAFE_AUTOMATIC_TAGS = {"LongTermDebt"}


def _supplement_rows(rows, bundle: dict) -> dict:
    """Fill period-safe missing series from already filtered, accession-linked facts."""
    grouped = {}
    for row in rows:
        if row["taxonomy_tag"] in _UNSAFE_AUTOMATIC_TAGS:
            continue
        grouped.setdefault((row["canonical_label"], row["period_end"], row["quarters"]), []).append(row)
    resolved = []
    for key, candidates in grouped.items():
        latest_filed = max(row["filed_at"] for row in candidates)
        latest = [row for row in candidates if row["filed_at"] == latest_filed]
        values = {float(row["value"]) for row in latest}
        if len(values) != 1:
            continue
        resolved.append((key[0], key[1], int(key[2]), values.pop()))

    def section_has(scope: str, statement: str, label: str) -> bool:
        return any(label in row for row in bundle.get(scope, {}).get(statement, {}).values())

    blocked = set()
    for label, _, quarters, _ in resolved:
        scope = "annual" if quarters == 4 else "quarterly" if quarters == 1 else None
        if scope and label in _INCOME and section_has(scope, "income", label):
            blocked.add((scope, label))
        if scope and label in _CASHFLOW and section_has(scope, "cashflow", label):
            blocked.add((scope, label))
        if quarters == 0 and label in _BALANCE and any(
                section_has(scope_name, "balance", label)
                for scope_name in ("annual", "quarterly")):
            blocked.add(("balance", label))
        if scope and label in _SUPPLEMENT_FLOWS and label in (
                bundle.get("supplements", {}).get("flows", {})):
            blocked.add(("supplement", label))
        if quarters == 0 and label in _SUPPLEMENT_POINTS and label in (
                bundle.get("supplements", {}).get("points", {})):
            blocked.add(("points", label))

    for label, period_end, quarters, value in resolved:
        if quarters == 4:
            scope = "annual"
        elif quarters == 1:
            scope = "quarterly"
        else:
            scope = None
        income_periods = bundle.get(scope or "", {}).get("income", {})
        cashflow_periods = bundle.get(scope or "", {}).get("cashflow", {})
        if (scope and label in _INCOME and (scope, label) not in blocked
                and period_end in income_periods):
            income_periods[period_end].setdefault(label, value)
        if (scope and label in _CASHFLOW and (scope, label) not in blocked
                and period_end in cashflow_periods):
            cashflow_periods[period_end].setdefault(label, value)
        if quarters == 0 and label in _BALANCE and ("balance", label) not in blocked:
            for balance_scope in ("annual", "quarterly"):
                balance_periods = bundle[balance_scope].setdefault("balance", {})
                if period_end in balance_periods:
                    balance_periods[period_end].setdefault(label, value)
        if scope and label in _SUPPLEMENT_FLOWS and ("supplement", label) not in blocked:
            base_periods = (cashflow_periods if label in {
                "Income Taxes Paid", "Acquisitions", "Cash Dividends Paid",
                "Repurchase Of Capital Stock"} else income_periods)
            if period_end in base_periods:
                flows = bundle.setdefault("supplements", {}).setdefault("flows", {})
                flows.setdefault(label, {"annual": {}, "quarterly": {}})[scope].setdefault(period_end, value)
        if quarters == 0 and label in _SUPPLEMENT_POINTS and ("points", label) not in blocked:
            points = bundle.setdefault("supplements", {}).setdefault("points", {})
            old = points.get(label)
            if old is None or period_end > old["end"]:
                points[label] = {"value": value, "end": period_end}
    return bundle


def supplement_bundle(conn, *, cik: str, as_of: str, bundle: dict) -> dict:
    """Fill absent bundle rows from unconflicted filed face-statement facts in place."""
    rows = list(conn.execute(
        "SELECT fact.* FROM sec_statement_fact fact"
        " JOIN sec_statement_import_run run ON run.import_run_id=fact.import_run_id"
        " WHERE run.status='SUCCEEDED' AND fact.cik=? AND fact.filed_at<=?"
        " ORDER BY canonical_label,period_end,quarters,filed_at,accession,fact_id",
        (str(cik).zfill(10), as_of),
    ))
    return _supplement_rows(rows, bundle)
