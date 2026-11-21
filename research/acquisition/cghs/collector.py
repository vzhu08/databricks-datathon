"""Offline CGHS identity collector; no network, transfer, or clinical inference."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from research.acquisition.common import (
    AcquisitionError, canonical, digest, envelope, file_digest,
    public_url, publish_json_directory, review, validate,
)
from . import PARSER_VERSION

KINDS = {"campus", "group_summary", "multi_campus_group"}
EVENTS = {"renewal", "suspension", "delisting", "cashless_withdrawal", "nonrenewal", "name_change"}
SERIES_FIELDS = ("source_family", "issuer", "series_key", "eligible_population", "coverage_scope")


def require(condition, reason):
    if not condition:
        raise AcquisitionError(reason)


def text(value, nullable=False):
    if value is None and nullable:
        return None
    require(isinstance(value, str) and bool(value.strip()), "nonempty_text_required")
    return value


def iso_date(value):
    if value is None:
        return None
    require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), "invalid_date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise AcquisitionError("invalid_date") from exc


def sha(value):
    require(isinstance(value, str) and bool(re.fullmatch("[0-9a-f]{64}", value)), "invalid_sha256")
    return value


def local_file(root, relative):
    """Portable relative paths confined to the manifest directory, including symlinks."""
    require(isinstance(relative, str) and bool(relative) and "\\" not in relative, "invalid_relative_path")
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts and ":" not in relative, "invalid_relative_path")
    resolved = (root / path).resolve()
    require(root.resolve() in resolved.parents and resolved.is_file(), "missing_or_outside_local_file")
    return resolved


def locator(value):
    require(isinstance(value, dict) and set(value) == {"page", "table", "section", "row"}, "invalid_locator")
    require(all(type(value[k]) is int and value[k] > 0 for k in ("page", "table")), "invalid_locator")
    return f"PDF page {value['page']}, table {value['table']}, section {text(value['section'])}, row {text(value['row'])}"


def validity(raw):
    """Recognize unqualified positive intervals; preserve other wording for review."""
    if raw is None:
        return [], ["validity_unknown"]
    text(raw)
    tokens = list(re.finditer(r"(?<!\d)(\d{1,2})([./-])(\d{1,2})\2(\d{4})(?!\d)", raw))
    parsed = []
    for token in tokens:
        try:
            parsed.append(date(int(token[4]), int(token[3]), int(token[1])).isoformat())
        except ValueError:
            return [], ["validity_needs_review"]
    # Do not pair valid tokens across a malformed date or unexplained digits.
    remaining = re.sub(r"(?<!\d)(\d{1,2})([./-])(\d{1,2})\2(\d{4})(?!\d)", "", raw)
    if not parsed or len(parsed) % 2 or re.search(r"\d", remaining):
        return [], ["validity_needs_review"]
    for i in range(0, len(tokens), 2):
        separator = raw[tokens[i].end():tokens[i + 1].start()].strip().casefold()
        if separator not in {"to", "until", "through", "-", "–", "—"}:
            return [], ["validity_needs_review"]
    # Accept a small positive grammar instead of dropping arbitrary surrounding
    # prose. In particular, exclusions and suspensions are not validity episodes.
    label = r"(?:(?:valid(?:ity)?(?:\s+period)?|period(?:\s+of\s+validity)?)(?:\s+from)?|from)"
    prefix = rf"\s*(?:{label}\s*:?\s*)?"
    if not re.fullmatch(prefix, raw[:tokens[0].start()], re.I):
        return [], ["validity_needs_review"]
    for i in range(2, len(tokens), 2):
        gap = raw[tokens[i - 1].end():tokens[i].start()]
        if not re.fullmatch(rf"\s*(?:[;,]\s*|and\s+)?{prefix}", gap, re.I):
            return [], ["validity_needs_review"]
    if not re.fullmatch(r"\s*[.;]?\s*", raw[tokens[-1].end():]):
        return [], ["validity_needs_review"]
    if any(parsed[i] > parsed[i + 1] for i in range(0, len(parsed), 2)):
        return [], ["validity_needs_review"]
    episodes = [{"valid_from": parsed[i], "valid_to": parsed[i + 1]} for i in range(0, len(parsed), 2)]
    distinct = {(e["valid_from"], e["valid_to"]) for e in episodes}
    flags = []
    if len(distinct) > 1:
        flags.append("multiple_validity_episodes")
    if len(episodes) > len(distinct):
        flags.append("repeated_printed_validity_interval")
    return episodes, flags


def source_metadata(source):
    for key in (*SERIES_FIELDS, "source_key", "publisher"):
        text(source.get(key))
    require(source["source_family"] == "cghs_empanelment", "unexpected_source_family")
    require(bool(re.fullmatch(r"[a-zA-Z0-9_.-]+", source["source_key"])), "invalid_source_key")
    public_url(source["url"])
    sha(source["sha256"])
    iso_date(source.get("document_date"))
    stamp = source.get("retrieved_at")
    try:
        require(isinstance(stamp, str) and stamp.endswith("Z"), "utc_retrieval_timestamp_required")
        require(datetime.fromisoformat(stamp.replace("Z", "+00:00")).utcoffset() == timezone.utc.utcoffset(None),
                "utc_retrieval_timestamp_required")
    except ValueError as exc:
        raise AcquisitionError("utc_retrieval_timestamp_required") from exc
    rights = source.get("reuse", {})
    require(rights.get("status") in {"permitted", "hold", "rejected"}, "reuse_disposition_required")
    text(rights.get("reason"))
    require(rights.get("third_party_rights") in {"cleared", "unresolved"}, "third_party_review_required")
    if rights["status"] == "permitted" and rights["third_party_rights"] == "cleared":
        text(rights.get("license")); text(rights.get("attribution"))
    require(type(source.get("selected", False)) is bool, "invalid_snapshot_selection")
    if source.get("selected"):
        text(source.get("selection_reason"))
    return source["source_key"] + ":" + source["sha256"]


def select_snapshots(sources, as_of):
    """Choose within a population/issuer series; ambiguous or undated series stay unresolved."""
    groups = defaultdict(list)
    for source in sources:
        groups[tuple(source[k] for k in SERIES_FIELDS)].append(source)
    selections = []
    for key, group in sorted(groups.items()):
        future = [s for s in group if s.get("document_date") is not None and s["document_date"] > as_of]
        eligible = [s for s in group if s.get("document_date") is None or s["document_date"] <= as_of]
        require(not any(s.get("selected") for s in future), "cannot_select_future_snapshot")
        explicit = [s for s in group if s.get("selected")]
        require(len(explicit) <= 1, "multiple_explicit_snapshots_in_series")
        if explicit:
            selected, reason = explicit[0], "explicit_reviewed_selection"
        elif not eligible:
            selected, reason = None, "no_snapshot_on_or_before_as_of"
        elif any(s.get("document_date") is None for s in eligible):
            selected, reason = None, "undated_snapshot_requires_selection"
        else:
            latest = max(s["document_date"] for s in eligible)
            candidates = [s for s in eligible if s["document_date"] == latest]
            selected = candidates[0] if len(candidates) == 1 else None
            reason = "latest_permitted_document_date" if selected else "same_date_variants_require_selection"
        selections.append({**dict(zip(SERIES_FIELDS, key)),
                           "snapshot_ids": sorted(s["snapshot_id"] for s in group),
                           "future_snapshot_ids": sorted(s["snapshot_id"] for s in future),
                           "selected_snapshot_id": selected["snapshot_id"] if selected else None,
                           "reason": reason,
                           "selection_reason": selected.get("selection_reason") if selected else None})
    return selections


def read_rows(root, source):
    raw = local_file(root, source["raw_file"])
    require(file_digest(raw) == source["sha256"], "raw_hash_mismatch")
    extracted = local_file(root, source["rows_file"])
    require(file_digest(extracted) == sha(source["rows_sha256"]), "extraction_hash_mismatch")
    payload = json.loads(extracted.read_text(encoding="utf-8"))
    require(payload.get("raw_sha256") == source["sha256"], "extraction_source_mismatch")
    require(payload.get("review_status") == "producer_checked", "producer_transcription_review_required")
    text(payload.get("reviewer"))
    require(isinstance(payload.get("rows"), list), "rows_array_required")
    rows, held, locators = [], [], set()
    for original in payload["rows"]:
        require(isinstance(original, dict), "invalid_row")
        loc = locator(original.get("locator"))
        require(loc not in locators, "duplicate_row_locator")
        locators.add(loc)
        rights = original.get("rights", "cleared")
        require(rights in {"cleared", "unresolved"}, "invalid_row_rights")
        if rights == "unresolved":
            held.append({"snapshot_id": source["snapshot_id"], "locator": loc,
                         "row_sha256": digest(canonical(original)), "disposition": "hold",
                         "reason": "unresolved_row_third_party_rights"})
            continue
        kind = original.get("kind")
        require(kind in KINDS, "explicit_record_kind_required")
        fields = {k: text(original.get(k), nullable=True) for k in (
            "name_raw", "address_raw", "city", "state", "pin", "institution_type", "scope_raw",
            "validity_raw", "scheme_id", "scheme_id_namespace")}
        require((fields["scheme_id"] is None) == (fields["scheme_id_namespace"] is None), "scheme_id_namespace_required")
        flags = ["unlinked_source_observation", "independent_campus_review_pending"]
        if not fields["name_raw"]:
            flags.append("missing_name")
        if not fields["city"] or not fields["state"]:
            flags.append("unknown_geography")
        pin = fields["pin"]
        if pin and not re.fullmatch(r"[1-9][0-9]{5}", pin):
            pin = None
            flags.append("invalid_pin")
        if kind != "campus":
            flags.append("group_not_a_single_campus")
        parent = locator(original["parent_locator"]) if original.get("parent_locator") else None
        representation = locator(original["representation_of"]) if original.get("representation_of") else None
        if representation:
            text(original.get("representation_reason"))
            flags.append("duplicate_representation")
        branches = original.get("branch_labels", [])
        require(isinstance(branches, list) and all(isinstance(v, str) and v.strip() for v in branches), "invalid_branch_labels")
        require(not branches or kind == "multi_campus_group", "branches_require_group")
        episodes, validity_flags = validity(fields["validity_raw"])
        flags.extend(validity_flags)
        require(type(original.get("diagnostics_only", False)) is bool, "invalid_diagnostics_flag")
        events = original.get("events", [])
        require(isinstance(events, list), "invalid_events")
        for event in events:
            require(isinstance(event, dict) and event.get("kind") in EVENTS, "invalid_scheme_event")
            excerpt = text(event.get("excerpt"))
            require(any(excerpt in (fields[k] or "") for k in ("name_raw", "scope_raw", "validity_raw")), "event_excerpt_not_in_row")
            iso_date(event.get("effective_date")); text(event.get("authority"))
        fragments = original.get("fragments", [])
        require(isinstance(fragments, list), "invalid_fragments")
        for fragment in fragments:
            require(isinstance(fragment, dict) and all(type(fragment.get(k)) is int and fragment[k] > 0
                    for k in ("page", "table")), "invalid_fragments")
            box = fragment.get("bbox")
            require(isinstance(box, list) and len(box) == 4 and all(type(v) in (int, float) for v in box)
                    and box[0] < box[2] and box[1] < box[3], "invalid_fragment_bounds")
            values = fragment.get("fields")
            require(isinstance(values, dict) and set(values) <= set(fields)
                    and all(isinstance(v, str) for v in values.values()), "invalid_fragment_fields")
        record_id = "cghs.row:" + digest(canonical([source["snapshot_id"], source["rows_sha256"], loc]))
        rows.append({**fields, "record_id": record_id, "snapshot_id": source["snapshot_id"],
                     "source_key": source["source_key"], "issuer": source["issuer"],
                     "eligible_population": source["eligible_population"], "coverage_scope": source["coverage_scope"],
                     "document_date": source.get("document_date"), "locator": loc,
                     "fragments": fragments,
                     "record_kind": kind, "parent_locator": parent, "representation_of": representation,
                     "representation_reason": original.get("representation_reason"), "branch_labels": branches,
                     "pin_normalized": pin, "validity_episodes": episodes, "events": events,
                     "diagnostics_only": original.get("diagnostics_only", False), "quality_flags": flags,
                     "live_availability": "unknown", "vf_match_status": "pending_full_national_comparison",
                     "clinical_service_status": {s: "unconfirmed" for s in ("dialysis", "mri", "trauma_care")}})
    by_locator = {r["locator"]: r for r in rows}
    for row in rows:
        parent, rep = row["parent_locator"], row["representation_of"]
        if parent:
            require(row["record_kind"] == "campus" and parent in by_locator
                    and by_locator[parent]["record_kind"] == "group_summary"
                    and not by_locator[parent]["representation_of"], "unresolved_parent_group")
        if rep:
            require(rep in by_locator and rep != row["locator"] and not by_locator[rep]["representation_of"]
                    and by_locator[rep]["record_kind"] == row["record_kind"], "invalid_duplicate_representation")
    return sorted(rows, key=lambda r: r["record_id"]), held


def compile_collection(manifest, root):
    require(manifest.get("manifest_version") == "1.0.0", "unsupported_manifest_version")
    require(isinstance(manifest.get("sources"), list), "sources_array_required")
    require(iso_date(manifest.get("as_of")) is not None, "as_of_required")
    root = Path(root)
    sources, inventory, all_rows, held_rows, seen = [], [], [], [], set()
    for supplied in manifest["sources"]:
        source = dict(supplied)
        sid = source_metadata(source)
        require(sid not in seen, "duplicate_snapshot_receipt")
        seen.add(sid); source["snapshot_id"] = sid
        rights = source["reuse"]
        permitted = rights["status"] == "permitted" and rights["third_party_rights"] == "cleared"
        require(not source.get("selected") or permitted, "cannot_select_held_snapshot")
        item = {k: source.get(k) for k in ("snapshot_id", "source_key", *SERIES_FIELDS, "publisher", "url", "sha256", "retrieved_at", "document_date")}
        item.update(disposition="parsed" if permitted else "rejected" if rights["status"] == "rejected" else "held",
                    reason=rights["reason"], rows=None, held_rows=None)
        if permitted:
            rows, held = read_rows(root, source)
            source["rows"] = rows
            all_rows.extend(rows); held_rows.extend(held); sources.append(source)
            item.update(rows=len(rows), held_rows=len(held), rows_sha256=source["rows_sha256"])
        inventory.append(item)
    selections = select_snapshots(sources, manifest["as_of"])
    selected = {s["selected_snapshot_id"] for s in selections if s["selected_snapshot_id"]}
    batch = envelope()
    for selection in selections:
        if not selection["selected_snapshot_id"]:
            action = (f"Provide a reviewed snapshot dated on or before {manifest['as_of']}; later editions remain excluded."
                      if selection["reason"] == "no_snapshot_on_or_before_as_of" else
                      "Select one reviewed snapshot for this issuer/population series; retrieval time is not a document date.")
            batch["review_queue"].append(review(selection["reason"], selection["snapshot_ids"],
                action=action))
    for source in sources:
        if source["snapshot_id"] not in selected:
            continue
        batch["source_snapshots"].append({"snapshot_id": source["snapshot_id"], "source_key": source["source_key"],
            "publisher": source["publisher"], "source_family": source["source_family"], "url": source["url"],
            "retrieved_at": source["retrieved_at"], "published_date": source.get("document_date"),
            "license": source["reuse"]["license"], "attribution": source["reuse"]["attribution"],
            "sha256": source["sha256"], "artifact_uri": "urn:sha256:" + source["sha256"],
            "parser_version": PARSER_VERSION, "independence_status": "shared_origin"})
    repeated = defaultdict(list)
    for row in all_rows:
        if row["record_kind"] == "campus" and not row["representation_of"] and row["name_raw"] and row["address_raw"]:
            repeated[(row["snapshot_id"], row["name_raw"], row["address_raw"])].append(row)
    repeated_groups = []
    for key, members in sorted(repeated.items()):
        if len(members) < 2:
            continue
        group_id = "cghs.repeated:" + digest(canonical(key))
        repeated_groups.append({"group_id": group_id, "snapshot_id": key[0], "record_ids": sorted(r["record_id"] for r in members),
                                "reason": "exact_name_address_repetition_not_confirmed_deduplication"})
        for row in members:
            row["same_name_address_group_id"] = group_id
            row["quality_flags"].append("repeated_name_address_preserved")
    latest = []
    for row in sorted(all_rows, key=lambda r: r["record_id"]):
        row["selected_snapshot"] = row["snapshot_id"] in selected
        if not row["selected_snapshot"]:
            continue
        latest.append(row)
        if row["representation_of"]:
            continue
        xid = None
        if row["record_kind"] == "campus":
            xid = "cghs.external:" + row["record_id"].split(":", 1)[1]
            batch["external_facilities"].append({"external_facility_id": xid, "snapshot_id": row["snapshot_id"],
                "source_record_id": (row["scheme_id_namespace"] + ":" + row["scheme_id"]) if row["scheme_id"] else None,
                "record_locator": row["locator"], "name_original": row["name_raw"],
                "name_normalized": " ".join(row["name_raw"].casefold().split()) if row["name_raw"] else None,
                "address_original": row["address_raw"], "facility_type": row["institution_type"] or "healthcare_facility",
                "city": row["city"], "state": row["state"], "pin": row["pin_normalized"],
                "latitude": None, "longitude": None, "coordinate_method": None,
                "quality_flags": sorted(set(row["quality_flags"]))})
        for flag in sorted(set(row["quality_flags"]) - {"unlinked_source_observation"}):
            batch["review_queue"].append(review(flag, row["record_id"], external_id=xid,
                action=f"Inspect {row['locator']} in snapshot {row['snapshot_id']}; preserve source population and scope. No automatic campus or clinical confirmation."))
    for table, key in (("source_snapshots", "snapshot_id"), ("external_facilities", "external_facility_id"), ("review_queue", "review_id")):
        batch[table].sort(key=lambda r: r[key])
    validate(batch)
    counts = Counter((r["issuer"], r["city"] or "Unknown", r["state"] or "Unknown",
                      "duplicate_representation" if r["representation_of"] else r["record_kind"]) for r in latest)
    report = {"parser_version": PARSER_VERSION, "as_of": manifest["as_of"], "national_target_rows": 10088,
              "vf_overlap": None, "confirmed_vf_identities": None, "supported_vf_services": None,
              "source_dispositions": dict(sorted(Counter(i["disposition"] for i in inventory).items())),
              "retained_snapshot_observations": len(all_rows), "selected_snapshot_observations": len(latest),
              "selected_campus_observations": len(batch["external_facilities"]),
              "selected_group_records": sum(r["record_kind"] != "campus" and not r["representation_of"] for r in latest),
              "selected_duplicate_representations": sum(bool(r["representation_of"]) for r in latest),
              "held_rows": len(held_rows), "unresolved_snapshot_series": sum(s["selected_snapshot_id"] is None for s in selections),
              "future_dated_permitted_snapshots": sum(len(s["future_snapshot_ids"]) for s in selections),
              "diagnostics_only_campus_observations": sum(r["diagnostics_only"] and r["record_kind"] == "campus" and not r["representation_of"] for r in latest),
              "by_issuer_city_state_kind": [{"issuer": k[0], "city": k[1], "state": k[2], "kind": k[3], "rows": n} for k, n in sorted(counts.items())],
              "live_availability": "unknown", "live_databricks": "not_run", "submission": "not_performed"}
    return {"batch.json": batch, "observations.json": sorted(all_rows, key=lambda r: r["record_id"]),
            "source_inventory.json": sorted(inventory, key=lambda i: i["snapshot_id"]),
            "snapshot_selection.json": selections, "held_rows.json": sorted(held_rows, key=lambda r: (r["snapshot_id"], r["locator"])),
            "repeated_identity_groups.json": sorted(repeated_groups, key=lambda r: r["group_id"]), "report.json": report}


def run(manifest_path, output):
    manifest_path = Path(manifest_path)
    artifacts = compile_collection(json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path.parent)
    hashes = {name: digest(canonical(data) + b"\n") for name, data in artifacts.items()}
    publish_json_directory(output, {**artifacts, "sha256.json": hashes}, "existing_cghs_release_differs")
    return hashes
