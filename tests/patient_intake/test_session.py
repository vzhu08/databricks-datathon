from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from app.patient_intake.privacy import PatientSessionError
from app.patient_intake.session import EncounterHandle, PatientSession


NOTICE = "memory-notice-v1"
CANARY = "SYNTHETIC-PRIVATE-SESSION-violet-627"
SESSION_MODULE = import_module("app.patient_intake.session")


def open_encounter(owner):
    return owner.open(consent=True, notice_version=NOTICE)


class SessionTests(unittest.TestCase):
    def new_session(self, **kwargs):
        owner = PatientSession(notice_version=NOTICE, **kwargs)
        self.addCleanup(self.close_if_active, owner)
        return owner

    def close_if_active(self, owner):
        if owner.status == "active":
            owner.delete(owner._active.handle)

    def expect_error(self, code, operation):
        with self.assertRaises(PatientSessionError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def test_open_requires_affirmative_current_memory_notice(self):
        owner = self.new_session()
        for consent, notice in ((False, NOTICE), (1, NOTICE), (True, "retired-notice")):
            with self.subTest(consent=consent, notice=notice):
                self.expect_error("session_consent_required",
                                  lambda: owner.open(consent=consent, notice_version=notice))
        self.assertEqual(owner.status, "empty")
        handle = open_encounter(owner)
        self.assertEqual(handle.read(), (0, {}))
        self.expect_error("session_encounter_active", lambda: open_encounter(owner))
        self.assertEqual(handle.read(), (0, {}))

    def test_different_sessions_cannot_read_write_or_delete_each_others_encounter(self):
        first, second = self.new_session(), self.new_session()
        patient = open_encounter(first)
        other = open_encounter(second)
        patient.replace(0, {"description": CANARY})
        self.assertNotEqual(patient._identifier, other._identifier)

        # Copying the string identifier into another server object confers no authority.
        forged = EncounterHandle(second)
        forged._identifier = patient._identifier
        self.expect_error("session_encounter_unavailable", forged.read)
        self.expect_error("session_encounter_unavailable", lambda: forged.replace(0, {}))
        self.expect_error("session_encounter_unavailable", lambda: second.delete(patient))
        self.expect_error("session_encounter_unavailable", lambda: first.reset(other))
        self.assertEqual(other.read(), (0, {}))
        self.assertEqual(patient.read(), (1, {"description": CANARY}))

    def test_reads_and_writes_are_detached_and_validation_failure_is_atomic(self):
        handle = open_encounter(self.new_session())
        data = {"facts": [{"description": CANARY}]}
        self.assertEqual(handle.replace(0, data), 1)
        data["facts"].clear()
        revision, snapshot = handle.read()
        snapshot["facts"][0]["description"] = "edited only in the detached copy"
        self.expect_error("session_invalid_payload", lambda: handle.replace(revision, {"bad": object()}))
        self.expect_error("session_revision_stale", lambda: handle.replace(True, {}))
        self.assertEqual(handle.read(), (1, {"facts": [{"description": CANARY}]}))

    def test_two_simultaneous_completions_have_only_one_winner(self):
        handle = open_encounter(self.new_session())
        in_progress = handle.replace(0, {"state": "in_progress", "description": CANARY})
        ready = Barrier(2, timeout=5)

        def complete(label):
            ready.wait()
            try:
                return label, handle.replace(in_progress, {"state": label})
            except PatientSessionError as error:
                return label, error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = dict(pool.map(complete, ("completed-a", "completed-b")))
        revision, state = handle.read()
        self.assertEqual(revision, 2)
        self.assertEqual(outcomes[state["state"]], 2)
        self.assertEqual(sorted(outcomes.values(), key=str), [2, "session_revision_stale"])

    def test_late_completion_cannot_replace_a_concurrent_edit(self):
        handle = open_encounter(self.new_session())
        in_progress = handle.replace(0, {"state": "in_progress", "description": CANARY})
        waiting, proceed = Event(), Event()

        def complete():
            waiting.set()
            if not proceed.wait(timeout=5):
                raise AssertionError("test did not release completion")
            return handle.replace(in_progress, {"state": "completed"})

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(complete)
            try:
                self.assertTrue(waiting.wait(timeout=5))
                handle.replace(in_progress, {"state": "draft", "description": "new synthetic input"})
            finally:
                proceed.set()
            self.expect_error("session_revision_stale", lambda: future.result(timeout=5))
        self.assertEqual(handle.read(), (2, {"state": "draft", "description": "new synthetic input"}))

    def test_reset_and_delete_clear_data_and_invalidate_pending_handles(self):
        for operation, status in (("reset", "reset"), ("delete", "deleted")):
            with self.subTest(operation=operation):
                owner = self.new_session()
                old = open_encounter(owner)
                old_revision = old.replace(0, {"description": CANARY, "state": "in_progress"})
                getattr(owner, operation)(old)
                self.assertEqual(owner.status, status)
                self.assertIsNone(owner._active)
                self.expect_error("session_consent_required",
                                  lambda: owner.open(consent=False, notice_version=NOTICE))
                current = open_encounter(owner)
                self.assertNotEqual(old._identifier, current._identifier)
                self.expect_error("session_encounter_unavailable", old.read)
                self.expect_error("session_encounter_unavailable",
                                  lambda: old.replace(old_revision, {"state": "completed"}))
                self.expect_error("session_encounter_unavailable", lambda: owner.delete(old))
                self.assertEqual(current.read(), (0, {}))

    def test_absolute_expiry_blocks_access_even_if_timer_is_delayed(self):
        with patch.object(SESSION_MODULE, "monotonic", return_value=10) as clock, \
                patch.object(SESSION_MODULE, "Timer") as timer:
            owner = self.new_session(ttl_seconds=30)
            handle = open_encounter(owner)
            clock.return_value = 39
            version = handle.replace(0, {"description": CANARY})
            self.assertEqual(handle.read()[0], 1)
            clock.return_value = 40
            self.expect_error("session_encounter_unavailable",
                              lambda: handle.replace(version, {"state": "completed"}))
            self.assertEqual(owner.status, "expired")
            self.assertIsNone(owner._active)
            timer.return_value.cancel.assert_called_once()

    def test_timer_purges_without_access_and_stale_callback_cannot_purge_new_encounter(self):
        with patch.object(SESSION_MODULE, "monotonic", return_value=10) as clock, \
                patch.object(SESSION_MODULE, "Timer") as timers:
            owner = self.new_session(ttl_seconds=10)
            old = open_encounter(owner)
            old.replace(0, {"description": CANARY})
            callback = timers.call_args.args[1]
            old_args = timers.call_args.kwargs["args"]
            clock.return_value = 20
            callback(*old_args)
            self.assertIsNone(owner._active)  # No status/read call caused cleanup.
            self.assertEqual(owner.status, "expired")

            current = open_encounter(owner)
            callback(*old_args)
            self.assertEqual(current.read(), (0, {}))
