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
from research.matching.national import STATES
from research.matching.premises import MISSING


SITE_RADIUS_M = 150
# At India's northern latitude limit, a 0.002-degree cell is still wider than 150 m.
SITE_CELL_DEGREES = 0.002
HOUSE = re.compile(r"^(?:(?:no|number|door|house|plot)\.?\s+)?(\d{1,5}[a-z]?(?:\s*[/\-]\s*\d{1,5}[a-z]?)?)[,\s]+(.+)", re.I)
NAME_LEVELS = {"strong", "moderate"}
CATEGORIES = ("high", "moderate", "single_source", "contested", "weak", "unmatched")
LOCATION_STATUSES = ("campus_located", "area_located", "unresolved")
MAP_SOURCES = {"hot_osm_health", "overture_places"}
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
    location_basis: str | None = None
    plausible_branch: bool = False
    branch_conflict: bool = False


@dataclass(frozen=True)
class RegistryBranches:
    supporting_references: set[str]
    competing_references: set[str]


def same_site(left, right, address_agreement=None):
    """Two nearby records need compatible names; matching postal codes alone are insufficient."""
    if name_evidence(left.name_tokens, right.name_tokens)[0] not in NAME_LEVELS:
        return False
    if (left.state and right.state and left.state != right.state or
            left.pin and right.pin and left.pin != right.pin):
        return False
    if left.coordinates and right.coordinates:
        if haversine_m(*left.coordinates, *right.coordinates) > SITE_RADIUS_M:
            return False
        if address_agreement is False:
            return False
        if left.civic_address and right.civic_address and left.civic_address[0] != right.civic_address[0]:
            return False
        return True
    address_match = (left.civic_address and left.civic_address == right.civic_address
                     if address_agreement is None else address_agreement)
    return bool(address_match and
                (left.pin and left.pin == right.pin or left.city and left.city == right.city))


def rank_candidate(candidate):
    return (-candidate.strength, candidate.rank or 10**9, candidate.reference.id)


def directory_address(address):
    number, street = address
    return number, re.sub(r"\brd\b", "road", re.sub(r"\bst\b", "street", street))


def same_directory_site(left, right):
    address_agreement = (directory_address(left.civic_address) == directory_address(right.civic_address)
                         if left.civic_address and right.civic_address else None)
    return same_site(left, right, address_agreement)


def cluster_sites(candidates, site_match=same_site, address_key_fn=None):
    sites = []
    by_cell = defaultdict(list)
    by_address = defaultdict(list)
    for candidate in sorted(candidates, key=rank_candidate):
        reference = candidate.reference
        address = reference.civic_address
        if address and address_key_fn:
            address = address_key_fn(address)
        nearby = set(by_address.get(address, ()))
        if reference.coordinates:
            lat, lon = (floor(value / SITE_CELL_DEGREES) for value in reference.coordinates)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nearby.update(by_cell.get((lat + dx, lon + dy), ()))
        for index in sorted(nearby):
            site = sites[index]
            if all(site_match(reference, member.reference) for member in site):
                site.append(candidate)
                break
        else:
            if reference.coordinates:
                by_cell[lat, lon].append(len(sites))
            if address:
                by_address[address].append(len(sites))
            sites.append([candidate])
    return sites


def area_name(value):
    return bool(value and value not in MISSING and value not in {"india", "in"}
                and (state_key(value) not in STATES or value in {"delhi", "chandigarh", "puducherry"}))


def original_area(original):
    evidence = original["branch_evidence"]
    if (evidence["postal_state_disagreement"] or
            (ORIGINAL_CONFLICTS | {"address_pin_disagrees"}).intersection(original["input_problems"])):
        return None
    if len(evidence["pins"]) == 1 and evidence["pins"] == evidence["postal_pins"]:
        return {"kind": "pin", "value": evidence["pins"][0]}
    for kind, field in (("locality", "localities"), ("city", "cities"), ("district", "districts")):
        labels = evidence[field]
        if len(labels) == 1 and area_name(labels[0]):
            return {"kind": kind, "value": labels[0]}
    return None


