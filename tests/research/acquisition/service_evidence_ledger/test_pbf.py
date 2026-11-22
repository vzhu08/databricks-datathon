import unittest

from research.acquisition.service_evidence_ledger.hot_adapter import frozen_hot_links
from research.acquisition.service_evidence_ledger.pbf import november_observation


class NovemberOSMTests(unittest.TestCase):
    def test_cross_edition_lookup_uses_typed_id_in_exact_prior_snapshot(self):
        originals = [{"representative":"a","facility_id":key} for key in ("a","b")]
        records = [{"source_key":"hot_osm_health","snapshot_id":snapshot,
                    "representative":"a","source_record_id":oid,"runs":{"joint":{"stage":"rank_cut"}}}
                   for snapshot, oid in [("old","way/4"),("other","node/4"),("old","node/5")]]
        links = frozen_hot_links({"node/4","node/5"}, "old", originals, records)
        self.assertEqual(set(links), {"node/5"})
        self.assertEqual(set(links["node/5"]), {"a","b"})

    def test_negative_historical_map_tag_preserves_year_and_unknown_service_day(self):
        source = dict(tags={"source":"2C_Indore Field Visit 2019"}, facility_id=None, campus_id=None,
                      source_family="osm", independence="shared_origin", patient_status="unconfirmed",
                      service_observation_date=None, service_observed_date=None, observation_id="fixture",
                      osm_id="node/5", service="mri", category="negative_or_unavailable", source_key="facility:mri",
                      raw_value="no", locators=["fixture.pbf#node/5@v2"], version=2, payload_sha256="a"*64)
        link = dict(occurrence_key="a", quality="candidate", campus_id=None, review_reference=None)
        observation = november_observation(source, "november-fixture", {"a":link})
        self.assertEqual(observation["source_record"], source)
        self.assertEqual(observation["historical_survey_year"], 2019)
        self.assertIsNone(observation["source_date"])
        self.assertEqual((observation["claim_value"], observation["polarity"]), ("no","inconclusive"))
        self.assertEqual(observation["target_links"][0]["link_basis"], "same_typed_osm_id_across_editions")
        self.assertNotIn("link_basis", link)
