"""Validate answers against the question most recently issued by the server."""

import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

from .evidence import PRESENCE, review_candidate, unresolved_evidence, validate_candidate, validate_verbatim_text


_LANGUAGE = re.compile(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8}){0,3}\Z")
_QUESTION_V2 = "patient-question.v2"
_V1_KINDS = {"single", "multiple", "text", "evidence_review"}
_V2_FIELDS = {
    "single": (), "multiple": (), "text": (),
    "item_presence": ("items",), "quantity": ("units",), "catalog_selection": ("selection", "catalog"),
}
_NO_OPTIONS = {"text", "item_presence", "quantity"}
_V2_LIMIT = 16
_REVIEW_LABELS = {"confirm": "Matches my statement", "uncertain": "I’m not sure",
                  "disagree": "Does not match my statement"}


class UnsupportedInterview(ValueError):
    """The context is outside this configuration's supported use."""

    code = "unsupported_context"


class InterviewLimitReached(ValueError):
    """The interview has used all permitted answer turns."""

    code = "interview_limit"

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
    _check_issuance(submitted, issued)
    return _validate_choice_or_text(
        answer, kind=kind, option_ids=option_ids, exclusive_option_ids=exclusive_option_ids,
        max_selections=max_selections, max_text_chars=max_text_chars,
    )


def _check_issuance(submitted, issued):
    if type(submitted) is not QuestionBinding or type(issued) is not QuestionBinding or submitted != issued:
        raise ValueError("This question has changed. Use the current question")


def _validate_choice_or_text(answer, *, kind, option_ids=(), exclusive_option_ids=(),
                             max_selections=None, max_text_chars=None):
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


def _validate_item_answers(answers, *, issued_ids, required_ids, allowed_choices=None):
    """Return explicit observations in issuance order, omitting unanswered optional items."""
    issued = _option_ids(issued_ids)
    required = set(_option_ids(required_ids))
    if not issued or not required.issubset(issued):
        raise ValueError("This question's items are unavailable")
    if type(answers) is not list or not 1 <= len(answers) <= len(issued):
        raise ValueError("Answer each required item")
    observed = {}
    for row in answers:
        if type(row) is not dict or row.keys() != {"id", "presence"}:
            raise ValueError("Choose a status for each answered item")
        item, presence = row["id"], row["presence"]
        if (type(item) is not str or item not in issued or item in observed
                or type(presence) is not str or presence not in PRESENCE):
            raise ValueError("Choose one valid status for each answered item")
        if allowed_choices is not None and presence not in allowed_choices[item]:
            raise ValueError("Choose a status shown for this item")
        observed[item] = presence
    if not required.issubset(observed):
        raise ValueError("Answer each required item")
    return [{"id": item, "presence": observed[item]} for item in issued if item in observed]


def _validate_quantity_bounds(minimum, maximum, integer_only):
    if (type(integer_only) is not bool or not _finite_quantity(minimum)
            or not _finite_quantity(maximum) or minimum > maximum):
        raise ValueError("This question's measurement range is unavailable")
    if integer_only and math.ceil(minimum) > math.floor(maximum):
        raise ValueError("This question's measurement range is unavailable")


def _validate_quantity_value(value, *, minimum, maximum, integer_only):
    """Validate a number against the exact bounds for the selected issued unit."""
    _validate_quantity_bounds(minimum, maximum, integer_only)
    if (not _finite_quantity(value) or (integer_only and type(value) is not int)
            or not minimum <= value <= maximum):
        raise ValueError("Enter a value within the range shown for this unit")
    return value


def _validate_quantity_answer(answer, *, issued_units):
    if type(answer) is not dict or answer.keys() != {"value", "unit_id"}:
        raise ValueError("Enter a value and select a shown unit")
    unit_id = answer["unit_id"]
    if type(unit_id) is not str or unit_id not in issued_units:
        raise ValueError("Select a unit shown for this question")
    value = _validate_quantity_value(answer["value"], **issued_units[unit_id])
    return {"value": value, "unit_id": unit_id}


def _skip_requested(answer, *, optional):
    """Recognize the explicit skip action without interpreting omitted values."""
    if type(optional) is not bool:
        raise ValueError("This question's skip permission is unavailable")
    if type(answer) is not dict or "skip" not in answer:
        return False
    if answer.keys() != {"skip"} or answer["skip"] is not True:
        raise ValueError("This skip response is invalid")
    if not optional:
        raise ValueError("Answer this required question")
    return True


def _finite_quantity(value):
    # Match the shared bounded JSON record without coercing booleans or big integers.
    return ((type(value) is int and value.bit_length() <= 64)
            or (type(value) is float and math.isfinite(value)))


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
        is_v2 = _check_question_fields(provider_question, kind)

        question = {
            "id": validate_verbatim_text(provider_question["id"], max_chars=128),
            "kind": kind,
            "prompt": validate_verbatim_text(provider_question["prompt"], max_chars=1500),
            "options": _prepare_options(provider_question["options"], kind, max_options=_V2_LIMIT if is_v2 else 20),
            "interview_id": interview_data["interview_id"],
            "position": position,
        }
        if is_v2:
            question.update(_prepare_v2(provider_question, kind, interview_data))
        elif kind == "evidence_review":
            source_refs = {"description"}
            source_refs.update(row["issuance_id"] for row in interview_data["answers"]
                               if row["kind"] == "text" and type(row["answer"]) is str)
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
        _check_issuance(submitted, issued)
        kind = server_question["kind"]
        if kind == "catalog_selection" and server_question["catalog_context"] != interview_data["context"]:
            raise ValueError("This catalog has changed. Use the current question")
        skipped = _skip_requested(answers, optional=server_question.get("optional", False))
        validated = None if skipped else _answer_value(answers, server_question, self._max_answer_chars)

        updated = deepcopy(interview_data)
        record = {
            "kind": kind, "issuance_id": issued.issuance_id,
            "provider_question_id": server_question["id"],
            "answer": validated,
        }
        if skipped:
            record["skipped"] = True
        if kind == "catalog_selection":
            record["catalog"] = dict(server_question["catalog"])
        updated["answers"].append(record)
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
        if server_question.get("schema") == _QUESTION_V2:
            public.update(schema=_QUESTION_V2, optional=server_question["optional"])
            kind = server_question["kind"]
            if kind in ("item_presence", "quantity"):
                field = _V2_FIELDS[kind][0]
                public[field] = deepcopy(server_question[field])
            elif kind == "catalog_selection":
                public["selection"] = server_question["selection"]
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


