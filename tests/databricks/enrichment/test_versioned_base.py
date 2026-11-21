import copy
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import Invalid, canonical, digest, load
from export_sql_snapshot import POSTAL
from occurrence_keys import SOURCE
from prepare_versioned_base import MAPPING, finalize, prepare_rows, replay
from source_inspection import verify_base_export


class WindowsRelativePath(type(Path())):
    """Exercise Windows relative-path formatting with real files on any host."""
    def relative_to(self, *other):
        return PureWindowsPath(*super().relative_to(*other).parts)


class VersionedBase(unittest.TestCase):
    def setUp(self):
        fields = set(v for k, v in MAPPING.items() if k != "evidence") | set(MAPPING["evidence"])
        singleton = dict.fromkeys(fields)
        singleton.update(unique_id="001", name="  Synthetic singleton  ", address_zipOrPostcode=" 123456 ")
        twin = dict(singleton, unique_id="002", name="Synthetic pair", address_zipOrPostcode="invalid")
        self.facilities = [singleton, twin, dict(twin)]
        self.postal = [{"pincode": 123456, "statename": "Synthetic", "district": "Example", "officename": "A"},
                       {"pincode": 123456, "statename": "Synthetic", "district": "Example", "officename": "B"},
                       {"pincode": 234567, "statename": "Synthetic", "district": "Example", "officename": "C"}]
        self.fm = self.metadata(self.facilities, SOURCE)
        self.pm = self.metadata(self.postal, POSTAL)

    def metadata(self, rows, table):
        return {"original_table": table, "observed_delta_version": 0, "row_count": len(rows),
                "schema": {"columns": [{"name": k} for k in sorted(rows[0])]},
                "source_rows_sha256": digest(sorted(rows, key=canonical))}

    def result(self, facilities=None, postal=None):
        return prepare_rows(self.facilities if facilities is None else facilities,
                            self.postal if postal is None else postal, self.fm, self.pm, "0" * 64, "2026-11-21T00:00:00Z")

    def test_every_source_row_and_original_text_preserved(self):
        before = copy.deepcopy(self.facilities)
        result = self.result()
        self.assertEqual(self.facilities, before)
        self.assertEqual(sorted([r['source_row'] for r in result['base']], key=canonical), sorted(before, key=canonical))
        verify_base_export(result['base'], result['source_metadata'])
        self.assertEqual(result['validation_report']['lost_source_rows'], 0)
        self.assertEqual(result['validation_report']['added_source_rows'], 0)

    def test_postal_duplicates_do_not_multiply_base(self):
        result = self.result()
        report = result['validation_report']
        self.assertEqual(report['grouped_pin_lookup_rows'], 3)
        self.assertEqual(report['base_rows_with_postal_context'], 1)
        self.assertEqual(report['distinct_postal_pins'], 2)
        self.assertEqual(report['max_postal_rows_per_pin'], 2)
        self.assertEqual(len(result['postal_rows']), 3)
        self.assertEqual(result['source_metadata']['mapping']['pin'], 'address_zipOrPostcode')

    def test_reordered_inputs_have_byte_identical_outputs(self):
        expected = self.result()
        actual = self.result(list(reversed(self.facilities)), list(reversed(self.postal)))
        self.assertEqual(canonical(actual), canonical(expected))

    def test_source_and_postal_hash_changes_fail(self):
        changed = copy.deepcopy(self.facilities)
        changed[0]['name'] = 'Changed synthetic text'
        with self.assertRaisesRegex(Invalid, 'original fields/text'):
            self.result(facilities=changed)
        changed = copy.deepcopy(self.postal)
        changed[0]['officename'] = 'Changed'
        with self.assertRaisesRegex(Invalid, 'postal multiset'):
            self.result(postal=changed)

    def test_sidecar_binds_shared_handles_without_extra_campuses(self):
        result = self.result()
        groups = result['duplicate_groups']
        self.assertEqual(result['source_metadata']['duplicate_groups_sha256'], digest(groups))
        self.assertEqual(result['validation_report']['distinct_full_payloads'], 2)
        self.assertEqual(result['validation_report']['occurrence_keys'], 2)
        self.assertIn('not separate campuses', result['validation_report']['duplicate_meaning'])
        self.assertEqual(set(groups[0]['facility_ids']),
                         {r['facility_id'] for r in result['base'] if r['source_row']['unique_id'] == '002'})

    def test_manifest_replay_no_overwrite_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('prepare_versioned_base.local_output', side_effect=lambda p: Path(p)), \
                    patch('prepare_versioned_base.derive', return_value=self.result()):
                finalize(root)
                self.assertEqual(replay(root)['status'], 'byte_identical_replay')
                with self.assertRaisesRegex(Invalid, 'already exist'):
                    finalize(root)
                (root / 'duplicate_groups.json').write_text('[]')
                with self.assertRaisesRegex(Invalid, 'hash mismatch'):
                    replay(root)

    def test_writer_uses_posix_manifest_paths_on_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = WindowsRelativePath(tmp)
            (root / 'raw').mkdir()
            (root / 'raw/part.jsonl').write_text('{}\n', encoding='utf-8')
            self.assertEqual(str(next((root / 'raw').rglob('*')).relative_to(root)), r'raw\part.jsonl')
            with patch('prepare_versioned_base.local_output', return_value=root), \
                    patch('prepare_versioned_base.derive', return_value=self.result()):
                finalize(root)
            files = load(root / 'prepared_manifest.json')['files']
            self.assertIn('raw/part.jsonl', files)
            self.assertTrue(all('\\' not in name for name in files))

    def test_posix_produced_package_replays_with_windows_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'raw').mkdir()
            (root / 'raw/part.jsonl').write_text('{}\n', encoding='utf-8')
            with patch('prepare_versioned_base.local_output', return_value=root), \
                    patch('prepare_versioned_base.derive', return_value=self.result()):
                finalize(root)
                manifest = load(root / 'prepared_manifest.json')
                # Freeze the producer's POSIX spelling independently of this host.
                manifest['files'] = {name.replace('\\', '/'): sha for name, sha in manifest['files'].items()}
                (root / 'prepared_manifest.json').write_bytes(canonical(manifest).encode('utf-8'))
                before = (root / 'prepared_manifest.json').read_bytes()
                with patch('prepare_versioned_base.local_output', return_value=WindowsRelativePath(root)):
                    self.assertEqual(replay(root)['status'], 'byte_identical_replay')
                self.assertEqual((root / 'prepared_manifest.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
