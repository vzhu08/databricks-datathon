import unittest
from research.acquisition.esic_services.audit import compare, payload_hash, SERVICES


class AuditTests(unittest.TestCase):
    def inputs(self):
        base = [{"facility_id": "synthetic:" + str(i), "source_row": {"unique_id": "dup", "name": None}} for i in (1, 2)]
        frozen = [{"facility_id": r["facility_id"], "original_payload_sha256": payload_hash(r["source_row"]),
                   "state": "(no state label)", "baseline_service_context": dict.fromkeys(SERVICES, "unconfirmed"),
                   "outcomes": {"joint": "unmatched"}} for r in base]
        lane = [{"facility_id": r["facility_id"], "outcome": "candidate_only"} for r in base]
        return base, frozen, lane

    def test_copies_missing_geography_and_three_decisions_preserved(self):
        base, frozen, lane = self.inputs()
        report, ledgers = compare(base, frozen, {"synthetic": lane}, geographies=["Empty State"])
        self.assertEqual(len(ledgers["synthetic"]), 6)
        self.assertEqual(report["lane_comparisons"]["synthetic"]["newly_reached"], 2)
        self.assertEqual(report["lane_comparisons"]["synthetic"]["by_geography"]["(no state label)"]["occurrences"], 2)
        self.assertTrue(all(row["status"] == "unconfirmed" for row in ledgers["synthetic"]))
        self.assertEqual(report["lane_comparisons"]["synthetic"]["by_geography"]["Empty State"]["occurrences"], 0)

    def test_drop_or_payload_change_rejected(self):
        base, frozen, lane = self.inputs()
        with self.assertRaises(ValueError):
            compare(base, frozen, {"bad": lane[:1]})
        base[0]["source_row"]["name"] = "Edited"
        with self.assertRaises(ValueError):
            compare(base, frozen, {"bad": lane})


if __name__ == "__main__":
    unittest.main()
