from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from research.acquisition.national_facility_evidence import finding_provenance as mapper
from research.acquisition.national_facility_evidence.finding_examples import examples


AS_OF = "2026-11-22"
BRANCH = "Synthetic branch A"


def dated_statement(**changes):
    statement = mapper.Observation("Example operator", "A statement of onsite dialysis.", BRANCH, role="support",
                                   match="exact", origin="operator A", independent=True, observed_on=AS_OF,
                                   field="page 2", assertion="onsite_delivery")
    return replace(statement, **changes)


def synthetic_card(**changes):
    return {"facility_id": "demo-test", "location": {}, **changes}


def one_demo(card):
    response = {"status": "ok", "direct_results": [card]}
    return mapper.project_find_care(response, "dialysis", mode="demo")["findings"][0]


class FindingProvenanceTests(unittest.TestCase):
    def service(self, observations, review=None):
        return mapper.summarize_claim("service", BRANCH, observations, service="dialysis", as_of=AS_OF, review=review)

    def test_actual_finder_cards_and_warehouse_shapes(self):
        output = examples()
        direct, backup = output["demo_50_km"]["findings"]
        indirect, = output["demo_2_km"]["findings"]
        self.assertEqual((direct["result_group"], direct["index"]), ("direct_results", 0))
        self.assertEqual((backup["result_group"], backup["index"]), ("direct_results", 1))
        self.assertEqual((indirect["result_group"], indirect["index"]), ("indirect_leads", 0))
        for finding in (direct, backup, indirect):
            self.assertEqual(finding["location"]["precision"], "reported_position")
            self.assertEqual(finding["service"]["decision"], "unconfirmed")
            self.assertIsNone(finding["service"]["review"])
            self.assertIsNone(finding["service"]["sources"][0]["observed_on"])
            self.assertEqual(finding["service"]["sources"][0]["publisher"], "Synthetic demo record")
        self.assertEqual(direct["service"]["strength"], "reported")
        self.assertEqual(direct["service"]["sources"][0]["field"], "procedures")
        self.assertEqual(direct["service"]["sources"][0]["citation_scope"], "record")
        self.assertIn("North Campus", direct["service"]["scope"])
        self.assertIn("unverified", direct["service"]["scope"])
        self.assertEqual(backup["service"]["sources"][0]["field"], "capabilities")
        self.assertIsNone(backup["service"]["sources"][0]["citation"])
        self.assertIn("South Campus", backup["service"]["scope"])
        self.assertEqual(indirect["service"]["strength"], "no_evidence")
        self.assertEqual(indirect["service"]["sources"][0]["role"], "context")
        self.assertIn("Related specialty", indirect["service"]["scope"])
        for radius, signal in ((2, "related"), (50, "direct")):
            withheld = output[f"withheld_shape_{radius}_km"]
            self.assertEqual(withheld["findings"], [])
            self.assertEqual(withheld["summary"]["text_signal"], signal)
            self.assertIsNone(withheld["summary"]["independent_supporting_origins"])

    def test_fixture_location_does_not_inherit_service_or_request_precision(self):
        with_pin = one_demo(synthetic_card(location={"latitude": None, "longitude": 75, "pin": "302001"}))
        with_city = one_demo(synthetic_card(location={"latitude": True, "longitude": 75, "city": "Example"}))
        missing = one_demo(synthetic_card())
        self.assertEqual(with_pin["location"]["precision"], "postal_area")
        self.assertEqual(with_city["location"]["precision"], "city")
        self.assertEqual(missing["location"]["precision"], "unknown")
        self.assertEqual(with_pin["service"]["strength"], "no_evidence")

    def test_warehouse_output_does_not_copy_even_unexpected_nested_fields(self):
        payload = {"status": "withheld", "withheld": True, "evidence": "direct", "message": "PRIVATE TEST MARKER",
                   "direct_results": [{"name": "PRIVATE TEST MARKER"}], "location_choices": ["PRIVATE TEST MARKER"]}
        actual = mapper.project_find_care(payload, "mri", mode="warehouse")
        self.assertNotIn("PRIVATE TEST MARKER", json.dumps(actual))
        self.assertEqual(actual["findings"], [])
        for status in ("no_match", "unavailable", "ambiguous_location"):
            summary = mapper.project_find_care(dict(payload, status=status), "mri", mode="warehouse")["summary"]
            self.assertEqual(summary["status"], status)
            self.assertIsNone(summary["text_signal"])
            self.assertIsNone(summary["source_records"])
        raw = mapper.project_find_care(dict(payload, status="ok", withheld=False), "mri", mode="warehouse")
        self.assertEqual(raw["status"], "unavailable")
        self.assertEqual(raw["findings"], [])

    def test_vf_only_and_missing_source_counts(self):
        native = mapper.Observation("Virtue Foundation v0", "A publication reports the PIN.", "Original record area",
                                    role="support", field="address_zipOrPostcode", citation_scope="record")
        claim = mapper.summarize_claim("location", "Original record area", [native], precision="postal_area")
        self.assertEqual(claim["strength"], "reported")
        self.assertEqual(claim["source_records"], 1)
        self.assertIsNone(claim["independent_supporting_origins"])
        self.assertEqual(claim["sources"][0]["lineage"], "unknown")
        self.assertEqual(self.service([])["source_records"], 0)
        self.assertIsNone(self.service(None)["source_records"])
        self.assertIsNone(self.service(None)["strength"])

    def test_corroboration_deduplicates_mirrors_and_does_not_set_service_decision(self):
        first = dated_statement(origin="osm example origin", publisher="Example HOT copy")
        same = replace(first, publisher="Example Geofabrik copy")
        other = dated_statement(origin="independent example branch operator")
        mirrored = self.service([first, same])
        self.assertEqual((mirrored["source_records"], mirrored["independent_supporting_origins"]), (2, 1))
        self.assertEqual(mirrored["strength"], "reported")
        corroborated = self.service([first, same, other])
        self.assertEqual((corroborated["source_records"], corroborated["independent_supporting_origins"]), (3, 2))
        self.assertEqual(corroborated["strength"], "corroborated")
        self.assertEqual(corroborated["decision"], "unconfirmed")
        unassessed = self.service([first, replace(other, independent=False)])
        self.assertEqual(unassessed["strength"], "reported")
        self.assertIsNone(unassessed["independent_supporting_origins"])

    def test_only_explicit_current_review_may_carry_yes_or_no(self):
        yes = mapper.Review(BRANCH, AS_OF, "yes")
        no = mapper.Review(BRANCH, AS_OF, "no")
        positive = self.service([dated_statement()], yes)
        self.assertEqual((positive["decision"], positive["strength"]), ("yes", "reported"))
        self.assertEqual(positive["review"], {"scope": BRANCH, "as_of": AS_OF})
        self.assertEqual(self.service([dated_statement()], no)["decision"], "unconfirmed")
        for assertion in ("explicit_absence", "all_cases_referral"):
            self.assertEqual(self.service([dated_statement(assertion=assertion)], no)["decision"], "no")
        self.assertEqual(self.service([dated_statement(assertion="equipment_inventory")], no)["decision"], "unconfirmed")
        self.assertIsNone(self.service([dated_statement()], replace(yes, scope="Other branch"))["review"])

    def test_wrong_branch_old_and_capture_only_stay_context(self):
        wrong = dated_statement(scope="Same name, branch B", citation="https://example.invalid/wrong", citation_scope="claim")
        old = dated_statement(observed_on="2020-12-12")
        capture = dated_statement(observed_on=None, archive_captured_at="2026-11-22T01:00:00Z")
        result = self.service([wrong, old, capture], mapper.Review(BRANCH, AS_OF, "yes"))
        self.assertEqual([source["role"] for source in result["sources"]], ["context"] * 3)
        self.assertEqual(result["sources"][0]["citation_scope"], "claim")
        self.assertIsNone(result["sources"][2]["observed_on"])
        self.assertEqual(result["strength"], "no_evidence")
        self.assertEqual(result["decision"], "unconfirmed")
        undated_report = self.service([replace(capture, match="reported")])
        self.assertEqual(undated_report["strength"], "reported")
        self.assertEqual(undated_report["decision"], "unconfirmed")

    def test_scope_matched_conflict_blocks_review_and_preserves_both_links(self):
        own = dated_statement(citation="https://example.invalid/current", citation_scope="claim")
        opposing = dated_statement(role="conflict", assertion="explicit_absence", origin="example licensing authority",
                                   observed_on=None, effective_from="2026-11-20", effective_to="2026-11-25",
                                   citation="https://example.invalid/notice", citation_scope="claim")
        result = self.service([own, opposing], mapper.Review(BRANCH, AS_OF, "yes"))
        self.assertEqual(result["strength"], "conflicting_evidence")
        self.assertEqual(result["decision"], "unconfirmed")
        self.assertIsNone(result["review"])
        self.assertEqual([source["role"] for source in result["sources"]], ["support", "conflict"])
        self.assertEqual(result["sources"][1]["citation"], "https://example.invalid/notice")
        self.assertIn("conflicting statements", result["missing_check"])

    def test_area_evidence_cannot_corroborate_an_identified_branch(self):
        origin = mapper.Observation("Example record", "Reported address.", BRANCH, role="support", match="reported")
        postal = mapper.Observation("Example post directory", "Corroborates the postal area only.", "Postal area",
                                    role="support", match="exact", origin="example postal", independent=True)
        claim = mapper.summarize_claim("location", BRANCH, [origin, postal], precision="written_address")
        self.assertEqual(claim["strength"], "reported")
        self.assertEqual(claim["sources"][1]["role"], "context")

    def test_standalone_runtime_without_repository_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "finding_provenance.py"
            shutil.copyfile(mapper.__file__, source)
            subprocess.run([sys.executable, "-I", "-B", "-c",
                            "import runpy,sys; m=runpy.run_path(sys.argv[1]); "
                            "assert m['project_find_care']({},'mri',mode='warehouse')['findings']==[]",
                            str(source)], cwd=folder, check=True, capture_output=True, text=True)
