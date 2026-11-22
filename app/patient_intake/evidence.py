"""Provider-neutral validation of patient statements and evidence observations."""

from dataclasses import dataclass, field


PRESENCE = frozenset({"present", "absent", "unknown"})
TEMPORALITY = frozenset({"current", "historical", "unknown"})


def validate_verbatim_text(value, *, max_chars):
    """Check that a statement is nonempty and bounded, then return it unchanged."""
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("Invalid text limit")
    if type(value) is not str or len(value) > max_chars or not value.strip():
        raise ValueError("Enter a statement within the text limit")
    if any("\ud800" <= character <= "\udfff" for character in value):
        raise ValueError("Enter a statement with valid text")
    return value


@dataclass(frozen=True)
class Observation:
    """Candidate or confirmed fact content. The caller owns its provenance."""

    concept_id: str = field(repr=False)
    presence: str = field(repr=False)
    temporality: str = field(repr=False)

    def __post_init__(self):
        if type(self.concept_id) is not str or not self.concept_id.strip():
            raise ValueError("Invalid observation reference")
        if type(self.presence) is not str or self.presence not in PRESENCE:
            raise ValueError("Invalid observation presence")
        if type(self.temporality) is not str or self.temporality not in TEMPORALITY:
            raise ValueError("Invalid observation timing")


def conflicting_observation_indices(observations):
    """Identify explicit opposite observations for the same concept and timing.

    Observations with unknown timing cannot be assumed to refer to a current or
    historical event. Unknown presence stays unknown, even in a conflicting group.
    Indices preserve the caller's order and refer back to its provenance records.
    """
    observations = tuple(observations)
    polarities = {}
    for observation in observations:
        if type(observation) is not Observation:
            raise ValueError("Invalid observation")
        if observation.presence != "unknown":
            key = observation.concept_id, observation.temporality
            polarities.setdefault(key, set()).add(observation.presence)

    return tuple(
        index for index, observation in enumerate(observations)
        if observation.presence != "unknown"
        and polarities[(observation.concept_id, observation.temporality)] == {"present", "absent"}
    )


def validate_candidate(value, *, source_refs, max_label_chars):
    """Validate a provider's evidence proposal without affirming its contents."""
    fields = {"concept_id", "label", "presence", "temporality", "source_ref"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("This evidence proposal is unavailable")
    if type(value["source_ref"]) is not str or value["source_ref"] not in source_refs:
        raise ValueError("This evidence proposal does not match a current statement")
    observation = Observation(value["concept_id"], value["presence"], value["temporality"])
    validate_verbatim_text(observation.concept_id, max_chars=128)
    validate_verbatim_text(value["label"], max_chars=max_label_chars)
    return dict(value)


def review_candidate(candidate, decision, *, issuance_id, provider_question_id):
    """Record patient review separately from both provider inference and authority."""
    if decision not in ("confirm", "uncertain", "disagree"):
        raise ValueError("Choose an evidence review response")
    return {
        "candidate": dict(candidate),
        "decision": decision,
        "patient_presence": candidate["presence"] if decision == "confirm" else "unknown",
        "origin": "patient_review",
        "issuance_id": issuance_id,
        "provider_question_id": provider_question_id,
    }


def unresolved_evidence(reviews):
    """Keep disputed, uncertain and contradictory reviews visible for clarification."""
    if any(review["patient_presence"] == "unknown" or review["candidate"]["temporality"] == "unknown"
           for review in reviews):
        return True
    observations = (
        Observation(review["candidate"]["concept_id"], review["patient_presence"],
                    review["candidate"]["temporality"])
        for review in reviews
    )
    return bool(conflicting_observation_indices(observations))
