"""Build the closed-schema aggregate consumed by Andrew's #278 area view."""

import argparse
from pathlib import Path

from . import core


def display(frame):
    report = core.aggregate(frame)
    by = report["fallback"]["by_baseline_status"]["area_located"]
    geo = report["fallback"]["geography"]
    missing = geo[core.NO_STATE]["baseline_directory_and_fallback"]["unresolved"]["unknown"]
    unrecognized = geo[core.NOT_A_STATE]["baseline_directory_and_fallback"]["unresolved"]["unknown"]
    unresolved = core.FROZEN["unresolved"]
    value = {
        "schema": "issue-270-area-display-v1", "audience": "Datathon judge walkthrough",
        "edition": "Frozen national directory v4", "as_of": "2026-11-22",
        "source": "Virtue Foundation version 0 and the independently read national directory v4 aggregate (#160).",
        "originals": report["population"]["original_occurrences"],
        "distinct_upstream_ids": report["population"]["distinct_upstream_ids"],
        "precision": {"campus_classified": core.FROZEN["campus_located"],
                      **{k: by[k] for k in ("locality", "city", "postal_area", "district")},
                      "unresolved": unresolved},
        "campus_basis": {"named_map_listing": core.BASIS["campus_located"]["named_map_listing"],
                         "matching_address": core.BASIS["campus_located"]["matching_branch_address"]},
        "unresolved_reasons": {"missing_state": missing, "unrecognized_label": unrecognized,
                               "other": unresolved - missing - unrecognized},
    }
    core.need(sum(value["precision"].values()) == value["originals"], "display population changed")
    core.need(sum(value["campus_basis"].values()) == 2524 and sum(value["unresolved_reasons"].values()) == 146,
              "display subcategories changed")
    return value


def build(root, out):
    frame, _ = core.load(root)
    out.mkdir(parents=True, exist_ok=False)
    value = display(frame)
    core.write_json(out / "area-display.json", value)
    core.write_json(out / "manifest.json", {
        "edition": "issue-270-b3-area-display-v1",
        "input_directory_manifest_sha256": core.V4_AGG,
        "input_directory_occurrence_ledger_sha256": core.V4,
        "scope": "National category counts and descriptions only. Named areas, original occurrence links and coordinates stay in custody.",
        "audience": "Four named private Volume readers; the JSON is cleared for the Datathon judge walkthrough.",
        "authority": "https://github.com/vzhu08/databricks-datathon/issues/252#issuecomment-7076935890",
        "independent_input_receipt": "https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7075940482",
        "ui_schema_commit": "5a3653f51b8c4a8732e298540aba5be02804799b",
        "builder": core.pin(Path(__file__)),
        "files": {"area-display.json": {**core.pin(out / "area-display.json"), "records": 1}},
    })
    return value


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("nationwide", type=Path)
    cli.add_argument("out", type=Path)
    opts = cli.parse_args()
    print(build(opts.nationwide, opts.out))
