"""Build the display-only real-evidence handoff for #252 from pinned receipts."""

import argparse
import json
from pathlib import Path

from research.matching.common import file_digest

ISSUES = "https://github.com/vzhu08/databricks-datathon/issues"
PIB = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2306323&lang=2&reg=48"
EARLIER_PIB = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1680350"
ESIC = "https://mchyderabad.esic.gov.in/attachments/circularfile/c5dd5062449cb824d950ae94ecb923cc.pdf"
PILOT_RECEIPT = f"{ISSUES}/221#issuecomment-7076224239"
TRACE_RECEIPT = f"{ISSUES}/58#issuecomment-7075721205"
DISPLAY_AUTHORITY = f"{ISSUES}/239#issuecomment-7076347002"
PILOT_PIN = "b437f13e68f4185f603dadd918ee14a0bbb8137bc20c1ae34aa8a88421001c45"
TRACE_PIN = "451f05b1eb4007a15707363d3da9faf623df0158e73be6d8ae136e42161b5f5b"
OPERATOR_PIN = "d36215df7fd5799595d150214c28433f818fac2070591a2a7e289d64ff1b6b88"


def read(path, expected):
    if file_digest(path) != expected:
        raise ValueError(f"Unexpected digest for {path.name}")
    return json.loads(path.read_bytes())


def pin(path):
    return {"bytes": path.stat().st_size, "sha256": file_digest(path)}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def display(pilot_path, trace_path, operator_path):
    pilot = read(pilot_path / "manifest.json", PILOT_PIN)
    source = read(pilot_path / "source-summary.json", pilot["files"]["source-summary.json"]["sha256"])
    comparison = read(pilot_path / "comparison-summary.json", pilot["files"]["comparison-summary.json"]["sha256"])
    trace_manifest = read(trace_path / "manifest.json", TRACE_PIN)
    trace = read(trace_path / "aggregate.json", trace_manifest["files"]["aggregate.json"]["sha256"])
    operator = read(operator_path / "manifest.json", OPERATOR_PIN)
    operator_members = {r["path"]: r["sha256"] for r in operator["files"]}
    quantities = read(operator_path / "pib-quantities.json", operator_members["pib-quantities.json"])
    releases = read(operator_path / "pib-release-bodies.json", operator_members["pib-release-bodies.json"])
    release, = (r for r in releases if r["source_url"] == PIB)
    selected = [r for r in quantities if r["source_url"] == PIB and
                r["service"] in {"dialysis", "haemodialysis_activity"}]
    if len(selected) != 2 or any(r["scope"] != "pooled_twin_hospitals" for r in selected):
        raise ValueError("PIB measures must be unique, source-attributed and scoped to the twin hospitals")
    beds, = (r for r in selected if r["service"] == "dialysis" and r["unit"] == "beds")
    activity, = (r for r in selected if r["service"] == "haemodialysis_activity" and r["unit"] == "patients")

    population = trace["population"]
    trace_counts = trace["all_services"]
    same_osm = trace_counts["selected_osm_only"] + trace_counts["selected_osm_and_other_retained_site"]
    if (population["originals"], population["decisions"], population["campus_located_keys_traced"], same_osm) != (
            comparison["vf_occurrences"], sum(comparison["decisions"].values()), 52, 7):
        raise ValueError("Unexpected trace population")
    if (trace["clinical"]["reviewed_onsite_pairs_in_input"] or
            trace["documented_independent_same_premises_bindings"] or
            source["premises_with_explicit_dated_onsite_claim"]):
        raise ValueError("Eligibility disposition requires a new display review")

    return {
        "schema": "issue-239-judge-display-v1",
        "audience": "Datathon judge walkthrough. Release only the fields in this document.",
        "national": {
            "dataset": "Virtue Foundation facilities, Delta version 0",
            "baseline_decisions_as_of": "2026-11-21",
            "occurrences": comparison["vf_occurrences"],
            "distinct_upstream_ids": comparison["vf_unique_upstream_ids"],
            "occurrence_service_decisions": population["decisions"],
            "unconfirmed_occurrence_service_decisions": population["unconfirmed"],
            "unknown_national_accuracy": True,
            "issuer_pilot": {
                "scope": "National NABH dialysis programme listing screen, snapshot 2026-11-22",
                "issuer_listings_screened": source["listing_occurrences_screened"],
                "programme_mentions": source["dialysis_candidate_listings"],
                "distinct_printed_premises_keys": source["unique_issuer_name_address_premises"],
                "listings_with_unresolved_postal_context": source["candidate_listings_with_insufficient_structured_postal_context"],
                "exact_vf_links": comparison["vf_link_dispositions"]["exact_directory_text"],
                "dated_onsite_claims": source["premises_with_explicit_dated_onsite_claim"],
                "source": PILOT_RECEIPT,
            },
        },
        "vf_trace_case": {
            "grain": "Occurrence/service keys. The cohort has 52 keys on 50 originals.",
            "national_external_lead_keys": population["national_external_lead_keys"],
            "campus_located_lead_keys": population["campus_located_keys_traced"],
            "exact_shared_osm_object_keys": same_osm,
            "same_osm_by_service": {r["service"]: r["selected_osm_only"] + r["selected_osm_and_other_retained_site"]
                                    for r in trace["by_service"]},
            "exact_object_associations_by_field": trace["selected_osm_association_field_counts"],
            "cohort_candidate_associations": trace["trace_integrity"]["candidate_associations"],
            "cohort_associations_with_service_observation_date":
                trace["trace_integrity"]["associations_with_known_service_observation_date"],
            "keys_with_another_retained_site_group":
                trace_counts["other_retained_site_only"] + trace_counts["selected_osm_and_other_retained_site"],
            "explicit_competing_branch_bindings": trace["explicit_competing_branch_bindings_at_selected_directory_grain"],
            "missing_branch_crosswalk_keys": trace_counts["missing_branch_crosswalk"],
            "independent_same_premises_bindings": trace["documented_independent_same_premises_bindings"],
            "reviewed_onsite_pairs": trace["clinical"]["reviewed_onsite_pairs_in_input"],
            "map_snapshots": ["2026-10-09", "2026-11-01"],
            "same_origin_family": "OpenStreetMap",
            "point_precision": "A directory selection and service lead reference the same typed map object. Branch or entrance precision remains unverified.",
            "source": TRACE_RECEIPT,
        },
        "public_case": {
            "name": "ESIC Sanath Nagar complex, Hyderabad",
            "buildings_named_in_pib": ["ESIC Medical College & Hospital", "Super Speciality Hospital"],
            "has_documented_vf_occurrence_link_in_this_case": False,
            "has_documented_nabh_pilot_link_in_this_case": False,
            "publisher": "Press Information Bureau, ESIC briefing",
            "release_date": release["publication_date"],
            "source": PIB,
            "known_at_shared_campus": [
                {"value": beds["quantity"], "unit": "reported dialysis beds", "period": beds["observation_period"],
                 "locator": "2026 PIB release, campus infrastructure paragraph; exact observation period unstated"},
                {"value": activity["quantity"], "unit": "insured patients reported as benefiting from haemodialysis",
                 "period": activity["observation_period"], "locator": "2026 PIB release, nephrology activity paragraph"},
            ],
            "added_historical_branch_evidence": {
                "building": "ESIC Medical College & Hospital",
                "event": "In-house dialysis service dedication",
                "event_date": "2020-12-12",
                "publication_date": "2020-12-13",
                "source": EARLIER_PIB,
                "same_operator_lineage": "ESIC",
            },
            "shared_address_source_reference": ESIC,
            "shared_address_display": None,
            "current_building_level_onsite_status": None,
            "entrance": None,
            "current_staffed_capacity": None,
            "travel_minutes": None,
        },
        "decision": {
            "point_rank": {"status": "abstain", "eligible_destinations_in_cases": 0, "scores": None},
            "quality_penalty": {"status": "not_computed", "provenance": "Count the shared OSM lineage once.",
                                "recency": "Map snapshot dates do not date service.",
                                "conflict": "Another retained group is a branch lead; explicit branch binding is absent."},
            "range_rank": {"status": "not_computable", "score_range": None,
                           "reason": "No measured branch travel ranges or equivalent branch-level operational quantities."},
            "verify": {"status": "planning_leads_and_specific_verification",
                       "highest_value_fact": "A current, dated operator statement naming the exact physical branch or entrance and confirming onsite delivery of the requested service there."},
            "evaluation": {"scored_requests": 0, "wrong_branch_rate": None,
                           "unsupported_service_rate": None, "unstable_winner_rate": None,
                           "measured_deferral_cost": None},
        },
    }


