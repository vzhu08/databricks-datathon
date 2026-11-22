"""Run the competition notebook's fixed, local-only synthetic demonstration."""

import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def block_network(event, _args):
    if event.startswith("socket.") and event != "socket.__new__":
        raise RuntimeError(f"Network disabled in the submitted demonstration: {event}")


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    sys.addaudithook(block_network)
    sys.path.insert(0, str(ROOT))

    from app import national_directory, storm_page, storm_plan
    from app.find_care import claim_view, data_mode, present, withheld, withheld_summary
    from app.finding_provenance import project_find_care
    from app.ranking import search_facilities
    from app.intake.__main__ import load_journeys, replay_journey
    from app.facility_evidence_demo import area, care_decision, loader
    from app.simulation.replay import replay
    from app.simulation.scenario import make_scenario
    from app.storm_ui import build, build_ask, build_finder, build_intake

    try:
        national_directory.load(ROOT / "app")
    except national_directory.Unavailable:
        pass
    else:
        raise RuntimeError("The offline notebook must keep the deployment-only directory input separate")

    require(data_mode({"FIND_CARE_DATA": "demo"})["mode"] == "demo", "Expected demo mode")
    require(data_mode({"FIND_CARE_DATA": "warehouse"})["mode"] == "setup",
            "A missing warehouse must not fall through to fixtures")
    facilities = load("app/demo_facilities.json")
    require(facilities == load("contracts/fixtures/search.json") and len(facilities["facilities"]) == 6,
            "The shipped synthetic catalogue must match the search fixture")
    request = {"service": "dialysis", "location": {"city": "Jaipur", "state": "Rajasthan"}, "radius_km": 50}
    answer = search_facilities(**request, facilities=facilities["facilities"])
    require(answer["status"] == "ok" and bool(answer["direct_results"]), "No direct synthetic result")
    winner = answer["direct_results"][0]
    require(winner["name"] == "Example Regional Hospital" and winner["evidence_field"] == "procedures"
            and round(winner["distance_km"], 1) == 6.7 and winner["availability"] == "unknown",
            "Unexpected finder result, evidence or availability")
    require([row["facility_id"] for row in answer["direct_results"]] == ["demo-north", "demo-south"],
            "Unexpected synthetic result order")
    view = present(answer, **request)
    mapped = project_find_care(answer, request["service"], mode="demo")
    direct_claims = claim_view(mapped["findings"][0], request["service"], view["top"]["place"])
    require(direct_claims["location"]["line"].startswith("Reported as a map point") and
            direct_claims["service"]["line"].startswith("Unconfirmed") and
            direct_claims["service"]["sources"][0]["publisher"] == "Synthetic demo record",
            "The integrated provenance view must show distinct synthetic claims")

    nearby = {"service": "dialysis", "location": {"pin": "302001"}, "radius_km": 2}
    lead_answer = search_facilities(**nearby, facilities=facilities["facilities"])
    require(lead_answer["status"] == "needs_confirmation" and
            [row["facility_id"] for row in lead_answer["indirect_leads"]] == ["demo-near"],
            "Expected the related-only synthetic control")
    lead_view = present(lead_answer, **nearby)
    mapped_lead = project_find_care(lead_answer, nearby["service"], mode="demo")["findings"][0]
    related = claim_view(mapped_lead, nearby["service"], lead_view["leads"][0]["place"])["service"]
    require(mapped_lead["service"]["strength"] == "no_evidence" and related["sources"][0]["role"].startswith("Context"),
            "Related wording must remain contextual")
    restricted = withheld(answer)
    require(restricted["status"] == "withheld" and
            not any(restricted[field] for field in ("direct_results", "indirect_leads", "location_choices")),
            "The warehouse display gate must discard row results")
    mapped_summary = project_find_care(restricted, request["service"], mode="warehouse")["summary"]
    restricted_claim = withheld_summary(mapped_summary, request["service"])
    require(restricted_claim["state"] == "Unconfirmed" and winner["name"] not in str(restricted_claim),
            "The warehouse provenance view must stay at result level")

    from research.acquisition.national_facility_evidence.finding_examples import examples

    provenance = examples()
    direct, backup = provenance["demo_50_km"]["findings"]
    lead, = provenance["demo_2_km"]["findings"]
    withheld_mapping = provenance["withheld_shape_50_km"]
    require(direct["location"]["precision"] == "reported_position"
            and direct["service"]["decision"] == "unconfirmed"
            and direct["service"]["sources"][0]["field"] == "procedures"
            and backup["service"]["sources"][0]["field"] == "capabilities"
            and lead["service"]["sources"][0]["role"] == "context"
            and withheld_mapping["findings"] == []
            and withheld_mapping["summary"]["independent_supporting_origins"] is None,
            "The integrated mapper must preserve claim scope and the warehouse display boundary")

    journeys, _ = load_journeys()
    runs = [replay_journey(journeys, name) for name in journeys["journeys"]]
    require(len(runs) == 7, "Expected the seven fictional intake journeys")
    finder_steps = sum(step["finder"] is not None for run in runs for step in run["transitions"])
    warning = next(run for run in runs if run["journey_id"] == "warning_overrides_plan")
    require(finder_steps > 0 and warning["transitions"][-1]["finder"] is None,
            "An emergency journey must not dispatch the facility finder")

    def evidence_fixture(module, name):
        path = ROOT / "tests" / "facility_evidence_demo" / name
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
        result = module.load({module.PATH_SETTING: str(path)}, expected_sha256=pin)
        require(result["status"] == "ok" and result["synthetic"], "Cleared synthetic schema fixture required")
        return result

    display = evidence_fixture(loader, "synthetic_display.json")
    national_area = evidence_fixture(area, "synthetic_area.json")
    care_request = {"concern": "dialysis", "severity": "moderate", "urgency": "soon", "danger": "no"}
    decision = care_decision.evaluate(care_request, display, national_area)
    require(decision["status"] == "no_reviewed_destination" and decision["eligible_destinations"] == 0,
            "Unreviewed evidence must produce zero eligible destinations")
    with patch.object(care_decision, "_loaded", side_effect=AssertionError("Emergency read evidence")):
        emergency = care_decision.evaluate({"danger": "yes"}, display, national_area)
    require(emergency["action"] == "interrupt" and emergency["evidence"] is None,
            "The emergency path must stop before evidence")

    storm = replay(make_scenario("storm", 17), 10)
    require(json.loads(json.dumps(storm)) == load("contracts/fixtures/storm_replay.json"), "Storm replay differs from the fixture")
    nearest, scarcity = (storm["policies"][name] for name in ("nearest_first", "scarcity_aware"))
    require((nearest["metrics"]["assigned"], scarcity["metrics"]["assigned"],
             scarcity["events"][0]["extra_travel_minutes"]) == (7, 8, 4), "Unexpected storm outcomes")

    page_summary = storm_page.headline(storm_page.bundle())
    frame = storm_page.document()
    require(page_summary["synthetic"] and [item["served"] for item in page_summary["policies"]] == [7, 8]
            and "data:font/woff2;base64," in frame and "<script src=" not in frame,
            "The hosted Storm frame must be self-contained and use the pinned replay")
    batch = batch_comparison(storm_plan)

    browser_bundles = {
        "scenarios.js": build,
        "answers.js": build_ask,
        "finder_examples.js": build_finder,
        "intake.js": build_intake,
    }
    for name, builder in browser_bundles.items():
        path = ROOT / "app" / "storm_ui" / "data" / name
        require(builder.render() == path.read_text(encoding="utf-8"), f"Browser bundle drift: {name}")
    routes = build_finder.bundle()
    require(routes["synthetic"] and len(routes["examples"]) == 9, "Expected nine stand-in travel responses")

    sys.path.insert(0, str(ROOT / "databricks" / "enrichment"))
    try:
        from common import canonical, digest
        from coverage import coverage
        from occurrence_keys import POLICY, SOURCE, map_occurrences

        sample = [
            {"unique_id": "001", "name": "Fictional sparse original"},
            {"unique_id": "002", "name": "Fictional repeated original",
             "description": "Example Campus offers onsite MRI. All dialysis patients are referred elsewhere."},
            {"unique_id": "002", "name": "Fictional repeated original",
             "description": "Example Campus offers onsite MRI. All dialysis patients are referred elsewhere."},
        ]
        base, groups = map_occurrences(sample, "unique_id", SOURCE, 0, POLICY)
        require(len({row["facility_id"] for row in base}) == 3 and groups[0]["multiplicity"] == 2
                and sorted((row["source_row"] for row in base), key=canonical) == sorted(sample, key=canonical)
                and map_occurrences(list(reversed(sample)), "unique_id", SOURCE, 0, POLICY) == (base, groups),
                "Occurrence mapping must preserve duplicates and be stable after reordering")

        enrichment = coverage(load("contracts/fixtures/enrichment.json"),
                              load("contracts/fixtures/enrichment_base.json"), "2026-11-21")
        require(enrichment["base"]["denominator"] == 2, "Unexpected synthetic coverage denominator")
    finally:
        sys.path.pop(0)

    from research.service_status.projection import lookup, project

    as_of = "2026-11-21"
    base_pin = digest(base)
    meta = {"mapping": {"id": "unique_id"}, "row_count": 3, "original_table": SOURCE,
            "observed_delta_version": 0, "base_file_sha256": base_pin}
    claims = project(base, meta, [], [], as_of=as_of, base_file_sha256=base_pin, checked_sources=["synthetic"])
    require(claims["decision_count"] == 9 and all(item["unconfirmed"] == 3 for item in claims["coverage"].values()),
            "All nine decisions must survive on the three synthetic originals")
    reviewed_id, unreviewed_twin_id = groups[0]["facility_ids"]
    original = lookup(claims, reviewed_id)
    exact_text = next(row["source_row"]["description"] for row in base if row["facility_id"] == reviewed_id)
    require(original["services"]["mri"]["status"] == "unconfirmed", "Original wording alone cannot promote")
    reviews = []
    for service, kind, phrase in (
        ("mri", "onsite_service", "Example Campus offers onsite MRI."),
        ("dialysis", "referral_only", "All dialysis patients are referred elsewhere."),
    ):
        start = exact_text.index(phrase)
        reviews.append({
            "facility_id": reviewed_id, "service": service, "review_id": f"synthetic-{service}",
            "finding": kind, "assessed_for": as_of, "reviewer": "fictional reviewer",
            "reviewed_at": as_of + "T18:00:00Z",
            "source": {"kind": "original", "field": "description", "start": start, "end": start + len(phrase),
                       "excerpt": phrase, "source_date": "2026-11-18", "source_family": "synthetic-publisher"},
        })
    reviewed = project(base, meta, reviews, [], as_of=as_of, base_file_sha256=base_pin, checked_sources=["synthetic"])
    reviewed_status = {service: item["status"] for service, item in lookup(reviewed, reviewed_id)["services"].items()}
    require(reviewed["decision_count"] == 9 and reviewed_status == {"mri": "yes", "dialysis": "no", "trauma_care": "unconfirmed"}
            and lookup(reviewed, unreviewed_twin_id)["services"]["mri"]["status"] == "unconfirmed",
            "Synthetic adjudication must apply only to the reviewed occurrence and service")

    result = {
        "synthetic": True,
        "find_care": {
            "request": request,
            "facility": winner["name"],
            "straight_line_km": round(winner["distance_km"], 1),
            "evidence": {"publisher": "Synthetic demo record", "field": winner["evidence_field"],
                         "statement": winner["evidence_excerpt"]},
            "availability": winner["availability"],
            "warehouse_display": restricted["status"],
            "nearby_alternative": {"facility": view["backups"][0]["name"], "campus": "South Campus",
                                   "straight_line_km": round(view["backups"][0]["distance_km"], 1),
                                   "field": view["backups"][0]["field"], "statement": view["backups"][0]["excerpt"]},
            "explanation": {claim: direct_claims[claim]["line"] for claim in ("location", "service")},
            "ranking_reason": view["why"],
            "verification": [direct_claims[claim]["missing_check"] for claim in ("location", "service")],
            "integrated_provenance": {
                "location": mapped["findings"][0]["location"]["strength"],
                "requested_service": mapped["findings"][0]["service"]["decision"],
                "related_service": mapped_lead["service"]["strength"],
                "withheld_summary": restricted_claim["state"],
            },
            "provenance_mapper": {
                "direct_findings": len(provenance["demo_50_km"]["findings"]),
                "related_findings": len(provenance["demo_2_km"]["findings"]),
                "withheld_findings": len(withheld_mapping["findings"]),
            },
        },
        "intake": {"fictional_journeys": len(runs), "finder_steps": finder_steps, "warning_stops_finder": True},
        "judge_walkthrough": {
            "service": decision["service"], "eligible_destinations": decision["eligible_destinations"],
            "ordinary_workflow_priority": decision["workflow_urgency"], "warning_action": emergency["action"],
        },
        "storm": {"requested": 8, "nearest_assigned": nearest["metrics"]["assigned"],
                  "scarcity_assigned": scarcity["metrics"]["assigned"],
                  "first_scarcity_detour_minutes": scarcity["events"][0]["extra_travel_minutes"]},
        "storm_batch": batch,
        "offline_browser_data": {"bundles_verified": sorted(browser_bundles), "synthetic_travel_examples": len(routes["examples"])},
        "enrichment": {"synthetic_base_rows": enrichment["base"]["denominator"],
                       "table_counts": enrichment["table_counts"],
                       "duplicate_preserving_originals": len(base),
                       "reviewed_synthetic_service_status": reviewed_status,
                       "occurrence_service_decisions": reviewed["decision_count"]},
    }

    if (ROOT / "app/capacity_recommendation.py").is_file():
        from app.capacity_recommendation import demo_capacity_inputs, recommend_capacity

        capacity_request, snapshot = demo_capacity_inputs()
        recommendation = recommend_capacity(capacity_request, snapshot)
        require(recommendation.get("chosen") and recommendation.get("fastest"), "Capacity preview failed")
        result["capacity_preview"] = {"chosen": recommendation["chosen"], "fastest": recommendation["fastest"]}

        if (ROOT / "app/travel/hosted.py").is_file():
            from app.travel.hosted import demo_car_travel
            from app.travel.tomtom import from_environment

            provider = from_environment({})
            try:
                options = {"origin_id": snapshot["origin_id"], "provider": provider}
                travel = demo_car_travel(capacity_request, snapshot, **options)
                expected_ids = {row["facility_id"] for row in snapshot["candidates"]}
                require(set(travel) == expected_ids and all(
                    row["status"] == "unavailable" and row["minutes"] is None for row in travel.values()
                ), "Disabled hosted routing must return no times for any candidate")
                require(demo_car_travel({**capacity_request, "emergency": True}, snapshot, **options) == {},
                        "Emergency must skip hosted routing")
            finally:
                provider.close()
            result["hosted_travel"] = {"candidate_count": len(travel), "estimates_available": 0,
                                       "provider": "disabled", "emergency_skipped": True}

    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def batch_comparison(storm_plan):
    from app.simulation.batch_planner import make_instance, neutral_instance, solve

    instance = make_instance(seed=17)
    plan = storm_plan.checked(solve(instance))
    require(not storm_plan.real(plan), "The generated control must be labeled synthetic")
    neutral = solve(neutral_instance(instance))
    policies = plan["policies"]
    names = ("assigned", "unmet", "by_priority", "total_travel_seconds", "unserved_reasons")
    metrics = {name: {key: output["metrics"][key] for key in names} for name, output in policies.items()}
    for name in policies:
        require(all(neutral["policies"][name]["metrics"][key] == metrics[name][key] for key in names[:4]),
                "Neutral replay changed the allocation objective")
    first, exact = (policies[key] for key in ("nearest_first", "exact_optimum"))
    require((len(plan["patients"]), len(first["assignments"]), len(exact["assignments"])) == (120, 115, 120),
            "Unexpected seed-17 control outcomes")
    nearest = {row["patient"]: row for row in first["assignments"]}
    optimal = {row["patient"]: row for row in exact["assignments"]}
    cohort = sorted(nearest.keys() & optimal.keys())
    patient = "sim-013"
    moved = "sim-007"
    reason = next(row["reason"] for row in first["unserved"] if row["patient"] == patient)
    slot = next(row for row in first["metrics"]["resources_used"] if row["slot_id"] == optimal[patient]["slot_id"])
    require(reason == "compatible_slots_exhausted" and slot["used"] == slot["slots"] == 1
            and nearest[moved]["slot_id"] == slot["slot_id"] and optimal[moved]["slot_id"] != slot["slot_id"],
            "The example must demonstrate a shared staffed-slot constraint")
    priorities = {row["id"]: row["priority"] for row in plan["patients"]}
    require(priorities[patient] == "highest" and priorities[moved] == "routine", "Unexpected case priorities")
    return {
        "geography": plan["geography"]["name"], "scenario": plan["scenario"], "requested": len(plan["patients"]),
        "sites": len(plan["facilities"]), "policies": metrics, "case": {
            "rescued": optimal[patient], "reason": reason, "slot_capacity": slot["slots"],
            "moved_nearest": nearest[moved], "moved_exact": optimal[moved],
        },
        "shared_travel": {"cohort": len(cohort),
                          "nearest_first_seconds": sum(nearest[key]["travel_seconds"] for key in cohort),
                          "exact_optimum_seconds": sum(optimal[key]["travel_seconds"] for key in cohort)},
    }


if __name__ == "__main__":
    raise SystemExit(main())
