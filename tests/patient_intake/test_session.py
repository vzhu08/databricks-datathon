from concurrent.futures import ThreadPoolExecutor
import gc
from importlib import import_module
from threading import Barrier, Event
import unittest
from unittest.mock import patch
from weakref import ref

from app.patient_intake.privacy import PatientSessionError
from app.patient_intake.session import CleanupMailbox, EncounterHandle, PatientSession


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


USER_REF = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PATIENT_REF = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SURVEY_REF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class CleanupMailboxTests(unittest.TestCase):
    def test_retirement_during_create_reserves_capacity_and_enqueues_late_ids(self):
        mailbox = CleanupMailbox(capacity=1)
        reservation = mailbox.reserve()
        self.create(reservation, "users", USER_REF)
        self.create(reservation, "patients", PATIENT_REF)
        create = reservation.admit_create("surveys")
        reservation.retire()
        reservation.retire()
        self.assertEqual(mailbox.counts(), {"awaiting_create": 1})
        self.assertIsNone(mailbox.claim())
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_full$"):
            mailbox.reserve()

        reservation.settle_create(create, outcome="created", resource_id=SURVEY_REF)
        self.assertEqual(mailbox.counts(), {"pending": 1})
        claim = mailbox.claim()
        self.assertEqual(claim.resources, (("surveys", SURVEY_REF), ("patients", PATIENT_REF),
                                           ("users", USER_REF)))
        self.assertIsNone(mailbox.claim())
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_invalid$"):
            mailbox.finish(claim, disposed=("patients",))
        mailbox.finish(claim, disposed=("surveys", "patients", "users"))
        reservation.retire()
        self.assertEqual(mailbox.counts(), {})
        self.assertIsNot(mailbox.reserve(), reservation)

    @staticmethod
    def create(reservation, role, identifier):
        attempt = reservation.admit_create(role)
        reservation.settle_create(attempt, outcome="created", resource_id=identifier)
        return attempt

    def test_simultaneous_create_settlement_and_retirement_are_not_lost(self):
        mailbox = CleanupMailbox()
        reservation = mailbox.reserve()
        attempt = reservation.admit_create("users")
        ready = Barrier(2, timeout=5)

        def settle():
            ready.wait()
            reservation.settle_create(attempt, outcome="created", resource_id=USER_REF)

        def notify():
            ready.wait()
            reservation.retire()

        with ThreadPoolExecutor(max_workers=2) as pool:
            settled, notified = pool.submit(settle), pool.submit(notify)
            settled.result(timeout=5)
            notified.result(timeout=5)
        self.assertEqual(mailbox.counts(), {"pending": 1})
        self.assertEqual(mailbox.claim().resources, (("users", USER_REF),))

    def test_partial_cleanup_drops_verified_ids_and_reports_exhaustion(self):
        mailbox = CleanupMailbox(attempts=2)
        reservation = mailbox.reserve()
        self.create(reservation, "users", USER_REF)
        self.create(reservation, "patients", PATIENT_REF)
        self.create(reservation, "surveys", SURVEY_REF)
        self.assertIsNone(mailbox.claim())
        reservation.retire()
        first_attempt = mailbox.claim()
        mailbox.finish(first_attempt, disposed=("surveys", "patients"))
        reservation.retire()
        second_attempt = mailbox.claim()
        self.assertEqual(second_attempt.resources, (("users", USER_REF),))
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_stale$"):
            mailbox.finish(first_attempt, disposed=("users",))
        mailbox.finish(second_attempt)
        self.assertEqual(mailbox.counts(), {"exhausted": 1})
        self.assertIsNone(mailbox.claim())

    def test_unknown_create_remains_unresolved_after_known_ids_are_disposed(self):
        mailbox = CleanupMailbox()
        reservation = mailbox.reserve()
        self.create(reservation, "users", USER_REF)
        attempt = reservation.admit_create("patients")
        reservation.retire()
        reservation.settle_create(attempt, outcome="unknown")
        mailbox.finish(mailbox.claim(), disposed=("users",))
        self.assertEqual(mailbox.counts(), {"unresolved": 1})
        self.assertIsNone(mailbox.claim())

        rejected = mailbox.reserve()
        rejected.settle_create(rejected.admit_create("users"), outcome="not_created")
        rejected.retire()
        self.assertEqual(mailbox.counts(), {"unresolved": 1})

    def test_foreign_create_and_disposal_claims_are_rejected(self):
        mailbox, other = CleanupMailbox(), CleanupMailbox()
        reservation = mailbox.reserve()
        attempt = reservation.admit_create("users")
        foreign = other.reserve()
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_stale$"):
            foreign.settle_create(attempt, outcome="created", resource_id=USER_REF)
        foreign.retire()
        reservation.settle_create(attempt, outcome="created", resource_id=USER_REF)
        reservation.retire()
        claim = mailbox.claim()
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_stale$"):
            other.finish(claim, disposed=("users",))
        mailbox.finish(claim, retryable=False)
        self.assertEqual(mailbox.counts(), {"failed": 1})
        self.assertEqual(other.counts(), {})

    def test_create_roles_are_ordered_single_use_and_stop_on_retire(self):
        mailbox = CleanupMailbox()
        reservation = mailbox.reserve()
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_invalid$"):
            reservation.admit_create("surveys")
        attempt = reservation.admit_create("users")
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_stale$"):
            reservation.admit_create("users")
        reservation.retire()
        reservation.settle_create(attempt, outcome="created", resource_id=USER_REF)
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_stale$"):
            reservation.settle_create(attempt, outcome="created", resource_id=USER_REF)
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_stale$"):
            reservation.admit_create("patients")
        self.assertFalse(reservation.active)


