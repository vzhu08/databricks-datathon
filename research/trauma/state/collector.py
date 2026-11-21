"""Read the Rajasthan Road Safety Cell listing from a saved HTML response."""

import argparse
from collections import Counter
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import unicodedata

from lxml import html


SOURCE_KEY = "rajasthan_trauma"
PUBLISHER = "Rajasthan Road Safety Cell"
SOURCE_FAMILY = "rajasthan_road_safety"
PARSER_VERSION = "1.0.0"
EVIDENCE_REVISION = 2
ATTRIBUTION = (
    "State Road Safety Cell, Department of Transport and Road Safety, Rajasthan; "
    "portal by Rajasthan Knowledge Corporation Limited (RKCL). The portal footer "
    "states all rights reserved; no reuse license was identified."
)

# Rajasthan RGAVP district directory, with alternate forms recorded by state agencies.
# These are spelling checks, not a crosswalk to current administrative boundaries.
DISTRICT_NAMES = set("""
ajmer|alwar|balotra|balotara|banswara|baran|barmer|beawar|bharatpur|bhilwara|
bikaner|bundi|chittorgarh|chittogarh|churu|dausa|deeg|dholpur|didwana kuchaman|
dungarpur|ganganagar|sri ganganagar|shri ganganagar|hanumangarh|jaipur|jaisalmer|
jalore|jhalawar|jhunjhunu|jodhpur|karauli|khairthal|khairthal tijara|kota|
kotputli behror|nagaur|pali|phalodi|pratapgarh|rajsamand|salumber|sawai madhopur|
sikar|sirohi|tonk|udaipur
""".replace("\n", "").split("|"))

FIELDS = (
    "serial_original", "district_original", "name_original",
    "ambulance_108_status_original", "ambulance_108_vehicle_original",
    "ambulance_als_status_original", "ambulance_als_vehicle_original",
)
REVIEW_ACTIONS = {
    "row_layout_mismatch": "Inspect original cells and recover their column labels.",
    "missing_name": "Inspect the row and resolve the facility wording before using the listing.",
    "missing_district": "Resolve the district through separate campus evidence.",
    "unexpected_district": "Verify source spelling or historical district context without replacing the original.",
    "duplicate_name": "Compare districts and campuses before treating these listings as one facility.",
    "duplicate_serial": "Compare all occurrences of the display serial and preserve variants.",
    "invalid_serial": "Check the source display serial at the original row locator.",
    "missing_serial": "Check the source display serial at the original row locator.",
    "explicit_designation_requires_review": "Interpret the exact designation before treating the row as affirmative trauma evidence.",
}
DATE_LABELS = {
    "published_date": r"(?:date\s+published|publication\s+date|published(?:\s+(?:on|date))?)",
    "effective_date": r"(?:data\s+as\s+of|as\s+(?:of|on)|effective\s+(?:date|from)|valid\s+from)",
    "valid_until": r"(?:valid\s+(?:up\s+to|until|through)|expir(?:y\s+date|es(?:\s+on)?))",
    "last_updated": r"(?:last\s+updated|updated\s+on)",
}


def render_text(element):
    """Decode HTML entities and fold layout whitespace while retaining visible wording."""
    def fragments(node):
        yield node.text or ""
        for child in node:
            if child.tag == "br":
                yield "\n"
            elif isinstance(child.tag, str) and child.tag not in {"script", "style"}:
                yield from fragments(child)
            yield child.tail or ""

    lines = (" ".join(line.split()) for line in "".join(fragments(element)).split("\n"))
    return "\n".join(line for line in lines if line)


def word_key(value):
    characters = (
        char if char.isalnum() or unicodedata.category(char).startswith("M") else " "
        for char in unicodedata.normalize("NFKC", value).casefold()
    )
    return " ".join("".join(characters).split())


