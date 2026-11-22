"""Conservative tag screen shared by frozen HOT and full national PBF readers."""
from collections import Counter
from hashlib import sha256
import json
import re

VERSION = 'osm-services-1.0.0'
SERVICES = ('dialysis', 'mri', 'trauma_care')
EXACT = {
    'dialysis': {'dialysis', 'haemodialysis', 'hemodialysis', 'peritoneal_dialysis'},
    'mri': {'mri', 'mri_scan', 'magnetic_resonance_imaging'},
    'trauma_care': {'trauma_care', 'trauma care', 'trauma_unit', 'trauma_centre', 'trauma_center'},
}
DEDICATED = {
    'dialysis': {'dialysis', 'healthcare:dialysis'},
    'mri': {'mri', 'healthcare:mri', 'scanner:mri'},
    'trauma_care': {'trauma', 'trauma_care', 'healthcare:trauma', 'healthcare:trauma_care'},
}
MENTION = {
    'dialysis': re.compile(r'(?i)\b(?:dialysis|ha?emodialysis|peritoneal[ _]dialysis)\b'),
    'mri': re.compile(r'(?i)\bmri(?:[ _]scan)?\b|\bmagnetic[ _]resonance\b'),
    'trauma_care': re.compile(r'(?i)\btrauma\b|(?:^|_)trauma(?:_|$)'),
}
GENERIC = {'dialysis': {'nephrology'}, 'mri': {'radiology', 'diagnostic_imaging'},
           'trauma_care': {'emergency', 'emergency_ward', 'orthopaedics', 'orthopedics'}}
OTHER_CAPABILITIES = {
    'ct': {'ct', 'ct_scan', 'ct-scan', 'computed_tomography'},
    'icu': {'icu', 'intensive', 'intensive_care'},
    'orthopaedics': {'orthopaedics', 'orthopedics', 'orthopaedic'},
    'neurosurgery': {'neurosurgery'}, 'paediatrics': {'paediatrics', 'pediatrics'},
    'burn_care': {'burns', 'burn_care'}, 'ventilation': {'ventilation', 'ventilator'},
    'blood_provision': {'blood_bank', 'blood_transfusion'},
    'emergency_surgery': {'emergency_surgery'},
}
LIFECYCLE = ('disused', 'abandoned', 'demolished', 'removed', 'razed', 'closed', 'proposed', 'planned', 'construction')
REQUIRED_KEYS = sorted({'healthcare', 'healthcare:speciality', 'emergency', 'description',
                        'check_date', 'survey:date', 'opening_date', 'source:date',
                        'operator', 'branch', 'capacity:persons', 'capacity:patients',
                        'mri:count', 'dialysis:count', 'disused:healthcare', 'proposed:healthcare'}
                       | set().union(*DEDICATED.values()))


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def tokens(value):
    return {part.strip().lower() for part in str(value).split(';') if part.strip()}


def family(distributor):
    """Distributor names are not independent origins."""
    if distributor.lower() in {'osm', 'hot', 'geofabrik', 'overture_osm', 'openstreetmap'}:
        return 'osm'
    raise ValueError('Unsupported distributor; explicit lineage required')


def typed_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'(node|way|relation)/[1-9]\d*', value):
        raise ValueError('Expected original typed OSM ID')
    return value


