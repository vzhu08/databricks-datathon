"""Candidate-only fixtures for the national premises and locality replay."""
import unittest

from matching_fixtures import base_row, envelope, ext, mapping, snapshot
from research.matching.common import MatchingError, digest
from research.matching.national import NO_STATE, execute_national


class PremisesReplayTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = snapshot()

    def reference(self, number, name, **fields):
        return ext(number, name, self.snapshot, **fields)

    def replay(self, base, references, **kwargs):
        return execute_national(base, [envelope([self.snapshot], references)], mapping(base),
                                premises_mapping={"address": ["source_row.address", "source_row.address2"],
                                                  "description": "source_row.description"},
                                sample_size=0, missed_sample_size=0, **kwargs)

    @staticmethod
    def original(number, name="Tamarind Crest Hospital", **fields):
        return base_row(number, **{"name": name, "address": None, "address2": None,
                                  "description": None, **fields})

    def stages(self, result, row):
        return result["candidate_stages"][row["facility_id"]]

    def test_exact_plot_and_street_ranks_the_correct_branch_within_one_pin(self):
        row = self.original(1, address="Plot No. 4-B", address2="Rainwood Rd, Blue Ward", pin="123456")
        wrong = self.reference(1, "Tamarind Crest Hospital", pin="123456",
                               address_original="Plot 14, Rainwood Road, Blue Ward")
        right = self.reference(2, "Tamarind Crest Hospital", pin="123456",
                               address_original="Plot 4-B, Rainwood Road, Blue Ward")
        result = self.replay([row], [wrong, right])
        candidates = self.stages(result, row)["pre_cut"]
        self.assertEqual([c["external_facility_id"] for c in candidates],
                         [right["external_facility_id"], wrong["external_facility_id"]])
        self.assertEqual(candidates[0]["retrieval_reason"], "exact_structured_address")
        self.assertIn("premises_conflict", candidates[1]["flags"])
        self.assertEqual(result["base_rows"][0]["outcome"], "ambiguous")
        proof = result["premises_evidence"]["base"][row["facility_id"]]
        self.assertEqual(proof["premises"], [("plot", "4-b")])
        self.assertEqual([o["field"] for o in proof["observations"][:2]],
                         ["source_row.address", "source_row.address2"])
        self.assertEqual(proof["observations"][0]["raw"], "Plot No. 4-B")

    def test_premises_and_locality_work_without_street_and_do_not_use_landmarks(self):
        row = self.original(1, address="Plot 7", address2="Blue Ward")
        right = self.reference(1, "Tamarind Crest Hospital", address_original="Plot 7, Blue Ward")
        landmark = self.reference(2, "Foxglove Infirmary", address_original="Opposite Plot 7, Blue Ward")
        result = self.replay([row], [right, landmark])
        stage = self.stages(result, row)
        self.assertEqual(stage["scored"], 1)
        self.assertEqual(stage["pre_cut"][0]["retrieval_reason"], "premises_locality")

    def test_single_disagreeing_address_and_structured_pins_open_geography_review(self):
        address = "Plot 4, Rainwood Road"
        for left, right in (("address", "address_original"), ("address", "pin"), ("pin", "address_original")):
            with self.subTest(base_field=left, external_field=right):
                base_fields = {"address": address}
                base_fields[left] = f"{address}, 123456" if left == "address" else "123456"
                ref_fields = {"address_original": address}
                ref_fields[right] = f"{address}, 654321" if right == "address_original" else "654321"
                row = self.original(1, **base_fields)
                reference = self.reference(1, "Tamarind Crest Hospital", **ref_fields)
                result = self.replay([row], [reference])
                pair = self.stages(result, row)["pre_cut"][0]
                self.assertEqual(pair["signals"]["pin"], "unknown")
                self.assertTrue(pair["signals"]["premises"]["observed_pin_conflict"])
                self.assertIn("pin_conflict", pair["flags"])
                self.assertNotIn("geography_unknown", pair["flags"])
                self.assertEqual(pair["retrieval_reason"], "exact_structured_address")
                self.assertEqual(pair["review_reason"], "geography_conflict")
                self.assertEqual(result["base_rows"][0]["conflicts"], ["candidate_geography_conflict"])
                match = result["batch"]["facility_matches"][0]
                self.assertEqual(match["status"], "candidate")
                self.assertIn("Observed postal PINs disagree", match["rationale"])
                evidence = result["premises_evidence"]
                for side, record_id, field, raw in (
                    ("base", row["facility_id"], f"source_row.{left}", base_fields[left]),
                    ("external", reference["external_facility_id"], right, ref_fields[right]),
                ):
                    self.assertIn((field, raw), [(o["field"], o["raw"])
                                               for o in evidence[side][record_id]["observations"]])
                self.assertEqual(pair["record_locator"], "synthetic row 1")

    def test_observed_pin_conflict_penalizes_rank_and_preserves_a_rival_below_cutoff(self):
        address = "Plot 4, Rainwood Road"
        row = self.original(1, address=address, address2="123456")
        refs = [self.reference(i, "Tamarind Crest Hospital", address_original=address,
                               pin="654321" if i == 1 else "123456") for i in range(1, 7)]
        result = self.replay([row], refs)
        pairs = self.stages(result, row)["pre_cut"]
        self.assertEqual([p["source_record_id"] for p in pairs], ["EX-002", "EX-003", "EX-004", "EX-005", "EX-006", "EX-001"])
        rival = pairs[-1]
        self.assertEqual(rival["stage"], "rank_cut")
        self.assertTrue({"pin_conflict", "ambiguous_campus"} <= set(rival["flags"]))
        self.assertEqual(rival["review_reason"], "ambiguous_campus")
        self.assertEqual(rival["retrieval_reason"], "exact_structured_address")
        self.assertEqual(result["base_rows"][0]["outcome"], "ambiguous")

    def test_multiple_pins_on_one_side_do_not_establish_a_pair_disagreement(self):
        row = self.original(1, address="Plot 4, Rainwood Road, 123456", address2="234567")
        reference = self.reference(1, "Tamarind Crest Hospital", address_original="Plot 4, Rainwood Road, 654321")
        result = self.replay([row], [reference])
        pair = self.stages(result, row)["pre_cut"][0]
        self.assertIn("multiple_observed_pins", pair["flags"])
        self.assertNotIn("pin_conflict", pair["flags"])
        self.assertEqual(pair["review_reason"], "geography_conflict")

    def test_different_hospitals_sharing_a_building_and_point_keep_proximity_reason(self):
        row = self.original(1, address="Plot 4, Rainwood Road", lat=22.12345, lon=77.12345)
        other = self.reference(1, "Foxglove Infirmary", address_original="Plot 4, Rainwood Road",
                               latitude=22.12345, longitude=77.12345)
        result = self.replay([row], [other])
        pair = self.stages(result, row)["pre_cut"][0]
        self.assertIn("exact_structured_address", pair["block_stages"])
        self.assertIsNone(pair["signals"]["premises"]["admission"])
        self.assertIn("proximity_only", pair["flags"])
        self.assertEqual(result["batch"]["facility_matches"][0]["status"], "candidate")
        separate = self.replay([{**row, "source_row": {**row["source_row"], "lat": None, "lon": None}}], [other])
        trace = self.stages(separate, row)
        self.assertEqual(trace["pre_cut"], [])
        rejected = trace["scoring_rejections"]["no_qualifying_name_identifier_phone_or_proximity"]
        self.assertIn(other["external_facility_id"], [separate["stage_reference_ids"][i] for i in rejected])

    def test_documented_alternate_script_alias_retains_locator(self):
        row = self.original(1, "Tamarind Crest Hospital (Blue Ward)", city="Rainwood")
        other = self.reference(1, "इमली शिखर अस्पताल", city="Rainwood")
        result = self.replay([row], [other], attributes={
            other["external_facility_id"]: {"aliases": ["Tamarind Crest Hospital (Blue Ward)"]}})
        pair = self.stages(result, row)["pre_cut"][0]
        self.assertEqual(pair["retrieval_reason"], "documented_branch_alias")
        self.assertTrue(pair["signals"]["premises"]["documented_alias"])
        ext_row = result["premises_evidence"]["external"][other["external_facility_id"]]
        self.assertEqual(ext_row["record_locator"], "synthetic row 1")
        self.assertIn("blue ward", ext_row["qualifiers"])

    def test_missing_geography_and_multi_state_pin_remain_visible(self):
        rows = [self.original(1), self.original(2, "Foxglove Infirmary", pin="234567", state="Rainwood")]
        references = [self.reference(1, "Tamarind Crest Hospital"),
                      self.reference(2, "Foxglove Infirmary", pin="234567", state="Karnataka")]
        post = [{"pin": "234567", "state": state, "district": district, "office": office}
                for state, district, office in [("Karnataka", "Fern", "Fern A"), ("Goa", "Clover", "Clover B")]]
        result = self.replay(rows, references, postal=post, postal_mapping={key: key for key in post[0]})
        self.assertEqual([r["state"] for r in result["base_rows"]],
                         [NO_STATE, "(label is not a state or union territory)"])
        self.assertEqual(result["base_rows"][1]["state_provenance"]["pin"], "pin_spans_states")
        self.assertEqual(self.stages(result, rows[0])["pre_cut"][0]["retrieval_reason"], "distinctive_name_fallback")
        entry = result["premises_evidence"]["postal_by_pin"]["234567"]
        self.assertEqual(entry["districts"], ["clover", "fern"])
        self.assertEqual(entry["states"], ["goa", "karnataka"])
        self.assertEqual([o["row_index"] for o in entry["offices"]], [0, 1])
        self.assertEqual([o["office"] for o in entry["offices"]], ["Fern A", "Clover B"])

    def test_distinctive_name_and_district_cross_state_needs_review(self):
        row = self.original(1, "Tamarind Crest", address="Dist. Rainwood", state="Goa")
        other = self.reference(1, "Tamarind Crest Hospital", state="Karnataka")
        result = self.replay([row], [other], attributes={other["external_facility_id"]: {"district": "Rainwood"}})
        pair = self.stages(result, row)["pre_cut"][0]
        self.assertEqual(pair["retrieval_reason"], "distinctive_name_district")
        self.assertIsNone(pair["legacy_admission"])
        self.assertEqual(pair["review_reason"], "geography_conflict")

    def test_competing_coordinates_and_mixed_campus_keep_open_review(self):
        row = self.original(1, address="Plot 4, Rainwood Road", lat=22.12345, lon=77.12345,
                            description="Two campuses operate here. Branches are listed separately.")
        other = self.reference(1, "Tamarind Crest Hospital", address_original="Plot 4, Rainwood Road",
                               latitude=26.12345, longitude=78.12345)
        result = self.replay([row], [other])
        pair = self.stages(result, row)["pre_cut"][0]
        self.assertIn("mixed_campus_description", pair["flags"])
        self.assertIn("competing_coordinates", pair["flags"])
        self.assertIsNone(pair["signals"]["premises"]["admission"])
        self.assertEqual(result["base_rows"][0]["outcome"], "ambiguous")
        self.assertTrue({"ambiguous_campus", "base_mixed_campus_address"} <=
                        {r["reason_code"] for r in result["batch"]["review_queue"]})

    def test_pre_cut_serious_alternatives_and_identical_copies_survive(self):
        first = self.original(2, address="Plot 9, Rainwood Road", pin="123456")
        copy = {**first, "facility_id": self.original(1)["facility_id"]}
        base = [first, copy]
        references = [self.reference(i, "Tamarind Crest Hospital",
                                     address_original=f"Plot {i}, Rainwood Road", pin="123456")
                      for i in range(1, 10)]
        before = digest(base)
        result = self.replay(base, references, expect_duplicate_groups=1)
        self.assertEqual(digest(base), before)
        self.assertEqual([r["facility_id"] for r in result["base_rows"]], [r["facility_id"] for r in base])
        trace = self.stages(result, copy)["pre_cut"]
        self.assertEqual(len(result["candidate_stages"]), 1)
        self.assertEqual(len(trace), 9)
        self.assertEqual(trace[0]["source_record_id"], "EX-009")
        self.assertEqual(trace[0]["other_serious_candidates_for_base"], 8)
        self.assertEqual(trace[0]["other_bases_for_external"], 0)
        self.assertEqual([p["pre_cut_rank"] for p in trace if p["stage"] == "rank_cut"], [6, 7, 8, 9])
        self.assertTrue(all(p["serious"] for p in trace))
        self.assertEqual([r["candidate_count"] for r in result["base_rows"]], [5, 5])
        self.assertEqual(result["national_report"]["outcomes"]["confirmed"], 0)

    def test_premises_replay_refuses_identity_policy(self):
        policy = {"fictional": {"base_field": "name", "external_field": "name_original",
                                "source_keys": [self.snapshot["source_key"]]}}
        with self.assertRaisesRegex(MatchingError, "candidate-only mode"):
            self.replay([self.original(1)], [self.reference(1, "Tamarind Crest Hospital")], policy=policy)