def column_map(headers):
    keys = [word_key(value) for value in headers]
    roles = {}
    ambiguous = False
    for index, key in enumerate(keys):
        role = None
        if key in {"s no", "sno", "sr no", "serial", "serial no", "serial number"}:
            role = "serial_original"
        elif key in {"district", "district name"}:
            role = "district_original"
        elif key in {"facility", "facility name", "hospital", "hospital name", "location"} or re.fullmatch(
            r"(?:trauma|truma) cent(?:re|er)(?: (?:location|name))?", key
        ):
            role = "name_original"
        elif "designation" in key or key in {"trauma level", "trauma centre level", "trauma center level"}:
            role = "designation_original"
        elif "vehicle" in key or "ambulance" in key:
            words = key.split()
            kind = next((kind for kind in ("108", "als") if kind in words), None)
            if "vehicle" in words:
                if kind is None:
                    kind = next((k for k in ("108", "als")
                                 if roles.get(f"ambulance_{k}_status_original") == index - 1), None)
                if kind:
                    role = f"ambulance_{kind}_vehicle_original"
            elif kind:
                role = f"ambulance_{kind}_status_original"
        if role:
            ambiguous = ambiguous or role in roles
            roles[role] = index
    return roles, ambiguous


def find_listing(document):
    candidates = []
    for number, table in enumerate(document.xpath("//table"), 1):
        rows = table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")
        for index, row in enumerate(rows):
            headers = [render_text(cell) for cell in row.xpath("./th | ./td")]
            roles, ambiguous = column_map(headers)
            if not set(FIELDS).issubset(roles):
                continue
            if ambiguous or row.xpath("./*[@rowspan or @colspan]"):
                raise ValueError(f"Ambiguous column headers in HTML table {number}, row {index + 1}.")
            candidates.append((number, table, rows, index, headers, roles))
            break
    if len(candidates) != 1:
        raise ValueError(f"Expected one trauma directory table by headers, found {len(candidates)}.")
    return candidates[0]


def source_dates(document, table, heading):
    observations = {label: [] for label in (*DATE_LABELS, "copyright")}
    nodes = ([heading] if heading is not None else []) + table.xpath("./caption")
    # Dates in the listing heading/caption or adjacent annotation, plus page metadata.
    for parent in (table, table.getparent()):
        for sibling in (parent.getprevious(), parent.getnext()):
            if sibling is not None and sibling.tag in {"p", "time", "small"}:
                nodes.append(sibling)
    annotations = [(render_text(node), f"HTML line {node.sourceline}") for node in nodes]
    meta_roles = {
        "article published time": "published_date", "datepublished": "published_date",
        "date published": "published_date", "publication date": "published_date",
        "article modified time": "last_updated", "datemodified": "last_updated",
        "date modified": "last_updated", "last updated": "last_updated",
        "effective date": "effective_date", "valid from": "effective_date", "valid until": "valid_until",
    }
    for meta in document.xpath("//meta[@content]"):
        key = word_key(meta.get("name") or meta.get("property") or meta.get("itemprop") or "")
        if key in meta_roles:
            label = meta_roles[key]
            observations[label].append({"original": meta.get("content"), "locator": f"HTML meta line {meta.sourceline}"})
    date_token = r"\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{4}"
    for label, pattern in DATE_LABELS.items():
        for annotation, locator in annotations:
            for match in re.finditer(rf"\b{pattern}\s*[:–-]?\s*({date_token})\b", annotation, re.I):
                observations[label].append({"original": match.group(1), "locator": locator})
    for node in document.xpath("//*[@id='copyright' or contains(concat(' ', normalize-space(@class), ' '), ' copyright ')]"):
        for year in re.findall(r"\b(?:19|20)\d{2}\b", render_text(node)):
            observations["copyright"].append({"original": year, "locator": f"HTML line {node.sourceline}"})

    selected = {}
    for label, entries in observations.items():
        if label == "copyright":
            continue
        values = set()
        for entry in entries:
            entry["iso_date"] = explicit_date(entry["original"])
            values.add(entry["iso_date"])
        selected[label] = next(iter(values)) if len(values) == 1 else None
    return selected, observations


def explicit_date(value):
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\S+)?", value):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    # Numeric day/month forms can be ambiguous. Keep those original tokens only.
    for pattern in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value.replace(",", ""), pattern).date().isoformat()
        except ValueError:
            continue
    return None


