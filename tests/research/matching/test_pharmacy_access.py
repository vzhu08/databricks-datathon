import unittest

from research.matching.pharmacy_access import build, candidate_rows


class PharmacyAccessTests(unittest.TestCase):
    def setUp(self):
        self.vf = [
            {
                "occurrence_key": key,
                "upstream_id": "repeated",
                "state": "Delhi",
                "original_payload": {
                    "name": "Fernbrook Multispeciality Hospital",
                    "address_zipOrPostcode": "110001",
                    "address_city": "Delhi",
                    "address_line1": "14, River Road",
                },
            }
            for key in ("row-one", "row-two")
        ]
        self.prior = {
            r["occurrence_key"]: {
                "previous_external_pharmacy_support": True,
                "prior_source_families": ["nhp"],
                "vf_mentions_pharmacy": True,
            }
            for r in self.vf
        }

    def outlet(self, key, text, pin="110001"):
        return {
            "kendra_code": key,
            "state_ut": "Delhi",
            "district": "New Delhi",
            "pin": pin,
            "address": text,
        }

    def test_distinct_on_premises_and_nearby_survive_duplicate_original(self):
        pos, leads = candidate_rows(
            self.vf,
            [
                self.outlet("p", "Inside Fernbrook Hospital"),
                self.outlet("q", "Opp. Fernbrook Multispeciality Hospital"),
                self.outlet("ignored", "Inside Fernbrook Hospital", pin="110002"),
            ],
        )
        self.assertEqual(len(leads), 4)
        reviews = [
            {
                "review_key": x["review_key"],
                "disposition": x["wording"],
                "reason": "Named site and wording checked",
            }
            for x in leads
        ]
        rows, s = build(self.vf, self.prior, pos, leads, reviews)
        self.assertEqual(s["all"]["both"], 2)
        self.assertEqual(s["all"]["either"], 2)
        self.assertEqual(s["distinct_upstream_ids"], 1)
        self.assertEqual(rows[0]["source_families"], ["nhp", "pmbi"])

    def test_near_hospital_followed_by_another_landmark(self):
        _, leads = candidate_rows(
            self.vf,
            [self.outlet("q", "Near Fernbrook Multispeciality Hospital, opposite the library")],
        )
        self.assertEqual([lead["wording"] for lead in leads], ["nearby", "nearby"])

    def test_postal_context_and_unreviewed_spelling_leads(self):
        pos, leads = candidate_rows(
            self.vf,
            [
                self.outlet("x", "Near Fembrook Multispeciality Hospital"),
                self.outlet("y", "Shop 4, West Market"),
            ],
        )
        self.assertEqual(pos, {"row-one", "row-two"})
        self.assertFalse(
            any(r["nearby_supported"] for r in build(self.vf, self.prior, pos, leads, [])[0])
        )
        # A clear single-letter typo generates a review lead; the strongest output remains held.
        _, leads = candidate_rows(
            self.vf, [self.outlet("z", "Near Fernbrok Multispeciality Hospital")]
        )
        self.assertEqual(leads[0]["alias_basis"], "spelling_variant")
        self.assertEqual(
            build(self.vf, self.prior, pos, leads, [])[1]["unreviewed_candidate_pairs"], 2
        )

    def test_landmark_and_road_name_do_not_upgrade(self):
        pos, leads = candidate_rows(
            self.vf, [self.outlet("x", "Opposite Old School, on Fernbrook Hospital Road")]
        )
        self.assertEqual(leads[0]["wording"], "name_only")
        bad = {
            "review_key": leads[0]["review_key"],
            "disposition": "nearby",
            "reason": "shared PIN",
        }
        with self.assertRaises(ValueError):
            build(self.vf, self.prior, pos, leads, [bad])
        self.assertTrue(build(self.vf, self.prior, pos, leads, [])[0][0]["ambiguous"])

    def test_manually_resolved_branch_and_address_or_operator_evidence(self):
        pos, leads = candidate_rows(
            self.vf, [self.outlet("x", "14 River Road, Fernbrook Hospital, East Ward")]
        )
        review = {
            "review_key": leads[0]["review_key"],
            "disposition": "on_premises",
            "reason": "named building",
            "shared_civic_phrase": "14 River Road",
        }
        rows, _ = build(self.vf, self.prior, pos, leads, [review])
        self.assertIn("reviewed_matching_named_premises", rows[0]["onsite_basis"])
        # The second occurrence keeps its own review state.
        self.assertEqual(rows[1]["onsite_basis"], ["prior_external_pharmacy"])
        bad = {**review, "shared_civic_phrase": "10 River Road"}
        with self.assertRaises(ValueError):
            build(self.vf, self.prior, pos, leads, [bad])
        operator = {
            **bad,
            "onsite_basis": "named_premises_and_operator_pharmacy",
            "operator_url": "https://example.org/branch/pharmacy",
        }
        rows, _ = build(self.vf, self.prior, pos, leads, [operator])
        self.assertIn("hospital_operator", rows[0]["source_families"])
        wrong = {
            **review,
            "disposition": "different_facility",
            "reason": "operator identifies the address as another branch",
        }
        self.assertNotIn(
            "pmbi", build(self.vf, self.prior, pos, leads, [wrong])[0][0]["source_families"]
        )
        with self.assertRaises(ValueError):
            build(self.vf, self.prior, pos, leads, [{**wrong, "review_key": "stale"}])
