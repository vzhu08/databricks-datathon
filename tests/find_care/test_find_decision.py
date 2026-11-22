"""#330: wording of one individual Find care decision, against A's published result contract and B's #315 claims."""
import json
import unittest
from pathlib import Path

from app import find_decision as decision_words
from app import finding_provenance as provenance
from app.ranking import search_facilities

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "contracts/fixtures/search.json").read_text(encoding="utf-8"))["facilities"]
REQUEST = "Dialysis near Jaipur, Rajasthan, within 50 km."


def claims(fact="dialysis unit", field="procedures", role="support", origin="fixture_family"):
    """Vincent's synthetic contract example from #330: one fixture family, a reported locality, no date."""
    scope = "Fictional facility record"
    service = provenance.summarize_claim("service", scope, [provenance.Observation(
        provenance.SYNTHETIC, fact, scope, role=role, origin=origin, field=field)], service="dialysis")
    location = provenance.summarize_claim("location", scope, [provenance.Observation(
        provenance.SYNTHETIC, "The record reports this locality.", scope, role="support", origin=origin,
        field="locality")], precision="locality")
    return location, service


def candidate(key="campus-a", name="Campus A", **changes):
    location, service = claims()
    return {"key": key, "name": name, "area": "Invented locality", "location": location, "service": service,
            "source_scope": "synthetic", "availability": "unknown", "travel": None, "distance_km": None,
            "label": None, "reason": "direct_service_statement",
            "missing": ["service_date", "physical_branch", "staffed_capacity", "travel_time"],
            "next_action": "confirmation_note", **changes}


def decided(status, chosen=None, others=(), **changes):
    return {"status": status, "reason": changes.pop("reason", None), "chosen": chosen,
            "candidates": [row for row in (chosen, *others) if row], "next_action": changes.pop("next_action", None),
            "missing": changes.pop("missing", []), "allocation": None, "summary": None, **changes}


