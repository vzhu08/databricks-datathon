import unittest

from .privacy import CanaryProbe, SURFACES


class SyntheticPrivacyProbeTests(unittest.TestCase):
    def test_empty_sensor_and_error_echo_remain_visible(self):
        probe = CanaryProbe(markers=[b"SYNTHETIC_HEALTH_01", b"SYNTHETIC_TOKEN_02"],
                            capture_marker=b"BENIGN_CAPTURE_03")
        for surface in SURFACES - {"telemetry"}:
            probe.capture(surface, b"BENIGN_CAPTURE_03")
        probe.capture("rendered_error", b"Failure: SYNTHETIC_HEALTH_01")
        self.assertEqual(probe.missing_surfaces(), ["telemetry"])
        self.assertEqual(probe.measurements(), {"canary_matches": 1, "required_sinks_observed": False})
        probe.capture("telemetry", b"BENIGN_CAPTURE_03")
        self.assertEqual(probe.measurements(), {"canary_matches": 1, "required_sinks_observed": True})
