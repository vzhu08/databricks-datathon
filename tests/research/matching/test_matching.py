import copy
import json
import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from matching_fixtures import (ROOT, base_row, by_pair, envelope, ext, mapping, match_for, snapshot)
from merge import plan_merge

from research.matching.common import MatchingError, digest, load, stable_id  # noqa: E402
from research.matching.normalize import name_evidence, phone_keys, pin_key, state_key, tokens
from research.matching.run import execute

STATE = "Synthetic State"


def run(base, externals, snap=None, **kwargs):
    snap = snap or snapshot()
    snaps = kwargs.pop("snapshots", [snap])
    return execute(base, [envelope(snaps, externals)], mapping=kwargs.pop("mapping", mapping(base)), **kwargs)


class SharedFixtureTests(unittest.TestCase):
    def test_shared_synthetic_fixture_runs_and_leaves_base_untouched(self):
        base = load(ROOT / "contracts/fixtures/enrichment_base.json")
        before = copy.deepcopy(base)
        result = execute(base, [load(ROOT / "contracts/fixtures/enrichment.json")])
        self.assertEqual(before, base)
        self.assertEqual(2, result["report"]["base"]["denominator"])
        self.assertEqual(result["report"]["base"]["sha256_before"], result["report"]["base"]["sha256_after"])
        statuses = {m["status"] for m in result["batch"]["facility_matches"]}
        self.assertEqual({"candidate"}, statuses)  # three same-name campuses: nothing may confirm
        self.assertEqual(1, by_pair(result)[("synthetic:base:001", "synthetic:external:001")]["rank"])
        self.assertEqual(1, by_pair(result)[("synthetic:base:002", "synthetic:external:002")]["rank"])
        # C emits only its own tables.
        self.assertEqual([], result["batch"]["source_snapshots"])
        self.assertEqual([], result["batch"]["external_facilities"])
        self.assertEqual([], result["batch"]["facility_evidence"])

    def test_export_shape_needs_an_observed_mapping(self):
        base = [base_row(1, name="Example Health Centre")]
        with self.assertRaisesRegex(MatchingError, "Refusing to guess"):
            execute(base, [envelope([snapshot()], [])])
        with self.assertRaisesRegex(MatchingError, "unknown role"):
            execute(base, [envelope([snapshot()], [])], mapping={"hospital_name": "source_row.name"})
        with self.assertRaisesRegex(MatchingError, "no base row has"):
            execute(base, [envelope([snapshot()], [])], mapping={"name": "source_row.title"})


class SourceMetadataTests(unittest.TestCase):
    def test_d_prepared_package_supplies_the_mapping(self):
        sys.path.insert(0, str(ROOT / "databricks/enrichment"))
        from source_inspection import map_base
        rows = [{"source_id": "0007", "source_name": "Larkspur Hospital", "st": "Synthetic State", "town": "North Town"},
                {"source_id": "0008", "source_name": "Marigold Hospital", "st": "Synthetic State", "town": "North Town"}]
        base = map_base(rows, "source_id", "synthetic.fixture.facilities")
        metadata = {"mapping": {"id": "source_id", "name": "source_name", "state": "st", "evidence": []},
                    "row_count": 2}
        externals = [ext(1, "Larkspur Hospital", snapshot(), city="North Town", state="Synthetic State")]
        result = execute(base, [envelope([snapshot()], externals)], source_metadata=metadata,
                         mapping={"city": "source_row.town"})
        self.assertEqual(["city", "name", "state"], result["report"]["base_mapping_roles"])
        pair = by_pair(result)[("0007", "synthetic:external:001")]   # leading-zero ID kept as text
        self.assertEqual(("agree", "agree"), (pair["signals"]["state"], pair["signals"]["place"]))
        self.assertEqual(rows[0], base[0]["source_row"])
        with self.assertRaisesRegex(MatchingError, "row_count differs"):
            execute(base, [envelope([snapshot()], externals)], source_metadata=dict(metadata, row_count=3))
        with self.assertRaisesRegex(MatchingError, "mapping object"):
            execute(base, [envelope([snapshot()], externals)], source_metadata={"row_count": 2})


