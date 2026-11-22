import unittest
from unittest.mock import Mock

from app.patient_intake.providers.mgp_v2 import MgpSurveyV2, OwnedMgpSurvey, dispose_claim
from app.patient_intake.providers.transport import Budget, Reply


SURVEY = "00000000-0000-0000-0000-000000000001"


def question(wire, **meta):
    return dict(id="invented", index=0, question={"text": "Invented question"}, answer_type=wire, meta=meta)


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock()

    def issue(self, value, **ports):
        self.transport.request.side_effect = [Reply("received", value), Reply("unavailable")]
        self.adapter = MgpSurveyV2(enabled=True, transport=self.transport, budget=Budget(5),
                                   survey_for=lambda _: SURVEY, choices_for=lambda row, _: row, **ports)
        self.proposal = self.adapter.assess({})
        return self.proposal.get("question")

    def answer(self, value, **fields):
        q = self.proposal["question"]
        self.adapter.assess(dict(answer=value, kind=q["kind"], provider_question_id=q["id"],
                                 issuance_id="one", **fields), continuation=self.proposal["continuation"])
        call = self.transport.request.call_args
        return call.kwargs["payload"] if call.args[0] == "POST" else "withheld"

    def test_group_multiple_preserves_explicit_item_choices(self):
        rows = [dict(id="item1", name="First", choices=[dict(id="absent", label="No")]),
                dict(id="item2", name="Second", choices=[dict(id="unknown", label="Unsure")])]
        q = question("symptoms", component="group_multiple", answers=rows)
        proposed = self.issue(q)
        self.assertEqual(proposed["items"][1]["choices"], rows[1]["choices"])
        self.assertEqual(self.answer({"items": [dict(id="item1", presence="absent"),
                                               dict(id="item2", presence="unknown")]}),
                         {"answer": [dict(id="item1", choice_id="absent"), dict(id="item2", choice_id="unknown")]})
        self.issue(q)
        self.assertEqual(self.answer({"items": []}), "withheld")

    def test_optional_and_group_skip(self):
        for component, expected in [(None, None), ("group_single", [dict(id="a", choice_id="unknown")])]:
            meta = dict(required=False, answers=[dict(id="a", label="A", name="A")])
            if component:
                meta["component"] = component
            self.issue(question("symptoms" if component else "choice", **meta))
            self.assertEqual(self.answer(None, skipped=True), {"answer": expected})

    def test_quantities_have_instance_precision_and_unit_limits(self):
        for wire, unit, n in [("age", "year", 23), ("duration", "hour", 1.5)]:
            q = question(wire, min_value=0, max_value=90, evidence_id="s_1")
            units = [dict(id=unit, label=unit, min=0, max=90, integer_only=wire == "age")]
            self.assertIsNone(self.issue(q))
            self.issue(q, units_for=lambda *_: units)
            val = dict(value=n, unit=unit)
            self.assertEqual(self.answer(dict(value=n, unit_id=unit)),
                             {"answer": val if wire == "age" else [dict(id="s_1", duration=val)]})
        self.issue(question("age", min_value=0, max_value=90),
                   units_for=lambda *_: [dict(id="year", label="Year", min=0, max=90, integer_only=True)])
        self.assertEqual(self.answer(dict(value=23.0, unit_id="year")), "withheld")

    def test_catalog_requires_complete_bound_source_and_local_handles(self):
        source = {"complete": True, "id": "catalog", "edition": "v1", "items": [dict(id="s_1", name="Invented")]}
        q = question("list", source_list_url="/v1/knowledge/symptoms?language=en")
        proposed = self.issue(q, catalog_for=lambda *_: source)
        handle = proposed["options"][0]["id"]
        self.assertNotEqual(handle, "s_1")
        self.assertEqual(self.answer([handle], catalog=proposed["catalog"]), {"answer": [dict(id="s_1")]})
        self.assertIsNone(self.issue(q, catalog_for=lambda *_: dict(source, complete=False)))
        self.assertIsNone(self.issue(q, catalog_for=lambda *_: dict(source, items=source["items"]*17)))

    def test_named_stop_and_emergency_precedence(self):
        for reasons, state in [(["suicidal_intent"], "provider_stop"), (["emergency"], "urgent"),
                               (["unrecognized"], "provider_unavailable")]:
            self.issue(question("future", alerts=[dict(type="hard_stop", reasons=reasons)]),
                       stop_guidance="Approved fixture text")
            self.assertEqual(self.proposal["state"], state)
            self.assertNotIn("continuation", self.proposal)

    def test_retirement_during_create_settles_late_id(self):
        mailbox = Mock()
        reservation = mailbox.reserve.return_value
        reservation.active = True
        def create(method, path, **kwargs):
            reservation.active = False
            reservation.admit_create.side_effect = ValueError
            return Reply("received", {"id": SURVEY}, http_status=201)
        self.transport.request.side_effect = create
        owned = OwnedMgpSurvey(enabled=True, mailbox=mailbox, session=self.transport,
                               budget=Budget(8), reconciled=lambda _: True)
        result = owned.assess({"interview_id": "example", "answers": []})
        self.assertEqual(result["state"], "provider_unavailable")
        reservation.settle_create.assert_called_once_with(reservation.admit_create.return_value,
                                                         outcome="created", resource_id=SURVEY)
        self.assertEqual(self.transport.request.call_count, 1)

    def test_disposal_settles_only_confirmed_prefix(self):
        mailbox = Mock()
        claim = mailbox.claim.return_value
        claim.resources = [("surveys", SURVEY), ("patients", SURVEY)]
        self.transport.request.side_effect = [Reply("empty"), Reply("timeout")]
        self.assertTrue(dispose_claim(mailbox, cleanup_session=self.transport, cleanup_budget=Budget(3)))
        mailbox.finish.assert_called_once_with(claim, disposed=("surveys",), retryable=True)
