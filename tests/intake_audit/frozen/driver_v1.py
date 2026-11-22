"""S's held-out translation of frozen case steps to the approved v1 interface."""

from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch

from app.intake import assessment as engine
from app.intake.finder_bridge import find_care_for_intake


SERVICES = {
    'dialysis': ('dialysis', 'dialysis_plan', 'simulated_treatment_plan'),
    'mri': ('mri', 'mri_referral', 'simulated_clinician_referral'),
    'trauma': ('trauma_care', 'injury', 'simulated_clinician_assessment'),
}
WARNINGS = ['chest_pain', 'stroke_like', 'severe_breathing_difficulty',
            'unresponsive', 'heavy_bleeding']


def warning_key(sign):
    return 'warning.' + ('severe_breathing_difficulty' if sign == 'severe_breathing' else sign)


def baseline(name):
    service_name = name.removeprefix('complete_')
    authority = None
    service = None
    concern = 'other'
    if name != 'no_clinician_authority':
        service, concern, authority = SERVICES[service_name]
    scenario_id = 's_audit_' + name
    scenario = {
        'schema_version': 'intake.scenario.v1', 'scenario_id': scenario_id,
        'scenario_version': '1', 'synthetic': True, 'service': service,
        'presenting_problem': 'Fictional adult for a software demonstration.',
        'concern_category': concern, 'known_answers': {},
        'clinician_plan': None if authority is None else {
            'scenario_id': scenario_id, 'scenario_version': '1', 'synthetic': True,
            'service': service, 'authority': authority, 'urgency': 'routine',
            'required_capabilities': [], 'preferred_capabilities': [],
        },
    }
    answers = {warning_key(sign): 'no' for sign in WARNINGS}
    answers.update({'context.age_group': 'adult', 'context.pregnancy': 'not_pregnant',
                    'context.onset': 'scheduled', 'context.severity': 'mild'})
    payload = {'schema_version': 'intake.v1', 'mode': 'synthetic', 'scenario_id': scenario_id,
               'input_revision': len(answers), 'answers': answers}
    return payload, scenario


def observe(response, record):
    assessment = response['assessment']
    finder = response['finder']
    record.update(state=assessment['state'], request=assessment['request'],
                  finder_present=finder is not None,
                  finder_service=finder['service'] if finder is not None else None,
                  ranked=bool(finder['ranked']) if finder is not None else False)


def execute(setup, steps, measures, record):
    # A Python mapping has at most one value for a key. A trusted + visitor
    # disagreement is separately representable and cannot substitute for this.
    if any(step.startswith('duplicate_warning_answer:') for step in steps):
        record['not_run'] = 'The public API takes a mapping, which cannot retain duplicate keys.'
        return
    if 'mutate_confirmation_revision' in steps or 'mutate_confirmation_policy' in steps:
        record['not_run'] = 'The public API exposes no mutation of fields on an opaque receipt.'
        return
    payload, scenario = baseline(setup)
    prior = None
    with ExitStack() as overrides:
        for step in steps:
            op, _, arg = step.partition(':')
            answers = payload['answers']
            if op == 'confirm_current':
                record['attempted'] = True
                before = engine.assess_intake(payload, scenario=scenario)
                try:
                    prior = engine.confirm_intake(payload, scenario=scenario)
                except ValueError:
                    if before['state'] == 'confirmation_required':
                        raise
                    prior = None
                else:
                    if prior is None or before['state'] != 'confirmation_required':
                        record['error'] = 'Confirmation was inconsistent with preconfirmation assessment.'
            elif op == 'confirm_other_scenario':
                record['attempted'] = True
                other_payload, other = baseline('complete_dialysis')
                prior = engine.confirm_intake(other_payload, scenario=other)
            elif op in ('find_initial', 'find'):
                record['attempted'] = True
                result = find_care_for_intake(payload, scenario=scenario,
                                              confirmation=prior, origin_id='central')
                if op == 'find':
                    observe(result, record)
                else:
                    first = {}
                    observe(result, first)
                    first['finder_calls'] = measures.calls
                    record['initial_phase'] = first
                    record['initial_ready_result'] = (
                        first['state'] == 'ready' and first['request'] == {
                            'service': 'mri', 'urgency': 'routine', 'required_capabilities': [],
                            'preferred_capabilities': []} and first['finder_service'] == 'mri'
                        and first['ranked'] and measures.calls == 1)
                    record['initial_control_failed'] = not record['initial_ready_result']
                    measures.calls = 0
            elif op == 'set_warning':
                sign, token = arg.split('=')
                answers[warning_key(sign)] = 'false' if token == 'string_false' else token
            elif op == 'add_conflicting_warning':
                sign, token = arg.split('=')
                key = warning_key(sign)
                scenario['known_answers'][key] = answers[key]
                answers[key] = token
            elif op == 'set_all_warnings':
                answers.update({warning_key(sign): arg for sign in WARNINGS})
            elif op == 'set_other_warning':
                answers[warning_key('unresponsive')] = arg
            elif op == 'remove_all_warning_answers':
                for sign in WARNINGS:
                    del answers[warning_key(sign)]
            elif op == 'remove_warning':
                del answers[warning_key(arg)]
            elif op in ('remove_age', 'remove_onset', 'remove_severity'):
                field = {'remove_age': 'age_group', 'remove_onset': 'onset',
                         'remove_severity': 'severity'}[op]
                del answers['context.' + field]
            elif op in ('set_population', 'set_age'):
                if arg == 'pregnancy':
                    answers['context.pregnancy'] = 'pregnant'
                else:
                    answers['context.age_group'] = 'unknown' if arg == 'unknown_age' else arg
            elif op == 'set_care_need':
                scenario['concern_category'] = arg
            elif op == 'set_presenting_text':
                scenario['presenting_problem'] = arg
            elif op == 'remove_clinician_authority':
                scenario['clinician_plan'] = None
            elif op == 'replace_authority_service':
                scenario['clinician_plan']['service'] = SERVICES[arg][0]
            elif op == 'inject_client_authority':
                payload['clinician_plan'] = baseline('complete_' + arg)[1]['clinician_plan']
            elif op == 'remove_plan_urgency':
                del scenario['clinician_plan']['urgency']
            elif op == 'add_second_authority':
                second = deepcopy(baseline('complete_' + arg)[1]['clinician_plan'])
                second['scenario_id'] = scenario['scenario_id']
                scenario['clinician_plan'] = [scenario['clinician_plan'], second]
            elif op == 'inject_client_state':
                payload['state'] = arg
            elif op == 'inject_client_request':
                payload['request'] = {'service': arg, 'urgency': 'routine',
                                      'required_capabilities': [], 'preferred_capabilities': []}
            elif op == 'inject_confirmation':
                prior = True
            elif op == 'replace_requested_service':
                scenario['service'] = SERVICES[arg][0]
            elif op == 'replace_scenario':
                payload, scenario = baseline(arg)
            elif op == 'advance_policy_version':
                overrides.enter_context(patch.object(engine, 'POLICY_VERSION', 'intake-policy.audit-next'))
            elif op == 'set_mode':
                if arg == 'missing':
                    del payload['mode']
                else:
                    payload['mode'] = arg
            elif op == 'make_next_assessment_fail':
                # Force the documented structural failure response with a
                # malformed revision, after the same consumer already succeeded.
                payload['input_revision'] = False
                continue
            else:
                raise ValueError('Unmapped frozen step: ' + op)
            if op not in ('find', 'find_initial'):
                payload['input_revision'] = len(payload['answers'])
