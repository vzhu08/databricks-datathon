"""Invented reviewer preferences for exercising the interface without clinical labels."""

from .preferences import SERVICES


def synthetic_bundle():
    cases = []
    for i in range(12):
        scenario_id = f"smoke-{i:02}"
        service = SERVICES[i % len(SERVICES)]
        urgency = ("routine", "time_sensitive", "highest")[i % 3]
        candidates = []
        for suffix, travel, dated in (("near", 8, "2025-11-01"), ("far", 14, "2026-10-01")):
            fid = f"{scenario_id}-{suffix}"
            candidates.append({
                "facility_id": fid, "campus_group": fid, "source_groups": [f"{fid}-origin"],
                "as_of": "2026-11-01", "travel_minutes": travel,
                "services": {service: {"status": "yes", "source_date": dated,
                                       "independent_families": [f"{fid}-origin"],
                                       "capabilities": {"requested_option": "yes" if suffix == "far" else "no"}}}})
        left, right = [c["facility_id"] for c in candidates]
        choice = "left" if urgency == "highest" else "right"
        reviews = []
        for reviewer in ("synthetic-reviewer-A", "synthetic-reviewer-B"):
            reviews.append({"reviewer_id": reviewer,
                            "preferences": [{"left": left, "right": right, "choice": choice}],
                            "acceptable_ids": [left if choice == "left" else right]})
        cases.append({"id": scenario_id, "scenario_group": scenario_id, "cluster_id": scenario_id,
                      "split": "train" if i < 6 else "test", "geography": "fictional-region",
                      "request": {"service": service, "urgency": urgency, "as_of": "2026-11-01",
                                  "travel_metric": "travel_minutes", "travel_budget": 40,
                                  "preferred": ["requested_option"]},
                      "candidates": candidates, "reviews": reviews})
    return {"schema_version": "routing-preferences-v1", "label_basis": "synthetic",
            "freeze_id": "invented-interface-control", "scenarios": cases}
