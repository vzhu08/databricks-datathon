"""Supplemental offline v2 checks. Run with -I -S -B and a pinned app/ path."""

from contextlib import contextmanager
import json
from pathlib import Path
import sys
from threading import Event, Thread
import unittest

# Load only our observer helpers before selecting the candidate app.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_binding import Encounter, SideEffects, attempt, completion, encounter
sys.path.pop(0)

USER = "00000000-0000-0000-0000-000000000011"
PATIENT = "00000000-0000-0000-0000-000000000022"
SURVEY = "00000000-0000-0000-0000-000000000033"


class Wire:
    """Record actual N exchange starts without retaining headers or calling HTTPS."""

    def __init__(self, respond):
        from patient_intake.providers.transport import Budget, Transport

        self.calls = []
        self.respond = respond
        self.budget = Budget(16)
        self.transport = Transport(host="audit.invalid", headers={}, attempts=16, exchange=self.exchange)

    def exchange(self, host, method, path, headers, body, timeout):
        payload = json.loads(body) if body is not None else None
        self.calls.append((method, path, payload))
        status, resource = self.respond(method, path, payload)
        return status, "application/json", json.dumps(resource).encode() if resource is not None else b"", {}


@contextmanager
def session(*, provider=None, factory=None):
    from patient_intake import PatientIntakeService
    from patient_intake.interview import PatientInterview
    from patient_intake.providers.mgp import PROVIDER_ID, PROVIDER_VERSION
    from patient_intake.session import PatientSession

    service = PatientIntakeService(interview=PatientInterview(), provider=provider, provider_bindings=factory,
                                   provider_identity=(PROVIDER_ID, PROVIDER_VERSION))
    owner = PatientSession(notice_version="audit-v1")
    flow = Encounter(owner, service, provider)
    try:
        yield flow
    finally:
        if owner.status == "active":
            owner.delete(flow.handle)


def prebound(wire):
    from patient_intake.providers.mgp_v2 import MgpSurveyV2

    def current_answer(interview, ident):
        row = interview["answers"][-1]
        return row if row["provider_question_id"] == ident else None

    return MgpSurveyV2(enabled=True, survey_for=lambda _: SURVEY, choices_for=current_answer,
                       transport=wire.transport, budget=wire.budget, stop_guidance="Synthetic stop guidance")


