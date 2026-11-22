import json
import unittest
from unittest.mock import Mock, patch

from app.patient_intake import interview
from app.patient_intake.providers import databricks_config as config, databricks_interview as db
from app.patient_intake.providers.transport import Budget
from tests.patient_intake.providers.test_databricks_interview import MODEL, extraction, result


def differential(label="allergic rhinitis", urgency="consultation"):
    return {"causes": [{"label": label, "row": 0}], "uncertainty": "overlap", "urgency": urgency}


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.exchange = Mock()
        for patcher in (patch.object(config, "_configuration", None), patch.object(config, "_providers", {}),
                        patch.object(config, "_WorkspaceExchange", return_value=self.exchange),
                        patch.object(db, "_PROCESS_BUDGETS", {"test": Budget(2), "demo": Budget(6)})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.opts = dict(enabled=True, endpoint=MODEL, demo_attempts=6, test_attempts=1)
        self.p = config.configured_databricks_provider(**self.opts, mode="assessment")

    def start(self, source="My nose is itchy today.", age=36, language="en"):
        self.data = interview.start(source, dict(age_years=age, language=language))
        self.reply = self.p.assess(self.data)

    def answer(self, value, *, provider=None):
        q = interview.prepare_question(self.reply["question"], self.data)
        q["issuance_id"] = "test-" + str(len(self.data["answers"]))
        self.data = interview.answer(self.data, q, q["issuance_id"], value)
        self.reply = (provider or self.p).assess(self.data, continuation=self.reply["continuation"])

    def test_fresh_review_and_context_determine_two_distinct_differentials(self):
        for quote, cause, urgency in (("My nose is itchy today.", "allergic rhinitis", "consultation"),
                                      ("My head hurts today.", "migraine", "consultation_24")):
            self.start(quote)
            assessment = differential(cause, urgency)
            if urgency == "consultation":
                assessment["causes"].append({"label": "viral respiratory infection", "row": 0})
            self.exchange.side_effect = [result(extraction(quote)), result(assessment)]
            self.answer("no")
            self.assertEqual(self.reply["question"]["evidence"]["label"], quote)
            self.answer("confirm")
            self.answer("worsened")
            self.assertEqual((self.reply["state"], self.reply["urgency"], self.reply["possible_causes"]),
                             ("experimental_assessment", urgency, [item["label"] for item in assessment["causes"]]))
            step = {"kind": "consultation", "specialty_code": None} if urgency == "consultation" else None
            self.assertEqual(self.reply["next_step"], step)
            wire = json.loads(self.exchange.call_args.args[4])
            self.assertEqual(set(wire), {"messages", "max_tokens"})
            self.assertEqual(wire["max_tokens"], 1024)
            payload = json.loads(wire["messages"][1]["content"])
            self.assertEqual(payload["reviewed"], [dict(quote=quote, presence="present", temporality="current")])
            self.assertEqual(payload["context"], {"age_years": 36, "language": "en"})
            self.assertEqual(payload["clarification"], {"topic": "change", "answer": "worsened"})
        self.assertEqual(self.exchange.call_count, 4)

    def test_warning_and_uncertain_warning_preempt_even_unsupported_context(self):
        for choice in ("yes", "unsure"):
            self.start(age=4)
            self.assertIn("112", self.reply["question"]["prompt"])
            self.answer(choice)
            self.assertEqual(self.reply["state"], "experimental_assessment")
            self.assertEqual(self.reply["urgency"], "emergency_ambulance")
            self.assertEqual(self.reply["possible_causes"], [])
            self.assertIsNone(self.reply["next_step"])
        self.exchange.assert_not_called()

    def test_age_language_and_hmac_before_extraction(self):
        for age, language in ((None, "en"), (9, "en"), (121, "en"), (30, "hi")):
            self.start(age=age, language=language)
            self.answer("no")
            self.assertEqual(self.reply["state"], "unsupported")
        self.start()
        self.data["context"]["age_years"] = 77
        self.answer("no")
        self.assertEqual(self.reply["reason"], "unsupported_correction")
        self.start()
        self.answer("no", provider=config.configured_databricks_provider(**self.opts))
        self.assertEqual(self.reply["reason"], "invalid_response")
        self.exchange.assert_not_called()

    def test_confirmed_current_warning_overrides_negative_screen_before_final_call(self):
        for quote in ("I have chest pressure now.", "There is heavy pressure right in the middle of my chest.",
                      "My chest has felt very tight since this morning."):
            self.start(quote)
            self.exchange.side_effect = [result(extraction(quote)), result(differential())]
            self.answer("no")
            self.answer("confirm")
            self.assertEqual(self.reply["urgency"], "emergency_ambulance")
            self.assertNotIn("continuation", self.reply)
        self.assertEqual(self.exchange.call_count, 3)

    def test_nonspecific_confirmed_rows_cannot_support_causes(self):
        for quote in ("Something is wrong.", "I feel different today."):
            self.start(quote)
            self.exchange.side_effect = [result(extraction(quote)), result(differential())]
            for answer in ("no", "confirm", "unchanged"):
                self.answer(answer)
            self.assertEqual(self.reply["state"], "provider_stop")
            self.assertNotIn("possible_causes", self.reply)
        self.assertEqual(self.exchange.call_count, 2)

    def test_grounding_dispute_unknown_and_history_only_suppress_differential(self):
        for decision, presence, time in (("disagree", "present", "current"), ("uncertain", "present", "current"),
                                         ("confirm", "unknown", "current"), ("confirm", "present", "unknown"),
                                         ("confirm", "absent", "current"), ("confirm", "present", "historical")):
            quote = "Invented observation."
            self.start(quote)
            self.exchange.return_value = result(extraction(quote, presence, time))
            self.answer("no")
            self.answer(decision)
            if self.reply["state"] == "awaiting_clarification":
                self.answer("unchanged")
            self.assertEqual(self.reply["state"], "provider_stop")
        self.assertEqual(self.exchange.call_count, 6)

    def test_missing_line_and_opposing_reviewed_polarities_abstain(self):
        yes, no = "My ankle is swollen today.", "My ankle is not swollen today."
        self.start(yes + "\n" + no)
        self.exchange.return_value = result(extraction(yes))
        self.answer("no")
        self.assertEqual(self.reply["state"], "provider_stop")
        both = extraction(yes)
        both["observations"] += extraction(no, "absent")["observations"]
        self.exchange.return_value = result(both)
        self.start(yes + "\n" + no)
        for answer in ("no", "confirm", "confirm", "unchanged"):
            self.answer(answer)
        self.assertEqual(self.reply["state"], "provider_stop")
        self.assertEqual(self.exchange.call_count, 2)

    def test_complete_response_strict_schema_and_evidence_index(self):
        payload = {"reviewed": [{"quote": "My head hurts.", "presence": "present", "temporality": "current"},
                                {"quote": "B", "presence": "present", "temporality": "historical"}]}
        self.start()
        base = differential()
        invalid = [dict(base, guidance="Take an invented dose."), dict(base, confidence=0.9),
                   dict(base, uncertainty="definitely"), dict(base, urgency="self_care"),
                   differential("Take medication"), differential("100% certain"),
                   dict(base, next_step={"facility_id": "example"}),
                   dict(base, causes=base["causes"] * 2), dict(base, causes=[]),
                   dict(base, urgency="emergency_ambulance"), {"abstain": 1}]
        for index in (1, -1, True, 7):
            invalid.append(dict(base, causes=[{"label": "migraine", "row": index}]))
        for obj in invalid:
            with self.subTest(obj=obj), patch.object(self.p, "_model", return_value=(obj, None)):
                with self.assertRaises((ValueError, TypeError)):
                    self.p._finish(self.data, payload)

    def test_abstain_emergency_and_truncated_finalization(self):
        quote = "My head hurts today."
        for obj, finish, state in (({"abstain": True}, "stop", "provider_stop"),
                                   (dict(differential(urgency="emergency_ambulance"), causes=[]),
                                    "stop", "experimental_assessment"),
                                   (differential(), "length", "provider_unavailable")):
            self.start(quote)
            self.exchange.side_effect = [result(extraction(quote)), result(obj, finish=finish)]
            for answer in ("no", "confirm", "improved"):
                self.answer(answer)
            self.assertEqual(self.reply["state"], state)
            self.assertFalse(self.reply.get("possible_causes"))
        self.assertEqual(self.exchange.call_count, 6)

    def test_configured_mode_switch_never_refills_a_lane(self):
        self.assertIsNone(config.configured_databricks_provider(mode="assessment"))
        with self.assertRaises(ValueError):
            config.configured_databricks_provider(**self.opts, mode="unexpected")
        opts = dict(self.opts, lane="test")
        doc = config.configured_databricks_provider(**opts)
        self.p = config.configured_databricks_provider(**opts, mode="assessment")
        self.assertNotEqual(doc.identity, self.p.identity)
        self.exchange.return_value = result({"observations": [], "topic": "impact"})
        self.start()
        self.assertEqual(doc.assess(self.data)["state"], "provider_stop")
        self.answer("no")
        self.assertEqual(self.reply["reason"], "budget_exhausted")
        self.assertEqual(doc.assess(interview.start("Other invented input.", {}))["reason"], "budget_exhausted")
        demo_doc = config.configured_databricks_provider(**self.opts)
        self.assertEqual(demo_doc.assess(interview.start("Other invented input.", {}))["state"], "provider_stop")
        self.assertEqual(self.exchange.call_count, 2)
