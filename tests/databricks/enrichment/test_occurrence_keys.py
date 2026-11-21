"""Synthetic rows under the explicitly reviewed snapshot policy."""
import hashlib
import json
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import Invalid, canonical, digest
from occurrence_keys import POLICY, SOURCE, map_occurrences
from source_inspection import map_base, verify_base_export


class OccurrenceKeys(unittest.TestCase):
    def setUp(self):
        self.rows = [{"unique_id": "001", "name": "  Synthetic singleton  ", "value": None},
                     {"unique_id": "002", "name": "Synthetic pair", "value": None},
                     {"unique_id": "002", "name": "Synthetic pair", "value": None}]

    def mapped(self, rows=None, **overrides):
        args = dict(id_policy=POLICY, source_version=0)
        args.update(overrides)
        return map_base(self.rows if rows is None else rows, "unique_id", SOURCE, **args)

    def metadata(self):
        return {"mapping": {"id": "unique_id"}, "original_table": SOURCE, "observed_delta_version": 0,
                "id_policy": POLICY, "row_count": len(self.rows),
                "source_rows_sha256": digest(sorted(self.rows, key=canonical))}

    def test_exact_reviewed_hash_and_original_singleton(self):
        base = self.mapped()
        expected = {"001"}
        for ordinal in ("1", "2"):
            wire = json.dumps([SOURCE, "0", "002", ordinal], ensure_ascii=False, separators=(",", ":"))
            expected.add("base-occurrence:" + hashlib.sha256(wire.encode("utf-8")).hexdigest())
        self.assertEqual({r["facility_id"] for r in base}, expected)
        self.assertEqual(sorted([r["source_row"] for r in base], key=canonical), sorted(self.rows, key=canonical))

    def test_reordered_rows_replay_identically(self):
        shuffled = self.rows[:]
        random.Random(19).shuffle(shuffled)
        self.assertEqual(self.mapped(shuffled), self.mapped())
        verify_base_export(self.mapped(), self.metadata())

    def test_shared_group_retains_all_occurrences(self):
        base, groups = map_occurrences(self.rows, "unique_id", SOURCE, 0, POLICY)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["multiplicity"], 2)
        self.assertEqual(groups[0]["original_unique_id"], "002")
        self.assertEqual(set(groups[0]["facility_ids"]), {r["facility_id"] for r in base if r["source_row"]["unique_id"] == "002"})

    def test_three_identical_occurrences_are_not_dropped(self):
        rows = self.rows + [dict(self.rows[-1])]
        base, groups = map_occurrences(rows, "unique_id", SOURCE, 0, POLICY)
        self.assertEqual(len(base), 4)
        self.assertEqual(groups[0]["multiplicity"], 3)

    def test_default_duplicate_rejection_remains(self):
        with self.assertRaisesRegex(Invalid, "duplicate base ID"):
            map_base(self.rows, "unique_id", SOURCE)

    def test_changed_payload_requires_review(self):
        changed = [dict(row) for row in self.rows]
        changed[-1]["name"] += " different"
        with self.assertRaisesRegex(Invalid, "different-payload"):
            self.mapped(changed)

    def test_null_and_missing_fields_are_different_payloads(self):
        changed = [dict(row) for row in self.rows]
        del changed[-1]["value"]
        with self.assertRaisesRegex(Invalid, "different-payload"):
            self.mapped(changed)

    def test_wrong_snapshot_policy_or_id_mapping_rejected(self):
        for version in (None, 1, "0", False):
            with self.subTest(version=version), self.assertRaisesRegex(Invalid, "version 0"):
                self.mapped(source_version=version)
        with self.assertRaisesRegex(Invalid, "unknown occurrence"):
            self.mapped(id_policy="unreviewed")
        with self.assertRaises(Invalid):
            map_base(self.rows, "unique_id", "synthetic.other.table", id_policy=POLICY, source_version=0)
        with self.assertRaises(Invalid):
            map_base(self.rows, None, SOURCE, id_policy=POLICY, source_version=0)
        with self.assertRaises(Invalid):
            self.mapped(allow_surrogate=True)

    def test_retained_id_cannot_collide_with_generated_key(self):
        collision = next(r["facility_id"] for r in self.mapped() if r["facility_id"] != "001")
        with self.assertRaisesRegex(Invalid, "key collision"):
            self.mapped(self.rows + [{"unique_id": collision, "name": "Synthetic collision"}])

    def test_missing_or_nontext_ids_fail(self):
        for value in (None, "", " ", 2, False):
            with self.subTest(value=value), self.assertRaisesRegex(Invalid, "nonempty text"):
                self.mapped([{"unique_id": value}])

    def test_verifier_rejects_changed_keys_rows_and_policy(self):
        base = self.mapped()
        base[0]["facility_id"] = "changed"
        with self.assertRaisesRegex(Invalid, "mapped IDs"):
            verify_base_export(base, self.metadata())
        base = self.mapped()
        base.pop()
        with self.assertRaisesRegex(Invalid, "row count"):
            verify_base_export(base, self.metadata())
        metadata = self.metadata()
        metadata["observed_delta_version"] = 1
        with self.assertRaisesRegex(Invalid, "version 0"):
            verify_base_export(self.mapped(), metadata)


if __name__ == "__main__":
    unittest.main()