class CandidateTests(unittest.TestCase):
    def test_same_name_different_campus_is_never_collapsed(self):
        base = [base_row(1, name="Example Health Centre", city="North Town", state=STATE, pin="900001"),
                base_row(2, name="Example Health Centre", city="South Town", state=STATE, pin="900002")]
        externals = [ext(1, "Example Health Centre", snapshot(), city="North Town", state=STATE, pin="900001"),
                     ext(2, "Example Health Centre", snapshot(), city="South Town", state=STATE, pin="900002")]
        result = run(base, externals)
        pairs = by_pair(result)
        self.assertEqual(4, len(pairs))
        self.assertEqual(1, pairs[("synthetic:base:001", "synthetic:external:001")]["rank"])
        self.assertEqual(1, pairs[("synthetic:base:002", "synthetic:external:002")]["rank"])
        self.assertIn("place_conflict", pairs[("synthetic:base:001", "synthetic:external:002")]["flags"])
        self.assertTrue(all("ambiguous_campus" in c["flags"] for c in pairs.values()))
        self.assertTrue(all(m["status"] == "candidate" and m["method"] == "candidate_generation"
                            and m["reviewer"] is None for m in result["batch"]["facility_matches"]))
        self.assertEqual(2, len(base))  # both campuses still present

    def test_alias_from_sidecar_and_base_column(self):
        base = [base_row(1, name="Rivergate Institute", aliases=["Old Mill Hospital"], city="North Town", state=STATE)]
        externals = [ext(1, "Old Mill Hospital", snapshot(), city="North Town", state=STATE),
                     ext(2, "Harbour Lane Clinic", snapshot(), city="North Town", state=STATE)]
        result = run(base, externals, attributes={"synthetic:external:002": {"aliases": ["Rivergate Institute"]}})
        pairs = by_pair(result)
        self.assertEqual(2, len(pairs))
        for c in pairs.values():
            self.assertIn("matched_via_alias", c["flags"])
            self.assertFalse(c["auto_confirmed"])
        with self.assertRaisesRegex(MatchingError, "not in the batches"):
            run(base, externals, attributes={"synthetic:external:999": {"aliases": ["x"]}})

    def test_misleading_acronym_is_weak_and_needs_geography(self):
        base = [base_row(1, name="ABG Hospital", city="North Town", state=STATE)]
        externals = [ext(1, "Alpha Beta Gamma Hospital", snapshot(), city="North Town", state=STATE),
                     ext(2, "Aster Bright Grove Hospital", snapshot(), city="North Town", state=STATE),
                     ext(3, "Amber Birch Glen Hospital", snapshot())]  # no geography: not retrieved
        result = run(base, externals)
        pairs = by_pair(result)
        self.assertEqual({"synthetic:external:001", "synthetic:external:002"}, {k[1] for k in pairs})
        for c in pairs.values():
            self.assertEqual("weak", c["signals"]["name_level"])
            self.assertIn("acronym_only", c["flags"])
            self.assertEqual("acronym_only", c["review_reason"])
        self.assertTrue(all(m["status"] == "candidate" for m in result["batch"]["facility_matches"]))

    def test_shared_switchboard_is_not_identity_but_direct_phone_retrieves(self):
        base = [base_row(n, name=name, phone="+91 11 5550 0100", city="North Town", state=STATE)
                for n, name in ((1, "Cedar Wing"), (2, "Maple Wing"), (3, "Willow Wing"))]
        base.append(base_row(4, name="Juniper House", phone="011-5550-0199"))
        externals = [ext(1, "Group Enquiry Desk", snapshot()), ext(2, "Cedar Wing Annexe", snapshot()),
                     ext(3, "Unrelated Name", snapshot())]
        attributes = {"synthetic:external:001": {"phones": ["01155500100"]},
                      "synthetic:external:002": {"phones": ["01155500100"]},
                      "synthetic:external:003": {"phones": ["1155500199"]}}
        result = run(base, externals, attributes=attributes)
        pairs = by_pair(result)
        # The shared number alone retrieves nothing; with a name it is flagged, never confirmed.
        self.assertNotIn(("synthetic:base:002", "synthetic:external:001"), pairs)
        flagged = pairs[("synthetic:base:001", "synthetic:external:002")]
        self.assertIn("shared_switchboard", flagged["flags"])
        self.assertTrue(flagged["signals"]["phone_switchboard"])
        direct = pairs[("synthetic:base:004", "synthetic:external:003")]
        self.assertEqual("phone", direct["retrieval_reason"])
        self.assertIn("phone_match", direct["flags"])
        self.assertTrue(all(m["status"] == "candidate" for m in result["batch"]["facility_matches"]))

    def test_name_only_and_proximity_only_stay_candidates(self):
        base = [base_row(1, name="Larkspur Hospital"),
                base_row(2, name="Quartz Clinic", lat=20.0, lon=77.0)]
        externals = [ext(1, "Larkspur Hospital", snapshot()),
                     ext(2, "Different Pharmacy", snapshot(), facility_type="pharmacy", latitude=20.0003, longitude=77.0),
                     ext(3, "Faraway Stores", snapshot(), latitude=20.003, longitude=77.0)]
        result = run(base, externals)
        pairs = by_pair(result)
        name_only = pairs[("synthetic:base:001", "synthetic:external:001")]
        self.assertIn("name_only", name_only["flags"])
        self.assertEqual("name_only", name_only["review_reason"])
        near = pairs[("synthetic:base:002", "synthetic:external:002")]
        self.assertEqual("proximity_only", near["retrieval_reason"])
        self.assertEqual("none", near["signals"]["name_level"])
        self.assertLess(near["signals"]["distance_m"], 100)
        self.assertNotIn(("synthetic:base:002", "synthetic:external:003"), pairs)  # ~330 m, no name evidence
        self.assertTrue(all(m["status"] == "candidate" for m in result["batch"]["facility_matches"]))
        off = run(base, externals, config={"proximity_only_m": 0})
        self.assertNotIn(("synthetic:base:002", "synthetic:external:002"), by_pair(off))

    def test_wrong_district_and_pin_are_flagged_and_other_state_is_dropped(self):
        base = [base_row(1, name="Larkspur Hospital", district="East District", state=STATE, pin="900001")]
        externals = [ext(1, "Larkspur Hospital", snapshot(), city="West District", state=STATE, pin="900009"),
                     ext(2, "Larkspur Hospital", snapshot(), city="Elsewhere", state="Other Synthetic State")]
        result = run(base, externals)
        pairs = by_pair(result)
        conflict = pairs[("synthetic:base:001", "synthetic:external:001")]
        self.assertLessEqual({"place_conflict", "pin_conflict"}, set(conflict["flags"]))
        self.assertEqual("geography_conflict", conflict["review_reason"])
        self.assertNotIn(("synthetic:base:001", "synthetic:external:002"), pairs)
        self.assertEqual("candidate", match_for(result, 1, 1)["status"])

    def test_missing_invalid_and_swapped_coordinates_keep_textual_candidates(self):
        base = [base_row(1, name="Larkspur Hospital", city="North Town", state=STATE, lat=None, lon=None),
                base_row(2, name="Marigold Hospital", city="North Town", state=STATE, lat="20.0", lon=77.0),
                base_row(3, name="Nettle Hospital", city="North Town", state=STATE, lat=77.0, lon=20.0),
                base_row(4, name="Orchid Hospital", city="North Town", state=STATE, lat=20.0, lon=None)]
        before = copy.deepcopy(base)
        externals = [ext(n, name, snapshot(), city="North Town", state=STATE, latitude=20.0, longitude=77.0)
                     for n, name in ((1, "Larkspur Hospital"), (2, "Marigold Hospital"), (3, "Nettle Hospital"),
                                     (4, "Orchid Hospital"))]
        result = run(base, externals)
        pairs = by_pair(result)
        for n in (1, 2, 3, 4):
            self.assertIn((f"synthetic:base:{n:03d}", f"synthetic:external:{n:03d}"), pairs)
        self.assertIsNone(pairs[("synthetic:base:001", "synthetic:external:001")]["signals"]["distance_m"])
        self.assertIsNone(pairs[("synthetic:base:002", "synthetic:external:002")]["signals"]["distance_m"])
        swapped = pairs[("synthetic:base:003", "synthetic:external:003")]["signals"]
        self.assertGreater(swapped["distance_m"], 1_000_000)          # measured on the ORIGINAL values
        self.assertEqual(0.0, swapped["distance_if_base_axes_swapped_m"])  # cue only
        self.assertEqual(before, base)                                 # nothing repaired in place
        geo = result["geography_report"]["base"]
        self.assertEqual(1, geo["flag_counts"]["possible_swapped_axes"])
        self.assertEqual(1, geo["flag_counts"]["coordinates_not_finite_numbers"])
        self.assertEqual(1, geo["flag_counts"]["coordinates_incomplete"])
        self.assertEqual(1, geo["flag_counts"]["coordinates_missing"])
        proposal = geo["proposed_corrections"][0]
        self.assertEqual({"latitude": 77.0, "longitude": 20.0}, proposal["original"])
        self.assertEqual((20.0, 77.0), (proposal["proposed"]["latitude"], proposal["proposed"]["longitude"]))
        reasons = {r["reason_code"] for r in result["batch"]["review_queue"]}
        self.assertLessEqual({"base_possible_swapped_axes", "base_coordinates_not_finite_numbers",
                              "base_coordinates_incomplete"}, reasons)

    def test_unknown_stays_unknown(self):
        base = [base_row(1, name="Larkspur Hospital")]
        result = run(base, [ext(1, "Larkspur Hospital", snapshot())])
        s = by_pair(result)[("synthetic:base:001", "synthetic:external:001")]["signals"]
        self.assertEqual(("unknown", "unknown", "unknown", "unknown"), (s["state"], s["place"], s["pin"], s["address"]))
        self.assertIsNone(s["distance_m"])
        self.assertEqual("unknown", s["distance_band"])
        self.assertIn("not supplied", result["geography_report"]["base"]["postal_context"])
        self.assertEqual(0, result["report"]["base"]["rows_without_any_candidate"])
        empty = run([base_row(1, name="Zinnia Hospital")], [ext(1, "Larkspur Hospital", snapshot())])
        self.assertEqual(1, empty["report"]["base"]["rows_without_any_candidate"])
        self.assertEqual([], empty["batch"]["facility_matches"])

    def test_generic_name_is_not_a_campus_name(self):
        self.assertEqual(("weak", "generic_name_equal"),
                         name_evidence(tokens("District Hospital"), tokens("District Hospital")))
        base = [base_row(1, name="District Hospital", state=STATE)]
        result = run(base, [ext(1, "District Hospital", snapshot(), state=STATE)])
        self.assertEqual([], result["batch"]["facility_matches"])  # state agreement alone is not enough

    def test_normalisation_helpers(self):
        self.assertEqual(["jln", "government", "hospital"], tokens("J.L.N. Govt. Hosp."))
        self.assertEqual("moderate", name_evidence(tokens("Larkspur Hospital Annexe"), tokens("Larkspur Annexe Wing Hospital"))[0])
        self.assertEqual("900001", pin_key("900001"))
        self.assertEqual("900001", pin_key(900001))
        self.assertIsNone(pin_key("0"))
        self.assertIsNone(pin_key(True))
        self.assertEqual(frozenset({"1155500100"}), phone_keys("+91 11 5550 0100"))
        self.assertEqual(state_key("Jammu & Kashmir"), state_key("jammu and kashmir"))


