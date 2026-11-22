"""Validate answers against the question most recently issued by the server."""

import re
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

from .evidence import review_candidate, unresolved_evidence, validate_candidate, validate_verbatim_text


_LANGUAGE = re.compile(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8}){0,3}\Z")
_KINDS = {"single", "multiple", "text", "evidence_review"}
_REVIEW_LABELS = {"confirm": "Matches my statement", "uncertain": "I’m not sure",
                  "disagree": "Does not match my statement"}


class UnsupportedInterview(ValueError):
    """The context is outside this configuration's supported use."""


class InterviewLimitReached(ValueError):
    """The interview has used all permitted answer turns."""


@dataclass(frozen=True)
class QuestionBinding:
    """An encounter, revision, and question issuance from the server session."""

    encounter_id: str = field(repr=False)
    revision: int
    issuance_id: str = field(repr=False)

    def __post_init__(self):
        if any(type(value) is not str or not value.strip()
               for value in (self.encounter_id, self.issuance_id)):
            raise ValueError("Invalid question reference")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("Invalid question revision")


def validate_answer(answer, *, submitted, issued, kind, option_ids=(), exclusive_option_ids=(),
                    max_selections=None, max_text_chars=None):
    """Check the current issuance, then return verbatim text or ordered choice IDs.

    The issued binding and choice configuration must come from the current
    server session. A mutable session must atomically check and consume that
    issuance when applying the answer. Choice IDs have no clinical meaning here.
    """
    if type(submitted) is not QuestionBinding or type(issued) is not QuestionBinding or submitted != issued:
        raise ValueError("This question has changed. Use the current question")

    if type(kind) is not str or kind not in ("single", "multiple", "text"):
        raise ValueError("This question type is unavailable")
    if kind == "text":
        return validate_verbatim_text(answer, max_chars=max_text_chars)
    options = _option_ids(option_ids)
    exclusive = _option_ids(exclusive_option_ids)
    if not options or not set(exclusive).issubset(options):
        raise ValueError("This question's choices are unavailable")

    if kind == "single":
        if type(answer) is not str or answer not in options:
            raise ValueError("Choose an option shown for this question")
        return (answer,)

    if max_selections is None:
        max_selections = len(options)
    if type(max_selections) is not int or not 1 <= max_selections <= len(options):
        raise ValueError("This question's choice limit is unavailable")
    if type(answer) not in (list, tuple) or not 1 <= len(answer) <= max_selections:
        raise ValueError("Choose within the allowed number of options")
    if any(type(value) is not str or value not in options for value in answer):
        raise ValueError("Choose options shown for this question")
    selected = set(answer)
    if len(selected) != len(answer):
        raise ValueError("Choose each option once")
    if len(selected) > 1 and selected.intersection(exclusive):
        raise ValueError("Choose that option on its own")
    return tuple(option for option in options if option in selected)


def _option_ids(values):
    if (type(values) not in (list, tuple)
            or any(type(value) is not str or not value.strip() for value in values)
            or len(set(values)) != len(values)):
        raise ValueError("This question's choices are unavailable")
    return tuple(values)


