"""Offline patient-runtime contract checks using invented data only."""

import pickle
import unittest

from app.patient_intake.contracts import InvalidRecord, _snapshot
from app.patient_intake.service import (
    _Confirmation, _confirmation_tag, _matches_confirmation, _result_secret,
)


class RuntimeBoundaryTests(unittest.TestCase):
    def test_transport_snapshot_is_bounded_detached_and_redacts_failures(self):
        canary = "invented-private-description"
        submitted = {"description": canary, "answers": [{"presence": "unknown"}]}
        detached = _snapshot(submitted)
        submitted["answers"][0]["presence"] = "absent"
        self.assertEqual(detached["answers"][0]["presence"], "unknown")
        cyclic = {canary: []}
        cyclic[canary].append(cyclic)
        for invalid in (cyclic, {canary: float("nan")}, {canary: object()}, {canary: [None] * 5000},
                        {canary: canary * 5000}, {canary: 1 << 65}, {7: canary}):
            with self.assertRaises(InvalidRecord) as caught:
                _snapshot(invalid)
            self.assertNotIn(canary, str(caught.exception))

    def test_receipt_requires_same_result_revision_policy_and_provider(self):
        secret = _result_secret()
        fields = [secret, 7, "policy-1", "test-provider", "edition-1"]
        tag = _confirmation_tag(*fields)
        receipt = _Confirmation(tag)
        self.assertTrue(_matches_confirmation(receipt, tag))
        for i, value in enumerate([_result_secret(), 8, "policy-2", "other-provider", "edition-2"]):
            changed = list(fields)
            changed[i] = value
            self.assertFalse(_matches_confirmation(receipt, _confirmation_tag(*changed)))
        for claimed in ({"ready": True}, tag, True, None):
            self.assertFalse(_matches_confirmation(claimed, tag))
        with self.assertRaises(TypeError):
            pickle.dumps(receipt)


class Handle:
    def __init__(self):
        self.data = {}
        self.rev = 0

    def read(self):
        return self.rev, _snapshot(self.data)

    def replace(self, revision, data):
        if revision != self.rev:
            raise ValueError("revision_stale")
        self.data = _snapshot(data)
        self.rev += 1
        return self.rev


class Interview:
    def start(self, description, context):
        return {"description": description, "context": context}

    def prepare_question(self, question, data):
        return question

    def question_view(self, question):
        return {k: v for k, v in question.items() if k != "id"}

    def answer(self, data, question, question_id, answers):
        return {**data, "answer": answers}

    def has_unresolved_evidence(self, data):
        return data.get("answer") == "unresolved"


class RuntimeFlowTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        from app.patient_intake import PatientIntakeService
        self.handle = Handle()
        self.adapter = Mock()
        self.navigator = Mock(return_value={"state": "no_reviewed_destination"})
        self.identity = dict(provider_id="stub", provider_version="edition-1")
        self.service = PatientIntakeService(interview=Interview(), provider=self.adapter,
                                           provider_identity=("stub", "edition-1"), handoff=self.navigator,
                                           max_turns=3)
        self.result = dict(**self.identity, state="completed", urgency="self_care", guidance="fixture step",
                           uncertainty="fixture uncertainty", possible_causes=[], next_step=None)
        self.adapter.assess.return_value = self.result
        self.edit()
        self.service.consent(self.handle, self.handle.rev, granted=True)

    def edit(self):
        return self.service.edit(self.handle, self.handle.rev, description="novel invented description", context={})

    def assess(self):
        return self.service.assess(self.handle, self.handle.rev)

    def test_question_issuance_current_confirmation_and_edit_invalidation(self):
        self.adapter.assess.return_value = dict(**self.identity, state="awaiting_clarification",
                question=dict(id="vendor", kind="text", prompt="invented follow-up", options=[]), continuation="private-token")
        q = self.assess()["question"]
        with self.assertRaises(ValueError):
            self.service.answer(self.handle, self.handle.rev, question_id="vendor", answers="invented")
        self.service.answer(self.handle, self.handle.rev, question_id=q["issuance_id"], answers="invented")
        self.adapter.assess.return_value = self.result
        a = self.assess()
        self.assertEqual(a["state"], "completed")
        self.assertEqual(self.adapter.assess.call_args.kwargs["continuation"], "private-token")
        receipt = self.service.confirm(self.handle, a["revision"])
        for invalid in (True, a, {"ready": True}):
            with self.assertRaises(ValueError):
                self.service.navigate(self.handle, self.handle.rev, confirmation=invalid)
        self.assertEqual(self.service.navigate(self.handle, a["revision"], confirmation=receipt),
                         {"state": "no_reviewed_destination"})
        self.edit()
        with self.assertRaises(ValueError):
            self.service.navigate(self.handle, self.handle.rev, confirmation=receipt)
        self.assertIsNone(self.assess()["guidance"])
        self.assertEqual(self.adapter.assess.call_count, 2)

    def test_write_superseded_before_readback_reports_stale(self):
        original = self.handle.replace

        def interrupted(revision, data):
            committed = original(revision, data)
            self.handle.replace = original
            self.service.consent(self.handle, committed, granted=False)
            return committed

        self.handle.replace = interrupted
        with self.assertRaisesRegex(ValueError, "revision_stale"):
            self.assess()
        self.adapter.assess.assert_not_called()
        self.assertFalse(self.service.view(self.handle)["consent"])

    def test_late_completion_cannot_replace_an_edit(self):
        def delayed(*args, **kwargs):
            self.assertEqual(self.service.view(self.handle)["state"], "assessment_in_progress")
            self.edit()
            return self.result
        self.adapter.assess.side_effect = delayed
        with self.assertRaises(ValueError):
            self.assess()
        self.assertEqual(self.service.view(self.handle)["state"], "draft")
        self.assertFalse(self.service.view(self.handle)["consent"])

    def test_budget_across_edits_and_failure_after_success(self):
        self.assess()
        self.adapter.assess.side_effect = RuntimeError("private synthetic canary")
        failed = self.assess()
        self.assertEqual(failed["state"], "provider_unavailable")
        self.assertIsNone(failed["guidance"])
        self.assertNotIn("canary", repr(failed))
        self.edit()
        self.service.consent(self.handle, self.handle.rev, granted=True)
        self.assess()
        self.assertEqual(self.assess()["reason"], "budget_exhausted")
        self.assertEqual(self.adapter.assess.call_count, 3)

    def test_completion_and_urgency_with_unresolved_evidence(self):
        self.adapter.assess.return_value = dict(**self.identity, state="awaiting_clarification",
                question=dict(id="v", kind="text", prompt="fixture", options=[]))
        q = self.assess()["question"]
        self.service.answer(self.handle, self.handle.rev, question_id=q["issuance_id"], answers="unresolved")
        self.adapter.assess.return_value = self.result
        self.assertEqual(self.assess()["state"], "unsupported")
        self.adapter.assess.return_value = dict(self.result, state="urgent", urgency="emergency")
        urgent = self.assess()
        self.assertEqual(urgent["guidance"], self.result["guidance"])
        with self.assertRaises(ValueError):
            self.service.confirm(self.handle, self.handle.rev)
        self.navigator.assert_not_called()

    def test_provider_stop_clears_completion_and_requires_a_new_interview(self):
        completed = self.assess()
        prior = self.service.confirm(self.handle, completed["revision"])
        self.adapter.assess.return_value = dict(**self.identity, state="provider_stop", guidance="Invented stop")
        stopped = self.assess()
        self.assertEqual((stopped["state"], stopped["guidance"]), ("provider_stop", "Invented stop"))
        self.assertIsNone(stopped["urgency"])
        self.assertIsNone(stopped["next_step"])
        self.assertEqual(stopped["possible_causes"], [])
        with self.assertRaises(ValueError):
            self.service.confirm(self.handle, stopped["revision"])
        with self.assertRaises(ValueError):
            self.service.navigate(self.handle, stopped["revision"], confirmation=prior)
        self.navigator.assert_not_called()
        self.service.consent(self.handle, self.handle.rev, granted=False)
        self.service.consent(self.handle, self.handle.rev, granted=True)
        with self.assertRaises(ValueError):
            self.assess()
        self.assertEqual(self.adapter.assess.call_count, 2)
        self.edit()
        self.service.consent(self.handle, self.handle.rev, granted=True)
        self.assertEqual(self.assess()["state"], "provider_stop")

    def test_malformed_stop_never_commits_guidance(self):
        for extra in ({"next_step": None}, {"urgency": "emergency"}, {"guidance": " "}):
            self.adapter.assess.return_value = dict(dict(self.identity, state="provider_stop", guidance="Fixture"), **extra)
            result = self.assess()
            self.assertEqual(result["reason"], "invalid_response")
            self.assertIsNone(result["guidance"])

    def test_disposition_must_match_state_and_next_step_before_confirmation(self):
        consult = {"kind": "consultation", "specialty_code": None}
        for state, level, step in (("completed", "emergency", None), ("completed", "unknown", None),
                                   ("completed", "consultation_24", consult), ("urgent", "self_care", None),
                                   ("urgent", "emergency", consult), ("completed", "self_care", consult),
                                   ("completed", "consultation", None)):
            with self.subTest(state=state, level=level, step=step):
                self.handle = Handle()
                self.edit()
                self.service.consent(self.handle, self.handle.rev, granted=True)
                self.adapter.assess.return_value = self.result
                self.assess()
                prior = self.service.confirm(self.handle, self.handle.rev)
                self.adapter.assess.return_value = dict(self.result, state=state, urgency=level, next_step=step)
                result = self.assess()
                self.assertEqual((result["state"], result["reason"]), ("provider_unavailable", "invalid_response"))
                with self.assertRaises(ValueError):
                    self.service.confirm(self.handle, result["revision"])
                with self.assertRaises(ValueError):
                    self.service.navigate(self.handle, result["revision"], confirmation=prior)
        self.navigator.assert_not_called()

    def test_all_five_supported_dispositions(self):
        from app.patient_intake.contracts import _provider_reply
        for level in ("consultation_24", "emergency", "emergency_ambulance", "self_care", "consultation"):
            urgent = level in ("consultation_24", "emergency", "emergency_ambulance")
            step = {"kind": "consultation", "specialty_code": None} if level == "consultation" else None
            reply = dict(self.result, state="urgent" if urgent else "completed", urgency=level, next_step=step)
            self.assertEqual(_provider_reply(reply, ("stub", "edition-1")), reply)

    def test_wrong_provenance_malformed_results_and_absent_configuration(self):
        from app.patient_intake import PatientIntakeService
        for changes in ({"provider_id": "unapproved"}, {"order": True}, {"next_step": {"kind": "procedure"}}):
            self.adapter.assess.return_value = dict(self.result, **changes)
            self.assertEqual(self.assess()["reason"], "invalid_response")
        unconfigured = PatientIntakeService(interview=Interview(), provider=self.adapter)
        self.assertEqual(unconfigured.assess(self.handle, self.handle.rev)["state"], "provider_unavailable")
        self.assertEqual(self.adapter.assess.call_count, 3)
        with self.assertRaises(ValueError):
            self.service.edit(self.handle, None, description="x", context={})

    def test_confirmation_cannot_cross_encounters_at_the_same_revision(self):
        self.assess()
        receipt = self.service.confirm(self.handle, self.handle.rev)
        self.handle = Handle()
        self.edit()
        self.service.consent(self.handle, self.handle.rev, granted=True)
        self.assess()
        with self.assertRaises(ValueError):
            self.service.navigate(self.handle, self.handle.rev, confirmation=receipt)
        self.navigator.assert_not_called()


