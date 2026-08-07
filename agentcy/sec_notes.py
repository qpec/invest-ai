"""Conservative streaming importer for official SEC Financial Statement Notes data."""
from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from pathlib import Path

from agentcy.sec_statements import _file_hash, _supplement_rows, canonical_labels


def allowed_form(form: str) -> bool:
    return str(form).upper() in {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def allowed_report_category(category: str) -> bool:
    return category in {"N", "D", "T"}


def _rows(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
        yield from csv.DictReader(text, delimiter="\t")


def _date(value: str) -> str:
    value = str(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def import_archive(conn, path: Path, *, eligible_ciks: set[str], imported_at: str) -> dict:
    path = Path(path)
    archive_hash = _file_hash(path)
    existing = conn.execute(
        "SELECT import_run_id,status,fact_count FROM sec_notes_import_run WHERE archive_name=? AND archive_hash=?",
        (path.name, archive_hash),
    ).fetchone()
    if existing and existing["status"] == "SUCCEEDED":
        return {"facts": int(existing["fact_count"]), "status": "SUCCEEDED"}

    with conn:
        if existing:
            run_id = int(existing["import_run_id"])
            conn.execute(
                "UPDATE sec_notes_import_run SET started_at=?,finished_at=NULL,"
                " status='RUNNING',failure_summary=NULL WHERE import_run_id=?",
                (imported_at, run_id),
            )
        else:
            conn.execute(
                "INSERT INTO sec_notes_import_run"
                " (archive_name,archive_hash,started_at,status) VALUES (?,?,?,'RUNNING')",
                (path.name, archive_hash, imported_at),
            )
            run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    try:
        with zipfile.ZipFile(path) as archive:
            submissions = {}
            for row in _rows(archive, "sub.tsv"):
                cik = str(row.get("cik") or "").zfill(10)
                if cik in eligible_ciks and allowed_form(row.get("form") or ""):
                    submissions[row["adsh"]] = {
                        "cik": cik,
                        "filed_at": _date(row["filed"]),
                        "form": row["form"],
                    }

            reports = {}
            for row in _rows(archive, "ren.tsv"):
                category = row.get("menucat") or ""
                if row["adsh"] in submissions and allowed_report_category(category):
                    reports[(row["adsh"], row["report"])] = (
                        category,
                        row.get("shortname") or row.get("longname") or "",
                    )

            monetary = set()
            for row in _rows(archive, "tag.tsv"):
                datatype = (row.get("datatype") or "").lower()
                if row.get("abstract") == "0" and "monetary" in datatype:
                    monetary.add((row["tag"], row["version"]))

            concepts = {}
            for row in _rows(archive, "pre.tsv"):
                report = reports.get((row["adsh"], row["report"]))
                concept = (row["tag"], row["version"])
                if report is None or concept not in monetary:
                    continue
                labels = canonical_labels(row["tag"], row.get("plabel") or "")
                if labels:
                    concepts[(row["adsh"], *concept)] = (*report, labels)

            inserted = 0
            batch = []
            for row in _rows(archive, "num.tsv"):
                concept = concepts.get((row["adsh"], row["tag"], row["version"]))
                if concept is None or row.get("dimh") != "0x00000000" or row.get("coreg"):
                    continue
                try:
                    quarters = int(row["qtrs"])
                    value = float(row["value"])
                except (TypeError, ValueError):
                    continue
                if quarters not in {0, 1, 4}:
                    continue
                meta = submissions[row["adsh"]]
                category, report_name, labels = concept
                for label in labels:
                    material = "|".join((
                        path.name, row["adsh"], category, row["tag"], row["version"],
                        label, row["ddate"], str(quarters), row["uom"], str(value),
                    ))
                    batch.append((
                        run_id, row["adsh"], meta["cik"], meta["filed_at"], meta["form"],
                        category, report_name, row["tag"], row["version"], label,
                        _date(row["ddate"]), quarters, row["uom"], value,
                        hashlib.sha256(material.encode()).hexdigest(), imported_at,
                    ))
                if len(batch) >= 5000:
                    before = conn.total_changes
                    conn.executemany(
                        "INSERT OR IGNORE INTO sec_notes_fact"
                        " (import_run_id,accession,cik,filed_at,form,report_category,report_name,"
                        " taxonomy_tag,taxonomy_version,canonical_label,period_end,quarters,unit,"
                        " value,source_hash,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        batch,
                    )
                    inserted += conn.total_changes - before
                    batch.clear()
                    conn.commit()
            if batch:
                before = conn.total_changes
                conn.executemany(
                    "INSERT OR IGNORE INTO sec_notes_fact"
                    " (import_run_id,accession,cik,filed_at,form,report_category,report_name,"
                    " taxonomy_tag,taxonomy_version,canonical_label,period_end,quarters,unit,"
                    " value,source_hash,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                inserted += conn.total_changes - before
                conn.commit()

        inserted = int(conn.execute(
            "SELECT COUNT(*) FROM sec_notes_fact WHERE import_run_id=?", (run_id,)
        ).fetchone()[0])
        with conn:
            conn.execute(
                "UPDATE sec_notes_import_run SET finished_at=?,status='SUCCEEDED',fact_count=?"
                " WHERE import_run_id=?",
                (imported_at, inserted, run_id),
            )
        return {"facts": inserted, "status": "SUCCEEDED"}
    except Exception as error:
        with conn:
            conn.execute(
                "UPDATE sec_notes_import_run SET finished_at=?,status='FAILED',failure_summary=?"
                " WHERE import_run_id=?",
                (imported_at, str(error), run_id),
            )
        raise


def supplement_bundle(conn, *, cik: str, as_of: str, bundle: dict) -> dict:
    """Fill still-absent series from unconflicted, period-safe Notes facts."""
    rows = list(conn.execute(
        "SELECT fact.* FROM sec_notes_fact fact"
        " JOIN sec_notes_import_run run ON run.import_run_id=fact.import_run_id"
        " WHERE run.status='SUCCEEDED' AND fact.cik=? AND fact.filed_at<=?"
        " ORDER BY canonical_label,period_end,quarters,filed_at,accession,fact_id",
        (str(cik).zfill(10), as_of),
    ))
    return _supplement_rows(rows, bundle)
