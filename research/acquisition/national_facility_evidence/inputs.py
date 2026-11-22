"""Read the pinned first editions without acquiring or refetching source data."""

from collections import defaultdict
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys

from research.matching.common import canonical, digest, file_digest
from research.matching.national import NO_STATE, NOT_A_STATE, STATES, state_from_pin
from research.matching.normalize import fold, pin_key, state_key
from research.geography.postal import aggregate

from .model import EvidenceBatch, SERVICES, identifier, index, need

ISSUES = "https://github.com/vzhu08/databricks-datathon/issues"
DATASET = "databricks_virtue_foundation_dataset_dais_2026_databricks.virtue_foundation_dataset"
RECIPIENT = Path("team-intake-20261121/recipient-160")
PREPARED = Path("vincent-source-20261121/prepared")
NABH = Path("windows-nabh-173/readback")
PILOT_PIN = "b437f13e68f4185f603dadd918ee14a0bbb8137bc20c1ae34aa8a88421001c45"
BASE_PIN = "27e4a79de42ec56c76cc676ed45494a52497d179858bc50549a461434c45e9d8"
POSTAL_PIN = "af41bd5f7a20653f4af877ebd9c878d4cc162fb683e7fb7253bda24564d56343"
D_PIN = "2f3fc37e591ee834a839d20e4211cb5f3ecc71defaacdcce826615f4e0923b9a"
G_PIN = "d36215df7fd5799595d150214c28433f818fac2070591a2a7e289d64ff1b6b88"
K_PIN = "d3a4650d238b9c6a9138102f40123d94f71417224e653dbe454c64318d893c7b"
NABH_PIN = "d215fb594af3fc78b8e1e46a1e938ddec28565611f869241d10615c2d3e8e547"
QUAL_PIN = "3bae2f0ab2528cef703cafd7280752bae886ed89b0e4865115581e4cc81ae16c"
PAYLOAD_MULTISET = "30d32fa927f5d43753ea6d42f3685ea62e1b416a6cffce7e11ebd1d83b905ca6"
MATCHING = "dbfs:/Volumes/workspace/datathon_acquisition/matching_inputs"
INTAKE = "dbfs:/Volumes/workspace/default/datathon_vf_research_intake"
PILOT_FILES = {"compare_vf.py", "comparison-summary.json", "freeze.json", "method.md",
               "producer_checks.py", "replay.md", "source-summary.json", "source_screen.py"}


