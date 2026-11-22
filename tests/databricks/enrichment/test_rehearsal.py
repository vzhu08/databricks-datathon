import ast
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import IDS, Invalid, load
from rehearsal import rehearse
from simulation import SimulatedStore


class RehearsalTests(unittest.TestCase):
    def test_notebook_preserves_bootstrap_path_and_job_parameters(self):
        class Widgets:
            def __init__(self):
                self.values = {"repo_root": str(ROOT), "output_catalog": "workspace",
                               "run_id": "synthetic-rehearsal"}

            def getAll(self):
                return dict(self.values)

            def text(self, name, default):
                self.values[name] = default

            def get(self, name):
                return self.values[name]

        notebook = ROOT / "databricks/enrichment/notebooks/04_private_rehearsal.py"
        tree = ast.parse(notebook.read_text())
        boundary = next(i for i, node in enumerate(tree.body)
                        if isinstance(node, ast.ImportFrom) and node.module == "common")
        startup = ast.Module(body=tree.body[:boundary], type_ignores=[])
        widgets = Widgets()
        existing = dict(widgets.values)
        namespace = {"dbutils": SimpleNamespace(widgets=widgets)}
        old_path = sys.path[:]
        try:
            exec(compile(startup, str(notebook), "exec"), namespace)
        finally:
            sys.path[:] = old_path
        self.assertEqual(namespace["repo_root"], ROOT)
        self.assertTrue(all(widgets.values[key] == value for key, value in existing.items()))
        self.assertEqual(widgets.values["confirm_private_rehearsal"], "")

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
