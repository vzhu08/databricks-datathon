#!/usr/bin/env python3
"""Import named PMNDP dialysis rosters into a contract v1.0.0 acquisition batch.

    python -m research.matching.pmndp.roster --manifest <file> --output-dir <path>

One interface serves every roster: a document descriptor plus a table profile
that says which printed column holds what. Three layers stay separate in the
output: raw programme rows, distinct campus candidates, and the claims a row
supports. Nothing is linked to an original facility here, and no claim says
that a patient can get dialysis at a centre today.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from research.matching.common import (MatchingError, canonical, digest, empty, file_digest, load, require,
                                      schema_check, stable_id, write_json)
from research.matching.normalize import address_tokens, place_key, state_key, tokens
from . import IMPORTER_VERSION

KINDS = ("listing", "establishment", "registrations")
CLAIM_KINDS = ("programme_listing", "centre_established", "historical_registrations")
DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %B %Y", "%d %b %Y")
AGGREGATE = r"^\s*(grand\s+|sub\s*-?\s*)?total\b"
DOCUMENT_FIELDS = ("key", "kind", "state", "publisher", "family", "url", "sha256", "retrieved_at",
                   "published_date", "source_date", "license", "independence_status", "rows", "profile")
OUTPUTS = ("batch", "raw_rows", "campus_candidates", "claims", "rejects", "report")
_PIN = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_document(document, position):
    path = f"documents[{position}]"
    require(isinstance(document, dict) and set(DOCUMENT_FIELDS) <= set(document), path,
            "needs: " + ", ".join(DOCUMENT_FIELDS))
    require(document["kind"] in KINDS, f"{path}.kind", "one of: " + ", ".join(KINDS))
    require(isinstance(document["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", document["sha256"]) is not None,
            f"{path}.sha256", "raw SHA-256 of the original document required")
    require(state_key(document["state"]) is not None, f"{path}.state", "state name required")
    for field in ("published_date", "source_date"):
        require(document[field] is None or (isinstance(document[field], str) and _DAY.match(document[field])),
                f"{path}.{field}", "ISO date or null")
    require(document["independence_status"] in ("independent", "shared_origin", "unassessed"),
            f"{path}.independence_status", "contract value required")
    profile = document["profile"]
    require(isinstance(profile, dict) and isinstance(profile.get("columns"), dict), f"{path}.profile",
            "needs a columns object")
    columns = profile["columns"]
    require(isinstance(columns.get("name"), int), f"{path}.profile.columns.name", "column index required")
    for role, index in columns.items():
        if role == "registrations":
            require(isinstance(index, dict) and index and all(isinstance(v, int) for v in index.values()),
                    f"{path}.profile.columns.registrations", "object: period label -> column index")
        else:
            require(role in ("serial", "district", "name", "address", "established") and isinstance(index, int),
                    f"{path}.profile.columns.{role}", "known role with a column index")
    require(document["kind"] != "establishment" or "established" in columns, f"{path}.profile.columns",
            "an establishment roster needs the established column")
    require(document["kind"] != "registrations" or "registrations" in columns, f"{path}.profile.columns",
            "a registrations roster needs the registrations columns")
    return document


def _cell(cells, index):
    value = cells[index] if index is not None and index < len(cells) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _date(text, formats):
    for pattern in formats:
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _count(text):
    compact = text.replace(",", "").strip()
    return int(compact) if re.fullmatch(r"\d+", compact) else None


def ingest(document, table_rows):
    """Raw programme rows, aggregate rows and rejects for one document.

    A row is rejected only when it cannot be read as a named centre. A missing
    date or count keeps the row and drops only that claim, with a flag.
    """
    profile = document["profile"]
    columns = profile["columns"]
    skip = [re.compile(p, re.I) for p in profile.get("skip", [])]
    aggregate = re.compile(profile.get("aggregate", AGGREGATE), re.I)
    formats = tuple(profile.get("date_formats", DATE_FORMATS))
    carry = set(profile.get("carry", []))
    periods = columns.get("registrations", {})
    needed = max([v for v in columns.values() if isinstance(v, int)] + list(periods.values())) + 1
    raw, aggregates, rejects, headers, last = [], [], [], 0, {}
    for item in table_rows:
        require(isinstance(item, dict) and all(isinstance(item.get(k), int) for k in ("page", "table", "row"))
                and isinstance(item.get("cells"), list), f"{document['key']}.rows", "each row needs page, table, row, cells")
        cells = item["cells"]
        printed = [c.strip() for c in cells if isinstance(c, str) and c.strip()]
        where = {"document": document["key"], "page": item["page"], "table": item["table"], "row": item["row"]}
        excerpt = " | ".join(printed)
        if not printed or any(p.search(excerpt) for p in skip):
            headers += 1
            continue
        if any(aggregate.search(text) for text in printed):
            aggregates.append({**where, "excerpt": excerpt})
            continue
        name = _cell(cells, columns["name"])
        serial_text = _cell(cells, columns.get("serial"))
        if len(cells) < needed or name is None:
            rejects.append({**where, "reason": "too_few_cells" if len(cells) < needed else "name_missing", "excerpt": excerpt})
            continue
        if "serial" in columns and (serial_text is None or _count(serial_text.rstrip(".")) is None):
            rejects.append({**where, "reason": "serial_unreadable", "excerpt": excerpt})
            continue
        flags = []
        district = _cell(cells, columns.get("district"))
        if district is None and "district" in carry and last.get("district"):
            district, flags = last["district"], flags + ["district_inherited_from_previous_row"]
        last["district"] = district
        established_text = _cell(cells, columns.get("established"))
        established = _date(established_text, formats) if established_text else None
        if "established" in columns and established is None:
            flags.append("established_unreadable" if established_text else "established_missing")
        registrations = {}
        for period in sorted(periods):
            text = _cell(cells, periods[period])
            if text is None or text in ("-", "--", "NA", "N.A.", "Nil"):
                flags.append(f"count_missing:{period}")
            elif _count(text) is None:
                flags.append(f"count_unreadable:{period}")
            else:
                registrations[period] = _count(text)
        raw.append({
            "raw_row_id": stable_id("pmndp-row", document["sha256"], item["page"], item["table"], item["row"]),
            **where, "serial": _count(serial_text.rstrip(".")) if serial_text else None,
            "district_original": district, "name_original": name,
            "address_original": _cell(cells, columns.get("address")),
            "established_original": established_text, "established_date": established,
            "registrations": registrations, "flags": flags, "excerpt": excerpt,
        })
    serials = [r["serial"] for r in raw if r["serial"] is not None]
    counted = Counter(serials)
    expected = set(range(1, max(serials) + 1)) if serials else set()
    summary = {"rows_read": len(table_rows), "header_or_blank_rows": headers, "aggregate_rows": len(aggregates),
               "programme_rows": len(raw), "rejected_rows": len(rejects),
               "rejected_by_reason": dict(sorted(Counter(r["reason"] for r in rejects).items())),
               "serial_missing": sorted(expected - set(serials)),
               "serial_repeated": sorted(s for s, n in counted.items() if n > 1)}
    require(summary["rows_read"] == headers + len(aggregates) + len(raw) + len(rejects), document["key"],
            "row accounting does not add up")
    return raw, aggregates, rejects, summary


def _keys(row):
    address = row["address_original"]
    return (place_key(row["district_original"]) or "", " ".join(tokens(row["name_original"])),
            " ".join(sorted(address_tokens(address))) if address else None)


def campuses(documents, rows_by_document):
    """Distinct campus candidates across the documents of one upstream family.

    A name that appears once per district in every document is one campus, so
    the two Andhra Pradesh annexes reconcile. Where one document lists several
    centres with the same name in one district, they are branches: they stay
    apart and merge across documents only on an identical address.
    """
    branched = set()
    for document in documents:
        seen = defaultdict(set)
        for row in rows_by_document[document["key"]]:
            district, name, address = _keys(row)
            seen[(document["family"], state_key(document["state"]), district, name)].add(address)
        branched.update(key for key, addresses in seen.items() if len(addresses) > 1)
    grouped = defaultdict(list)
    for document in documents:
        for row in rows_by_document[document["key"]]:
            district, name, address = _keys(row)
            scope = (document["family"], state_key(document["state"]), district, name)
            grouped[scope + ((address,) if scope in branched else (None,))].append((document, row))
    result = []
    for key in sorted(grouped, key=lambda k: canonical(list(k))):
        members = grouped[key]
        family, state, district, name, branch = key
        keys = sorted({d["key"] for d, _ in members})
        flags = []
        if (family, state, district, name) in branched:
            flags.append("same_name_branch")
            if branch is None:
                flags.append("same_name_branch_unreconciled")
        if any(len([1 for d, _ in members if d["key"] == k]) > 1 for k in keys):
            flags.append("repeated_row_in_document")
        first = min(members, key=lambda m: (m[0]["key"], m[1]["page"], m[1]["table"], m[1]["row"]))[1]
        addresses = sorted({r["address_original"] for _, r in members if r["address_original"]})
        result.append({
            "campus_id": stable_id("pmndp-campus", family, state, district, name, branch),
            "family": family, "state": members[0][0]["state"], "district_original": first["district_original"],
            "name_original": first["name_original"],
            "names_seen": sorted({r["name_original"] for _, r in members}),
            "address_original": addresses[0] if addresses else None,
            "documents": keys, "shared_origin_overlap": len(keys) > 1,
            "raw_row_ids": sorted(r["raw_row_id"] for _, r in members), "flags": flags,
        })
    return result


def _claims(document, row, campus_id):
    """What one programme row supports. Listing, establishment date and past
    registrations are separate claims and none of them is about today."""
    programme = document.get("programme", "PMNDP")
    as_of = f" dated {document['source_date']}" if document["source_date"] else ""
    tail = " This does not show that patients can get dialysis there today."
    base = {"campus_id": campus_id, "document": document["key"], "raw_row_id": row["raw_row_id"],
            "present_day_access": "unconfirmed"}
    out = [{**base, "kind": "programme_listing", "value": None, "effective_date": document["source_date"],
            "assertion": f"Named as a {programme} dialysis centre in a roster from {document['publisher']}{as_of}.{tail}"}]
    if row["established_date"]:
        out.append({**base, "kind": "centre_established", "value": row["established_date"],
                    "effective_date": row["established_date"],
                    "assertion": f"The roster gives {row['established_date']} as the date this {programme} dialysis "
                                 f"centre was established.{tail}"})
    for period, count in sorted(row["registrations"].items()):
        out.append({**base, "kind": "historical_registrations", "value": {"period": period, "patients": count},
                    "effective_date": document["source_date"],
                    "assertion": f"The roster records {count} patients registered at this {programme} dialysis centre "
                                 f"for {period}. It is a historical count.{tail}"})
    return out


def build(manifest, rows_for):
    """Pure function behind the CLI. `rows_for(document)` returns the extracted
    rows object for that document: {"source_sha256", "rows"}."""
    require(isinstance(manifest, dict) and isinstance(manifest.get("documents"), list) and manifest["documents"],
            "manifest", "needs a documents array")
    documents = [check_document(d, i) for i, d in enumerate(manifest["documents"])]
    require(len({d["key"] for d in documents}) == len(documents), "documents", "a document key is listed twice")
    require(len({d["sha256"] for d in documents}) == len(documents), "documents", "one document is listed twice")
    documents.sort(key=lambda d: d["key"])
    rows_by_document, aggregates, rejects, per_document, snapshot_of = {}, [], [], {}, {}
    batch = empty()
    for document in documents:
        extracted = rows_for(document)
        require(isinstance(extracted, dict) and extracted.get("source_sha256") == document["sha256"],
                f"{document['key']}.rows", "the rows file was not extracted from the document with this SHA-256")
        raw, totals, bad, summary = ingest(document, extracted["rows"])
        rows_by_document[document["key"]] = raw
        aggregates += totals
        rejects += bad
        per_document[document["key"]] = summary
        snapshot_of[document["key"]] = stable_id("pmndp-snapshot", document["url"], document["sha256"])
        batch["source_snapshots"].append({
            "snapshot_id": snapshot_of[document["key"]], "source_key": document["key"],
            "publisher": document["publisher"], "source_family": document["family"], "url": document["url"],
            "retrieved_at": document["retrieved_at"], "published_date": document["published_date"],
            "license": document["license"], "attribution": document["publisher"], "sha256": document["sha256"],
            "artifact_uri": "urn:sha256:" + document["sha256"], "parser_version": IMPORTER_VERSION,
            "independence_status": document["independence_status"]})
    candidates = campuses(documents, rows_by_document)
    campus_of = {raw_id: c for c in candidates for raw_id in c["raw_row_ids"]}
    by_key = {d["key"]: d for d in documents}
    claims, externals, evidence = [], {}, {}
    for document in documents:
        for row in rows_by_document[document["key"]]:
            campus = campus_of[row["raw_row_id"]]
            sid = snapshot_of[document["key"]]
            eid = stable_id("pmndp-external", campus["campus_id"], sid)
            pins = set(_PIN.findall(row["address_original"] or ""))
            locator = f"page {row['page']}, table {row['table']}, row {row['row']}" + (
                f" (serial {row['serial']})" if row["serial"] is not None else "")
            externals.setdefault(eid, {
                "external_facility_id": eid, "snapshot_id": sid, "source_record_id": None,
                "record_locator": locator, "name_original": row["name_original"],
                "name_normalized": " ".join(tokens(row["name_original"])) or None,
                "address_original": row["address_original"], "facility_type": "dialysis_centre",
                "city": None, "state": document["state"], "pin": pins.pop() if len(pins) == 1 else None,
                "latitude": None, "longitude": None, "coordinate_method": None,
                "quality_flags": sorted({"unlinked_source_identity", "coordinates_missing", *campus["flags"],
                                         *(["shared_origin_overlap"] if campus["shared_origin_overlap"] else [])})})
            for claim in _claims(document, row, campus["campus_id"]):
                record = {"external_facility_id": eid, "snapshot_id": sid, "facility_id": None, "match_id": None,
                          "claim_type": "service", "service": "dialysis", "polarity": "inconclusive",
                          "assertion": claim["assertion"], "excerpt": row["excerpt"], "observation": None,
                          "locator": locator, "source_url": document["url"],
                          "effective_date": claim["effective_date"], "valid_until": None,
                          "temporal_status": "historical" if claim["effective_date"] else "undated",
                          "reviewer": None, "reviewed_at": None}
                evidence_id = stable_id("pmndp-evidence", claim["kind"], claim["value"], record)
                evidence[evidence_id] = {"evidence_id": evidence_id, **record}
                claims.append({**claim, "evidence_id": evidence_id, "external_facility_id": eid})
    reviews = {}

    def queue(reason, severity, action, *parts, external=None):
        review_id = stable_id("pmndp-review", reason, *parts)
        reviews[review_id] = {"review_id": review_id, "facility_id": None, "external_facility_id": external,
                              "evidence_id": None, "match_id": None, "reason_code": reason, "severity": severity,
                              "status": "open", "next_action": action, "resolution": None}

    for reject in rejects:
        queue("pmndp_row_unreadable", "medium",
              f"Read {reject['document']} page {reject['page']}, table {reject['table']}, row {reject['row']} in the "
              f"original document ({reject['reason']}); the row was not imported.",
              by_key[reject["document"]]["sha256"], reject["page"], reject["table"], reject["row"])
    for key, summary in per_document.items():
        if summary["serial_missing"] or summary["serial_repeated"]:
            queue("pmndp_serial_numbers_do_not_reconcile", "medium",
                  f"Serial numbers in {key} are not consecutive (missing {summary['serial_missing']}, repeated "
                  f"{summary['serial_repeated']}). Compare the extracted rows with the original pages.",
                  by_key[key]["sha256"])
    for campus in candidates:
        if "same_name_branch_unreconciled" in campus["flags"]:
            queue("pmndp_same_name_branch_unreconciled", "medium",
                  "Another document lists several centres with this name in this district and this row has no "
                  "address. Decide which branch it is before using it.", campus["campus_id"])
    batch["external_facilities"] = sorted(externals.values(), key=lambda r: r["external_facility_id"])
    batch["facility_evidence"] = sorted(evidence.values(), key=lambda r: r["evidence_id"])
    batch["review_queue"] = sorted(reviews.values(), key=lambda r: r["review_id"])
    batch["source_snapshots"].sort(key=lambda r: r["snapshot_id"])
    schema_check(batch, "output")
    raw_rows = [row for key in sorted(rows_by_document) for row in rows_by_document[key]]
    claims.sort(key=lambda c: c["evidence_id"])
    report = {
        "importer_version": IMPORTER_VERSION, "contract_version": batch["contract_version"],
        "interpretation": "Programme listings, establishment dates and past registration counts as printed. "
                          "Every claim is unlinked, unreviewed and inconclusive for present-day patient access. "
                          "Totals printed in a document are context and are not facility rows.",
        "documents": per_document,
        "programme_rows": len(raw_rows), "rejected_rows": len(rejects), "aggregate_rows": len(aggregates),
        "campus_candidates": {"denominator": len(candidates), "unit": "distinct campus candidates",
                              "in_more_than_one_document": sum(c["shared_origin_overlap"] for c in candidates),
                              "by_family": dict(sorted(Counter(c["family"] for c in candidates).items())),
                              "flag_counts": dict(sorted(Counter(f for c in candidates for f in c["flags"]).items()))},
        "claims": {"denominator": len(claims), "unit": "claims supported by a programme row",
                   "by_kind": dict(sorted(Counter(c["kind"] for c in claims).items())),
                   "zero_registration_claims": sum(c["kind"] == "historical_registrations"
                                                   and c["value"]["patients"] == 0 for c in claims)},
        "row_flag_counts": dict(sorted(Counter(f.split(":")[0] for r in raw_rows for f in r["flags"]).items())),
        "table_counts": {table: len(batch[table]) for table in batch if table != "contract_version"},
    }
    return {"batch": batch, "raw_rows": raw_rows, "campus_candidates": candidates, "claims": claims,
            "rejects": rejects + [{**a, "reason": "aggregate_row_kept_as_context"} for a in aggregates],
            "report": report}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.matching.pmndp.roster", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", required=True, help="Document descriptors and profiles; rows paths are relative to it")
    parser.add_argument("--output-dir", required=True, help="Keep real runs under data/local/")
    args = parser.parse_args(argv)
    try:
        manifest_path = Path(args.manifest).resolve()
        manifest = load(manifest_path)
        out = Path(args.output_dir)
        root = manifest_path.parent

        def rows_for(document):
            path = (root / document["rows"]).resolve()
            require(path.is_relative_to(root), f"{document['key']}.rows", "must stay inside the manifest directory")
            return load(path)

        require(out.resolve() != root, "output-dir", "must not be the directory that holds the manifest")
        result = build(manifest, rows_for)
        hashes = {name: write_json(out / f"{name}.json", result[name]) for name in OUTPUTS}
        inputs = {"manifest": file_digest(manifest_path),
                  "rows": {d["key"]: file_digest(root / d["rows"]) for d in manifest["documents"]}}
        write_json(out / "manifest.json", {"importer_version": IMPORTER_VERSION, "inputs_sha256": inputs,
                                           "outputs_sha256": hashes})
        print(canonical({"status": "ok", "table_counts": result["report"]["table_counts"],
                         "programme_rows": result["report"]["programme_rows"],
                         "rejected_rows": result["report"]["rejected_rows"],
                         "campus_candidates": result["report"]["campus_candidates"]["denominator"],
                         "claims": result["report"]["claims"]["by_kind"], "batch_sha256": hashes["batch"]}))
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
