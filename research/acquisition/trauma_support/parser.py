"""Fail-closed readers for pinned official programme editions.

Keep printed strings and source locators. State/name normalization is only a
candidate comparison key, never a reviewed campus identity.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import pdfplumber

from research.trauma.national.parser import read_pdf as read_freeze


EDITIONS = {
    "freeze65": {
        "file": "freeze65-programme.pdf",
        "sha256": "fb0deb83f24ee85612a10cdcb491a14b6d667e02874e8800f341d3ba33236586",
        "url": "https://www.mohfw-dohfw.gov.in/static/uploads/2025/11/444e913a7f93a8a4ac9aeaa8658abd62.pdf",
        "published_date": None,
        "scope": "11th/12th Plan construction and support; publication date unknown",
    },
    "functional2025": {
        "file": "functional-20250725.pdf",
        "sha256": "c5e206028dd54cdf12786cc464fa4e95d7e67f39a7343f647aa4dba29946ff7b",
        "url": "https://sansad.in/getFile/loksabhaquestions/annex/185/AU982_6nsyH6.pdf?source=pqals",
        "published_date": "2025-07-25",
        "scope": "Lok Sabha UQ 982, Annexure A section 3(ii)/(iii), programme functionality",
    },
    "sanction2026": {
        "file": "sanction-20260310.pdf",
        "sha256": "dd723795fc9bc5d1d7a73d288a78239df2595ed0dcbacc986bdc318f1ab433db",
        "url": "https://sansad.in/getFile/annex/270/AU2048_OvVj2M.pdf?source=pqars",
        "published_date": "2026-03-10",
        "scope": "Rajya Sabha UQ 2048, Annexure I, sanctioned facilities only",
    },
}
FAMILY = "mohfw_nppmtbi_state_programme_returns"
RIGHTS = "Raw PDF and printed-name extracts: permission unconfirmed; local working copy only."


def compact(value):
    return re.sub(r"[^\w]", "", (value or "").casefold())


STATES = (
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam",
    "Bihar", "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli", "Daman and Diu",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala",
    "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
)
STATE_KEYS = {compact(s): s for s in STATES}
STATE_KEYS.update({
    "andamannikobar": "Andaman and Nicobar Islands",
    "andamannicobar": "Andaman and Nicobar Islands",
    "andamannicobarislands": "Andaman and Nicobar Islands",
    "dadarnagarhaveli": "Dadra and Nagar Haveli",
    "dadranagarhaveli": "Dadra and Nagar Haveli",
    "jammukashmir": "Jammu and Kashmir", "jk": "Jammu and Kashmir",
    "orissa": "Odisha", "uttrakhand": "Uttarakhand",
    "nctofdelhi": "Delhi", "newdelhi": "Delhi", "pondicherry": "Puducherry",
})


def state_key(value):
    # Historical boundaries stay separate: do not recode old J&K to Ladakh.
    return STATE_KEYS.get(compact(value))


def functionality(value):
    key = compact(value)
    if key == "functional":
        return "reported_functional"
    if key in {"nonfunctional", "nonfunctioanl"}:
        return "reported_nonfunctional"
    if not key:
        return "not_reported"
    raise ValueError("Unrecognized functionality wording; review the source")


@dataclass(frozen=True)
class GridRow:
    page: int
    cells: tuple


def parse_grid(grids, resource, width, expected, has_status):
    records, state, state_page = [], None, None
    for row in grids:
        if len(row.cells) != width:
            raise ValueError("Unexpected table width")
        cells = row.cells
        if not cells[0] or not re.fullmatch(r"\d+", cells[0]):
            first = compact(cells[0])
            if first in {"sno", "slno", "detailsof47burnunits"}:
                continue
            raise ValueError("Unrecognized non-data table row")
        serial = int(cells[0])
        if serial != len(records) + 1:
            raise ValueError("Discontinuous or duplicate source serial")
        if cells[1]:
            state, state_page = cells[1], row.page
        if not state or not state_key(state) or not cells[2]:
            raise ValueError("Missing/unrecognized state or facility name")
        records.append({
            "resource": resource, "section": resource, "serial": serial,
            "page": row.page, "state_printed": state, "state_page": state_page,
            "state": state_key(state), "name_printed": cells[2], "raw_cells": list(cells),
            "level_printed": cells[3] if width == 6 or not has_status else None,
            "plan_printed": cells[4] if width == 6 else None,
            "status_printed": cells[-1] if has_status else None,
            "functionality": functionality(cells[-1]) if has_status else "not_reported",
            "programme_stage": "sanctioned", "source_facility_identifier": None,
        })
    if len(records) != expected:
        raise ValueError(f"Expected {expected} rows, found {len(records)}")
    return records


def read_edition(directory, edition):
    spec = EDITIONS[edition]
    path = Path(directory) / spec["file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
        raise ValueError(f"{edition}: bytes differ from reviewed edition")
    if edition == "freeze65":
        document = read_freeze(path)
        rows = [{
            "resource": "trauma_care", "section": r.section.key,
            "serial": r.serial, "page": r.page, "state_printed": r.state,
            "state_page": r.state_page, "state": state_key(r.state),
            "name_printed": r.name, "raw_cells": [r.excerpt],
            "level_printed": r.printed_level, "plan_printed": None,
            "status_printed": r.printed_status,
            "functionality": functionality(r.printed_status),
            "programme_stage": r.section.key, "source_facility_identifier": None,
        } for r in document.rows]
        if len(rows) != 196 or any(not r["state"] for r in rows):
            raise ValueError("Freeze count/state check failed")
    else:
        rows = []
        with pdfplumber.open(path) as pdf:
            groups = ([("trauma_care", range(6, 15), 6, 196, True),
                       ("burn_treatment", range(14, 17), 4, 47, True)]
                      if edition == "functional2025" else
                      [("trauma_care", range(1, 7), 4, 196, False)])
            for resource, pages, width, total, has_status in groups:
                grids = []
                for index in pages:
                    # July p.9 omits part of the right border. The verified
                    # column edge is x=523 on all July trauma/burn pages.
                    settings = {"explicit_vertical_lines": [523]} if has_status else {}
                    for table in pdf.pages[index].find_tables(settings):
                        if len(table.columns) == width:
                            grids.extend(GridRow(index + 1, tuple(c)) for c in table.extract())
                rows.extend(parse_grid(grids, resource, width, total, has_status))
    for row in rows:
        locator = f"{row['section']}:PDF-p{row['page']}:serial-{row['serial']}"
        row.update({
            "mention_id": f"{spec['sha256']}:{locator}", "edition": edition,
            "locator": locator, "source_sha256": spec["sha256"],
            "source_url": spec["url"], "source_family": FAMILY,
            "publisher": "Ministry of Health and Family Welfare, Government of India",
            "published_date": spec["published_date"],
            "effective_date": None, "reported_as_of": spec["published_date"], "valid_until": None,
            "date_basis": "answer date; no separate facility observation date" if spec["published_date"] else "unknown",
            "units": "programme facility", "count": None,
            "negation": row["functionality"] == "reported_nonfunctional",
            "current_availability": "unknown", "campus_link": "unreviewed",
            "rights": RIGHTS,
        })
    return rows