def parse_listing(raw):
    document = html.document_fromstring(raw, parser=html.HTMLParser(encoding="utf-8"))
    table_number, table, table_rows, header_index, headers, roles = find_listing(document)
    caption = table.find("caption")
    heading = caption if caption is not None else next(iter(table.xpath(
        "preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6][1]"
    )), None)
    heading_text = render_text(heading) if heading is not None else ""
    name_header = headers[roles["name_original"]]
    designation_key = re.compile(r"\b(?:trauma|truma) cent(?:re|er)s?\b")
    if designation_key.search(word_key(heading_text)):
        designation_context = {"text": heading_text, "locator": f"HTML line {heading.sourceline}"}
    elif designation_key.search(word_key(name_header)):
        designation_context = {"text": name_header, "locator": f"HTML table {table_number}, tr[{header_index + 1}], "
                               f"cell[{roles['name_original'] + 1}]"}
    else:
        raise ValueError("Matched columns but found no trauma-centre listing title or location header.")

    rows = []
    for index, row in enumerate(table_rows[header_index + 1:], header_index + 2):
        if row.getparent().tag == "tfoot":
            continue
        cells = row.xpath("./th | ./td")
        originals = [render_text(cell) or None for cell in cells]
        if [word_key(value or "") for value in originals] == [word_key(value) for value in headers]:
            continue
        locator = f"HTML table {table_number}, tr[{index}] (line {row.sourceline})"
        layout_ok = len(cells) == len(headers) and not row.xpath("./*[@rowspan or @colspan]")
        fields = {name: originals[column] if layout_ok else None for name, column in roles.items()}
        fields.setdefault("designation_original", None)
        flags = []
        if not layout_ok:
            flags.append("row_layout_mismatch")
        else:
            for field in ("name", "district", "serial"):
                if not fields[f"{field}_original"]:
                    flags.append(f"missing_{field}")
            if fields["serial_original"] and not re.fullmatch(r"[0-9]+", fields["serial_original"]):
                flags.append("invalid_serial")
            if fields["district_original"] and word_key(fields["district_original"]) not in DISTRICT_NAMES:
                flags.append("unexpected_district")
        rows.append({**fields, "table_row": index, "record_locator": locator,
                     "cells_original": originals, "quality_flags": flags})
    if not rows:
        raise ValueError("The trauma directory header has no body rows.")
    dates, observations = source_dates(document, table, heading)
    return {
        "rows": rows, "column_headers": headers, "column_indices": roles,
        "table_number": table_number, "designation_context": designation_context,
        "dates": dates, "date_observations": observations,
    }


