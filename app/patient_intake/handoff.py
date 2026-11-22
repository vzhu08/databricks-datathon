"""Review boundary between private campus evidence and patient navigation."""

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy

# Databricks Apps runs with app/ as the project root. Repository tests also
# import this module through the app package.
if __package__ == "patient_intake":
    from ranking.location import coordinates
    from ranking.urgency import rank_campuses
else:
    from ..ranking.location import coordinates
    from ..ranking.urgency import rank_campuses


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
