"""Derive D's opaque, whole-frame sample commitment within existing custody."""

from collections import Counter
import hashlib
import hmac
import secrets

from . import core

SEED = "loc270-d-v1"
STRATA = ("chain", "urban_independent", "rural_or_unnamed")
TARGET = 20


def token(secret, role, value):
    return hmac.new(secret, core.encode([SEED, role, value]), hashlib.sha256).hexdigest()


def read_or_create_secret(path):
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(secrets.token_bytes(32))
    value = path.read_bytes()
    core.need(len(value) == 32, "invalid custodian token secret")
    return value


def read_strata(area, path, digest):
    if path is None:
        return {}, {
            "status": "no_defensible_preassigned_source_in_custody",
            "chain": None, "urban_independent": None, "rural_or_unnamed": None,
            "note": "The original area-only branch frame does not preassign these groups. Names, host reuse, geometry, PIN and method-specific candidate outcomes do not substitute for the strata.",
        }
    source = core.read(path, digest)
    core.need(source["directory_v4_local_sha256"] == core.V4 and source["cohort"] == "area_located"
              and source["selection_seed"] == SEED and source["rights_receipt"],
              "strata input lacks frozen cohort, seed or permission")
    definitions = source["definitions"]
    core.need(set(definitions) == set(STRATA) and all(definitions.values()), "missing exact stratum definitions")
    labels, payloads = {}, {}
    for item in source["assignments"]:
        k, label = item["occurrence_key"], item["stratum"]
        core.need(k in area and k not in labels and label in STRATA, "invalid or repeated area stratum key")
        group = area[k]["original_payload_sha256"]
        core.need(payloads.setdefault(group, label) == label, "conflicting strata for identical originals")
        labels[k] = label
    missing_groups = {row["original_payload_sha256"] for key, row in area.items() if key not in labels}
    core.need(missing_groups.isdisjoint(payloads), "approved strata split identical copies between known and unknown")
    return labels, {**definitions, "status": "preassigned_input_verified", "manifest_sha256": digest,
                     "rights_receipt": source["rights_receipt"]}


def selection(blinded):
    selected, stats = {}, {}
    for name in (*STRATA, "unknown"):
        group = [r for r in blinded if r["stratum"] == name]
        groups = len({r["payload_group_token"] for r in group})
        chosen = []
        if name != "unknown":
            group.sort(key=lambda r: (hashlib.sha256(core.encode([SEED, name, r["occurrence_token"]])).hexdigest(),
                                      r["occurrence_token"]))
            visited = set()
            for row in group:
                identity = row["payload_group_token"]
                if identity in visited:
                    continue
                visited.add(identity)
                chosen.append(row["occurrence_token"])
                if len(chosen) == TARGET:
                    break
            selected[name] = chosen
        stats[name] = {"original_occurrences": len(group), "distinct_payload_groups": groups,
                       "selected": len(chosen), "shortage": None if name == "unknown" else TARGET - len(chosen)}
    return selected, stats


def lock(frame, secret_path, out, approved=None):
    area = {key: row for key, row in frame.items() if row["baseline_directory_status"] == "area_located"}
    labels, definitions = read_strata(area, *(approved or (None, None)))
    secret = read_or_create_secret(secret_path)
    blinded = [{
        "occurrence_token": token(secret, "original_occurrence", key),
        "payload_group_token": token(secret, "payload_group", row["original_payload_sha256"]),
        "baseline_precision": row["area"]["precision"],
        "stratum": labels.get(key, "unknown"),
    } for key, row in area.items()]
    core.need(len({r["occurrence_token"] for r in blinded}) == len(area) == 7418,
              "opaque input did not retain all 7,418 originals")
    frame_pin = core.write_rows(out / "blinded-area-frame.jsonl", blinded)
    chosen, stats = selection(blinded)
    record = {"seed": SEED, "frame_sha256": frame_pin["sha256"], "chosen": chosen}
    commitment = core.encode(record) + b"\n"
    (out / "private-selection.json").write_bytes(commitment)
    core.need(sum(s["original_occurrences"] for s in stats.values()) == 7418,
              "sample strata did not cover the frozen input")
    return {"seed": SEED, "input_sha256": frame_pin["sha256"],
            "commitment_sha256": hashlib.sha256(commitment).hexdigest(),
            "sampling_specification": f"{core.ISSUE}#issuecomment-7076993551",
            "target_cases": TARGET * len(STRATA), "stratum_definitions": definitions, "stratum_counts": stats,
            "selected_cases": sum(len(values) for values in chosen.values()),
            "reviewed_cases": None, "wrong_branch_rate": None,
            "custody": "Frame bytes, token secret and selected token lists stay in the restricted Windows workspace."}


def coverage(frame, secret_path, selection_path, commitment_sha, candidate_union, flag_names):
    """Count frozen lead coverage against the already locked draw."""
    record = core.read(selection_path, commitment_sha)
    core.need(record["seed"] == "loc270-d-unstratified-v1" and len(record["chosen"]) == 60
              and len(flag_names) == 5, "invalid readback of the locked random draw or frozen flag union")
    area = {key for key, row in frame.items() if row["baseline_directory_status"] == "area_located"}
    secret = secret_path.read_bytes()
    opaque = {token(secret, "original_occurrence", key): key for key in area}
    core.need(len(opaque) == 7418 and len(set(record["chosen"])) == 60
              and all(value in opaque for value in record["chosen"]) and candidate_union <= area,
              "locked random selection or candidate flags are outside the frozen area cohort")
    inside = sum(opaque[value] in candidate_union for value in record["chosen"])
    return {"selected": 60, "with_any_of_five_frozen_flags": inside, "with_none_of_five_frozen_flags": 60 - inside,
            "b1_and_c_coverage": None,
            "interpretation": "A flag may supply only area context or a research lead. The coverage check assigns no independent review disposition."}
