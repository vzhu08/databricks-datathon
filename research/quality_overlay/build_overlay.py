"""Build the optional search quality overlay (app/ranking/quality.py) from the research outputs.

Inputs are row-level research files kept outside Git; so is the output.

    python3 -I research/quality_overlay/build_overlay.py \
        --integrity integrity_flags.csv --repairs pin_repairs.csv \
        --duplicates duplicate_clusters.csv --chains chain_rows.csv \
        --evidence evidence_table.csv --out quality_overlay.csv

Rules:
- `structure` integrity rows (shifted columns, no usable name, placeholder text) -> `excluded`.
- pin repair `high` or `medium` with a point -> `repaired` at that point, unless the proposal keeps the
  recorded point, in which case the row is left as it is.
- pin repair `low` or unresolved -> `unplaced`, with the screen's location reason codes.
- high or medium duplicate clusters, and chain rows that duplicate another campus record -> one
  `duplicate_group`.
- evidence ladder levels per service -> `evidence_<service>` (a badge only).
"""
import argparse
import csv

FIELDS = ["facility_id", "point_status", "latitude", "longitude", "location_method", "location_precision",
          "location_checks", "duplicate_group", "evidence_dialysis", "evidence_mri", "evidence_trauma_care"]
REASON_CODES = {
    "far_from_pin_100km": "far_from_pin_area",
    "far_from_pin_25km": "far_from_pin_area",
    "pin_state_mismatch": "far_from_pin_area",
    "point_in_other_state": "far_from_pin_area",
    "coords_outside_india": "far_from_pin_area",
    "far_from_city_50km": "far_from_town",
    "no_building_within_50m": "no_building_nearby",
    "coords_shared_unrelated": "shared_point",
}
LADDER = {
    "Self-reported only": "self_reported",
    "Identity independently corroborated": "identity_corroborated",
    "Dated related evidence (department or equipment proxy)": "dated_related",
    "Dated independent service evidence": "dated_service",
}
LADDER_COLUMNS = {"dialysis": "dialysis_ladder", "mri": "mri_ladder", "trauma_care": "trauma_ladder"}
TRIGGER_CODES = {"footprint:no_building_within_50m": "no_building_nearby", "footprint:shared_coordinates": "shared_point"}


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def ladder_level(value):
    value = (value or "").strip()
    if value in LADDER:
        return LADDER[value]
    return value if value in LADDER.values() else ""


def build(integrity, repairs, duplicates, chains, evidence):
    out = {}

    def row(facility_id):
        return out.setdefault(facility_id, dict.fromkeys(FIELDS, "") | {"facility_id": facility_id})

    reasons = {r["facility_id"]: set(filter(None, (r.get("reasons") or "").split("|"))) for r in integrity}
    for r in integrity:
        if "structure" in (r.get("families") or "").split("|"):
            row(r["facility_id"])["point_status"] = "excluded"

    for r in repairs:
        target = row(r["facility_id"])
        if target["point_status"] == "excluded":
            continue
        codes = sorted({REASON_CODES[x] for x in reasons.get(r["facility_id"], ()) if x in REASON_CODES}
                       | ({TRIGGER_CODES[r["trigger"]]} if r.get("trigger") in TRIGGER_CODES else set()))
        if r["confidence"] in ("high", "medium") and r.get("new_lat"):
            if r["method"].startswith("keep_point"):
                continue
            precision = r.get("point_precision") or "city"
            target.update(point_status="repaired", latitude=r["new_lat"], longitude=r["new_lon"],
                          location_method=r["method"], location_precision=precision)
        else:
            target.update(point_status="unplaced", location_checks="|".join(codes) or "far_from_pin_area")

    for r in duplicates:
        if r.get("cluster_confidence") in ("high", "medium"):
            row(r["vf_id"])["duplicate_group"] = "dup-" + r["cluster_id"]
    for r in chains:
        if r.get("role") == "duplicate_of_campus_record" and r.get("campus_record_id"):
            group = "campus-" + r["campus_id"]
            row(r["facility_id"])["duplicate_group"] = group
            row(r["campus_record_id"])["duplicate_group"] = group

    for r in evidence:
        for service, column in LADDER_COLUMNS.items():
            level = ladder_level(r.get(column))
            if level:
                row(r["facility_id"])["evidence_" + service] = level
    return [out[key] for key in sorted(out)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("integrity", "repairs", "duplicates", "chains", "evidence", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    rows = build(read(args.integrity), read(args.repairs), read(args.duplicates), read(args.chains), read(args.evidence))
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["point_status"] or "as_recorded"] = counts.get(r["point_status"] or "as_recorded", 0) + 1
    print(len(rows), "overlay rows", counts)


if __name__ == "__main__":
    main()
