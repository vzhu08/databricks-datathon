"""Server-only assessment orchestration primitives."""

import hashlib
import hmac
import json
import secrets

from .contracts import (
    POLICY_VERSION, _STRUCTURED_ASSESSMENT_STATES, _provider_reply, _snapshot, _text, _valid_disposition,
)


class _Confirmation:
    """An opaque receipt for one reviewed result in one server encounter."""

    __slots__ = ("_tag",)

    def __init__(self, tag):
        self._tag = tag

    def __reduce__(self):
        raise TypeError("Keep assessment confirmations in the server session")


def _result_secret():
    """Generate independently for each newly committed completed result."""
    return secrets.token_hex(32)


def _confirmation_tag(secret, revision, policy_version, provider_id, provider_version):
    # The secret is unique to a result and never appears in a display record.
    binding = json.dumps([revision, policy_version, provider_id, provider_version],
                         separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hmac.digest(bytes.fromhex(secret), binding, hashlib.sha256)


def _matches_confirmation(receipt, tag):
    return (type(receipt) is _Confirmation and type(receipt._tag) is bytes
            and hmac.compare_digest(receipt._tag, tag))


def _empty(revision, state="draft", consent=False):
    return dict(state=state, revision=revision, policy_version=POLICY_VERSION, consent=consent,
                provider_id=None, provider_version=None, question=None, guidance=None,
                uncertainty=None, urgency=None, possible_causes=[], next_step=None, reason=None,
                description_status=None)


_ANY_REVISION = object()
_TERMINAL_INTERVIEW_STATES = ("urgent", "provider_stop", "experimental_assessment")


def _read(handle, expected=_ANY_REVISION):
    revision, data = handle.read()
    if expected is not _ANY_REVISION and (type(expected) is not int or expected != revision):
        raise ValueError("revision_stale")
    if not data:
        data = dict(state="draft", interview=None, server_question=None, calls_used=0, continuation=None, result_secret=None,
                    consent_identity=None, consent_policy=None, assessment=_empty(revision))
    return revision, data


def _unsupported_context(data):
    assessment = data["assessment"]
    return assessment["state"] == "unsupported" and assessment["reason"] == "unsupported_context"


class PatientIntakeService:
    """Use one trusted adapter configuration and a server-owned handle per encounter."""

    def __init__(self, *, interview, provider=None, provider_identity=None, provider_bindings=None,
                 handoff=None, max_turns=8):
        if type(max_turns) is not int or not 1 <= max_turns <= 32:
            raise ValueError("invalid_turn_limit")
        if provider_identity is not None and (type(provider_identity) is not tuple
                or len(provider_identity) != 2 or not all(_text(s, 128) for s in provider_identity)):
            raise ValueError("invalid_provider_configuration")
        self._interview = interview
        self._provider = provider
        if provider_bindings is not None and (provider is not None or not callable(provider_bindings)):
            raise ValueError("invalid_provider_configuration")
        self._bindings = provider_bindings
        self._identity = provider_identity if provider is not None or provider_bindings is not None else None
        self._handoff = handoff
        self._max_turns = max_turns

    def view(self, handle):
        revision, data = _read(handle)
        a = data["assessment"]
        if a["policy_version"] != POLICY_VERSION or (a["consent"] and not self._consented(data)):
            return dict(_empty(revision, "provider_unavailable"), reason="configuration_changed")
        if a["state"] in _STRUCTURED_ASSESSMENT_STATES and not _valid_disposition(a):
            return dict(_empty(revision, "provider_unavailable"), reason="invalid_response")
        return a

    def _consented(self, data):
        return (self._identity is not None
                and data.get("consent_bound", False) is (self._bindings is not None)
                and data["consent_identity"] == list(self._identity)
                and data.get("consent_policy") == POLICY_VERSION)

    def _commit(self, handle, revision, data, state, *, retire_provider=False, **display):
        a = dict(_empty(revision + 1, state, self._consented(data)), **display)
        if data["interview"] is not None:
            a["description_status"] = "uninterpreted"
        if state != "awaiting_clarification":
            data["server_question"] = None
        data["state"] = state
        data["assessment"] = a
        data["result_secret"] = _result_secret() if state == "completed" else None
        if retire_provider:
            committed_revision = handle.replace(revision, data, retire_provider=True)
        else:
            committed_revision = handle.replace(revision, data)
        _, committed = _read(handle, committed_revision)
        return committed["assessment"]

    def edit(self, handle, expected_revision, *, description, context):
        rev, data = _read(handle, expected_revision)
        ineligible = _unsupported_context(data)
        retire = data.get("consent_bound", False)
        data.update(continuation=None, consent_identity=None, consent_policy=None, consent_bound=False,
                    interview=None, interview_ended=False)
        try:
            data["interview"] = _snapshot(self._interview.start(description, context))
        except (TypeError, ValueError) as error:
            if getattr(error, "code", None) == "unsupported_context" or ineligible:
                return self._commit(handle, rev, data, "unsupported", reason="unsupported_context", retire_provider=retire)
            return self._commit(handle, rev, data, "draft", reason="invalid_input", retire_provider=retire)
        try:
            return self._commit(handle, rev, data, "draft", retire_provider=retire)
        except ValueError as error:
            if getattr(error, "code", None) != "session_invalid_payload":
                raise
        data["interview"] = None
        if ineligible:
            return self._commit(handle, rev, data, "unsupported", reason="unsupported_context", retire_provider=retire)
        return self._commit(handle, rev, data, "draft", reason="invalid_input", retire_provider=retire)

    def consent(self, handle, expected_revision, *, granted):
        rev, data = _read(handle, expected_revision)
        if type(granted) is not bool:
            raise ValueError("invalid_consent")
        if _unsupported_context(data):
            return data["assessment"]
        retire = data.get("consent_bound", False)
        if granted and retire and self._consented(data):
            return data["assessment"]
        data["consent_bound"] = granted and self._identity is not None and self._bindings is not None
        data["continuation"] = None
        data["consent_policy"] = POLICY_VERSION if granted else None
        data["consent_identity"] = list(self._identity) if granted and self._identity else None
        return self._commit(handle, rev, data, "draft", retire_provider=retire)

    def answer(self, handle, expected_revision, *, question_id, answers):
        rev, data = _read(handle, expected_revision)
        a = self.view(handle)
        q = data["server_question"]
        if (a["revision"] != rev or a["state"] != "awaiting_clarification" or not q
                or type(question_id) is not str or question_id != q["issuance_id"]):
            raise ValueError("question_stale")
        try:
            interview = self._interview.answer(data["interview"], q, question_id, answers)
            data["interview"] = _snapshot(interview)
        except (TypeError, ValueError):
            raise ValueError("invalid_answer") from None
        return self._commit(handle, rev, data, "draft")

    def assess(self, handle, expected_revision):
        rev, data = _read(handle, expected_revision)
        if _unsupported_context(data):
            return data["assessment"]
        if (data.get("interview_ended") or data["assessment"]["state"] in
                ("assessment_in_progress", "awaiting_clarification", *_TERMINAL_INTERVIEW_STATES)):
            raise ValueError("assessment_action_unavailable")
        if self._identity is None:
            return self._commit(handle, rev, data, "provider_unavailable", reason="unavailable")
        if not self._consented(data) or data["interview"] is None:
            return self._commit(handle, rev, data, "draft", reason="consent_or_input_required")
        provenance = dict(provider_id=self._identity[0], provider_version=self._identity[1])
        if data["calls_used"] >= self._max_turns:
            return self._commit(handle, rev, data, "provider_unavailable", reason="budget_exhausted", **provenance)
        data["calls_used"] += 1
        self._commit(handle, rev, data, "assessment_in_progress", **provenance)
        attempt, data = _read(handle, rev + 1)
        state, fields = self._evaluate(handle, attempt, data)
        try:
            return self._commit(handle, attempt, data, state, **provenance, **fields)
        except ValueError as error:
            if getattr(error, "code", None) != "session_invalid_payload":
                raise
        # The provider output exceeded the owner's per-encounter storage cap.
        # Use the original bounded reservation, still subject to the same CAS.
        _, reserved = _read(handle, attempt)
        reserved["continuation"] = None
        return self._commit(handle, attempt, reserved, "provider_unavailable",
                            reason="invalid_response", **provenance)

    def _evaluate(self, handle, attempt, data):
        # An ambiguous transport failure cannot safely reuse the old provider turn.
        continuation = data["continuation"]
        data["continuation"] = None
        try:
            provider = self._provider
            if self._bindings is not None:
                provider = handle.bind_provider(attempt, self._bindings)
            raw = provider.assess(_snapshot(data["interview"]), continuation=continuation)
        except Exception:
            return "provider_unavailable", {"reason": "unavailable"}
        try:
            reply = _provider_reply(raw, self._identity)
            state = reply.pop("state")
            del reply["provider_id"], reply["provider_version"]
            if state == "awaiting_clarification":
                question = _snapshot(self._interview.prepare_question(reply["question"], data["interview"]))
                question["issuance_id"] = secrets.token_urlsafe(24)
                data["continuation"] = reply.get("continuation")
                data["server_question"] = question
                return state, {"question": _snapshot(self._interview.question_view(question))}
            needs_resolved_evidence = state == "completed" or (
                state == "experimental_assessment" and reply["urgency"] not in ("emergency", "emergency_ambulance")
            )
            if needs_resolved_evidence and self._interview.has_unresolved_evidence(data["interview"]) is not False:
                return "unsupported", {"reason": "unsupported_correction"}
            if state in _TERMINAL_INTERVIEW_STATES:
                data["interview_ended"] = True
            return state, reply
        except Exception as error:
            if getattr(error, "code", None) == "interview_limit":
                return "unsupported", {"reason": "interview_limit"}
            return "provider_unavailable", {"reason": "invalid_response"}

    def _tag(self, rev, data):
        a = data["assessment"]
        if (a["state"] != "completed" or not _valid_disposition(a) or not self._consented(data)
                or a["policy_version"] != POLICY_VERSION
                or a["revision"] != rev or (a["provider_id"], a["provider_version"]) != self._identity):
            raise ValueError("confirmation_unavailable")
        return _confirmation_tag(data["result_secret"], rev, POLICY_VERSION, *self._identity)

    def confirm(self, handle, expected_revision):
        rev, data = _read(handle, expected_revision)
        return _Confirmation(self._tag(rev, data))

    def navigate(self, handle, expected_revision, *, confirmation):
        rev, data = _read(handle, expected_revision)
        if not _matches_confirmation(confirmation, self._tag(rev, data)):
            raise ValueError("confirmation_invalid")
        result = (self._handoff(handle, rev, data["assessment"]) if self._handoff
                  else {"state": "no_reviewed_destination"})
        _read(handle, rev)
        return result