def matched_site_address(candidates):
    """Find a civic address shared by two source families in the same site."""
    families = defaultdict(set)
    for candidate in candidates:
        ref = candidate.reference
        if ref.civic_address and candidate.votes and ref.family:
            for kind, value in (("pin", ref.pin), ("city", ref.city)):
                if value:
                    families[(directory_address(ref.civic_address), kind, value)].add(ref.family)
    return any(len(sources) >= 2 for sources in families.values())


def directory_location(candidates, original, original_conflict, supplement):
    """Assign directory precision while keeping reviewed identity separate."""
    plausible = cluster_sites((item for item in candidates if item.plausible_branch), same_directory_site,
                              directory_address)
    source_sites = defaultdict(set)
    for index, site in enumerate(plausible):
        for item in site:
            ref = item.reference
            source_sites[ref.family or ref.snapshot].add(index)

    if not original_conflict:
        for index, site in enumerate(plausible):
            clean = [item for item in site if not (item.contradicts_base or item.branch_conflict)]
            anchors = [item for item in clean if item.location_basis]
            address_corroboration = bool(supplement and any(
                item.reference.id in supplement.supporting_references for item in clean))
            if not (anchors or address_corroboration or matched_site_address(clean)):
                continue
            rivals = {family for family, indexes in source_sites.items() if indexes - {index}}
            if supplement and any(item.reference.id in supplement.competing_references for item in site):
                rivals.add("nhp")
            support = {item.reference.family for item in clean if item.votes and item.reference.family}
            if address_corroboration:
                support.add("nhp")
            support -= rivals
            if rivals and (len(rivals) > 1 or len(support) <= len(rivals)):
                continue
            preferred = min(anchors or clean,
                            key=lambda item: (item.location_basis != "matching_branch_address",
                                              *rank_candidate(item)))
            ref = preferred.reference
            return {
                "status": "campus_located",
                "basis": preferred.location_basis or "matching_branch_address",
                "reference": ref.id,
                "address": ref.address,
                "coordinates": ref.coordinates,
                "supporting_families": sorted(support),
                "competing_families": sorted(rivals),
            }

    area = original_area(original) if original is not None else None
    if area is None and not original_conflict:
        items = [item for site in plausible for item in site]
        refs = [item.reference for item in items] if any(
            not (item.contradicts_base or item.branch_conflict) for item in items) else []
        for kind in ("pin", "city"):
            values = {getattr(ref, kind) for ref in refs}
            if len(values) == 1 and (value := next(iter(values))) and (kind == "pin" or area_name(value)):
                area = {"kind": kind, "value": value}
                break
    if area:
        return {"status": "area_located", "basis": area["kind"], "area": area["value"]}
    return {"status": "unresolved", "basis": "insufficient_or_conflicting_geography"}


def classify(candidates, original_conflict=False, original=None, supplement=None):
    """Infer a campus and count each source family at most once across sites."""
    sites = cluster_sites(item for item in candidates if item.strength)

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
        "directory_location": directory_location(
            candidates, original, original_conflict or bool(original and
                                                             "address_pin_disagrees" in original["input_problems"]),
            supplement),
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
    premises = signals.get("premises", {})
    branch_conflict = any(premises.get(key) for key in (
        "premises_conflict", "street_conflict", "branch_qualifier_conflict",
        "mixed_campus_description", "own_postal_state_conflict", "multiple_observed_pins"))
    branch_address = premises.get("campus_rank", 0) >= 2
    same_area = any(signals[key] == "agree" for key in ("pin", "place", "address"))
    close = signals["distance_band"] in ("same_site", "near")
    strength = 0
    basis = None
    name_qualifies = signals["name_level"] in NAME_LEVELS and not signals["non_hospital_type"]
    if name_qualifies and (reference.coordinates or reference.civic_address):
        strength = 1
        if not conflict:
            if branch_address or signals["distance_band"] == "same_site":
                strength = 3
            elif close or same_area:
                strength = 2
    if name_qualifies and not conflict:
        if branch_address and reference.address:
            basis = "matching_branch_address"
        elif (signals["external_source_key"] in MAP_SOURCES and reference.coordinates
                and not premises.get("competing_coordinates")
                and (same_area or signals["distance_band"] == "same_site")):
            basis = "named_map_listing"
    return Candidate(reference, strength, flags, rank=pair["pre_cut_rank"], contradicts_base=conflict,
                     location_basis=basis, plausible_branch=bool(basis or strength and (same_area or close)),
                     branch_conflict=branch_conflict)


