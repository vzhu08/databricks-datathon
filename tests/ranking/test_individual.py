import json
import unittest
from copy import deepcopy

from app.capacity_recommendation import demo_capacity_inputs, recommend_capacity
from app.ranking.individual import select_individual


def campus(key="fixture-a", precision="locality", **fields):
    """An invented record in the shape of the two venue-cleared mapper claims."""
    source = dict(role="support", origin="fixture", field="procedures", fact="dialysis unit",
                  match="reported", observed_on=None, citation_scope="record",
                  citation="https://example.invalid/campus", assertion=None)
    claim = dict(kind="service", service="dialysis", scope="fixture record", decision="unconfirmed",
                 strength="reported", as_of="2026-11-22", review=None, source_records=1,
                 independent_supporting_origins=1, sources=[source],
                 missing_check="Confirm dated onsite dialysis at this branch.")
    loc = dict(kind="location", scope="fixture record", precision=precision, sources=[],
               strength="reported", missing_check=None)
    return dict(key=key, name="Example Campus A", area="Example locality", location=loc,
                service=claim, source_scope="synthetic", **fields)


def select(rows, **kwargs):
    return select_individual("dialysis", rows, **kwargs)


class IndividualSelectionTests(unittest.TestCase):
    def test_scoped_vf_only_example_can_export_the_same_claim(self):
        row = campus(travel={"status": "known", "minutes": 2, "source": "fixture"}, distance_km=1)
        row["source_scope"] = "vf_only"  # An invented private classification for this test.
        original = deepcopy(row)
        result = select([row])
        chosen = json.loads(json.dumps(result))["chosen"]
        self.assertEqual((result["status"], chosen["label"], result["next_action"]),
                         ("provisional", "Provisional · VF only", "confirmation_note"))
        self.assertEqual((chosen["service"], chosen["location"]), (row["service"], row["location"]))
        self.assertEqual(chosen["key"], row["key"])
        self.assertIsNone(chosen["travel"]["minutes"])
        self.assertIsNone(chosen["distance_km"])
        self.assertEqual(chosen["availability"], "unknown")
        self.assertIn("Seek independent corroboration for the VF record.", chosen["missing"])
        self.assertEqual(row, original)

    def test_capacity_result_from_actual_allocator_and_separate_emergency_stop(self):
        allocation = recommend_capacity(*demo_capacity_inputs())
        result = select([campus()], allocation=allocation)
        self.assertEqual((result["status"], result["next_action"]), ("assigned", "referral_note"))
        self.assertEqual(result["chosen"], allocation["chosen"])
        self.assertEqual(result["allocation"]["mode"], "synthetic")
        emergency = select([campus()], emergency=True, allocation=allocation)
        self.assertEqual((emergency["status"], emergency["candidates"], emergency["chosen"]),
                         ("emergency", [], None))

    def test_real_allocation_requires_a_permitted_matching_branch(self):
        allocation = dict(recommend_capacity(*demo_capacity_inputs()), mode="reviewed")
        key = allocation["chosen"]["facility_id"]
        row = campus(key, precision="identified_campus")
        row["service"].update(decision="yes", review={"as_of": "2026-11-22"})
        row["source_scope"] = "private_reviewed"
        self.assertEqual(select([row], allocation=allocation)["status"], "assigned")
        for change in ({"key": "different"}, {"location": dict(row["location"], precision="district")},
                       {"availability": "full"}, {"availability": "stale"}, {"source_scope": "vf_only"}):
            with self.subTest(change=change):
                result = select([{**row, **change}], allocation=allocation)
                self.assertNotEqual(result["next_action"], "referral_note")
                self.assertEqual(result["allocation"]["reason"], "unsupported_individual_assignment")
        for choice in ({"free_staffed_slots": 0}, {"travel_minutes": None}, {"travel_source": ""}):
            result = select([row], allocation=dict(allocation, chosen={**allocation["chosen"], **choice}))
            self.assertEqual(result["status"], "provisional")

    def test_lineage_and_dates_outrank_repeats_distance_and_capture_time(self):
        repeat, multi, recent, unknown = [campus(k) for k in ("a", "b", "c", "d")]
        repeat["service"]["sources"] *= 5
        repeat["service"]["source_records"] = 5
        repeat["service"]["sources"][0].update(observed_on="2024-01-01", archive_captured_at="2026-11-22")
        multi["service"].update(strength="corroborated", independent_supporting_origins=2)
        recent["service"]["sources"][0]["observed_on"] = "2025-01-01"
        unknown["service"]["independent_supporting_origins"] = None
        ranked = select([repeat, unknown, recent, multi])["candidates"]
        self.assertEqual([row["key"] for row in ranked], ["b", "c", "a", "d"])
        self.assertIsNone(ranked[-1]["service"]["independent_supporting_origins"])

    def test_distinct_occurrences_with_same_display_name_and_different_branches(self):
        rows = [campus(k, precision="verified_entrance", distance_km=dist)
                for k, dist in [("b", 4), ("a", 4), ("c", 1)]]
        rows[-1]["name"] = "Example Campus B"
        self.assertEqual([r["key"] for r in select(rows)["candidates"]], ["c", "a", "b"])
        with self.assertRaises(ValueError):
            select([rows[0], rows[0]])
        rows[0]["service"]["service"] = "mri"
        with self.assertRaises(ValueError):
            select(rows)

    def test_road_tie_break_and_provider_failure_preserve_lead(self):
        first, second = [campus(k, precision="identified_campus", distance_km=d)
                         for k, d in [("a", 2), ("b", 9)]]
        for row, minutes in [(first, 8), (second, 4)]:
            row["travel"] = dict(status="known", source="fixture ordinary car", minutes=minutes)
        self.assertEqual(select([first, second])["chosen"]["key"], "b")
        first["travel"].update(status="unavailable", reason="provider_failure")
        result = select([first, second])
        self.assertEqual((result["status"], result["chosen"]["key"]), ("provisional", "a"))
        self.assertIsNone(result["chosen"]["travel"]["minutes"])
        self.assertEqual(result["chosen"]["travel"]["reason"], "provider_failure")

    def test_wrong_branch_negative_conflict_and_stock_remain_visible(self):
        for code, reason in [("negative", "service_reported_absent"), ("conflict", "conflicting_service_evidence"),
                             ("context", "identity_or_area_only"), ("full", "availability_full")]:
            row = campus()
            claim = row["service"]
            if code == "negative":
                claim["sources"][0]["assertion"] = "all_cases_referral"
            elif code == "conflict":
                claim["strength"] = "conflicting_evidence"
                claim["sources"].append(dict(role="conflict", fact="Fixture contradicts this statement"))
            elif code == "context":
                claim["strength"] = "no_evidence"
                claim["sources"][0].update(role="context", match="different", scope="Another branch")
            else:
                row["availability"] = "full"
            with self.subTest(code=code):
                result = select([row])
                self.assertEqual((result["status"], result["reason"]), ("verification_lead", reason))
                self.assertEqual(result["chosen"]["service"], claim)
        row = campus(availability="stale")
        self.assertEqual(select([row])["chosen"]["availability"], "stale")

    def test_area_only_source_failure_and_empty_cases(self):
        row = campus(precision="district", distance_km=0)
        row.update(name=None, service=None)
        lead = select([row])
        self.assertEqual((lead["status"], lead["chosen"]["area"]), ("verification_lead", row["area"]))
        self.assertIsNone(lead["chosen"]["distance_km"])
        self.assertIn("requested service", " ".join(lead["missing"]))
        for rows in ([], [{"key": "opaque"}]):
            self.assertEqual(select(rows)["reason"], "missing_individual_evidence")
        self.assertEqual(select_individual(None, [row])["reason"], "missing_requested_service")

    def test_warehouse_summary_precedes_individual_selection_and_allocation(self):
        summary = dict(status="withheld", service="dialysis", independent_supporting_origins=None)
        allocation = recommend_capacity(*demo_capacity_inputs())
        result = select([campus()], withheld_summary=summary, allocation=allocation)
        self.assertEqual((result["status"], result["candidates"], result["chosen"]), ("withheld", [], None))
        self.assertNotIn("Example Campus", json.dumps(result))
        self.assertIsNone(result["allocation"])
        for status in ("no_match", "unavailable", "unresolved_location"):
            result = select([campus()], withheld_summary=dict(summary, status=status))
            self.assertEqual((result["status"], result["reason"]), ("no_usable_evidence", status))
