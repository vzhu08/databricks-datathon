"""Build conservative equipment observations from explicit workbook columns.

Unknown layouts stay in the raw rows and mention review queue. Blank/merged
names are not filled down. Form, installation and breakdown dates remain
separate, and no observation here establishes delivered clinical service.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .capture import canonical, sha256, write_json
from .extract import as_text, modality_hits


def folded(value):
    return re.sub(r"\s+", " ", as_text(value)).strip().casefold()


def header_fields(cells):
    fields = defaultdict(list)
    for col, value in cells.items():
        text = folded(value)
        if re.search(r"equipment\s+(?:name|description)|name of (?:the )?equipment", text):
            fields["equipment"].append(col)
        elif re.search(r"institut(?:e|ion) name|name of (?:the )?facility|facility name|hospital name", text) and len(text) < 90:
            fields["facility"].append(col)
        elif re.fullmatch(r"district(?: name)?", text):
            fields["district"].append(col)
        elif re.search(r"serial\s*(?:no|number)|equipment s\.?no", text):
            fields["serial"].append(col)
        elif re.search(r"barcode|equipment id", text):
            fields["equipment_id"].append(col)
        elif re.search(r"^qty\.?$|^quantity(?:\s|$)|total available", text):
            fields["quantity"].append(col)
        elif re.search(r"status|functional|working", text) and not re.search(r"date|reason", text):
            fields["condition"].append(col)
        elif re.search(r"date|since|upto|warranty|amc|cmc", text):
            fields["dates_and_coverage"].append(col)
    if len(fields["equipment"]) != 1 or sum(bool(v) for v in fields.values()) < 2:
        return None
    return dict(fields)


def condition(value):
    value = folded(value)
    return {"functional": "functional", "working": "functional",
            "non functional not repairable": "nonfunctional_not_repairable",
            "non functional repairable": "nonfunctional_repairable",
            "not working": "nonfunctional", "non functional": "nonfunctional",
            "not installed": "not_installed"}.get(value, "uninterpreted" if value else None)


def classify_rows(rows):
    """One observation per explicit equipment-name row under a known header.

    Emits all equipment, not only the search lexicon, retaining zero quantities.
    Multi-facility/group scope is never resolved by the parser.
    """
    sheet, fields, headers, context, context_rows = None, None, {}, [], []
    for row in rows:
        if row.get("kind") != "sheet_row":
            continue
        if row["sheet"] != sheet:
            sheet, fields, headers, context, context_rows = row["sheet"], None, {}, [], []
        cells = row["cells"]
        new_fields = header_fields(cells)
        if new_fields:
            fields, headers = new_fields, cells.copy()
            continue
        if fields is None:
            if len(context) < 8:
                context.append(cells)
                context_rows.append(row["row"])
            continue
        # Preserve W/NW column labels in a separate header row. Numeric coding
        # and symbolic status are left uninterpreted without a source legend.
        if any(folded(v) in {"w", "nw"} for v in cells.values()) and not cells.get(fields["equipment"][0]):
            for col, value in cells.items():
                if folded(value) in {"w", "nw"}:
                    headers[col] = as_text(headers.get(col, "")) + " / " + as_text(value)
                    fields.setdefault("condition", [])
                    if col not in fields["condition"]:
                        fields["condition"].append(col)
            continue
        equipment = cells.get(fields["equipment"][0])
        if not isinstance(equipment, str) or not equipment.strip():
            continue
        if folded(equipment) in {"total", "grand total", "equipment name", "equipment description"}:
            continue
        def values(key):
            return [{"column": int(col), "header": headers.get(col), "value": cells.get(col)}
                    for col in fields.get(key, [])]
        names = values("facility")
        # Only an explicit single facility column provides a printed row name.
        name = names[0]["value"] if len(names) == 1 else None
        if not isinstance(name, str) or not name.strip():
            name = None
        flags = ["historical_equipment_only", "condition_observation_date_unreviewed", "campus_unreviewed"]
        if name is None:
            flags.append("facility_in_sheet_or_context_requires_review")
        elif re.search(r"&|\band\b|associated|group", name, re.I):
            flags.append("possible_group_not_campus")
        evidence_key = hashlib.sha256((row["record_id"] + ":equipment").encode()).hexdigest()
        yield {"observation_id": evidence_key, "record_id": row["record_id"],
               "edition_sha256": row["edition_sha256"], "sheet": sheet, "row": row["row"],
               "equipment_column": int(fields["equipment"][0]), "equipment_printed": equipment,
               "modalities": sorted({x[0] for x in modality_hits(equipment)}),
               "facility_printed": name, "facility_column_values": names,
               "source_facility_key": None if name is None else hashlib.sha256(
                   canonical([row["edition_sha256"], name, values("district")]).encode()).hexdigest(),
               "district_fields": values("district"), "serial_fields": values("serial"),
               "equipment_id_fields": values("equipment_id"), "quantity_fields": values("quantity"),
               "quantity_unit": "equipment units as printed in Qty/Quantity; no imputed unit count",
               "condition_fields": [{**v, "interpretation": condition(v["value"])} for v in values("condition")],
               "dates_and_coverage_fields": values("dates_and_coverage"),
               "heading_context": context, "heading_context_rows": context_rows,
               "publication_date": None, "observation_period": None,
               "address": None, "pin": None, "campus_id": None,
               "source_family": "nhsrc_bemmp_equipment_mapping", "flags": flags,
               "service_decision": None}


def build(root):
    root = Path(root)
    editions = json.loads((root / "editions.json").read_text())
    occurrences = json.loads((root / "file-occurrences.json").read_text())
    states = defaultdict(set)
    for occurrence in occurrences:
        if occurrence.get("sha256"):
            states[occurrence["sha256"]].add(occurrence["state_printed"])
    counts, by_state, by_modality = Counter(), defaultdict(Counter), Counter()
    row_ids, source_facilities = set(), set()
    serial_records, sheet_counts = defaultdict(list), Counter()
    rajasthan = []
    output = root / "equipment-observations.jsonl.gz"
    with output.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as out:
        for edition in editions:
            if edition["status"] != "text_extracted_review_pending" or edition["suffix"] not in {".xls", ".xlsx"}:
                continue
            source = root / edition["extracted_path"]
            if sha256(source) != edition["extracted_sha256"]:
                raise ValueError("extraction digest mismatch")
            with gzip.open(source, "rt", encoding="utf-8") as stream:
                for observation in classify_rows(json.loads(line) for line in stream):
                    observation["catalogue_state_labels"] = sorted(states[edition["sha256"]])
                    out.write((canonical(observation) + "\n").encode())
                    counts["equipment_rows"] += 1
                    sheet_counts[(edition["sha256"], observation["sheet"])] += 1
                    row_ids.add(observation["record_id"])
                    if observation["source_facility_key"]:
                        source_facilities.add(observation["source_facility_key"])
                    for field in observation["serial_fields"]:
                        serial = as_text(field["value"]).strip()
                        if serial.casefold() not in {"", "na", "n.a", "n.a.", "n/a", "nil", "none", "*", "-", "0", "0.0", "not available"} and len(serial) >= 3:
                            serial_records[serial].append({"record_id": observation["record_id"],
                                "edition_sha256": edition["sha256"], "sheet": observation["sheet"],
                                "row": observation["row"], "facility_printed": observation["facility_printed"],
                                "equipment_printed": observation["equipment_printed"]})
                    counts["rows_with_explicit_facility"] += observation["facility_printed"] is not None
                    counts["rows_with_target_modality"] += bool(observation["modalities"])
                    for modality in observation["modalities"]:
                        by_modality[modality] += 1
                        for state in observation["catalogue_state_labels"]:
                            by_state[state][modality] += 1
                    # This source control is selected by immutable edition, not by
                    # a generalised claim about all Rajasthan equipment.
                    if edition["sha256"] == "e2f8e392ce107e6b3cd213db7f188ce648c29b329c7455f69f40163eec4aaadd" and observation["sheet"] == "Mapping Data" and observation["equipment_printed"].strip() == "Dialysis Unit":
                        rajasthan.append(observation)
    qa = {"dialysis_rows": len(rajasthan),
          "distinct_nonblank_institute_labels": len({x["facility_printed"] for x in rajasthan if x["facility_printed"]}),
          "distinct_nonblank_serials": len({as_text(v["value"]).strip() for x in rajasthan for v in x["serial_fields"] if as_text(v["value"]).strip()}),
          "condition_counts": dict(Counter(as_text(v["value"]) for x in rajasthan for v in x["condition_fields"])),
          "first_excel_row": min((x["row"] for x in rajasthan), default=None)}
    serial_groups = [{"serial_printed": serial, "records": records,
                      "distinct_editions": len({r["edition_sha256"] for r in records}),
                      "interpretation": "Repeated identifier lead; not proof of the same physical device."}
                     for serial, records in sorted(serial_records.items()) if len(records) > 1]
    write_json(root / "duplicate-serial-groups.json", serial_groups)
    sheet_dispositions = [{"edition_sha256": e["sha256"], "sheet": s["sheet"],
                           "source_nonempty_rows": s["nonempty_rows"],
                           "explicit_equipment_rows": sheet_counts[(e["sha256"], s["sheet"])],
                           "disposition": "explicit_header_rows_extracted_remaining_raw_preserved" if sheet_counts[(e["sha256"], s["sheet"])] else "raw_only_layout_or_summary_review"}
                          for e in editions if e["suffix"] in {".xlsx", ".xls"} for s in e["parts"]]
    write_json(root / "sheet-dispositions.json", sheet_dispositions)
    summary = {**dict(counts), "unique_source_record_ids": len(row_ids),
               "edition_scoped_source_facility_keys": len(source_facilities),
               "campus_count": None, "target_modality_equipment_rows": dict(by_modality),
               "by_catalogue_state": {k: dict(v) for k, v in sorted(by_state.items())},
               "rajasthan_control": qa,
               "repeated_serial_string_groups": len(serial_groups),
               "repeated_serial_groups_across_editions": sum(x["distinct_editions"] > 1 for x in serial_groups),
               "sheet_dispositions": dict(Counter(x["disposition"] for x in sheet_dispositions)),
               "warnings": ["Rows may repeat across sheets, summaries, files and editions. No summable unique device count is claimed.",
                            "Unrecognised or merged layouts remain in extracted rows and lexical mention ledger.",
                            "Source row names may denote groups; no national campus or service review has run."],
               "output_sha256": sha256(output)}
    write_json(root / "observation-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(build(args.root)))


if __name__ == "__main__":
    main()
