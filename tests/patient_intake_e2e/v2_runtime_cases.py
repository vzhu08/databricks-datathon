"""Staged v2 forms and lifecycle, with a synthetic exchange replacing HTTPS."""

import json
from threading import Event, Thread

from patient_intake.providers.mgp import PROVIDER_ID, PROVIDER_VERSION
from patient_intake.providers.mgp_v2 import OwnedMgpSurvey, dispose_claim
from patient_intake.session import CleanupMailbox


ROOT = "/api/mgp/v1/"
ROLES = ("users", "patients", "surveys")
UID, PID, SID = IDS = [f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 4)]
CREATIONS = (
    (201, {"id": UID}),
    (201, {"id": PID, "user_id": UID}),
    (201, {"id": SID, "patient_id": PID, "type": "triage"}),
)
CATALOG = {"complete": True, "id": "fixture-catalog", "edition": "fixture-edition",
           "items": [{"id": "fixture-vendor-item", "name": "Invented observation"}]}


def wire_question(index, kind, **meta):
    return (200, {"id": f"fixture-question-{index}", "index": index,
                  "question": {"text": f"Invented question {index}"},
                  "answer_type": kind, "meta": meta})


class Exchange:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def __call__(self, host, method, path, headers, body, timeout):
        self.calls.append((method, path, None if body is None else json.loads(body)))
        response = self.responses.popleft()
        status, value = response() if callable(response) else response
        return status, "application/json", json.dumps(value).encode() if value is not None else b"", {}


