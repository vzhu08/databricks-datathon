#!/usr/bin/env python3
"""Extract the printed table rows of a roster PDF, unchanged, with their locators.

    python -m research.matching.pmndp.extract --pdf <file> --output <rows.json>

Needs pdfplumber (research/acquisition/requirements-pdf.txt). The output holds
source text, so keep it under ignored data/local/. Nothing is interpreted here:
column meaning comes from the profile given to the importer.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from research.matching.common import MatchingError, file_digest, require, write_json

_SPACE = re.compile(r"\s+")


def clean(cell):
    """Whitespace collapsed; an empty cell becomes None. No other change."""
    if cell is None:
        return None
    text = _SPACE.sub(" ", str(cell)).strip()
    return text or None


def lines_above(words, columns, top, bottom):
    """Rows printed between `top` and `bottom` that sit in the table's columns.

    A table that continues on a new page can lose its first row when the page
    has no rule above it. `words` are {"text", "x0", "x1", "top"}; `columns`
    are (x0, x1) pairs. A line is kept only when its words fall in at least
    half of the columns, so a heading above the table is not taken for a row.
    """
    lines = {}
    for word in words:
        if top <= word["top"] < bottom:
            lines.setdefault(round(word["top"] / 3), []).append(word)
    found = []
    for key in sorted(lines):
        cells = [[] for _ in columns]
        for word in sorted(lines[key], key=lambda w: w["x0"]):
            centre = (word["x0"] + word["x1"]) / 2
            for index, (x0, x1) in enumerate(columns):
                if x0 <= centre < x1:
                    cells[index].append(word["text"])
        if sum(bool(c) for c in cells) * 2 >= len(columns) and len(columns) > 1:
            found.append([clean(" ".join(c)) for c in cells])
    return found


def table_rows(pdf_path):
    """Rows of every ruled table, plus `recovered` rows printed directly above a
    table in its columns. Recovered rows are numbered 0, -1, ... upwards."""
    import pdfplumber
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            floor = 0
            words = page.extract_words()
            for table_number, table in enumerate(page.find_tables(), start=1):
                boxes = [cell for row in table.rows for cell in row.cells if cell]
                edges = sorted({round(b[0]) for b in boxes} | {round(max(b[2] for b in boxes))})
                columns = list(zip(edges, edges[1:]))
                above = lines_above(words, columns, floor, table.bbox[1])
                for offset, cells in enumerate(above):
                    rows.append({"page": page_number, "table": table_number, "row": offset - len(above) + 1,
                                 "cells": cells, "recovered": "text_above_table"})
                for row_number, cells in enumerate(table.extract(), start=1):
                    rows.append({"page": page_number, "table": table_number, "row": row_number,
                                 "cells": [clean(cell) for cell in cells]})
                floor = table.bbox[3]
    return pages, rows


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.matching.pmndp.extract", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--output", required=True, help="Rows file; keep it under data/local/")
    args = parser.parse_args(argv)
    try:
        pages, rows = table_rows(args.pdf)
        require(bool(rows), "pdf", "no table rows were found; the document may be a scan")
        digest = write_json(Path(args.output), {"source_sha256": file_digest(args.pdf), "pages": pages, "rows": rows})
        print(f"pages={pages} rows={len(rows)} rows_file_sha256={digest}")
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
