"""Replay the shipped journeys using the candidate's published scenario manifest."""

import argparse
import hashlib
import json
import sys
import unittest
from pathlib import Path

from run import Measurements, release_configuration, snapshot


def check_release(tree, commit):
    config = release_configuration(tree, False)
    measures = Measurements(tree)
    sys.path.insert(0, str(tree))
    sys.addaudithook(measures.audit)
    sys.setprofile(measures.profile)
    try:
        from app.intake.__main__ import load_journeys
        from tests.intake.test_scenarios import ScenarioFixtureTests
        from tests.intake_e2e.test_cli import IntakeCliTests

        fixture, fixture_hash = load_journeys()
        scripts = fixture['scenarios']
        pins = json.loads((tree / 'contracts/intake/reviewed_scenarios.json').read_bytes())
        expected_pins = []
        for script in scripts.values():
            canonical = json.dumps(script, sort_keys=True, ensure_ascii=True,
                                   separators=(',', ':'), allow_nan=False).encode('ascii')
            expected_pins.append({'scenario_id': script['scenario_id'],
                                  'scenario_version': script['scenario_version'],
                                  'sha256': hashlib.sha256(canonical).hexdigest()})
        by_id = lambda entry: entry['scenario_id']
        if len(scripts) != 7 or sorted(expected_pins, key=by_id) != sorted(pins['editions'], key=by_id):
            raise ValueError('Published pins do not exactly cover the seven shipped editions')

        # R's existing suite checks returned states, ranked IDs and the per-step
        # call count for each journey. Use that suite on the extracted candidate.
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(ScenarioFixtureTests)
        tests.addTest(IntakeCliTests('test_blocked_paths_never_reach_the_ranker'))
        result = unittest.TextTestRunner(verbosity=1).run(tests)
    finally:
        sys.setprofile(None)
    traces = fixture['journeys'].values()
    all_steps = [step for steps in traces for step in steps]
    return {**config, 'candidate_sha': commit, 'fixture_sha256': fixture_hash,
            'scenarios': sorted(scripts), 'journeys': list(fixture['journeys']),
            'transitions': len(all_steps),
            'expected_ranked_transitions': sum(step['expected']['request'] is not None for step in all_steps),
            'expected_blocked_transitions': sum(step['expected']['request'] is None for step in all_steps),
            'observed_ranker_calls_across_both_replays': measures.calls,
            'external_attempts': measures.total_external,
            'tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
            'skips': len(result.skipped)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    with snapshot(args.repo, args.sha) as tree:
        report = check_release(tree, args.sha)
    with args.report.open('x') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print(json.dumps(report, indent=2))
    sys.exit(int(any(report[key] for key in ('errors', 'failures', 'skips', 'external_attempts'))))