def classify(tags, key, value, service):
    """Classify a mention, with scope/lifecycle gates before affirmative tags.

    The category describes map wording only. Every resulting patient decision
    remains unconfirmed. Unknown tag grammars and prose remain review-only.
    """
    text = str(value)
    low = text.strip().lower()
    parts = tokens(text)
    prefix, separator, remainder = key.partition(':')
    suffix = remainder if separator and prefix in LIFECYCLE else key
    dedicated = suffix in DEDICATED[service]
    service_key = bool(MENTION[service].search(suffix.replace(':', ' ')))
    if not (MENTION[service].search(text) or dedicated or service_key):
        return None
    if key in {'name', 'name:en', 'name:hi', 'brand', 'operator'} or key.startswith('name:'):
        return 'name_or_operator_only'
    scope = ' '.join(str(tags.get(k, '')) for k in ['description', 'note', 'fixme'])
    # Only qualify object-wide prose if it also names the same service.
    relevant_scope = scope if MENTION[service].search(scope) else ''
    context = low + ' ' + relevant_scope.lower()
    if (key.startswith(('proposed:', 'planned:', 'construction:'))
            or str(tags.get('healthcare', '')).lower() in {'proposed', 'construction'}
            or re.search(r'\b(planned|proposed|future|under construction|will offer)\b', context)):
        return 'future'
    if (key.startswith(tuple(k + ':' for k in LIFECYCLE[:6]))
            or any(str(tags.get(k, '')).lower() in {'yes', 'true', '1'} for k in LIFECYCLE[:6])
            or any(k in tags for k in ['disused:healthcare', 'abandoned:healthcare', 'demolished:healthcare'])
            or re.search(r'\b(closed|defunct|discontinued|no longer|removed)\b', context)):
        return 'defunct_or_closed'
    if re.search(r'\b(referr?al|referred|refer(?:s|ring)?|off[ -]?site)\b', context):
        return 'referral_or_offsite'
    if (((dedicated or service_key) and low in {'no', 'false', '0', 'none'})
            or re.search(r'\b(no|not|without|unavailable|nonfunctional|non-functional)\b', context)):
        return 'negative_or_unavailable'
    if re.search(r'\b(home|mobile|on wheels)\b', context):
        return 'home_or_mobile_scope'
    if key in {'description', 'note', 'fixme'}:
        return 'free_text_review'
    if key in {'healthcare', 'healthcare:speciality'} and parts & EXACT[service]:
        return 'explicit_service_tag'
    if dedicated and (low in {'yes', 'true', '1'} or low in EXACT[service]):
        return 'explicit_service_tag'
    if (dedicated or service_key) and re.fullmatch(r'\d+(?:\.\d+)?', low):
        return 'numeric_tag_review'
    if service == 'trauma_care' and parts & {'trauma', 'trauma_surgery', 'orthopedic_trauma_surgery'}:
        return 'specialty_scope_review'
    return 'free_text_review'


def observations(record):
    tags = record['tags']
    found = []
    for key, value in sorted(tags.items()):
        if value is None or value == '':
            continue
        for service in SERVICES:
            category = classify(tags, key, value, service)
            if category:
                found.append({'service': service, 'source_key': key, 'raw_value': value,
                              'category': category, 'patient_status': 'unconfirmed',
                              'service_observed_date': None})
        if key in {'healthcare', 'healthcare:speciality'}:
            for capability, values in OTHER_CAPABILITIES.items():
                if tokens(value) & values:
                    found.append({'service': capability, 'source_key': key, 'raw_value': value,
                                  'category': 'other_explicit_specialty_or_modality',
                                  'patient_status': 'unconfirmed', 'service_observed_date': None})
    return found