class V2Checks(unittest.TestCase):
    def exercise_answer(self, proposal, valid, invalid, wire_answer, skipped=False):
        def response(method, path, payload):
            if method == "GET":
                return 200, proposal
            return 200, {"meta": {"alerts": [{"type": "hard_stop", "reasons": ["emergency"]}]}}

        wire = Wire(response)
        with session(provider=prebound(wire)) as flow:
            view = flow.submit()
            self.assertEqual(view["question"]["schema"], "patient-question.v2")
            for value in invalid:
                self.assertFalse(attempt(lambda: flow.answer(view, value), "invalid_answer"))
                self.assertEqual(flow.service.view(flow.handle), view)
            self.assertEqual(len(wire.calls), 1)
            flow.answer(view, valid)
            row = flow.handle.read()[1]["interview"]["answers"][-1]
            self.assertEqual(row.get("skipped", False), skipped)
            self.assertEqual(row["answer"], None if skipped else valid)
            self.assertEqual(flow.invoke("assess")["state"], "urgent")
            self.assertEqual([(m, p) for m, p, _ in wire.calls],
                             [(m, f"/api/mgp/v1/surveys/{SURVEY}/questions/current") for m in ("GET", "POST")])
            self.assertEqual(wire.calls[-1][2], {"answer": wire_answer})

    def test_only_explicit_optional_skip_sends_null(self):
        q = dict(id="q", index=0, answer_type="choice", question={"text": "Fictional choice"},
                 meta={"required": False, "answers": [{"id": "a", "label": "Choice A"}]})
        self.exercise_answer(q, {"skip": True}, [None, "", [], {}], None, skipped=True)

    def test_group_skip_sends_explicit_unknown_for_each_issued_item(self):
        q = dict(id="q", index=0, answer_type="symptoms", question={"text": "Fictional group"},
                 meta={"component": "group_single", "required": False, "answers": [
                     {"id": key, "name": key, "label": key} for key in ("a", "b")]})
        self.exercise_answer(q, {"skip": True}, [None, []],
                             [{"id": key, "choice_id": "unknown"} for key in ("a", "b")], skipped=True)

    def test_only_eligible_edit_restores_progress(self):
        for context in ({"age": 10}, {"language": "fr"}):
            with self.subTest(context=context), encounter([completion("CURRENT")]) as flow:
                self.assertEqual(flow.edit(**context)["state"], "unsupported")
                for granted in (True, False, True):
                    self.assertEqual(flow.invoke("consent", granted=granted)["state"], "unsupported")
                    self.assertEqual(flow.invoke("assess")["state"], "unsupported")
                self.assertEqual(len(flow.provider.requests), 0)
                self.assertEqual(flow.edit()["state"], "draft")
                self.assertEqual(flow.invoke("assess")["state"], "draft")
                self.assertEqual(len(flow.provider.requests), 0)
                flow.invoke("consent", granted=True)
                self.assertEqual(flow.invoke("assess")["state"], "completed")
                self.assertEqual(len(flow.provider.requests), 1)

    def test_item_unknown_and_absent_are_distinct_from_omission(self):
        choices = [{"id": key, "label": key} for key in ("present", "absent", "unknown")]
        q = dict(id="q", index=0, answer_type="symptoms", question={"text": "Fictional items"},
                 meta={"component": "group_multiple", "answers": [
                     {"id": key, "name": key, "choices": choices} for key in ("a", "b")]})
        rows = [{"id": "a", "presence": "unknown"}, {"id": "b", "presence": "absent"}]
        self.exercise_answer(q, {"items": rows}, [{"items": rows[:1]}, {"skip": True}],
                             [{"id": "a", "choice_id": "unknown"}, {"id": "b", "choice_id": "absent"}])

    def test_recognized_stop_blocks_assessment_and_navigation(self):
        payload = {"meta": {"alerts": [{"type": "hard_stop", "reasons": ["suicidal_intent"]}]}}
        wire = Wire(lambda *_: (200, payload))
        with session(provider=prebound(wire)) as flow:
            stop = flow.submit()
            self.assertEqual((stop["state"], stop["guidance"]), ("provider_stop", "Synthetic stop guidance"))
            self.assertIsNone(stop["urgency"])
            self.assertIsNone(stop["next_step"])
            self.assertFalse(attempt(lambda: flow.invoke("confirm"), "confirmation_unavailable"))
            self.assertFalse(attempt(lambda: flow.invoke("navigate", confirmation=None), "confirmation_unavailable"))
            self.assertFalse(attempt(lambda: flow.invoke("assess"), "assessment_action_unavailable"))
            self.assertEqual(len(wire.calls), 1)

    def test_assessment_retains_uncertainty_and_uninterpreted_status(self):
        reply = dict(completion("CURRENT"), uncertainty="Synthetic unresolved uncertainty.")
        with encounter([reply]) as flow:
            result = flow.submit()
            flow.invoke("confirm")
            for view in (result, flow.service.view(flow.handle)):
                self.assertEqual(view["state"], "completed")
                self.assertEqual(view["uncertainty"], reply["uncertainty"])
                self.assertEqual(view["description_status"], "uninterpreted")

    def race(self, unknown):
        from patient_intake.providers.mgp_v2 import OwnedMgpSurvey, dispose_claim
        from patient_intake.session import CleanupMailbox

        mailbox = CleanupMailbox()
        started, release = Event(), Event()

        def create(method, path, payload):
            if method == "POST" and path.endswith("/users"):
                return 201, {"id": USER}
            if method == "POST" and path.endswith("/patients"):
                started.set()
                if not release.wait(4) or unknown:
                    raise TimeoutError()
                return 201, {"id": PATIENT, "user_id": USER}
            raise AssertionError("unexpected create")

        creation = Wire(create)
        cleanup = Wire(lambda *_: (204, None))

        def factory():
            return OwnedMgpSurvey(enabled=True, mailbox=mailbox, session=creation.transport,
                                  budget=creation.budget, reconciled=lambda _: True)

        with session(factory=factory) as flow:
            flow.edit()
            flow.invoke("consent", granted=True)
            outcomes = []
            old_handle = flow.handle
            revision = old_handle.read()[0]

            def submit():
                try:
                    flow.service.assess(old_handle, revision)
                    outcomes.append("applied")
                except ValueError as exc:
                    outcomes.append(getattr(exc, "code", None) or str(exc))

            worker = Thread(target=submit)
            worker.start()
            try:
                self.assertTrue(started.wait(3))
                flow.owner.reset(old_handle)
                flow.handle = flow.owner.open(consent=True, notice_version="audit-v1")
                self.assertEqual(mailbox.counts(), {"awaiting_create": 1})
                self.assertIsNone(mailbox.claim())
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(outcomes, ["session_encounter_unavailable"])
            self.assertEqual(flow.service.view(flow.handle)["state"], "draft")
            self.assertEqual([p for _, p, _ in creation.calls], ["/api/mgp/v1/users", "/api/mgp/v1/patients"])
            self.assertTrue(dispose_claim(mailbox, cleanup_session=cleanup.transport, cleanup_budget=cleanup.budget))
            expected = [("users", USER)] if unknown else [("patients", PATIENT), ("users", USER)]
            self.assertEqual(cleanup.calls, [("DELETE", f"/api/mgp/v1/{role}/{ident}", None) for role, ident in expected])
            self.assertEqual(mailbox.counts(), {"unresolved": 1} if unknown else {})
            self.assertFalse(dispose_claim(mailbox, cleanup_session=cleanup.transport, cleanup_budget=cleanup.budget))

    def test_verified_late_create_disposed_in_reverse_order(self):
        self.race(unknown=False)

    def test_unknown_late_create_retained_after_known_disposal(self):
        self.race(unknown=True)


if __name__ == "__main__":
    app = Path(sys.argv.pop(1)).resolve()
    effects = SideEffects(app)
    run = unittest.main(exit=False, verbosity=2)
    unexpected = {key: count for key, count in effects.counts.items() if key != "mock_exchange_starts" and count}
    if unexpected:
        print("Unexpected side-effect entries", unexpected)
    sys.exit(int(not run.result.wasSuccessful() or bool(unexpected)))