class _Provider:
    def __init__(self, mailbox):
        self.cleanup_reservation = mailbox.reserve()

    def assess(self, data, *, continuation=None):
        raise AssertionError("session should never call provider assessment")

    def retire(self):
        raise AssertionError("session should retire the reservation directly")


class ProviderSessionTests(unittest.TestCase):
    def test_revisions_reuse_binding_and_revoke_retires_before_next_create(self):
        mailbox = CleanupMailbox()
        owner = PatientSession(notice_version=NOTICE)
        handle = open_encounter(owner)
        self.addCleanup(owner.delete, handle)
        adapter = handle.bind_provider(0, lambda: _Provider(mailbox))
        self.assertEqual(mailbox.counts(), {"attached": 1})
        revision = handle.replace(0, {"description": CANARY})
        with self.assertRaisesRegex(PatientSessionError, "^session_revision_stale$"):
            handle.bind_provider(0, self.fail)
        self.assertIs(handle.bind_provider(revision, self.fail), adapter)
        create = adapter.cleanup_reservation.admit_create("users")
        revision = handle.replace(revision, {}, retire_provider=True)
        self.assertEqual(handle.read(), (revision, {}))
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_stale$"):
            adapter.cleanup_reservation.admit_create("patients")
        adapter.cleanup_reservation.settle_create(create, outcome="created", resource_id=USER_REF)
        self.assertEqual(mailbox.claim().resources, (("users", USER_REF),))

    def test_reset_delete_and_expiry_erase_before_create_returns(self):
        for ending in ("reset", "delete", "expiry"):
            with self.subTest(ending=ending), patch.object(SESSION_MODULE, "monotonic", return_value=10) as clock, \
                    patch.object(SESSION_MODULE, "Timer") as timers:
                mailbox = CleanupMailbox()
                owner = PatientSession(notice_version=NOTICE, ttl_seconds=10)
                handle = open_encounter(owner)
                revision = handle.replace(0, {"description": CANARY})
                reservation = handle.bind_provider(revision, lambda: _Provider(mailbox)).cleanup_reservation
                attempt = reservation.admit_create("users")
                if ending == "expiry":
                    clock.return_value = 20
                    timers.call_args.args[1](*timers.call_args.kwargs["args"])
                else:
                    getattr(owner, ending)(handle)
                self.assertIsNone(owner._active)
                self.assertEqual(mailbox.counts(), {"awaiting_create": 1})
                with self.assertRaisesRegex(PatientSessionError, "^session_encounter_unavailable$"):
                    handle.read()
                reservation.settle_create(attempt, outcome="created", resource_id=USER_REF)
                self.assertEqual(mailbox.claim().resources, (("users", USER_REF),))

    def test_reset_can_win_while_factory_is_running_and_candidate_is_released(self):
        mailbox = CleanupMailbox(capacity=1)
        owner = PatientSession(notice_version=NOTICE)
        handle = open_encounter(owner)
        waiting, proceed = Event(), Event()

        def factory():
            candidate = _Provider(mailbox)
            waiting.set()
            if not proceed.wait(timeout=5):
                raise AssertionError("test did not release factory")
            return candidate

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(handle.bind_provider, 0, factory)
            try:
                self.assertTrue(waiting.wait(timeout=5))
                owner.reset(handle)
            finally:
                proceed.set()
            with self.assertRaisesRegex(PatientSessionError, "^session_encounter_unavailable$"):
                future.result(timeout=5)
        self.assertEqual(mailbox.counts(), {})

    def test_same_reservation_cannot_be_bound_to_two_sessions(self):
        mailbox = CleanupMailbox()
        first = PatientSession(notice_version=NOTICE)
        second = PatientSession(notice_version=NOTICE)
        one, two = open_encounter(first), open_encounter(second)
        self.addCleanup(first.delete, one)
        self.addCleanup(second.delete, two)
        adapter = one.bind_provider(0, lambda: _Provider(mailbox))
        with self.assertRaisesRegex(PatientSessionError, "^session_cleanup_stale$"):
            two.bind_provider(0, lambda: adapter)
        self.assertTrue(adapter.cleanup_reservation.active)

    def test_lost_session_retires_reservation_without_retaining_patient_state(self):
        with patch.object(SESSION_MODULE, "Timer") as timers:
            mailbox = CleanupMailbox()
            owner = PatientSession(notice_version=NOTICE)
            handle = open_encounter(owner)
            revision = handle.replace(0, {"description": CANARY})
            adapter = handle.bind_provider(revision, lambda: _Provider(mailbox))
            reservation = adapter.cleanup_reservation
            attempt = reservation.admit_create("users")
            owner_ref = ref(owner)
            del handle, owner, adapter
            gc.collect()
            self.assertIsNone(owner_ref())
            timers.call_args.args[1](*timers.call_args.kwargs["args"])
            self.assertEqual(mailbox.counts(), {"awaiting_create": 1})
            reservation.settle_create(attempt, outcome="created", resource_id=USER_REF)
            self.assertEqual(mailbox.claim().resources, (("users", USER_REF),))
