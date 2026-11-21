import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import IDS, Invalid, digest, empty, load, stable_id
from coverage import coverage
from merge import plan_merge
from publication import current, publish
from simulation import SimulatedStore


def transition(old, new, table="facility_matches", tid="review:001"):
    return {"transition_id": tid, "table": table, "row_id": old[IDS[table]],
            "prior_payload_sha256": digest(old), "new_payload_sha256": digest(new),
            "actor": "synthetic-reviewer", "at": "2026-11-21T18:00:00Z",
            "reason": "Synthetic campus review", "replacement": new}


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.batch = load(ROOT / "contracts/fixtures/enrichment.json")
        self.base = load(ROOT / "contracts/fixtures/enrichment_base.json")

    def test_replay_and_permutation(self):
        first = plan_merge([self.batch], self.base)
        reversed_batch = {k: list(reversed(v)) if isinstance(v, list) else v for k, v in self.batch.items()}
        replay = plan_merge([reversed_batch, self.batch], self.base, first["batch"])
        self.assertEqual(first, replay)
        self.assertEqual(first, plan_merge([reversed_batch, self.batch], self.base))
        self.assertEqual(first, plan_merge([self.batch, reversed_batch], self.base))

    def test_duplicate_id_different_payload_never_overwrites(self):
        for table, field in (("external_facilities", "name_original"), ("source_snapshots", "attribution"),
                             ("facility_evidence", "assertion"), ("facility_matches", "rationale")):
            batch = copy.deepcopy(self.batch)
            batch[table][0][field] = "changed content"
            with self.assertRaisesRegex(Invalid, "conflicting payload"):
                plan_merge([batch], self.base, self.batch)

    def test_snapshot_retrieval_clock_retained_and_new_order_stable(self):
        later = copy.deepcopy(self.batch)
        later["source_snapshots"][0]["retrieved_at"] = "2026-11-22T00:00:00Z"
        original = plan_merge([self.batch], self.base)
        self.assertEqual(plan_merge([later], self.base, original["batch"]), original)
        self.assertEqual(plan_merge([later, self.batch], self.base), plan_merge([self.batch, later], self.base))
        persisted_later = plan_merge([later], self.base)
        self.assertEqual(plan_merge([self.batch], self.base, persisted_later["batch"]), persisted_later)

    def test_equal_timestamp_encodings_merge_deterministically(self):
        variant = copy.deepcopy(self.batch)
        variant["source_snapshots"][0]["retrieved_at"] = "2026-11-21T17:00:00.000Z"
        self.assertEqual(plan_merge([variant, self.batch], self.base),
                         plan_merge([self.batch, variant], self.base))

    def test_numeric_encoding_cannot_change_immutable_hash_on_replay(self):
        variant = copy.deepcopy(self.batch)
        variant["facility_evidence"][2]["observation"]["distance_m"] = 25
        with self.assertRaisesRegex(Invalid, "conflicting payload"):
            plan_merge([variant, self.batch], self.base)

    def review_transition(self):
        old = self.batch["facility_matches"][1]
        new = copy.deepcopy(old)
        new.update(status="confirmed", method="manual_review", rationale="Reviewed same campus",
                   reviewer="synthetic-reviewer", reviewed_at="2026-11-21T18:00:00Z")
        return transition(old, new)

    def test_explicit_review_transition_and_replay(self):
        t = self.review_transition()
        plan = plan_merge([], self.base, self.batch, [t])
        self.assertEqual(plan["batch"]["facility_matches"][1]["status"], "confirmed")
        self.assertEqual(plan["ledger"], [t])
        self.assertEqual(plan, plan_merge([], self.base, plan["batch"], [t], plan["ledger"]))

    def test_stale_hash_forged_actor_and_immutable_change(self):
        t = self.review_transition()
        for changes in ({"prior_payload_sha256": "0" * 64}, {"actor": "another-reviewer"}):
            altered = {**t, **changes}
            with self.assertRaises(Invalid):
                plan_merge([], self.base, self.batch, [altered])
        t["replacement"]["facility_id"] = self.base[0]["facility_id"]
        t["new_payload_sha256"] = digest(t["replacement"])
        with self.assertRaisesRegex(Invalid, "immutable facts"):
            plan_merge([], self.base, self.batch, [t])

    def test_accepted_ledger_must_match_accepted_rows(self):
        t = self.review_transition()
        with self.assertRaisesRegex(Invalid, "ledger tip"):
            plan_merge([], self.base, self.batch, [t], [t])

    def test_hash_chain_order_and_fork_rejection(self):
        first = self.review_transition()
        old = first["replacement"]
        new = {**old, "status": "rejected"}
        second = transition(old, new, tid="review:002")
        p1 = plan_merge([], self.base, self.batch, [first, second])
        p2 = plan_merge([], self.base, self.batch, [second, first])
        self.assertEqual(p1, p2)
        fork = {**first, "transition_id": "review:fork"}
        with self.assertRaisesRegex(Invalid, "same prior hash"):
            plan_merge([], self.base, self.batch, [first, fork])

    def test_cyclic_queue_history_cannot_be_published(self):
        old = self.batch["review_queue"][0]
        new = {**old, "status": "resolved", "resolution": "synthetic resolution"}
        first = transition(old, new, "review_queue", "review:resolve")
        second = transition(new, old, "review_queue", "review:reopen")
        with self.assertRaisesRegex(Invalid, "cyclic"):
            plan_merge([], self.base, self.batch, [first, second])

    def test_rejected_link_transition_must_unlink_evidence_in_same_plan(self):
        old = self.batch["facility_matches"][0]
        new = {**old, "status": "rejected", "reviewed_at": "2026-11-21T18:00:00Z"}
        transitions = [transition(old, new)]
        with self.assertRaisesRegex(Invalid, "confirmed match"):
            plan_merge([], self.base, self.batch, transitions)
        for e in self.batch["facility_evidence"]:
            if e["match_id"] == old["match_id"]:
                replacement = {**e, "facility_id": None, "match_id": None, "reviewed_at": "2026-11-21T18:00:00Z"}
                transitions.append(transition(e, replacement, "facility_evidence", "unlink:" + e["evidence_id"]))
        plan = plan_merge([], self.base, self.batch, transitions)
        self.assertTrue(all(e["facility_id"] is None for e in plan["batch"]["facility_evidence"]))

    def test_source_id_derivation_is_clock_and_order_independent(self):
        self.assertEqual(stable_id("source", "source-key", {"a": 1, "b": 2}),
                         stable_id("source", "source-key", {"b": 2, "a": 1}))
        self.assertNotEqual(stable_id("source", "source-key", "raw-sha-a"),
                            stable_id("source", "source-key", "raw-sha-b"))

    def test_coverage_denominators_unknowns_and_freshness(self):
        result = coverage(plan_merge([self.batch], self.base)["batch"], self.base, "2026-11-21")
        self.assertEqual(result["base"]["denominator"], 2)
        self.assertEqual(result["base"]["confirmed_identity"], 1)
        self.assertEqual(result["base"]["trauma_unknown"], 1)
        self.assertEqual(result["trauma_by_polarity"]["denominator"], 2)
        self.assertEqual(result["evidence_by_effective_age"]["counts"], {"over_365_days": 1, "unknown": 2})
        self.assertEqual(result["validation_errors"], 0)
        self.assertIn("unknown", result["live_availability"])


class PublicationSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "simulation.sqlite")
        self.store = SimulatedStore(self.path)
        self.batch = load(ROOT / "contracts/fixtures/enrichment.json")
        self.base = load(ROOT / "contracts/fixtures/enrichment_base.json")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def publish(self, run, batch=None, **kwargs):
        return publish(self.store, [batch or self.batch], self.base, run, "2026-11-21", **kwargs)

    def next_batch(self):
        extra = empty()
        extra["review_queue"] = [{**self.batch["review_queue"][0], "review_id": "synthetic:review:new"}]
        return extra

    def test_simulated_failure_after_each_write_preserves_prior_pointer_and_recovers(self):
        old = self.publish("first")
        for stage in range(1, 6):
            with self.subTest(failed_after_table=stage):
                def fail(index):
                    if index == stage:
                        raise RuntimeError("simulated write interruption")
                with self.assertRaisesRegex(RuntimeError, "simulated"):
                    self.publish("new", self.next_batch(), after_write=fail)
                observed, batch = current(self.store)
                self.assertEqual(observed, old)
                self.assertEqual(batch["review_queue"], self.batch["review_queue"])
        # Reopen storage to model process restart, not just in-memory retry.
        self.store.close()
        self.store = SimulatedStore(self.path)
        new = self.publish("new", self.next_batch())
        self.assertEqual(new["counts"]["review_queue"], 2)
        self.assertEqual(new["parent_run"], "first")
        self.assertEqual(current(self.store)[0], new)
        self.assertEqual(self.publish("new", self.next_batch()), new)
        self.assertEqual(self.store.read_state()[0], 2)

    def test_simulated_first_run_failure_does_not_publish(self):
        def fail(_):
            raise RuntimeError("simulated")
        with self.assertRaises(RuntimeError):
            self.publish("first", after_write=fail)
        self.assertEqual(current(self.store), (None, None))

    def test_run_id_cannot_rebind_and_old_replay_does_not_rewind(self):
        old = self.publish("old")
        new = self.publish("new", self.next_batch())
        self.assertEqual(self.publish("old"), old)
        self.assertEqual(current(self.store)[0], new)
        with self.assertRaisesRegex(Invalid, "different inputs"):
            self.publish("old", self.next_batch())

    def test_changed_base_text_is_rejected_before_writes(self):
        old = self.publish("first")
        self.base[0]["original_evidence"] += " changed"
        with self.assertRaisesRegex(Invalid, "base rows/text/order changed"):
            self.publish("changed")
        self.assertEqual(current(self.store)[0], old)

    def test_simulated_readback_corruption_prevents_publication(self):
        old = self.publish("first")
        real_reader = self.store.read_completed
        def corrupt(manifest):
            result = real_reader(manifest)
            if "batch_sha256" not in manifest:
                result["review_queue"] = []
            return result
        self.store.read_completed = corrupt
        with self.assertRaisesRegex(Invalid, "readback differs"):
            self.publish("bad", self.next_batch())
        self.assertEqual(current(self.store)[0], old)

    def test_simulated_stale_revision_and_competing_publication(self):
        old = self.publish("first")
        with self.assertRaisesRegex(Invalid, "state changed"):
            self.publish("stale", expected_revision=0)
        competing = SimulatedStore(self.path)
        def race(index):
            if index == 5:
                publish(competing, [self.batch], self.base, "winner", "2026-11-21")
        try:
            with self.assertRaisesRegex(Invalid, "concurrent publication won"):
                self.publish("loser", self.next_batch(), after_write=race)
            self.assertEqual(current(self.store)[0]["run_id"], "winner")
            self.assertNotIn("loser", self.store.read_state()[1]["runs"])
            self.publish("loser", self.next_batch())
            self.assertEqual(current(self.store)[0]["parent_run"], "winner")
        finally:
            competing.close()

    def test_invalid_batch_never_writes_or_publishes(self):
        self.batch["external_facilities"][0]["snapshot_id"] = "missing:id"
        with self.assertRaises(Invalid):
            self.publish("invalid")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM stage").fetchone()[0], 0)
        self.assertEqual(current(self.store), (None, None))


if __name__ == "__main__":
    unittest.main()
