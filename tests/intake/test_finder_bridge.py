import unittest
from unittest.mock import patch

from app.intake import finder_bridge as bridge
from app.intake.__main__ import load_journeys
from app.storm_ui import build_ask


class FinderFixtures(unittest.TestCase):
    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("live call"))
        self.addCleanup(network.stop)
        self.addCleanup(network.start().assert_not_called)

    def test_matches_every_existing_service_urgency_and_origin(self):
        self.assertEqual(bridge.ORIGIN_IDS, ("central", "east", "south", "west"))
        for key, answer in build_ask.bundle()["answers"].items():
            service, origin, urgency = key.split("|")
            request = dict(service=service, urgency=urgency, required_capabilities=[],
                           preferred_capabilities=[])
            with self.subTest(key=key):
                self.assertEqual(bridge._rank_request(request, origin), answer["response"])

    def test_unreviewed_required_capability_withholds_options(self):
        request = dict(service="mri", urgency="routine", required_capabilities=["sedation"],
                       preferred_capabilities=[])
        result = bridge._rank_request(request, "central")
        self.assertEqual(result["ranked"], [])
        self.assertEqual(result["status"], "needs_confirmation")
        for lead in result["needs_confirmation"]:
            self.assertIn("required_capability_unconfirmed", lead["reasons"])


class ConfirmedIntake(unittest.TestCase):
    def setUp(self):
        from app.intake.assessment import confirm_intake
        self.confirm = confirm_intake
        fixture, _ = load_journeys()
        self.scenarios = fixture["scenarios"]
        self.scenario = self.scenarios["scheduled_mri"]
        self.payload = dict(schema_version="intake.v1", mode="synthetic", scenario_id="scheduled_mri",
                            input_revision=1, answers={"context.severity": "mild"})
        network = patch("socket.socket.connect", side_effect=AssertionError("live call"))
        self.addCleanup(network.stop)
        self.addCleanup(network.start().assert_not_called)

    def search(self, confirmation=None):
        return bridge.find_care_for_intake(self.payload, scenario=self.scenario,
                                           confirmation=confirmation, origin_id="central")

    def test_only_current_receipt_reaches_the_finder(self):
        receipt = self.confirm(self.payload, scenario=self.scenario)
        allowed = self.search(receipt)
        self.assertEqual(allowed["finder"]["status"], "ok")
        with patch.object(bridge, "_rank_request") as lookup:
            for forged in (None, True, {"state": "ready", "confirmation_status": "current"}):
                self.assertIsNone(self.search(forged)["finder"])
            self.payload["answers"]["context.severity"] = "moderate"
            self.assertIsNone(self.search(receipt)["finder"])
            self.payload = allowed["assessment"]
            self.assertIsNone(self.search(receipt)["finder"])
            lookup.assert_not_called()

    def test_warning_supersedes_previous_success(self):
        receipt = self.confirm(self.payload, scenario=self.scenario)
        self.assertTrue(self.search(receipt)["finder"]["ranked"])
        self.payload["answers"]["warning.chest_pain"] = "yes"
        with patch.object(bridge, "_rank_request") as lookup:
            result = self.search(receipt)
            self.assertEqual(result["assessment"]["state"], "emergency_escalation")
            self.assertIsNone(result["finder"])
            lookup.assert_not_called()

    def test_non_ready_states_stop_before_any_fixture_lookup(self):
        unassessed = self.scenarios["injury_unassessed"]
        unsupported = self.scenarios["unsupported_concern"]
        for state, payload, scenario in [
            ("invalid_input", dict(self.payload, mode="warehouse"), self.scenario),
            ("more_information_needed", dict(self.payload, input_revision=0, answers={}), self.scenario),
            ("clinician_assessment_needed", dict(self.payload, scenario_id=unassessed["scenario_id"],
                                                answers={"warning.heavy_bleeding": "no"}), unassessed),
            ("unsupported_care_need", dict(self.payload, scenario_id=unsupported["scenario_id"],
                                           input_revision=0, answers={}), unsupported),
            ("confirmation_required", self.payload, self.scenario),
        ]:
            with self.subTest(state=state), patch.object(bridge, "_rank_request") as lookup:
                response = bridge.find_care_for_intake(payload, scenario=scenario, origin_id="east")
                self.assertEqual(response["assessment"]["state"], state)
                self.assertIsNone(response["finder"])
                lookup.assert_not_called()

    def test_unknown_origin_and_fixture_failure_after_success(self):
        receipt = self.confirm(self.payload, scenario=self.scenario)
        self.assertTrue(self.search(receipt)["finder"]["ranked"])
        with patch.object(build_ask, "FIXTURE") as fixture:
            with self.assertRaises(ValueError):
                bridge.find_care_for_intake(self.payload, scenario=self.scenario,
                                            confirmation=receipt, origin_id="unknown")
            fixture.read_text.assert_not_called()
            fixture.read_text.side_effect = OSError("missing fictional travel fixture")
            with self.assertRaisesRegex(OSError, "missing fictional travel fixture"):
                self.search(receipt)