def summary(records, ledger, input_count, schema_keys, key_mapping, edition):
    by_service = {}
    geographies = sorted({r.get('state') or 'UNKNOWN' for r in records})
    for service in SERVICES:
        selected = [row for row in ledger if row['service'] == service]
        categories = sorted({row['category'] for row in selected})
        by_service[service] = {
            'unique_mentioned_objects': len({r['osm_id'] for r in selected}),
            'raw_mentions_including_repeats': sum(len(r['locators']) for r in selected),
            'unique_key_value_observations': len(selected),
            'by_category_objects_nonexclusive': {c: len({r['osm_id'] for r in selected if r['category'] == c}) for c in categories},
            'explicit_qualifying_objects': len({r['osm_id'] for r in selected if r['category'] == 'explicit_service_tag'}),
            'generic_only_tag_objects': sum(bool(set().union(*(tokens(v) for k,v in r['tags'].items() if k in {'healthcare', 'healthcare:speciality', 'emergency'})) & GENERIC[service]) and not any(MENTION[service].search(str(v)) for v in r['tags'].values()) for r in records),
            'by_source_state': {state: {'mentioned_objects': len({r['osm_id'] for r in selected if (r['state'] or 'UNKNOWN') == state}),
                                      'explicit_objects': len({r['osm_id'] for r in selected if (r['state'] or 'UNKNOWN') == state and r['category'] == 'explicit_service_tag'})} for state in geographies},
        }
    original_keys = set(key_mapping.values())
    key_audit = {}
    for key in REQUIRED_KEYS:
        count = sum(r['tags'].get(key) not in (None, '') for r in records)
        present = key in original_keys
        missing = 'absent_in_full_snapshot' if edition.get('complete_tag_schema') else 'not_preserved_by_export'
        key_audit[key] = {'status': 'present_with_values' if count else ('present_all_null_or_empty' if present else missing), 'nonempty_objects': count}
    control = {
        'exact_healthcare_dialysis': len({r['osm_id'] for r in records if r['tags'].get('healthcare') == 'dialysis'}),
        'exact_dialysis_specialty_token': len({r['osm_id'] for r in records if 'dialysis' in tokens(r['tags'].get('healthcare:speciality', ''))}),
        'specialty_substring_objects': {s:len({r['osm_id'] for r in records if term in str(r['tags'].get('healthcare:speciality', '')).lower()}) for s,term in [('dialysis','dialysis'),('mri','mri'),('trauma_care','trauma')]},
    }
    return {'parser_version': VERSION, 'edition': edition, 'prior_filter_control':control,
            'input_occurrences': input_count, 'distinct_typed_objects': len({r['osm_id'] for r in records}),
            'unique_object_payloads': len(records),
            'repeated_payload_occurrences': input_count - len(records),
            'conflicting_object_ids': sum(n > 1 for n in Counter(r['osm_id'] for r in records).values()),
            'source_family': 'osm', 'independent_origins_count': 1,
            'verified_physical_campuses': None, 'supported_current_services': 0,
            'export_columns': sorted(schema_keys), 'original_key_mapping': key_mapping,
            'required_key_audit': key_audit, 'services': by_service,
            'unique_source_object_service_pairs': len({(r['osm_id'], r['service']) for r in ledger}),
            'unique_key_value_observations': len(ledger),
            'raw_mentions_including_repeats': sum(len(r['locators']) for r in ledger),
            'other_capability_objects': {s:len({r['osm_id'] for r in ledger if r['service']==s}) for s in OTHER_CAPABILITIES},
            'unmarked_objects': 'Unknown; never an explicit service absence',
            'date_policy': 'Map edit, extract and retrieval dates do not date a service observation.',
            'vf_comparison': {'status': 'not_run', 'occurrences': None, 'incremental_coverage': None}}


def screen(records, edition, input_count, schema_keys, key_mapping):
    ledger = []
    for record in records:
        for claim in observations(record):
            row = {**record, **claim, 'edition_sha256': edition['sha256'],
                   'source_family': 'osm', 'independence': 'shared_origin',
                   'campus_id': None, 'facility_id': None,
                   'source_url': 'https://www.openstreetmap.org/' + record['osm_id'],
                   'attribution': '© OpenStreetMap contributors, ODbL 1.0',
                   'license_url': 'https://opendatacommons.org/licenses/odbl/1-0/'}
            row['observation_id'] = 'osm-service:' + digest([edition['sha256'], record['osm_id'], record['payload_sha256'], claim])
            ledger.append(row)
    ledger.sort(key=lambda r:r['observation_id'])
    return ledger, summary(records, ledger, input_count, schema_keys, key_mapping, edition)
