"""Create or read the national, counts-only location summary for the presenter app."""

import argparse
import hashlib
import json
from pathlib import Path


SOURCE_SHA256 = "8fa615bd16f60170a55b1b04e9666b2dec937784f711b7e31aa367096ddf8d50"
DISPLAY_SHA256 = "dfb08860a7b8dfb2eeb4cb42741879deac26a599bb379db3d9f6f9baaa24f914"
TIERS = ("previously_findable", "registry_or_operator", "agreeing_points", "map_name_and_area", "unresolved")
EVIDENCE = ("registry_or_operator", "agreeing_points", "registry_or_agreeing_points",
            "nearby_only_possible_shared_origins")


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative whole-number count")
    return value


def project(source):
    national = source["national"]
    tiers = {key: count(national["mutually_exclusive"][key]) for key in TIERS}
    evidence = {key: count(national["overlapping"][key]) for key in EVIDENCE}
    total = count(source["population"])
    covered = count(national["overlapping"]["covered"])
    if sum(tiers.values()) != total or covered != total - tiers["unresolved"]:
        raise ValueError("National coverage does not reconcile to the original rows")
    union = evidence["registry_or_agreeing_points"]
    a, b = evidence["registry_or_operator"], evidence["agreeing_points"]
    if not (max(a, b) <= union <= min(a + b, covered) and evidence["nearby_only_possible_shared_origins"] <= b):
        raise ValueError("Overlapping evidence counts do not reconcile")
    return {
        "edition": "national-facility-area-display-v1",
        "as_of": "2026-11-22",
        "population": total,
        "covered": covered,
        "coverage_tiers": tiers,
        "overlapping_evidence": evidence,
        "source": "Virtue Foundation v0, official NHP and NABH directories, Overture Maps, "
                  "© OpenStreetMap contributors, and the frozen project directory.",
        "osm_attribution_url": "https://www.openstreetmap.org/copyright",
        "method": "Each original record counts once. A named facility can qualify in a registry locality, "
                  "landmark area or PIN, through a map listing in that area, or with agreeing points under 1 km.",
        "limitations": "VF and external maps may share a source. Building accuracy, present-day operation "
                       "and onsite services require separate evidence.",
    }


def read_summary(raw):
    """Read bytes from the hosted app's existing local/Volume file reader."""
    if hashlib.sha256(raw).hexdigest() != DISPLAY_SHA256:
        raise ValueError("The national location summary is unavailable for this edition")
    return json.loads(raw)


def build(source, destination):
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("The source does not match the verified November 22 aggregate")
    data = project(json.loads(raw))
    payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    read_summary(payload)
    destination.write_bytes(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.source, args.destination)