class IdentifierTests(unittest.TestCase):
    POLICY = {"synthetic_registry": {"base_field": "source_row.registry_id", "external_field": "source_record_id",
                                     "source_keys": ["synthetic_directory"]}}

    def base(self):
        return [base_row(1, name="Larkspur Hospital", registry_id="R-1", city="North Town", state=STATE),
                base_row(2, name="Marigold Hospital", registry_id="R-2", city="North Town", state=STATE)]

    def test_unambiguous_shared_identifier_confirms_and_d_accepts_it(self):
        base = self.base()
        externals = [ext(1, "Larkspur Hosp", snapshot(), source_record_id="R-1", city="North Town", state=STATE)]
        result = run(base, externals, policy=self.POLICY)
        row = match_for(result, 1, 1)
        self.assertEqual(("confirmed", "shared_identifier"), (row["status"], row["method"]))
        self.assertEqual({"namespace": "synthetic_registry", "value": "R-1", "base_field": "source_row.registry_id",
                          "external_field": "source_record_id"}, row["shared_identifier"])
        self.assertIsNone(row["reviewer"])
        self.assertEqual(1, result["report"]["base"]["rows_with_automatic_shared_identifier_confirmation"])
        plan = plan_merge([envelope([snapshot()], externals), result["batch"]], base, identity_policy=self.POLICY)
        self.assertEqual(1, sum(m["status"] == "confirmed" for m in plan["batch"]["facility_matches"]))

    def test_without_policy_an_identifier_is_ignored(self):
        base = self.base()
        result = run(base, [ext(1, "Unrelated Name", snapshot(), source_record_id="R-1")])
        self.assertEqual([], result["batch"]["facility_matches"])

    def test_conflicting_same_source_identifier_blocks_confirmation(self):
        base = self.base()
        externals = [ext(1, "Larkspur Hospital", snapshot(), source_record_id="R-1", address_original="1 First Road"),
                     ext(2, "Larkspur Hospital", snapshot(), source_record_id="R-1", address_original="9 Ninth Road")]
        result = run(base, externals, policy=self.POLICY)
        for n in (1, 2):
            self.assertEqual("candidate", match_for(result, 1, n)["status"])
        reasons = {r["reason_code"] for r in result["batch"]["review_queue"] if r["match_id"]}
        self.assertEqual({"identifier_not_unique"}, reasons)
        self.assertTrue(all(r["severity"] == "high" for r in result["batch"]["review_queue"] if r["match_id"]))
        duplicated = self.base() + [base_row(3, name="Larkspur Hospital East", registry_id="R-1")]
        again = run(duplicated, externals[:1], policy=self.POLICY)
        self.assertTrue(all(m["status"] == "candidate" for m in again["batch"]["facility_matches"]))

    def test_namespace_collision_from_another_source_is_not_a_match(self):
        base = self.base()
        other = snapshot("synthetic_other_registry")
        externals = [ext(1, "Unrelated Name", other, source_record_id="R-1")]
        result = run(base, externals, snapshots=[other], policy=self.POLICY)
        self.assertEqual([], result["batch"]["facility_matches"])

    def test_identifier_with_campus_conflict_or_competitor_needs_review(self):
        base = self.base()
        far = [ext(1, "Larkspur Hospital", snapshot(), source_record_id="R-1", city="Elsewhere", state="Other Synthetic State")]
        result = run(base, far, policy=self.POLICY)
        self.assertEqual("candidate", match_for(result, 1, 1)["status"])
        self.assertEqual({"identifier_campus_conflict"}, {r["reason_code"] for r in result["batch"]["review_queue"]})
        twins = [base_row(1, name="Larkspur Hospital", registry_id="R-1"), base_row(2, name="Larkspur Hospital")]
        competing = run(twins, [ext(1, "Larkspur Hospital", snapshot(), source_record_id="R-1")], policy=self.POLICY)
        self.assertTrue(all(m["status"] == "candidate" for m in competing["batch"]["facility_matches"]))
        mismatch = [base_row(1, name="Larkspur Hospital", registry_id="R-1", city="North Town", state=STATE)]
        disagree = run(mismatch, [ext(1, "Larkspur Hospital", snapshot(), source_record_id="R-7",
                                      city="North Town", state=STATE)], policy=self.POLICY)
        self.assertEqual("identifier_conflict", by_pair(disagree)[("synthetic:base:001", "synthetic:external:001")]["review_reason"])

    def test_integer_identifier_is_not_exact_text(self):
        base = [base_row(1, name="Larkspur Hospital", registry_id=7)]
        result = run(base, [ext(1, "Larkspur Hospital", snapshot(), source_record_id="7")], policy=self.POLICY)
        self.assertEqual("candidate", match_for(result, 1, 1)["status"])
        self.assertEqual("identifier_not_unique",
                         by_pair(result)[("synthetic:base:001", "synthetic:external:001")]["review_reason"])

    def test_hidden_competitor_beyond_top_k_still_blocks(self):
        base = [base_row(n, name="Larkspur Hospital", registry_id=("R-1" if n == 1 else None)) for n in range(1, 4)]
        externals = [ext(1, "Larkspur Hospital", snapshot(), source_record_id="R-1")] + [
            ext(n, "Larkspur Hospital", snapshot(), city="North Town") for n in range(2, 9)]
        result = run(base, externals, policy=self.POLICY, config={"top_k": 1})
        self.assertEqual("candidate", match_for(result, 1, 1)["status"])


