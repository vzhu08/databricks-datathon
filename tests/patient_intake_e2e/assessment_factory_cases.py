"""App-only composition checks for both factory modes using synthetic exchanges."""

from unittest.mock import Mock

from patient_intake import PatientIntakeService
from patient_intake.handoff import PatientHandoff
from patient_intake.interview import PatientInterview
from patient_intake.session import PatientSession


ASSESSMENT_ID = "databricks-assessment-experimental"
ASSESSMENT_SOURCE = "Invented fixture: my nose itches and I keep sneezing today."
POSSIBILITIES = ["allergic rhinitis", "viral respiratory infection"]
DIFFERENTIAL = {
    "causes": [{"label": label, "row": 0} for label in POSSIBILITIES],
    "urgency": "consultation",
    "uncertainty": "overlap",
}


def extracted(source):
    return {"observations": [{"quote": source, "presence": "present", "temporality": "current"}],
            "topic": "change"}


class AssessmentFactoryRuntimeCases(FactoryScreenFixture):
    def open_service(self, *, mode="assessment", lane="test", source=ASSESSMENT_SOURCE):
        provider = databricks_config.configured_databricks_provider(
            enabled=True, endpoint=ENDPOINT, lane=lane, demo_attempts=6, test_attempts=2, mode=mode,
        )
        owner = PatientSession(notice_version="fixture.v1")
        handle = owner.open(consent=True, notice_version="fixture.v1")
        self.addCleanup(lambda: owner.delete(handle) if owner.status == "active" else None)
        handoff = Mock(wraps=PatientHandoff())
        service = PatientIntakeService(
            interview=PatientInterview(), provider=provider, provider_identity=provider.identity, handoff=handoff,
        )
        draft = service.edit(handle, 0, description=source, context={"age_years": 37, "language": "en"})
        self.assertFalse(draft["consent"])
        return service, handle, handoff, draft

    @staticmethod
    def dispatch(service, handle, draft):
        consented = service.consent(handle, draft["revision"], granted=True)
        return service.assess(handle, consented["revision"])

    def respond(self, service, handle, view, answer):
        self.assertEqual(view["state"], "awaiting_clarification")
        recorded = service.answer(
            handle, view["revision"], question_id=view["question"]["issuance_id"], answers=answer,
        )
        return service.assess(handle, recorded["revision"])

    def assert_terminal_no_handoff(self, service, handle, handoff, view):
        with self.assertRaises(ValueError):
            service.confirm(handle, view["revision"])
        with self.assertRaises(ValueError):
            service.navigate(handle, view["revision"], confirmation=object())
        handoff.assert_not_called()

    def test_factory_modes_share_quota_and_differential_never_reaches_handoff(self):
        exchange, constructor = self.connect([
            extracted(ASSESSMENT_SOURCE), {"next": "review_summary"},
            extracted(ASSESSMENT_SOURCE), DIFFERENTIAL,
        ])
        doc, handle, handoff, draft = self.open_service(mode="documentation")
        view = self.dispatch(doc, handle, draft)
        for answer in ("confirm", "worsened"):
            view = self.respond(doc, handle, view, answer)
        self.assertEqual(view["state"], "provider_stop")
        self.assertEqual(view["possible_causes"], [])
        self.assert_terminal_no_handoff(doc, handle, handoff, view)
        self.assertEqual(len(exchange.requests), 2)

        assessment, handle, handoff, draft = self.open_service()
        view = self.dispatch(assessment, handle, draft)
        self.assertIn("112", view["question"]["prompt"])
        view = self.respond(assessment, handle, view, "no")
        self.assertEqual(view["reason"], "budget_exhausted")
        self.assertEqual(len(exchange.requests), 2)
        self.assert_terminal_no_handoff(assessment, handle, handoff, view)

        assessment, handle, handoff, draft = self.open_service(lane="demo")
        view = self.dispatch(assessment, handle, draft)
        self.assertEqual(len(exchange.requests), 2)
        view = self.respond(assessment, handle, view, "no")
        self.assertEqual(view["question"]["evidence"]["label"], ASSESSMENT_SOURCE)
        view = self.respond(assessment, handle, view, "confirm")
        self.assertEqual(len(exchange.requests), 3)
        result = self.respond(assessment, handle, view, "worsened")
        self.assertEqual(result["state"], "experimental_assessment")
        self.assertEqual(result["provider_id"], ASSESSMENT_ID)
        self.assertEqual(result["provider_version"], ENDPOINT + "-assessment.v1")
        self.assertEqual(result["possible_causes"], POSSIBILITIES)
        self.assertEqual(result["urgency"], "consultation")
        self.assertTrue(result["uncertainty"])
        self.assertEqual(result["next_step"], {"kind": "consultation", "specialty_code": None})
        self.assert_terminal_no_handoff(assessment, handle, handoff, result)
        constructor.assert_called_once()
        self.assertEqual(len(exchange.requests), 4)
        self.assertEqual(exchange.pending, deque())
        wire = exchange.requests[-1][2]
        self.assertEqual(wire["max_tokens"], 1024)
        details = json.loads(wire["messages"][1]["content"])
        self.assertEqual(details["context"], {"age_years": 37, "language": "en"})
        self.assertEqual(details["reviewed"], [
            {"quote": ASSESSMENT_SOURCE, "presence": "present", "temporality": "current"},
        ])
        self.assertEqual(details["clarification"], {"topic": "change", "answer": "worsened"})

        changed = assessment.edit(
            handle, result["revision"], description="A different invented statement.",
            context={"age_years": 37, "language": "en"},
        )
        self.assertIsNone(changed["guidance"])
        self.assertEqual(changed["possible_causes"], [])
        self.assertFalse(changed["consent"])
        with self.assertRaises(ValueError):
            assessment.assess(handle, result["revision"])
        self.assert_terminal_no_handoff(assessment, handle, handoff, changed)
        self.assertEqual(len(exchange.requests), 4)

    def test_reported_or_uncertain_warning_has_zero_model_cost(self):
        exchange, constructor = self.connect([])
        for answer in ("yes", "unsure"):
            with self.subTest(answer=answer):
                service, handle, handoff, draft = self.open_service()
                view = self.dispatch(service, handle, draft)
                self.assertIn("112", view["question"]["prompt"])
                result = self.respond(service, handle, view, answer)
                self.assertEqual(result["state"], "experimental_assessment")
                self.assertEqual(result["urgency"], "emergency_ambulance")
                self.assertEqual(result["possible_causes"], [])
                self.assertIsNone(result["next_step"])
                self.assert_terminal_no_handoff(service, handle, handoff, result)
        constructor.assert_called_once()
        self.assertEqual(exchange.requests, [])

    def test_abstain_and_invalid_assessment_reply_withhold_handoff(self):
        exchange, _ = self.connect([
            extracted(ASSESSMENT_SOURCE), {"abstain": True},
            extracted(ASSESSMENT_SOURCE), {**DIFFERENTIAL, "confidence": 0.9},
        ])
        for expected in ("provider_stop", "provider_unavailable"):
            with self.subTest(expected=expected):
                service, handle, handoff, draft = self.open_service(lane="demo")
                view = self.dispatch(service, handle, draft)
                for answer in ("no", "confirm", "worsened"):
                    view = self.respond(service, handle, view, answer)
                self.assertEqual(view["state"], expected)
                self.assertEqual(view["possible_causes"], [])
                self.assertIsNone(view["urgency"])
                self.assertIsNone(view["next_step"])
                self.assert_terminal_no_handoff(service, handle, handoff, view)
        self.assertEqual(len(exchange.requests), 4)

    def test_confirmed_warning_and_vague_report_stop_before_final_exchange(self):
        warning = "I have heavy pressure in the middle of my chest right now and I am short of breath."
        vague = "Something is wrong."
        exchange, _ = self.connect([extracted(warning), extracted(vague)])
        service, handle, handoff, draft = self.open_service(lane="demo", source=warning)
        view = self.dispatch(service, handle, draft)
        view = self.respond(service, handle, view, "no")
        result = self.respond(service, handle, view, "confirm")
        self.assertEqual((result["state"], result["urgency"]), ("experimental_assessment", "emergency_ambulance"))
        self.assertEqual(result["possible_causes"], [])
        self.assert_terminal_no_handoff(service, handle, handoff, result)
        self.assertEqual(len(exchange.requests), 1)

        service, handle, handoff, draft = self.open_service(lane="demo", source=vague)
        view = self.dispatch(service, handle, draft)
        for answer in ("no", "confirm", "worsened"):
            view = self.respond(service, handle, view, answer)
        self.assertEqual(view["state"], "provider_stop")
        self.assertEqual(view["possible_causes"], [])
        self.assert_terminal_no_handoff(service, handle, handoff, view)
        self.assertEqual(len(exchange.requests), 2)
