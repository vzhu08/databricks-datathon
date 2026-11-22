"""Synthetic acceptance cases executed against the staged production modules."""

import sys
from collections import deque
from copy import deepcopy
from unittest import TestCase, defaultTestLoader, TextTestRunner
from unittest.mock import Mock, patch

from patient_intake import POLICY_VERSION, PatientIntakeService
from patient_intake.handoff import PatientHandoff
from patient_intake.interview import PatientInterview
from patient_intake.providers.transport import Budget, Transport
from patient_intake.session import PatientSession, PatientSessionError


IDENTITY = ("test-only-assessment", "fixture-v1")
NOTICE = "test-only-notice.v1"
CONTEXT = {"age_years": 38, "language": "en"}
DESCRIPTION = "Invented fixture: my left wrist aches after carrying a box."
SECOND_DESCRIPTION = "Invented fixture: my right ankle aches after a walk."
GUIDANCE = "Fixture guidance from the test provider."


def reply(state, **fields):
    return {"state": state, "provider_id": IDENTITY[0], "provider_version": IDENTITY[1], **fields}


def completed(*, urgency="consultation", **updates):
    fields = {
        "guidance": GUIDANCE,
        "urgency": urgency,
        "uncertainty": "Fixture uncertainty.",
        "possible_causes": [],
        "next_step": {"kind": "consultation", "specialty_code": None},
    }
    fields.update(updates)
    return reply("completed", **fields)


class ScriptedProvider:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def assess(self, interview_data, *, continuation=None):
        self.calls.append((deepcopy(interview_data), continuation))
        return self.responses.popleft()


class FaultProvider:
    """Return one valid control, then exercise the real neutral HTTP boundary."""

    def __init__(self, exchange):
        self.exchange = Mock(side_effect=exchange)
        self.transport = Transport(host="fixture.invalid", headers={}, attempts=1, exchange=self.exchange)
        self.budget = Budget(1)
        self.calls = 0

    def assess(self, interview_data, *, continuation=None):
        self.calls += 1
        if self.calls == 1:
            return completed()
        result = self.transport.request(
            "POST", "/synthetic-check", payload=interview_data, encounter=self.budget,
        )
        return reply("provider_unavailable", reason=result.status)


class RuntimeFixture(TestCase):
    def encounter(self):
        owner = PatientSession(notice_version=NOTICE)
        handle = owner.open(consent=True, notice_version=NOTICE)

        def clear():
            if owner.status == "active":
                owner.delete(handle)

        self.addCleanup(clear)
        return owner, handle

    def start(self, service, handle, description=DESCRIPTION):
        initial = service.view(handle)
        draft = service.edit(
            handle, initial["revision"], description=description, context=CONTEXT,
        )
        self.assertEqual(draft["state"], "draft")
        self.assertEqual(draft["policy_version"], POLICY_VERSION)
        return service.consent(handle, draft["revision"], granted=True)

    def service(self, provider, *, handoff=None, **limits):
        return PatientIntakeService(
            interview=PatientInterview(), provider=provider, provider_identity=IDENTITY,
            handoff=handoff, **limits,
        )

    def assert_withheld(self, result):
        self.assertIsNone(result["guidance"])
        self.assertIsNone(result["question"])
        self.assertIsNone(result["next_step"])
        self.assertEqual(result["possible_causes"], [])


