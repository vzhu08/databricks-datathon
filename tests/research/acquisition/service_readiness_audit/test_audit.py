import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.acquisition.service_readiness_audit.audit import (
    SCHEMA, SERVICES, build_plan, canonical, coverage, dimensions, validate,
)
from datetime import date
import hashlib


def frame(n=4, national=False):
    rows = []
    for i in range(n):
        source_id = str(i if not national or i < 10077 else i - 10077)
        for service in sorted(SERVICES):
            rows.append({"occurrence_key": f"synthetic:{i}", "source_id": source_id,
                         "service": service, "status": "unconfirmed", "state": None, "region": None,
                         "mentions": [], "conflict": None, "independent_origin_ids": None})
    return {"schema": SCHEMA, "freeze_sha256": "a" * 64, "input_hashes": {"synthetic-ledger": "b" * 64},
            "original_payload_multiset_sha256": "c" * 64, "decisions": rows}


def mention(mid="synthetic-m1", origin="synthetic-o1", when="2026-11-01"):
    return {"mention_id": mid, "claimant_id": "synthetic-claimant", "origin_id": origin,
            "campus_id": "synthetic-campus", "observation_id": "synthetic-observation", "observed_on": when,
            "locator": "synthetic page 1", "excerpt": "Synthetic statement only"}