class PatientInterview:
    """Build and reduce JSON-safe interview snapshots for a server session.

    The caller stores snapshots and questions server-side, using atomic revision
    checks on every update. This reducer does not infer symptoms or invoke a provider.
    """

    def __init__(self, *, max_turns=12, max_description_chars=4000, max_answer_chars=1500,
                 supported_age_range=None, supported_languages=None):
        limits = (max_turns, max_description_chars, max_answer_chars)
        if any(type(limit) is not int or limit < 1 for limit in limits):
            raise ValueError("Invalid interview limit")
        if supported_age_range is not None:
            if (type(supported_age_range) not in (tuple, list) or len(supported_age_range) != 2
                    or any(type(age) is not int or age < 0 for age in supported_age_range)
                    or supported_age_range[0] > supported_age_range[1]):
                raise ValueError("Invalid supported age range")
            supported_age_range = tuple(supported_age_range)
        if supported_languages is not None:
            if (type(supported_languages) not in (tuple, list) or not supported_languages
                    or any(not _valid_language(language) for language in supported_languages)):
                raise ValueError("Invalid supported languages")
            supported_languages = frozenset(language.lower() for language in supported_languages)
        self._max_turns, self._max_description_chars, self._max_answer_chars = limits
        self._age_range = supported_age_range
        self._languages = supported_languages

    def start(self, description, context):
        """Start a fresh interview, discarding earlier answers and evidence."""
        return {
            "interview_id": uuid4().hex,
            "source": {"description": validate_verbatim_text(description, max_chars=self._max_description_chars)},
            "context": self._normalize_context(context),
            "answers": [],
            "patient_evidence": [],
        }

    def _normalize_context(self, context):
        if type(context) is not dict or set(context) - {"age_years", "language"}:
            raise ValueError("Enter supported interview context fields")
        age, language = context.get("age_years"), context.get("language")
        if age is not None and (type(age) is not int or age < 0):
            raise ValueError("Enter a valid age in years")
        if language is not None and not _valid_language(language):
            raise ValueError("Select a valid interview language")
        if self._age_range is not None and (age is None or not self._age_range[0] <= age <= self._age_range[1]):
            raise UnsupportedInterview("This age is outside the supported interview range")
        if self._languages is not None and (language is None or language.lower() not in self._languages):
            raise UnsupportedInterview("This interview does not support the selected language")
        return {"age_years": age, "language": language}

    def prepare_question(self, provider_question, interview_data):
        """Validate a provider proposal before the service adds its issuance ID."""
        position = self._position(interview_data)
        if type(provider_question) is not dict:
            raise ValueError("This follow-up question is unavailable")
        kind = provider_question.get("kind")
        if type(kind) is not str or kind not in _KINDS:
            raise ValueError("This question type is unavailable")
        fields = {"id", "kind", "prompt", "options"}
        if kind == "evidence_review":
            fields.add("evidence")
        if set(provider_question) != fields:
            raise ValueError("This follow-up question is unavailable")

        question = {
            "id": validate_verbatim_text(provider_question["id"], max_chars=128),
            "kind": kind,
            "prompt": validate_verbatim_text(provider_question["prompt"], max_chars=1500),
            "options": _prepare_options(provider_question["options"], kind),
            "interview_id": interview_data["interview_id"],
            "position": position,
        }
        if kind == "evidence_review":
            source_refs = {"description"}
            source_refs.update(row["issuance_id"] for row in interview_data["answers"] if row["kind"] == "text")
            question["evidence"] = validate_candidate(
                provider_question["evidence"], source_refs=source_refs, max_label_chars=240,
            )
            question["prompt"] = "Does this observation match your statement?"
        return question

    def _position(self, interview_data):
        position = len(interview_data["answers"])
        if position >= self._max_turns:
            raise InterviewLimitReached("This interview reached its follow-up limit")
        return position

    def answer(self, interview_data, server_question, question_id, answers):
        """Return a new snapshot after accepting the exact current issued question."""
        position = self._position(interview_data)
        if type(server_question) is not dict or type(question_id) is not str or not question_id.strip():
            raise ValueError("This question has changed. Use the current question")
        issued = QuestionBinding(
            server_question.get("interview_id"), server_question.get("position"), server_question.get("issuance_id"),
        )
        submitted = QuestionBinding(interview_data["interview_id"], position, question_id)
        kind = server_question["kind"]
        validated = validate_answer(
            answers, submitted=submitted, issued=issued, kind="single" if kind == "evidence_review" else kind,
            option_ids=[option["id"] for option in server_question["options"]],
            max_text_chars=self._max_answer_chars,
        )

        updated = deepcopy(interview_data)
        updated["answers"].append({
            "kind": kind, "issuance_id": issued.issuance_id,
            "provider_question_id": server_question["id"],
            "answer": validated if kind == "text" else list(validated),
        })
        if kind == "evidence_review":
            updated["patient_evidence"].append(review_candidate(
                server_question["evidence"], validated[0],
                issuance_id=issued.issuance_id, provider_question_id=server_question["id"],
            ))
        return updated

    @staticmethod
    def question_view(server_question):
        """Expose display fields only. Keep provider and session identifiers private."""
        public = {key: server_question[key] for key in ("issuance_id", "kind", "prompt")}
        public["options"] = [dict(option) for option in server_question["options"]]
        if server_question["kind"] == "evidence_review":
            public["evidence"] = {
                key: server_question["evidence"][key] for key in ("label", "presence", "temporality")
            }
        return public

    @staticmethod
    def has_unresolved_evidence(interview_data):
        return unresolved_evidence(interview_data["patient_evidence"])


def _valid_language(language):
    return type(language) is str and _LANGUAGE.fullmatch(language) is not None


def _prepare_options(options, kind):
    if type(options) is not list or len(options) > 20 or bool(options) != (kind != "text"):
        raise ValueError("This question's choices are unavailable")
    prepared = []
    for option in options:
        if type(option) is not dict or set(option) != {"id", "label"}:
            raise ValueError("This question's choices are unavailable")
        prepared.append({
            "id": validate_verbatim_text(option["id"], max_chars=128),
            "label": validate_verbatim_text(option["label"], max_chars=240),
        })
    identifiers = _option_ids([option["id"] for option in prepared])
    if kind == "evidence_review":
        if set(identifiers) != _REVIEW_LABELS.keys():
            raise ValueError("This evidence proposal is unavailable")
        return [{"id": identifier, "label": label} for identifier, label in _REVIEW_LABELS.items()]
    return prepared


# Defaults set mechanical bounds only. An approved provider configuration may
# supply explicit population and language limits through PatientInterview.
_default = PatientInterview()
start = _default.start
prepare_question = _default.prepare_question
answer = _default.answer
question_view = PatientInterview.question_view
has_unresolved_evidence = PatientInterview.has_unresolved_evidence