class StagedV2Cases(RuntimeFixture):
    def owned_service(self, wire, *, mailbox=None, units_for=None, catalog_for=None):
        mailbox = CleanupMailbox() if mailbox is None else mailbox
        transport = Transport(host="fixture.invalid", headers={}, attempts=24, exchange=wire)
        factory = Mock(side_effect=lambda: OwnedMgpSurvey(
            mailbox=mailbox, session=transport, budget=Budget(24), enabled=True,
            # A preapproved fixture context, not a clinical interpretation of prose.
            reconciled=lambda data: data["source"]["description"] == DESCRIPTION,
            units_for=units_for, catalog_for=catalog_for, stop_guidance="Fixture provider stop.",
        ))
        service = PatientIntakeService(
            interview=PatientInterview(), provider_bindings=factory, max_turns=12,
            provider_identity=(PROVIDER_ID, PROVIDER_VERSION), handoff=PatientHandoff(),
        )
        return service, mailbox, factory

    def test_v2_forms_transport_and_reverse_order_disposal(self):
        option = {"id": "option-a", "label": "A"}
        wire = Exchange(
            *CREATIONS,
            wire_question(0, "choice", required=False, answers=[option]),
            wire_question(1, "symptoms", component="group_single",
                          answers=[{"id": x, "name": label} for x, label in (("left", "Left"), ("right", "Right"))]),
            wire_question(2, "symptoms", component="group_multiple",
                          answers=[
                              {"id": "first", "name": "First", "choices": [{"id": "absent", "label": "No"}]},
                              {"id": "second", "name": "Second", "choices": [{"id": "unknown", "label": "Unsure"}]},
                          ]),
            wire_question(3, "age", min_value=0, max_value=90),
            wire_question(4, "duration", evidence_id="fixture-evidence"),
            wire_question(5, "list", source_list_url="/v1/knowledge/symptoms?language=en"),
            wire_question(6, "multiple_choice", answers=[option]),
            wire_question(7, "text", required=False),
            (204, None), (200, {"id": SID, "type": "triage", "status": "completed"}),
            (200, {"triage": {"level": "consultation", "description": GUIDANCE, "serious": []},
                   "conditions": [{"common_name": "Invented possibility"}]}),
        )

        def units_for(_, raw):
            age = raw["answer_type"] == "age"
            unit = "year" if age else "hour"
            return [{"id": unit, "label": unit, "min": 0, "max": 90, "integer_only": age}]

        owner, handle = self.encounter()
        service, mailbox, factory = self.owned_service(
            wire, units_for=units_for, catalog_for=lambda *_: CATALOG,
        )
        initial = self.start(service, handle)
        self.assertEqual(wire.calls, [])
        factory.assert_not_called()
        current = service.assess(handle, initial["revision"])
        self.assertEqual(current["description_status"], "uninterpreted")
        forms = [
            ("single", {"skip": True}, None),
            ("single", {"skip": True}, [{"id": value, "choice_id": "unknown"} for value in ("left", "right")]),
            ("item_presence", {"items": [{"id": "second", "presence": "unknown"},
                                         {"id": "first", "presence": "absent"}]},
             [{"id": "first", "choice_id": "absent"}, {"id": "second", "choice_id": "unknown"}]),
            ("quantity", {"value": 38, "unit_id": "year"}, {"value": 38, "unit": "year"}),
            ("quantity", {"value": 1.5, "unit_id": "hour"},
             [{"id": "fixture-evidence", "duration": {"value": 1.5, "unit": "hour"}}]),
            ("catalog_selection", None, [{"id": "fixture-vendor-item"}]),
            ("multiple", ["option-a"], [{"id": "option-a"}]),
            ("text", {"skip": True}, None),
        ]

        for index, (kind, answer, expected_wire) in enumerate(forms):
            with self.subTest(form=index, kind=kind):
                public = current["question"]
                self.assertEqual(current["state"], "awaiting_clarification")
                self.assertEqual(public["schema"], "patient-question.v2")
                self.assertEqual(public["kind"], kind)
                self.assertNotIn("id", public)
                call_count = len(wire.calls)
                issuance = public["issuance_id"]
                if kind == "catalog_selection":
                    catalog_handle = public["options"][0]["id"]
                    self.assertNotEqual(catalog_handle, "fixture-vendor-item")
                    self.assertNotIn("catalog", public)
                    answer = [catalog_handle]
                    wrong = ["fixture-vendor-item"]
                elif kind == "item_presence":
                    self.assertEqual(public["items"][1]["choices"], [{"id": "unknown", "label": "Unsure"}])
                    wrong = {"items": [{"id": "first", "presence": "unknown"}]}
                elif kind == "quantity":
                    wrong = {"value": 38.0, "unit_id": "year"} if index == 3 else {
                        "value": 1.5, "unit_id": "invented",
                    }
                else:
                    wrong = None
                for rejected_id, rejected_answer in ((issuance, wrong), ("stale-issuance", answer)):
                    with self.assertRaises(ValueError):
                        service.answer(handle, current["revision"], question_id=rejected_id, answers=rejected_answer)
                draft = service.answer(handle, current["revision"], question_id=issuance, answers=answer)
                self.assertEqual(len(wire.calls), call_count)
                current = service.assess(handle, draft["revision"])
                self.assertEqual(wire.calls[call_count],
                                 ("POST", ROOT + f"surveys/{SID}/questions/current", {"answer": expected_wire}))

        self.assertEqual(current["state"], "completed")
        self.assertEqual(current["description_status"], "uninterpreted")
        self.assertEqual(wire.calls[:3], [
            ("POST", ROOT + "users", {}),
            ("POST", ROOT + "patients", {"user_id": UID}),
            ("POST", ROOT + "surveys", {"type": "triage", "patient_id": PID}),
        ])
        self.assertNotIn(DESCRIPTION, repr(wire.calls))
        factory.assert_called_once()
        confirmation = service.confirm(handle, current["revision"])
        self.assertEqual(service.navigate(handle, current["revision"], confirmation=confirmation),
                         {"state": "no_reviewed_destination"})
        self.assertEqual(mailbox.counts(), {"attached": 1})
        prior = len(wire.calls)
        owner.reset(handle)
        self.assertEqual(len(wire.calls), prior)
        with self.assertRaises(PatientSessionError):
            service.view(handle)
        self.assertEqual(mailbox.counts(), {"pending": 1})
        cleanup_wire = Exchange((204, None), (404, None), (204, None))
        cleanup = Transport(host="fixture.invalid", headers={}, attempts=3, exchange=cleanup_wire)
        self.assertTrue(dispose_claim(mailbox, cleanup_session=cleanup, cleanup_budget=Budget(3)))
        self.assertEqual(cleanup_wire.calls,
                         [("DELETE", ROOT + f"{role}/{identifier}", None)
                          for role, identifier in reversed(tuple(zip(ROLES, IDS)))])
        self.assertEqual(mailbox.counts(), {})

    def test_unrepresentable_form_and_supported_stops_do_not_issue_a_question(self):
        for question, state in (
            (wire_question(0, "list", source_list_url="/v1/knowledge/symptoms?language=en"), "unsupported"),
            (wire_question(0, "age", min_value=0, max_value=90), "unsupported"),
            (wire_question(0, "future", alerts=[{"type": "hard_stop", "reasons": ["suicidal_intent"]}]),
             "provider_stop"),
            (wire_question(0, "future", alerts=[{"type": "hard_stop", "reasons": ["emergency", "unrecognized"]}]),
             "urgent"),
        ):
            with self.subTest(expected_state=state):
                _, handle = self.encounter()
                wire = Exchange(*CREATIONS, question)
                service, _, _ = self.owned_service(wire, catalog_for=lambda *_: {**CATALOG, "complete": False})
                draft = self.start(service, handle)
                result = service.assess(handle, draft["revision"])
                self.assertEqual(result["state"], state)
                self.assertIsNone(result["question"])
                self.assertIsNone(result["next_step"])
                with self.assertRaises(ValueError):
                    service.confirm(handle, result["revision"])
                self.assertEqual(len(wire.calls), 4)

    def test_saturated_cleanup_mailbox_prevents_provider_creation(self):
        mailbox = CleanupMailbox(capacity=1)
        reserved = mailbox.reserve()
        self.addCleanup(reserved.retire)
        wire = Exchange()
        _, handle = self.encounter()
        service, _, _ = self.owned_service(wire, mailbox=mailbox)
        draft = self.start(service, handle)
        result = service.assess(handle, draft["revision"])
        self.assertEqual(result["state"], "provider_unavailable")
        self.assert_withheld(result)
        self.assertEqual(wire.calls, [])

    def test_reset_during_creation_tracks_late_or_unknown_delivery(self):
        for known in (True, False):
            with self.subTest(verified_late_id=known):
                started, release = Event(), Event()

                def late_create():
                    started.set()
                    if not release.wait(3) or not known:
                        raise TimeoutError("Invented ambiguous request")
                    return CREATIONS[0]

                owner, handle = self.encounter()
                wire = Exchange(late_create)
                service, mailbox, _ = self.owned_service(wire)
                consented = self.start(service, handle)
                outcomes = []

                def assess():
                    try:
                        outcomes.append(service.assess(handle, consented["revision"]))
                    except PatientSessionError as error:
                        outcomes.append(error.code)

                thread = Thread(target=assess, daemon=True)
                thread.start()
                try:
                    self.assertTrue(started.wait(2))
                    owner.reset(handle)
                    self.assertEqual(owner.status, "reset")
                    self.assertEqual(mailbox.counts(), {"awaiting_create": 1})
                    self.assertIsNone(mailbox.claim())
                finally:
                    release.set()
                    thread.join(3)

                self.assertFalse(thread.is_alive())
                self.assertEqual(outcomes, ["session_encounter_unavailable"])
                self.assertEqual(wire.calls, [("POST", ROOT + "users", {})])
                if known:
                    cleanup_wire = Exchange((204, None))
                    cleanup = Transport(host="fixture.invalid", headers={}, attempts=1, exchange=cleanup_wire)
                    self.assertTrue(dispose_claim(mailbox, cleanup_session=cleanup, cleanup_budget=Budget(1)))
                    self.assertEqual(cleanup_wire.calls, [("DELETE", ROOT + f"users/{UID}", None)])
                    self.assertEqual(mailbox.counts(), {})
                else:
                    self.assertEqual(mailbox.counts(), {"unresolved": 1})
                    self.assertIsNone(mailbox.claim())
