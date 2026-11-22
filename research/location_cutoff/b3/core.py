"""Validate and project the exact directory edition without exposing raw source rows."""

import gzip
from collections import Counter
import hashlib
import json
import re

from research.matching.national import NO_STATE, NOT_A_STATE, STATES
from research.matching.normalize import state_key
from research.matching.premises import MISSING

ISSUE = "https://github.com/vzhu08/databricks-datathon/issues/270"
INTAKE = "dbfs:/Volumes/workspace/default/datathon_vf_research_intake"
MATCHING = "dbfs:/Volumes/workspace/datathon_acquisition/matching_inputs"
V4 = "f444e4dda3c8f9c9f1efc7738a03c341dc1a3c67ec267e6b777a8baae8b5a2d8"
V4_AGG = "b7fcc924faf9f2b77126c3464d6f102882a4388b7e2b5a8cd69733f8479f739e"
V5 = "3cecb445a5fecdddefa42eff500864ee952a4f08290fede3902e2812f3af3b2c"
V5_AGG = "23b0cde51f6c6f773276a725d8ce9dcf2692c79ebf3765310a28d2470b5523be"
D_MANIFEST = "2f3fc37e591ee834a839d20e4211cb5f3ecc71defaacdcce826615f4e0923b9a"
D_OCC = "a5cdc3effbc923d3ab444db57bf5d5e9b25147446f0de5f9c40c355e20fdcdcf"
D_DECISIONS = "51dabdfd56af0d2e97afe6cd157308665b348517291fd8cfcbe2b1e92c3e4f6e"
LOC04 = "d7e61f271751083f9b000ecb3dcce5fb32b35828ba1e771e76d0d9db5ad3f00c"
BASE_PREPARED = "27e4a79de42ec56c76cc676ed45494a52497d179858bc50549a461434c45e9d8"
PAYLOAD_MULTISET = "30d32fa927f5d43753ea6d42f3685ea62e1b416a6cffce7e11ebd1d83b905ca6"
SERVICES = ("dialysis", "mri", "trauma_care")
FROZEN = {"campus_located": 2524, "area_located": 7418, "unresolved": 146}
BASIS = {"area_located": {"pin": 6988, "city": 328, "locality": 102},
         "campus_located": {"named_map_listing": 2435, "matching_branch_address": 89},
         "unresolved": {"insufficient_or_conflicting_geography": 146}}
PRECISIONS = ("locality", "postal_area", "city", "district", "unknown")
CONFLICTS = {"state_disagrees_with_pin", "base_geography_disagreement", "district_disagrees_with_pin",
             "address_pin_disagrees"}
