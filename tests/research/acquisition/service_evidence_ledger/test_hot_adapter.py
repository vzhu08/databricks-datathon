import unittest

from research.acquisition.service_evidence_ledger.hot_adapter import adapt_hot


class HotAdapterTests(unittest.TestCase):
    def inputs(self):
        manifest = {"permitted_audience": "four-person private research team; OSM-derived ledger remains ODbL-1.0",
                    "ledger_observations": 1, "attribution": "Synthetic", "license_url": "https://example.invalid/license",
                    "source_edition": {"sha256": "a" * 64, "publisher": "Synthetic", "source_url": "https://example.invalid/map",
                                       "publication_date": None, "first_retrieved_at": "2026-11-21T00:00:00Z"}}
        source = {"observation_id": "synthetic", "osm_id": "node/123", "edition_sha256": "a" * 64,
                  "source_family": "osm", "independence": "shared_origin", "patient_status": "unconfirmed",
                  "campus_id": None, "facility_id": None, "locators": ["features/1", "features/2"],
                  "service_observation_date": None, "service_observed_date": None,
                  "source_key": "healthcare", "raw_value": "dialysis", "service": "dialysis",
                  "category": "explicit_service_tag", "payload_sha256": "b" * 64}
        joint = [{"representative": "twin-a", "facility_id": f} for f in ["twin-a", "twin-b"]]
        candidate = {"source_key": "hot_osm_health", "snapshot_id": "hot_osm_health:" + "a" * 64,
                     "source_record_id": "node/123", "representative": "twin-a", "runs": {"joint": {"stage": "rank_cut"}}}
        return manifest, [source], joint, [candidate]

    def test_all_locators_twins_and_source_record_preserved(self):
        args = self.inputs(); result = adapt_hot(*args); row = result["observations"][0]
        self.assertEqual(row["source_record"], args[1][0])
        self.assertEqual(len(row["locator"]["all_original_locators"]), 2)
        self.assertEqual([r["occurrence_key"] for r in row["target_links"]], ["twin-a", "twin-b"])
        self.assertTrue(all(r["quality"] == "candidate" and r["campus_id"] is None for r in row["target_links"]))
        self.assertIsNone(row["effective_from"])
        self.assertEqual(row["polarity"], "inconclusive")

    def test_same_object_in_other_edition_does_not_join(self):
        args = self.inputs(); args[3][0]["snapshot_id"] = "hot_osm_health:" + "c" * 64
        self.assertEqual(adapt_hot(*args)["observations"][0]["target_links"], [])

    def test_missing_representative_fails_and_dated_claim_needs_review(self):
        args = self.inputs(); args[3][0]["representative"] = "missing"
        with self.assertRaisesRegex(ValueError, "representative_missing"):
            adapt_hot(*args)
        args = self.inputs(); args[1][0]["service_observation_date"] = "2026-11-20"
        with self.assertRaisesRegex(ValueError, "dated_hot_observation"):
            adapt_hot(*args)
