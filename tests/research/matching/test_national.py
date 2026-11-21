"""NAT-C01: twin-aware matching and one output row per original base row.
Entirely synthetic data."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from matching_fixtures import ROOT, base_row, envelope, ext, mapping, snapshot

from research.matching.common import MatchingError, digest
from research.matching.normalize import fold, state_key
from research.matching.national import (duplicate_groups, execute_national, payload_digest,
                                        sidecar_groups)

STATE, OTHER = "Rajasthan", "Gujarat"          # real state names, invented facilities
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
                 ext(2, "Marigold Hospital", other, city="North Town", state=STATE),
                 ext(3, "Juniper Clinic", snap, source_record_id="R-4", city="East Town", state=OTHER)]
    return base, envelope([snap, other], externals)


def run(base, batch, **kwargs):
    return execute_national(base, [batch], mapping=kwargs.pop("mapping", mapping(base)), **kwargs)


class AccentTests(unittest.TestCase):
    def test_latin_accents_do_not_create_state_conflicts(self):
        """Public references spell states with macrons; the base does not."""
        for plain, accented in (("Rajasthan", "Rājasthān"), ("Bihar", "Bihār"), ("Tamil Nadu", "Tamil Nādu"),
                                ("Dadra and Nagar Haveli and Daman and Diu", "Dādra and Nagar Haveli and Damān and Diu")):
            self.assertEqual(state_key(plain), state_key(accented))
        self.assertEqual(state_key("Daman and Diu"), state_key("Dadra & Nagar Haveli"))
        self.assertEqual("राजस्थान", fold("राजस्थान"))            # marks in other scripts are part of the word
        base = [base_row(1, name="Larkspur Hospital", city="North Town", state="Rajasthan")]
        externals = [ext(1, "Larkspur Hospital", snapshot(), city="North Town", state="Rājasthān")]
        pair = run(base, envelope([snapshot()], externals))["candidates"][0]
        self.assertEqual("agree", pair["signals"]["state"])
        self.assertNotIn("state_conflict", pair["flags"])


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
        handles = ["synthetic:base:002", "synthetic:base:001"]
        good = [{"original_unique_id": "R-1", "multiplicity": 2, "facility_ids": handles, "group_id": "not checked",
                 "source_row_sha256": digest(base[0]["source_row"]), "meaning": "Interchangeable occurrences."}]
        metadata = {"mapping": {"id": "registry_id", "name": "name", "state": "state"}, "row_count": 5,
                    "base_file_sha256": digest(base)}
        for sidecar in (good, {"groups": good}):
            self.assertEqual([frozenset(handles)], [g["handles"] for g in sidecar_groups(sidecar)])
            detail = execute_national(base, [batch], source_metadata=metadata, duplicate_sidecar=sidecar)[
                "national_report"]["identical_payload_groups_detail"]
            self.assertEqual(("agrees with the base", ["group_id", "meaning"]),
                             (detail["sidecar"], detail["sidecar_fields_not_verified"]))
        run(base, batch, duplicate_sidecar=[sorted(handles)])           # bare handle arrays declare nothing else
        with self.assertRaisesRegex(MatchingError, "sidecar disagrees"):
            run(base, batch, duplicate_sidecar=[["synthetic:base:001", "synthetic:base:003"]])
        with self.assertRaisesRegex(MatchingError, "sidecar disagrees"):
            run(base, batch, duplicate_sidecar=[])
        with self.assertRaisesRegex(MatchingError, "two or more distinct"):
            sidecar_groups([["synthetic:base:001"]])
        with self.assertRaisesRegex(MatchingError, "expected 2"):
            run(base, batch, expect_duplicate_groups=2)
        run(base, batch, expect_duplicate_groups=1)

    def test_declared_original_id_and_multiplicity_are_verified(self):
        base, batch = data()
        handles = ["synthetic:base:001", "synthetic:base:002"]
        metadata = {"mapping": {"id": "registry_id", "name": "name", "state": "state"}, "row_count": 5,
                    "base_file_sha256": digest(base)}
        with_metadata = lambda sidecar: execute_national(base, [batch], source_metadata=metadata, duplicate_sidecar=sidecar)
        with self.assertRaisesRegex(MatchingError, "differs from the original ID"):
            with_metadata([{"original_id": "R-999", "multiplicity": 2, "row_handles": handles}])
        with self.assertRaisesRegex(MatchingError, "multiplicity differs"):
            with_metadata([{"original_id": "R-1", "multiplicity": 999, "row_handles": handles}])
        with self.assertRaisesRegex(MatchingError, "differs from the original ID"):
            with_metadata([{"original_unique_id": "R-3", "facility_ids": handles}])
        with self.assertRaisesRegex(MatchingError, "hash of the group's original row"):
            with_metadata([{"original_unique_id": "R-1", "facility_ids": handles, "source_row_sha256": "0" * 64}])
        with self.assertRaisesRegex(MatchingError, "must be an integer"):
            with_metadata([{"original_id": "R-1", "multiplicity": "2", "row_handles": handles}])
        with self.assertRaisesRegex(MatchingError, "cannot be verified"):      # no ID column is known without metadata
            run(base, batch, duplicate_sidecar=[{"original_id": "R-1", "row_handles": handles}])


class NationalRunTests(unittest.TestCase):
    def test_copies_share_one_result_and_confirm_nothing_automatically(self):
        base, batch = data()
        result = run(base, batch, policy=POLICY)
        rows = {r["facility_id"]: r for r in result["base_rows"]}
        self.assertEqual([row["facility_id"] for row in base], [r["facility_id"] for r in result["base_rows"]])
        # The registry ID appears twice in the full base, so it proves nothing; both copies carry one shared result.
        for fid in ("synthetic:base:001", "synthetic:base:002"):
            self.assertEqual(("ambiguous", "synthetic:base:001", 2, [], 1),
                             (rows[fid]["outcome"], rows[fid]["matched_as"], rows[fid]["duplicate_multiplicity"],
                              rows[fid]["confirmed_external_facility_ids"], rows[fid]["candidate_count"]))
            self.assertEqual(result["duplicate_groups"][0]["group_id"], rows[fid]["duplicate_group"])
        pair = [c for c in result["candidates"] if c["facility_id"] == "synthetic:base:001"][0]
        self.assertEqual(("identifier_not_unique", 0, False),
                         (pair["review_reason"], pair["other_bases_for_external"], "ambiguous_campus" in pair["flags"]))
        self.assertEqual(1, result["national_report"]["identical_payload_groups_detail"]["with_identifier_confirmation_withheld"])
        # A row without copies still confirms on its unique identifier.
        self.assertEqual(("confirmed", ["synthetic:external:003"], None, 1),
                         (rows["synthetic:base:004"]["outcome"], rows["synthetic:base:004"]["confirmed_external_facility_ids"],
                          rows["synthetic:base:004"]["duplicate_group"], rows["synthetic:base:004"]["duplicate_multiplicity"]))
        self.assertEqual({"synthetic:base:004"}, {m["facility_id"] for m in result["batch"]["facility_matches"]
                                                  if m["status"] == "confirmed"})
        # The envelope names the representative only; the other handle is reached through base_rows.
        self.assertEqual({"synthetic:base:001", "synthetic:base:003", "synthetic:base:004"},
                         {m["facility_id"] for m in result["batch"]["facility_matches"]})
        self.assertEqual("candidate_only", rows["synthetic:base:003"]["outcome"])
        self.assertEqual("unmatched", rows["synthetic:base:005"]["outcome"])

    def test_d_validator_accepts_the_envelope_on_the_full_base(self):
        """Both normal entry points, with every original row given to each."""
        base, batch = data()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "in").mkdir()
            files = {"base": tmp / "in/base.json", "ext": tmp / "in/ext.json", "map": tmp / "in/map.json",
                     "policy": tmp / "in/policy.json"}
            for name, value in (("base", base), ("ext", batch), ("map", mapping(base)), ("policy", POLICY)):
                files[name].write_text(json.dumps(value), encoding="utf-8")
            matched = subprocess.run([sys.executable, "-m", "research.matching.national", "--base", str(files["base"]),
                                      "--external", str(files["ext"]), "--base-mapping", str(files["map"]),
                                      "--identity-policy", str(files["policy"]), "--expect-duplicate-groups", "1",
                                      "--output-dir", str(tmp / "out")], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(0, matched.returncode, matched.stderr)
            self.assertEqual({"ambiguous": 2, "candidate_only": 1, "confirmed": 1, "unit": "original rows", "unmatched": 1},
                             json.loads(matched.stdout)["outcomes"])
            validated = subprocess.run([sys.executable, str(ROOT / "databricks/enrichment/validate_batch.py"),
                                        "--base", str(files["base"]), "--batch", str(files["ext"]),
                                        "--batch", str(tmp / "out/batch.json"), "--identity-policy", str(files["policy"]),
                                        "--as-of", "2026-11-21"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)

    def test_report_keeps_both_denominators_and_every_row(self):
        base, batch = data()
        before = digest(base)
        report = run(base, batch, policy=POLICY)["national_report"]
        self.assertEqual(before, digest(base))
        self.assertEqual({"original_rows": 5, "distinct_payloads": 4, "original_rows_in_base_file": 5,
                          "identical_payload_groups": 1, "rows_in_identical_payload_groups": 2},
                         report["denominators"])
        self.assertEqual({"unit": "original rows", "confirmed": 1, "ambiguous": 2, "candidate_only": 1, "unmatched": 1},
                         report["outcomes"])
        self.assertEqual({"unit": "distinct payloads", "confirmed": 1, "ambiguous": 1, "candidate_only": 1,
                          "unmatched": 1}, report["outcomes_distinct_payloads"])
        state = report["by_state"]["rajasthan"]
        self.assertEqual((3, 2, 2, 1, 0), (state["original_rows"], state["distinct_payloads"], state["ambiguous"],
                                           state["candidate_only"], state["unmatched"]))
        self.assertEqual(sum(s["original_rows"] for s in report["by_state"].values()), 5)
        directory, other = report["by_source"]["synthetic_directory"], report["by_source"]["synthetic_map"]
        self.assertEqual((2, 2, 5, 1, 2, 2), (directory["reference_rows"], directory["reference_rows_retrieved"],
                                              directory["original_rows"], directory["confirmed"],
                                              directory["ambiguous"], directory["unmatched"]))
        self.assertEqual((1, 4), (other["candidate_only"], other["unmatched"]))
        for entry in list(report["by_state"].values()) + list(report["by_source"].values()):
            self.assertEqual(entry["original_rows"], sum(entry[o] for o in ("confirmed", "ambiguous",
                                                                           "candidate_only", "unmatched")))
        self.assertEqual({"0": 1, "1": 4}, {k: v for k, v in report["source_overlap"].items() if k != "unit"})
        self.assertEqual(1, report["input_problems"]["by_problem"]["name_missing"])

    def test_state_column_text_that_is_not_a_state_is_bucketed(self):
        base, batch = data()
        base[2]["source_row"]["state"] = "North Town"                    # a city in the state column
        base[3]["source_row"]["state"] = None
        report = run(base, batch)["national_report"]
        self.assertEqual({"rajasthan", "gujarat", "(label is not a state or union territory)", "(no state label)"},
                         set(report["by_state"]))
        self.assertEqual(1, report["by_state"]["(label is not a state or union territory)"]["original_rows"])
        self.assertEqual(5, sum(s["original_rows"] for s in report["by_state"].values()))

    def test_a_label_that_is_not_a_state_is_unknown_for_matching(self):
        """A city in the state column used to conflict with every candidate's state."""
        postal = [{"pin": "302001", "statename": STATE}, {"pin": "302001", "statename": STATE},
                  {"pin": "380001", "statename": STATE}, {"pin": "380001", "statename": OTHER},
                  {"pin": "999001", "statename": "Atlantis"}]
        base = [base_row(1, name="Larkspur Hospital", city="North Town", state="North Town", pin="302001"),
                base_row(2, name="Marigold Hospital", city="North Town", state=STATE, pin="380001"),
                base_row(3, name="Juniper Clinic", city="East Town", state=None, pin="999001"),
                base_row(4, name="Quillon Clinic", city="East Town", state=OTHER, pin="302001"),
                base_row(5, name="Tamarind Clinic", city="East Town", state=OTHER, pin="111111"),
                base_row(6, name="Saffron Clinic", city="East Town", state=OTHER, pin=None)]
        externals = [ext(1, "Larkspur Hospital", snapshot(), city="North Town", state=STATE)]
        result = run(base, envelope([snapshot()], externals), postal=postal,
                     postal_mapping={"pin": "pin", "state": "statename"})
        pair = result["candidates"][0]
        self.assertEqual(("synthetic:base:001", "unknown"), (pair["facility_id"], pair["signals"]["state"]))
        self.assertNotIn("state_conflict", pair["flags"])
        rows = {r["facility_id"][-1]: r for r in result["base_rows"]}
        self.assertEqual([("(label is not a state or union territory)", None, "rajasthan", {"label": "not_a_state", "pin": "exact"}),
                          ("rajasthan", "rajasthan", None, {"label": "state", "pin": "pin_spans_states"}),
                          ("(no state label)", None, None, {"label": "missing", "pin": "pin_state_not_recognised"}),
                          ("gujarat", "gujarat", "rajasthan", {"label": "state", "pin": "exact"}),
                          ("gujarat", "gujarat", None, {"label": "state", "pin": "pin_not_in_postal_directory"}),
                          ("gujarat", "gujarat", None, {"label": "state", "pin": "pin_missing_or_invalid"})],
                         [tuple(rows[n][k] for k in ("state", "state_for_matching", "state_from_pin", "state_provenance"))
                          for n in "123456"])
        self.assertIn("state_label_not_a_state", rows["1"]["input_problems"])
        self.assertIn("state_label_missing", rows["3"]["input_problems"])
        self.assertNotIn("base_geography_disagreement", rows["1"]["conflicts"])   # a malformed label is not a disagreement
        self.assertIn("base_geography_disagreement", rows["4"]["conflicts"])      # a real state that its PIN contradicts
        resolution = result["national_report"]["state_resolution"]
        self.assertEqual({"agree": 0, "disagree": 1}, resolution["label_is_a_state_and_pin_is_exact"])
        self.assertEqual((1, 1, 4), tuple(resolution["by_label"][k]["original_rows"] for k in ("not_a_state", "missing", "state")))
        self.assertEqual(1, resolution["by_label"]["not_a_state"]["exact"])
        self.assertNotIn("north town", json.dumps(result["national_report"]).casefold().replace("north town clinic", ""))
        without = run(base, envelope([snapshot()], externals))["base_rows"][0]
        self.assertEqual((None, {"label": "not_a_state", "pin": "no_postal_reference"}),
                         (without["state_from_pin"], without["state_provenance"]))

    def test_postal_state_evidence_must_be_complete_to_establish_anything(self):
        """An office with no state, or with a label that is not a state, proves neither
        a second state nor an exact one, and never a disagreement with the row."""
        postal = [{"pin": "100001", "statename": "Atlantis"},                                   # only an unrecognised label
                  {"pin": "100002", "statename": STATE}, {"pin": "100002", "statename": "NA"},   # recognised + unrecognised
                  {"pin": "100003", "statename": STATE}, {"pin": "100003", "statename": None},   # recognised + blank office
                  {"pin": "100004", "statename": None}, {"pin": "100004", "statename": " "},     # present, no state at all
                  {"pin": "100005", "statename": STATE},                                         # genuine other state
                  {"pin": "100006", "statename": STATE}, {"pin": "100006", "statename": OTHER},  # genuinely two states
                  {"pin": "100008", "statename": "The Dadra and Nagar Haveli and Daman and Diu"}]
        base = [base_row(n, name=f"Clinic {n}", city="East Town", state=OTHER, pin=f"10000{n}") for n in range(1, 8)]
        base.append(base_row(8, name="Clinic 8", city="East Town", state="Daman and Diu", pin="100008"))
        result = run(base, envelope([snapshot()], [ext(1, "Unrelated Hospital", snapshot(), state=STATE)]),
                     postal=postal, postal_mapping={"pin": "pin", "state": "statename"})
        rows = {r["facility_id"][-1]: r for r in result["base_rows"]}
        self.assertEqual({"1": (None, "pin_state_not_recognised"), "2": (None, "pin_state_incomplete"),
                          "3": (None, "pin_state_incomplete"), "4": (None, "pin_state_missing_in_directory"),
                          "5": ("rajasthan", "exact"), "6": (None, "pin_spans_states"),
                          "7": (None, "pin_not_in_postal_directory"),
                          "8": ("dadra and nagar haveli and daman and diu", "exact")},
                         {n: (r["state_from_pin"], r["state_provenance"]["pin"]) for n, r in rows.items()})
        self.assertEqual(["5"], [n for n, r in rows.items() if "base_geography_disagreement" in r["conflicts"]])
        self.assertEqual(["5"], [n for n, r in rows.items() if "state_disagrees_with_pin" in r["input_problems"]])
        self.assertEqual(["1", "2", "3", "4"], [n for n, r in rows.items() if "pin_state_evidence_incomplete" in r["input_problems"]])
        resolution = result["national_report"]["state_resolution"]
        self.assertEqual({"agree": 1, "disagree": 1}, resolution["label_is_a_state_and_pin_is_exact"])
        self.assertEqual((2, 1, 2, 1, 1, 1), tuple(resolution["by_label"]["state"][k] for k in (
            "exact", "pin_spans_states", "pin_state_incomplete", "pin_state_not_recognised",
            "pin_state_missing_in_directory", "pin_not_in_postal_directory")))
        profile = result["geography_report"]["postal_profile"]
        self.assertEqual((2, 2, 1), (profile["pins_with_unrecognised_state_label"], profile["pins_with_office_without_state"],
                                     profile["pins_with_multiple_states"]))

    def test_missed_sample_is_repeatable_and_never_lists_a_copy_twice(self):
        base, batch = data()
        extra = base_row(6, name="Quillon Sanatorium", city="West Town", state=STATE)
        base += [extra, twin(extra, 7)]
        one, two = run(base, batch)["missed_sample"], run(list(reversed(base)), batch)["missed_sample"]
        self.assertEqual(one, two)
        self.assertEqual((2, 2), (one["available"], one["sampled"]))
        self.assertEqual({"synthetic:base:005", "synthetic:base:006"},
                         {r["facility_id"] for r in one["rows"]})
        self.assertEqual(1, run(base, batch, missed_sample_size=1)["missed_sample"]["sampled"])

    def test_state_scope_keeps_copies_together(self):
        base, batch = data()
        result = run(base, batch, state="RAJASTHAN ")
        self.assertEqual(["synthetic:base:001", "synthetic:base:002", "synthetic:base:003"],
                         [r["facility_id"] for r in result["base_rows"]])
        report = result["national_report"]
        self.assertEqual((3, 2, 5), (report["denominators"]["original_rows"], report["denominators"]["distinct_payloads"],
                                     report["denominators"]["original_rows_in_base_file"]))
        self.assertEqual("rajasthan", report["scope"]["state"])
        with self.assertRaisesRegex(MatchingError, "no base row carries"):
            run(base, batch, state="Nowhere")

    def test_source_metadata_is_checked_against_the_whole_base(self):
        base, batch = data()
        metadata = {"mapping": {"id": "registry_id", "name": "name", "state": "state"}, "row_count": 5,
                    "base_file_sha256": digest(base)}
        result = execute_national(base, [batch], source_metadata=metadata, mapping={"city": "source_row.city"})
        self.assertEqual(["city", "name", "state"], result["national_report"]["run_report"]["base_mapping_roles"])
        with self.assertRaisesRegex(MatchingError, "row_count differs"):
            execute_national(base, [batch], source_metadata=dict(metadata, row_count=4))
        with self.assertRaisesRegex(MatchingError, "base_file_sha256: differs from the base file"):
            execute_national(base, [batch], source_metadata=dict(metadata, base_file_sha256="0" * 64))
        with self.assertRaisesRegex(MatchingError, "must record the hash"):
            execute_national(base, [batch], source_metadata={k: v for k, v in metadata.items() if k != "base_file_sha256"})
        # The CLI compares the recorded hash with the bytes of the file it was given.
        with self.assertRaisesRegex(MatchingError, "differs from the base file"):
            execute_national(base, [batch], source_metadata=metadata, base_file_sha256="f" * 64)

    def test_scope_does_not_hide_an_identifier_shared_outside_it(self):
        base, batch = data()
        base[2]["source_row"]["registry_id"] = "R-4"          # an in-scope row now shares the other state's ID
        rows = {r["facility_id"]: r for r in run(base, batch, policy=POLICY, state=OTHER)["base_rows"]}
        self.assertEqual("ambiguous", rows["synthetic:base:004"]["outcome"])

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
            files["meta"] = tmp / "in/source_metadata.json"
            metadata = {"mapping": {"id": "registry_id", "name": "name", "state": "state"}, "row_count": len(base),
                        "base_file_sha256": hashlib.sha256(files["base"].read_bytes()).hexdigest()}
            files["meta"].write_text(json.dumps(metadata), encoding="utf-8")
            before = {k: p.read_bytes() for k, p in files.items()}
            command = [sys.executable, "-m", "research.matching.national", "--base", str(files["base"]),
                       "--external", str(files["ext"]), "--base-mapping", str(files["map"]),
                       "--source-metadata", str(files["meta"]),
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
            wrong = tmp / "wrong_metadata.json"
            wrong.write_text(json.dumps(dict(metadata, base_file_sha256="0" * 64)), encoding="utf-8")
            stale = subprocess.run([wrong if part == str(files["meta"]) else part for part in command]
                                   + ["--output-dir", str(tmp / "three")], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(1, stale.returncode)
            self.assertIn("base_file_sha256: differs from the base file", stale.stderr)
            self.assertFalse((tmp / "three").exists())


if __name__ == "__main__":
    unittest.main()
