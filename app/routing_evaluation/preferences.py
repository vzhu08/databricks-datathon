"""Validate a frozen preference bundle and compute the common eligible pool."""

from collections.abc import Mapping

from app.ranking.urgency import rank_campuses

FEATURES = ("travel", "recency", "corroboration", "preferred")
SERVICES = ("dialysis", "mri", "trauma_care")
RATINGS = ("left", "right", "tie", "abstain")


def _id(value, field):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} requires a nonempty, trimmed string")
    return value


def _ids(values, field):
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    result = [_id(value, field) for value in values]
    if len(result) != len(set(result)):
        raise ValueError(f"Duplicate ID in {field}")
    return result


def _reviews(reviews, eligible):
    if not isinstance(reviews, list):
        raise ValueError("reviews must be a list")
    reviewers = set()
    for review in reviews:
        if not isinstance(review, Mapping) or not isinstance(review.get("preferences"), list):
            raise ValueError("Each reviewer supplies a preferences list")
        reviewer = _id(review["reviewer_id"], "reviewer_id")
        if reviewer in reviewers:
            raise ValueError("Duplicate reviewer in a scenario")
        reviewers.add(reviewer)
        acceptable = review["acceptable_ids"]
        if acceptable is not None and not set(_ids(acceptable, "acceptable_ids")) <= eligible:
            raise ValueError("An acceptable destination is outside the eligible pool")
        pairs = set()
        for pair in review["preferences"]:
            left, right = pair["left"], pair["right"]
            key = frozenset((left, right))
            if len(key) != 2 or not key <= eligible or key in pairs:
                raise ValueError("Invalid, ineligible, or repeated reviewer pair")
            pairs.add(key)
            if pair["choice"] not in RATINGS:
                raise ValueError("Unknown pairwise preference")
    return reviews


def prepare(bundle):
    if not isinstance(bundle, Mapping) or not isinstance(bundle.get("scenarios"), list):
        raise ValueError("Expected a preference bundle with a scenarios list")
    if bundle.get("schema_version") != "routing-preferences-v1":
        raise ValueError("Unsupported preference bundle")
    if bundle.get("label_basis") not in ("human_blinded", "synthetic"):
        raise ValueError("Declare human_blinded or synthetic label basis")
    if type(bundle.get("geography_holdout", False)) is not bool:
        raise ValueError("geography_holdout must be boolean")
    _id(bundle.get("freeze_id"), "freeze_id")
    cases = []
    ids = set()
    # A connected scenario/campus/copy group must have one bootstrap cluster and split.
    owners = {}
    for case in bundle["scenarios"]:
        if not isinstance(case, Mapping) or not isinstance(case.get("candidates"), list):
            raise ValueError("Each scenario must supply a candidate list")
        case_id = _id(case["id"], "scenario ID")
        if case_id in ids:
            raise ValueError("Duplicate scenario ID")
        ids.add(case_id)
        split = case["split"]
        if split not in ("train", "test"):
            raise ValueError("Assign every scenario a frozen train/test split")
        cluster = _id(case["cluster_id"], "cluster_id")
        geography = _id(case["geography"], "geography")
        groups = [("cluster", cluster), ("scenario", _id(case["scenario_group"], "scenario_group"))]
        for candidate in case["candidates"]:
            groups.append(("facility", _id(candidate["facility_id"], "facility_id")))
            groups.append(("campus", _id(candidate["campus_group"], "campus_group")))
            sources = _ids(candidate["source_groups"], "source_groups")
            if not sources:
                raise ValueError("Supply source/copy group identities for every candidate")
            groups.extend(("source", source) for source in sources)
        for group in groups:
            if owners.setdefault(group, (split, cluster)) != (split, cluster):
                raise ValueError(f"Leakage: {group[0]} group crosses a split or bootstrap cluster")
        request = case["request"]
        if not isinstance(request, Mapping) or "limit" in request or "candidates" in request:
            raise ValueError("Evaluation supplies the full candidate pool and limit")
        ranked = rank_campuses(candidates=case["candidates"], limit=None, **request)["ranked"]
        rows = {row["facility_id"]: row for row in ranked}
        reviews = _reviews(case["reviews"], set(rows))
        cases.append({"id": case_id, "split": split, "cluster": cluster, "geography": geography,
                      "service": request["service"], "urgency": request["urgency"],
                      "travel_metric": request["travel_metric"],
                      "rows": rows, "reviews": reviews})
    return cases
