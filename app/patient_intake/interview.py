"""Validate answers against the question most recently issued by the server."""

from dataclasses import dataclass, field

from .evidence import validate_verbatim_text


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
