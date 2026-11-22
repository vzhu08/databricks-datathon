"""Review boundary between private campus evidence and patient navigation."""

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from datetime import date

# Databricks Apps runs with app/ as the project root. Repository tests also
# import this module through the app package.
if __package__ == "patient_intake":
    from ranking.evidence import MATCHERS
    from ranking.location import coordinates
    from ranking.urgency import rank_campuses
else:
    from ..ranking.evidence import MATCHERS
    from ..ranking.location import coordinates
    from ..ranking.urgency import rank_campuses


_SUPPORTED_SERVICES = tuple(MATCHERS)


def _has_reference(value):
    return isinstance(value, str) and bool(value.strip())


def _screen_reviewed_destinations(release, *, service, as_of, required=()):
    """Return private reviewed candidates keyed by campus ID.

    The server-side evidence loader must verify the release and its review
    records before passing them here. This is a defensive screen of that
    internal projection. Its return value contains private evidence references.
    An absent, stale or invalid release yields no usable candidates.
    """
    if (not isinstance(release, Mapping)
            or not _has_reference(release.get("release_ref"))
            or release.get("as_of") != as_of
            or not isinstance(release.get("campuses"), (tuple, list))):
        return {}

    rows = [
        row for row in release["campuses"]
        if isinstance(row, Mapping) and _has_reference(row.get("facility_id"))
    ]
    counts = Counter(row["facility_id"] for row in rows)
    reviewed = {}
    for row in rows:
        campus_id = row["facility_id"]
        if (counts[campus_id] != 1
                or row.get("coordinate_status") != "reviewed"
                or coordinates(row) is None
                or not all(_has_reference(row.get(field)) for field in (
                    "campus_review_ref", "coordinate_review_ref", "display_permission_ref"
                ))):
            continue
        services = row.get("services")
        decision = services.get(service) if isinstance(services, Mapping) else None
        if not isinstance(decision, Mapping) or not _has_reference(decision.get("service_review_ref")):
            continue
        # Treat a closed site as ineligible. Leave unknown or unverified
        # availability to a separate, independently reviewed contact check.
        if decision.get("availability") == "unavailable":
            continue
        reviewed[campus_id] = row

    # Neutral travel makes the probe an eligibility check. Keep neither its
    # scores nor its leads, and carry the original review records forward.
    if not reviewed:
        return {}
    try:
        probe = rank_campuses(
            service, "routine", [{**row, "distance_km": 0} for row in reviewed.values()],
            as_of=as_of, required=required, travel_metric="distance_km", travel_budget=1, limit=None,
        )
    except ValueError:
        return {}
    return {row["facility_id"]: deepcopy(reviewed[row["facility_id"]]) for row in probe["ranked"]}


def _is_current(handle, expected_revision, assessment):
    revision, record = handle.read()
    return (
        type(expected_revision) is int
        and isinstance(assessment, dict)
        and assessment.get("state") == "completed"
        and assessment.get("revision") == revision == expected_revision
        and record.get("state") == "completed"
        and record.get("assessment") == assessment
    )


class PatientHandoff:
    """Server-side callback for a completion already confirmed by the runtime.

    The optional order reader must independently verify clinician authority
    scoped to this exact encounter and revision. The release reader must
    authenticate a private evidence release for the given evaluation date.
    Both ports are unset in the default composition. This callback does not
    acquire an origin or send coordinates.
    """

    def __init__(self, *, read_verified_order=None, read_reviewed_release=None, today=date.today):
        self._read_order = read_verified_order
        self._read_release = read_reviewed_release
        self._today = today

    def __call__(self, handle, expected_revision, assessment):
        if not _is_current(handle, expected_revision, assessment):
            return {"state": "assessment_blocked"}
        if assessment.get("urgency") == "self_care" and assessment.get("next_step") is None:
            return {"state": "no_reviewed_destination"}
        next_step = assessment.get("next_step")
        if (assessment.get("urgency") != "consultation"
                or not isinstance(next_step, dict) or next_step.get("kind") != "consultation"):
            return {"state": "assessment_blocked"}
        if self._read_order is None or self._read_release is None:
            return {"state": "no_reviewed_destination"}

        try:
            order = self._read_order(handle, expected_revision)
        except Exception:
            return {"state": "navigation_unavailable"}
        if order is None:
            return {"state": "no_reviewed_destination"}
        if not isinstance(order, Mapping) or order.get("service") not in _SUPPORTED_SERVICES:
            return {"state": "unsupported_service"}

        # A concurrent edit may have invalidated the order lookup.
        if not _is_current(handle, expected_revision, assessment):
            return {"state": "assessment_blocked"}
        as_of = self._today().isoformat()
        try:
            candidates = _screen_reviewed_destinations(
                self._read_release(as_of), service=order["service"], as_of=as_of,
                required=order["required_capabilities"],
            )
        except Exception:
            return {"state": "navigation_unavailable"}
        if not _is_current(handle, expected_revision, assessment):
            return {"state": "assessment_blocked"}
        if not candidates:
            return {"state": "no_reviewed_destination"}

        # Return only the approved display identifier. Release evidence and
        # coordinates stay server-side. Eligibility does not establish a slot.
        return {
            "state": "reviewed_destinations",
            "destinations": [{"facility_id": campus_id, "availability": "unknown"}
                             for campus_id in sorted(candidates)],
        }
