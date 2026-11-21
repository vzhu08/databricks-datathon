"""Geographic screening of base rows and external records.

Produces flags, proposed corrections beside the original values, coordinate
clusters and postal context. It changes no record and decides no identity.
"""
from __future__ import annotations

import re
from collections import Counter

from research.matching.common import stable_id
from .checks import duplicate_clusters, low_precision
from .postal import join

REVIEW_NS = "acq-c-geo-review"
_SIX = re.compile(r"(?<!\d)(\d{6})(?!\d)")

BASE_REVIEW = {
    "coordinates_incomplete": ("medium", "Only one coordinate value is present. Recover the pair from the original record; do not guess."),
    "coordinates_not_finite_numbers": ("medium", "Coordinate values are not finite numbers. Inspect the original record."),
    "coordinates_outside_wgs84": ("high", "Coordinates are outside the WGS84 range. Inspect the original record before any distance check."),
    "possible_swapped_axes": ("high", "Latitude and longitude look swapped. A proposed correction is recorded beside the original; confirm it against the address before use."),
    "outside_india_envelope": ("medium", "Coordinates fall outside the broad India envelope. Confirm the location; the envelope is a screening cue, not a border."),
    "null_island": ("high", "Coordinates are 0,0. Treat the location as unknown until corrected from a source."),
    "state_disagrees_with_pin": ("medium", "The stated state is not one the postal directory lists for this PIN. Check which is wrong."),
    "pin_state_evidence_incomplete": ("low", "At least one post office with this PIN has no state, or a state label that is not a recognised state, in the postal directory. The row's state cannot be checked against its PIN."),
    "district_disagrees_with_pin": ("low", "The stated district is not one the postal directory lists for this PIN. Check which is wrong."),
    "address_pin_disagrees": ("low", "The address text contains a different six-digit PIN from the PIN field. Check which is right."),
    "duplicate_coordinate_cluster": ("low", "Several differently named rows share exactly this point. It may be a town centroid or geocoder fallback."),
}


def _address_pin_conflict(view, address_text):
    if not view["pin"] or not isinstance(address_text, str):
        return False
    found = set(_SIX.findall(address_text))
    return bool(found) and view["pin"] not in found


def screen(views, kind, address_of, postal=None):
    """Per-record findings for `views` (base or external). `address_of(view)`
    returns the original address text or None."""
    findings = {}
    context = join([{"pin": v["pin"], "state_key": v["state"], "district_key": v["district"]} for v in views],
                   postal) if postal is not None else None
    for position, v in enumerate(views):
        flags = [f for f in v["coord"]["flags"] if f != "coordinates_missing"]
        if "coordinates_missing" in v["coord"]["flags"]:
            flags.append("coordinates_missing")
        if v["coord"]["usable"] and low_precision(v["coord"]["lat"], v["coord"]["lon"]):
            flags.append("low_precision_coordinates")
        if v.get("pin_invalid"):
            flags.append("pin_invalid_in_source")
        if _address_pin_conflict(v, address_of(v)):
            flags.append("address_pin_disagrees")
        if context is not None:
            flags.extend(context[position]["postal_flags"])
        findings[v["id"]] = {"flags": flags, "proposed": v["coord"]["proposed"],
                             "original": {"latitude": v["coord"]["lat"], "longitude": v["coord"]["lon"]}}
    points = [(v["id"], v["coord"]["lat"], v["coord"]["lon"], tuple(v["names"][0]) if v["names"] else None)
              for v in views if v["coord"]["usable"]]
    clusters = duplicate_clusters(points)
    for cluster in clusters:
        for record_id in cluster["record_ids"]:
            findings[record_id]["flags"].append("duplicate_coordinate_cluster")
    counts = Counter(flag for f in findings.values() for flag in f["flags"])
    return {"kind": kind, "records": len(views), "flag_counts": dict(sorted(counts.items())),
            "usable_coordinates": sum(v["coord"]["usable"] for v in views),
            "proposed_corrections": [
                {"record_id": rid, "original": f["original"], "proposed": f["proposed"],
                 "note": "Proposal only. The original coordinates are unchanged everywhere."}
                for rid, f in sorted(findings.items()) if f["proposed"]],
            "duplicate_coordinate_clusters": clusters,
            "postal_context": "not supplied; PIN/state/district consistency is unknown" if postal is None else "supplied",
            }, findings


def base_reviews(findings):
    """Queue items for base rows. One per (row, reason); clusters are queued once."""
    reviews = []
    for facility_id in sorted(findings):
        for flag in findings[facility_id]["flags"]:
            if flag not in BASE_REVIEW or flag == "duplicate_coordinate_cluster":
                continue
            severity, action = BASE_REVIEW[flag]
            reviews.append({"review_id": stable_id(REVIEW_NS, flag, facility_id), "facility_id": facility_id,
                            "external_facility_id": None, "evidence_id": None, "match_id": None,
                            "reason_code": "base_" + flag, "severity": severity, "status": "open",
                            "next_action": action, "resolution": None})
    return reviews


def cluster_reviews(report):
    severity, action = BASE_REVIEW["duplicate_coordinate_cluster"]
    out = []
    for cluster in report["duplicate_coordinate_clusters"]:
        first = cluster["record_ids"][0]
        out.append({"review_id": stable_id(REVIEW_NS, "duplicate_coordinate_cluster", cluster["record_ids"]),
                    "facility_id": first, "external_facility_id": None, "evidence_id": None, "match_id": None,
                    "reason_code": "base_duplicate_coordinate_cluster", "severity": severity, "status": "open",
                    "next_action": f"{action} {cluster['record_count']} rows share the point; the full list is in geography_report.json.",
                    "resolution": None})
    return out
