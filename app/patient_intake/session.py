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


_CREATE_ROLES = tuple(reversed(_CLEANUP_ROLES))


@dataclass(frozen=True, eq=False, repr=False)
class CleanupReservation:
    """Server-issued capability for one provider resource chain."""

    _mailbox: "CleanupMailbox"

    @property
    def active(self):
        return self._mailbox._active(self)

    def admit_create(self, role):
        return self._mailbox._admit_create(self, role)

    def settle_create(self, attempt, *, outcome, resource_id=None):
        self._mailbox._settle_create(self, attempt, outcome, resource_id)

    def retire(self):
        self._mailbox._retire(self)


@dataclass(frozen=True, repr=False)
class _CreateAttempt:
    role: str


@dataclass(frozen=True, repr=False)
class _CleanupClaim:
    """A one-attempt receipt. Resource references are for trusted disposal only."""

    _reservation: CleanupReservation
    resources: tuple[tuple[str, str], ...]


@dataclass(repr=False)
class _CleanupRecord:
    bound: bool = False
    requested: bool = False
    creation_unresolved: bool = False
    create_stopped: bool = False
    next_role: int = 0
    creating: Optional[_CreateAttempt] = None
    resources: tuple[tuple[str, str], ...] = ()
    attempts: int = 0
    claim: Optional[_CleanupClaim] = None
    terminal: Optional[str] = None


