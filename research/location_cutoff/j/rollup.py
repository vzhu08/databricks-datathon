"""Reconcile clinical and building overlaps; an authorized custodian may intersect v4 locally."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from research.acquisition.osm_services.pbf import file_digest

V4_SHA = "f444e4dda3c8f9c9f1efc7738a03c341dc1a3c67ec267e6b777a8baae8b5a2d8"
V4_COUNTS = {"campus_located": 2524, "area_located": 7418, "unresolved": 146}


def v4_area_keys(path, expected_keys):
    if file_digest(path) != V4_SHA:
        raise ValueError("Directory v4 occurrence digest differs")
    statuses = {}
    with gzip.open(path, "rt") as stream:
        for row in map(json.loads, stream):
            key = row["facility_id"]
            if key in statuses:
                raise ValueError("Duplicate directory v4 occurrence key")
            statuses[key] = row["directory_location"]["status"]
    if statuses.keys() != expected_keys:
        raise ValueError("Directory v4 occurrence keys differ")
    if Counter(statuses.values()) != V4_COUNTS:
        raise ValueError("Directory v4 counts differ")
    return {key for key, status in statuses.items() if status == "area_located"}


def footprint_counts(rows, selected):
    totals = Counter()
    for key in selected:
        clinical, mapped = rows[key]
        flags = clinical["flags"]
        interior = [b for b in mapped["buildings"] if b["interior"]]
        clinical_ids = {c["id"] for c in clinical["candidates"] if c["interior"] and c["building"]}
        generic_ids = {b["id"] for b in interior}
        if not clinical_ids <= generic_ids:
            raise ValueError("Mapped clinical buildings missing from building pass")
        totals.update(flags)
        totals.update({
            "point_usable": clinical["screen"] != "unusable_original_point",
            "any_building_interior": bool(interior),
            "any_building_boundary": any(not b["interior"] for b in mapped["buildings"]),
            "any_building_interior_multiple": len(interior) > 1,
            "any_building_interior_exact_name": any(b["exact_name"] for b in interior),
            "any_building_interior_with_no_exact_name": bool(interior) and not any(b["exact_name"] for b in interior),
            "building_interior_without_clinical_building_interior": bool(generic_ids and not clinical_ids),
            "building_interior_and_clinical_grounds_interior":
                bool(interior and flags.get("inside_site_without_building_tag")),
            "clinical_grounds_interior_without_mapped_building_interior":
                bool(flags.get("inside_site_without_building_tag") and not interior),
        })
    return {"original_occurrences": len(selected), "counts": dict(sorted(totals.items()))}


def run(directory, v4, subset):
    clinical_path, buildings_path = directory / "clinical.jsonl", directory / "buildings.jsonl"
    for name, path, field in (("clinical", clinical_path, "candidate_ledger_sha256"),
                               ("buildings", buildings_path, "ledger_sha256")):
        summary = json.loads((directory / f"{name}-summary.json").read_text())
        if file_digest(path) != summary[field]:
            raise ValueError(f"{name} ledger digest differs from summary")
    with clinical_path.open() as left, buildings_path.open() as right:
        rows = {}
        for a, b in zip(map(json.loads, left), map(json.loads, right), strict=True):
            key = a["occurrence_key"]
            if b["occurrence_key"] != key or key in rows:
                raise ValueError("Duplicate or different occurrence key in building comparison")
            rows[key] = (a, b)
    if len(rows) != 10088:
        raise ValueError("Incomplete national frame")
    selection = set(rows)
    result = {"national": footprint_counts(rows, selection)}
    if subset is not None:
        chosen = [json.loads(line) for line in subset.read_text().splitlines()]
        if not all(isinstance(key, str) for key in chosen):
            raise ValueError("Subset must contain occurrence-key strings")
        if len(set(chosen)) != len(chosen) or not set(chosen) <= selection:
            raise ValueError("Subset contains a duplicate or unknown occurrence")
        selection = set(chosen)
        result["subset_sha256"] = file_digest(subset)
        result["subset"] = footprint_counts(rows, selection)
    if v4 is not None:
        area = v4_area_keys(v4, set(rows))
        result["v4_sha256"] = V4_SHA
        result["v4_area"] = footprint_counts(rows, area)
        if subset is not None:
            result["subset_v4_area"] = footprint_counts(rows, selection & area)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--v4", type=Path, help="Pinned local directory-v4 occurrence file, in authorized custody")
    parser.add_argument("--subset", type=Path, help="Private JSONL of distinct original occurrence-key strings")
    args = parser.parse_args()
    print(json.dumps(run(args.directory, args.v4, args.subset), sort_keys=True, indent=2))
