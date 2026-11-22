import unittest

from research.acquisition.service_readiness_audit.november import compare, NEW_LANE


class NovemberTests(unittest.TestCase):
    def test_cross_service_and_directory_overlap(self):
        def hit(lane, family):
            return dict(lane=lane, family=family)
        october = hit("October", "osm")
        directory = hit("directory", "nhp")
        november = hit(NEW_LANE, "osm")
        def row(service, hits):
            return dict(occurrence_key="synthetic", service=service, candidates=hits, state="unknown",
                        status="unconfirmed", frozen_sample=False)
        old = [row("dialysis", [october]), row("mri", [directory]), row("trauma_care", [])]
        new = [dict(r, candidates=r["candidates"]+[november]) for r in old]
        result = compare(old, new)
        self.assertEqual(2, result["new_vs_october"]["total"])
        self.assertEqual(1, result["new_vs_october_already_in_mixed"]["by_service"]["mri"])
        self.assertEqual(1, result["gain_vs_mixed"]["by_service"]["trauma_care"])
        self.assertEqual(3, result["union"]["total"])
        new[0]["frozen_sample"] = True
        with self.assertRaisesRegex(ValueError, "sample"):
            compare(old, new)
