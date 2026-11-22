import copy
import unittest

from research.acquisition.service_readiness_audit.audit import digest
from research.acquisition.service_readiness_audit.hot import adapt


class HotAdapterTests(unittest.TestCase):
    def setUp(self):
        payload = {"unique_id": "s"}
        self.manifest = {"population": {"original_payload_multiset_sha256": digest([payload])}, "files": {}}
        link = {"occurrence_key": "a", "quality": "candidate", "campus_id": None}
        raw = dict(independence_status="shared_origin", locator={"all_original_locators": ["x", "y"]},
                   target_links=[link], modality="mri", observation_id="fixture", source_date=None,
                   claim_type="map_name_or_operator_only")
        self.data = dict(occurrences=[dict(original=dict(facility_id="a", source_row=payload),
                         identity=dict(facility_id="a", input_ordinal_zero_based=0, original_upstream_id="s",
                                       original_payload_sha256=digest(payload), state="fixture"))],
                         decisions=[dict(occurrence_key="a", service=s, state="fixture", status="unconfirmed")
                                    for s in ("dialysis", "mri", "trauma_care")],
                         observations=[dict(raw=raw, ledger_id="one", source_family="osm")])

    def test_candidate_and_unlinked_observation(self):
        unlinked = copy.deepcopy(self.data["observations"][0])
        unlinked["ledger_id"] = "two"
        unlinked["raw"]["target_links"] = []
        self.data["observations"].append(unlinked)
        frame, inventory, exact = adapt(self.manifest, self.data)
        self.assertEqual(4, inventory["original_locators"])
        self.assertEqual(1, inventory["unlinked_observations"])
        self.assertEqual(0, exact["mri"])
        self.assertEqual([0, 1, 0], [len(r["mentions"]) for r in frame["decisions"]])
        mention = frame["decisions"][1]["mentions"][0]
        self.assertEqual("one", mention["mention_id"])
        self.assertIsNone(mention["campus_id"])
        self.assertIsNone(mention["claimant_id"])

    def test_mutated_original_rejected(self):
        self.data["occurrences"][0]["original"]["source_row"]["extra"] = True
        with self.assertRaisesRegex(ValueError, "payload changed"):
            adapt(self.manifest, self.data)
