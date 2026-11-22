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