def build(pilot, trace, operator, out):
    payload = display(pilot, trace, operator)
    out.mkdir(parents=True, exist_ok=False)
    write(out / "display.json", payload)
    write(out / "manifest.json", {
        "edition": "issue-239-judge-display-v1",
        "authority": DISPLAY_AUTHORITY,
        "audience": payload["audience"],
        "approved_fields": {
            "national": "VF and issuer national counts and derived denominators",
            "vf_trace_case": "Frozen national-cohort counts, source fields and aggregate lineages",
            "public_case": "Attributed PIB facts and an official-address document link",
            "decision": "Research-only policy outcomes and explicit missing measures",
        },
        "custody": "Private source records, identifiers, address cells, map points and provider-level crosswalks omitted.",
        "inputs": {
            "issue_221_manifest": {"sha256": PILOT_PIN, "source": PILOT_RECEIPT},
            "issue_58_trace_manifest": {"sha256": TRACE_PIN, "source": TRACE_RECEIPT},
            "operator_manifest": {"sha256": OPERATOR_PIN, "source": f"{ISSUES}/143#issuecomment-7074691844"},
            "pib_copyright_policy": "https://www.pib.gov.in/ContentPage.aspx?lang=8&menuid=597&reg=20",
            "pib_historical_branch_source": EARLIER_PIB,
        },
        "generator": pin(Path(__file__)),
        "files": {"display.json": {**pin(out / "display.json"), "records": 1}},
    })


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("pilot", "trace", "operator", "out"):
        cli.add_argument(name, type=Path)
    opts = cli.parse_args()
    build(opts.pilot, opts.trace, opts.operator, opts.out)
