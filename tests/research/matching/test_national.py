"""NAT-C01: twin-aware matching and one output row per original base row.
Entirely synthetic data."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from matching_fixtures import ROOT, base_row, envelope, ext, mapping, snapshot

from research.matching.common import MatchingError, digest
from research.matching.national import (duplicate_groups, execute_national, payload_digest,
                                        sidecar_groups)
from research.matching.run import execute

STATE, OTHER = "Synthetic State", "Other Synthetic State"
POLICY = {"synthetic_registry": {"base_field": "source_row.registry_id", "external_field": "source_record_id",
                                 "source_keys": ["synthetic_directory"]}}


def twin(row, number):
    """A second handle for the same payload, as D's occurrence keys produce."""
    return {"facility_id": f"synthetic:base:{number:03d}", "source_row": copy.deepcopy(row["source_row"])}


def data():
    first = base_row(1, name="Larkspur Hospital", registry_id="R-1", city="North Town", state=STATE)
    base = [first, twin(first, 2),
            base_row(3, name="Marigold Hospital", registry_id="R-3", city="North Town", state=STATE),
            base_row(4, name="Juniper Clinic", registry_id="R-4", city="East Town", state=OTHER),
            base_row(5, name=None, registry_id="R-5", city="East Town", state=OTHER)]
    snap, other = snapshot(), snapshot("synthetic_map")
    externals = [ext(1, "Larkspur Hosp", snap, source_record_id="R-1", city="North Town", state=STATE),
                 ext(2, "Marigold Hospital", other, city="North Town", state=STATE)]
    return base, envelope([snap, other], externals)


def run(base, batch, **kwargs):
    return execute_national(base, [batch], mapping=kwargs.pop("mapping", mapping(base)), **kwargs)


class DuplicateGroupTests(unittest.TestCase):
    def test_groups_come_from_identical_payloads_only(self):
        base, _ = data()
        groups = duplicate_groups(base)
        self.assertEqual(1, len(groups))
        self.assertEqual((["synthetic:base:001", "synthetic:base:002"], 2, "synthetic:base:001"),
                         (groups[0]["members"], groups[0]["multiplicity"], groups[0]["representative"]))
        self.assertEqual("base-payload:" + payload_digest(base[0]), groups[0]["group_id"])
        base[1]["source_row"]["city"] = "South Town"          # same ID column, different payload
        self.assertEqual([], duplicate_groups(base))

    def test_sidecar_must_agree_with_the_base(self):
        base, batch = data()
        good = [{"original_id": "R-1", "multiplicity": 2, "row_handles": ["synthetic:base:002", "synthetic:base:001"]}]
        for sidecar in (good, {"groups": good}, [["synthetic:base:001", "synthetic:base:002"]]):
            self.assertEqual({frozenset({"synthetic:base:001", "synthetic:base:002"})}, sidecar_groups(sidecar))
            run(base, batch, duplicate_sidecar=sidecar)
        with self.assertRaisesRegex(MatchingError, "sidecar disagrees"):
            run(base, batch, duplicate_sidecar=[["synthetic:base:001", "synthetic:base:003"]])
        with self.assertRaisesRegex(MatchingError, "sidecar disagrees"):
            run(base, batch, duplicate_sidecar=[])
        with self.assertRaisesRegex(MatchingError, "two or more distinct"):
            sidecar_groups([["synthetic:base:001"]])
        with self.assertRaisesRegex(MatchingError, "expected 2"):
            run(base, batch, expect_duplicate_groups=2)
        run(base, batch, expect_duplicate_groups=1)


