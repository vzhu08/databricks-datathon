"""Replay the scoped A and H source predicates in memory for B3."""

from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
import sys
import zipfile

from . import core, feeds

ADDRESS_EDITION = "loc270-a-rival-address-v1"
ADDRESS_PIN = "9bdb5a057d5bcbd6b967a5896544b74718966a300e51070b741412b64b1b24d7"
ARRIVAL_EDITION = "loc270-h-arrival-v1"
ARRIVAL_PIN = "181463e49223563721f1bd1517e693a435f07cde92179cf0db9d56c09ebfec3a"
NHP_PIN = "55b74925654b8287f4a6cb82f4ef843437ae3dff0a752846af760c4da12a5586"
VF_OCC_FILE = "team-intake-20261121/recipient-160/run-01/D-baseline/source/occurrences.jsonl.gz"


def load_method(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counts_for(keys, frame):
    count = Counter(frame[key]["baseline_directory_status"] for key in keys)
    return {status: count[status] for status in core.FROZEN}


def precisions_for(keys, frame):
    count = Counter(frame[k]["area"]["precision"] for k in keys
                    if frame[k]["baseline_directory_status"] == "area_located")
    return {p: count[p] for p in ("postal_area", "city", "locality")}


def address(frame, nationwide, method):
    names = ("shortlist.py", "rivals.py", "address_replay.py", "native_inventory.py", "short-counts.json")
    manifest, receipt = feeds.package(method, ADDRESS_EDITION, ADDRESS_PIN, names)
    pins = manifest["input_sha256"]
    vf = core.checked(nationwide / VF_OCC_FILE, core.D_OCC)
    issuer = core.checked(nationwide / "windows-nabh-173/readback/nabh.sqlite", pins["issuer"])
    core.need(pins["vf"] == core.D_OCC and pins["decisions"] == core.D_DECISIONS, "A's frozen national frame differs")
    before = sys.path.copy()
    try:
        sys.path.insert(0, str(method.resolve()))
        m = load_method(method / "shortlist.py", "loc270_a_shortlist")
        chosen, tied = set(), set()
        for key, issuer_ids, original, source in m.iter_shortlist(issuer, vf, method):
            core.need(key in frame and key not in chosen and issuer_ids, "A's shortlist has an orphan or repeated original")
            chosen.add(key)
            if m.tied_streets(original) & m.tied_streets(source):
                tied.add(key)
    finally:
        sys.path[:] = before
    published = core.read(method / "short-counts.json", receipt["verified_members"]["short-counts.json"])["counts"]
    core.need(len(chosen) == published["originals"] == 16 and len(tied) == published["specific_number_tied_to_street"] == 3,
              "A's shortlist margins did not reproduce")
    return chosen, {
        "input": receipt, "source_family": "NABH registry",
        "shortlist_count_by_directory_status": counts_for(chosen, frame),
        "tied_number_street_count_by_directory_status": counts_for(tied, frame),
        "shortlist_count_by_exact_area_precision": precisions_for(chosen, frame),
        "tied_number_street_count_by_exact_area_precision": precisions_for(tied, frame),
        "reviewed_exact_location_upgrades_in_this_source_screen": 0,
    }


def nhp_records(nationwide):
    folder = nationwide.parent / "nhp-181/readback"
    archive = core.read(folder / "manifest.json", NHP_PIN)
    captured = archive["archive"]
    file = core.checked(folder / captured["filename"], captured)
    name = "facility-locators.jsonl.gz"
    member, = (m for m in archive["members"] if m["filename"] == name)
    with zipfile.ZipFile(file) as z:
        content = z.read(name)
    core.need(len(content) == member["bytes"] and hashlib.sha256(content).hexdigest() == member["sha256"],
              "official NHP member did not match")
    rows = [json.loads(line) for line in gzip.decompress(content).splitlines()]
    core.need(len(rows) == member["count"] == len({row["sr_no"] for row in rows}) == 30273,
              "NHP listing count changed")
    return rows, member["sha256"]


def arrival(frame, nationwide, method):
    names = ("profile.py", "aggregate.json")
    _, receipt = feeds.package(method, ARRIVAL_EDITION, ARRIVAL_PIN, names)
    h = load_method(method / "profile.py", "loc270_h_profile")
    source_rows, source_pin = nhp_records(nationwide)
    base = core.rows(core.checked(nationwide / VF_OCC_FILE, core.D_OCC))
    source_index, states = defaultdict(list), defaultdict(set)
    for (name, pin), row, features in h.candidates(source_rows):
        source_index[name, pin].append((row, features))
        state = h.name_key(row["State"])
        if state:
            states[name, state].add(pin)
    published = core.read(method / "aggregate.json", receipt["verified_members"]["aggregate.json"])
    core.need(source_pin == published["nhp_member_sha256"] and published["base_sha256"] == core.BASE_PREPARED,
              "official arrival sources differ")
    matched, identifiers, by_precision, national, area = set(), set(), defaultdict(Counter), Counter(), Counter()
    flags = tuple(published["vf_occurrences_with_any_candidate_flag"])
    for key, item in zip(frame, base, strict=True):
        original = item["original"]
        core.need(original["facility_id"] == key, "H source occurrence order shifted")
        row = original["source_row"]
        name, pin = h.name_key(row["name"]), h.pin_key(row["address_zipOrPostcode"])
        hits = source_index.get((name, pin), [])
        if not hits:
            national["no_exact_name_pin"] += 1
            continue
        identifiers.update(source["sr_no"] for source, _ in hits)
        matched.add(key)
        facts = {
            "exact_name_pin_occurrences": 1, "issuer_pairs": len(hits),
            "multiple_issuer_rows_at_name_pin" if len(hits) > 1 else "one_issuer_row_at_name_pin": 1,
            "same_issuer_name_at_multiple_pins_in_state": any(
                len(states[name, h.name_key(source["State"])]) > 1 for source, _ in hits),
            **{flag: any(f[flag] for _, f in hits) for flag in flags},
        }
        national.update(facts)
        if frame[key]["baseline_directory_status"] == "area_located":
            area.update(facts)
            by_precision[frame[key]["area"]["precision"]].update(facts)
    for field in ("vf_candidate_counts", "vf_occurrences_with_any_candidate_flag"):
        core.need(all(national[k] == v for k, v in published[field].items()), "H source margins changed")
    core.need(len(identifiers) == published["distinct_linked_issuer_rows"] and
              sum(map(len, source_index.values())) == published["source_rows_indexed"],
              "H issuer margins changed")
    keys = ("exact_name_pin_occurrences", "issuer_pairs", "multiple_issuer_rows_at_name_pin",
            "same_issuer_name_at_multiple_pins_in_state", *flags)
    return matched, {
        "input": receipt, "publisher_edition_sha256": NHP_PIN, "source_family": "MoHFW / NHP",
        "national": {k: national[k] for k in keys}, "actual_area": {k: area[k] for k in keys},
        "actual_area_by_precision": {
            p: {k: by_precision[p][k] for k in keys} for p in ("postal_area", "city", "locality")},
        "reviewed_patient_entrance_promotions": 0,
    }
