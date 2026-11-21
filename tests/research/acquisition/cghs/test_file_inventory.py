import tempfile
import unittest
from pathlib import Path

from research.acquisition.cghs.file_inventory import inventory
from research.acquisition.common import AcquisitionError, digest


class FileInventoryTests(unittest.TestCase):
    def test_hash_disposition_and_unknown_defaults_do_not_authorize_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "code.py").write_bytes(b"# synthetic code\n")
            (root / "unknown.txt").write_bytes(b"synthetic unknown\n")
            result = inventory({"fixture": root}, {"fixture/code.py": {
                "disposition": "candidate_code_synthetic", "reason": "Invented code fixture"}})
            self.assertEqual(result["file_count"], 2)
            self.assertEqual(result["files"][0]["sha256"], digest(b"# synthetic code\n"))
            self.assertEqual(result["files"][1]["disposition"], "hold_unclassified")
            self.assertTrue(all(not f["transfer_authorized"] for f in result["files"]))
            self.assertFalse(result["transfer_performed"])
            self.assertEqual(len(list(root.iterdir())), 2)

    def test_stale_decision_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(AcquisitionError, "decision_has_no_file"):
                inventory({"fixture": root}, {"fixture/gone": {"disposition": "hold_rights", "reason": "Synthetic hold"}})
            (root / "target.txt").write_text("synthetic")
            (root / "link.txt").symlink_to(root / "target.txt")
            with self.assertRaisesRegex(AcquisitionError, "symlink_requires_review"):
                inventory({"fixture": root}, {})