def lines(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        yield from map(json.loads, handle)


def checked(path, expected):
    if isinstance(expected, str):
        expected = {"sha256": expected}
    need(file_digest(path) == expected["sha256"], f"hash did not match for {path.name}")
    need("bytes" not in expected or path.stat().st_size == expected["bytes"], f"length did not match for {path.name}")
    return path


def read(path, expected):
    return json.loads(checked(path, expected).read_bytes())


def package(path, pin, names):
    manifest = read(path / "manifest.json", pin)
    descriptions = manifest["files"]
    if isinstance(descriptions, list):
        descriptions = {v.get("path", v.get("filename")): v for v in descriptions}
    files = {name: checked(path / name, descriptions[name]) for name in sorted(names)}
    return manifest, descriptions, files


def d_paths(root):
    folder = root / RECIPIENT / "run-01/D-baseline/source"
    return package(folder, D_PIN, ("occurrences.jsonl.gz", "decisions.jsonl.gz"))


def replay_issuer(root, pilot, out):
    """Run the exact checked producer method source-first and verify every private output."""
    manifest, published, methods = package(pilot, PILOT_PIN, PILOT_FILES)
    qualification = root / NABH / "qualification"
    _, _, qual = package(qualification, QUAL_PIN, ("issuer-qualification.json",))
    sqlite = checked(root / NABH / "nabh.sqlite", NABH_PIN)

    issuer, comparison = out / "source-only", out / "comparison"
    out.mkdir(parents=True, exist_ok=False)
    def run(script, *args):
        subprocess.run([sys.executable, "-B", "-X", "utf8", str(methods[script]), *map(str, args)],
                       check=True, stdout=subprocess.DEVNULL)

    run("source_screen.py", sqlite, qual["issuer-qualification.json"], issuer)
    checked(issuer / "source-summary.json", published["source-summary.json"])
    shutil.copyfile(methods["method.md"], issuer / "method.md")
    shutil.copyfile(methods["freeze.json"], issuer / "freeze.json")
    _, _, d = d_paths(root)
    run("compare_vf.py", issuer, d["occurrences.jsonl.gz"], d["decisions.jsonl.gz"], comparison)
    run("producer_checks.py")
    artifacts = manifest["private_local_replay_artifacts"]
    for name in artifacts:
        directory = issuer if name == "source-ledger.jsonl" else comparison
        checked(directory / name, artifacts[name])
    return issuer, comparison


def frozen_frame(root):
    prepared = read(root / PREPARED / "base.json", BASE_PIN)
    manifest, pins, files = d_paths(root)
    frozen = list(lines(files["occurrences.jsonl.gz"]))
    need(len(prepared) == len(frozen) == 10088, "unexpected VF population")
    original_rows = []
    for ordinal, (original, row) in enumerate(zip(prepared, frozen, strict=True)):
        identity = row["identity"]
        need(original == row["original"] and identity["input_ordinal_zero_based"] == ordinal,
             "VF payload, order or occurrence key changed")
        source = original["source_row"]
        payload = digest(source)
        need(payload == identity["original_payload_sha256"] and source["unique_id"] == identity["original_upstream_id"],
             "VF original payload or upstream ID changed")
        original_rows.append({"occurrence_key": original["facility_id"], "ordinal": ordinal,
                              "upstream_id": source["unique_id"], "payload_sha256": payload,
                              "state": identity["state"], "original_payload": source})
    originals = index(original_rows, "occurrence_key")
    decisions_path = files["decisions.jsonl.gz"]
    decisions = {(r["occurrence_key"], r["service"], r["state"], r["status"])
                 for r in lines(decisions_path)}
    need(decisions == {(key, service, row["state"], "unconfirmed")
                       for key, row in originals.items() for service in SERVICES},
         "frozen decision frame changed")
    need(pins["decisions.jsonl.gz"]["records"] == len(decisions) == 30264, "decision count mismatch")
    need(len(STATES) == 36 and all(r["state"] in STATES | {NO_STATE, NOT_A_STATE} for r in originals.values()),
         "unrecognized frozen geography fixture")
    need(digest(sorted((r["source_row"] for r in prepared), key=canonical)) == PAYLOAD_MULTISET,
         "unexpected VF payload multiset")
    return originals, decisions_path, {
        "dataset": f"{DATASET}.facilities VERSION AS OF 0", "sha256_prepared": BASE_PIN,
        "d_manifest_sha256": D_PIN, "d_files": {name: pins[name] for name in files},
        "d_population": manifest["population"],
        "row_custody": "Authorized team Delta v0 and a previously shared D row edition",
        "source": f"{ISSUES}/6#issuecomment-7069335700",
        "acquisition_row_manifest": f"{MATCHING}/service-ledger-163-collectors-v1-191fbfae50f42c32e14faacf064d7b72bcc67b83b62b7f61f850d4e477cc2fa8/manifest.json",
    }


def postal_context(root, originals):
    rows = read(root / PREPARED / "postal_rows.json", POSTAL_PIN)
    table, profile = aggregate(rows, {"pin": "pincode", "state": "statename", "district": "district"}, STATES)
    need(profile["postal_rows"] == 165627 and profile["distinct_pins"] == 19586, "unexpected postal reference population")
    contexts = {}
    for key, row in originals.items():
        pin = pin_key(row["original_payload"]["address_zipOrPostcode"])
        found, status = state_from_pin({"pin": pin}, table)
        indicated = row["state"]
        if status == "exact":
            status = ("compatible_label_and_postal_area" if found == indicated else
                      "postal_area_only" if indicated in {NO_STATE, NOT_A_STATE} else "state_pin_conflict")
        contexts[key] = {"occurrence_key": key, "status": status, "postal_state": found,
                         "pin": pin, "point_role": "no_campus_point"}
    profile.update(dataset=f"{DATASET}.india_post_pincode_directory VERSION AS OF 0", sha256=POSTAL_PIN,
                   source=f"{ISSUES}/6#issuecomment-7069335700", row_grain="post office grouped by PIN",
                   row_custody="Team-readable Delta v0. Derived context is private working output.",
                   counted_as_premises_evidence=False)
    return table, contexts, profile


def source_record(edition, family, source_key, origin, locator, fields):
    return {"record_id": identifier("record", edition, source_key), "edition": edition,
            "family": family, "source_key": source_key, "origin_record": origin,
            "locator": locator, "original_fields": fields}


def source_premises(record, local_key, name, address, state, pin, comparable, witnesses, point):
    return {"premises_id": identifier("premises", record["edition"], local_key), "record_id": record["record_id"],
            "name": name, "address": address, "state": state, "pin": pin, "comparable": comparable,
            "identity_reviewed": False, "witnesses": witnesses, "point": point}


def service_claim(record, local_key, premises_id, service, scope, locator, publication_date=None,
                  observation_date=None, effective_from=None, effective_to=None, original_status=None, wording=None):
    return {"claim_id": identifier("claim", record["record_id"], local_key), "record_id": record["record_id"],
            "premises_id": premises_id, "service": service, "scope": scope, "locator": locator,
            "publication_date": publication_date, "observation_date": observation_date,
            "effective_from": effective_from, "effective_to": effective_to, "original_status": original_status,
            "wording": wording, "availability": None, "capacity": None}


def issuer_batch(pilot, replay, postal):
    method = "nabh_strict_printed_premises"
    issuer, comparison = replay / "source-only", replay / "comparison"
    manifest = read(pilot / "manifest.json", PILOT_PIN)
    screened = read(issuer / "source-summary.json", manifest["files"]["source-summary.json"])
    ledger = checked(issuer / "source-ledger.jsonl", manifest["private_local_replay_artifacts"]["source-ledger.jsonl"])
    batch = EvidenceBatch(method, {
        "version": "issue-221 frozen full printed branch/address/PIN",
        "scope": "National NABH listings, 2026-11-22",
        "publisher": "NABH/QCI", "family": "nabh", "sqlite_sha256": NABH_PIN,
        "row_grain": "Issuer listing; distinct edition-scoped printed premises hypotheses",
        "terms": f"{ISSUES}/221#issuecomment-7076179691",
        "source": "https://nabh.co/find-a-healthcare-organisation/",
        "team_readable_input_rows": f"{INTAKE}/supplement-v1-971fa3ec5bd77029be93df299dd9ec85edab0baa788654476752e7260f86e201/manifest.json",
        "scope_qualification_manifest": f"{INTAKE}/nabh-directory-qualification-v1-{QUAL_PIN}/manifest.json",
        "method_and_aggregates_only": f"{MATCHING}/issue-221-issuer-dialysis-pilot-v1-{PILOT_PIN}/manifest.json",
        "private_replay_artifact_pins": manifest["private_local_replay_artifacts"],
        "input_counts": screened,
    })
    sites = {}
    for row in lines(ledger):
        locator = {"page": row["page"], "position": row["position"], "listing_id": row["listing_id"]}
        record = source_record(NABH_PIN, "nabh", row["listing_id"], row["listing_payload_sha256"], locator, row)
        batch.records.append(record)
        printed_key = row["premises_key"]
        state, _ = state_from_pin({"pin": row["pin"]}, postal)
        witness = {"family": "nabh", "locator": locator, "role": "civic_address"}
        site = source_premises(record, printed_key or ("unresolved", row["listing_id"]), row["name"],
                               row["premises_address"], state, row["pin"], bool(printed_key),
                               [witness] if printed_key else [],
                               {"role": "issuer_map_link", "precision": row["point_precision"], "records": row["points"]})
        batch.premises.append(site)
        if printed_key:
            need(printed_key not in sites, "issuer premises collision requires a new disposition")
            sites[printed_key] = site["premises_id"]
        for mention in row["dialysis_scope_mentions"]:
            loc = {**locator, "field": mention["field"], "position_in_field": mention["position"]}
            batch.claims.append(service_claim(record, loc, site["premises_id"], "dialysis", "programme", loc,
                                               original_status="accreditation_programme_only", wording=mention["wording"]))
    path = checked(comparison / "vf-link-ledger.jsonl",
                   manifest["private_local_replay_artifacts"]["vf-link-ledger.jsonl"])
    for row in lines(path):
        for candidate in row["candidates"]:
            batch.links.append({"occurrence_key": row["occurrence_key"], "premises_id": sites[candidate],
                                "basis": "full_printed_name_address_pin",
                                "exact_candidate": row["link_state"] == "exact_directory_text", "conflicts": []})
    return batch


def operator_batch(root):
    folder = root / RECIPIENT / "run-01/G/source"
    manifest, pins, files = package(folder, G_PIN, ("pib-observations.json", "rights-assessment.json"))
    observations = read(files["pib-observations.json"], pins["pib-observations.json"])
    rights = read(files["rights-assessment.json"], pins["rights-assessment.json"])
    batch = EvidenceBatch("esic_pib_report_scope", {
        "version": manifest["edition"], "manifest_sha256": G_PIN, "source": f"{ISSUES}/143#issuecomment-7074691844",
        "scope": "Two Sanath Nagar ESIC campus releases and original publication dates",
        "publisher": "Press Information Bureau / ESIC", "family": "esic",
        "team_readable_input_rows": f"{INTAKE}/{manifest['edition']}-{G_PIN}/manifest.json",
        "terms": rights["PIB"]["policy"], "members": {n: pins[n] for n in files},
        "input_counts": {"permitted_observations": len(observations),
                         "emergency_without_trauma_assignment": sum(r["service"] == "emergency" for r in observations)},
    })
    for row in observations:
        if row["service"] not in SERVICES:
            continue
        scope = {"pooled_twin_hospitals": "pooled_report", "historical_activity_2025_26": "pooled_report",
                 "education_program": "training"}.get(row["scope"], "reported_scope_unknown")
        locator = {"publisher_release_key": row["record_id"], **row["locator"]}
        origin = "esic-sanath-nagar-shared-complex" if scope == "pooled_report" else row["record_id"]
        record = source_record(G_PIN, row["source_family"], row["observation_id"], origin, locator, row)
        batch.records.append(record)
        batch.claims.append(service_claim(record, row["observation_id"], None, row["service"], scope, locator,
                                          row["publication_date"], row["service_observation_date"],
                                          original_status=row["temporal_status"], wording=row["mention_original"]))
    return batch


def equipment_batch(root, originals):
    folder = root / RECIPIENT / "run-01/K-v4/source"
    manifest, pins, files = package(folder, K_PIN, ("dmer.batch.json", "dmer.observations.json"))
    facilities = read(files["dmer.batch.json"], pins["dmer.batch.json"])
    rows = read(files["dmer.observations.json"], pins["dmer.observations.json"])
    snapshot, = facilities["source_snapshots"]
    batch = EvidenceBatch("dmer_name_state_lead", {
        "version": manifest["edition"], "manifest_sha256": K_PIN, "source": snapshot["url"],
        "scope": "Maharashtra DMER institution-level reporting, undated inventory",
        "publisher": snapshot["publisher"], "family": snapshot["source_family"], "terms": snapshot["license"],
        "team_readable_input_rows": f"{INTAKE}/{manifest['edition']}-{K_PIN}/manifest.json",
        "input_counts": {"institution_rows": len(facilities["external_facilities"]), "modality_observations": len(rows)},
        "members": {n: pins[n] for n in files},
    })
    lookup = defaultdict(list)
    for key, row in originals.items():
        name = fold(row["original_payload"]["name"])
        if name and row["state"] in STATES:
            lookup[name, row["state"]].append(key)
    target = index((r for r in rows if r["modality"] == "mri"), "external_facility_id")
    for item in facilities["external_facilities"]:
        raw_id = item["external_facility_id"]
        obs = target[raw_id]
        need(obs["sharing_status"] == "permitted_private" and obs["kind"] == "equipment_count",
             "DMER observation scope changed")
        locator = item["record_locator"]
        record = source_record(K_PIN, snapshot["source_family"], raw_id, locator, locator, item)
        batch.records.append(record)
        state, name = state_key(item["state"]), item["name_original"]
        comparable = bool(obs["grain"] == "campus" and fold(name) and state in STATES)
        site = source_premises(record, raw_id, name, item["address_original"], state, item["pin"], comparable, [],
                               {"role": "no_point", "precision": None})
        batch.premises.append(site)
        batch.claims.append(service_claim(record, obs["observation_id"], site["premises_id"], "mri",
                                          "equipment_inventory", obs["locator"], obs["published_date"],
                                          original_status=obs["vf_campus_join"], wording=obs["raw_value"]))
        if comparable:
            for key in lookup[fold(name), state]:
                batch.links.append({"occurrence_key": key, "premises_id": site["premises_id"],
                                    "basis": "printed_label_same_state_no_branch_address",
                                    "exact_candidate": False, "conflicts": []})
    return batch


def extension_batch(manifest_path, manifest_sha):
    """Read an explicitly cleared normalized packet. Receipts stay in the local inventory."""
    manifest = read(manifest_path, manifest_sha)
    need(manifest["schema"] == "national-facility-evidence-input-v1", "unknown input packet schema")
    need(manifest["audience"] == "existing_four_person_private_research"
         and manifest["custody"] == "verified_team_readable_rows",
         "row packet requires existing team read scope")
    need(all(manifest.get(k) for k in ("receipt", "terms", "method", "source", "publisher", "input_counts")),
         "missing source packet evidence or scope")
    tables = ("records", "premises", "claims", "links")
    need(set(manifest["files"]) == {f"{t}.jsonl" for t in tables}, "unexpected input packet table")
    rows = {t: list(lines(checked(manifest_path.with_name(f"{t}.jsonl"), manifest["files"][f"{t}.jsonl"]))) for t in tables}
    need(all(len(v) == manifest["files"][f"{t}.jsonl"]["records"] for t, v in rows.items()),
         "input packet counts did not match")
    keys = ("method", "source", "publisher", "receipt", "terms", "input_counts", "files", "audience", "custody")
    need(all(isinstance(manifest[k], str) for k in ("method", "source", "publisher", "receipt", "terms")),
         "source inventory fields must be public strings")
    need(all(type(v) is int and v >= 0 for v in manifest["input_counts"].values()),
         "source inventory counts must be nonnegative integers")
    scope = {k: manifest[k] for k in keys}
    return EvidenceBatch(manifest["method"], {**scope, "manifest_sha256": manifest_sha}, **rows)
