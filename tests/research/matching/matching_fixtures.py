"""Entirely synthetic builders. No name, address, phone or coordinate here
describes a real facility; places are invented and coordinates are arbitrary."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# D's validator is imported read-only so C's outputs are checked by the normative code.
sys.path.insert(0, str(ROOT / "databricks/enrichment"))

REVIEWER = "synthetic-reviewer"
AT = "2026-11-21T19:00:00Z"
LATER = "2026-11-21T20:00:00Z"


def snapshot(key="synthetic_directory", family=None):
    sha = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return {"snapshot_id": f"{key}:{sha}", "source_key": key, "publisher": "Synthetic fixture publisher",
            "source_family": family or key, "url": f"https://example.invalid/{key}",
            "retrieved_at": "2026-11-21T17:00:00Z", "published_date": None,
            "license": "Synthetic fixture; no real source content", "attribution": "Entirely synthetic example",
            "sha256": sha, "artifact_uri": f"synthetic://{key}", "parser_version": "fixture-1.0.0",
            "independence_status": "unassessed"}


def ext(number, name, snap, **fields):
    row = {"external_facility_id": f"synthetic:external:{number:03d}", "snapshot_id": snap["snapshot_id"],
           "source_record_id": f"EX-{number:03d}", "record_locator": f"synthetic row {number}",
           "name_original": name, "name_normalized": name.casefold() if name else None,
           "address_original": None, "facility_type": "hospital", "city": None, "state": None, "pin": None,
           "latitude": None, "longitude": None, "coordinate_method": None, "quality_flags": ["synthetic_only"]}
    row.update(fields)
    if row["latitude"] is not None and row["coordinate_method"] is None:
        row["coordinate_method"] = "source_point"
    return row


def envelope(snapshots, externals, evidence=()):
    return {"contract_version": "1.0.0", "source_snapshots": list(snapshots),
            "external_facilities": list(externals), "facility_matches": [],
            "facility_evidence": list(evidence), "review_queue": []}


def base_row(number, **columns):
    """D's export shape: every original column preserved under source_row."""
    return {"facility_id": f"synthetic:base:{number:03d}", "source_row": dict(columns)}


def mapping(base, **extra):
    keys = set()
    for row in base:
        keys.update(row["source_row"])
    roles = {"name": "name", "address": "address", "city": "city", "district": "district", "state": "state",
             "pin": "pin", "latitude": "lat", "longitude": "lon", "phone": "phone", "type": "type",
             "alt_names": "aliases"}
    result = {role: f"source_row.{column}" for role, column in roles.items() if column in keys}
    result.update(extra)
    return result


def trauma_evidence(number, external_row, snap, polarity="supports", reviewed=True):
    return {"evidence_id": f"synthetic:evidence:{number:03d}",
            "external_facility_id": external_row["external_facility_id"], "snapshot_id": snap["snapshot_id"],
            "facility_id": None, "match_id": None, "claim_type": "service", "service": "trauma_care",
            "polarity": polarity,
            "assertion": "Synthetic programme listed a trauma centre in 2018; current availability unknown.",
            "excerpt": "Synthetic campus: trauma centre, 2018.", "observation": None,
            "locator": f"synthetic page 1, row {number}", "source_url": snap["url"],
            "effective_date": "2018-01-01", "valid_until": None, "temporal_status": "historical",
            "reviewer": REVIEWER if reviewed else None, "reviewed_at": AT if reviewed else None}


def square(lat, lon, half_m=20.0):
    """A small square footprint centred on (lat, lon). Arbitrary synthetic geometry."""
    dlat = half_m / 111320.0
    dlon = half_m / (111320.0 * 0.9)
    ring = [[lon - dlon, lat - dlat], [lon + dlon, lat - dlat], [lon + dlon, lat + dlat],
            [lon - dlon, lat + dlat], [lon - dlon, lat - dlat]]
    return {"type": "Polygon", "coordinates": [ring]}


def by_pair(result):
    return {(c["facility_id"], c["external_facility_id"]): c for c in result["candidates"]}


def match_for(result, base_number, ext_number):
    pair = (f"synthetic:base:{base_number:03d}", f"synthetic:external:{ext_number:03d}")
    for row in result["batch"]["facility_matches"]:
        if (row["facility_id"], row["external_facility_id"]) == pair:
            return row
    return None
