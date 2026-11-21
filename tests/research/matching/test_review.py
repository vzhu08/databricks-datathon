import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from matching_fixtures import (LATER, ROOT, base_row, envelope, ext, mapping, match_for, snapshot,
                               trauma_evidence)
from common import Invalid
from coverage import coverage
from merge import plan_merge

from research.matching.common import MatchingError, digest
from research.matching.review import STRATA, apply, sample, stratum
from research.matching.run import execute

STATE = "Synthetic State"


def decision(row, verdict, at=LATER, reviewer="synthetic-reviewer-c", rationale="Synthetic address review."):
    return {"match_id": row["match_id"], "decision": verdict, "reviewer": reviewer, "reviewed_at": at,
            "rationale": rationale}


class Scenario:
    """Two same-name campuses; a programme source carries reviewed but unlinked trauma evidence."""

    def __init__(self):
        self.directory, self.program = snapshot(), snapshot("synthetic_program")
        self.base = [base_row(1, name="Example Health Centre", city="North Town", state=STATE),
                     base_row(2, name="Example Health Centre", city="South Town", state=STATE)]
        self.externals = [ext(1, "Example Health Centre", self.directory, city="North Town", state=STATE),
                          ext(2, "Example Health Centre", self.directory, city="South Town", state=STATE)]
        self.evidence = [trauma_evidence(1, self.externals[0], self.program),
                         trauma_evidence(2, self.externals[1], self.program)]
        self.source = envelope([self.directory, self.program], self.externals, self.evidence)
        self.result = execute(self.base, [self.source], mapping=mapping(self.base))
        self.batch = self.result["batch"]

    def match(self, base_number, ext_number):
        return match_for(self.result, base_number, ext_number)


class SamplingTests(unittest.TestCase):
    def test_all_candidates_sampled_when_fewer_than_limit(self):
        s = Scenario()
        self.assertEqual(4, s.result["report"]["review_sampling"]["sample_size"])
        self.assertEqual(4, len(s.result["review_worksheet"]))
        self.assertTrue(all(row["decision"] is None and row["reviewer"] is None for row in s.result["review_worksheet"]))

    def test_sample_is_capped_stratified_and_repeatable(self):
        candidates = []
        for n in range(200):
            flags = [["ambiguous_campus"], ["place_conflict"], ["matched_via_alias"], ["non_hospital_type"],
                     ["geography_unknown"], [], ["proximity_only"]][n % 7]
            candidates.append({"match_id": f"acq-c-match:{n:064d}", "flags": flags, "rank": 1,
                               "auto_confirmed": False, "signals": {"name_level": "strong"}})
        chosen, summary = sample(candidates, 50)
        self.assertEqual(50, len(chosen))
        self.assertEqual(200, summary["population"])
        for name in ("easy", "alias", "ambiguous_name", "conflicting_geography", "missing_geography", "non_hospital_type"):
            self.assertGreaterEqual(summary["strata"][name]["sampled"], 7, name)
        again, _ = sample(list(reversed(candidates)), 50)
        self.assertEqual([c["match_id"] for c in chosen], [c["match_id"] for c in again])
        self.assertEqual(set(STRATA), set(summary["strata"]))
        self.assertEqual("easy", stratum(candidates[5]))