def _prepare_options(options, kind, *, max_options):
    if type(options) is not list or len(options) > max_options or bool(options) != (kind not in _NO_OPTIONS):
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


def _check_question_fields(provider_question, kind):
    fields = {"id", "kind", "prompt", "options"}
    if "schema" in provider_question:
        if (type(provider_question["schema"]) is not str or provider_question["schema"] != _QUESTION_V2
                or type(kind) is not str or kind not in _V2_FIELDS):
            raise ValueError("This question type is unavailable")
        required = fields | {"schema"} | set(_V2_FIELDS[kind])
        if not required <= provider_question.keys() <= required | {"optional"}:
            raise ValueError("This follow-up question is unavailable")
        return True
    if type(kind) is not str or kind not in _V1_KINDS:
        raise ValueError("This question type is unavailable")
    if kind == "evidence_review":
        fields.add("evidence")
    if set(provider_question) != fields:
        raise ValueError("This follow-up question is unavailable")
    return False


def _prepare_v2(provider_question, kind, interview_data):
    optional = provider_question.get("optional", False)
    if type(optional) is not bool:
        raise ValueError("This question's skip permission is unavailable")
    prepared = {"schema": _QUESTION_V2, "optional": optional}
    if kind == "item_presence":
        prepared["items"] = _prepare_items(provider_question["items"])
    elif kind == "quantity":
        prepared["units"] = _prepare_units(provider_question["units"])
    elif kind == "catalog_selection":
        selection, catalog = provider_question["selection"], provider_question["catalog"]
        if type(selection) is not str or selection not in ("single", "multiple"):
            raise ValueError("This catalog selection is unavailable")
        if type(catalog) is not dict or catalog.keys() != {"id", "edition"}:
            raise ValueError("This catalog is unavailable")
        prepared["selection"] = selection
        prepared["catalog"] = {key: validate_verbatim_text(catalog[key], max_chars=128)
                               for key in ("id", "edition")}
        prepared["catalog_context"] = dict(interview_data["context"])
    return prepared


def _prepare_items(items):
    if type(items) is not list or not 1 <= len(items) <= _V2_LIMIT:
        raise ValueError("This question's items are unavailable")
    prepared = []
    for item in items:
        if (type(item) is not dict or item.keys() != {"id", "label", "required", "choices"}
                or type(item["required"]) is not bool):
            raise ValueError("This question's items are unavailable")
        choices = _prepare_options(item["choices"], "single", max_options=len(PRESENCE))
        if any(choice["id"] not in PRESENCE for choice in choices):
            raise ValueError("This item's statuses are unavailable")
        prepared.append({
            "id": validate_verbatim_text(item["id"], max_chars=128),
            "label": validate_verbatim_text(item["label"], max_chars=240),
            "required": item["required"], "choices": choices,
        })
    _option_ids([item["id"] for item in prepared])
    return prepared


def _unit_bounds(unit):
    return {"minimum": unit["min"], "maximum": unit["max"], "integer_only": unit["integer_only"]}


def _prepare_units(units):
    if type(units) is not list or not 1 <= len(units) <= _V2_LIMIT:
        raise ValueError("This question's units are unavailable")
    prepared = []
    for unit in units:
        if type(unit) is not dict or unit.keys() != {"id", "label", "min", "max", "integer_only"}:
            raise ValueError("This question's units are unavailable")
        _validate_quantity_bounds(**_unit_bounds(unit))
        prepared.append({
            **unit, "id": validate_verbatim_text(unit["id"], max_chars=128),
            "label": validate_verbatim_text(unit["label"], max_chars=240),
        })
    _option_ids([unit["id"] for unit in prepared])
    return prepared


def _answer_value(answers, question, max_text_chars):
    kind = question["kind"]
    if kind == "item_presence":
        if type(answers) is not dict or answers.keys() != {"items"}:
            raise ValueError("Answer each required item")
        items = question["items"]
        return {"items": _validate_item_answers(
            answers["items"], issued_ids=[item["id"] for item in items],
            required_ids=[item["id"] for item in items if item["required"]],
            allowed_choices={item["id"]: {choice["id"] for choice in item["choices"]} for item in items},
        )}
    if kind == "quantity":
        return _validate_quantity_answer(answers, issued_units={unit["id"]: _unit_bounds(unit)
                                                               for unit in question["units"]})
    choice_kind = {"evidence_review": "single", "catalog_selection": question.get("selection")}.get(kind, kind)
    validated = _validate_choice_or_text(
        answers, kind=choice_kind, option_ids=[option["id"] for option in question["options"]],
        max_text_chars=max_text_chars,
    )
    return validated if kind == "text" else list(validated)


# Defaults set mechanical bounds only. An approved provider configuration may
# supply explicit population and language limits through PatientInterview.
_default = PatientInterview()
start = _default.start
prepare_question = _default.prepare_question
answer = _default.answer
question_view = PatientInterview.question_view
has_unresolved_evidence = PatientInterview.has_unresolved_evidence
