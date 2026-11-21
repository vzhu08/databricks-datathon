"""Compile the DMER Maharashtra MRI equipment inventory for unlinked national comparison."""

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from research.matching.common import canonical, counts, empty, stable_id


URL = "https://dmer.maharashtra.gov.in/english/list-of-hospitals-with-ct-mri-facilities/"
POLICY = "https://dmer.maharashtra.gov.in/english/website-content-management-policy/"
PUBLISHER = "Directorate of Medical Education and Research, Government of Maharashtra"
SOURCE_KEY = "maharashtra_dmer_mri_inventory"
FAMILY = "maharashtra_dmer"
NAME_HEADERS = {"hospital name", "name of hospital", "name of institution"}
MRI_HEADERS = {"mri", "mri scan", "mri scan facility", "mri count"}
GROUP = re.compile(r"\b(group|network|consortium|associated hospitals|hospitals)\b", re.I)


def value(cell):
    return " ".join(cell.stripped_strings)


def headers(cells):
    return [" ".join(value(cell).casefold().split()) for cell in cells]


def find_inventory(soup):
    matches = []
    for index, table in enumerate(soup.find_all("table"), start=1):
        rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
        for header_index, tr in enumerate(rows):
            cells = tr.find_all(["td", "th"], recursive=False)
            labels = headers(cells)
            names = [i for i, label in enumerate(labels) if label in NAME_HEADERS]
            mri = [i for i, label in enumerate(labels) if label in MRI_HEADERS]
            if names and mri:
                if len(names) != 1 or len(mri) != 1:
                    raise ValueError("Duplicate hospital or MRI columns")
                matches.append((index, table, rows, header_index, labels, names[0], mri[0], value(cells[mri[0]])))
                break
    if len(matches) != 1:
        raise ValueError(f"Expected one institution/MRI inventory table, found {len(matches)}")
    return matches[0]


def inventory_date(table):
    # Keep page publication/retrieval dates separate from an inventory's own date.
    caption = table.find("caption", recursive=False)
    prior = table.find_previous_sibling()
    texts = [value(tag) for tag in (caption, prior) if tag and tag.name in ("caption", "p")]
    dates = {date.fromisoformat(s).isoformat() for text in texts for s in re.findall(
        r"\b(?:as of|as on|inventory date)\s*[:–-]?\s*(\d{4}-\d{2}-\d{2})\b", text, re.I)}
    if len(dates) > 1:
        raise ValueError("Conflicting inventory dates")
    return next(iter(dates), None)