class DecisionTests(unittest.TestCase):
    def test_confirmed_link_attaches_evidence_and_d_accepts_first_submission(self):
        s = Scenario()
        decisions = [decision(s.match(1, 1), "confirmed"), decision(s.match(1, 2), "rejected"),
                     decision(s.match(2, 1), "conflict")]
        out = apply(s.batch, decisions, s.source)
        self.assertEqual({"confirmed": 1, "rejected": 1, "conflict": 1, "candidate": 1},
                         out["summary"]["matches_by_final_status"])
        self.assertEqual(1, out["summary"]["evidence_linked"])
        self.assertEqual(1, out["summary"]["evidence_left_unlinked"])
        self.assertEqual([s.match(1, 2)["match_id"]], out["summary"]["observed_false_matches"])
        # First submission: reviewed batch plus evidence-only transitions.
        plan = plan_merge([s.source, out["reviewed_batch"]], s.base, transitions=out["evidence_transitions"])
        evidence = {e["evidence_id"]: e for e in plan["batch"]["facility_evidence"]}
        self.assertEqual("synthetic:base:001", evidence["synthetic:evidence:001"]["facility_id"])
        self.assertIsNone(evidence["synthetic:evidence:002"]["facility_id"])  # its match was never confirmed
        report = coverage(plan["batch"], plan["base"], "2026-11-21")
        self.assertEqual(1, report["base"]["linked_supporting_trauma_including_historical"])
        self.assertEqual(1, report["base"]["confirmed_identity"])
        self.assertEqual(s.base, plan["base"])

    def test_transitions_replay_against_already_accepted_candidates(self):
        s = Scenario()
        out = apply(s.batch, [decision(s.match(1, 1), "confirmed")], s.source)
        plan = plan_merge([s.source, s.batch], s.base, transitions=out["transitions"])
        final = {m["match_id"]: m for m in plan["batch"]["facility_matches"]}
        self.assertEqual("confirmed", final[s.match(1, 1)["match_id"]]["status"])
        self.assertEqual("manual_review", final[s.match(1, 1)["match_id"]]["method"])
        self.assertEqual(digest(out["reviewed_batch"]["facility_matches"]),
                         digest(plan["batch"]["facility_matches"]))
        resolved = [r for r in plan["batch"]["review_queue"] if r["status"] == "resolved"]
        self.assertEqual(1, len(resolved))
        self.assertEqual(len(plan["ledger"]), len(out["transitions"]))

    def test_rejected_or_conflicting_match_cannot_verify_a_service_claim(self):
        s = Scenario()
        for verdict in ("rejected", "conflict"):
            out = apply(s.batch, [decision(s.match(1, 1), verdict)], s.source)
            self.assertEqual(0, out["summary"]["evidence_linked"])
            self.assertEqual([], out["evidence_transitions"])
            plan = plan_merge([s.source, out["reviewed_batch"]], s.base)
            self.assertTrue(all(e["facility_id"] is None for e in plan["batch"]["facility_evidence"]))
            self.assertEqual(0, coverage(plan["batch"], plan["base"], "2026-11-21")["base"]["linked_trauma_any_polarity"])
        # Hand-forcing the link onto a rejected match is refused by D's validator too.
        out = apply(s.batch, [decision(s.match(1, 1), "rejected")], s.source)
        forced = copy.deepcopy(s.source)
        forced["facility_evidence"][0].update(facility_id="synthetic:base:001", match_id=s.match(1, 1)["match_id"])
        with self.assertRaises(Invalid):
            plan_merge([forced, out["reviewed_batch"]], s.base)

    def test_candidate_without_decision_leaves_evidence_unlinked(self):
        s = Scenario()
        out = apply(s.batch, [], s.source)
        self.assertEqual(2, out["summary"]["evidence_left_unlinked"])
        self.assertEqual([], out["transitions"])
        self.assertEqual(digest(s.batch), digest(out["reviewed_batch"]))

    def test_rejecting_a_linked_match_unlinks_its_evidence(self):
        s = Scenario()
        first = apply(s.batch, [decision(s.match(1, 1), "confirmed")], s.source)
        accepted = plan_merge([s.source, first["reviewed_batch"]], s.base, transitions=first["evidence_transitions"])
        accepted_source = dict(accepted["batch"], facility_matches=[], review_queue=[])
        later = "2026-11-21T21:00:00Z"
        second = apply(first["reviewed_batch"], [decision(s.match(1, 1), "rejected", at=later)], accepted_source)
        self.assertEqual(1, second["summary"]["evidence_unlinked"])
        plan = plan_merge([], s.base, accepted=accepted["batch"], transitions=second["transitions"],
                          accepted_ledger=accepted["ledger"])
        self.assertTrue(all(e["facility_id"] is None for e in plan["batch"]["facility_evidence"]))
        self.assertEqual(0, sum(m["status"] == "confirmed" for m in plan["batch"]["facility_matches"]))

    def test_invalid_decisions_are_refused(self):
        s = Scenario()
        good = decision(s.match(1, 1), "confirmed")
        cases = [
            ([dict(good, match_id="acq-c-match:unknown")], "unknown match"),
            ([good, good], "more than one decision"),
            ([dict(good, decision="probably")], "confirmed, rejected or conflict"),
            ([dict(good, reviewer="  ")], "nonempty text"),
            ([dict(good, rationale="")], "nonempty text"),
            ([dict(good, reviewed_at="2026-11-21 20:00")], "UTC timestamp"),
            ([{"match_id": good["match_id"]}], "needs match_id"),
            ([good, decision(s.match(2, 1), "confirmed")], "more than one base row"),
        ]
        for decisions, message in cases:
            with self.assertRaisesRegex(MatchingError, message):
                apply(s.batch, decisions, s.source)
        early = [decision(s.match(1, 1), "confirmed", at="2026-11-21T18:00:00Z")]  # before the evidence review
        with self.assertRaisesRegex(MatchingError, "precedes the evidence review"):
            apply(s.batch, early, s.source)

    def test_endorsing_an_automatic_confirmation_links_evidence_without_rewriting_it(self):
        policy = {"synthetic_registry": {"base_field": "source_row.registry_id", "external_field": "source_record_id",
                                         "source_keys": ["synthetic_directory"]}}
        directory, program = snapshot(), snapshot("synthetic_program")
        base = [base_row(1, name="Larkspur Hospital", registry_id="R-1")]
        externals = [ext(1, "Larkspur Hospital", directory, source_record_id="R-1")]
        source = envelope([directory, program], externals, [trauma_evidence(1, externals[0], program)])
        result = execute(base, [source], mapping=mapping(base), policy=policy)
        row = match_for(result, 1, 1)
        self.assertEqual("confirmed", row["status"])
        untouched = apply(result["batch"], [], source)
        self.assertEqual(0, untouched["summary"]["evidence_linked"])  # no reviewer, no link
        out = apply(result["batch"], [decision(row, "confirmed")], source)
        self.assertEqual(1, out["summary"]["evidence_linked"])
        self.assertTrue(out["ledger"][0]["endorsed_automatic_confirmation"])
        self.assertEqual("shared_identifier", out["reviewed_batch"]["facility_matches"][0]["method"])
        plan = plan_merge([source, out["reviewed_batch"]], base, transitions=out["evidence_transitions"],
                          identity_policy=policy)
        self.assertEqual("synthetic:base:001", plan["batch"]["facility_evidence"][0]["facility_id"])

    def test_review_cli_writes_all_artifacts(self):
        s = Scenario()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "matches.json").write_text(json.dumps(s.batch), encoding="utf-8")
            (tmp / "source.json").write_text(json.dumps(s.source), encoding="utf-8")
            (tmp / "decisions.json").write_text(json.dumps([decision(s.match(1, 1), "confirmed")]), encoding="utf-8")
            done = subprocess.run([sys.executable, "-m", "research.matching.review", "--matches", str(tmp / "matches.json"),
                                   "--decisions", str(tmp / "decisions.json"), "--external", str(tmp / "source.json"),
                                   "--output-dir", str(tmp / "out")], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(0, done.returncode, done.stderr)
            self.assertEqual({"evidence_transitions.json", "review_ledger.json", "review_summary.json",
                              "reviewed_batch.json", "transitions.json"}, {p.name for p in (tmp / "out").iterdir()})
            summary = json.loads((tmp / "out/review_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(1, summary["confirmed"])
            self.assertIn("not a precision estimate", summary["denominator_note"])


if __name__ == "__main__":
    unittest.main()
