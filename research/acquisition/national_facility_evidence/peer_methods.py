"""Integrate approved peer comparisons without widening row custody."""

import json
from hashlib import sha256
import shutil
import subprocess
import sys

from . import inputs, model

A0_EDITION = "issue-235-address-method-v1"
A0_PIN = "a72d6fd813fa62522a5a5aea2be440f49429011650ce0b7102eb53f5ff13d399"
A0_FILES = {"address_replay.py", "aggregate.json", "method.md", "replay-guide.md",
            "replay-manifest.json", "synthetic_checks.py"}
K_SOURCE_EDITION = "k-233-mri-source-first-v1"
K_SOURCE_PIN = "290d987f664d37a181bab1e2c2053305e95f4dfbca9153f4735c4095686b31ad"
K_TIME_EDITION = "k-233-cycle01-b-mri-v1"
K_TIME_PIN = "6492d230e70109e15c292eb6b32e69ea730c0a79790528d7403f25036e4fb18e"


def location(edition, manifest_pin):
    return f"{inputs.MATCHING}/{edition}-{manifest_pin}/manifest.json"


def address_comparison(root, pilot, receipt_root, working, issuer_batch):
    """Regenerate A's normalized-address control from the same authorized sources."""
    package = receipt_root / A0_EDITION
    _, published, files = inputs.package(package, A0_PIN, A0_FILES)
    producer = working / "pinned-221-layout"
    (producer / "inputs/vf").mkdir(parents=True)
    (producer / "source-freeze").mkdir()
    replay = working.parent / "replay-221/source-only"
    for name in ("source-ledger.jsonl", "source-summary.json", "freeze.json", "method.md"):
        shutil.copyfile(replay / name, producer / "source-freeze" / name)
    _, _, pilot_files = inputs.package(pilot, inputs.PILOT_PIN, ("compare_vf.py", "source_screen.py"))
    for name, file in pilot_files.items():
        shutil.copyfile(file, producer / name)
    _, _, d = inputs.d_paths(root)
    for name, file in d.items():
        shutil.copyfile(file, producer / "inputs/vf" / name)

    private = working / "private-comparison"
    for name, arguments in (("synthetic_checks.py", ()), ("address_replay.py", (producer, private))):
        subprocess.run([sys.executable, "-B", "-X", "utf8", str(files[name]), *map(str, arguments)],
                       check=True, stdout=subprocess.DEVNULL)
    reference = json.loads(files["replay-manifest.json"].read_bytes())
    pins = reference["files"]
    inputs.checked(private / "private-crosswalk.jsonl", pins["private-crosswalk.jsonl"])
    # The pinned producer's write_text emits platform-native line endings in the two JSON files.
    raw = (private / "aggregate.json").read_bytes()
    normalized = raw.replace(b"\r\n", b"\n")
    model.need(normalized == files["aggregate.json"].read_bytes(), "A0 aggregate differs after newline normalization")
    regenerated = json.loads((private / "manifest.json").read_bytes())
    model.need(regenerated["files"]["aggregate.json"] == sha256(raw).hexdigest(),
               "A0 replay manifest did not describe its own output")
    regenerated["files"]["aggregate.json"] = sha256(normalized).hexdigest()
    model.need(regenerated == reference, "A0 replay manifest differs beyond native line endings")
    stats = json.loads(normalized)
    model.need(stats["extension_candidate_edges"] == {}
               and stats["extension_occurrence_outcomes"]["unmatched"] == 10088,
               "the frozen A0 edition was expected to add zero branch candidates")

    return model.EvidenceBatch(
        "nabh_normalized_address_a0",
        {"version": A0_EDITION, "manifest_sha256": A0_PIN, "publisher": "Developer A",
         "source_edition": f"{inputs.ISSUES}/221#issuecomment-7076224239",
         "scope_and_readback": f"{inputs.ISSUES}/235#issuecomment-7076432800",
         "terms": issuer_batch.inventory["terms"],
         "method_and_aggregates_only": location(A0_EDITION, A0_PIN),
         "input_counts": stats["denominator"], "outcomes": stats["extension_occurrence_outcomes"],
         "same_single_pin_originals": stats["vf_occurrences_sharing_single_issuer_pin"],
         "private_replay_artifact_pins": pins,
         "verification": "Private crosswalk is byte-identical. JSON aggregate is exact after platform newline normalization."},
        issuer_batch.records, issuer_batch.premises, issuer_batch.claims,
    )


def equipment_comparators(receipt_root):
    """Verify K's counts for the comparison report, without assuming shared crosswalks."""
    _, source_members, source_files = inputs.package(receipt_root / K_SOURCE_EDITION, K_SOURCE_PIN, ("aggregate.json",))
    source = inputs.read(source_files["aggregate.json"], source_members["aggregate.json"])
    _, time_members, time_files = inputs.package(receipt_root / K_TIME_EDITION, K_TIME_PIN, ("aggregate.json",))
    time = inputs.read(time_files["aggregate.json"], time_members["aggregate.json"])
    model.need(source["originals"] == time["national_unchanged"]["original_occurrences"] == 10088
               and source["decisions"] == time["national_unchanged"]["unconfirmed_service_decisions"] == 30264
               and source["diagnostic_mri_rows"] == time["primary_slots"] == 13,
               "equipment comparator denominators changed")
    return {
        "nhsrc_mri_source_first": {
            "row_custody": "Shared method and aggregates. Private installation and VF crosswalk rows excluded from union.",
            "method_and_aggregates_only": location(K_SOURCE_EDITION, K_SOURCE_PIN),
            "aggregate": source_members["aggregate.json"],
            "source_receipt": f"{inputs.ISSUES}/233#issuecomment-7076273611",
            "equipment_rows_screened": source["national_equipment_rows"],
            "diagnostic_mri_rows": source["diagnostic_mri_rows"],
            "service_conditions_by_source_label": source["by_condition"],
            "location_hypotheses_by_original_scope": source["by_location"],
            "vf_candidate_counts": source["vf_candidates"],
            "vf_originals_reached_from_frozen_misses": source["reached_frozen_misses"],
            "verified_physical_links": source["verified_physical_links"],
            "verified_dated_scanning_rows": source["verified_dated_scanning_rows"],
        },
        "nhsrc_mri_host_and_time": {
            "row_custody": "Shared method and aggregate only. Same 13 slots as the source-first arm.",
            "method_and_aggregates_only": location(K_TIME_EDITION, K_TIME_PIN),
            "aggregate": time_members["aggregate.json"],
            "source_receipt": f"{inputs.ISSUES}/233#issuecomment-7076432667",
            "decision_date": time["decision_date"], "primary_mri_slots": time["primary_slots"],
            "eligible_latest_publication_comparisons": time["b0"]["eligible_latest_publication_comparisons"],
            "unresolved_slots": time["b1"]["unresolved_slots"],
            "eligible_historical_onsite_activity": time["b1"]["eligible_historical_onsite_activity"],
            "eligible_current_operation": time["b1"]["eligible_current_operation"],
            "eligible_vf_campus_pairs": time["b1"]["eligible_vf_campus_pairs"],
            "independent_accuracy": time["independent_accuracy"],
        },
    }
