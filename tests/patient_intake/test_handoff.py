import unittest
from copy import deepcopy
from datetime import date
from unittest.mock import Mock

from app.patient_intake.handoff import PatientHandoff, _screen_reviewed_destinations

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


class Encounter:
    """Minimal test double for O's detached read and revision contract."""

    def __init__(self, state="completed"):
        self.revision = 3
        self.assessment = {
            "revision": 3, "state": state, "urgency": "consultation", "guidance": "Test-only provider guidance",
            "next_step": {"kind": "consultation", "specialty_code": "nephrology"},
        }
        self.state = state

    def read(self):
        return self.revision, {"state": self.state, "assessment": deepcopy(self.assessment)}


class PatientHandoffTests(unittest.TestCase):
    def setUp(self):
        self.handle = Encounter()
        self.order = Mock(return_value={"service": "dialysis", "required_capabilities": ["monitored"]})
        self.release = Mock(return_value={"release_ref": "test-release", "as_of": AS_OF,
                                          "campuses": [_campus()]})
        self.handoff = PatientHandoff(read_verified_order=self.order, read_reviewed_release=self.release,
                                      today=lambda: date.fromisoformat(AS_OF))

    def test_default_consultation_preserves_guidance_and_has_no_destinations(self):
        assessment = deepcopy(self.handle.assessment)
        self.assertEqual(PatientHandoff()(self.handle, 3, assessment), {"state": "no_reviewed_destination"})
        self.assertEqual(self.handle.assessment, assessment)

    def test_blocked_and_old_assessments_do_not_read_order_or_evidence(self):
        for state in ["urgent", "draft", "unsupported", "provider_unavailable", "awaiting_clarification"]:
            with self.subTest(state=state):
                encounter = Encounter(state)
                self.assertEqual(self.handoff(encounter, 3, encounter.assessment),
                                 {"state": "assessment_blocked"})
        self.assertEqual(self.handoff(self.handle, 2, self.handle.assessment), {"state": "assessment_blocked"})
        other = Encounter()
        other.assessment["guidance"] = "Different test encounter"
        self.assertEqual(self.handoff(other, 3, self.handle.assessment), {"state": "assessment_blocked"})
        self.order.assert_not_called()
        self.release.assert_not_called()

    def test_consultation_and_unsupported_order_do_not_load_campuses(self):
        self.order.return_value = None
        self.assertEqual(self.handoff(self.handle, 3, self.handle.assessment),
                         {"state": "no_reviewed_destination"})
        self.order.return_value = {"service": "cardiac", "required_capabilities": []}
        self.assertEqual(self.handoff(self.handle, 3, self.handle.assessment),
                         {"state": "unsupported_service"})
        self.release.assert_not_called()

    def test_verified_test_only_order_and_campus_allow_limited_result(self):
        self.assertEqual(
            self.handoff(self.handle, 3, self.handle.assessment),
            {"state": "reviewed_destinations",
             "destinations": [{"facility_id": "TEST-ONLY-CAMPUS", "availability": "unknown"}]},
        )
        self.order.assert_called_once_with(self.handle, 3)
        self.release.assert_called_once_with(AS_OF)

    def test_evidence_failure_after_success_withholds_previous_destinations(self):
        self.assertEqual(self.handoff(self.handle, 3, self.handle.assessment)["state"],
                         "reviewed_destinations")
        self.release.side_effect = OSError("private evidence locator")
        self.assertEqual(self.handoff(self.handle, 3, self.handle.assessment),
                         {"state": "navigation_unavailable"})

    def test_edit_during_lookup_discards_result(self):
        approved_release = self.release.return_value

        def edited(as_of):
            self.handle.revision += 1
            return approved_release

        self.release.side_effect = edited
        self.assertEqual(self.handoff(self.handle, 3, self.handle.assessment),
                         {"state": "assessment_blocked"})


