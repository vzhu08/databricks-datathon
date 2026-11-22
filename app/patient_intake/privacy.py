"""Bounded patient state and content-free failures for the session boundary."""

from enum import Enum
from math import isfinite


_MAX_DEPTH = 12
_MAX_NODES = 2048
_MAX_TEXT_CHARS = 32768  # Total across keys and values of one encounter snapshot.
_MAX_INTEGER = 2**63 - 1


class ErrorCode(str, Enum):
    CONSENT_REQUIRED = "session_consent_required"
    ENCOUNTER_ACTIVE = "session_encounter_active"
    ENCOUNTER_UNAVAILABLE = "session_encounter_unavailable"
    REVISION_STALE = "session_revision_stale"
    INVALID_PAYLOAD = "session_invalid_payload"
    INVALID_CONFIGURATION = "session_invalid_configuration"
    UNAVAILABLE = "session_unavailable"
    CLEANUP_FULL = "session_cleanup_full"
    CLEANUP_STALE = "session_cleanup_stale"
    CLEANUP_INVALID = "session_cleanup_invalid"


class PatientSessionError(ValueError):
    """A fixed code safe to display or record without values or identifiers."""

    def __init__(self, code: ErrorCode):
        self.code = code.value if type(code) is ErrorCode else ErrorCode.UNAVAILABLE.value
        super().__init__(self.code)


def copy_patient_data(data: dict) -> dict:
    """Detach a bounded JSON object; reject unsupported values without echoing data.

    This is a storage bound. Callers still validate an allowlisted product
    schema and decide which data belongs in the encounter.
    """
    if type(data) is not dict:
        raise PatientSessionError(ErrorCode.INVALID_PAYLOAD)

    nodes = 0
    text_chars = 0

    def copy(value, depth):
        nonlocal nodes, text_chars
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            raise PatientSessionError(ErrorCode.INVALID_PAYLOAD)
        kind = type(value)
        if kind is str:
            text_chars += len(value)
            if text_chars <= _MAX_TEXT_CHARS:
                return value
        elif value is None or kind is bool:
            return value
        elif kind is int and -_MAX_INTEGER - 1 <= value <= _MAX_INTEGER:
            return value
        elif kind is float and isfinite(value):
            return value
        elif kind is list:
            return [copy(item, depth + 1) for item in value]
        elif kind is dict:
            result = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise PatientSessionError(ErrorCode.INVALID_PAYLOAD)
                result[copy(key, depth + 1)] = copy(item, depth + 1)
            return result
        raise PatientSessionError(ErrorCode.INVALID_PAYLOAD)

    try:
        return copy(data, 0)
    except RuntimeError:
        # A caller modifying the input object during a copy cannot obtain a
        # partial commit. Do not propagate the underlying implementation error.
        pass
    raise PatientSessionError(ErrorCode.INVALID_PAYLOAD)
