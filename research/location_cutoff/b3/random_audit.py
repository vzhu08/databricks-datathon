"""Execute D's separately precommitted simple random draw once in custody."""

import argparse
from collections import Counter
import hashlib
from pathlib import Path

from . import audit, core

SEED = "loc270-d-unstratified-v1"
FRAME_SHA = "8aae6c9c404a07ed27ef03fb02d6fddb9d467a11a7264bcc4455e3f69e85e0a4"
STRATIFIED_SHA = "ece9264fdcb4cff817d6469b3a25e05a9ead9f125f7974a7ddb054603de79034"
METHOD = f"{core.ISSUE}#issuecomment-7077186335"
SIZE = 60


def run(nationwide, stratum_folder, secret_path, out):
    core.need(not out.exists(), "the random audit already has a committed output directory")
    frame, _ = core.load(nationwide)
    area = {key: row for key, row in frame.items() if row["baseline_directory_status"] == "area_located"}
    old_frame = core.checked(stratum_folder / "blinded-area-frame.jsonl", FRAME_SHA)
    old_selection = core.read(stratum_folder / "private-selection.json", STRATIFIED_SHA)
    core.need(old_selection == {"seed": audit.SEED, "frame_sha256": FRAME_SHA,
                               "chosen": {k: [] for k in audit.STRATA}}, "the prior stratified shortfall moved")
    secret = secret_path.read_bytes()
    core.need(len(secret) == 32, "invalid preexisting custodian token secret")
    opaque = {}
    for (key, row), blinded in zip(area.items(), core.rows(old_frame), strict=True):
        expected = audit.token(secret, "original_occurrence", key)
        core.need(blinded["occurrence_token"] == expected and blinded["payload_group_token"] ==
                  audit.token(secret, "payload_group", row["original_payload_sha256"]),
                  "previous opaque frame does not match exact original keys or multiplicity")
        opaque[key] = expected
    core.need(len(set(opaque.values())) == len(area) == 7418, "area token multiplicity changed")
    ordered = sorted(area, key=lambda key: (hashlib.sha256(core.encode([SEED, key])).digest(),
                                            key.encode("utf-8")))
    selected = ordered[:SIZE]
    core.need(len(set(selected)) == SIZE, "random selection repeated an original key")
    choice = {"seed": SEED, "frame_sha256": FRAME_SHA, "chosen": [opaque[key] for key in selected]}
    commitment = core.encode(choice) + b"\n"
    payloads = Counter(area[key]["original_payload_sha256"] for key in selected)
    complete_pairs = sum(n == 2 for n in payloads.values())
    out.mkdir(parents=True, exist_ok=False)
    (out / "private-random-selection.json").write_bytes(commitment)
    result = {
        "selection_rule": METHOD, "seed": SEED, "directory_v4_local_sha256": core.V4,
        "frame_sha256": FRAME_SHA, "prior_stratified_commitment_sha256": STRATIFIED_SHA,
        "commitment_sha256": hashlib.sha256(commitment).hexdigest(),
        "eligible_original_occurrences": len(area), "selected_original_occurrences": len(selected),
        "distinct_selected_payloads": len(payloads), "complete_selected_identical_pairs": complete_pairs,
        "reference_material": {"reviewer_locked_reference_cases": 0, "coverage_established_here": False},
        "review_dispositions": {"no_candidate": 0, "reference_unavailable": 0, "rejected": 0,
                                "independently_supported": 0, "not_yet_reviewed": len(selected)},
        "review_scope": "Selection only. Candidate point files, reference decisions and later strata are outside the draw.",
    }
    core.write_json(out / "random-audit-aggregate.json", result)
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("nationwide", "stratum_folder", "secret", "out"):
        cli.add_argument(name, type=Path)
    opt = cli.parse_args()
    print(run(opt.nationwide, opt.stratum_folder, opt.secret, opt.out))
