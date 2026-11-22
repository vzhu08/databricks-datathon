"""Exercise the instrumentation on an accounting fixture outside the holdout."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
import unittest

from .run import CONTROL_MANIFEST_SHA256, release_configuration, snapshot


class TestMeasurements(unittest.TestCase):
    def test_independent_release_replaces_only_snapshot_manifest(self):
        with TemporaryDirectory() as directory:
            tree = Path(directory)
            with self.assertRaisesRegex(ValueError, 'no reviewed scenario manifest'):
                release_configuration(tree, True)
            manifest = tree / 'contracts/intake/reviewed_scenarios.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes(b'{"schema_version":"intake.editions.v1","editions":[]}')
            original = manifest.read_bytes()
            default = release_configuration(tree, False)['release_configuration']
            self.assertEqual(manifest.read_bytes(), original)
            selected = release_configuration(tree, True)['release_configuration']
            self.assertEqual(selected['published_manifest_sha256'], default['active_manifest_sha256'])
            self.assertEqual(selected['active_manifest_sha256'], CONTROL_MANIFEST_SHA256)
            entries = json.loads(manifest.read_bytes())['editions']
            self.assertEqual({entry['scenario_id'] for entry in entries},
                             {'s_audit_complete_dialysis', 's_audit_complete_mri', 's_audit_complete_trauma'})
            self.assertEqual(len(entries), 3)

    def test_ranker_alias_and_denied_attempts_are_counted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ranker = root / 'app/ranking/urgency.py'
            ranker.parent.mkdir(parents=True)
            ranker.write_text('def rank_campuses():\n    return []\n')
            # A fresh process isolates the permanent Python audit hook.
            program = dedent("""
                import json, socket, subprocess, sys
                from pathlib import Path
                from run import Measurements
                root = Path(sys.argv[1])
                measure = Measurements(root)
                sys.path.insert(0, str(root))
                from app.ranking.urgency import rank_campuses as alias
                sys.addaudithook(measure.audit)
                sys.setprofile(measure.profile)
                alias()
                try:
                    socket.socket()
                except PermissionError:
                    pass
                try:
                    subprocess.run(['unused-audit-fixture-executable'])
                except PermissionError:
                    pass
                sys.setprofile(None)
                print(json.dumps([measure.calls, measure.external]))
            """)
            output = subprocess.check_output(
                [sys.executable, '-B', '-c', program, str(root)],
                cwd=Path(__file__).parent, text=True)
            self.assertEqual(json.loads(output), [1, ['socket.__new__', 'subprocess.Popen']])

    def test_reads_pinned_bytes_even_in_dirty_checkout(self):
        with TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            source = repo / 'probe.py'
            source.write_text('pinned')
            subprocess.run(['git', 'add', 'probe.py'], cwd=repo, check=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture'], cwd=repo, check=True)
            sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
            source.write_text('dirty')
            (repo / 'extra.py').write_text('untracked')
            with snapshot(repo, sha) as tree:
                self.assertEqual((tree / 'probe.py').read_text(), 'pinned')
                self.assertFalse((tree / 'extra.py').exists())
