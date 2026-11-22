"""Join authorized candidate feeds without admitting unreviewed premises."""

from collections import Counter
import gzip
import hashlib
import json

from . import core

CLINICAL_EDITION = "issue-270-j-clinical-v1"
CLINICAL_PIN = "2e1e628dc0e6450c73b7ad4c4d8e38f098513affd05e8e2e3c65e72eed645b25"
BUILDINGS_EDITION = "issue-270-j-buildings-v1"
BUILDINGS_PIN = "043f738dd9305c0aa009ec13e38e9a62fdcb7e7e0ba7f28e83fd5ef983a28400"
RURAL_EDITION = "loc270-g-rural-v1"
RURAL_PIN = "b2b52fd16babe8da86d04d2a8a367fc390c8c03b3ec42fecbc4a48e0cfc3b81a"
AREA_OUTCOMES = {"area_name_type_district_and_address_token", "area_name_type_and_district"}
RURAL_COUNTS = {"area_name_type_district_and_address_token": 1, "area_name_type_and_district": 2,
                "state_namesake_only": 4, "typed_no_match": 9, "no_explicit_rural_type": 10072}


def package(folder, edition, digest, used):
    manifest = core.read(folder / "manifest.json", digest)
    pins = {name: manifest["files"][name] for name in used}
    for name, pin in pins.items():
        core.checked(folder / name, pin)
    return manifest, {
        "manifest_sha256": digest, "verified_members": pins,
        "source_uri": f"{core.MATCHING}/{edition}-{digest}/manifest.json",
    }


def area_members(frame):
    return {key for key, row in frame.items() if row["baseline_directory_status"] == "area_located"}


def geometry(frame, j_clinical, j_buildings):
    clinical_members = ("clinical.jsonl", "clinical-summary.json")
    building_members = ("buildings.jsonl", "buildings-summary.json", "national-rollup.json")
    mc, cp = package(j_clinical, CLINICAL_EDITION, CLINICAL_PIN, clinical_members)
    mb, bp = package(j_buildings, BUILDINGS_EDITION, BUILDINGS_PIN, building_members)
    baseline = {"occurrences.jsonl.gz": core.D_OCC, "decisions.jsonl.gz": core.D_DECISIONS}
    core.need(mc["vf_input_sha256"] == mb["vf_input_sha256"] == baseline
              and mc["pbf_sha256"] == mb["pbf_sha256"] and mb["clinical_edition"] == CLINICAL_PIN,
              "clinical and building feeds have different frozen frames or OSM editions")
    geo = core.read(j_clinical / clinical_members[1], cp["verified_members"][clinical_members[1]])
    roll = core.read(j_buildings / building_members[2], bp["verified_members"][building_members[2]])["national"]
    a = core.rows(j_clinical / clinical_members[0])
    b = core.rows(j_buildings / building_members[0])
    all_signals, points = {}, Counter()
    for key, clinical, buildings in zip(frame, a, b, strict=True):
        core.need(key == clinical["occurrence_key"] == buildings["occurrence_key"], "J occurrence order or key shifted")
        f = clinical["flags"]
        core.need(set(f) <= set(geo["occurrences"]), "unknown clinical flag")
        interior = [item for item in buildings["buildings"] if item["interior"]]
        has_building = bool(interior)
        has_name = any(item["exact_name"] for item in interior)
        grounds = bool(f.get("inside_site_without_building_tag"))
        clinical_building = bool(f.get("inside_mapped_building"))
        clinical_interior = bool(f.get("interior"))
        usable = clinical["screen"] != "unusable_original_point"
        points[clinical["screen"]] += 1
        all_signals[key] = {
            **{name: bool(f.get(name)) for name in geo["occurrences"]},
            "point_usable": usable,
            "any_building_interior": has_building,
            "any_building_boundary": any(not item["interior"] for item in buildings["buildings"]),
            "any_building_interior_exact_name": has_name,
            "any_building_interior_multiple": len(interior) > 1,
            "any_building_interior_with_no_exact_name": has_building and not has_name,
            "building_interior_and_clinical_grounds_interior": has_building and grounds,
            "clinical_grounds_interior_without_mapped_building_interior": grounds and not has_building,
            "building_interior_without_clinical_building_interior": has_building and not clinical_building,
            "building_interior_and_clinical_outline_interior": has_building and clinical_interior,
            "any_building_interior_or_clinical_outline_interior": has_building or clinical_interior,
        }
    core.need(points == geo["point_classes"] and len(all_signals) == roll["original_occurrences"] == 10088,
              "J national cohort or original point screen changed")
    fields = tuple(next(iter(all_signals.values())))
    totals = signal_counts(all_signals, frame, fields)
    core.need(all(totals[name] == value for name, value in roll["counts"].items()),
              "J aggregate flags did not reproduce")
    area = area_members(frame)
    by_precision = {p: signal_counts(all_signals, (k for k in area if frame[k]["area"]["precision"] == p), fields)
                    for p in ("postal_area", "city", "locality")}
    by_original_state_availability = {
        label: signal_counts(all_signals, (k for k in area if
            (frame[k]["original_state"] in {core.NO_STATE, core.NOT_A_STATE}) == missing), fields)
        for label, missing in (("known", False), ("unknown", True))
    }
    return all_signals, {"clinical_input": cp, "all_building_input": bp, "origin": "OpenStreetMap",
                         "pbf_sha256": mc["pbf_sha256"], "snapshot_date": mc["pbf_snapshot_utc"][:10],
                         "national": totals, "actual_area": signal_counts(all_signals, area, fields),
                         "actual_area_by_precision": by_precision,
                         "actual_area_by_original_state_availability": by_original_state_availability,
                         "approved_promotions_from_j_screen": 0, "wrong_branch_rate": None}


