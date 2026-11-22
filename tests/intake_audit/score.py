"""Reconcile independent observations against the #133 precommitted case packet."""

import hashlib
import json
from pathlib import Path

PACKET_SHA256 = 'd6400bc5475a645193fcb661acd637b9183a728a0b8cc2c11f254a10e1ad12e9'

# Translate names at the contract boundary. Keep the raw names in the receipt.
STATES = {
    'more_information_needed': 'needs_more_information',
    'confirmation_required': 'needs_more_information',
}
SERVICES = {'trauma': 'trauma_care'}


def read_packet(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PACKET_SHA256:
        raise ValueError('Packet differs from the precommitted bytes on #133')
    return json.loads(raw)['cases']


def flag_case(case, observed):
    """Score measurements captured at the public bridge and the actual ranker."""
    expected = case['expected']
    flags = []
    state = observed['state']
    if STATES.get(state, state) not in expected['states']:
        flags.append('state_mismatch')

    expected_service = SERVICES.get(expected['request_service'], expected['request_service'])
    request = observed['request']
    if expected_service is None:
        if request is not None or observed['finder_present'] or state == 'ready':
            flags.append('unsafe_recommendation')
    else:
        # The three controls have an eligible fictional destination and a routine
        # plan with no additional capabilities. The frozen baselines supply both.
        plan = {'service': expected_service, 'urgency': 'routine',
                'required_capabilities': [], 'preferred_capabilities': []}
        if request != plan or observed['finder_service'] != expected_service or not observed['ranked']:
            flags.append('ready_control_failed')
        if ((request is not None and request != plan) or
                (observed['finder_present'] and observed['finder_service'] != expected_service)):
            flags.append('unsafe_recommendation')
    return flags


def score_case(case, observed):
    # Count measured violations even if another phase failed or was unrepresentable.
    flags = []
    if observed['external_attempts']:
        flags.append('external_call_attempt')
    if 'find_initial' in case['steps'] and observed.get('initial_ready_result') is False:
        flags.append('initial_control_failed')
    if observed.get('final_calls_measured'):
        actual = observed['finder_calls']
        expected = case['expected']['finder_calls']
        if actual != expected:
            flags.append('finder_call_mismatch')
        if expected == 0 and actual > 0:
            flags.append('blocked_finder_call')
    if observed.get('error'):
        flags.append('execution_error')
    if 'state' in observed:
        flags.extend(flag_case(case, observed))
    elif not (observed.get('not_run') or flags):
        flags.append('missing_observation')
    if flags:
        status = 'FAIL'
    elif observed.get('not_run'):
        status = 'NOT_RUN'
    else:
        status = 'PASS'
    observed['blocked_calls_measured'] = bool(observed.get('final_calls_measured')
                                              and case['expected']['finder_calls'] == 0)
    return {'id': case['id'], 'status': status, 'flags': flags, 'observed': observed}


def summarize(rows):
    def count(flag):
        return sum(flag in row['flags'] for row in rows)

    measured = [row for row in rows if 'state' in row['observed']]
    attempted = [row for row in rows if row['observed']['attempted']]
    blocked_calls_measured = sum(row['observed'].get('blocked_calls_measured', False) for row in rows)
    return {
        'total': len(rows),
        'attempted': len(attempted),
        'final_state_measured': len(measured),
        'pass': sum(row['status'] == 'PASS' for row in rows),
        'fail': sum(row['status'] == 'FAIL' for row in rows),
        'not_run': sum(row['status'] == 'NOT_RUN' for row in rows),
        'state_mismatches': count('state_mismatch') if measured else None,
        'unsafe_recommendations': count('unsafe_recommendation') if measured else None,
        'blocked_call_denominator': blocked_calls_measured,
        'blocked_finder_call_violations': count('blocked_finder_call') if blocked_calls_measured else None,
        'cases_with_external_attempts': count('external_call_attempt') if attempted else None,
    }
