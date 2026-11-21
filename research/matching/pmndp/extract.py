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


def table_rows(pdf_path):
    import pdfplumber
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            for table_number, table in enumerate(page.extract_tables(), start=1):
                for row_number, cells in enumerate(table, start=1):
                    rows.append({"page": page_number, "table": table_number, "row": row_number,
                                 "cells": [clean(cell) for cell in cells]})
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