class RuntimeHandoffTests(unittest.TestCase):
    def setUp(self):
        from app.patient_intake import PatientIntakeService, interview
        from app.patient_intake.session import PatientSession

        self.session_type = PatientSession
        self.handle = self.open_encounter()
        self.provider = Mock()
        self.provider.assess.return_value = {
            "state": "completed", "provider_id": "test-only", "provider_version": "v1",
            "guidance": "Invented consultation guidance.", "uncertainty": "Test-only uncertainty.",
            "urgency": "consultation", "possible_causes": [],
            "next_step": {"kind": "consultation", "specialty_code": "nephrology"},
        }
        self.order = Mock(side_effect=lambda handle, revision: (
            {"service": "dialysis", "required_capabilities": ["monitored"]}
            if handle is self.handle and handle.read()[0] == revision else None
        ))
        self.release = Mock(return_value={"release_ref": "test-release", "as_of": AS_OF,
                                          "campuses": [_campus()]})
        self.handoff = Mock(wraps=PatientHandoff(read_verified_order=self.order,
                                                 read_reviewed_release=self.release,
                                                 today=lambda: date.fromisoformat(AS_OF)))
        self.service = PatientIntakeService(interview=interview, provider=self.provider,
                                            provider_identity=("test-only", "v1"), handoff=self.handoff)

    def open_encounter(self):
        session = self.session_type(notice_version="test-notice")
        handle = session.open(consent=True, notice_version="test-notice")
        self.addCleanup(session.delete, handle)
        return handle

    def complete(self, handle):
        edit = self.service.edit(handle, handle.read()[0], description="Invented symptom statement", context={})
        consent = self.service.consent(handle, edit["revision"], granted=True)
        return self.service.assess(handle, consent["revision"])

    def navigate(self, handle, receipt):
        return self.service.navigate(handle, handle.read()[0], confirmation=receipt)

    def test_other_encounter_cannot_reuse_confirmation_even_at_identical_revision(self):
        completed = self.complete(self.handle)
        receipt = self.service.confirm(self.handle, completed["revision"])
        other = self.open_encounter()
        self.assertEqual(completed, self.complete(other))
        with self.assertRaises(ValueError):
            self.navigate(other, receipt)
        self.handoff.assert_not_called()
        self.order.assert_not_called()
        self.release.assert_not_called()
        self.assertEqual(self.navigate(self.handle, receipt),
                         {"state": "reviewed_destinations",
                          "destinations": [{"facility_id": "TEST-ONLY-CAMPUS", "availability": "unknown"}]})
        self.order.assert_called_once_with(self.handle, completed["revision"])

    def test_edit_blocks_prior_receipt_before_handoff_or_evidence(self):
        completed = self.complete(self.handle)
        receipt = self.service.confirm(self.handle, completed["revision"])
        edited = self.service.edit(self.handle, completed["revision"],
                                   description="A different invented statement", context={})
        self.assertEqual(edited["state"], "draft")
        with self.assertRaises(ValueError):
            self.navigate(self.handle, receipt)
        self.handoff.assert_not_called()
        self.order.assert_not_called()
        self.release.assert_not_called()

    def test_provider_failure_after_success_revokes_navigation(self):
        completed = self.complete(self.handle)
        receipt = self.service.confirm(self.handle, completed["revision"])
        self.assertEqual(self.navigate(self.handle, receipt)["state"], "reviewed_destinations")
        self.handoff.reset_mock()
        self.order.reset_mock()
        self.release.reset_mock()
        self.provider.assess.side_effect = OSError("Test-only provider failure")
        failed = self.service.assess(self.handle, completed["revision"])
        self.assertEqual((failed["state"], failed["guidance"]), ("provider_unavailable", None))
        with self.assertRaises(ValueError):
            self.navigate(self.handle, receipt)
        with self.assertRaises(ValueError):
            self.service.confirm(self.handle, failed["revision"])
        self.handoff.assert_not_called()
        self.order.assert_not_called()
        self.release.assert_not_called()

    def test_unsafe_dispositions_never_dispatch_navigation(self):
        reply = self.provider.assess.return_value
        for state, urgency, assessment_state in [
            ("urgent", "consultation_24", "urgent"),
            ("completed", "emergency", "provider_unavailable"),
            ("completed", "unknown", "provider_unavailable"),
        ]:
            with self.subTest(state=state, urgency=urgency):
                handle = self.open_encounter()
                self.provider.assess.return_value = dict(reply, state=state, urgency=urgency, next_step=None)
                result = self.complete(handle)
                self.assertEqual(result["state"], assessment_state)
                with self.assertRaises(ValueError):
                    self.service.confirm(handle, result["revision"])
        self.handoff.assert_not_called()
        self.order.assert_not_called()
        self.release.assert_not_called()