class NationalRunTests(unittest.TestCase):
    def test_twins_share_one_result_and_do_not_compete(self):
        base, batch = data()
        plain = execute(base, [batch], mapping=mapping(base), policy=POLICY)
        # As separate rows the two copies block each other: nothing confirms.
        self.assertEqual(0, plain["report"]["base"]["rows_with_automatic_shared_identifier_confirmation"])
        result = run(base, batch, policy=POLICY)
        rows = {r["facility_id"]: r for r in result["base_rows"]}
        self.assertEqual([row["facility_id"] for row in base], [r["facility_id"] for r in result["base_rows"]])
        for fid in ("synthetic:base:001", "synthetic:base:002"):
            self.assertEqual(("confirmed", "synthetic:base:001", 2, ["synthetic:external:001"]),
                             (rows[fid]["outcome"], rows[fid]["matched_as"], rows[fid]["duplicate_multiplicity"],
                              rows[fid]["confirmed_external_facility_ids"]))
            self.assertEqual(result["duplicate_groups"][0]["group_id"], rows[fid]["duplicate_group"])
        # The contract batch names only the representative, so one reference is never confirmed twice.
        self.assertEqual({"synthetic:base:001", "synthetic:base:003"},
                         {m["facility_id"] for m in result["batch"]["facility_matches"]})
        self.assertEqual("candidate_only", rows["synthetic:base:003"]["outcome"])
        self.assertEqual(("unmatched", None, 1), (rows["synthetic:base:004"]["outcome"],
                                                  rows["synthetic:base:004"]["duplicate_group"],
                                                  rows["synthetic:base:004"]["duplicate_multiplicity"]))

    def test_report_keeps_both_denominators_and_every_row(self):
        base, batch = data()
        before = digest(base)
        report = run(base, batch, policy=POLICY)["national_report"]
        self.assertEqual(before, digest(base))
        self.assertEqual({"original_rows": 5, "distinct_payloads": 4, "original_rows_in_base_file": 5,
                          "identical_payload_groups": 1, "rows_in_identical_payload_groups": 2},
                         report["denominators"])
        self.assertEqual({"unit": "original rows", "confirmed": 2, "ambiguous": 0, "candidate_only": 1, "unmatched": 2},
                         report["outcomes"])
        self.assertEqual({"unit": "distinct payloads", "confirmed": 1, "ambiguous": 0, "candidate_only": 1,
                          "unmatched": 2}, report["outcomes_distinct_payloads"])
        state = report["by_state"]["synthetic state"]
        self.assertEqual((3, 2, 2, 1, 0), (state["original_rows"], state["distinct_payloads"], state["confirmed"],
                                           state["candidate_only"], state["unmatched"]))
        self.assertEqual(sum(s["original_rows"] for s in report["by_state"].values()), 5)
        directory, other = report["by_source"]["synthetic_directory"], report["by_source"]["synthetic_map"]
        self.assertEqual((1, 1, 5, 2, 3), (directory["reference_rows"], directory["reference_rows_retrieved"],
                                           directory["original_rows"], directory["confirmed"], directory["unmatched"]))
        self.assertEqual((1, 4), (other["candidate_only"], other["unmatched"]))
        for entry in list(report["by_state"].values()) + list(report["by_source"].values()):
            self.assertEqual(entry["original_rows"], sum(entry[o] for o in ("confirmed", "ambiguous",
                                                                           "candidate_only", "unmatched")))
        self.assertEqual({"0": 2, "1": 3}, {k: v for k, v in report["source_overlap"].items() if k != "unit"})
        self.assertEqual(1, report["input_problems"]["by_problem"]["name_missing"])

    def test_missed_sample_is_repeatable_and_never_lists_a_copy_twice(self):
        base, batch = data()
        extra = base_row(6, name="Quillon Sanatorium", city="West Town", state=STATE)
        base += [extra, twin(extra, 7)]
        one, two = run(base, batch)["missed_sample"], run(list(reversed(base)), batch)["missed_sample"]
        self.assertEqual(one, two)
        self.assertEqual((3, 3), (one["available"], one["sampled"]))
        self.assertEqual({"synthetic:base:004", "synthetic:base:005", "synthetic:base:006"},
                         {r["facility_id"] for r in one["rows"]})
        self.assertEqual(1, run(base, batch, missed_sample_size=1)["missed_sample"]["sampled"])

    def test_state_scope_keeps_copies_together(self):
        base, batch = data()
        result = run(base, batch, state="SYNTHETIC  STATE")
        self.assertEqual(["synthetic:base:001", "synthetic:base:002", "synthetic:base:003"],
                         [r["facility_id"] for r in result["base_rows"]])
        report = result["national_report"]
        self.assertEqual((3, 2, 5), (report["denominators"]["original_rows"], report["denominators"]["distinct_payloads"],
                                     report["denominators"]["original_rows_in_base_file"]))
        self.assertEqual("synthetic state", report["scope"]["state"])
        with self.assertRaisesRegex(MatchingError, "no base row carries"):
            run(base, batch, state="Nowhere")

    def test_source_metadata_is_checked_against_the_whole_base(self):
        base, batch = data()
        metadata = {"mapping": {"id": "registry_id", "name": "name", "state": "state"}, "row_count": 5}
        result = execute_national(base, [batch], source_metadata=metadata, mapping={"city": "source_row.city"})
        self.assertEqual(["city", "name", "state"], result["national_report"]["run_report"]["base_mapping_roles"])
        with self.assertRaisesRegex(MatchingError, "row_count differs"):
            execute_national(base, [batch], source_metadata=dict(metadata, row_count=4))

    def test_cli_is_reproducible_and_never_touches_inputs(self):
        base, batch = data()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "in").mkdir()
            files = {"base": tmp / "in/base.json", "ext": tmp / "in/ext.json", "map": tmp / "in/map.json",
                     "groups": tmp / "in/groups.json", "policy": tmp / "in/policy.json"}
            files["base"].write_text(json.dumps(base), encoding="utf-8")
            files["ext"].write_text(json.dumps(batch), encoding="utf-8")
            files["map"].write_text(json.dumps(mapping(base)), encoding="utf-8")
            files["groups"].write_text(json.dumps([["synthetic:base:001", "synthetic:base:002"]]), encoding="utf-8")
            files["policy"].write_text(json.dumps(POLICY), encoding="utf-8")
            before = {k: p.read_bytes() for k, p in files.items()}
            command = [sys.executable, "-m", "research.matching.national", "--base", str(files["base"]),
                       "--external", str(files["ext"]), "--base-mapping", str(files["map"]),
                       "--duplicate-groups", str(files["groups"]), "--identity-policy", str(files["policy"]),
                       "--expect-duplicate-groups", "1"]
            outputs = []
            for name in ("one", "two"):
                done = subprocess.run(command + ["--output-dir", str(tmp / name)], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(0, done.returncode, done.stderr)
                outputs.append({p.name: p.read_bytes() for p in sorted((tmp / name).iterdir()) if p.name != "timing.json"})
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual({"base_rows.json", "batch.json", "candidates.json", "duplicate_groups.json",
                              "geography_report.json", "manifest.json", "missed_sample.json", "national_report.json",
                              "report.json", "review_worksheet.json"}, set(outputs[0]))
            self.assertTrue((tmp / "one/timing.json").exists())
            self.assertEqual(before, {k: p.read_bytes() for k, p in files.items()})
            refused = subprocess.run(command + ["--output-dir", str(tmp / "in")], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(1, refused.returncode)
            self.assertIn("INVALID", refused.stderr)


if __name__ == "__main__":
    unittest.main()
