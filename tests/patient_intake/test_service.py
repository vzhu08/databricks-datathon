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