def build_artifacts(raw, metadata, expected_count=None):
    listing = parse_listing(raw)
    rows = listing["rows"]
    dates = listing["dates"]
    url = metadata["source_url"]
    retrieved_at = metadata["retrieved_at"]
    effective = dates["effective_date"]
    cutoff = dates["valid_until"]
    # D's contract validator requires an effective date for dated evidence and
    # an expiry for expired evidence. Other date observations stay in coverage.
    valid_until = None
    temporal_status = "undated"
    if effective:
        temporal_status = "dated"
        if cutoff and cutoff >= effective:
            valid_until = cutoff
    elif cutoff and cutoff < retrieved_at[:10]:
        valid_until = cutoff
    if valid_until and valid_until < retrieved_at[:10]:
        temporal_status = "expired"
    sha256 = hashlib.sha256(raw).hexdigest()
    snapshot_id = f"{SOURCE_KEY}:{sha256}"
    snapshot = {
        "snapshot_id": snapshot_id, "source_key": SOURCE_KEY, "publisher": PUBLISHER,
        "source_family": SOURCE_FAMILY, "url": url, "retrieved_at": retrieved_at,
        "published_date": dates["published_date"], "license": None, "attribution": ATTRIBUTION,
        "sha256": sha256, "artifact_uri": metadata["artifact_uri"], "parser_version": PARSER_VERSION,
        "independence_status": "unassessed",
    }
    names = Counter(word_key(row["name_original"]) for row in rows if row["name_original"])
    serials = Counter(row["serial_original"] for row in rows if row["serial_original"])
    facilities, evidence, reviews = [], [], []
    for row in rows:
        original = row["name_original"]
        name = word_key(original or "") or None
        flags = row["quality_flags"]
        if name and names[name] > 1:
            flags.append("duplicate_name")
        if serials[row["serial_original"]] > 1:
            flags.append("duplicate_serial")
        if row["designation_original"]:
            flags.append("explicit_designation_requires_review")
        for kind in ("108", "als"):
            status = row[f"ambulance_{kind}_status_original"]
            vehicle = row[f"ambulance_{kind}_vehicle_original"]
            vehicle_values = [value.strip() for value in re.split(r"[,;/\n]+", vehicle or "") if value.strip()]
            row[f"ambulance_{kind}_vehicle_values"] = vehicle_values
            if len(vehicle_values) > 1:
                flags.append(f"ambulance_{kind}_multiple_vehicle_values")
            if "row_layout_mismatch" not in flags:
                if not status:
                    flags.append(f"ambulance_{kind}_missing_status")
                elif status.casefold() not in {"yes", "no"}:
                    flags.append(f"ambulance_{kind}_unexpected_status")
                if (status or "").casefold() == "no" and vehicle_values:
                    flags.append(f"ambulance_{kind}_vehicle_with_no")
                if (status or "").casefold() == "yes" and not vehicle_values:
                    flags.append(f"ambulance_{kind}_yes_without_vehicle")
        external_id = f"{snapshot_id}:table-{listing['table_number']}-row-{row['table_row']}"
        row["external_facility_id"] = external_id
        row["snapshot_id"] = snapshot_id
        row["designation_context"] = listing["designation_context"]
        locator = row["record_locator"]
        facilities.append({
            "external_facility_id": external_id, "snapshot_id": snapshot_id,
            "source_record_id": None, "record_locator": locator,
            "name_original": original, "name_normalized": name, "address_original": None,
            "facility_type": "unknown", "city": None, "state": "Rajasthan", "pin": None,
            "latitude": None, "longitude": None, "coordinate_method": None, "quality_flags": flags,
        })
        evidence_id = None
        if original:
            evidence_id = f"{external_id}:trauma-listing-v{EVIDENCE_REVISION}"
            excerpt = original
            excerpt_column = listing["column_indices"]["name_original"]
            assertion = (
                "The Rajasthan Road Safety Cell lists this facility under trauma centres. "
                "Current trauma service capability is unknown."
            )
            if row["designation_original"]:
                excerpt = row["designation_original"]
                excerpt_column = listing["column_indices"]["designation_original"]
                assertion = (
                    "The Rajasthan Road Safety Cell lists this facility under trauma centres with a separate "
                    "designation value. Current trauma service capability is unknown."
                )
            evidence.append({
                "evidence_id": evidence_id, "external_facility_id": external_id, "snapshot_id": snapshot_id,
                "facility_id": None, "match_id": None, "claim_type": "service", "service": "trauma_care",
                "polarity": "inconclusive", "assertion": assertion,
                "excerpt": excerpt, "observation": None,
                "locator": f"{locator}, cell[{excerpt_column + 1}]; "
                           f"listing context: {listing['designation_context']['locator']}",
                "source_url": url, "effective_date": effective, "valid_until": valid_until,
                "temporal_status": temporal_status, "reviewer": None, "reviewed_at": None,
            })
        row["evidence_id"] = evidence_id
        for flag in flags:
            action = REVIEW_ACTIONS.get(flag)
            if action is None and flag.endswith(("_vehicle_with_no", "_yes_without_vehicle", "_unexpected_status", "_missing_status")):
                action = "Inspect the original ambulance columns and retain the unresolved listing status."
            if action:
                reviews.append({
                    "review_id": f"{external_id}:review:{flag}:v{EVIDENCE_REVISION}", "external_facility_id": external_id,
                    "facility_id": None, "match_id": None, "evidence_id": evidence_id,
                    "reason_code": flag, "severity": "high" if flag == "row_layout_mismatch" else "medium",
                    "status": "open", "next_action": action, "resolution": None,
                })

    batch = {
        "contract_version": "1.0.0", "source_snapshots": [snapshot], "external_facilities": facilities,
        "facility_matches": [], "facility_evidence": evidence, "review_queue": reviews,
    }
    coverage = {
        "snapshot_id": snapshot_id, "table_number": listing["table_number"],
        "evidence_revision": EVIDENCE_REVISION,
        "column_headers": listing["column_headers"], "designation_context": listing["designation_context"],
        "dates": dates, "date_observations": listing["date_observations"],
        "observed_rows": len(rows), "expected_rows": expected_count,
        "row_count_delta": len(rows) - expected_count if expected_count is not None else None,
        "unique_serials": len(serials), "duplicate_serial_groups": sum(count > 1 for count in serials.values()),
        "duplicate_name_groups": sum(count > 1 for count in names.values()),
        "serial_gap_ranges": serial_gaps(serials),
        "blank_fields": {
            field: sum(row[field] is None for row in rows if "row_layout_mismatch" not in row["quality_flags"])
            for field in listing["column_indices"]
        },
        "district_rows": dict(Counter(row["district_original"] for row in rows if row["district_original"])),
        "quality_flag_counts": dict(Counter(flag for row in rows for flag in row["quality_flags"])),
        "review_rows": len(reviews), "identity_rows": len(facilities), "evidence_rows": len(evidence),
        "evidence_polarity_counts": dict(Counter(row["polarity"] for row in evidence)),
        "temporal_status_counts": dict(Counter(row["temporal_status"] for row in evidence)),
        "acquisition_method": metadata.get("acquisition_method"),
    }
    return batch, rows, coverage


