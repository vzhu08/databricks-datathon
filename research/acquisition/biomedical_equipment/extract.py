"""Offline extraction of every captured file, sheet, page and archive member.

The mention ledger is a search/review index, not a service evidence producer.
No filename date, count, condition, campus or service is inferred from a hit.
Original row/cell positions and contradictory or duplicate records survive.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import re
import warnings
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, time
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from lxml import etree

from . import PARSER_VERSION
from .capture import canonical, sha256, write_json

MODALITIES = {
    "mri": r"\bm\.?\s*r\.?\s*i\.?\b|\bmagnetic\s+resonance\b",
    "dialysis": r"\b(?:ha?emodialys\w*|dialys\w*)\b",
    "ct": r"\bct\s*(?:scan(?:ner)?|machine|unit)\b|\bc\.?t\.?\b(?=\s*$)|\bcomputed\s+tomograph\w*\b",
    "x_ray": r"\bx[\s-]*ray\w*\b|\bradiograph\w*\b",
    "ultrasound": r"\bultra[\s-]*sound\w*\b|\bultrasonograph\w*\b|\busg\b|\bsonograph\w*\b",
    "ventilation": r"\bventilat(?:or|ion|ors)\b",
    "anaesthesia": r"\ban[ae]*esthe(?:sia|tic)\b|\bboyle'?s?\b",
    "emergency_equipment": r"\bdefibrillat\w*\b|\bresuscitat\w*\b|\bcrash\s*cart\b",
}
PATTERNS = {key: re.compile(value, re.I) for key, value in MODALITIES.items()}
NOTICE = re.compile(r"copyright|©|all\s+rights\s+reserved|confidential|not\s+(?:be\s+)?reproduc|permission\s+to\s+reproduc", re.I)
DATE_CUE = re.compile(r"\bas\s+(?:on|of)\b|\bsurvey\b|\b(?:observation|mapping|report|visit|inventory)\s+date\b|\b20(?:0\d|1\d|2\d)\b", re.I)
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024


def scalar(value):
    if isinstance(value, (date, datetime, time)):
        return {"type": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        return {"type": "nonfinite", "value": str(value)}
    return value


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("value", value))
    return str(value)


def modality_hits(text):
    return [(name, match.start(), match.end(), match.group())
            for name, pattern in PATTERNS.items() for match in pattern.finditer(text)]


def safe_members(archive):
    """Validate entire ZIP before reading; don't extract into caller filesystem."""
    members = archive.infolist()
    if len(members) > 10000 or sum(x.file_size for x in members) > MAX_ARCHIVE_BYTES:
        raise ValueError("archive size/member limit")
    for item in members:
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename:
            raise ValueError("unsafe archive member path")
        if item.file_size > MAX_MEMBER_BYTES or item.flag_bits & 1:
            raise ValueError("oversized or encrypted archive member")
        if (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("archive symlink")
    return [item for item in members if not item.is_dir()]


def workbook_rows(path, suffix, sheets):
    """Yield every nonempty source row. Sparse columns are 1-based."""
    if suffix == ".xlsx":
        yield from xlsx_rows(path, sheets)
    else:
        if b"<html" in path.read_bytes()[:4096].lower() or b"<!doctype html" in path.read_bytes()[:4096].lower():
            from lxml import html
            doc = html.fromstring(path.read_bytes())
            heading = " ".join(doc.xpath("//body//text()[not(ancestor::table)]"))
            if heading.strip():
                yield {"kind": "html_heading", "cells": {"1": heading}}
            for number, table in enumerate(doc.xpath("//table[not(ancestor::table)]"), 1):
                name = f"HTML table {number}"
                meta = {"sheet": name, "nonempty_rows": 0, "format": "HTML served as XLS", "hidden": None}
                sheets.append(meta)
                for row in html_table_rows(table, name):
                    if any(v.strip() for v in row["cells"].values()):
                        meta["nonempty_rows"] += 1
                        yield row
            return
        import xlrd
        book = xlrd.open_workbook(str(path), on_demand=True)
        try:
            for sheet in book.sheets():
                meta = {"sheet": sheet.name, "declared_rows": sheet.nrows,
                        "declared_columns": sheet.ncols, "nonempty_rows": 0,
                        "hidden": bool(sheet.visibility), "formula_cells": None,
                        "formula_note": "XLS reader returns cached values; raw BIFF retained."}
                sheets.append(meta)
                for row in range(sheet.nrows):
                    cells = {}
                    for col in range(sheet.ncols):
                        cell = sheet.cell(row, col)
                        if cell.ctype not in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                            value = cell.value
                            if cell.ctype == xlrd.XL_CELL_DATE:
                                try:
                                    value = xlrd.xldate_as_datetime(value, book.datemode)
                                except xlrd.XLDateError:
                                    value = {"type": "invalid_excel_date", "value": value}
                            elif cell.ctype == xlrd.XL_CELL_ERROR:
                                value = {"type": "excel_error", "value": xlrd.error_text_from_code.get(value, str(value))}
                            cells[str(col + 1)] = scalar(value)
                    if cells:
                        meta["nonempty_rows"] += 1
                        yield {"kind": "sheet_row", "sheet": sheet.name, "row": row + 1,
                               "cells": cells, "formulas": None}
        finally:
            book.release_resources()


def html_table_rows(table, name):
    """Reserve cells covered by rowspans without copying their values down.

    A reserved slot is absent from `cells`, rather than populated with an
    invented repeated hospital/equipment/quantity. Malformed overlapping spans
    fail the file extraction rather than assigning cells to ambiguous headers.
    HTML rowspan=0 extends to the end of its own row group, not the next group.
    """
    rows = table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")
    group_ends = {row.getparent(): n for n, row in enumerate(rows, 1)}
    occupied = {}
    for rownum, row in enumerate(rows, 1):
        occupied = {col: span for col, span in occupied.items() if span["end_row"] >= rownum}
        inherited = {str(col): dict(span) for col, span in sorted(occupied.items())}
        cells, col, spans = {}, 1, {}
        for cell in row.xpath("./th|./td"):
            while col in occupied:
                col += 1
            raw_rowspan, raw_colspan = cell.get("rowspan", "1"), cell.get("colspan", "1")
            rowspan, colspan = int(raw_rowspan), int(raw_colspan)
            if rowspan == 0:
                rowspan = group_ends[row.getparent()] - rownum + 1
            if not (1 <= rowspan <= 100000 and 1 <= colspan <= 3000):
                raise ValueError("invalid HTML span; manual layout review required")
            if rownum + rowspan - 1 > group_ends[row.getparent()]:
                raise ValueError("HTML rowspan crosses row group; manual layout review required")
            if any(c in occupied for c in range(col, col + colspan)):
                raise ValueError("overlapping HTML spans; manual layout review required")
            cells[str(col)] = cell.text_content()
            spans[str(col)] = {"rowspan": raw_rowspan, "colspan": raw_colspan}
            if rowspan > 1:
                for c in range(col, col + colspan):
                    occupied[c] = {"origin_row": rownum, "origin_column": col,
                                   "end_row": rownum + rowspan - 1}
            col += colspan
        result = {"kind": "sheet_row", "sheet": name, "row": rownum, "cells": cells,
                  "formulas": None, "html_spans": spans,
                  "layout_note": "HTML cell spans retained; rowspans are not filled down."}
        if inherited:
            result["reserved_html_columns"] = inherited
        yield result


def xlsx_rows(path, sheets):
    """Read physical XML rows, including cells outside stale dimensions.

    Sparse XML traversal avoids expanding formatted million-row sheets. Cached
    values and formulas are retained separately without evaluating source code.
    """
    from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
    from openpyxl.utils.cell import column_index_from_string
    from openpyxl.utils.datetime import from_excel, CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    prefix = "{" + ns["s"] + "}"
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with zipfile.ZipFile(path) as archive:
        safe_members(archive)
        workbook = etree.fromstring(archive.read("xl/workbook.xml"), parser)
        rels = etree.fromstring(archive.read("xl/_rels/workbook.xml.rels"), parser)
        targets = {x.get("Id"): x.get("Target") for x in rels}
        epoch = CALENDAR_MAC_1904 if workbook.xpath("boolean(s:workbookPr[@date1904='1' or @date1904='true'])", namespaces=ns) else CALENDAR_WINDOWS_1900
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = etree.fromstring(archive.read("xl/sharedStrings.xml"), parser)
            strings = ["".join(x.xpath(".//s:t/text()", namespaces=ns)) for x in shared]
        formats, date_styles = dict(BUILTIN_FORMATS), set()
        if "xl/styles.xml" in archive.namelist():
            styles = etree.fromstring(archive.read("xl/styles.xml"), parser)
            formats.update({int(x.get("numFmtId")): x.get("formatCode") for x in styles.xpath("s:numFmts/s:numFmt", namespaces=ns)})
            date_styles = {i for i, x in enumerate(styles.xpath("s:cellXfs/s:xf", namespaces=ns))
                           if is_date_format(formats.get(int(x.get("numFmtId", 0)), ""))}
        for sheet in workbook.xpath("s:sheets/s:sheet", namespaces=ns):
            rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = targets[rid]
            member = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if ".." in PurePosixPath(member).parts:
                raise ValueError("unsafe workbook sheet relationship")
            meta = {"sheet": sheet.get("name"), "nonempty_rows": 0, "physical_rows": 0,
                    "hidden": sheet.get("state", "visible") != "visible", "formula_cells": 0,
                    "merged_ranges": []}
            sheets.append(meta)
            with archive.open(member) as stream:
                for _, element in etree.iterparse(stream, events=("end",), resolve_entities=False, no_network=True):
                    if element.tag == prefix + "mergeCell":
                        meta["merged_ranges"].append(element.get("ref"))
                    if element.tag != prefix + "row":
                        continue
                    meta["physical_rows"] += 1
                    cells, formulas = {}, {}
                    for cell in element:
                        if cell.tag != prefix + "c":
                            continue
                        coordinate = cell.get("r")
                        col = str(column_index_from_string(re.match(r"[A-Z]+", coordinate)[0]))
                        kind = cell.get("t")
                        raw_value = cell.findtext(prefix + "v")
                        formula = cell.find(prefix + "f")
                        if kind == "inlineStr":
                            value = "".join(cell.xpath(".//s:t/text()", namespaces=ns))
                        elif raw_value is None:
                            value = None
                        elif kind == "s":
                            value = strings[int(raw_value)]
                        elif kind == "b":
                            value = raw_value == "1"
                        elif kind in {"e", "str", "d"}:
                            value = {"type": "excel_error", "value": raw_value} if kind == "e" else raw_value
                        else:
                            value = float(raw_value) if any(c in raw_value.lower() for c in ".e") else int(raw_value)
                            if int(cell.get("s", 0)) in date_styles:
                                try:
                                    value = from_excel(value, epoch)
                                except (ValueError, OverflowError):
                                    value = {"type": "invalid_excel_date", "value": raw_value}
                        if value is not None or formula is not None:
                            cells[col] = scalar(value)
                        if formula is not None:
                            formulas[col] = {"text": formula.text, "attributes": dict(formula.attrib)}
                    if cells or formulas:
                        meta["nonempty_rows"] += 1
                        meta["formula_cells"] += len(formulas)
                        yield {"kind": "sheet_row", "sheet": meta["sheet"], "row": int(element.get("r")),
                               "cells": cells, "formulas": formulas}
                    element.clear()
                    while element.getprevious() is not None:
                        del element.getparent()[0]


def document_rows(path, suffix, parts):
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text(extraction_mode="plain") or ""
            parts.append({"page": number, "characters": len(text),
                          "status": "text_extracted" if text.strip() else "requires_visual_or_ocr_review"})
            # Page text and line numbers are extraction locators, never table rows.
            for line, value in enumerate(text.splitlines(), 1):
                if value.strip():
                    yield {"kind": "pdf_line", "page": number, "line": line, "cells": {"1": value}}
    elif suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            safe_members(archive)
            names = [n for n in archive.namelist() if n.startswith("word/") and
                     re.search(r"/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$", n)]
            for name in sorted(names):
                doc = etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                paragraphs = doc.xpath("//w:p", namespaces=ns)
                parts.append({"part": name, "paragraphs": len(paragraphs),
                              "tables": len(doc.xpath("//w:tbl", namespaces=ns)),
                              "status": "xml_text_extracted_layout_review_pending"})
                for number, para in enumerate(paragraphs, 1):
                    text = "".join(para.xpath(".//w:t/text()", namespaces=ns))
                    if text.strip():
                        yield {"kind": "docx_paragraph", "part": name, "paragraph": number, "cells": {"1": text}}
    else:
        raise ValueError(f"unsupported format: {suffix}")


def extract(root):
    root = Path(root)
    catalogue = json.loads((root / "catalogue.json").read_text())
    downloads = json.loads((root / "downloads.json").read_text())
    by_url = {r["url"]: r for r in downloads}
    editions = {}
    occurrences = []

    def add_file(path, name, context, depth=0):
        digest = sha256(path)
        occurrence = {**context, "name": name, "sha256": digest, "bytes": path.stat().st_size}
        occurrences.append(occurrence)
        suffix = Path(name).suffix.lower()
        with path.open("rb") as stream:
            magic = stream.read(8)
        declared_suffix = suffix
        # NHSRC has an OLE/BIFF workbook served with an .xlsx filename.
        if suffix in {".xls", ".xlsx"}:
            if magic.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
                suffix = ".xls"
            elif magic.startswith(b"PK"):
                suffix = ".xlsx"
        if digest in editions and suffix == ".zip":
            if depth >= 3:
                raise ValueError("archive nesting limit")
            with zipfile.ZipFile(path) as archive:
                for position, member in enumerate(safe_members(archive), 1):
                    content = archive.read(member)
                    child = root / "blobs" / hashlib.sha256(content).hexdigest()
                    add_file(child, member.filename, {**context, "parent_sha256": digest,
                             "member_position": position, "member_path": member.filename}, depth + 1)
            return
        if digest in editions:
            return
        meta = {"sha256": digest, "bytes": path.stat().st_size, "path": str(path.relative_to(root)),
                "suffix": suffix, "declared_suffix": declared_suffix, "status": "pending", "parts": [], "row_count": 0,
                "mentions": Counter(), "notice_hits": [], "date_cues": [],
                "publication_date": None, "observation_period": None,
                "source_family": "nhsrc_bemmp_equipment_mapping", "independence": "shared_programme_lineage",
                "rights_status": "file_review_pending", "parser_version": PARSER_VERSION,
                "container_notice_hits": [], "embedded_media_files": []}
        editions[digest] = meta
        try:
            if suffix in {".xlsx", ".docx"}:
                with zipfile.ZipFile(path) as archive:
                    safe_members(archive)
                    meta["embedded_media_files"] = [n for n in archive.namelist() if "/media/" in n]
                    for member in archive.namelist():
                        if member.endswith(".xml"):
                            # Scan headers, footers, comments and other text parts,
                            # not only cells. Preserve exact hit + part for review.
                            content = archive.read(member).decode("utf-8", errors="replace")
                            for match in NOTICE.finditer(content):
                                meta["container_notice_hits"].append({"part": member,
                                    "offset": match.start(), "context": content[max(0, match.start()-80):match.end()+160]})
            if suffix == ".zip":
                if depth >= 3:
                    raise ValueError("archive nesting limit")
                with zipfile.ZipFile(path) as archive:
                    members = safe_members(archive)
                    for position, member in enumerate(members, 1):
                        content = archive.read(member)
                        member_digest = hashlib.sha256(content).hexdigest()
                        dest = root / "blobs" / member_digest
                        if not dest.exists():
                            dest.write_bytes(content)
                        add_file(dest, member.filename, {**context, "parent_sha256": digest,
                                 "member_position": position, "member_path": member.filename}, depth + 1)
                    meta["parts"] = [{"members": len(members)}]
                    meta["status"] = "archive_enumerated"
                return
            if suffix in {".xlsx", ".xls"}:
                rows = workbook_rows(path, suffix, meta["parts"])
            else:
                rows = document_rows(path, suffix, meta["parts"])
            output = root / "extracted" / f"{digest}.jsonl.gz"
            output.parent.mkdir(exist_ok=True)
            # mtime=0 and empty filename make replayed gzip bytes deterministic.
            with output.open("wb") as raw_out, gzip.GzipFile(filename="", fileobj=raw_out, mode="wb", mtime=0) as out:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    for row in rows:
                        row_id = hashlib.sha256(canonical({"edition": digest, **{k: v for k, v in row.items() if k not in {"cells", "formulas"}}}).encode()).hexdigest()
                        row["record_id"] = row_id
                        row["edition_sha256"] = digest
                        out.write((canonical(row) + "\n").encode())
                        meta["row_count"] += 1
                        locator = {k: v for k, v in row.items() if k not in {"cells", "formulas", "edition_sha256"}}
                        for col, value in row["cells"].items():
                            text = as_text(value)
                            if NOTICE.search(text):
                                meta["notice_hits"].append({**locator, "column": int(col), "text": text})
                            if DATE_CUE.search(text) and len(meta["date_cues"]) < 200:
                                meta["date_cues"].append({**locator, "column": int(col), "text": text})
                            for modality, start, end, exact in modality_hits(text):
                                meta["mentions"][modality] += 1
                                mention_id = hashlib.sha256(f"{row_id}:{col}:{modality}:{start}".encode()).hexdigest()
                                mentions.write(canonical({"mention_id": mention_id, **locator,
                                    "edition_sha256": digest, "column": int(col), "modality": modality,
                                    "start": start, "end": end, "exact_match": exact,
                                    "source_cell": value, "row_cells": row["cells"],
                                    "assertion_type": "unreviewed_lexical_mention",
                                    "publication_date": None, "observation_period": None,
                                    "campus_id": None, "service_decision": None}) + "\n")
                    meta["warnings"] = sorted({str(w.message) for w in caught})
            meta["extracted_path"] = str(output.relative_to(root))
            meta["extracted_sha256"] = sha256(output)
            meta["status"] = "text_extracted_review_pending"
            meta["rights_status"] = "notice_requires_review" if meta["notice_hits"] or meta["container_notice_hits"] else "no_text_notice_found_visual_review_pending"
        except Exception as exc:
            meta["status"] = "extraction_gap"
            meta["error"] = f"{type(exc).__name__}: {exc}"

    mention_path = root / "mentions.jsonl"
    with mention_path.open("w", encoding="utf-8") as mentions:
        for item in catalogue:
            receipt = by_url.get(item["url"])
            if not receipt or not receipt.get("download_ok"):
                occurrences.append({"entry": item["entry"], "state_printed": item["state_printed"],
                                    "url": item["url"], "status": "download_gap"})
                continue
            path = root / receipt["path"]
            if sha256(path) != receipt["sha256"]:
                raise ValueError("download digest mismatch")
            add_file(path, unquote(urlsplit(item["url"]).path.rsplit("/", 1)[-1]),
                     {"entry": item["entry"], "state_printed": item["state_printed"], "url": item["url"]})
    # Every catalogue occurrence still references its blob; children inherit all
    # parent entries when an archive's bytes are listed under multiple URLs.
    write_json(root / "file-occurrences.json", occurrences)
    write_json(root / "editions.json", sorted(editions.values(), key=lambda x: x["sha256"]))
    counts = Counter()
    for edition in editions.values():
        counts.update(edition["mentions"])
    summary = {"parser_version": PARSER_VERSION, "catalogue_occurrences": len(catalogue),
               "file_occurrences_including_members": len(occurrences), "unique_editions_including_members": len(editions),
               "status_counts": dict(Counter(x["status"] for x in editions.values())),
               "extracted_rows_lines_paragraphs": sum(x["row_count"] for x in editions.values()),
               "lexical_mentions_by_modality": dict(counts),
               "mention_definition": "One regex hit at an exact cell/line/paragraph character offset; not a device, facility or service count.",
               "source_families": 1, "unresolved_campus_matches": None,
               "national_comparison": "pending_pinned_base_and_Vincent_review",
               "national_occurrence_denominator": 10088, "distinct_upstream_id_denominator": 10077,
               "service_decision_denominator": 30264, "changed_service_decisions": None,
               "live_databricks_checked": False}
    write_json(root / "extraction-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(extract(args.root)))


if __name__ == "__main__":
    main()
