import unittest

from research.acquisition.service_readiness_audit.collectors import reconcile, services


class CollectorReconciliationTests(unittest.TestCase):
    def test_shared_directory_origins_and_overlapping_candidate_terms(self):
        decision = dict(occurrence_key="fixture", service="mri", state="unknown", status="unconfirmed")
        link = dict(occurrence_key="fixture", quality="candidate", campus_id=None)
        def observation(mid, lane, family, modality, terms=(), withheld=False):
            raw = dict(source_facility_id="object", claim_type="tag", modality=modality,
                       source_record=dict(term_leads=terms, withheld_for_contact_pattern=withheld),
                       independence_status="shared_origin", target_links=[link])
            return dict(ledger_id=mid, lane=lane, source_family=family, raw=raw)
        obs = [observation("1", "NHP_181", "nhp", "directory_field", ["mri", "mri"]),
               observation("2", "fixture-blood", "nhp", "blood_provision"),
               observation("3", "fixture-map", "osm", "mri"),
               observation("4", "NHP_181", "nhp", "directory_field", ["mri"], True)]
        rows, stats = reconcile({"observations":obs}, [decision], [decision])
        self.assertEqual(["1", "3"], [c["ledger_id"] for c in rows[0]["candidates"]])
        self.assertEqual(3, stats["observations_in_families_shared_between_lanes"])
        self.assertEqual(1, stats["multiple_family_candidate_decisions"])
        self.assertEqual(0, stats["multiple_mention_same_family_decisions"])
        self.assertEqual(0, stats["lanes"]["fixture-blood"]["sample_candidate_decisions"])
        self.assertEqual("unconfirmed", rows[0]["status"])