def serial_gaps(serials):
    numbers = sorted({int(serial) for serial in serials if re.fullmatch(r"[0-9]{1,6}", serial)})
    return [[left + 1, right - 1] for left, right in zip(numbers, numbers[1:]) if right - left > 1]


def write_json(path, payload):
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        try:
            json.dump(payload, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
            temp.close()
            temp_path.replace(path)
        finally:
            if temp_path.exists():
                temp.close()
                temp_path.unlink()


def inventory_for(snapshot_id, output_dir, paths):
    artifacts = []
    for item in paths:
        path = item.resolve()
        relative_name = path.relative_to(output_dir) if path.is_relative_to(output_dir) else path
        contents = path.read_bytes()
        artifacts.append({
            "path": relative_name.as_posix(), "absolute_path": str(path),
            "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest(),
        })
    return {
        "contract_version": "1.0.0", "snapshot_id": snapshot_id,
        "evidence_revision": EVIDENCE_REVISION, "artifacts": artifacts,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--html", required=True, type=Path, help="Saved UTF-8 response body")
    cli.add_argument("--metadata", required=True, type=Path, help="JSON with source_url and UTC retrieved_at")
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--expected-count", type=int, help="Optional baseline for the count-drift report")
    cli.add_argument("--schema", type=Path, default=Path("contracts/enrichment/schema.json"))
    args = cli.parse_args()

    from jsonschema import Draft202012Validator, FormatChecker

    metadata = json.loads(args.metadata.read_text(encoding="utf-8-sig"))
    metadata.setdefault("artifact_uri", args.html.resolve().as_uri())
    batch, rows, coverage = build_artifacts(args.html.read_bytes(), metadata, args.expected_count)
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(batch)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        output_dir / "campuses.json": rows,
        output_dir / "coverage.json": coverage,
        output_dir / "batch.json": batch,
    }
    for path, payload in outputs.items():
        write_json(path, payload)
    inventory = inventory_for(coverage["snapshot_id"], output_dir, [args.html, args.metadata, *outputs])
    write_json(output_dir / "artifact_inventory.json", inventory)
    counts = {key: coverage[key] for key in ("observed_rows", "row_count_delta", "identity_rows", "evidence_rows", "review_rows")}
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