class DeterminismTests(unittest.TestCase):
    def data(self):
        base = [base_row(n, name=f"Campus {word} Hospital", city="North Town", state=STATE, pin="900001",
                         lat=20.0 + n / 1000, lon=77.0)
                for n, word in enumerate(("Larkspur", "Marigold", "Nettle", "Orchid", "Poppy"), 1)]
        externals = [ext(n, f"Campus {word} Hospital", snapshot(), city="North Town", state=STATE,
                         latitude=20.0 + n / 1000, longitude=77.0001)
                     for n, word in enumerate(("Larkspur", "Marigold", "Nettle", "Orchid", "Quince"), 1)]
        return base, externals

    def test_rerun_and_input_order_do_not_change_output(self):
        base, externals = self.data()
        first = run(base, externals)
        second = run(base, externals)
        self.assertEqual(digest(first), digest(second))
        shuffled = list(reversed(externals))
        third = run(base, shuffled)
        self.assertEqual(digest(first["batch"]), digest(third["batch"]))
        row = match_for(first, 1, 1)
        self.assertEqual(stable_id("acq-c-match", "synthetic:base:001", "synthetic:external:001"), row["match_id"])

    def test_cli_is_reproducible_and_never_touches_inputs(self):
        base, externals = self.data()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "in").mkdir()
            files = {"base": tmp / "in/base.json", "ext": tmp / "in/ext.json", "map": tmp / "in/map.json"}
            files["base"].write_text(json.dumps(base), encoding="utf-8")
            files["ext"].write_text(json.dumps(envelope([snapshot()], externals)), encoding="utf-8")
            files["map"].write_text(json.dumps(mapping(base)), encoding="utf-8")
            before = {k: p.read_bytes() for k, p in files.items()}
            outputs = []
            for name in ("one", "two"):
                done = subprocess.run([sys.executable, "-m", "research.matching.run", "--base", str(files["base"]),
                                       "--external", str(files["ext"]), "--base-mapping", str(files["map"]),
                                       "--output-dir", str(tmp / name)], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(0, done.returncode, done.stderr)
                outputs.append({p.name: p.read_bytes() for p in sorted((tmp / name).iterdir())})
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual({"batch.json", "candidates.json", "geography_report.json", "manifest.json",
                              "report.json", "review_worksheet.json"}, set(outputs[0]))
            self.assertEqual(before, {k: p.read_bytes() for k, p in files.items()})
            refused = subprocess.run([sys.executable, "-m", "research.matching.run", "--base", str(files["base"]),
                                      "--external", str(files["ext"]), "--base-mapping", str(files["map"]),
                                      "--output-dir", str(tmp / "in")], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(1, refused.returncode)
            self.assertIn("INVALID", refused.stderr)

    def test_d_validator_accepts_candidate_batch(self):
        base, externals = self.data()
        result = run(base, externals)
        plan = plan_merge([envelope([snapshot()], externals), result["batch"]], base)
        self.assertEqual(len(result["batch"]["facility_matches"]), len(plan["batch"]["facility_matches"]))
        self.assertEqual(base, plan["base"])

    def test_conflicting_external_payload_under_one_id_fails(self):
        base, externals = self.data()
        changed = copy.deepcopy(externals)
        changed[0]["city"] = "South Town"
        with self.assertRaisesRegex(MatchingError, "conflicting payload"):
            execute(base, [envelope([snapshot()], externals), envelope([snapshot()], changed)], mapping=mapping(base))

    def test_bounded_national_scale_smoke(self):
        rng = random.Random(7)
        words = [f"w{n:04d}" for n in range(4000)]
        externals = [ext(n, f"{rng.choice(words)} {rng.choice(words)} Hospital", snapshot(),
                         state=STATE, pin=f"9{rng.randrange(100000):05d}",
                         latitude=10 + rng.random() * 20, longitude=70 + rng.random() * 20)
                     for n in range(1, 20001)]
        base = [base_row(n, name=externals[n * 7]["name_original"], state=STATE, pin=externals[n * 7]["pin"],
                         lat=externals[n * 7]["latitude"], lon=externals[n * 7]["longitude"])
                for n in range(1, 1001)]
        started = time.monotonic()
        result = run(base, externals)
        self.assertEqual(1000, result["report"]["base"]["rows_with_at_least_one_candidate"])
        self.assertLess(time.monotonic() - started, 120)


if __name__ == "__main__":
    unittest.main()
