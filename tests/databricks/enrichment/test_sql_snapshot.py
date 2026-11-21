import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import Invalid
from export_sql_snapshot import collect_chunks, verify_receipt


class SqlSnapshot(unittest.TestCase):
    def response(self):
        return {"statement_id": "synthetic-statement", "status": {"state": "SUCCEEDED"},
                "manifest": {"format": "JSON_ARRAY", "truncated": False, "schema": {"column_count": 1},
                             "total_row_count": 2, "total_chunk_count": 2},
                "result": {"chunk_index": 0, "row_offset": 0, "row_count": 1,
                           "data_array": [['{"unique_id":"001","name":"Synthetic","missing":null}']],
                           "next_chunk_internal_link": "/api/2.0/sql/statements/synthetic-statement/result/chunks/1"}}

    def second(self):
        return {"chunk_index": 1, "row_offset": 1, "row_count": 1,
                "data_array": [['{"unique_id":"002","name":"Synthetic \\u2028","value":1.25}']]}

    def test_all_chunks_preserve_native_json_text(self):
        second = self.second()
        values = collect_chunks(self.response(), lambda _: second)
        self.assertEqual(values[1], second["data_array"][0][0])
        self.assertIsNone(json.loads(values[0])["missing"])
        self.assertEqual(len(values), 2)

    def test_truncated_or_failed_results_rejected(self):
        for field in ("truncated", "failed"):
            response = self.response()
            if field == "truncated": response["manifest"]["truncated"] = True
            else: response["status"]["state"] = "FAILED"
            with self.subTest(field=field), self.assertRaises(Invalid):
                collect_chunks(response, lambda _: self.fail("must reject before chunk fetch"))

    def test_missing_repeated_or_wrong_offset_chunks_rejected(self):
        for field, value in (("chunk_index", 0), ("row_offset", 0), ("row_count", 2)):
            second = self.second(); second[field] = value
            with self.subTest(field=field), self.assertRaises(Invalid):
                collect_chunks(self.response(), lambda _: second)
        response = self.response()
        del response["result"]["next_chunk_internal_link"]
        with self.assertRaisesRegex(Invalid, "incomplete"):
            collect_chunks(response, lambda _: self.second())

    def test_changed_statement_and_bad_source_row_shape_rejected(self):
        response = self.response()
        response["result"]["next_chunk_internal_link"] = "/api/2.0/sql/statements/other/result/chunks/1"
        with self.assertRaisesRegex(Invalid, "changed statement"):
            collect_chunks(response, lambda _: self.second())
        response = self.response()
        response["result"]["data_array"] = [[None]]
        with self.assertRaisesRegex(Invalid, "serialized source-row"):
            collect_chunks(response, lambda _: self.second())

    def test_receipt_hash_and_each_payload_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b'{"synthetic":true}'
            (root / "metadata.json").write_bytes(payload)
            manifest = json.dumps({"files": [{"file": "metadata.json", "bytes": len(payload),
                                             "sha256": hashlib.sha256(payload).hexdigest()}]}).encode()
            (root / "manifest.json").write_bytes(manifest)
            with patch('export_sql_snapshot.RECEIPT_SHA', hashlib.sha256(manifest).hexdigest()):
                verify_receipt(root)
                (root / "metadata.json").write_bytes(b'changed')
                with self.assertRaisesRegex(Invalid, "hash or size"):
                    verify_receipt(root)


if __name__ == "__main__":
    unittest.main()
