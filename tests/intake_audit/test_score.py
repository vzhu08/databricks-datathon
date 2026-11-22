"""Check the audit accounting using invented observations outside the holdout."""

import unittest

from .score import score_case, summarize


def blocked_case():
    return {'id': 'accounting-example', 'steps': ['find'], 'expected': {
        'states': ['needs_more_information'], 'request_service': None, 'finder_calls': 0}}


def observed_block():
    return dict(attempted=True, external_attempts=[], state='more_information_needed',
                request=None, finder_present=False, finder_calls=0, final_calls_measured=True)


class TestScoring(unittest.TestCase):
    def test_distinguishes_unsafe_output_from_calls(self):
        observed = observed_block()
        observed.update(state='ready', finder_present=True)
        row = score_case(blocked_case(), observed)
        self.assertEqual(row['flags'], ['state_mismatch', 'unsafe_recommendation'])
        self.assertEqual(summarize([row])['blocked_finder_call_violations'], 0)

    def test_no_result_does_not_hide_invocation(self):
        observed = observed_block()
        observed.update(finder_calls=1, external_attempts=['socket.connect'])
        row = score_case(blocked_case(), observed)
        self.assertIn('blocked_finder_call', row['flags'])
        self.assertIn('external_call_attempt', row['flags'])
        self.assertEqual(row['status'], 'FAIL')

    def test_unrepresentable_case_is_unmeasured(self):
        row = score_case(blocked_case(), dict(attempted=False, external_attempts=[],
                                              not_run='Unrepresentable input'))
        totals = summarize([row])
        self.assertEqual(totals['pass'], 0)
        self.assertEqual(totals['not_run'], 1)
        self.assertIsNone(totals['state_mismatches'])
        self.assertIsNone(totals['cases_with_external_attempts'])

    def test_blocked_edit_requires_initial_control(self):
        case = blocked_case()
        case['steps'] = ['find_initial', 'find']
        observed = observed_block()
        observed['initial_ready_result'] = False
        self.assertIn('initial_control_failed', score_case(case, observed)['flags'])
