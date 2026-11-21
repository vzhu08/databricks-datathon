from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import IDS, Invalid, load
from rehearsal import rehearse
from simulation import SimulatedStore


class RehearsalTests(unittest.TestCase):
    def test_persistent_protocol_receipt_and_nonempty_store_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SimulatedStore(str(Path(folder) / "rehearsal.sqlite"))
            try:
                def versions():
                    result = {table: store.connection.execute("SELECT count(*) FROM stage WHERE table_name=?",
                              (table,)).fetchone()[0] for table in IDS}
                    return {**result, "enrichment_publication": store.read_state()[0]}
                args = (store, [load(ROOT / "contracts/fixtures/enrichment.json")],
                        load(ROOT / "contracts/fixtures/enrichment_base.json"), "synthetic-rehearsal", "2026-11-21", {}, versions)
                receipt = rehearse(*args)
                self.assertTrue(all(value for key, value in receipt["checks"].items() if isinstance(value, bool)))
                self.assertEqual(receipt["checks"]["original_payload_drift"], 0)
                self.assertEqual(receipt["versions"]["first"]["enrichment_publication"], 1)
                self.assertEqual(receipt["versions"]["interrupted"]["enrichment_publication"], 1)
                self.assertEqual(receipt["versions"]["recovered"]["enrichment_publication"], 2)
                self.assertEqual(store.connection.execute("SELECT count(*) FROM stage").fetchone()[0], 13)
                self.assertEqual(receipt["recovery_manifest"]["parent_run"], "synthetic-rehearsal")
                with self.assertRaisesRegex(Invalid, "newly initialized"):
                    rehearse(*args)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
