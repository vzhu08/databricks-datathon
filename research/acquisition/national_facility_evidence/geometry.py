"""Verify the permitted issuer-to-OSM geometry projection without a VF join."""

from collections import Counter, defaultdict

from . import inputs, model

ISSUER_FREEZE = "6a687d9b4fad7956e5144f8c4677beeb48d45f239604efe5ddfb4694281680e7"
EDITION = "issuer-campus-geometry-234"
MANIFEST = "ba49b00495d339dcba9a37bb5f8d75332779c47a84e36919e3a679af2aa4c11d"
SOURCE = f"{inputs.MATCHING}/{EDITION}-{MANIFEST}/manifest.json"
RECEIPT = f"{inputs.ISSUES}/234#issuecomment-7076553763"


def verify(root, folder, issuer):
    manifest, pins, files = inputs.package(folder, MANIFEST, ("candidates.jsonl", "summary.json"))
    model.need(manifest["audience"] == "Four authorized project readers only" and
               manifest["source_pins"]["issuer_freeze"] == ISSUER_FREEZE, "unexpected geometry scope or issuer freeze")
    summary = inputs.read(files["summary.json"], pins["summary.json"])
    _, d_pins, _ = inputs.d_paths(root)
    frozen = summary["national_frozen_frame"]
    model.need(frozen["input_sha256"] == {n: d_pins[n]["sha256"] for n in
                                         ("occurrences.jsonl.gz", "decisions.jsonl.gz")}
               and frozen["occurrence_count"] == 10088 and frozen["unconfirmed_decisions"] == 30264
               and not frozen["new_vf_links_computed"] and frozen["mutations"] == 0,
               "geometry edition did not use the same frozen VF frame")
    paths = {r["record_id"]: r for r in issuer.premises}
    source = {r["source_key"]: (r, paths[r["record_id"]]) for r in issuer.records}
    rows, seen, by_scope = [], set(), defaultdict(Counter)
    typed_objects, associations = defaultdict(set), Counter()
    measures = Counter()
    for row in inputs.lines(files["candidates.jsonl"]):
        listing = row["listing_id"]
        model.need(listing in source and listing not in seen, "orphan or duplicate issuer geometry row")
        seen.add(listing)
        record, premises = source[listing]
        original = record["original_fields"]
        model.need(row["payload_sha256"] == original["listing_payload_sha256"] and
                   row["capture_locator"] == [original["page"], original["position"]] and
                   row["has_address_key"] == bool(original["premises_key"]) and
                   row["has_numeric_point"] == bool(original["points"]),
                   "issuer payload, capture locator or input availability changed")
        model.need(row["entrance_confirmed"] is None and row["independent_premises_origin"] is None,
                   "geometry admission requires a new review disposition")
        outcome = row["outcome"]
        candidates = row["candidate_objects"]
        unique = {(r["edition"], r["osm_id"]) for r in candidates}
        model.need(len(unique) == len(candidates), "duplicated candidate edge inside issuer row")
        for edition, osm in unique:
            typed_objects[edition].add(osm)
            associations[edition] += 1
        measures.update(
            exact_branch_name_listings=any(c["same_name"] for c in candidates),
            exact_structured_address_listings=any(c["same_address"] for c in candidates),
            footprint_coincidence_listings_any_candidate=any(c["named_footprint_contains_point"] for c in candidates),
            listings_with_mapped_entrance_candidates=any(c["is_entrance"] for c in candidates),
            listings_with_declared_map_source_candidates=any(c["source_lineage"] for c in candidates),
            same_numeric_coordinates_6dp_listings=any(c["same_numeric_coordinates_6dp"] for c in candidates),
            listings_with_same_name_and_address_conflict=any(c["same_name"] and c["address_conflict"] for c in candidates),
        )
        geography = premises["state"] or "unknown"
        by_scope[geography][outcome] += 1
        rows.append({"issuer_record_id": record["record_id"], "issuer_premises_id": premises["premises_id"],
                     "issuer_postal_area": geography, "geometry_observation": row})

    model.need(seen == source.keys() and len(rows) == manifest["row_count"] == 49, "issuer geometry frame changed")
    outcomes = Counter(r["geometry_observation"]["outcome"] for r in rows)
    model.need(all(outcomes[k] == n for k, n in summary["outcomes"].items()) and
               associations == summary["eligible_osm_candidates_by_edition"] and
               associations.total() == manifest["candidate_observations"], "geometry outcome or association margin changed")
    shared = len(set.intersection(*typed_objects.values()))
    typed = len(set.union(*typed_objects.values()))
    model.need(shared == summary["shared_candidate_typed_osm_ids_between_editions"] and
               typed == summary["distinct_candidate_typed_osm_ids"] and
               all(measures[k] == summary[k] for k in measures if k in summary),
               "geometry lineage or evidence margins changed")
    return rows, {
        "scope": "49 frozen issuer listings. Issuer-to-map candidate evidence only.",
        "row_input": {"manifest_uri": SOURCE, "manifest_sha256": MANIFEST, "members": {n: pins[n] for n in files},
                      "custody": "Existing authorized four-reader source rows, freshly downloaded and checked",
                      "receipt": RECEIPT, "source_pins": manifest["source_pins"],
                      "licence": manifest["upstream_licenses"]},
        "issuer_listings": len(rows),
        "issuer_listings_with_eligible_address": sum(r["geometry_observation"]["has_address_key"] for r in rows),
        "issuer_listings_with_numeric_points": sum(r["geometry_observation"]["has_numeric_point"] for r in rows),
        "issuer_state_is_postal_area_context": True,
        "candidate_associations_by_map_edition": dict(associations),
        "distinct_typed_osm_objects": typed, "shared_typed_objects_between_map_editions": shared,
        "origin_family": "OpenStreetMap",
        "source_objects_screened_or_extracted": summary["source_objects_screened_or_extracted"],
        "combined_issuer_outcomes": summary["outcomes"],
        "by_issuer_postal_state_or_unknown": {s: dict(c) for s, c in by_scope.items()},
        "candidate_relation_diagnostics": dict(measures),
        "independently_verified_campuses": 0, "confirmed_entrances": 0, "added_vf_links": 0,
        "new_vf_link_comparison_performed": False, "added_service_decisions": 0,
    }