def compile_inventory(raw, receipt):
    sha = hashlib.sha256(raw).hexdigest()
    if receipt["sha256"] != sha or receipt["url"] != URL:
        raise ValueError("Source URL or raw hash differs from capture receipt")
    stamp = receipt["retrieved_at"]
    if not stamp.endswith("Z") or datetime.fromisoformat(stamp).utcoffset() != timedelta(0):
        raise ValueError("Capture receipt requires a UTC retrieval timestamp ending in Z")
    soup = BeautifulSoup(raw, "html.parser")
    table_no, table, rows, hi, labels, name_col, mri_col, mri_heading = find_inventory(soup)
    as_of = inventory_date(table)
    publication = soup.select_one('meta[property="article:published_time"][content]')
    published = datetime.fromisoformat(publication["content"]).date().isoformat() if publication else None
    sid = stable_id("dmer_mri.snapshot", URL, sha)
    batch = empty()
    batch["source_snapshots"].append(dict(
        snapshot_id=sid, source_key=SOURCE_KEY, publisher=PUBLISHER, source_family=FAMILY, url=URL,
        retrieved_at=stamp, published_date=published, sha256=sha, artifact_uri=f"urn:sha256:{sha}",
        parser_version="dmer-mri-1", independence_status="unassessed", attribution=PUBLISHER,
        license=f"DMER website copyright policy: attributed fair use; commercial reproduction requires permission; "
                f"third-party material has separate terms. {POLICY}"))
    ledger = []
    repeated_headers = 0
    for row_no, tr in enumerate(rows[hi + 1:], start=hi + 2):
        cells = tr.find_all(["td", "th"], recursive=False)
        if headers(cells) == labels:
            repeated_headers += 1
            continue
        loc = f"HTML table {table_no}, physical tr {row_no} (1-based)"
        flags = []
        if (len(cells) != len(labels) or any(cell.get("rowspan", "1") != "1" or
                                            cell.get("colspan", "1") != "1" for cell in cells)):
            flags.append("ambiguous_cell_layout")
        # In a short/shifted row no positional cell can safely be treated as MRI.
        aligned = not flags
        name = value(cells[name_col]) if aligned else None
        raw_mri = value(cells[mri_col]) if aligned else None
        if not name and aligned:
            flags.append("missing_institution_name")
        if name and GROUP.search(name):
            flags.append("group_institution")
        count = None
        if not aligned:
            state = "unreadable_layout"
        elif not raw_mri:
            state = "missing"
            flags.append("missing_mri_value")
        elif not re.fullmatch("[0-9]+", raw_mri):
            state = "malformed"
            flags.append("malformed_mri_value")
        else:
            count = int(raw_mri)
            state = "positive" if count else "zero"
        xid = eid = None
        if name:
            xid = stable_id("dmer_mri.external", sid, loc, name)
            batch["external_facilities"].append(dict(
                external_facility_id=xid, snapshot_id=sid, source_record_id=None,
                record_locator=f"{loc}, cell {name_col+1}", name_original=name,
                name_normalized=" ".join(name.casefold().split()), address_original=None,
                facility_type="institution_group" if "group_institution" in flags else "health_institution",
                city=None, state="Maharashtra", pin=None, latitude=None, longitude=None,
                coordinate_method=None, quality_flags=["unlinked_source_identity", *flags]))
        if xid and count is not None:
            evidence_loc = f"{loc}, cell {mri_col+1}, column {mri_heading}"
            eid = stable_id("dmer_mri.evidence", xid, evidence_loc, raw_mri, as_of)
            batch["facility_evidence"].append(dict(
                evidence_id=eid, external_facility_id=xid, snapshot_id=sid, facility_id=None, match_id=None,
                claim_type="service", service="mri", polarity="inconclusive",
                assertion=f"DMER reports an MRI inventory count of {count} for this listed institution. "
                          "The operating status and appointments for a specific campus are unknown.",
                excerpt=raw_mri, observation=None, locator=evidence_loc, source_url=URL,
                effective_date=as_of, valid_until=None, temporal_status="dated" if as_of else "undated",
                reviewer=None, reviewed_at=None))
        for flag in flags:
            action = ("Resolve the group’s campus identity before assigning equipment to an original."
                      if flag == "group_institution" else "Inspect the original table row and its column alignment.")
            batch["review_queue"].append(dict(
                review_id=stable_id("dmer_mri.review", sid, loc, flag), facility_id=None, match_id=None,
                external_facility_id=xid, evidence_id=eid, reason_code=flag, severity="medium",
                status="open", next_action=f"{action} Locator: {loc}.", resolution=None))
        ledger.append(dict(locator=loc, name=name, mri_field=mri_heading, raw_value=raw_mri,
                           count=count, value_status=state, flags=flags, external_facility_id=xid, evidence_id=eid))
    if not ledger:
        raise ValueError("Inventory contains no data rows")
    reasons = Counter(flag for row in ledger for flag in row["flags"])
    rejected = Counter(flag for row in ledger if row["evidence_id"] is None
                       for flag in row["flags"] if flag != "group_institution")
    states = Counter(row["value_status"] for row in ledger)
    report = dict(scope="Maharashtra DMER inventory", input_rows=len(ledger), repeated_headers=repeated_headers,
                  published_date=published, inventory_as_of=as_of, mri_header=mri_heading,
                  count_by_value_status=dict(states), reported_units=sum(row["count"] or 0 for row in ledger),
                  rows_without_evidence=sum(row["evidence_id"] is None for row in ledger),
                  rejected_row_reasons=dict(rejected), review_reasons=dict(reasons), output_counts=counts(batch),
                  original_rows_compared=0, confirmed_original_links=0,
                  national_overlap="Unknown until compared with the complete original base and reviewed campus links.")
    return {"batch.json": batch, "rows.json": ledger, "report.json": report}


def run(html, receipt, output):
    artifacts = compile_inventory(html.read_bytes(), json.loads(receipt.read_text(encoding="utf-8-sig")))
    files = {name: (canonical(data) + "\n").encode("utf-8") for name, data in artifacts.items()}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files["sha256.json"] = (canonical(hashes) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staged = Path(temporary) / "release"
        staged.mkdir()
        for name, data in files.items():
            (staged / name).write_bytes(data)
        try:
            staged.rename(output)
        except OSError:
            if not output.is_dir():
                raise
            if any(not (output / n).is_file() or (output / n).read_bytes() != b for n, b in files.items()):
                raise ValueError("Existing output differs from the frozen release")
    return hashes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, type=Path, help="original DMER source bytes")
    parser.add_argument("--receipt", required=True, type=Path, help="JSON with url, retrieved_at (UTC), and sha256")
    parser.add_argument("--out", required=True, type=Path, help="private release directory")
    args = parser.parse_args()
    print(canonical(run(args.html, args.receipt, args.out)))