class StagedRuntimeCases(RuntimeFixture):
    def test_fresh_input_review_follow_up_and_no_reviewed_destination(self):
        evidence = reply(
            "awaiting_clarification",
            question={
                "id": "fixture-vendor-evidence",
                "kind": "evidence_review",
                "prompt": "Please review the fixture observation.",
                "options": [{"id": decision, "label": decision}
                            for decision in ("confirm", "uncertain", "disagree")],
                "evidence": {"concept_id": "fixture-observation", "label": "Left wrist discomfort",
                             "presence": "present", "temporality": "current", "source_ref": "description"},
            },
            continuation="fixture-private-turn-one",
        )
        question = reply(
            "awaiting_clarification",
            question={"id": "fixture-vendor-followup", "kind": "text",
                      "prompt": "When did the fictional discomfort start?", "options": []},
            continuation="fixture-private-turn-two",
        )
        provider = ScriptedProvider(evidence, question, completed())
        _, handle = self.encounter()
        handoff = Mock(wraps=PatientHandoff())
        service = self.service(provider, handoff=handoff)
        consented = self.start(service, handle)
        self.assertEqual(provider.calls, [])

        first = service.assess(handle, consented["revision"])
        self.assertEqual(first["state"], "awaiting_clarification")
        self.assertEqual(first["question"]["evidence"]["label"], "Left wrist discomfort")
        self.assertIsNone(first["guidance"])
        for private in ("fixture-private-turn-one", "fixture-vendor-evidence",
                        "fixture-observation", DESCRIPTION):
            self.assertNotIn(private, repr(first))
        evidence_review = service.answer(
            handle, first["revision"], question_id=first["question"]["issuance_id"], answers="confirm",
        )
        follow_up = service.assess(handle, evidence_review["revision"])
        self.assertEqual(follow_up["question"]["kind"], "text")
        self.assertNotEqual(follow_up["question"]["issuance_id"], first["question"]["issuance_id"])
        answered = service.answer(
            handle, follow_up["revision"], question_id=follow_up["question"]["issuance_id"],
            answers="After the fictional task.",
        )
        self.assertEqual(len(provider.calls), 2)
        result = service.assess(handle, answered["revision"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["guidance"], GUIDANCE)
        self.assertEqual(service.view(handle), result)
        self.assertEqual([c for _, c in provider.calls],
                         [None, "fixture-private-turn-one", "fixture-private-turn-two"])
        self.assertEqual(provider.calls[0][0]["source"]["description"], DESCRIPTION)
        supplied = provider.calls[-1][0]
        self.assertEqual(supplied["patient_evidence"][0]["origin"], "patient_review")
        self.assertEqual(supplied["patient_evidence"][0]["patient_presence"], "present")
        self.assertEqual(supplied["answers"][-1]["answer"], "After the fictional task.")

        handoff.assert_not_called()
        confirmation = service.confirm(handle, result["revision"])
        destination = service.navigate(handle, result["revision"], confirmation=confirmation)
        self.assertEqual(destination, {"state": "no_reviewed_destination"})
        handoff.assert_called_once()
        self.assertFalse(any(name.endswith("travel.tomtom") for name in sys.modules))
        self.assertEqual(service.view(handle), result)

    def test_missing_approved_configuration_never_sends_or_returns_a_fixture(self):
        for provider in (None, ScriptedProvider(completed())):
            with self.subTest(has_adapter=provider is not None):
                _, handle = self.encounter()
                handoff = Mock()
                service = PatientIntakeService(
                    interview=PatientInterview(), provider=provider, handoff=handoff,
                )
                draft = self.start(service, handle)
                result = service.assess(handle, draft["revision"])
                self.assertEqual(result["state"], "provider_unavailable")
                self.assert_withheld(result)
                if provider is not None:
                    self.assertEqual(provider.calls, [])
                with self.assertRaises(ValueError):
                    service.confirm(handle, result["revision"])
                handoff.assert_not_called()

    def test_timeout_rate_limit_and_bad_reply_clear_previous_success(self):
        for name, exchange in (
            ("timeout", TimeoutError("opaque-fixture-error")),
            ("rate_limited", lambda *args: (429, "application/json", b"", {"Retry-After": "1"})),
            ("invalid_response", lambda *args: (200, "application/json", b"{", {})),
        ):
            with self.subTest(failure=name):
                _, handle = self.encounter()
                provider = FaultProvider(exchange)
                handoff = Mock(wraps=PatientHandoff())
                service = self.service(provider, handoff=handoff)
                ready = self.start(service, handle)
                good = service.assess(handle, ready["revision"])
                self.assertEqual(good["state"], "completed")
                old = service.confirm(handle, good["revision"])
                failure = service.assess(handle, good["revision"])
                self.assertEqual(failure["state"], "provider_unavailable")
                self.assertEqual(failure["reason"], name)
                self.assert_withheld(failure)
                self.assertEqual(service.view(handle), failure)
                self.assertNotIn("opaque-fixture-error", repr(failure))
                self.assertEqual(provider.calls, 2)
                provider.exchange.assert_called_once()
                with self.assertRaises(ValueError):
                    service.navigate(handle, good["revision"], confirmation=old)
                with self.assertRaises(ValueError):
                    service.confirm(handle, failure["revision"])
                handoff.assert_not_called()

    def test_edit_invalidates_consent_and_the_old_result_even_at_a_new_revision(self):
        _, handle = self.encounter()
        provider = ScriptedProvider(completed(), completed())
        handoff = Mock(wraps=PatientHandoff())
        service = self.service(provider, handoff=handoff)
        initial = self.start(service, handle)
        done = service.assess(handle, initial["revision"])
        old = service.confirm(handle, done["revision"])
        edited = service.edit(
            handle, done["revision"], description=SECOND_DESCRIPTION, context=CONTEXT,
        )
        self.assertEqual(edited["state"], "draft")
        self.assertFalse(edited["consent"])
        self.assert_withheld(edited)
        withheld = service.assess(handle, edited["revision"])
        self.assertEqual(withheld["state"], "draft")
        self.assertEqual(len(provider.calls), 1)
        confirmed_input = service.consent(handle, withheld["revision"], granted=True)
        current = service.assess(handle, confirmed_input["revision"])
        self.assertEqual(current["state"], "completed")
        self.assertEqual(provider.calls[1][0]["source"]["description"], SECOND_DESCRIPTION)
        with self.assertRaises(ValueError):
            service.navigate(handle, current["revision"], confirmation=old)
        handoff.assert_not_called()
        new = service.confirm(handle, current["revision"])
        self.assertEqual(service.navigate(handle, current["revision"], confirmation=new),
                         {"state": "no_reviewed_destination"})

    def test_two_server_sessions_and_expiry_cannot_reuse_an_assessment(self):
        now = [125.0]
        with patch("patient_intake.session.monotonic", side_effect=lambda: now[0]):
            first_owner, first_handle = self.encounter()
            provider = ScriptedProvider(completed(), completed())
            handoff = Mock(wraps=PatientHandoff())
            service = self.service(provider, handoff=handoff)
            first = self.start(service, first_handle)
            first_result = service.assess(first_handle, first["revision"])
            receipt = service.confirm(first_handle, first_result["revision"])

            now[0] += 100
            second_owner, second_handle = self.encounter()
            self.assertEqual(service.view(second_handle)["state"], "draft")
            self.assert_withheld(service.view(second_handle))
            second = self.start(service, second_handle, SECOND_DESCRIPTION)
            second_result = service.assess(second_handle, second["revision"])
            self.assertEqual(first_result["revision"], second_result["revision"])
            with self.assertRaises(ValueError):
                service.navigate(second_handle, second_result["revision"], confirmation=receipt)
            self.assertEqual(provider.calls[-1][0]["source"]["description"], SECOND_DESCRIPTION)

            now[0] += 800
            self.assertEqual(first_owner.status, "expired")
            with self.assertRaises(PatientSessionError) as expired:
                service.view(first_handle)
            self.assertEqual(expired.exception.code, "session_encounter_unavailable")
            with self.assertRaises(PatientSessionError):
                service.navigate(first_handle, first_result["revision"], confirmation=receipt)
            self.assertEqual(second_owner.status, "active")
            self.assertEqual(service.view(second_handle), second_result)
            handoff.assert_not_called()


    def test_urgent_guidance_cannot_turn_into_an_ordinary_handoff(self):
        variants = (
            (completed(urgency="emergency"), "provider_unavailable"),
            (completed(urgency="unknown"), "provider_unavailable"),
            (reply("urgent", guidance=GUIDANCE, urgency="consultation_24",
                   uncertainty="Fixture uncertainty.", next_step=None, possible_causes=[]), "urgent"),
        )
        for response, expected in variants:
            with self.subTest(state=response["state"], urgency=response["urgency"]):
                _, handle = self.encounter()
                provider = ScriptedProvider(response)
                handoff = Mock()
                service = self.service(provider, handoff=handoff)
                draft = self.start(service, handle)
                result = service.assess(handle, draft["revision"])
                self.assertEqual(result["state"], expected)
                self.assertEqual(result["guidance"], GUIDANCE if expected == "urgent" else None)
                with self.assertRaises(ValueError):
                    service.confirm(handle, result["revision"])
                handoff.assert_not_called()

    def test_storage_limit_after_followups_clears_the_oversized_result(self):
        question = reply(
            "awaiting_clarification",
            question={"id": "fixture-text", "kind": "text", "prompt": "Fixture follow-up.", "options": []},
        )
        oversized = completed(
            guidance="g" * 2048, uncertainty="u" * 2048, possible_causes=["x" * 256] * 32,
        )
        provider = ScriptedProvider(*([question] * 12), oversized)
        _, handle = self.encounter()
        handoff = Mock()
        service = self.service(provider, handoff=handoff, max_turns=13)
        current = self.start(service, handle, DESCRIPTION.ljust(4000, "x"))
        for index in range(12):
            issued = service.assess(handle, current["revision"])
            with self.subTest(followup=index):
                self.assertEqual(issued["state"], "awaiting_clarification")
                current = service.answer(
                    handle, issued["revision"], question_id=issued["question"]["issuance_id"],
                    answers="x" * 1500,
                )
        result = service.assess(handle, current["revision"])
        self.assertEqual(result["state"], "provider_unavailable")
        self.assertEqual(result["reason"], "invalid_response")
        self.assert_withheld(result)
        self.assertEqual(len(provider.calls), 13)
        self.assertEqual(service.view(handle), result)
        handoff.assert_not_called()