def signal_counts(signals, keys, fields):
    totals = Counter()
    for key in keys:
        totals.update(signals[key])
    return {name: totals[name] for name in fields}


def rural(frame, folder):
    names = ("occurrence-projection.json.gz", "aggregate.json", "method-and-scope.json")
    _, receipt = package(folder, RURAL_EDITION, RURAL_PIN, names)
    tokens = {hashlib.sha256(key.encode("utf-8")).hexdigest(): key for key in frame}
    core.need(len(tokens) == len(frame) == 10088, "G token collision")
    area = area_members(frame)
    outcomes, sources, seen = {}, Counter(), set()
    with gzip.open(folder / names[0], "rb") as stream:
        projection = json.load(stream)
    for row in projection:
        h = row["occurrence_token_sha256"]
        core.need(h in tokens and h not in seen, "G token duplication or out-of-frame key")
        seen.add(h)
        key = tokens[h]
        outcome = row["outcome"]
        outcomes[key] = outcome
        if key in area and outcome in AREA_OUTCOMES:
            sources.update(historical_health_centres=bool(row["historical_district_candidates"]),
                           official_nhp=bool(row["nhp_district_candidates"]))
    core.need(seen == tokens.keys() and Counter(outcomes.values()) == RURAL_COUNTS,
              "G token coverage or national outcome counts changed")

    def counts(keys):
        out = Counter(outcomes[key] for key in keys)
        return {name: out[name] for name in RURAL_COUNTS}

    leads = {k for k in area if outcomes[k] in AREA_OUTCOMES}
    return leads, {"input": receipt, "origin": "MoHFW historical OGD and NHP", "national": counts(frame),
                   "actual_area": counts(area), "district_compatible_leads_by_source_on_actual_area": dict(sources),
                   "actual_area_by_precision": {
                       p: counts(k for k in area if frame[k]["area"]["precision"] == p)
                       for p in ("postal_area", "city", "locality")},
                   "approved_promotions_from_g_b2_screen": 0, "wrong_branch_rate": None}


def overlap(frame, geo_signals, rural_leads, additional=None):
    area = area_members(frame)
    groups = {
        "j_clinical_interior": {k for k in area if geo_signals[k]["interior"]},
        "j_all_building_interior": {k for k in area if geo_signals[k]["any_building_interior"]},
        "g_b2_district_compatible_lead": rural_leads,
    }
    groups.update({name: keys & area for name, keys in (additional or {}).items()})
    key_union = set().union(*groups.values())
    combos = Counter(
        "+".join(name for name, members in groups.items() if k in members) for k in key_union
    )
    outside = len(area - key_union)
    core.need(sum(combos.values()) + outside == len(area), "candidate union did not retain the cohort")
    return {"actual_cohort": len(area), "across_keyed_feeds": list(groups),
            "candidate_flags_by_exact_combination": dict(combos),
            "unique_originals_with_at_least_one_of_these_flags": len(key_union),
            "originals_without_any_of_these_flags": outside,
            "source_domains": "J’s two flags share OSM origin. G/B2 and H share MoHFW material where documented. A uses the NABH source.",
            "outside_joined_feeds_overlap": None,
            "interpretation": "This is a deduplicated lead union on original occurrences. Any promotion requires D’s separate reviewed premises and entrance result."}, key_union