class OwnedProviderTests(unittest.TestCase):
    """Exercise the approved handle calls without network I/O or a vendor account."""

    class BoundHandle(Handle):
        def __init__(self):
            super().__init__()
            self.binding = None

        def bind_provider(self, expected_revision, factory):
            if expected_revision != self.rev or self.data["state"] != "assessment_in_progress":
                raise ValueError("revision_stale")
            if self.binding is None:
                self.binding = factory()
            return self.binding

        def replace(self, revision, data, *, retire_provider=False):
            committed = super().replace(revision, data)
            if retire_provider and self.binding is not None:
                self.binding.cleanup_reservation.retire()
                self.binding = None
            return committed

    def setUp(self):
        from unittest.mock import Mock
        from app.patient_intake import PatientIntakeService
        self.handle = self.BoundHandle()
        self.adapter = Mock()
        self.factory = Mock(return_value=self.adapter)
        self.service = PatientIntakeService(interview=Interview(), provider_bindings=self.factory,
                                            provider_identity=("fixture", "1"))
        self.reply = dict(state="awaiting_clarification", provider_id="fixture", provider_version="1",
                          question=dict(id="fixture", kind="text", prompt="Invented", options=[]),
                          continuation="private")
        self.adapter.assess.return_value = self.reply
        self.edit()

    def edit(self):
        return self.service.edit(self.handle, self.handle.rev, description="Invented narrative", context={})

    def consent(self, granted):
        return self.service.consent(self.handle, self.handle.rev, granted=granted)

    def assess(self):
        return self.service.assess(self.handle, self.handle.rev)

    def test_consent_precedes_binding_and_repeat_grant_preserves_current_question(self):
        self.assertEqual(self.assess()["reason"], "consent_or_input_required")
        self.factory.assert_not_called()
        self.consent(True)
        q = self.assess()
        self.assertEqual(q["description_status"], "uninterpreted")
        self.assertEqual(self.consent(True), q)
        self.service.answer(self.handle, q["revision"], question_id=q["question"]["issuance_id"], answers="Fixture")
        self.assess()
        self.factory.assert_called_once_with()
        self.assertEqual(self.adapter.assess.call_args.kwargs["continuation"], "private")
        with self.assertRaises(ValueError):
            self.service.consent(self.handle, q["revision"], granted=False)
        self.adapter.cleanup_reservation.retire.assert_not_called()
        self.consent(False)
        self.assertIsNone(self.handle.binding)
        self.adapter.cleanup_reservation.retire.assert_called_once_with()
        self.assertEqual(self.assess()["reason"], "consent_or_input_required")

    def test_edit_during_provider_turn_retires_binding_and_discards_late_question(self):
        self.consent(True)
        def delayed(*args, **kwargs):
            self.edit()
            return self.reply
        self.adapter.assess.side_effect = delayed
        with self.assertRaisesRegex(ValueError, "revision_stale"):
            self.assess()
        self.adapter.cleanup_reservation.retire.assert_called_once_with()
        self.assertIsNone(self.handle.binding)
        current = self.service.view(self.handle)
        self.assertFalse(current["consent"])
        self.assertIsNone(current["question"])

    def test_reservation_failure_withholds_provider_dispatch(self):
        self.consent(True)
        self.factory.side_effect = ValueError("fixture-private-mailbox")
        a = self.assess()
        self.assertEqual((a["state"], a["reason"]), ("provider_unavailable", "unavailable"))
        self.assertNotIn("fixture-private-mailbox", repr(a))
        self.adapter.assess.assert_not_called()

    def test_switching_to_direct_adapter_requires_reconsent_and_retires_old_owner(self):
        from app.patient_intake import PatientIntakeService
        self.consent(True)
        self.assess()
        direct = PatientIntakeService(interview=Interview(), provider=self.adapter, provider_identity=("fixture", "1"))
        self.assertEqual(direct.view(self.handle)["reason"], "configuration_changed")
        direct.consent(self.handle, self.handle.rev, granted=True)
        self.assertIsNone(self.handle.binding)
        self.adapter.cleanup_reservation.retire.assert_called_once_with()
        with self.assertRaises(ValueError):
            PatientIntakeService(interview=Interview(), provider=self.adapter, provider_bindings=self.factory)

    def test_unsupported_context_remains_visible_until_a_valid_edit(self):
        from app.patient_intake import PatientIntakeService
        from app.patient_intake.interview import PatientInterview
        from app.patient_intake.session import PatientSession
        owner = PatientSession(notice_version="fixture")
        handle = owner.open(consent=True, notice_version="fixture")
        self.addCleanup(owner.delete, handle)
        reducer = PatientInterview(supported_age_range=(20, 30), supported_languages=["en-IN"])
        service = PatientIntakeService(interview=reducer, provider_bindings=self.factory,
                                      provider_identity=("fixture", "1"))
        revision = 0
        for context in ({"age_years": 19, "language": "en-IN"}, {"age_years": 24, "language": "fr"}):
            blocked = service.edit(handle, revision, description="Invented", context=context)
            self.assertEqual((blocked["state"], blocked["reason"]), ("unsupported", "unsupported_context"))
            for grant in (True, False):
                self.assertEqual(service.consent(handle, blocked["revision"], granted=grant), blocked)
                self.assertEqual(service.assess(handle, blocked["revision"]), blocked)
            invalid = service.edit(handle, blocked["revision"], description="", context={})
            self.assertEqual(invalid["reason"], "unsupported_context")
            revision = invalid["revision"]
        self.factory.assert_not_called()
        valid = service.edit(handle, revision, description="Invented", context={"age_years": 24, "language": "en-IN"})
        self.assertEqual((valid["state"], valid["reason"], valid["consent"]), ("draft", None, False))
        self.assertEqual(service.assess(handle, valid["revision"])["reason"], "consent_or_input_required")
