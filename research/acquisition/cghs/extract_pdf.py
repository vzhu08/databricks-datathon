"""Extract explicitly selected ruled PDF tables for subsequent producer review."""
import argparse
import json
import re
from pathlib import Path

from research.acquisition.common import file_digest, write_json
from .collector import require, text

FIELDS = {"serial", "name_raw", "address_raw", "scope_raw", "validity_raw", "scheme_id",
          "scheme_id_namespace", "city", "state", "pin", "institution_type"}


def extract(path, layout):
    import pdfplumber  # Optional dependency; offline JSON intake does not require it.

    require(isinstance(layout, list) and bool(layout), "explicit_table_layout_required")
    positions = [(item["page"], item["table"]) for item in layout]
    require(positions == sorted(set(positions)), "table_layout_must_be_unique_and_ordered")
    records, seen, current = [], set(), None
    with pdfplumber.open(path) as pdf:
        for item in layout:
            page_no, table_no = item["page"], item["table"]
            section = text(item["section"])
            require(type(page_no) is int and type(table_no) is int and 1 <= page_no <= len(pdf.pages)
                    and table_no > 0, "invalid_table_position")
            page = pdf.pages[page_no - 1]
            tables = page.find_tables()
            require(table_no <= len(tables), "table_not_found")
            table = tables[table_no - 1]
            raw_rows = table.extract()
            columns = item["columns"]
            require(isinstance(columns, list) and len(columns) == len(raw_rows[0]), "column_count_changed")
            fields = [c["field"] for c in columns]
            require(set(fields) <= FIELDS and len(fields) == len(set(fields))
                    and {"serial", "name_raw"} <= set(fields), "invalid_column_fields")
            actual = [" ".join((cell or "").split()).casefold() for cell in raw_rows[0]]
            expected = [" ".join(text(c["header"]).split()).casefold() for c in columns]
            require(actual == expected, "table_header_changed")
            boxes = table.rows[0].cells
            require(all(box is not None for box in boxes), "ambiguous_header_geometry")
            for row_no, raw_row in enumerate(raw_rows[1:], 1):
                if [" ".join((cell or "").split()).casefold() for cell in raw_row] == expected:
                    continue
                band = table.rows[row_no].bbox
                cells = {}
                for field, box in zip(fields, boxes):
                    # Character centres avoid losing glyphs that touch a table border.
                    x0, x1, top, bottom = box[0], box[2], band[1], band[3]
                    value = page.filter(lambda obj: obj.get("object_type") == "char"
                        and x0 <= (obj["x0"] + obj["x1"]) / 2 < x1
                        and top <= (obj["top"] + obj["bottom"]) / 2 < bottom).extract_text(x_tolerance=2, y_tolerance=3)
                    if value:
                        cells[field] = value
                serial = cells.pop("serial", "").strip().rstrip(".")
                if serial:
                    require(bool(re.fullmatch(r"[1-9][0-9]*", serial)), "unrecognized_row_serial")
                    require((section, serial) not in seen, "repeated_serial_requires_explicit_section")
                    seen.add((section, serial))
                    current = {"locator": {"page": page_no, "table": table_no, "section": section, "row": serial},
                               "fragments": []}
                    records.append(current)
                elif cells:
                    require(current is not None and current["locator"]["section"] == section,
                            "orphan_continuation_requires_review")
                else:
                    continue
                for field, value in cells.items():
                    current[field] = current.get(field, "") + ("\n" if current.get(field) else "") + value
                current["fragments"].append({"page": page_no, "table": table_no,
                    "bbox": [round(n, 3) for n in band], "fields": cells})
    require(bool(records), "no_table_records")
    return {"raw_sha256": file_digest(path), "review_status": "unreviewed", "reviewer": None,
            "note": "Check original cells, assign campus/group kind, geography, rights and relationships before producer_checked intake.",
            "rows": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="private, unreviewed extraction JSON")
    args = parser.parse_args()
    require(not args.out.exists(), "extraction_output_already_exists")
    result = extract(args.pdf, json.loads(args.layout.read_text(encoding="utf-8")))
    write_json(args.out, result)
    print(json.dumps({"rows": len(result["rows"]), "review_status": "unreviewed"}))


if __name__ == "__main__":
    main()
