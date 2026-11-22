"""Synthetic preservation, scope, lineage and replay checks; no private data."""
from pathlib import Path
import tempfile
import unittest

from research.acquisition.service_evidence_ledger.ledger import (
    SERVICES, attach_joint_trace, build, key, normalize_lanes, reconcile, write_release,
)


def baseline():
    base = [{"facility_id": fid, "source_row": {"unique_id": upstream, "description": "Onsite MRI. No dialysis."}}
            for fid, upstream in [("twin-a", "same-original"), ("twin-b", "same-original"), ("missing", "unknown")]]
    occurrences = [{"facility_id": r["facility_id"], "original_upstream_id": r["source_row"]["unique_id"],
                    "input_ordinal_zero_based": n, "original_payload_sha256": key(r["source_row"]),
                    "state": "(no state label)" if n == 2 else "synthetic state", "conflicts": [],
                    "branch_evidence": {"mixed_campus": n == 2}} for n, r in enumerate(base)]
    decisions = [{"occurrence_key": r["facility_id"], "service": s, "state": r["state"],
                  "status": "unconfirmed", "as_of": "2026-11-21", "reason": "Not adjudicated"}
                 for r in occurrences for s in SERVICES]
    return base, occurrences, decisions


def edition(eid="source-a", family="origin-a"):
    return {"edition_id": eid, "publisher": "Synthetic publisher", "source_url": "https://example.invalid/source",
            "content_sha256": "a" * 64, "reuse_terms": "Synthetic fixture", "geographic_scope": "Synthetic India scope",
            "sharing_scope": "private_datathon_four_readers", "source_family": family,
            "origin_status": "known" if family else "unknown", "published_date": "2026-11-01",
            "retrieved_at": "2026-11-20T00:00:00Z"}


def observation(oid="claim-a", eid="source-a", polarity="supports", quality="candidate"):
    return {"observation_id": oid, "edition_id": eid, "source_facility_id": "synthetic-campus",
            "modality": "mri", "claim_type": "onsite_service", "claim_scope": "whole-campus",
            "claim_value": "service statement", "units": None, "raw_text": "Onsite MRI.",
            "locator": {"page": 1, "row": 3}, "original_occurrence_key": None,
            "source_date": "2026-11-01", "effective_from": "2026-11-01", "effective_until": "2026-11-30",
            "polarity": polarity, "independence_status": "unassessed", "multi_campus": False,
            "mirror_of": [], "supersedes": [],
            "target_links": [{"occurrence_key": "twin-a", "campus_id": "reviewed-campus" if quality == "confirmed" else None,
                              "quality": quality, "review_reference": "synthetic-review" if quality == "confirmed" else None}]}


def package(rows, editions=None, lane="A"):
    return {"schema_version": "service-evidence-lane-v1", "lane": lane,
            "editions": editions or [edition()], "observations": rows}


