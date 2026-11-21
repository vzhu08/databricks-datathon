"""Read the ruled tables in the Ministry's NPPMTBI programme brief."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import pdfplumber


@dataclass(frozen=True)
class Section:
    annexure: int
    key: str
    heading: str
    page: int
    expected_rows: int | None

    @property
    def locator(self):
        return f"Annexure {self.annexure}, PDF p. {self.page}, heading: {self.heading}"


@dataclass(frozen=True)
class GridRow:
    page: int
    cells: tuple[str | None, ...]


@dataclass(frozen=True)
class ProgrammeRow:
    section: Section
    page: int
    serial: int
    state: str
    state_page: int
    name: str | None
    printed_level: str | None
    printed_status: str | None
    excerpt: str

    @property
    def level(self):
        match = re.fullmatch(r"(?:L\s*[-–]\s*)?(III|II|I)\.?",
                             self.printed_level or "", re.IGNORECASE)
        return match[1].upper() if match else None

    @property
    def locator(self):
        return (f"Annexure {self.section.annexure}, {self.section.key}, "
                f"PDF p. {self.page}, serial {self.serial}")

    @property
    def key(self):
        return f"{self.section.key}:{self.serial}"


@dataclass(frozen=True)
class Document:
    sections: dict[str, Section]
    rows: list[ProgrammeRow]
    pages: list[str]
    metadata: dict


def flatten(text):
    return " ".join(text.split())


def is_table_note(text):
    return bool(re.match(r"^(?:notes?\s*:|source\s*:|\*+\s)", text.lstrip(), re.IGNORECASE))


def parse_rows(section, grid_rows):
    """Carry a standalone or merged-cell state through continuation pages."""
    records = []
    state = None
    state_page = None
    for grid_row in grid_rows:
        cells = grid_row.cells
        first = cells[0] or ""
        if is_table_note(first) and not any(cells[1:]):
            continue
        if re.fullmatch(r"S(?:l)?\.\s*No\.?", first, re.IGNORECASE):
            continue
        serial = re.fullmatch(r"(\d+)\.?", first)
        if section.annexure == 3:
            if len(cells) != 4 or not serial:
                raise ValueError(f"Unexpected state-column row on PDF p. {grid_row.page}: {cells!r}")
            _, new_state, name, level = cells
            status = None
            if new_state:
                state, state_page = new_state, grid_row.page
        else:
            # None denotes an absent grid cell. An empty string denotes a printed
            # cell with no contents, such as a missing level.
            columns = [cell for cell in cells if cell is not None]
            if not serial and first and not any(columns[1:]):
                state, state_page = first, grid_row.page
                continue
            width = 4 if section.key == "completed" else 3
            if not serial or len(columns) != width:
                raise ValueError(f"Unexpected status-table row on PDF p. {grid_row.page}: {cells!r}")
            _, name, level, *status_column = columns
            status = status_column[0] if status_column else None
        if not state or int(serial[1]) != len(records) + 1:
            raise ValueError(f"Missing state or discontinuous serial on PDF p. {grid_row.page}: {cells!r}")
        records.append(ProgrammeRow(
            section, grid_row.page, int(serial[1]), state, state_page,
            name or None, level or None, status or None,
            "\n".join(cell for cell in cells if cell),
        ))
    if section.expected_rows is not None and len(records) != section.expected_rows:
        raise ValueError(f"{section.key}: found {len(records)} rows, expected {section.expected_rows}")
    return records


SECTION_HEADINGS = (
    (2, "completed", r"CONSTRUCTION COMPLETED\s*\(Total:\s*(\d+)\)"),
    (2, "under_construction", r"TRAUMA CARE FACILITIES UNDER CONSTRUCTION\s*\(Total:\s*(\d+)\)"),
    (2, "construction_not_started", r"TRAUMA CARE FACILITIES CONSTRUCTION NOT YET STARTED\s*\(Total:\s*(\d+)\)"),
    (3, "supported", r"(List of Trauma Care Facilities supported during 12th FYP)"),
)


def read_pdf(path: Path):
    sections = {}
    grids = {}
    pages = []
    active = None
    with pdfplumber.open(path) as pdf:
        metadata = {key: str(pdf.metadata[key]) for key in ("CreationDate", "ModDate")
                    if key in pdf.metadata}
        for page in pdf.pages:
            number = page.page_number
            pages.append(page.extract_text())
            if not pages[-1].strip():
                raise ValueError(f"PDF p. {number} has no extractable text")
            headings = []
            for line in page.extract_text_lines():
                for annexure, key, pattern in SECTION_HEADINGS:
                    match = re.fullmatch(pattern, flatten(line["text"]), re.IGNORECASE)
                    if match:
                        total = int(match[1]) if annexure == 2 else None
                        if key in sections:
                            raise ValueError(f"Duplicate programme section: {key}")
                        sections[key] = Section(annexure, key, line["text"], number, total)
                        grids[key] = []
                        headings.append((line["bottom"], key))
            if active is None and not headings:
                continue

            # The continuation pages omit the first horizontal rule. Recover it
            # from the tops of the drawn vertical rules so the first row survives.
            settings = {}
            if not headings:
                rule_top = min(edge["top"] for edge in page.vertical_edges)
                settings["explicit_horizontal_lines"] = [rule_top]
            tables = sorted(page.find_tables(settings), key=lambda table: table.bbox[1])
            if not tables:
                raise ValueError(f"Missing programme table on PDF p. {number}")
            previous = None
            page_sections = set()
            for table in tables:
                left, top, right, bottom = table.bbox
                preceding = [key for y, key in headings if y < top]
                key = preceding[-1] if preceding else active
                if key is None:
                    raise ValueError(f"Table precedes programme heading on PDF p. {number}")
                if previous and previous[0] == key:
                    # A full-width state label can split the detected grid
                    # because it has no internal vertical rules.
                    gap_top = previous[1]
                    if top > gap_top:
                        gap = page.crop((left, gap_top, right, top)).extract_text().strip()
                        if gap and not is_table_note(gap):
                            if sections[key].annexure != 2 or "\n" in gap:
                                raise ValueError(f"Unrecognised inter-table text on PDF p. {number}")
                            grids[key].append(GridRow(number, (gap,)))
                grids[key].extend(GridRow(number, tuple(row)) for row in table.extract())
                previous = (key, bottom)
                page_sections.add(key)
            if not {key for _, key in headings} <= page_sections:
                raise ValueError(f"Programme heading without a grid on PDF p. {number}")
            active = previous[0]

    if set(sections) != {key for _, key, _ in SECTION_HEADINGS}:
        raise ValueError("The PDF does not contain all expected programme tables")
    # Annexure 3 has no printed total in its heading. The summary gives the
    # supported denominator, distinct from facilities merely identified.
    supported_totals = re.findall(r"(\d+)\s+TCFs\s+have\s+been\s+supported",
                                  flatten(" ".join(pages[:sections["completed"].page - 1])),
                                  re.IGNORECASE)
    if len(set(supported_totals)) != 1:
        raise ValueError("Cannot establish the supported-facility denominator")
    supported = sections["supported"]
    sections["supported"] = Section(supported.annexure, supported.key, supported.heading,
                                    supported.page, int(supported_totals[0]))
    rows = [row for key, section in sections.items() for row in parse_rows(section, grids[key])]
    return Document(sections, rows, pages, metadata)


def text_hashes(document):
    return [hashlib.sha256(page.encode("utf-8")).hexdigest() for page in document.pages]
