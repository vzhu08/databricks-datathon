"""Extract explicitly profiled PDF tables without guessing unidentified columns.

Profiles are reviewed layout mappings, not jurisdiction/clinical truth. Blank and
unrecognized physical rows remain in a reject ledger. Contact columns are excluded.
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

import pymupdf

from research.acquisition.common import canonical, digest, read_json, write_json

FIELDS = {"serial", "registration_id", "name", "address", "district", "state", "pin",
          "facility_type", "service_wording", "system_of_medicine"}
SEEDS = {
    "rajasthan": dict(state="Rajasthan", registration_namespace="india:rajasthan:clinical-establishments",
                      column_counts=[12], header_rows={"1": 2}, columns=dict(serial=0, district=1, name=2, facility_type=3,
                                                       address=4, service_wording=-2, system_of_medicine=-1)),
    "telangana": dict(state="Telangana", registration_namespace="india:telangana:clinical-establishments",
                      column_counts=[14, 15], header_rows={"1": 3},
                      split_columns=[11, 2, 2], columns=dict(serial=0, name=1, facility_type=2, address=3,
                                                         state=4, district=5, pin=6, service_wording=-2,
                                                         system_of_medicine=-1)),
}


def clean(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def profile_check(profile):
    if not profile.get("registration_namespace") or not profile.get("state"):
        raise ValueError("A scoped registration namespace and index jurisdiction are required")
    columns = profile["columns"]
    if not {"serial", "name"} <= columns.keys() or set(columns) - FIELDS:
        raise ValueError("Only declared non-contact facility columns are allowed")
    if not profile.get("column_counts") or any(not isinstance(n, int) or n < 2 for n in profile["column_counts"]):
        raise ValueError("Expected table widths are required")
    for n in profile["column_counts"]:
        indices = [i % n for i in columns.values() if isinstance(i, int) and -n <= i < n]
        if len(indices) != len(columns) or len(indices) != len(set(indices)):
            raise ValueError("Column mappings must be distinct and in range at every supported width")


def classify_row(cells, profile, locator):
    if len(cells) not in profile["column_counts"]:
        return None, dict(locator=locator, reason="unreviewed_column_layout", column_count=len(cells))
    values = {key: clean(cells[index]) for key, index in profile["columns"].items()}
    serial = values.get("serial")
    if serial is None or not re.fullmatch(r"\d+[.]?", serial):
        has_values = any(values.values())
        header = bool(serial and re.search(r"(?:s\.?\s*no|sl\s*no|serial)", serial, re.I))
        # Title rows require an explicit reviewed header mapping; an arbitrary
        # nonnumeric value is not silently dismissed as a title.
        reason = "header_or_title" if header else "blank_row" if not has_values else "unresolved_continuation_or_nonserial_row"
        return None, dict(locator=locator, reason=reason, selected_values=values)
    row = {key: values.get(key) for key in FIELDS}
    row.update(locator=locator, index_jurisdiction=profile["state"],
               registration_namespace=profile["registration_namespace"], quality_flags=[])
    row["state"] = row["state"] or profile["state"]
    if row["state"].casefold() != profile["state"].casefold():
        row["quality_flags"].append("source_state_differs_from_index_jurisdiction")
    if "state" not in profile["columns"]:
        row["quality_flags"].append("state_from_index_not_independently_geocoded")
    if not row["registration_id"]:
        row["quality_flags"].append("registration_id_not_present")
    if not row["name"]:
        row["quality_flags"].append("missing_name")
    if not row["address"]:
        row["quality_flags"].append("missing_address")
    return row, None


def table_rows(tables, profile):
    """Join only reviewed horizontal fragments with matching physical row bounds."""
    split = profile.get("split_columns")
    if len(tables) == 2 and split:
        left, right = sorted(tables, key=lambda t: t.bbox[0])
        nleft, nright, gap = split
        if left.col_count != nleft or right.col_count != nright or left.bbox[2] >= right.bbox[0]:
            raise ValueError("Unreviewed split-table layout")
        if len(left.rows) != len(right.rows):
            raise ValueError("Split-table row counts differ")
        for a, b in zip(left.rows, right.rows):
            if abs(a.bbox[1] - b.bbox[1]) > 0.75 or abs(a.bbox[3] - b.bbox[3]) > 0.75:
                raise ValueError("Split-table row boundaries differ")
        return [("1+2 (aligned horizontal fragments)", [a + [None] * gap + b
                  for a, b in zip(left.extract(), right.extract())])]
    return [(str(i), t.extract()) for i, t in enumerate(tables, 1)]


def extract(path, profile):
    profile_check(profile)
    raw = Path(path).read_bytes()
    sha = digest(raw)
    if profile.get("sha256") and sha != profile["sha256"]:
        raise ValueError("Profile is bound to another raw snapshot")
    rows, rejected, pages = [], [], []
    with pymupdf.open(path) as doc:
        for page_no, page in enumerate(doc, 1):
            page_text = page.get_text()
            date_labels = [line.strip() for line in page_text.splitlines()
                           if re.match(r"\s*(?:data\s+as\s+(?:on|of)|as\s+on)\b", line, re.I)]
            tables = page.find_tables().tables
            page_record = dict(page=page_no, tables=len(tables), physical_rows=0,
                               parsed_rows=0, rejected_rows=0, source_date_labels=date_labels,
                               extracted_text_sha256=digest(page_text.encode()), text_characters=len(page_text))
            if not tables:
                rejected.append(dict(locator=f"PDF page {page_no}", reason="no_detected_table",
                                     text_characters=len(page_text)))
            for table_no, extracted in table_rows(tables, profile):
                for row_no, cells in enumerate(extracted, 1):
                    locator = f"PDF page {page_no}, table {table_no}, physical row {row_no} (1-based)"
                    if row_no <= profile.get("header_rows", {}).get(str(page_no), 0):
                        serial = clean(cells[profile["columns"]["serial"]])
                        if serial and re.fullmatch(r"\d+[.]?", serial):
                            raise ValueError("Numeric serial in a configured header row")
                        row, reject = None, dict(locator=locator, reason="header_or_title")
                    else:
                        row, reject = classify_row(cells, profile, locator)
                    page_record["physical_rows"] += 1
                    if row is not None:
                        rows.append(row)
                        page_record["parsed_rows"] += 1
                    else:
                        rejected.append(reject)
                        page_record["rejected_rows"] += 1
            pages.append(page_record)
    serials = [int(row["serial"].rstrip(".")) for row in rows]
    duplicates = sorted(k for k, v in Counter(serials).items() if v > 1)
    gaps = sorted(set(range(min(serials), max(serials) + 1)) - set(serials)) if serials else []
    return dict(raw_sha256=sha, parser_version="ce-register-1", profile=profile,
                profile_sha256=digest(canonical(profile)), rows=rows, rejected_rows=rejected,
                pages=pages, summary=dict(pages=len(pages), physical_rows=sum(p["physical_rows"] for p in pages),
                    parsed_rows=len(rows), rejected_physical_rows=sum(p["rejected_rows"] for p in pages),
                    pages_without_tables=sum(not p["tables"] for p in pages),
                    reject_reasons=dict(Counter(r["reason"] for r in rejected)),
                    serial_min=min(serials) if serials else None, serial_max=max(serials) if serials else None,
                    duplicate_serials=duplicates, missing_serials=gaps,
                    states=dict(Counter(r["state"] for r in rows)),
                    districts=dict(Counter(r["district"] or "unknown" for r in rows)),
                    flagged_rows=sum(bool(r["quality_flags"]) for r in rows)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdf", required=True, type=Path)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", choices=SEEDS)
    group.add_argument("--profile", type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    result = extract(args.pdf, SEEDS[args.seed] if args.seed else read_json(args.profile))
    write_json(args.out, result)
    print(canonical({k:v for k,v in result["summary"].items() if k != "districts"}).decode())


if __name__ == "__main__":
    main()
