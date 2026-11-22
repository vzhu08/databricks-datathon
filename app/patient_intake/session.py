"""Process-local patient encounter ownership and compare-and-swap storage."""

from dataclasses import dataclass, field
import re
import secrets
from threading import Lock, Timer
from time import monotonic
from typing import Optional
from weakref import ref

from .privacy import ErrorCode, PatientSessionError, copy_patient_data


DEFAULT_TTL_SECONDS = 900
_NOTICE_VERSION = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_CLEANUP_ROLES = ("surveys", "patients", "users")
_RESOURCE_ID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


@dataclass(frozen=True, eq=False, repr=False)
class _CleanupReservation:
    _binding: object


@dataclass(frozen=True, repr=False)
class _CleanupClaim:
    """A one-attempt receipt. Resource references are for trusted disposal only."""

    _reservation: _CleanupReservation
    resources: tuple[tuple[str, str], ...]


@dataclass(repr=False)
class _CleanupRecord:
    registered: bool = False
    requested: bool = False
    creation_unresolved: bool = False
    resources: tuple[tuple[str, str], ...] = ()
    attempts: int = 0
    claim: Optional[_CleanupClaim] = None
    terminal: Optional[str] = None


class _CleanupMailbox:
    """Bounded local lifecycle state for one trusted provider adapter.

    A process composition must own this independently of any one WebSocket.
    There is no transport, scheduler, callback, or process-loss recovery here.
    The final provider and encounter binding is a separate integration seam.
    """

    def __init__(self, *, capacity=32, attempts=3):
        if (type(capacity) is not int or not 1 <= capacity <= 128
                or type(attempts) is not int or not 1 <= attempts <= 5):
            raise PatientSessionError(ErrorCode.INVALID_CONFIGURATION)
        self._capacity = capacity
        self._attempts = attempts
        self._binding = object()
        self._records = {}
        self._lock = Lock()

    def reserve(self):
        """Reserve a slot before any remote creation can begin."""
        with self._lock:
            if len(self._records) >= self._capacity:
                raise PatientSessionError(ErrorCode.CLEANUP_FULL)
            reservation = _CleanupReservation(self._binding)
            self._records[reservation] = _CleanupRecord()
            return reservation

    def register(self, reservation, resources, *, creation_unresolved=False):
        """Publish verified partial or complete IDs once a create attempt ends."""
        with self._lock:
            record = self._record(reservation)
            if record.registered:
                raise PatientSessionError(ErrorCode.CLEANUP_STALE)
            if type(creation_unresolved) is not bool or type(resources) is not dict or len(resources) > 3:
                raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
            resources = resources.copy()
            for role, identifier in resources.items():
                if (type(role) is not str or role not in _CLEANUP_ROLES
                        or type(identifier) is not str or len(identifier) != 36
                        or not _RESOURCE_ID.fullmatch(identifier)):
                    raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
            record.resources = tuple((role, resources[role]) for role in _CLEANUP_ROLES if role in resources)
            record.creation_unresolved = creation_unresolved
            record.registered = True
            self._settle(reservation, record)

    def request_cleanup(self, reservation):
        """Record a local notification, including one received before registration."""
        with self._lock:
            if not self._owns(reservation):
                raise PatientSessionError(ErrorCode.CLEANUP_STALE)
            record = self._records.get(reservation)
            if record is None:
                return  # A duplicate notification cannot recreate a retired record.
            record.requested = True
            self._settle(reservation, record)

    def counts(self):
        """Expose only operational states and counts, without resource references."""
        with self._lock:
            counts = {}
            for record in self._records.values():
                if record.terminal is not None:
                    state = record.terminal
                elif record.claim is not None:
                    state = "in_flight"
                elif not record.requested:
                    state = "attached" if record.registered else "reserved"
                else:
                    state = "pending" if record.registered else "awaiting_registration"
                counts[state] = counts.get(state, 0) + 1
            return counts

    def claim(self):
        """Issue at most one current attempt per pending record."""
        with self._lock:
            for reservation, record in self._records.items():
                if (record.requested and record.registered and record.resources
                        and record.claim is None and record.terminal is None):
                    record.attempts += 1
                    record.claim = _CleanupClaim(reservation, record.resources)
                    return record.claim
            return None

    def finish(self, claim, *, disposed=(), retryable=True):
        """Record verified deletion of specific roles from one current attempt."""
        with self._lock:
            if type(claim) is not _CleanupClaim:
                raise PatientSessionError(ErrorCode.CLEANUP_STALE)
            record = self._record(claim._reservation)
            if record.claim is not claim:
                raise PatientSessionError(ErrorCode.CLEANUP_STALE)
            roles = {role for role, _ in record.resources}
            if (type(retryable) is not bool or type(disposed) is not tuple
                    or len(disposed) > len(roles)
                    or any(type(role) is not str or role not in roles for role in disposed)
                    or len(set(disposed)) != len(disposed)):
                raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
            record.resources = tuple(pair for pair in record.resources if pair[0] not in disposed)
            record.claim = None
            if record.resources:
                if not retryable:
                    record.terminal = "failed"
                elif record.attempts >= self._attempts:
                    record.terminal = "exhausted"
            self._settle(claim._reservation, record)

    def _record(self, reservation):
        record = self._records.get(reservation) if self._owns(reservation) else None
        if record is None:
            raise PatientSessionError(ErrorCode.CLEANUP_STALE)
        return record

    def _owns(self, reservation):
        return (type(reservation) is _CleanupReservation
                and reservation._binding is self._binding)

    def _settle(self, reservation, record):
        if record.requested and record.registered and not record.resources:
            if record.creation_unresolved:
                record.terminal = "unresolved"
            else:
                del self._records[reservation]