def insurer_candidate(link, reference):
    usable = link["serious"] and (reference.coordinates or reference.civic_address)
    shared = link["vf_shared_iffco_lineage"] or link["other_vf_insurer_or_tpa_lineage_cue"]
    strength = 0
    conflict = link["geography_or_mixed_conflict"] or link["branch_conflict"]
    if usable:
        strength = 1 if conflict else min(3, max(1, link["evidence_tier"]))
    matched_address = link["premises_and_street"] or link["premises_and_locality"]
    basis = "matching_branch_address" if link["serious"] and matched_address and reference.address and not conflict else None
    plausible = bool(basis or usable and (matched_address or link["printed_pin_relation"] == "agree" or strength >= 2))
    return Candidate(reference, strength, tuple(link["flags"]), not shared, link["insurer_only_pre_cut_rank"], conflict,
                     location_basis=basis, plausible_branch=plausible)


def registry_branches(path, occurrences):
    """Reuse the pinned official NHP and blood-host comparison as one lineage."""
    supplements = {}
    for row, comparison in zip(occurrences, json_lines(path), strict=True):
        representative = row["retrieval_representative"]
        if (row["facility_id"], representative, row["state"]) != (
                comparison["occurrence_key"], comparison["representative"], comparison["state"]):
            raise ValueError("Registry comparison and original occurrences do not reconcile")
        support, rivals = set(), set()
        for detail in comparison.get("details", []):
            if detail["source"] not in {"nhp_official_only", "blood"}:
                raise ValueError("Unexpected registry comparison source")
            matched = detail["compatible_incumbent_keys"] if not detail["original_conflict"] else []
            if detail["source"] == "nhp_official_only":
                support.update(matched)
            if matched or detail["alternative"] or (detail["leader_conflict"] and
                    comparison["outcome"] == "ambiguous_host_or_branch"):
                rivals.update(detail["incompatible_serious_incumbent_keys"])
        branches = RegistryBranches(support, rivals)
        if supplements.setdefault(representative, branches) != branches:
            raise ValueError("Identical occurrences disagree in the registry comparison")
    return supplements


def run(replay, occurrences_path, batches, projection, output, insurer_links=None, control=None,
        base=None, joint_occurrences=None, registry_comparison=None):
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
    paths.extend(path for path in (insurer_links, control, base, joint_occurrences, registry_comparison) if path)
    inputs = {path.as_posix(): digest(path) for path in paths}
    supplements = registry_branches(registry_comparison, occurrences) if registry_comparison else {}
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
        classified[representative] = classify(candidates, original_conflict, original,
                                              supplements.get(representative))
    if classified.keys() != representatives.keys() or insurer:
        raise ValueError("Candidate and occurrence representatives do not reconcile")

    totals, by_state, transitions = Counter(), defaultdict(Counter), defaultdict(Counter)
    locations, location_bases, locations_by_state = Counter(), defaultdict(Counter), defaultdict(Counter)
    campus_competition = Counter()
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
                location = result["directory_location"]
                status = location["status"]
                locations[status] += 1
                location_bases[status][location["basis"]] += 1
                locations_by_state[row["state"]][status] += 1
                if status == "campus_located":
                    campus_competition["outvoted_one" if location["competing_families"] else "no_rival"] += 1
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
                  "location_statuses": {key: locations[key] for key in LOCATION_STATUSES},
                  "location_bases": location_bases,
                  "campus_competition": {key: campus_competition[key] for key in ("no_rival", "outvoted_one")},
                  "location_by_state": {
                      state: {status: counts[status] for status in LOCATION_STATUSES}
                      for state, counts in locations_by_state.items()},
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
    for name in ("insurer-links", "control", "base", "joint-occurrences", "registry-comparison"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    report = run(args.replay, args.occurrences, args.reference, args.projection, args.output,
                 args.insurer_links, args.control, args.base, args.joint_occurrences, args.registry_comparison)
    print(encoded({key: report[key] for key in ("occurrences", "candidate_pairs", "categories", "location_statuses")}),
          end="")


if __name__ == "__main__":
    main()
