"""Finite answer choices and progression for scripted fictional intake."""

from collections.abc import Mapping

from .danger_signs import evaluate_danger_signs, warning_catalogue


_WARNING_CHOICES = (("yes", "Yes"), ("no", "No"), ("unknown", "Not sure"))
_WARNING_PROMPTS = {
    "warning.chest_pain": "Does the story report new chest pain?",
    "warning.stroke_like": (
        "Does the story report sudden changes in the face, an arm or speech now or within "
        "the past 24 hours, even if the changes have stopped?"
    ),
    "warning.severe_breathing_difficulty": "Does the story report severe trouble breathing now?",
    "warning.unresponsive": "Does the story say the person cannot be woken now?",
    "warning.heavy_bleeding": "Does the story report heavy bleeding now?",
}
_CONTEXT = (
    ("context.age_group", "Is the person in the story an adult or a child?", "Age group",
     (("adult", "Adult"), ("child", "Child"))),
    ("context.pregnancy", "Does the story say the person is pregnant?", "Pregnancy",
     (("not_pregnant", "Not pregnant"), ("pregnant", "Pregnant"))),
    ("context.onset", "What timing does the story describe?", "Timing",
     (("recent", "Started recently"), ("ongoing", "Ongoing"), ("scheduled", "Scheduled care"))),
    ("context.severity", "How does the story describe the concern?", "Reported severity",
     (("mild", "Mild"), ("moderate", "Moderate"), ("severe", "Severe"))),
)
_UNRESOLVED = {"unknown", "conflicting"}
_WARNING_STATES = {"emergency_escalation", "more_information_needed", "no_reported_warning"}
_DIAGNOSTICS = ("missing", "unknown", "conflicting", "invalid")


def question_catalogue():
    """Return fresh display rows in walk order, with only visitor-selectable answers."""
    warnings = [
        _row(rule["question_id"], "danger", _WARNING_PROMPTS[rule["question_id"]], rule["label"],
             rule["source_ids"], _WARNING_CHOICES)
        for rule in warning_catalogue().values()
    ]
    context = [
        _row(qid, "context", prompt, label, (), (*choices, ("unknown", "Not sure")))
        for qid, prompt, label, choices in _CONTEXT
    ]
    return warnings + context


def _row(qid, kind, text, short, sources, choices):
    return {
        "id": qid, "kind": kind, "text": text, "short": short, "sources": list(sources),
        "answers": [{"id": answer_id, "label": label} for answer_id, label in choices],
    }


def _answer_ids(catalogue):
    return {
        row["id"]: {choice["id"] for choice in row["answers"]} | {"conflicting"}
        for row in catalogue
    }


def _valid_token(value, allowed):
    return type(value) is str and value in allowed


def _invalid_answers(layer, allowed):
    if not isinstance(layer, Mapping):
        return {"<answers>"}
    invalid = set()
    for key, value in layer.items():
        if type(key) is not str or key not in allowed:
            # An unrecognized key might contain free text. Do not send it to the renderer.
            invalid.add("<question>")
        elif not _valid_token(value, allowed[key]):
            invalid.add(key)
    return invalid


def _context_progress(layers):
    unknown, conflicting, missing = [], [], set()
    for qid, *_ in _CONTEXT:
        observed = {layer[qid] for layer in layers if qid in layer and type(layer[qid]) is str}
        if not observed:
            missing.add(qid)
        if "unknown" in observed:
            unknown.append(qid)
        if "conflicting" in observed or len(observed) > 1:
            conflicting.append(qid)
    return unknown, conflicting, missing


def _result(status, *, next_id=None, **diagnostics):
    return {
        "status": status,
        "next_question_ids": [next_id] if next_id else [],
        **{f"{key}_question_ids": list(diagnostics.get(key, ())) for key in _DIAGNOSTICS},
    }


def next_question(answers, *, context_answers=None, warning_state=None):
    """Return the next question or a stop, with IDs for unresolved answers.

    Pass trusted story facts as context_answers and, optionally, N's state
    string. A complete questionnaire still needs the engine's referral and
    confirmation checks. Missing questions never stand in for negative answers.
    """
    known = {} if context_answers is None else context_answers
    allowed = _answer_ids(question_catalogue())
    danger = evaluate_danger_signs(answers, known_answers=known)
    layers = tuple(layer for layer in (answers, known) if isinstance(layer, Mapping))
    context_unknown, context_conflicts, context_missing = _context_progress(layers)
    invalid = _invalid_answers(answers, allowed) | _invalid_answers(known, allowed)
    if warning_state is not None and not _valid_token(warning_state, _WARNING_STATES):
        invalid.add("<warning_state>")

    diagnostics = {
        "missing": danger["missing_question_ids"],
        "unknown": danger["unknown_question_ids"] + context_unknown,
        "conflicting": danger["conflicting_question_ids"] + context_conflicts,
        "invalid": sorted(invalid.union(danger["invalid_question_ids"])),
    }
    if "emergency_escalation" in (danger["state"], warning_state):
        return _result("escalated", **diagnostics)
    if diagnostics["invalid"]:
        return _result("invalid", **diagnostics)
    if diagnostics["missing"]:
        return _result("question", next_id=diagnostics["missing"][0], **diagnostics)
    if "more_information_needed" in (danger["state"], warning_state):
        return _result("needs_review", **diagnostics)

    if any(layer.get("context.age_group") == "child" or layer.get("context.pregnancy") == "pregnant"
           for layer in layers):
        return _result("unsupported", **diagnostics)

    for qid, *_ in _CONTEXT:
        if qid in context_unknown or qid in context_conflicts:
            return _result("needs_review", **diagnostics)
        if qid in context_missing:
            diagnostics["missing"] = [qid]
            return _result("question", next_id=qid, **diagnostics)
    return _result("complete", **diagnostics)


def edit_answers(answers, question_id, answer_id):
    """Replace or clear a visitor answer and discard all later visitor answers.

    Pass None to clear the edited answer. The caller clears confirmations and
    finder results and advances the revision, even after an edit back to the
    original value. Start with an empty answer mapping when the story changes.
    """
    allowed = _answer_ids(question_catalogue())
    if _invalid_answers(answers, allowed):
        raise ValueError("Cannot edit an invalid answer mapping")
    if type(question_id) is not str or question_id not in answers:
        raise ValueError("The edited question must already have a visitor answer")
    if answer_id is not None and not _valid_token(answer_id, allowed[question_id] - {"conflicting"}):
        raise ValueError("The replacement must be a selectable answer or None")

    order = list(allowed)
    index = order.index(question_id)
    prefix = {qid: answers[qid] for qid in order[:index] if qid in answers}
    if answer_id is not None:
        prefix[question_id] = answer_id
    return {
        "answers": prefix,
        "invalidated_question_ids": [qid for qid in order[index:] if qid in answers and qid not in prefix],
        "invalidate_confirmation": True,
        "invalidate_finder": True,
    }