class LedgerTests(unittest.TestCase):
    def test_full_occurrences_twins_unknowns_and_decisions_preserved(self):
        b, o, d = baseline()
        result = build(b, o, d, national=False)
        self.assertEqual(result["decisions"], d)
        self.assertEqual([r["original"] for r in result["occurrences"]], b)
        self.assertEqual(result["report"]["population"]["occurrences_in_duplicate_groups"], 2)
        self.assertEqual(result["report"]["unknown_geography_occurrences"], 1)
        self.assertIsNone(result["report"]["verified_original_field_spans"])
        self.assertEqual(len(result["report"]["state_service"]), 6)

    def test_missing_and_duplicate_decisions_rejected(self):
        b, o, d = baseline()
        for wrong in (d[:-1], d + [d[0]]):
            with self.assertRaisesRegex(ValueError, "decision_frame"):
                build(b, o, wrong, national=False)

    def test_zero_row_geography_bucket_preserved(self):
        result = build(*baseline(), national=False,
                       geography_buckets=["synthetic state", "(no state label)", "empty jurisdiction"])
        empty = [r for r in result["report"]["state_service"] if r["state"] == "empty jurisdiction"]
        self.assertEqual(len(empty), 3)
        self.assertTrue(all(r["original_occurrences"] == r["unconfirmed"] == 0 for r in empty))

    def test_joint_trace_retained_without_replacing_prior_identity_or_decisions(self):
        b, o, d = baseline()
        result = build(b, o, d, national=False)
        joint = [{"facility_id": r["facility_id"], "original_payload_sha256": r["original_payload_sha256"],
                  "input_ordinal": i, "state": r["state"], "outcomes": {"joint": "candidate_only"},
                  "baseline_service_context": dict.fromkeys(SERVICES, "unconfirmed")} for i, r in enumerate(o, 1)]
        attach_joint_trace(result, joint)
        self.assertEqual([r["identity"] for r in result["occurrences"]], o)
        self.assertEqual([r["joint_identity"] for r in result["occurrences"]], joint)
        self.assertEqual(result["decisions"], d)
        with self.assertRaisesRegex(ValueError, "joint_occurrence_frame_changed"):
            attach_joint_trace(result, joint[:-1])

    def test_changed_original_and_reordered_occurrences_rejected(self):
        b, o, d = baseline()
        with self.assertRaisesRegex(ValueError, "order_changed"):
            build(b, list(reversed(o)), d, national=False)
        b[0]["source_row"]["description"] += " changed"
        with self.assertRaisesRegex(ValueError, "payload_changed"):
            build(b, o, d, national=False)

    def test_raw_claim_and_confirmed_link_never_change_baseline(self):
        b, o, d = baseline()
        r = build(b, o, d, [package([observation(quality="confirmed")])], national=False)
        self.assertEqual(r["decisions"], d)
        self.assertEqual(r["report"]["baseline_decision_transitions"], 0)
        self.assertEqual(len(r["reconciliation"]), 1)
        self.assertEqual(r["reconciliation"][0]["reviewed_independent_families"], [])

    def test_mirrored_mentions_retained_one_family_no_independent_agreement(self):
        a, b = observation(), observation("claim-b", "source-b")
        b["mirror_of"] = [key(["A", "claim-a"])]
        p = package([a, b], [edition(), edition("source-b")])
        _, rows = normalize_lanes([p], baseline()[0])
        groups, repeated = reconcile(rows)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(repeated), 1)
        self.assertEqual(groups, [])  # Candidate identity does not create a confirmed campus.

    def test_conflicts_require_comparable_campus_claim_units_and_dates(self):
        b, o, d = baseline()
        a = observation(quality="confirmed")
        negative = observation("negative", polarity="contradicts", quality="confirmed")
        for change, expected in [({}, 1), ({"effective_from": None}, 0),
                                 ({"effective_from": "2026-12-01", "effective_until": "2026-12-31"}, 0),
                                 ({"claim_type": "installed_equipment"}, 0), ({"units": "machines"}, 0),
                                 ({"claim_value": "different proposition"}, 0),
                                 ({"multi_campus": True}, 0)]:
            n = {**negative, **change}
            result = build(b, o, d, [package([a, n])], national=False)
            self.assertEqual(result["report"]["comparable_conflicted_groups"], expected)
            self.assertEqual(len(result["observations"]), 2)

    def test_unknown_origins_and_unlinked_observations_retained(self):
        a = observation()
        a["target_links"] = []
        b, o, d = baseline()
        result = build(b, o, d, [package([a], [edition(family=None)])], national=False)
        self.assertEqual(len(result["observations"]), 1)
        self.assertIsNone(result["observations"][0]["source_family"])
        self.assertEqual(result["report"]["combined_linked_occurrence_modality_pairs"], 0)

    def test_independence_and_confirmed_campus_need_explicit_reviews(self):
        a = observation(quality="confirmed")
        a["target_links"][0]["review_reference"] = None
        with self.assertRaisesRegex(ValueError, "confirmed_link_requires_review"):
            normalize_lanes([package([a])], baseline()[0])
        a = observation()
        a["independence_status"] = "reviewed_independent"
        with self.assertRaisesRegex(ValueError, "independence_review_required"):
            normalize_lanes([package([a])], baseline()[0])

    def test_original_offsets_validate_negation_without_rewriting(self):
        a = observation()
        a.update(original_occurrence_key="twin-a", modality="dialysis", raw_text="No dialysis.",
                 locator={"field": "description", "start": 12, "end": 25}, polarity="contradicts")
        # An off-by-one locator beyond the original field must fail closed.
        with self.assertRaisesRegex(ValueError, "original_locator"):
            normalize_lanes([package([a])], baseline()[0])
        raw = baseline()[0][0]["source_row"]["description"]
        a["locator"] = {"field": "description", "start": raw.index("No"), "end": len(raw)}
        _, rows = normalize_lanes([package([a])], baseline()[0])
        self.assertEqual(rows[0]["raw"]["raw_text"], "No dialysis.")

    def test_relation_and_edition_collisions_rejected(self):
        a = observation(); a["mirror_of"] = ["not-loaded"]
        with self.assertRaisesRegex(ValueError, "unresolved_relationship"):
            normalize_lanes([package([a])], baseline()[0])
        other = edition(); other["content_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "edition_id_collision"):
            normalize_lanes([package([observation()]), package([], [other], "B")], baseline()[0])

    def test_immutable_release_replays_and_refuses_overwrite(self):
        artifact = build(*baseline(), national=False)
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "one", Path(tmp) / "two"
            first = write_release(one, artifact, {"fixture": True})
            self.assertEqual(first, write_release(two, artifact, {"fixture": True}))
            self.assertEqual(first, write_release(one, artifact, {"fixture": True}))
            for p in one.iterdir():
                self.assertEqual(p.read_bytes(), (two / p.name).read_bytes())
            with self.assertRaisesRegex(ValueError, "changed_bytes"):
                write_release(one, artifact, {"fixture": False})


if __name__ == "__main__":
    unittest.main()
