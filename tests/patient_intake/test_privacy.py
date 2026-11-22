import logging
import traceback
import unittest
from unittest.mock import patch

from app.patient_intake.privacy import PatientSessionError, copy_patient_data
from app.patient_intake.session import CleanupMailbox, PatientSession


CANARY = "SYNTHETIC-PRIVATE-EXCEPTION-lilac-816"
NOTICE = "memory-notice-v1"


class PrivacyTests(unittest.TestCase):
    def test_bounds_reject_unserializable_or_oversized_snapshots_with_fixed_code(self):
        cyclic = []
        cyclic.append(cyclic)
        invalid_documents = (
            {CANARY: object()},
            {("not", "a", "string"): CANARY},
            {"values": [None] * 2048},
            {"description": CANARY * 2048},
            {"evidence": cyclic},
            {"confidence": float("nan")},
            {"count": 2**63},
        )
        for index, data in enumerate(invalid_documents):
            with self.subTest(index=index):
                with self.assertRaises(PatientSessionError) as error:
                    copy_patient_data(data)
                self.assertEqual(str(error.exception), "session_invalid_payload")
                self.assertNotIn(CANARY, repr(error.exception))

    def test_no_patient_values_or_handles_in_standard_exception_representation_or_logs(self):
        owner = PatientSession(notice_version=NOTICE)
        handle = owner.open(consent=True, notice_version=NOTICE)
        self.addCleanup(owner.delete, handle)
        with patch.object(logging.Logger, "handle") as logs:
            handle.replace(0, {"description": CANARY})
            try:
                handle.replace(1, {"description": CANARY, "unsafe": object()})
            except PatientSessionError as error:
                rendered = traceback.format_exc()
                self.assertIn("session_invalid_payload", rendered)
                self.assertNotIn(CANARY, rendered)
                self.assertNotIn(CANARY, repr(error))
            else:
                self.fail("invalid snapshot was accepted")
            logs.assert_not_called()
        for representation in (repr(handle), repr(owner), repr(owner._active)):
            self.assertNotIn(CANARY, representation)
            self.assertNotIn(handle._identifier, representation)

    def test_error_constructor_never_exposes_arbitrary_public_message(self):
        self.assertEqual(str(PatientSessionError(CANARY)), "session_unavailable")

    def test_timer_failure_withholds_encounter_and_discards_underlying_error(self):
        owner = PatientSession(notice_version=NOTICE)
        with patch("app.patient_intake.session.Timer") as timer:
            timer.return_value.start.side_effect = RuntimeError(CANARY)
            with self.assertRaises(PatientSessionError) as caught:
                owner.open(consent=True, notice_version=NOTICE)
        self.assertEqual(str(caught.exception), "session_unavailable")
        self.assertIsNone(caught.exception.__context__)
        self.assertIsNone(owner._active)
        timer.return_value.cancel.assert_called_once()

    def test_cleanup_accepts_only_resource_references_and_exposes_coarse_status(self):
        mailbox = CleanupMailbox()
        reservation = mailbox.reserve()
        identifier = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        attempt = reservation.admit_create("users")
        for outcome, resource_id in (("created", CANARY), ("unknown", CANARY), (CANARY, identifier)):
            with self.assertRaises(PatientSessionError) as caught:
                reservation.settle_create(attempt, outcome=outcome, resource_id=resource_id)
            self.assertEqual(str(caught.exception), "session_cleanup_invalid")
            self.assertNotIn(CANARY, repr(caught.exception))
        self.assertEqual(mailbox.counts(), {"creating": 1})
        reservation.settle_create(attempt, outcome="created", resource_id=identifier)
        reservation.retire()
        claim = mailbox.claim()
        self.assertNotIn(identifier, repr(claim))
        self.assertEqual(mailbox.counts(), {"in_flight": 1})
