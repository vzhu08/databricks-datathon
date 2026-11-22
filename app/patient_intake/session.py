"""Process-local patient encounter ownership and compare-and-swap storage."""

from dataclasses import dataclass, field
import re
import secrets
from threading import Lock, Timer
from time import monotonic
from weakref import ref

from .privacy import ErrorCode, PatientSessionError, copy_patient_data


DEFAULT_TTL_SECONDS = 900
_NOTICE_VERSION = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


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
