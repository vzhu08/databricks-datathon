"""Exercise the instrumentation on an accounting fixture outside the holdout."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
import unittest

from .run import snapshot


class TestMeasurements(unittest.TestCase):
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
