"""Reclassify a frozen national matcher replay by agreement on physical location."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
from hashlib import file_digest, sha256
import json
from math import floor, isfinite
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from research.geography.distance import haversine_m
from research.matching.normalize import fold, name_evidence, pin_key, state_key, tokens


SITE_RADIUS_M = 150
# At India's northern latitude limit, a 0.002-degree cell is still wider than 150 m.
SITE_CELL_DEGREES = 0.002
HOUSE = re.compile(r"^(?:(?:no|number|door|house|plot)\.?\s+)?(\d{1,5}[a-z]?(?:\s*[/\-]\s*\d{1,5}[a-z]?)?)[,\s]+(.+)", re.I)
NAME_LEVELS = {"strong", "moderate"}
CATEGORIES = ("high", "moderate", "single_source", "contested", "weak", "unmatched")
ORIGINAL_CONFLICTS = {"state_disagrees_with_pin", "base_geography_disagreement", "district_disagrees_with_pin"}


def read(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def json_lines(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def stage_rows(path):
    """Stream the compact JSON object written by the national matcher."""
    decoder = json.JSONDecoder()
    chunk_size = 1024 * 1024
    with path.open(encoding="utf-8") as stream:
        if stream.read(1) != "{":
            raise ValueError(f"Expected a matcher trace object in {path}")
        buffer = stream.read(chunk_size)
        start = 0
        while buffer[start:start + 1] != "}":
            while True:
                try:
                    key, end = decoder.raw_decode(buffer, start)
                    if buffer[end:end + 1] != ":":
                        raise ValueError("Missing matcher trace key separator")
                    row, end = decoder.raw_decode(buffer, end + 1)
                    if buffer[end:end + 1] not in {",", "}"}:
                        raise ValueError("Missing matcher trace row delimiter")
                    break
                except ValueError:
                    tail = stream.read(chunk_size)
                    if not tail:
                        raise
                    buffer, start = buffer[start:] + tail, 0
            yield key, row
            start = end + (buffer[end] == ",")
            if start == len(buffer):
                buffer, start = stream.read(chunk_size), 0
        if (buffer[start + 1:] + stream.read()).strip():
            raise ValueError("Trailing matcher trace data")


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def point(latitude, longitude):
    values = (latitude, longitude)
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
           for value in values) and 6 <= latitude <= 38 and 68 <= longitude <= 98:
        return values
    return None


def address_key(address, pin, city):
    """Allow a textual site match with a civic number, street text and postal context."""
    match = HOUSE.match(address.strip()) if isinstance(address, str) else None
    if not match or not (pin or city):
        return None
    house, street = match.groups()
    # Keep the first address component and preserve slash-number semantics.
    street = fold(street.split(",", 1)[0])
    return (re.sub(r"\s+", "", house).lower(), street) if street and len(street.split()) >= 2 else None


@dataclass(frozen=True)
class Reference:
    id: str
    name: str
    family: str | None
    source_record_id: str
    locator: str
    snapshot: str
    coordinates: tuple | None
    address: str | None
    pin: str | None
    city: str | None
    state: str | None
    name_tokens: tuple
    civic_address: tuple | None


@dataclass(frozen=True)
class Candidate:
    reference: Reference
    strength: int
    flags: tuple = ()
    votes: bool = True
    rank: int | None = None
    contradicts_base: bool = False


def same_site(left, right):
    """Two nearby records need compatible names; matching postal codes alone are insufficient."""
    if name_evidence(left.name_tokens, right.name_tokens)[0] not in NAME_LEVELS:
        return False
    if (left.state and right.state and left.state != right.state or
            left.pin and right.pin and left.pin != right.pin):
        return False
    if left.coordinates and right.coordinates:
        if haversine_m(*left.coordinates, *right.coordinates) > SITE_RADIUS_M:
            return False
        if left.civic_address and right.civic_address and left.civic_address[0] != right.civic_address[0]:
            return False
        return True
    return bool(left.civic_address and left.civic_address == right.civic_address and
                (left.pin and left.pin == right.pin or left.city and left.city == right.city))


def rank_candidate(candidate):
    return (-candidate.strength, candidate.rank or 10**9, candidate.reference.id)


def cluster_sites(candidates):
    sites = []
    by_cell = defaultdict(list)
    by_address = defaultdict(list)
    for candidate in sorted((candidate for candidate in candidates if candidate.strength), key=rank_candidate):
        reference = candidate.reference
        nearby = set(by_address.get(reference.civic_address, ()))
        if reference.coordinates:
            lat, lon = (floor(value / SITE_CELL_DEGREES) for value in reference.coordinates)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nearby.update(by_cell.get((lat + dx, lon + dy), ()))
        for index in sorted(nearby):
            site = sites[index]
            if all(same_site(reference, member.reference) for member in site):
                site.append(candidate)
                break
        else:
            if reference.coordinates:
                by_cell[lat, lon].append(len(sites))
            if reference.civic_address:
                by_address[reference.civic_address].append(len(sites))
            sites.append([candidate])
    return sites


def classify(candidates, original_conflict=False):
    """Infer a campus and count each source family at most once across sites."""
    sites = cluster_sites(candidates)

    preferences = defaultdict(dict)
    for index, site in enumerate(sites):
        for candidate in site:
            family = candidate.reference.family
            if family and candidate.votes:
                preferences[family][index] = max(candidate.strength, preferences[family].get(index, 0))
    families = defaultdict(list)
    split = []
    for family, strengths in sorted(preferences.items()):
        best_strength = max(strengths.values())
        best = [site for site, strength in strengths.items() if strength == best_strength]
        if len(best) == 1:
            families[best[0]].append(family)
        else:
            split.append(family)

    order = sorted(range(len(sites)), key=lambda index: (-len(families[index]), rank_candidate(sites[index][0])))
    winner = order[0] if order else None
    support = families[winner]
    dissent = sorted(family for index in order[1:] for family in families[index])
    other_votes = len(dissent) + len(split)
    candidate = sites[winner][0] if winner is not None else None
    leader = candidate.reference if candidate else None
    clean_support = {item.reference.family for item in (sites[winner] if winner is not None else ())
                     if item.votes and not item.contradicts_base} & set(support)
    if not candidates:
        category = "unmatched"
    elif original_conflict or (support and not clean_support) or (other_votes and len(support) <= max(
            (len(families[index]) for index in order[1:]), default=0)):
        category = "contested"
    elif len(support) >= 2:
        # Two unanimous families, or at least three families with 75% agreement.
        high = len(clean_support) >= 2 and (not other_votes or
                                           len(clean_support) >= max(3, 3 * other_votes))
        category = "high" if high else "moderate"
    elif len(support) == 1 and candidate.strength >= 2:
        category = "single_source" if not other_votes else "contested"
    else:
        category = "weak"
    return {
        "category": category,
        "leading_reference": leader.id if leader else None,
        "leading_name": leader.name if leader else None,
        "leading_coordinates": leader.coordinates if leader else None,
        "leading_address": leader.address if leader else None,
        "leading_source": {"record_id": leader.source_record_id, "locator": leader.locator,
                           "snapshot_id": leader.snapshot} if leader else None,
        "supporting_families": support,
        "supporting_families_without_base_conflicts": sorted(clean_support),
        "dissenting_families": dissent,
        "split_families": split,
        "original_conflict": original_conflict,
        "sites": [{"families": families[index], "references": [item.reference.id for item in sites[index]]}
                  for index in order],
        "other_reference_count": len(candidates) - sum(map(len, sites)),
        "flagged_references": {item.reference.id: item.flags for item in candidates if item.flags},
    }


def reference_index(batches, lineage):
    index = {}
    for path in batches:
        batch = read(path)
        families = {snapshot["snapshot_id"]: snapshot["source_family"] for snapshot in batch["source_snapshots"]}
        for row in batch["external_facilities"]:
            key = row["external_facility_id"]
            snapshot = row["snapshot_id"]
            family = families[snapshot]
            record_id = row["source_record_id"]
            if family == "overture_places_conflated":
                family = lineage.get(record_id)
            name, address = row["name_original"], row["address_original"]
            pin, city = pin_key(row["pin"]), fold(row["city"])
            if key in index:
                raise ValueError(f"Duplicate reference in {path}")
            index[key] = Reference(
                key, name, family, record_id, row["record_locator"], snapshot,
                point(row["latitude"], row["longitude"]), address, pin, city, state_key(row["state"]),
                tuple(tokens(name)), address_key(address, pin, city),
            )
    return index


def overture_families(projection):
    """Collapse Overture records with documented OSM or NHP lineage into that family."""
    families = {}
    for row in json_lines(projection):
        sources = [item for item in row["sources"] if item.get("provider") and item.get("record_id")
                   and item["provider"].lower() != "overture"]
        keys = {fold(f"{item['provider']} {item.get('dataset') or ''}") for item in sources}
        origins = set()
        if any(re.search(r"\b(?:osm|openstreetmap|geofabrik)\b", key) for key in keys):
            origins.add("osm")
        if any(re.search(r"\bnhp\b|\bnational health portal\b", key) for key in keys):
            origins.add("nhp")
        families[row["id"]] = next(iter(origins)) if len(origins) == 1 else (
            "overture" if sources and not origins else None)
    return families


def map_candidate(pair, reference):
    signals = pair["signals"]
    flags = tuple(pair["flags"])
    conflict = any(signals[key] == "conflict" for key in ("pin", "place", "state")) or "pin_conflict" in flags
    strength = 0
    if signals["name_level"] in NAME_LEVELS and not signals["non_hospital_type"] and (
            reference.coordinates or reference.civic_address):
        strength = 1
        if not conflict:
            if signals.get("premises", {}).get("campus_rank", 0) >= 2 or signals["distance_band"] == "same_site":
                strength = 3
            elif signals["distance_band"] == "near" or any(
                    signals[key] == "agree" for key in ("pin", "place", "address")):
                strength = 2
    return Candidate(reference, strength, flags, rank=pair["pre_cut_rank"], contradicts_base=conflict)


def insurer_candidate(link, reference):
    usable = link["serious"] and (reference.coordinates or reference.civic_address)
    shared = link["vf_shared_iffco_lineage"] or link["other_vf_insurer_or_tpa_lineage_cue"]
    strength = 0
    conflict = link["geography_or_mixed_conflict"] or link["branch_conflict"]
    if usable:
        strength = 1 if conflict else min(3, max(1, link["evidence_tier"]))
    return Candidate(reference, strength, tuple(link["flags"]), not shared, link["insurer_only_pre_cut_rank"], conflict)


def run(replay, occurrences_path, batches, projection, output, insurer_links=None, control=None,
        base=None, joint_occurrences=None):
    occurrences = list(json_lines(occurrences_path))
    if base:
        originals = read(base)
        if len(originals) != len(occurrences) or any(
                original["facility_id"] != row["facility_id"] or
                sha256(encoded(original["source_row"]).rstrip("\n").encode()).hexdigest() !=
                row["original_payload_sha256"] for original, row in zip(originals, occurrences, strict=True)):
            raise ValueError("Prepared base and occurrence payloads do not reconcile")
    representatives = {}
    for row in occurrences:
        representatives.setdefault(row["retrieval_representative"], row)
    if len({row["facility_id"] for row in occurrences}) != len(occurrences):
        raise ValueError("Occurrence keys must be unique")
    paths = [replay, occurrences_path, projection, *batches]
    paths.extend(path for path in (insurer_links, control, base, joint_occurrences) if path)
    inputs = {path.as_posix(): digest(path) for path in paths}
    old_outcomes = {}
    if joint_occurrences:
        for row, frozen in zip(occurrences, json_lines(joint_occurrences), strict=True):
            if (row["facility_id"], row["retrieval_representative"], row["original_payload_sha256"]) != (
                    frozen["facility_id"], frozen["representative"], frozen["original_payload_sha256"]):
                raise ValueError("Frozen joint outcomes and occurrence payloads do not reconcile")
            old_outcomes[row["facility_id"]] = frozen["outcomes"]["joint"]
    references = reference_index(batches, overture_families(projection))
    insurer = defaultdict(list)
    if insurer_links:
        for link in json_lines(insurer_links):
            insurer[link["representative"]].append(insurer_candidate(
                link, references[link["insurer_external_facility_id"]]))
    previous = {}
    if control:
        for representative, stage in stage_rows(control):
            previous[representative] = stage["pre_cut"]
        if previous.keys() != representatives.keys():
            raise ValueError("Control trace and occurrences do not reconcile")

    classified = {}
    pair_counts = Counter()
    for representative, stage in stage_rows(replay):
        original = representatives[representative]
        if representative in classified:
            raise ValueError("Duplicate representative in matcher trace")
        pairs = stage["pre_cut"]
        ids = {pair["external_facility_id"] for pair in pairs}
        if len(ids) != len(pairs):
            raise ValueError("Duplicate candidate in matcher trace")
        historical = [pair for pair in previous.pop(representative, []) if pair["external_facility_id"] not in ids]
        candidates = [map_candidate(pair, references[pair["external_facility_id"]]) for pair in pairs + historical]
        supplemental = insurer.pop(representative, [])
        candidates.extend(supplemental)
        pair_counts.update(joint=len(pairs), historical=len(historical), insurer=len(supplemental))
        original_conflict = bool(ORIGINAL_CONFLICTS.intersection(original["input_problems"]) or
                                 original["branch_evidence"]["mixed_campus"] or
                                 original["branch_evidence"]["postal_state_disagreement"])
        classified[representative] = classify(candidates, original_conflict)
    if classified.keys() != representatives.keys() or insurer:
        raise ValueError("Candidate and occurrence representatives do not reconcile")

    totals, by_state, transitions = Counter(), defaultdict(Counter), defaultdict(Counter)
    if output.exists():
        raise FileExistsError(output)
    with TemporaryDirectory(dir=output.parent) as temp:
        interim = Path(temp)
        with (interim / "occurrences.jsonl.gz").open("xb") as raw, gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            for row in occurrences:
                representative = row["retrieval_representative"]
                result = classified[representative]
                category = result["category"]
                totals[category] += 1
                by_state[row["state"]][category] += 1
                old_outcome = old_outcomes.get(row["facility_id"])
                if old_outcome:
                    transitions[old_outcome][category] += 1
                stream.write(encoded(dict(result, facility_id=row["facility_id"],
                                          representative=representative,
                                          state=row["state"],
                                          previous_joint_outcome=old_outcome,
                                          original_payload_sha256=row["original_payload_sha256"])).encode("utf-8"))
        report = {"occurrences": len(occurrences), "representatives": len(representatives),
                  "candidate_pairs": pair_counts, "categories": {key: totals[key] for key in CATEGORIES},
                  "by_state": by_state, "joint_retrieval_to_consensus": transitions,
                  "site_radius_m": SITE_RADIUS_M, "input_sha256": inputs,
                  "occurrence_output_sha256": digest(interim / "occurrences.jsonl.gz")}
        (interim / "aggregate.json").write_text(encoded(report), encoding="utf-8", newline="\n")
        output.mkdir()
        for file in interim.iterdir():
            file.rename(output / file.name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("replay", "occurrences", "projection", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--reference", type=Path, action="append", required=True)
    for name in ("insurer-links", "control", "base", "joint-occurrences"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    report = run(args.replay, args.occurrences, args.reference, args.projection, args.output,
                 args.insurer_links, args.control, args.base, args.joint_occurrences)
    print(encoded({key: report[key] for key in ("occurrences", "candidate_pairs", "categories")}), end="")


if __name__ == "__main__":
    main()