class EncounterHandle:
    """In-process authority issued by a PatientSession to trusted server code."""

    __slots__ = ("_owner", "_identifier")

    def __init__(self, owner):
        self._owner = owner
        self._identifier = secrets.token_urlsafe(32)

    def __repr__(self):
        return "<EncounterHandle>"

    def read(self) -> tuple[int, dict]:
        """Return the current revision and a detached server snapshot."""
        return self._owner._read(self)

    def replace(self, expected_revision: int, data: dict) -> int:
        """Replace one current revision atomically and return its successor."""
        return self._owner._replace(self, expected_revision, data)


@dataclass(repr=False)
class _Encounter:
    handle: EncounterHandle
    expires_at: float
    revision: int = 0
    data: dict = field(default_factory=dict)


def _expire(owner_ref, identifier):
    # A pending timer cannot keep a disconnected session or its data alive.
    owner = owner_ref()
    if owner is not None:
        owner._expire(identifier)


class PatientSession:
    """One instance per server-owned session. Keep the instance and handle server-side."""

    def __init__(self, *, notice_version: str, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        if (type(notice_version) is not str or len(notice_version) > 64
                or not _NOTICE_VERSION.fullmatch(notice_version)
                or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= DEFAULT_TTL_SECONDS):
            raise PatientSessionError(ErrorCode.INVALID_CONFIGURATION)
        self._notice_version = notice_version
        self._ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._active = None
        self._timer = None
        self._status = "empty"

    @property
    def status(self) -> str:
        """Return the lifecycle label with no encounter ID or patient values."""
        with self._lock:
            self._purge_expired()
            return self._status

    def open(self, *, consent: bool, notice_version: str) -> EncounterHandle:
        """Create an empty revision-zero encounter after affirmative local-memory consent."""
        if (consent is not True or type(notice_version) is not str
                or notice_version != self._notice_version):
            raise PatientSessionError(ErrorCode.CONSENT_REQUIRED)
        with self._lock:
            self._purge_expired()
            if self._active is not None:
                raise PatientSessionError(ErrorCode.ENCOUNTER_ACTIVE)
            handle = EncounterHandle(self)
            self._active = _Encounter(handle, monotonic() + self._ttl_seconds)
            self._status = "active"
            self._arm_expiry(self._active)
            return handle

    def reset(self, handle: EncounterHandle) -> None:
        """Clear the current encounter. The next open requires fresh consent."""
        self._close(handle, "reset")

    def delete(self, handle: EncounterHandle) -> None:
        """Erase the current encounter and retain only a coarse lifecycle label."""
        self._close(handle, "deleted")

    def _close(self, handle, status):
        with self._lock:
            self._current(handle)
            self._clear(status)

    def _current(self, handle):
        self._purge_expired()
        if self._active is None or self._active.handle is not handle:
            raise PatientSessionError(ErrorCode.ENCOUNTER_UNAVAILABLE)
        return self._active

    def _read(self, handle):
        with self._lock:
            encounter = self._current(handle)
            data = copy_patient_data(encounter.data)
            self._current(handle)  # A copy that crossed the deadline is withheld.
            return encounter.revision, data

    def _replace(self, handle, expected_revision, data):
        with self._lock:
            encounter = self._current(handle)
            if type(expected_revision) is not int or expected_revision != encounter.revision:
                raise PatientSessionError(ErrorCode.REVISION_STALE)
            snapshot = copy_patient_data(data)
            self._current(handle)
            encounter.data = snapshot
            encounter.revision += 1
            return encounter.revision

    def _purge_expired(self):
        if self._active is not None and monotonic() >= self._active.expires_at:
            self._clear("expired")

    def _clear(self, status):
        self._active = None
        self._status = status
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _arm_expiry(self, encounter):
        timer = Timer(max(0, encounter.expires_at - monotonic()), _expire,
                      args=(ref(self), encounter.handle._identifier))
        timer.daemon = True
        self._timer = timer
        try:
            timer.start()
        except RuntimeError:
            self._clear("expired")
        else:
            return
        raise PatientSessionError(ErrorCode.UNAVAILABLE)

    def _expire(self, identifier):
        with self._lock:
            if self._active is None or self._active.handle._identifier != identifier:
                return
            self._purge_expired()
            if self._active is not None:
                self._arm_expiry(self._active)
