"""Run the sealed #133 audit against a pinned, local Git commit."""

import argparse
from contextlib import contextmanager
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import threading

if __package__:
    from .score import PACKET_SHA256, read_packet, score_case, summarize
else:
    from score import PACKET_SHA256, read_packet, score_case, summarize


@contextmanager
def snapshot(repo, sha):
    if not re.fullmatch(r'[a-f0-9]{40}', sha):
        raise ValueError('Supply the full integrated commit SHA from the handoff')
    commit = subprocess.check_output(
        ['git', '-C', str(repo), 'rev-parse', '--verify', sha + '^{commit}'], text=True
    ).strip()
    if commit != sha:
        raise ValueError('The supplied SHA must name the commit itself')
    with tempfile.TemporaryDirectory(prefix='intake-audit-') as temporary:
        root = Path(temporary).resolve()
        # Read committed bytes only. Do not import code or bytecode from an
        # owner checkout, a neighboring worktree, or the harness branch.
        archive = root / 'snapshot.tar'
        subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar',
                        '--output', str(archive), commit], check=True)
        tree = root / 'tree'
        tree.mkdir()
        with tarfile.open(archive) as tar:
            for entry in tar:
                if not entry.isfile() or Path(entry.name).suffix in {'.pyc', '.pyo'}:
                    continue
                target = (tree / entry.name).resolve()
                if tree not in target.parents:
                    raise ValueError('Unexpected archive path')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(entry).read())
        yield tree


class Measurements:
    """Process-wide denials, including imports and every phase of a case."""

    denied_events = {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork',
                     'os.exec', 'socket.__new__', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                     'socket.gethostbyaddr', 'socket.getnameinfo', 'socket.sendto',
                     'socket.sendmsg', 'socket.bind'}

    def __init__(self, tree):
        self.ranker = str(tree / 'app/ranking/urgency.py')
        self.calls = 0
        self.external = []
        self.total_external = 0

    def audit(self, event, args):
        if event in self.denied_events:
            self.external.append(event)
            self.total_external += 1
            raise PermissionError('Disabled for offline intake audit: ' + event)

    def profile(self, frame, event, arg):
        if (event == 'call' and frame.f_code.co_name == 'rank_campuses'
                and frame.f_code.co_filename == self.ranker):
            self.calls += 1


def load_driver(path):
    spec = importlib.util.spec_from_file_location('intake_holdout_driver', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTROL_MANIFEST_SHA256 = '3e7cb26e9a611ae7955c074d5853075d96bd5ea0ffb57abf8f40abcc6929db76'


def release_configuration(tree, independent_controls):
    """Install the fixed audit release only in the temporary candidate snapshot."""
    manifest = tree / 'contracts/intake/reviewed_scenarios.json'
    if not manifest.is_file():
        if independent_controls:
            raise ValueError('Candidate has no reviewed scenario manifest')
        return {}  # Preserve the historical report for the pre-catalogue candidate.

    published_digest = sha256(manifest.read_bytes()).hexdigest()
    active_digest = published_digest
    if independent_controls:
        frozen = (Path(__file__).resolve().parent / 'frozen/control_editions.v1.json').read_bytes()
        active_digest = sha256(frozen).hexdigest()
        if active_digest != CONTROL_MANIFEST_SHA256:
            raise ValueError('Independent control manifest differs from the #133 freeze')
        manifest.write_bytes(frozen)
    return {'release_configuration': {
        'name': 'independent-controls' if independent_controls else 'published',
        'published_manifest_sha256': published_digest,
        'active_manifest_sha256': active_digest,
    }}


def run(args):
    cases = read_packet(args.packet)
    rows = []
    driver_path = args.driver.resolve()
    driver_digest = sha256(driver_path.read_bytes()).hexdigest()
    with snapshot(args.repo, args.sha) as tree:
        configuration = release_configuration(tree, args.independent_controls)
        measures = Measurements(tree)
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(tree))
        sys.addaudithook(measures.audit)
        threading.setprofile(measures.profile)
        sys.setprofile(measures.profile)
        previous = Path.cwd()
        try:
            os.chdir(tree)
            startup_error = None
            try:
                driver = load_driver(driver_path)
                for name, module in tuple(sys.modules.items()):
                    path = getattr(module, '__file__', None)
                    if name.startswith('app.') and path and tree not in Path(path).resolve().parents:
                        raise ValueError(f'{name} loaded from outside the pinned candidate')
            except Exception as exc:
                startup_error = f'{type(exc).__name__}: {exc}'
            initial_events = list(measures.external)
            for case in cases:
                measures.external.clear()
                measures.calls = 0
                observed = {'attempted': False}
                try:
                    # The driver receives inputs and steps only. The scorer alone
                    # sees the sealed expected states, requests and call counts.
                    if startup_error is None:
                        driver.execute(case['setup'], list(case['steps']), measures, observed)
                    else:
                        observed['not_run'] = 'Candidate or driver could not load'
                except Exception as exc:
                    observed['error'] = f'{type(exc).__name__}: {exc}'
                observed['final_calls_measured'] = observed['attempted'] and (
                    'find_initial' not in case['steps'] or 'initial_ready_result' in observed
                )
                observed.update(external_attempts=list(measures.external),
                                finder_calls=measures.calls)
                rows.append(score_case(case, observed))
        finally:
            sys.setprofile(None)
            threading.setprofile(None)
            os.chdir(previous)
    return {**configuration, 'candidate_sha': args.sha, 'packet_sha256': PACKET_SHA256,
            'driver_sha256': driver_digest, 'startup_error': startup_error,
            'import_external_attempts': initial_events,
            'total_external_attempts': measures.total_external,
            'summary': summarize(rows), 'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--independent-controls', action='store_true',
                        help='Install the three pre-reviewed S control editions in the temporary release')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Use a new path to preserve the previous audit receipt')
    result = run(args)
    with args.report.open('x') as report:
        json.dump(result, report, indent=2, allow_nan=False)
        report.write('\n')
    print(json.dumps(result['summary'], indent=2))
    return int(result['summary']['pass'] != result['summary']['total']
               or result['total_external_attempts'] != 0)


if __name__ == '__main__':
    sys.exit(main())