class AuditTests(unittest.TestCase):
    def test_national_occurrences_and_duplicate_ids_are_preserved(self):
        f = frame(10088, national=True)
        self.assertEqual({"occurrences": 10088, "distinct_source_ids": 10077,
                          "decisions": 30264, "source_id_multiplicities": {1: 10066, 2: 11}}, validate(f))
        plan, forms = build_plan(f, as_of="2026-11-22", target=300)
        self.assertEqual(300, len(forms))
        self.assertEqual(30264, sum(s["population"] for s in plan["strata"]))
        self.assertAlmostEqual(30264, sum(s["weight"] for s in plan["sample"]))
        f["decisions"].pop()
        with self.assertRaisesRegex(ValueError, "all three"):
            validate(f)

    def test_partial_frame_never_passes_as_national(self):
        with self.assertRaisesRegex(ValueError, "national"):
            build_plan(frame(), as_of="2026-11-22")

    def test_unequal_strata_respect_budget_and_reconstruct_population(self):
        f = frame(20)
        for row in f["decisions"]:
            i = int(row["occurrence_key"].split(":")[1])
            row["region"] = "synthetic-north" if i < 6 else "synthetic-east" if i < 10 else None
        plan, _ = build_plan(f, as_of="2026-11-22", target=23, fixture=True)
        self.assertEqual(23, plan["actual_sample"])
        self.assertAlmostEqual(60, sum(row["weight"] for row in plan["sample"]))
        self.assertEqual(9, len(plan["strata"]))
        self.assertTrue(all(0 < s["inclusion_probability"] <= 1 for s in plan["strata"]))
        self.assertTrue(all(s["sample"] <= s["population"] for s in plan["strata"]))

    def test_duplicate_and_inconsistent_decisions_rejected(self):
        f = frame()
        f["decisions"].append(copy.deepcopy(f["decisions"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate(f, fixture=True)
        f = frame()
        f["decisions"][1]["state"] = "synthetic-region"
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            validate(f, fixture=True)

    def test_replay_is_order_invariant_and_inputs_remain_unchanged(self):
        f = frame(25)
        before = canonical(f)
        a, forms = build_plan(f, as_of="2026-11-22", target=12, fixture=True)
        self.assertEqual(before, canonical(f))
        f["decisions"].reverse()
        b, other_forms = build_plan(f, as_of="2026-11-22", target=12, fixture=True)
        self.assertEqual(a, b)
        self.assertEqual(forms, other_forms)
        f["freeze_sha256"] = "d" * 64
        changed, _ = build_plan(f, as_of="2026-11-22", target=12, fixture=True)
        self.assertNotEqual([r["audit_id"] for r in a["sample"]], [r["audit_id"] for r in changed["sample"]])

    def test_repeats_do_not_become_independent_confirmations(self):
        f = frame()
        row = f["decisions"][0]
        row["mentions"] = [mention(), mention("synthetic-m2")]
        d = dimensions(row, date(2026, 11, 22))
        self.assertEqual("single_origin", d["origins"])
        self.assertEqual("present", d["repeated_origin"])
        c = coverage(f["decisions"], date(2026, 11, 22))
        self.assertEqual((2, 2, 1, 1, 0), tuple(c[k] for k in ("mention_assignments", "unique_mention_ids",
                         "attributed_campus_service_observations", "known_origins", "reviewed_independent_origin_ids")))
        row["mentions"].append(mention("synthetic-m3", "synthetic-o2"))
        self.assertEqual("multiple_unresolved", dimensions(row, date(2026, 11, 22))["origins"])
        row["independent_origin_ids"] = ["synthetic-o1", "synthetic-o2"]
        with self.assertRaisesRegex(ValueError, "review reference"):
            validate(f, fixture=True)
        row["independence_review_ref"] = "synthetic-review-1"
        validate(f, fixture=True)
        self.assertEqual("reviewed_independent_multiple", dimensions(row, date(2026, 11, 22))["origins"])

    def test_dates_unknown_geography_and_conflicts_remain_in_frame(self):
        f = frame()
        row = f["decisions"][0]
        row["mentions"] = [mention(when=None)]
        self.assertEqual("date_unknown", dimensions(row, date(2026, 11, 22))["time"])
        row["mentions"].append(mention("synthetic-m2", when="2019-01-01"))
        self.assertEqual("partly_undated", dimensions(row, date(2026, 11, 22))["time"])
        row["mentions"].append(mention("synthetic-m3", when="2027-01-01"))
        self.assertEqual("future_present", dimensions(row, date(2026, 11, 22))["time"])
        row["conflict"] = True
        with self.assertRaisesRegex(ValueError, "cannot cover"):
            build_plan(f, as_of="2026-11-22", target=1, fixture=True)
        plan, _ = build_plan(f, as_of="2026-11-22", target=8, fixture=True)
        self.assertEqual(8, plan["actual_sample"])
        self.assertTrue(all(s["sample"] == s["population"] or s["sample"] >= 2 for s in plan["strata"]))
        self.assertEqual(12, plan["coverage"]["decision_margins"]["region"]["unknown"])
        self.assertEqual(1, plan["coverage"]["decision_margins"]["conflict"]["present"])

    def test_forms_do_not_expose_status_strata_or_labels(self):
        plan, forms = build_plan(frame(), as_of="2026-11-22", fixture=True)
        for form in forms:
            self.assertEqual({"audit_id", "occurrence_key", "service", "reviewer", "reviewed_at",
                              "independence_attested", "finding", "evidence_refs", "rationale"}, set(form))
            self.assertIsNone(form["finding"])
        self.assertIsNone(plan["validated_accuracy"])
        self.assertIsNone(plan["accuracy_interval"])
        self.assertIsNone(plan["uncertainty"]["unreachable"])
        self.assertEqual(len(forms), plan["uncertainty"]["unreviewed"])

    def test_null_origin_cannot_inflate_evidence_and_unknown_is_explicit(self):
        f = frame()
        row = f["decisions"][0]
        row["mentions"] = [mention(origin=None), mention("synthetic-m2", origin=None)]
        self.assertEqual("unknown", dimensions(row, date(2026, 11, 22))["origins"])
        self.assertEqual("unknown", dimensions(row, date(2026, 11, 22))["repeated_origin"])
        row["independent_origin_ids"] = ["not-observed"]
        with self.assertRaisesRegex(ValueError, "observed origins"):
            validate(f, fixture=True)

    def test_cli_pins_exact_bytes_and_writes_hash_checked_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "frame.json"
            source.write_bytes(canonical(frame(10088, national=True)))
            byte_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            args = [sys.executable, "-m", "research.acquisition.service_readiness_audit.audit", "--frame", str(source),
                    "--frame-sha256", byte_hash, "--freeze-sha256", "a" * 64,
                    "--as-of", "2026-11-22", "--out-dir", str(root / "out")]
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            manifest = json.loads((root / "out/manifest.json").read_text())
            for name, expected in manifest["files"].items():
                self.assertEqual(expected, hashlib.sha256((root / "out" / name).read_bytes()).hexdigest())
            self.assertEqual(30264, json.loads(result.stdout)["denominator"]["decisions"])
            self.assertNotEqual(0, subprocess.run(args, capture_output=True).returncode)
            source.write_bytes(source.read_bytes() + b"\n")
            fail = subprocess.run(args, capture_output=True, text=True)
            self.assertNotEqual(0, fail.returncode)
            self.assertIn("byte hash mismatch", fail.stderr)


if __name__ == "__main__":
    unittest.main()
