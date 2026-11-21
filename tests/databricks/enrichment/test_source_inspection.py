from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import Invalid, canonical, digest
from delta_store import identifier, volume_path
from source_inspection import map_base, profile_rows, verify_base_export


class SourceInspectionTests(unittest.TestCase):
    def test_identifier_injection_and_part_count(self):
        self.assertEqual(identifier("catalog.schema.table", 3), "`catalog`.`schema`.`table`")
        for bad in ("foo; DROP TABLE x", "a.b", "`a`", "a b", "a--b", "a.b.c.d"):
            with self.subTest(value=bad), self.assertRaises(Invalid):
                identifier(bad, 3)

    def test_volume_paths_cannot_escape(self):
        self.assertEqual(volume_path("/Volumes/catalog/schema/volume/input.json"),
                         "/Volumes/catalog/schema/volume/input.json")
        for bad in ("/tmp/data", "/Volumes/c/s/v/../secret", "/Volumes/c/s/v", "/Volumes/c/s/v\\file"):
            with self.subTest(value=bad), self.assertRaises(Invalid):
                volume_path(bad)

    def test_original_text_and_ids_preserved_and_verified(self):
        rows = [{"raw_id": "001", "name": "  Example Campus  ", "evidence": "exact\noriginal text", "amount": Decimal("1.2300")}]
        mapped = map_base(rows, "raw_id", "synthetic.source")
        self.assertEqual(mapped[0]["facility_id"], "001")
        self.assertEqual(mapped[0]["source_row"]["name"], rows[0]["name"])
        self.assertEqual(mapped[0]["source_row"]["evidence"], rows[0]["evidence"])
        self.assertEqual(mapped[0]["source_row"]["amount"], "1.2300")
        meta = {"row_count": 1, "source_rows_sha256": digest([mapped[0]["source_row"]])}
        verify_base_export(mapped, meta)
        mapped[0]["source_row"]["evidence"] = "edited"
        with self.assertRaisesRegex(Invalid, "original fields/text changed"):
            verify_base_export(mapped, meta)

    def test_source_surrogate_requires_opt_in_and_identical_rows_fail(self):
        rows = [{"name": "synthetic campus", "address": "A"}, {"name": "synthetic campus", "address": "B"}]
        with self.assertRaisesRegex(Invalid, "explicitly approve"):
            map_base(rows, None, "synthetic.source")
        self.assertEqual(map_base(rows, None, "synthetic.source", True),
                         map_base(list(reversed(rows)), None, "synthetic.source", True))
        with self.assertRaisesRegex(Invalid, "duplicate base ID"):
            map_base([rows[0], rows[0]], None, "synthetic.source", True)

    def test_profile_counts_missing_duplicate_postal_and_bad_coordinates(self):
        rows = [{"id": "1", "pin": "123456", "lat": 26, "lon": 75, "text": "synthetic"},
                {"id": "1", "pin": "123456", "lat": float("nan"), "lon": 75, "text": None},
                {"id": None, "pin": None, "lat": 91, "lon": 75, "text": ""},
                {"id": "2", "pin": "234567", "lat": None, "lon": None, "text": None}]
        result = profile_rows(rows, {"id": "id", "pin": "pin", "latitude": "lat", "longitude": "lon", "evidence": ["text"]})
        self.assertEqual(result["row_count"], 4)
        self.assertEqual(result["duplicate_id_rows"], 1)
        self.assertEqual(result["missing_by_column"]["text"], 3)
        self.assertEqual(result["postal_context"]["rows_beyond_first_per_pin"], 1)
        self.assertEqual(result["postal_context"]["max_rows_per_pin"], 2)
        self.assertEqual(result["coordinate_counts"], {"valid_wgs84": 1, "invalid_or_nonfinite": 1, "outside_wgs84": 1, "missing_or_incomplete": 1})

    def test_unknown_mapping_fails_without_guess(self):
        with self.assertRaisesRegex(Invalid, "observed columns"):
            profile_rows([{"name": "Synthetic"}], {"id": "invented_id"})


if __name__ == "__main__":
    unittest.main()