class DecisionWordingTests(unittest.TestCase):
    def test_a_provisional_lead_says_what_the_record_says_and_what_is_unknown(self):
        result = decided("provisional", candidate(), next_action="confirmation_note")
        view = decision_words.explain(result, "dialysis")
        self.assertEqual("Provisional lead: Campus A. Confirm before anyone travels.", view["headline"])
        self.assertEqual("Provisional · Synthetic demo record", view["label"])
        lead = view["lead"]
        self.assertEqual(["“dialysis unit” (procedures field, Synthetic demo record)"], lead["says"])
        self.assertEqual("Independent sources for the service: 1.", lead["origins"])
        self.assertEqual("Service statement dated: unknown.", lead["date"])
        self.assertEqual("Free staffed places: unknown.", lead["availability"])
        self.assertEqual("Travel time: unknown.", lead["travel"])
        self.assertEqual(["the date the service statement applies to", "which physical branch the statement is about",
                          "whether a staffed place is free", "the travel time by road"], lead["missing"])
        self.assertEqual("confirmation", view["note_kind"])

    def test_the_call_script_is_never_a_referral_or_a_reservation(self):
        result = decided("provisional", candidate(), next_action="confirmation_note")
        note = decision_words.confirmation_note(result, "dialysis", REQUEST, synthetic=True)
        self.assertTrue(note.startswith("Confirmation call script (demonstration data, invented facilities)"))
        for part in ("This is not a referral and nothing is reserved.", "Call: Campus A, Invented locality",
                     "Status: Provisional · Synthetic demo record", "“dialysis unit” (procedures field",
                     "Free staffed places: unknown. Travel time: unknown.", "Do you provide dialysis at this site today",
                     "Not known yet:\n- the date the service statement applies to", "call 112"):
            self.assertIn(part, note)
        for part in ("Referral note", "Send to:", "booked", "confirmed slot"):
            self.assertNotIn(part, note)
        # Only a decision that asks for a confirmation note gets one.
        for other in (decided("assigned", next_action="referral_note"), decided("emergency"),
                      decided("no_usable_evidence", missing=["a location"]), decided("withheld"),
                      decided("verification_lead", candidate(next_action="verify_identity"), next_action="verify_identity"),
                      decided("provisional", candidate(), next_action="verify_identity")):
            self.assertIsNone(decision_words.confirmation_note(other, "dialysis", REQUEST, synthetic=True))

    def test_vf_only_is_said_only_when_the_scope_is_established(self):
        self.assertEqual("Provisional · VF only", decision_words.label({"source_scope": "vf_only"}))
        self.assertEqual("Provisional · Synthetic demo record", decision_words.label({"source_scope": "synthetic"}))
        for scope in (None, "", "virtue_foundation", "unknown", "VF"):
            self.assertEqual("Provisional · source scope unknown", decision_words.label({"source_scope": scope}))
        self.assertEqual("Provisional · VF only", decision_words.label({"label": "Provisional · VF only"}))

    def test_repeats_do_not_read_as_corroboration_and_unknown_lineage_reads_unknown(self):
        scope = "Named branch"
        repeated = provenance.summarize_claim("service", scope, [
            provenance.Observation("Mirror one", "dialysis", scope, role="support", origin="osm"),
            provenance.Observation("Mirror two", "dialysis", scope, role="support", origin="osm")], service="dialysis")
        unknown = provenance.summarize_claim("service", scope, [
            provenance.Observation("A publisher", "dialysis", scope, role="support")], service="dialysis")
        self.assertEqual("Independent sources for the service: 1.",
                         decision_words.lead(candidate(service=repeated), "dialysis")["origins"])
        self.assertEqual("Independent sources for the service: unknown.",
                         decision_words.lead(candidate(service=unknown), "dialysis")["origins"])

    def test_full_stale_and_a_real_travel_time_are_stated_at_their_own_scope(self):
        self.assertEqual("Reported full, with no free staffed place.",
                         decision_words.lead(candidate(availability="full"), "dialysis")["availability"])
        self.assertIn("out of date", decision_words.lead(candidate(availability="stale"), "dialysis")["availability"])
        timed = candidate(travel={"status": "known", "minutes": 12.5, "source": "TomTom ordinary car"})
        self.assertEqual("Travel time: 12.5 min (TomTom ordinary car).", decision_words.lead(timed, "dialysis")["travel"])
        failed = candidate(travel={"status": "unavailable", "minutes": None, "source": "TomTom"}, distance_km=6.67)
        self.assertEqual("Road time could not be fetched. About 6.7 km away in a straight line.",
                         decision_words.lead(failed, "dialysis")["travel"])

    def test_an_identity_lead_an_empty_input_a_withheld_result_and_an_emergency(self):
        location, _ = claims()
        only_identity = candidate(service=None, next_action="verify_identity", missing=["service_evidence"])
        view = decision_words.explain(decided("verification_lead", only_identity, next_action="verify_identity"), "mri")
        self.assertEqual("No record states an MRI scan. Closest identifiable lead: Campus A.", view["headline"])
        self.assertEqual(["No statement about an MRI scan was supplied."], view["lead"]["says"])
        self.assertEqual(["any statement that the service is offered"], view["lead"]["missing"])
        self.assertIsNone(view["note_kind"])
        empty = decision_words.explain(decided("no_usable_evidence", missing=["A location to search from"],
                                               next_action="clarify_input"), "dialysis")
        self.assertEqual("No usable evidence for dialysis with this request.", empty["headline"])
        self.assertEqual(["A location to search from"], empty["missing"])
        self.assertEqual("Change the request and search again.", empty["next_action"])
        withheld = decision_words.explain(decided("withheld", next_action="request_clearance"), "dialysis")
        self.assertIn("no facility can be named here yet", withheld["headline"])
        self.assertIsNone(withheld["lead"])
        emergency = decision_words.explain(decided("emergency", candidate()), "dialysis")
        self.assertIn("call 112 now", emergency["headline"])
        self.assertIsNone(emergency["lead"])

    def test_other_candidates_are_listed_without_the_chosen_one(self):
        first, second = candidate(), candidate("campus-b", "Campus B")
        view = decision_words.explain(decided("provisional", first, [second], next_action="confirmation_note"), "dialysis")
        self.assertEqual(["Campus B"], [row["name"] for row in view["others"]])

    def test_demonstration_cards_keep_their_own_claims_and_never_another_cards(self):
        response = search_facilities("dialysis", {"city": "Jaipur", "state": "Rajasthan"}, facilities=FIXTURE)
        findings = provenance.project_find_care(response, "dialysis", mode="demo")["findings"]
        rows = decision_words.card_candidates(response, findings)
        self.assertEqual(["demo-north", "demo-south"], [row["key"] for row in rows])
        self.assertTrue(all(row["source_scope"] == "synthetic" and row["travel"] is None for row in rows))
        self.assertIn("North Campus", rows[0]["service"]["scope"])
        self.assertIn("South Campus", rows[1]["service"]["scope"])
        self.assertEqual("Jaipur, Rajasthan, 302001", rows[0]["area"])
        # A card with no matching finding gets null claims.
        alone = decision_words.card_candidates(response, findings[:1])
        self.assertEqual((None, None), (alone[1]["location"], alone[1]["service"]))


if __name__ == "__main__":
    unittest.main()
