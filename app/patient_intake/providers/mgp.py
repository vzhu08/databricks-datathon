"""Optional Infermedica MGP v1 candidate for a server-owned Triage survey."""

import re
import secrets
from threading import Lock

PROVIDER_ID = "infermedica-mgp"
PROVIDER_VERSION = "platform-v1-candidate"
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_OPTION = re.compile(r"[a-zA-Z0-9_.-]{1,80}")
_FAILURES = {
    "access_denied": "unauthorized", "budget_exhausted": "budget_exhausted",
    "rate_limited": "rate_limited", "timeout": "timeout", "invalid_response": "invalid_response",
}
_KINDS = {"choice": "single", "multiple_choice": "multiple"}
_LEVELS = ("self_care", "consultation", "consultation_24", "emergency", "emergency_ambulance")


def _reply(state, **fields):
    return dict(state=state, provider_id=PROVIDER_ID, provider_version=PROVIDER_VERSION, **fields)


def _failure(reply):
    return _reply("provider_unavailable", reason=_FAILURES.get(reply.status, "unavailable"))


def _text(value, limit):
    return (type(value) is str and bool(value.strip()) and len(value) <= limit
            and all(ch.isprintable() for ch in value))


def _identifier(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


class MgpSurveyCandidate:
    """One instance per encounter and survey, accessible only from the server.

    survey_for must return the trusted UUID only when the current interview
    belongs to that survey and its evidence has been reconciled. choices_for
    reads the validated selection for the last issued vendor question.
    """

    def __init__(self, *, survey_for=None, choices_for=None, transport=None, budget=None, enabled=False):
        self._survey_for = survey_for
        self._choices_for = choices_for
        self._transport = transport
        self._budget = budget
        self._enabled = enabled is True
        self._lock = Lock()
        self._started = False
        self._survey = None
        self._pending = None

    def assess(self, interview_data, *, continuation=None):
        if (not self._enabled or self._transport is None or self._budget is None
                or not callable(self._survey_for) or not callable(self._choices_for)):
            return _reply("provider_unavailable", reason="unavailable")
        if not self._lock.acquire(blocking=False):
            return _reply("provider_unavailable", reason="unavailable")
        try:
            return self._assess(interview_data, continuation)
        except Exception:
            # A binding or transport exception can carry encounter data.
            self._pending = None
            return _reply("provider_unavailable", reason="unavailable")
        finally:
            self._lock.release()

    def _call(self, method, suffix, payload=None):
        path = f"/api/mgp/v1/surveys/{self._survey}{suffix}"
        return self._transport.request(method, path, payload=payload, encounter=self._budget)

    def _assess(self, interview_data, continuation):
        survey = self._survey_for(interview_data)
        if not _identifier(survey, _UUID):
            self._pending = None
            return _reply("unsupported", reason="unsupported_correction")
        if self._started:
            if self._survey != survey:
                self._pending = None
                return _reply("unsupported", reason="unsupported_correction")
            if (self._pending is None or
                    type(continuation) is not str or len(continuation) != 32 or
                    not continuation.isascii() or not secrets.compare_digest(continuation, self._pending[0])):
                return _reply("unsupported", reason="unsupported")
            _, question = self._pending
            choices = self._choices_for(interview_data, question["id"])
            # Consume before POST. A timeout cannot authorize an implicit re-submit.
            self._pending = None
            if not self._valid_choices(question, choices):
                return _reply("unsupported", reason="unsupported")
            answer = [{"id": item} for item in choices]
            if question["kind"] == "single":
                answer = answer[0]
            result = self._call("POST", "/questions/current", {"answer": answer})
        else:
            if continuation is not None:
                return _reply("unsupported", reason="unsupported")
            self._survey = survey
            self._started = True
            result = self._call("GET", "/questions/current")

        if result.status == "empty":
            if continuation is None:
                return _reply("unsupported", reason="unsupported")
            return self._finished()
        if result.status != "received":
            return _failure(result)
        return self._question(result.data)

    @staticmethod
    def _valid_choices(question, values):
        if type(values) not in (list, tuple) or not 1 <= len(values) <= len(question["options"]):
            return False
        allowed = {option["id"] for option in question["options"]}
        return ((question["kind"] == "multiple" or len(values) == 1)
                and all(type(value) is str and value in allowed for value in values)
                and len(set(values)) == len(values))

    def _question(self, value):
        if type(value) is not dict:
            return _reply("provider_unavailable", reason="invalid_response")
        question_type = value.get("answer_type")
        if type(question_type) is not str:
            return _reply("provider_unavailable", reason="invalid_response")
        if question_type not in _KINDS:
            return _reply("unsupported", reason="unsupported")
        question_id = value.get("id")
        prompt = value.get("question")
        meta = value.get("meta")
        options = meta.get("answers") if type(meta) is dict else None
        if (not _identifier(question_id, _OPTION) or type(prompt) is not dict
                or not _text(prompt.get("text"), 500)
                or type(options) is not list or not 1 <= len(options) <= 16):
            return _reply("provider_unavailable", reason="invalid_response")
        safe_options = []
        for option in options:
            if (type(option) is not dict or not _identifier(option.get("id"), _OPTION)
                    or not _text(option.get("label"), 160)
                    or option.get("choices") is not None):
                return _reply("provider_unavailable", reason="invalid_response")
            safe_options.append({"id": option["id"], "label": option["label"]})
        if len({option["id"] for option in safe_options}) != len(safe_options):
            return _reply("provider_unavailable", reason="invalid_response")

        display = dict(id=question_id, kind=_KINDS[question_type],
                       prompt=prompt["text"], options=safe_options)
        continuation = secrets.token_hex(16)
        # Keep a detached copy so a consumer cannot alter the answer allowlist.
        self._pending = continuation, {**display, "options": [dict(option) for option in safe_options]}
        return _reply("awaiting_clarification", question=display, continuation=continuation)

    def _finished(self):
        survey = self._call("GET", "")
        if survey.status != "received":
            return _failure(survey)
        if (type(survey.data) is not dict or survey.data.get("id") != self._survey
                or survey.data.get("type") != "triage" or survey.data.get("status") != "completed"):
            return _reply("provider_unavailable", reason="invalid_response")
        result = self._call("GET", "/evidence_assessment")
        if result.status != "received":
            if result.status == "empty":
                return _reply("unsupported", reason="unsupported")
            return _failure(result)
        return _assessment(result.data)


def _assessment(value):
    if type(value) is not dict or type(value.get("triage")) is not dict:
        return _reply("provider_unavailable", reason="invalid_response")
    triage = value["triage"]
    level = triage.get("level")
    guidance = triage.get("description")
    serious = triage.get("serious")
    conditions = value.get("conditions")
    if (level not in _LEVELS or not _text(guidance, 1000)
            or type(serious) is not list or len(serious) > 64
            or type(conditions) is not list or len(conditions) > 64):
        return _reply("provider_unavailable", reason="invalid_response")
    for item in serious:
        severity = item.get("seriousness") if type(item) is dict else None
        if (severity not in ("serious", "emergency", "emergency_ambulance")
                or severity in _LEVELS and _LEVELS.index(severity) > _LEVELS.index(level)
                or severity == "serious" and level == "self_care"):
            return _reply("provider_unavailable", reason="invalid_response")
    labels = []
    for item in conditions:
        if type(item) is not dict or not _text(item.get("common_name"), 160):
            return _reply("provider_unavailable", reason="invalid_response")
        labels.append(item["common_name"])
    urgent = level in ("emergency_ambulance", "emergency", "consultation_24")
    if not labels and not urgent:
        return _reply("unsupported", reason="unsupported")
    return _reply("urgent" if urgent else "completed", guidance=guidance, urgency=level,
                  uncertainty="The listed causes are possibilities from the reported evidence.",
                  possible_causes=labels[:8],
                  next_step={"kind": "consultation", "specialty_code": None}
                  if level == "consultation" else None)
