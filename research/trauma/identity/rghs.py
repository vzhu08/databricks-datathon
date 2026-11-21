"""Extract RGHS identity cells from page-addressable PDF tables."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


HEADER = {
    "serial": {"sno", "srno", "slno", "serialno", "serialnumber"},
    "identifier": {"id", "hospitalid", "hospitalidentifier", "hospitalcode",
                   "facilityid", "facilitycode", "rghshospitalid", "hcnpid", "hfrid"},
    "name": {"facilityname", "hospitalname", "nameofhospital", "nameoffacility",
             "nameofgovernmenthospital", "hospitalnameaspertms", "hospital"},
    "address": {"address", "hospitaladdress", "facilityaddress", "completeaddress"},
    "district": {"district", "districtname"},
    "city": {"city", "cityname", "town"},
    "state": {"state", "statename"},
    "pin": {"pin", "pincode", "postalcode"},
    "effective": {"effectivefrom", "validfrom", "empanelmentfrom", "empanelmentdate"},
    "expiry": {"empanelmentvalidtill", "validtill", "validupto", "validuntil",
               "expirydate", "empanelmentvalidupto"},
}
DATE_PATTERN = r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}"


def key(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def parse_date(value: str | None) -> str | None:
    if not value or not re.fullmatch(DATE_PATTERN, value.strip()):
        return None
    parts = re.split(r"[-/.]", value.strip())
    if len(parts[0]) == 4:
        year, month, day = parts
    elif len(parts[2]) == 4:
        day, month, year = parts
    else:
        return None
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def header_columns(cells: list[str]) -> dict[str, int]:
    tokens = [key(cell) for cell in cells]
    return {
        field_name: tokens.index(token)
        for field_name, aliases in HEADER.items()
        for token in tokens
        if token in aliases
    }


def has_header(columns: dict[str, int]) -> bool:
    return "name" in columns and bool(
        columns.keys() & {"identifier", "serial", "address", "district", "city"}
    )


def nonblank(cell: str | None) -> str:
    if cell is None or not any(char.isalnum() for char in cell):
        return ""
    return cell.strip()


@dataclass
class Table:
    page: int
    index: int
    rows: list[list[str | None]]
    method: str = "ruled"


@dataclass
class Row:
    fields: dict[str, str]
    locator: str
    continuation_locators: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    identifier_label: str | None = None

    @property
    def record_locator(self) -> str:
        return "; continuation at ".join([self.locator, *self.continuation_locators])


def parse_tables(tables: list[Table]) -> tuple[list[Row], list[dict]]:
    """Carry compatible column layouts across pages and report unassigned material."""
    rows = []
    issues = []
    columns = {}
    identifier_label = None
    active_width = 0
    previous_page = 0
    for table in tables:
        if table.page > previous_page + 1:
            columns = {}
        previous_page = table.page
        previous_row = None
        for index, raw_cells in enumerate(table.rows, 1):
            cells = [nonblank(cell) for cell in raw_cells]
            if not any(cells):
                continue
            locator = f"PDF page {table.page}, table {table.index}, row {index}"
            found = header_columns(cells)
            if has_header(found):
                columns = found
                active_width = len(cells)
                identifier_label = cells[found["identifier"]] if "identifier" in found else None
                previous_row = None
                continue
            if not columns or active_width != len(cells):
                issues.append({"locator": locator, "code": "unrecognized_layout", "cells": raw_cells})
                continue
            fields = {name: cells[position] for name, position in columns.items() if cells[position]}
            if fields.get("serial") and not re.fullmatch(r"\d+[.)]?", fields["serial"]):
                issues.append({"locator": locator, "code": "section_or_non_numeric_serial",
                               "cells": raw_cells})
                previous_row = None
                continue
            is_identified = bool(fields.keys() & {"serial", "identifier"})
            if not is_identified and fields.keys() == {"address"} and previous_row:
                address = previous_row.fields.get("address", "")
                previous_row.fields["address"] = "\n".join(filter(None, [address, fields["address"]]))
                previous_row.continuation_locators.append(locator)
                continue
            if not is_identified and not fields.get("name"):
                issues.append({"locator": locator, "code": "unassigned_section_or_row",
                               "cells": raw_cells})
                previous_row = None
                continue
            if not is_identified and columns.keys() & {"serial", "identifier"} and not (
                fields.keys() & {"address", "district", "city"}
            ):
                issues.append({"locator": locator, "code": "unassigned_name_or_section",
                               "cells": raw_cells})
                previous_row = None
                continue
            flags = [f"missing_{name}" for name in ("name", "address", "district") if not fields.get(name)]
            if not fields.get("identifier"):
                flags.append("missing_hospital_identifier")
            for date_field in ("effective", "expiry"):
                if fields.get(date_field) and not parse_date(fields[date_field]):
                    flags.append(f"invalid_{date_field}_date")
            if table.method != "ruled":
                flags.append("text_layout_review_required")
            previous_row = Row(fields, locator, flags=flags, identifier_label=identifier_label)
            rows.append(previous_row)

    unique_rows = []
    seen = {}
    for row in rows:
        if "identifier" in row.fields:
            key_fields = tuple(sorted((name, value) for name, value in row.fields.items()
                                      if name != "serial"))
            record = (key(row.identifier_label or ""), key_fields)
            if record in seen:
                issues.append({"locator": row.locator, "code": "duplicate_identifier_payload",
                               "retained_locator": seen[record]})
                continue
            seen[record] = row.locator
        unique_rows.append(row)
    ids = Counter((key(row.identifier_label or ""), row.fields["identifier"])
                  for row in unique_rows if "identifier" in row.fields)
    for row in unique_rows:
        if ids[(key(row.identifier_label or ""), row.fields.get("identifier"))] > 1:
            row.flags.append("repeated_hospital_identifier")
            issues.append({"locator": row.record_locator, "code": "conflicting_identifier_payload"})
    return unique_rows, issues


def extract_pdf(path: Path) -> tuple[list[Row], list[dict], dict]:
    import pdfplumber

    tables = []
    text_pages = []
    page_table_counts = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text() or ""
            text_pages.append(page_text)
            cleaned = page.dedupe_chars()
            page_tables = cleaned.extract_tables()
            method = "ruled"
            if not page_tables and page_text:
                page_tables = cleaned.extract_tables({"vertical_strategy": "text",
                                                      "horizontal_strategy": "text"})
                method = "text"
            tables.extend(Table(number, index, table, method)
                          for index, table in enumerate(page_tables, 1))
            page_table_counts.append(len(page_tables))
    rows, issues = parse_tables(tables)
    for page, count in enumerate(page_table_counts, 1):
        if not count:
            issues.append({"locator": f"PDF page {page}", "code": "no_extractable_table"})
    dates = {}
    for name, phrase in (("document_as_of", r"updated\s+(?:till|through|as of)"),
                         ("published_date", r"published\s+(?:on|date\s*:)")):
        dates[name] = [
            {"date": parse_date(match[1]), "excerpt": match[0], "locator": f"PDF page {page}"}
            for page, text in enumerate(text_pages, 1)
            for match in re.finditer(rf"{phrase}\s+({DATE_PATTERN})", text, re.I)
        ]
    return rows, issues, {"page_table_counts": page_table_counts, **dates}


def normalize_words(value: str | None) -> list[str]:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    # Join dotted initials, while leaving normal punctuation as a separator.
    text = re.sub(r"\b(?:[a-z]\.\s*)+[a-z](?![a-z])",
                  lambda match: re.sub(r"[.\s]", "", match[0]), text)
    words = []
    for char in text:
        words.append(char if unicodedata.category(char)[0] in "LMN" else " ")
    return "".join(words).split()