PIN_PATTERN = re.compile(r"[1-9][0-9]{5}")
SENSITIVE_OR_POINT = re.compile(r"@|(?:https?://|www\.)|[0-9]{8,}|\d+[.]\d{3,}\s*[, ]\s*-?\d+[.]\d{3,}", re.I)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def pin(path):
    with path.open("rb") as stream:
        return {"bytes": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def checked(path, expected):
    got = pin(path)
    if isinstance(expected, str):
        need(got["sha256"] == expected, f"invalid SHA-256 for {path.name}")
    else:
        need(got == {k: expected[k] for k in ("bytes", "sha256")}, f"invalid SHA-256 or length for {path.name}")
    return path


def read(path, expected):
    return json.loads(checked(path, expected).read_bytes())


def rows(path):
    reader = gzip.open if path.suffix == ".gz" else open
    with reader(path, "rt", encoding="utf-8") as handle:
        yield from map(json.loads, handle)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def write_rows(path, records):
    with path.open("wb") as stream:
        count = 0
        for record in records:
            stream.write(encode(record) + b"\n")
            count += 1
    return {**pin(path), "records": count}


def fallback_area(original):
    """Use only the original-area witness rule from the pinned v4 producer."""
    evidence = original["branch_evidence"]
    if evidence["postal_state_disagreement"] or CONFLICTS.intersection(original["input_problems"]):
        return None
    if len(evidence["pins"]) == 1 and evidence["pins"] == evidence["postal_pins"]:
        return {"kind": "pin", "value": evidence["pins"][0], "fields": ["pins", "postal_pins"]}
    for kind, field in (("locality", "localities"), ("city", "cities"), ("district", "districts")):
        values = evidence[field]
        if len(values) != 1:
            continue
        value = values[0]
        if (value and value not in MISSING | {"india", "in"}
                and (state_key(value) not in STATES or value in {"delhi", "chandigarh", "puducherry"})):
            return {"kind": kind, "value": value, "fields": [field]}
    return None


def area_projection(directory, original):
    status = directory["status"]
    witness = fallback_area(original)
    if status == "area_located":
        need(witness is not None and (witness["kind"], witness["value"]) ==
             (directory["basis"], directory["area"]), "frozen area witness did not reproduce")
    if status == "unresolved":
        need(witness is None, "withheld area requires a separate adjudication")
    if witness is None:
        return {"precision": "unknown", "label": None, "evidence": None,
                "disposition": "no_defensible_area_in_frozen_original_evidence"}
    value, kind = witness["value"], witness["kind"]
    need(isinstance(value, str) and bool(value) and not SENSITIVE_OR_POINT.search(value), "invalid area label")
    if kind == "pin":
        need(PIN_PATTERN.fullmatch(value) is not None, "invalid postal area")
    return {"precision": "postal_area" if kind == "pin" else kind, "label": value,
            "evidence": {"edition": "loc-04-campus-point-handoff-v3", "branch_evidence_fields": witness["fields"],
                         "families": ["VF original", "India Post v0"] if kind == "pin" else ["VF original"]},
            "disposition": "area_only"}


def load(nationwide):
    compare = nationwide / "loc-campus-directory-v4-databricks/readback"
    v4_manifest = read(compare / "manifest.json", V4_AGG)
    need(v4_manifest["local_occurrence_output_sha256"] == V4, "directory ledger pin mismatch")
    v4_summary = read(compare / "aggregate.json", v4_manifest["files"]["aggregate.json"])
    need(v4_summary["location_statuses"] == FROZEN, "frozen national margins changed")
    loc04_name = "loc-04-campus-point-handoff-v3/handoff-v3/occurrences.jsonl.gz"
    need(v4_manifest["input_sha256"][f"data/local/nationwide/{loc04_name}"] == LOC04, "original area source changed")
    origin = nationwide / "team-intake-20261121/recipient-160/run-01/D-baseline/source"
    d = read(origin / "manifest.json", D_MANIFEST)
    d_occ, d_decisions = (d["files"][name] for name in ("occurrences.jsonl.gz", "decisions.jsonl.gz"))
    need(d_occ["sha256"] == D_OCC and d_decisions["sha256"] == D_DECISIONS, "frozen D frame changed")
    base = checked(nationwide / "vincent-source-20261121/prepared/base.json", BASE_PREPARED)
    streams = [
        checked(nationwide / "loc-campus-directory-v4/occurrences.jsonl.gz", V4),
        checked(nationwide / "loc-campus-directory-v5/occurrences.jsonl.gz", V5),
        checked(nationwide / loc04_name, LOC04),
        checked(origin / "occurrences.jsonl.gz", d_occ),
    ]
    frame, serialized, upstream, bases = {}, [], Counter(), Counter()
    for ordinal, (old, corrected, org, item) in enumerate(zip(*(rows(p) for p in streams), strict=True)):
        identity, original = item["identity"], item["original"]
        key = original["facility_id"]
        raw = original["source_row"]
        payload_bytes = encode(raw)
        digest = hashlib.sha256(payload_bytes).hexdigest()
        need(key not in frame and all(r["facility_id"] == key for r in (old, corrected, org, identity)),
             "occurrence key or order changed")
        need(all(r["original_payload_sha256"] == digest for r in (old, corrected, org, identity)),
             "original payload differs")
        need(org["input_ordinal_zero_based"] == identity["input_ordinal_zero_based"] == ordinal,
             "original ordinal shifted")
        uid = raw["unique_id"]
        need(uid and org["original_upstream_id"] == identity["original_upstream_id"] == uid, "upstream identifier shifted")
        state = old["state"]
        need(state in STATES | {NO_STATE, NOT_A_STATE} and state == corrected["state"] == identity["state"] == org["state"],
             "frozen geography shifted")
        a, b = old["directory_location"], corrected["directory_location"]
        fields = ("status", "basis", "area")
        need(tuple(a.get(f) for f in fields) == tuple(b.get(f) for f in fields), "v5 changes baseline precision")
        stored = area_projection(a, org)
        frame[key] = {"occurrence_key": key, "original_payload_sha256": digest, "original_state": state,
                      "baseline_directory_status": a["status"], "baseline_directory_basis": a["basis"],
                      "area": stored, "verified_premises": None, "verified_patient_entrance": None}
        serialized.append(payload_bytes)
        upstream[uid] += 1
        bases[a["status"], a["basis"]] += 1
    baseline_bases = {(status, basis): count for status, by in BASIS.items() for basis, count in by.items()}
    need(len(frame) == 10088 and bases == baseline_bases, "frozen occurrence or basis count changed")
    need(hashlib.sha256(b"[" + b",".join(sorted(serialized)) + b"]").hexdigest() == PAYLOAD_MULTISET,
         "unexpected payload multiset")
    need(len(upstream) == 10077 and Counter(upstream.values()) == {1: 10066, 2: 11}
         and Counter(Counter(r["original_payload_sha256"] for r in frame.values()).values()) == {1: 10066, 2: 11},
         "duplicate occurrence population changed")
    decision_path = checked(origin / "decisions.jsonl.gz", d_decisions)
    observed = set()
    for row in rows(decision_path):
        key, service = row["occurrence_key"], row["service"]
        need((key, service) not in observed and key in frame and service in SERVICES and row["status"] == "unconfirmed"
             and row["state"] == frame[key]["original_state"], "frozen decision key, status or geography shifted")
        observed.add((key, service))
    need(len(observed) == 30264, "frozen decision count changed")
    return frame, {"prepared_vf_v0": pin(base), "original_payload_multiset_sha256": PAYLOAD_MULTISET,
                   "directory_v4_manifest_sha256": V4_AGG,
                   "directory_v4_local_ledger_sha256": V4, "directory_v5_local_ledger_sha256": V5,
                   "directory_v5_impact_manifest_sha256": V5_AGG, "loc04_original_area_input_sha256": LOC04,
                   "d_manifest_sha256": D_MANIFEST, "frozen_occurrence_file": d_occ, "frozen_decision_file": d_decisions,
                   "source_receipts": {
                       "directory_shared_aggregate": f"{INTAKE}/loc-campus-directory-v4-{V4_AGG}/manifest.json",
                       "directory_correction_aggregate": f"{INTAKE}/loc-campus-directory-v5-impact-{V5_AGG}/manifest.json",
                       "frozen_team_occurrences_decisions": f"{MATCHING}/service-ledger-163-collectors-v1-191fbfae50f42c32e14faacf064d7b72bcc67b83b62b7f61f850d4e477cc2fa8/manifest.json",
                       "directory_scope": "https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7075486841",
                   }}


def aggregate(frame):
    by_geography = {key: Counter() for key in sorted(STATES | {NO_STATE, NOT_A_STATE})}
    by_baseline = {status: Counter() for status in FROZEN}
    membership = Counter()
    for row in frame.values():
        status, precision = row["baseline_directory_status"], row["area"]["precision"]
        by_geography[row["original_state"]][status, precision] += 1
        by_baseline[status][precision] += 1
        if status == "area_located":
            membership[row["original_payload_sha256"]] += 1

    def cells(counts):
        return {key: counts[key] for key in PRECISIONS}

    totals = Counter()
    for counts in by_baseline.values():
        totals.update(counts)
    need(len(membership) == 7413 and Counter(membership.values()) == {1: 7408, 2: 5}, "area duplicate membership changed")
    geography = {}
    for location, counts in by_geography.items():
        total = counts.total()
        geography[location] = {"original_occurrences": total,
                               "baseline_directory_and_fallback": {
                                   status: {p: counts[status, p] for p in PRECISIONS} for status in FROZEN},
                               "frozen_unconfirmed_by_service": dict.fromkeys(SERVICES, total)}
    need(sum(geography[s]["original_occurrences"] for s in (NO_STATE, NOT_A_STATE)) == 448,
         "missing geography count changed")
    return {"population": {"original_occurrences": 10088, "distinct_upstream_ids": 10077, "identical_pairs": 11,
                           "unknown_original_state_ut_occurrences": 448, "frozen_unconfirmed_decisions": 30264,
                           "unconfirmed_per_service": dict.fromkeys(SERVICES, 10088), "service_transitions": 0},
            "frozen_directory": {"by_status": FROZEN, "by_status_and_basis": BASIS, "area_original_occurrences": 7418,
                                 "area_distinct_payload_groups": len(membership), "area_identical_pairs": 5,
                                 "area_with_unknown_original_state_ut": sum(
                                     r["baseline_directory_status"] == "area_located" and
                                     r["original_state"] in {NO_STATE, NOT_A_STATE} for r in frame.values())},
            "fallback": {"by_precision": cells(totals), "by_baseline_status": {k: cells(v) for k, v in by_baseline.items()},
                         "premises_or_entrance_supplied_by_area_rule": 0, "geography": geography,
                         "interpretation": "Directory campus labels remain separate from any independently reviewed premises. Postal areas, cities and localities describe area precision."}}
