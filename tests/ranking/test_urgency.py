import unittest
from datetime import date

from app.ranking.urgency import rank_campuses


DAY = "2026-11-21"


def campus(facility_id, minutes, *, status="yes", source_date=DAY, families=("synthetic",),
           capabilities=None, as_of=DAY, distance=None):
    return {
        "facility_id": facility_id,
        "as_of": as_of,
        "travel_minutes": minutes,
        "distance_km": distance,
        "services": {
            "mri": {
                "status": status,
                "source_date": source_date,
                "independent_families": families,
                "capabilities": capabilities or {},
            }
        },
    }


def rank(candidates, urgency="routine", **options):
    settings = dict(as_of=DAY, travel_metric="travel_minutes", travel_budget=60)
    settings.update(options)
    return rank_campuses("mri", urgency, candidates, **settings)


class UrgencyRankTests(unittest.TestCase):
    def test_urgency_alters_tradeoff_between_travel_and_a_preference(self):
        near = campus("near", 20)
        far = campus("far", 27, capabilities={"preferred-scanner": "yes"})
        for urgency, winner, travel_weight in [
            ("routine", "far", 45),
            ("time_sensitive", "far", 65),
            ("highest", "near", 80),
        ]:
            with self.subTest(urgency=urgency):
                result = rank([near, far], urgency, preferred=["preferred-scanner"])
                self.assertEqual(result["status"], "ok")
                first = result["ranked"][0]
                self.assertEqual(first["facility_id"], winner)
                self.assertEqual(first["weights"]["travel"], travel_weight)
                self.assertEqual(first["availability"], "unknown")

    def test_required_features_and_service_status_cannot_be_bought_with_weight(self):
        candidates = [
            campus("unknown-feature", 0),
            campus("absent-feature", 1, capabilities={"protocol": "no"}),
            campus("offsite", 2, status="no", capabilities={"protocol": "yes"}),
            campus("unconfirmed-service", 4, status="unconfirmed", capabilities={"protocol": "yes"}),
            campus("eligible", 40, capabilities={"protocol": "yes"}),
        ]
        result = rank(candidates, "highest", required=["protocol"], preferred=["protocol"])
        self.assertEqual([r["facility_id"] for r in result["ranked"]], ["eligible"])
        self.assertEqual(result["ranked"][0]["weights"]["preferred"], 0)
        self.assertEqual(result["needs_confirmation"], [])
        fallback = rank(candidates[:-1], "highest", required=["protocol"])
        self.assertEqual(fallback["status"], "needs_confirmation")
        self.assertEqual([(x["facility_id"], x["reasons"]) for x in fallback["needs_confirmation"]], [
            ("unknown-feature", ["required_capability_unconfirmed"]),
            ("unconfirmed-service", ["service_unconfirmed"]),
        ])

    def test_status_and_capabilities_are_specific_to_requested_service(self):
        at_other_service = campus("other", 1, capabilities={"protocol": "yes"})
        at_other_service["services"]["dialysis"] = at_other_service["services"].pop("mri")
        result = rank([at_other_service], required=["protocol"])
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["needs_confirmation"][0]["reasons"],
                         ["service_unconfirmed", "required_capability_unconfirmed"])

    def test_dates_use_assertion_age_and_same_assessment_snapshot(self):
        recent = campus("recent", 10)
        old = campus("old", 10, source_date="2024-11-21")
        undated = campus("undated", 10, source_date=None)
        undated["page_updated"] = DAY
        rows = rank([old, undated, recent], as_of=date.fromisoformat(DAY))["ranked"]
        self.assertEqual([x["facility_id"] for x in rows], ["recent", "old"])
        self.assertEqual(rows[0]["factors"]["recency"], 1)
        self.assertAlmostEqual(rows[1]["factors"]["recency"], .5, places=3)
        self.assertAlmostEqual(sum(rows[0]["weights"].values()), 100)

    def test_undated_yes_at_highest_urgency_stays_a_confirmation_lead(self):
        record = campus("nearest", 0)
        del record["services"]["mri"]["source_date"]
        record["page_updated"] = DAY
        result = rank([record], "highest")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["ranked"], [])
        self.assertEqual(result["needs_confirmation"][0]["reasons"], ["missing_service_evidence_date"])
        eligible = campus("documented", 40)
        mixed = rank([record, eligible], "highest")
        self.assertEqual([x["facility_id"] for x in mixed["ranked"]], ["documented"])

    def test_undated_invalid_or_future_no_is_an_unscored_confirmation_lead(self):
        for source_date, reason in [
            (None, "missing_service_evidence_date"),
            ("not-a-date", "invalid_service_evidence_date"),
            ("2026-11-22", "invalid_service_evidence_date"),
        ]:
            with self.subTest(source_date=source_date):
                response = rank([campus("x", 0, status="no", source_date=source_date)], "highest")
                self.assertEqual(response["status"], "needs_confirmation")
                self.assertEqual(response["ranked"], [])
                self.assertEqual(response["needs_confirmation"][0]["reasons"],
                                 ["service_unconfirmed", reason])
        self.assertEqual(rank([campus("x", 0, status="no", source_date=DAY)])["status"], "no_match")

    def test_future_malformed_or_mismatched_evidence_stays_unconfirmed(self):
        for record, reason in [
            (campus("f", 1, source_date="2027-11-21"), "invalid_service_evidence_date"),
            (campus("m", 1, source_date="2026-99-00"), "invalid_service_evidence_date"),
            (campus("s", 1, as_of="2026-11-20"), "assessment_date_mismatch"),
        ]:
            with self.subTest(reason=reason, facility=record["facility_id"]):
                result = rank([record])
                self.assertEqual(result["ranked"], [])
                self.assertEqual(result["needs_confirmation"][0]["reasons"], [reason])

    def test_independence_credit_collapses_copies_and_caps_at_two_additions(self):
        families = [["a", "a"], ["a", "b"], ["a", "b", "c"], ["a", "b", "c", "d"]]
        rows = rank([campus(str(i), 10, families=f) for i, f in enumerate(families)],
                    limit=None)["ranked"]
        self.assertEqual([x["facility_id"] for x in rows], ["2", "3", "1", "0"])
        self.assertEqual([x["factors"]["corroboration"] for x in rows], [1, 1, .5, 0])

    def test_missing_time_does_not_mix_distance_units(self):
        a = campus("a", None, distance=1)
        b = campus("b", 8, distance=2)
        self.assertEqual([x["facility_id"] for x in rank([a, b])["ranked"]], ["b"])
        result = rank([a, b], travel_metric="distance_km", travel_budget=1)
        self.assertEqual([x["facility_id"] for x in result["ranked"]], ["a"])
        self.assertEqual(result["ranked"][0]["travel"], 1)
        unknown = rank([a])["needs_confirmation"]
        self.assertEqual(unknown[0]["reasons"], ["travel_unknown"])
        self.assertEqual(rank([campus("far", 61)])["status"], "no_match")

    def test_deterministic_ties_finder_limit_and_full_planner_pool(self):
        rows = [campus(str(i), 5) for i in range(5, 0, -1)]
        self.assertEqual([x["facility_id"] for x in rank(rows, limit=10)["ranked"]], ["1", "2", "3"])
        self.assertEqual(len(rank(rows, limit=None)["ranked"]), 5)
        self.assertEqual(rank(rows), rank(reversed(rows)))

    def test_fail_closed_for_invalid_request_and_duplicate_campuses(self):
        for inputs in [{"as_of": "tomorrow"}, {"travel_budget": 0}, {"travel_metric": "mi"},
                       {"half_life_months": float("inf")}, {"required": "scanner"},
                       {"preferred": [""]}, {"limit": True}, {"urgency": "infer"}]:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                rank([], **inputs)
        with self.assertRaisesRegex(ValueError, "unique"):
            rank([campus("same", 2), campus("same", 3)])


if __name__ == "__main__":
    unittest.main()
