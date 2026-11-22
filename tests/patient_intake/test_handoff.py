import unittest

from app.patient_intake.handoff import _screen_reviewed_destinations

AS_OF = "2026-11-22"


def _campus():
    # Deliberately fictional. The reference strings model a server-verified
    # release, and no fixture is passed into a production loader.
    return {
        "facility_id": "TEST-ONLY-CAMPUS",
        "as_of": AS_OF,
        "latitude": 20.5,
        "longitude": 75.5,
        "coordinate_status": "reviewed",
        "campus_review_ref": "test-campus-review",
        "coordinate_review_ref": "test-coordinate-review",
        "display_permission_ref": "test-display-review",
        "services": {"dialysis": {
            "status": "yes",
            "service_review_ref": "test-service-review",
            "source_date": AS_OF,
            "independent_families": ["test-evidence-family"],
            "capabilities": {"monitored": "yes"},
            "availability": "unknown",
        }},
    }


def _screen(*campuses, **kwargs):
    release = {"release_ref": "test-release", "as_of": AS_OF, "campuses": campuses}
    return _screen_reviewed_destinations(release, service="dialysis", as_of=AS_OF, **kwargs)


class ReviewedDestinationTests(unittest.TestCase):
    def test_no_release_and_no_candidates(self):
        self.assertEqual(_screen_reviewed_destinations(None, service="dialysis", as_of=AS_OF), {})
        self.assertEqual(_screen(), {})

    def test_reviewed_campus_preserves_evidence_and_does_not_mutate_release(self):
        campus = _campus()
        result = _screen(campus, required=("monitored",))
        self.assertEqual(result, {campus["facility_id"]: campus})
        self.assertEqual(result[campus["facility_id"]]["services"]["dialysis"]["availability"], "unknown")
        result[campus["facility_id"]]["services"].clear()
        self.assertIn("dialysis", campus["services"])

    def test_ineligible_campus_coordinate_service_or_display_cannot_enter_finder(self):
        for field, invalid in [
            ("campus_review_ref", None), ("coordinate_review_ref", None),
            ("display_permission_ref", ""), ("coordinate_status", "disputed"),
            ("latitude", float("nan")), ("as_of", "2026-11-21"),
        ]:
            with self.subTest(field=field):
                self.assertEqual(_screen({**_campus(), field: invalid}), {})

        for field, invalid in [
            ("service_review_ref", None), ("status", "unconfirmed"),
            ("source_date", None), ("availability", "unavailable"),
            ("capabilities", {"monitored": "unconfirmed"}),
        ]:
            with self.subTest(field=field):
                campus = _campus()
                campus["services"]["dialysis"][field] = invalid
                self.assertEqual(_screen(campus, required=("monitored",)), {})

    def test_duplicate_campus_id_cannot_pick_a_preferred_review(self):
        good = _campus()
        conflicting = {**good, "coordinate_status": "disputed"}
        self.assertEqual(_screen(good, conflicting), {})
