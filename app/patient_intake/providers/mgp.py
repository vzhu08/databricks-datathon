"""Optional Infermedica MGP v1 candidate for a server-owned Triage survey."""

import re
import secrets
from urllib.parse import parse_qsl, urlsplit
from threading import Lock

PROVIDER_ID = "infermedica-mgp"
PROVIDER_VERSION = "platform-v1-candidate"
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_OPTION = re.compile(r"[a-zA-Z0-9_.-]{1,80}")
_FAILURES = {
    "access_denied": "unauthorized", "budget_exhausted": "budget_exhausted",
    "rate_limited": "rate_limited", "timeout": "timeout", "invalid_response": "invalid_response",
}
# A missing selection from the server must never implicitly skip a question.
SKIP = object()
_KINDS = {"choice": "single", "multiple_choice": "multiple", "list": "multiple", "text": "text"}
_ALERT_REASONS = ("emergency", "suicide_attempt", "suicidal_intent", "suicidal_thoughts")


def _early_stop(alerts):
    if type(alerts) is not list or len(alerts) > 16:
        return _reply("provider_unavailable", reason="invalid_response")
    emergency = False
    unknown = False
    for alert in alerts:
        if type(alert) is not dict or alert.get("type") not in ("soft_stop", "hard_stop"):
            unknown = True
            continue
        reasons = alert.get("reasons")
        if type(reasons) is not list or not 1 <= len(reasons) <= 16:
            unknown = True
            continue
        emergency |= "emergency" in reasons
        unknown |= any(reason not in _ALERT_REASONS for reason in reasons)
    if emergency:
        return _reply("urgent", urgency="emergency", guidance="The provider flagged an emergency.",
                      uncertainty="The interview ended before a final assessment.",
                      possible_causes=[], next_step=None)
    if unknown:
        return _reply("provider_unavailable", reason="invalid_response")
    if alerts:
        # The published stop alone does not specify an MGP triage level.
        return _reply("unsupported", reason="unsupported")
    return None
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

    def __init__(self, *, survey_for=None, choices_for=None, catalog_for=None, transport=None, budget=None, enabled=False):
        self._survey_for = survey_for
        self._choices_for = choices_for
        self._catalog_for = catalog_for
        self._transport = transport
        self._budget = budget
        self._enabled = enabled is True
        self._lock = Lock()
        self._started = False
        self._survey = None
        self._pending = None
        self._answered = {}

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
            payload = self._answer_payload(question, choices)
            if payload is None:
                return _reply("unsupported", reason="unsupported")
            result = self._call("POST", "/questions/current", payload)
            if result.status == "received" and question["index"] is not None:
                self._answered[question["index"]] = question
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

    def correct(self, interview_data, *, continuation, index, choices):
        """Replace an accepted answer in the still-open, currently bound survey."""
        if not self._enabled or not self._lock.acquire(blocking=False):
            return _reply("provider_unavailable", reason="unavailable")
        try:
            if (self._pending is None or type(index) is not int or index not in self._answered
                    or type(continuation) is not str or not continuation.isascii()
                    or not secrets.compare_digest(continuation, self._pending[0])):
                return _reply("unsupported", reason="unsupported_correction")
            self._pending = None
            if self._survey_for(interview_data) != self._survey:
                return _reply("unsupported", reason="unsupported_correction")
            question = self._answered[index]
            payload = self._answer_payload(question, choices)
            if payload is None:
                return _reply("unsupported", reason="unsupported_correction")
            self._answered = {i: q for i, q in self._answered.items() if i <= index}
            result = self._call("PUT", f"/questions/{index}", payload)
            if result.status == "empty":
                return self._finished()
            return self._question(result.data) if result.status == "received" else _failure(result)
        except Exception:
            self._pending = None
            return _reply("provider_unavailable", reason="unavailable")
        finally:
            self._lock.release()

    def _answer_payload(self, question, choices):
        if choices is SKIP and question.get("component") == "group_single":
            answer = [dict(id=row["id"], choice_id="unknown") for row in question["options"]]
        elif choices is SKIP and question["optional"]:
            answer = None
        elif question["kind"] == "text" and _text(choices, question["max_length"]):
            answer = choices
        elif self._valid_choices(question, choices):
            if question.get("component") == "single":
                answer = [dict(id=question["item_id"], choice_id=choices[0])]
            elif question.get("component") == "group_single":
                answer = [dict(id=choices[0], choice_id="present")]
            else:
                answer = [{"id": item} for item in choices]
                if question["kind"] == "single":
                    answer = answer[0]
        else:
            return None
        return {"answer": answer}

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
        meta = value.get("meta")
        if type(meta) is dict and "alerts" in meta:
            stop = _early_stop(meta["alerts"])
            if stop:
                return stop
        question_type = value.get("answer_type")
        if type(question_type) is not str:
            return _reply("provider_unavailable", reason="invalid_response")
        if question_type not in (*_KINDS, "symptoms"):
            return _reply("unsupported", reason="unsupported")
        question_id = value.get("id")
        prompt = value.get("question")
        if type(meta) is not dict or type(meta.get("required", True)) is not bool:
            return _reply("provider_unavailable", reason="invalid_response")
        if value.get("user_answer") is not None or meta.get("subcomponent"):
            # A preselected answer or specialized visual prompt needs lossless rendering.
            return _reply("unsupported", reason="unsupported")
        options = [] if question_type == "text" else meta.get("answers")
        if question_type == "list":
            options = self._catalog_options(meta.get("source_list_url"))
            if options is None:
                return _reply("unsupported", reason="unsupported")
        index = value.get("index")
        if index is not None and (type(index) is not int or not 0 <= index < 1024):
            return _reply("provider_unavailable", reason="invalid_response")
        component = None
        item_id = None
        if question_type == "symptoms":
            component = meta.get("component")
            if component not in ("single", "group_single"):
                return _reply("unsupported", reason="unsupported")
            if type(options) is not list or not 1 <= len(options) <= 16:
                return _reply("provider_unavailable", reason="invalid_response")
            if component == "single":
                item = options[0]
                if len(options) != 1 or type(item) is not dict or not _identifier(item.get("id"), _OPTION):
                    return _reply("provider_unavailable", reason="invalid_response")
                item_id = item["id"]
                options = item.get("choices")
            elif all(type(row) is dict for row in options):
                options = [{"id": row.get("id"), "label": row.get("name")} for row in options]
        limit = meta.get("max_length", 1500)
        if question_type == "text" and (type(limit) is not int or limit < 1):
            return _reply("provider_unavailable", reason="invalid_response")
        if (not _identifier(question_id, _OPTION) or type(prompt) is not dict
                or not _text(prompt.get("text"), 500)
                or type(options) is not list or len(options) > 16
                or (question_type != "text" and not options)):
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

        display = dict(id=question_id, kind=_KINDS.get(question_type, "single"),
                       prompt=prompt["text"], options=safe_options)
        continuation = secrets.token_hex(16)
        # Keep a detached copy so a consumer cannot alter the answer allowlist.
        self._pending = continuation, {**display, "optional": component is None and not meta.get("required", True),
                                       "component": component, "item_id": item_id, "index": index,
                                       "max_length": min(limit, 1500) if question_type == "text" else None,
                                       "options": [dict(option) for option in safe_options]}
        return _reply("awaiting_clarification", question=display, continuation=continuation)

    def _catalog_options(self, source):
        items = self._catalog_data(source)
        if type(items) is not list or not 1 <= len(items) <= 16 or any(type(i) is not dict for i in items):
            return None
        return [{"id": item.get("id"), "label": item.get("name")} for item in items]

    def _catalog_data(self, source):
        """Resolve an exact, complete, locally authorized list. Never follow vendor URLs."""
        if not callable(self._catalog_for) or not _text(source, 512) or not source.startswith("/") or source.startswith("//"):
            return None
        url = urlsplit(source)
        if url.scheme or url.netloc or url.fragment:
            return None
        path = url.path.removeprefix("/api/mgp")
        collections = ("symptoms", "chronic_diseases", "specialists", "hospitalizations")
        if path not in {"/v1/knowledge/" + name for name in collections}:
            return None
        try:
            pairs = parse_qsl(url.query, strict_parsing=True, max_num_fields=5, keep_blank_values=True)
        except ValueError:
            return None
        filters = dict(pairs)
        if len(filters) != len(pairs) or set(filters) - {"age", "age.value", "age.unit", "sex", "language"}:
            return None
        if any(not _identifier(v, _OPTION) for v in filters.values()):
            return None
        # Only this server binding can attest edition, demographics and completeness.
        return self._catalog_for(self._survey, path.rsplit("/", 1)[1], filters)

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
