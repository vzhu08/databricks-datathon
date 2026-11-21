import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import Invalid, canonical, digest, empty, load
import prepare_local_export as adapter
from publication import publish
from simulation import SimulatedStore
from source_inspection import verify_base_export


class LocalExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "input.json"
        self.output = self.root / "prepared"
        self.rows = [
            {"id": "002", "name": "  Synthetic Campus B  ", "text": "line one\nline two\t\"quoted\"",
             "nullable": None, "tags": ["a", "b"], "nested": {"active": False}, "lat": 26.0, "lon": 75.0},
            {"id": "001", "name": "सिंथेटिक", "text": "literal \\n; Unicode\u2028separator", "amount": "1.2300"},
        ]
        self.mapping = {"id": "id", "name": "name", "evidence": ["text"], "latitude": "lat", "longitude": "lon"}
        self.input.write_text(json.dumps(self.rows, ensure_ascii=False, indent=2), encoding="utf-8")
        self.options = {"operator": "synthetic-reviewer", "exported_at": "2026-11-21T18:30:00Z",
                        "completeness": "complete", "scope": "Entire synthetic fixture table", "expected_row_count": 2}

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, **options):
        return adapter.prepare_export(self.input, "json", "synthetic.fixture.facilities", self.mapping,
                                      self.output, **{**self.options, **options})

    def assert_unpublished(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["input.json"])

    def test_preserves_leading_zero_ids_all_fields_text_and_raw_bytes(self):
        original = self.input.read_bytes()
        metadata = self.prepare()
        base = load(self.output / "base.json")
        self.assertEqual([r["facility_id"] for r in base], ["001", "002"])
        self.assertEqual([r["source_row"] for r in base], sorted(self.rows, key=lambda r: r["id"]))
        self.assertEqual((self.output / "source_export.json").read_bytes(), original)
        self.assertEqual(self.input.read_bytes(), original)
        self.assertEqual(metadata["source_rows_sha256"], digest(sorted(self.rows, key=canonical)))
        self.assertEqual(metadata["operator_export"]["ordered_rows_sha256"], digest(self.rows))
        self.assertEqual(metadata["operator_export"]["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(metadata["base_file_sha256"], hashlib.sha256((self.output / "base.json").read_bytes()).hexdigest())
        self.assertEqual(metadata["row_count"], 2)
        self.assertEqual(metadata["snapshot_mode"], "operator_supplied_export")
        self.assertIsNone(metadata["schema"])
        self.assertIsNone(metadata["observed_delta_version"])
        self.assertIsNone(metadata["inspected_at"])
        self.assertEqual(metadata["observed_json_types"]["nested"], ["object"])
        self.assertEqual((self.output / "base.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)

    def test_jsonl_preserves_crlf_unicode_and_final_newline(self):
        raw = ("\r\n".join(json.dumps(r, ensure_ascii=False) for r in self.rows) + "\r\n").encode("utf-8")
        self.input.write_bytes(raw)
        metadata = adapter.prepare_export(self.input, "jsonl", "synthetic.fixture.facilities", self.mapping,
                                          self.output, **self.options)
        self.assertEqual((self.output / "source_export.jsonl").read_bytes(), raw)
        verify_base_export(load(self.output / "base.json"), metadata)

    def test_existing_consumer_accepts_prepared_pair_and_retains_partial_scope(self):
        metadata = self.prepare(completeness="partial", expected_row_count=10, scope="Synthetic selected region")
        base = load(self.output / "base.json")
        verify_base_export(base, load(self.output / "source_metadata.json"))
        store = SimulatedStore(str(self.root / "consumer.sqlite"))
        try:
            manifest = publish(store, [empty()], base, "synthetic-local-export", "2026-11-21", source_metadata=metadata)
            self.assertEqual(manifest["base_rows"], 2)
            self.assertEqual(manifest["source_metadata"]["operator_export"]["completeness"], "partial")
            self.assertEqual(manifest["source_metadata"]["operator_export"]["missing_row_count"], 8)
        finally:
            store.close()

    def test_duplicate_ids_including_exact_repeat_and_numeric_string_collision(self):
        for values in (("001", "001"), (1, "1")):
            with self.subTest(values=values):
                rows = copy.deepcopy(self.rows)
                rows[0]["id"], rows[1]["id"] = values
                self.input.write_text(json.dumps(rows))
                with self.assertRaisesRegex(Invalid, "duplicate base ID"):
                    self.prepare()
                self.assert_unpublished()

    def test_missing_empty_null_boolean_and_fractional_ids_fail_without_output(self):
        for value in (None, "", " ", True, 1.5):
            with self.subTest(value=value):
                rows = copy.deepcopy(self.rows)
                rows[0]["id"] = value
                self.input.write_text(json.dumps(rows))
                with self.assertRaisesRegex(Invalid, "source ID"):
                    self.prepare()
                self.assert_unpublished()
        del rows[0]["id"]
        self.input.write_text(json.dumps(rows))
        with self.assertRaisesRegex(Invalid, "source ID"):
            self.prepare()

    def test_integer_ids_preserve_original_type_and_full_precision(self):
        self.rows[0]["id"] = 9007199254740993
        self.input.write_text(json.dumps(self.rows))
        self.prepare()
        large = next(r for r in load(self.output / "base.json") if r["facility_id"] == "9007199254740993")
        self.assertEqual(large["source_row"]["id"], 9007199254740993)
        self.assertIsInstance(large["source_row"]["id"], int)

    def test_mapping_must_be_explicit_and_observed(self):
        for mapping in ({}, {"id": "guessed"}, {"id": "id", "evidence": ["guessed"]}):
            self.mapping = mapping
            with self.assertRaisesRegex(Invalid, "mapping"):
                self.prepare()
            self.assert_unpublished()

    def test_complete_requires_independent_matching_count(self):
        for count in (None, 1, 3):
            with self.subTest(count=count), self.assertRaises(Invalid):
                self.prepare(expected_row_count=count)
            self.assert_unpublished()

    def test_partial_and_unknown_do_not_invent_missing_count_or_source_version(self):
        metadata = self.prepare(completeness="unknown", expected_row_count=None, reported_delta_version=7)
        self.assertIsNone(metadata["operator_export"]["missing_row_count"])
        self.assertIsNone(metadata["observed_delta_version"])
        self.assertEqual(metadata["operator_export"]["reported_delta_version"], 7)
        self.assertIn("unverified", metadata["warning"])

    def test_partial_count_must_not_claim_all_rows(self):
        with self.assertRaisesRegex(Invalid, "partial label"):
            self.prepare(completeness="partial")
        self.assert_unpublished()

    def test_malformed_truncated_duplicate_key_and_nonfinite_inputs_fail(self):
        for raw in (b'[{"id":"001"}', b'[{"id":"001","id":"002"}]', b'[{"id":"001","x":NaN}]',
                    b'[{"id":"001","x":Infinity}]', b'[{"id":"001","x":1e400}]', b'[{"id":"001","x":1e-5000}]',
                    b'[{"id":"001","x":0.1234567890123456789}]', b'[{"id":"001","text":"\xff"}]',
                    b'[{"id":"001","text":"\\ud800"}]', b'[]', b'{}', b'[1]'):
            with self.subTest(raw=raw):
                self.input.write_bytes(raw)
                with self.assertRaises(Invalid):
                    self.prepare(completeness="partial", expected_row_count=None)
                self.assert_unpublished()

    def test_jsonl_truncated_last_row_and_blank_row_rejected(self):
        for raw in (b'{"id":"001"}\n{"id":', b'{"id":"001"}\n\n{"id":"002"}\n'):
            with self.assertRaises(Invalid):
                adapter.parse_rows(raw, "jsonl")

    def test_limits_reject_instead_of_truncating(self):
        for options in ({"max_rows": 1}, {"max_bytes": 10}):
            with self.assertRaises(Invalid):
                self.prepare(**options)
            self.assert_unpublished()

    def test_operator_metadata_is_explicit_and_validated(self):
        for options in ({"operator": " "}, {"scope": ""}, {"exported_at": "2026-02-30T12:00:00Z"},
                        {"exported_at": "2026-11-21"}, {"reported_delta_version": -1}):
            with self.assertRaises(Invalid):
                self.prepare(**options)
            self.assert_unpublished()

    def test_failure_after_first_write_leaves_no_final_or_staging_directory(self):
        real_write = adapter._write_bytes
        written = []
        def fail_second(path, content):
            if written:
                raise OSError("synthetic disk interruption")
            real_write(path, content)
            written.append(path)
        with patch.object(adapter, "_write_bytes", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "disk interruption"):
                self.prepare()
        self.assertEqual(len(written), 1)
        self.assert_unpublished()
        self.prepare()  # Same destination is recoverable after exception cleanup.

    def test_failed_readback_cleans_partial_output(self):
        real_verify = adapter.verify_base_export
        calls = []
        def fail_readback(base, metadata):
            calls.append(True)
            if len(calls) == 2:
                raise Invalid("synthetic readback mismatch")
            real_verify(base, metadata)
        with patch.object(adapter, "verify_base_export", side_effect=fail_readback):
            with self.assertRaisesRegex(Invalid, "readback mismatch"):
                self.prepare()
        self.assert_unpublished()

    def test_destination_never_overwritten_and_lock_collision_fails(self):
        self.prepare()
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with self.assertRaisesRegex(Invalid, "already exists"):
            self.prepare()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})
        other = self.root / "other"
        (self.root / ".other.lock").write_text("synthetic other writer")
        with self.assertRaisesRegex(Invalid, "lock"):
            adapter.prepare_export(self.input, "json", "synthetic.fixture.facilities", self.mapping, other, **self.options)
        self.assertFalse(other.exists())

    def test_base_tampering_detected_by_existing_consumer(self):
        metadata = self.prepare()
        base = load(self.output / "base.json")
        base[0]["source_row"]["text"] = "modified original"
        with self.assertRaisesRegex(Invalid, "original fields/text changed"):
            verify_base_export(base, metadata)

    def test_cli_scoped_output_and_existing_validation_cli(self):
        local = ROOT / "data/local"
        local.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="acq-d02-test-", dir=local) as tmp:
            mapping = Path(tmp) / "mapping.json"
            mapping.write_text(json.dumps(self.mapping))
            out = Path(tmp) / "prepared"
            cmd = [sys.executable, str(ROOT / "databricks/enrichment/prepare_local_export.py"),
                   "--input", str(self.input), "--format", "json", "--mapping", str(mapping),
                   "--source-table", "synthetic.fixture.facilities", "--operator", "synthetic-reviewer",
                   "--exported-at", "2026-11-21T18:30:00Z", "--completeness", "complete",
                   "--expected-row-count", "2", "--scope", "Entire synthetic fixture"]
            result = subprocess.run(cmd + ["--output-dir", str(out)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["base_rows"], 2)
            self.assertNotIn("Campus", result.stdout)
            envelope = Path(tmp) / "empty.json"
            envelope.write_text(canonical(empty()))
            validation = subprocess.run([sys.executable, str(ROOT / "databricks/enrichment/validate_batch.py"),
                "--base", str(out / "base.json"), "--batch", str(envelope), "--as-of", "2026-11-21"],
                cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(validation.returncode, 0, validation.stderr)
            rejected = subprocess.run(cmd + ["--output-dir", str(self.root / "not-ignored")],
                                      cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("data/local", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