class CleanupMailbox:
    """Bounded local lifecycle state for one trusted provider adapter.

    A process composition must own this independently of any one WebSocket.
    There is no transport, scheduler, callback, or process-loss recovery here.
    Each mailbox belongs to one server-configured provider instance.
    """

    def __init__(self, *, capacity=32, attempts=3):
        if (type(capacity) is not int or not 1 <= capacity <= 128
                or type(attempts) is not int or not 1 <= attempts <= 5):
            raise PatientSessionError(ErrorCode.INVALID_CONFIGURATION)
        self._capacity = capacity
        self._attempts = attempts
        self._records = {}
        self._lock = Lock()

    def reserve(self):
        """Reserve a slot before any remote creation can begin."""
        with self._lock:
            if len(self._records) >= self._capacity:
                raise PatientSessionError(ErrorCode.CLEANUP_FULL)
            reservation = CleanupReservation(self)
            self._records[reservation] = _CleanupRecord()
            return reservation

    def _active(self, reservation):
        with self._lock:
            record = self._records.get(reservation)
            return record is not None and not record.requested and not record.create_stopped

    def _bind(self, reservation):
        with self._lock:
            record = self._record(reservation)
            if (record.bound or record.requested or record.creating is not None
                    or record.next_role or record.create_stopped):
                raise PatientSessionError(ErrorCode.CLEANUP_STALE)
            record.bound = True

    def _admit_create(self, reservation, role):
        """Reserve exactly one permitted create before performing transport."""
        with self._lock:
            record = self._record(reservation)
            if record.requested or record.create_stopped or record.creating is not None:
                raise PatientSessionError(ErrorCode.CLEANUP_STALE)
            if (type(role) is not str or record.next_role >= len(_CREATE_ROLES)
                    or role != _CREATE_ROLES[record.next_role]):
                raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
            record.creating = _CreateAttempt(role)
            return record.creating

    def _settle_create(self, reservation, attempt, outcome, resource_id):
        """Keep even late outcomes for the exact admitted create attempt."""
        with self._lock:
            record = self._record(reservation)
            if type(attempt) is not _CreateAttempt or record.creating is not attempt:
                raise PatientSessionError(ErrorCode.CLEANUP_STALE)
            if type(outcome) is not str or outcome not in ("created", "not_created", "unknown"):
                raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
            if outcome == "created":
                if (type(resource_id) is not str or len(resource_id) != 36
                        or not _RESOURCE_ID.fullmatch(resource_id)):
                    raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
                record.resources = ((attempt.role, resource_id),) + record.resources
                record.next_role += 1
            else:
                if resource_id is not None:
                    raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
                record.create_stopped = True
                record.creation_unresolved = outcome == "unknown"
            record.creating = None
            self._settle(reservation, record)

    def _retire(self, reservation):
        """Close admission immediately and leave any current create to settle."""
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
                elif record.creating is not None:
                    state = "awaiting_create" if record.requested else "creating"
                elif not record.requested:
                    state = "attached" if record.bound or record.next_role or record.create_stopped else "reserved"
                else:
                    state = "pending"
                counts[state] = counts.get(state, 0) + 1
            return counts

    def claim(self):
        """Issue at most one current attempt per pending record."""
        with self._lock:
            for reservation, record in self._records.items():
                if (record.requested and record.creating is None and record.resources
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
            if (type(retryable) is not bool or type(disposed) is not tuple
                    or len(disposed) > len(record.resources)
                    or any(type(role) is not str for role in disposed)
                    or disposed != tuple(role for role, _ in record.resources[:len(disposed)])):
                raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
            record.resources = record.resources[len(disposed):]
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
        return type(reservation) is CleanupReservation and reservation._mailbox is self

    def _settle(self, reservation, record):
        if record.requested and record.creating is None and not record.resources:
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

    def replace(self, expected_revision: int, data: dict, *, retire_provider=False) -> int:
        """Replace one current revision, optionally retiring its provider binding."""
        return self._owner._replace(self, expected_revision, data, retire_provider)

    def bind_provider(self, expected_revision: int, factory):
        """Install or reuse a trusted local adapter for the current encounter."""
        return self._owner._bind_provider(self, expected_revision, factory)


@dataclass(frozen=True, repr=False)
class _BoundProvider:
    adapter: object
    reservation: CleanupReservation

    def current_adapter(self):
        if not self.reservation.active:
            raise PatientSessionError(ErrorCode.CLEANUP_STALE)
        return self.adapter


@dataclass(repr=False)
class _ExpiryContext:
    # The timer may outlive the session. This carries no session, adapter or data.
    reservation: Optional[CleanupReservation] = None


@dataclass(repr=False)
class _Encounter:
    handle: EncounterHandle
    expires_at: float
    revision: int = 0
    data: dict = field(default_factory=dict)
    provider: Optional[_BoundProvider] = None
    expiry_context: _ExpiryContext = field(default_factory=_ExpiryContext)


def _expire(owner_ref, identifier, context):
    # A pending timer cannot keep a disconnected session or its data alive.
    owner = owner_ref()
    if owner is not None:
        owner._expire(identifier)
    elif context.reservation is not None:
        context.reservation.retire()


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

    def _at_revision(self, handle, expected_revision):
        encounter = self._current(handle)
        if type(expected_revision) is not int or expected_revision != encounter.revision:
            raise PatientSessionError(ErrorCode.REVISION_STALE)
        return encounter

    def _replace(self, handle, expected_revision, data, retire_provider):
        with self._lock:
            encounter = self._at_revision(handle, expected_revision)
            if type(retire_provider) is not bool:
                raise PatientSessionError(ErrorCode.INVALID_PAYLOAD)
            snapshot = copy_patient_data(data)
            self._current(handle)
            if retire_provider:
                self._retire_provider(encounter)
            encounter.data = snapshot
            encounter.revision += 1
            return encounter.revision

    def _bind_provider(self, handle, expected_revision, factory):
        with self._lock:
            encounter = self._at_revision(handle, expected_revision)
            if encounter.provider is not None:
                return encounter.provider.current_adapter()

        # The trusted factory constructs a local adapter and its reservation.
        # It takes no patient data and runs outside the encounter lock.
        candidate = self._new_provider(factory)
        try:
            with self._lock:
                encounter = self._at_revision(handle, expected_revision)
                if encounter.provider is None:
                    adapter = candidate.current_adapter()
                    encounter.provider = candidate
                    encounter.expiry_context.reservation = candidate.reservation
                    return adapter
                adapter = encounter.provider.current_adapter()
        except BaseException:
            candidate.reservation.retire()
            raise
        candidate.reservation.retire()
        return adapter

    @staticmethod
    def _new_provider(factory):
        if not callable(factory):
            raise PatientSessionError(ErrorCode.CLEANUP_INVALID)
        try:
            adapter = factory()
            reservation = getattr(adapter, "cleanup_reservation", None)
            can_assess = callable(getattr(adapter, "assess", None))
        except PatientSessionError as error:
            if type(error) is PatientSessionError and error.code == ErrorCode.CLEANUP_FULL.value:
                raise PatientSessionError(ErrorCode.CLEANUP_FULL) from None
        except Exception:
            pass
        else:
            if type(reservation) is CleanupReservation:
                reservation._mailbox._bind(reservation)
                if can_assess:
                    return _BoundProvider(adapter, reservation)
                reservation.retire()
        raise PatientSessionError(ErrorCode.CLEANUP_INVALID)

    @staticmethod
    def _retire_provider(encounter):
        if encounter.provider is not None:
            # Retire the store's receipt directly. An adapter may be in a
            # network exchange and must not sit on the erasure path.
            encounter.provider.reservation.retire()
            encounter.provider = None
            encounter.expiry_context.reservation = None

    def _purge_expired(self):
        if self._active is not None and monotonic() >= self._active.expires_at:
            self._clear("expired")

    def _clear(self, status):
        if self._active is not None:
            self._retire_provider(self._active)
        self._active = None
        self._status = status
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _arm_expiry(self, encounter):
        timer = Timer(max(0, encounter.expires_at - monotonic()), _expire,
                      args=(ref(self), encounter.handle._identifier, encounter.expiry_context))
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
