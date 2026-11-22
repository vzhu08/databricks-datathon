"""Read frozen four-person collector handoffs and preserve their producer grain."""
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re

from research.geography.checks import coordinate_status
from research.geography.distance import haversine_m
from research.matching.normalize import core, pin_key, state_key, tokens
from .ledger import canonical, lines, pinned, require

# Only these exact editions have a four-reader producer handoff in #163.
PINS = {
    '166': 'd3a4650d238b9c6a9138102f40123d94f71417224e653dbe454c64318d893c7b',
    '170': '51b8264776f353af67bab23c274cbb45c0deeb1e4fb4de8888af55abdb7be3df',
}

def members(manifest):
    entries = manifest.get('files', manifest.get('file_entries'))
    if isinstance(entries, dict):
        return entries.items()
    return [(next(row[k] for k in ('name', 'file', 'filename', 'path') if k in row), row)
            for row in entries]

def verify(directory, digest):
    manifest = json.loads(pinned(directory / 'manifest.json', digest))
    for name, pin in members(manifest):
        path = directory / name
        require(path.resolve().is_relative_to(directory.resolve()), 'invalid_source_member')
        require(path.stat().st_size == pin['bytes'], 'source_member_length')
        with path.open('rb') as stream:
            require(hashlib.file_digest(stream, 'sha256').hexdigest() == pin['sha256'], 'source_member_hash')
    return manifest

def observation(row, facility, edition_id):
    return dict(observation_id=row['observation_id'], edition_id=edition_id,
                source_facility_id=facility, original_occurrence_key=None, source_date=None,
                effective_from=None, effective_until=None, polarity='inconclusive',
                multi_campus=False, mirror_of=[], supersedes=[], target_links=[], source_record=row)

def dmer(directory):
    manifest = verify(directory, PINS['166'])
    batch = json.loads((directory/'dmer.batch.json').read_bytes())
    snap, = batch['source_snapshots']
    edition = dict(edition_id=snap['snapshot_id'], content_sha256=snap['sha256'],
                   publisher=snap['publisher'], source_url=snap['url'], reuse_terms=snap['license'],
                   sharing_scope='private_datathon_four_readers', geographic_scope='Maharashtra institutional inventory',
                   source_family=snap['source_family'], origin_status='known', published_date=snap['published_date'],
                   retrieved_at=snap['retrieved_at'], packet_sha256=PINS['166'], source_manifest=manifest)
    refs = {r['external_facility_id']:r for r in batch['external_facilities']}
    observations = []
    for row in json.loads((directory/'dmer.observations.json').read_bytes()):
        fid = row['external_facility_id']
        require(fid in refs and row['source_sha256'] == snap['sha256'] and row['vf_campus_join'] == 'unreviewed'
                and row['current_service_decision']=='unconfirmed', 'dmer_source_scope_changed')
        r = observation(row, fid, edition['edition_id'])
        r.update(modality=row['modality'], claim_type=row['kind'], claim_scope=row['grain'],
                 claim_value=row['reported_value'], units=row['units'], raw_text=row['raw_value'],
                 locator={'physical_row':row['locator'], 'subject':row['subject']}, source_identity=refs[fid],
                 multi_campus=row['grain']=='campus_group', independence_status='unassessed')
        observations.append(r)
    require(len(observations)==54 and len(refs)==27, 'dmer_frame_changed')
    return dict(schema_version='service-evidence-lane-v1', lane='K_DMER_v4', editions=[edition], observations=observations)

HOSPITAL = re.compile(r'\b(?:hospital|medical college|(?:medical|medicine) institute|nursing home)\b')
BLOOD = re.compile(r'\b(?:blood (?:bank(?:ing)?|centre|transfusion(?: service)?|storage(?: unit| centre)?)|blood component(?: centre)?)\b')

def distinctive(value):
    parts = tokens(value)
    return ' '.join(parts) if core(parts) else ''

def point(row, lat, lon):
    c = coordinate_status(row[lat], row[lon])
    return (c['lat'], c['lon']) if c['usable'] and not c['flags'] else None

def host_links(centres, base):
    """Reproduce the #170 exact hospital-label, state, PIN and 1 km screen."""
    by_name = defaultdict(list)
    states = {r['normalized_state'] for r in centres} | {'ladakh'}
    for r in centres:
        name = distinctive(r['name'])
        if not HOSPITAL.search(name):
            continue
        alias = ' '.join(BLOOD.sub(' ', name).split()).removeprefix('at ')
        for label in {name, distinctive(alias)}:
            if HOSPITAL.search(label):
                by_name[label].append((r, point(r,'lat','lon')))
    result = defaultdict(list)
    for item in base:
        row = item['source_row']
        state = state_key(row['address_stateOrRegion'])
        pin = pin_key(row['address_zipOrPostcode'])
        pin = pin if pin and not pin.startswith('0') else None
        coords = point(row,'latitude','longitude')
        for centre, origin in by_name.get(distinctive(row['name']), ()):
            if state in states and centre['normalized_state'] and state != centre['normalized_state']:
                continue
            cp = centre['normalized_pin']
            same = bool(pin and pin == cp)
            metres = haversine_m(*coords,*origin) if coords and origin else None
            if same or (metres is not None and metres <= 1000 and not (pin and cp and pin!=cp)):
                result[centre['source_record_key']].append(dict(occurrence_key=item['facility_id'], quality='candidate',
                    campus_id=None, review_reference=None, same_pin=same, distance_metres=metres))
    return result

def blood(directory, base):
    manifest = verify(directory, PINS['170'])
    eid = 'indiadigital:'+manifest['source_file_sha256']
    provenance = json.loads((directory/'source-provenance.json').read_bytes())
    edition = dict(edition_id=eid, content_sha256=manifest['source_file_sha256'], publisher=manifest['publisher'],
                   source_url=manifest['source_url'], reuse_terms='IndiaDigital CC BY 4.0; upstream GODL-India. See source provenance.',
                   sharing_scope='private_datathon_four_readers', geographic_scope='India', source_family='nhp',
                   origin_status='known', published_date=manifest['source_packaged_on'], retrieved_at=manifest['retrieved_at_utc'],
                   source_manifest=manifest, source_provenance=provenance, packet_sha256=PINS['170'])
    centres = lines(directory/'blood-bank-centres-contact-redacted.jsonl')
    by_id = {r['source_record_key']:r for r in centres}
    require(len(by_id)==len(centres)==2823, 'blood_listing_keys_changed')
    links = host_links(centres,base)
    reached = {l['occurrence_key'] for ls in links.values() for l in ls}
    aggregate = json.loads((directory/'national-coverage.json').read_bytes())
    require(len(reached)==aggregate['vf']['candidate_occurrences'] and len(links)==aggregate['vf']['candidate_source_records'],
            'blood_host_screen_differs_from_pinned_edition')
    observations = []
    for row in lines(directory/'blood-bank-historical-observations.jsonl'):
        fid = row['source_record_key']
        require(fid in by_id and row['vf_occurrence_key'] is None and row['host_link_status']=='unreviewed'
                and row['time_status']=='historical' and row['source_sha256']==edition['content_sha256'], 'blood_source_scope_changed')
        r = observation(row,fid,eid)
        value = row['source_value']
        r.update(modality='blood_provision', claim_type=row['modality_or_claim'], claim_scope='historical_directory',
                 claim_value=value, units=None, raw_text=value if isinstance(value,str) else canonical(value).decode(),
                 locator={'source_locator':row['source_locator']}, target_links=links.get(fid,[]),
                 source_identity=by_id[fid], source_date=row['row_observed_on'],
                 effective_from=row['effective_from'], effective_until=row['effective_until'], independence_status='shared_origin')
        observations.append(r)
    require(len(observations)==4388,'blood_observation_count_changed')
    return dict(schema_version='service-evidence-lane-v1', lane='IndiaDigital_170', editions=[edition], observations=observations)

def nhp(directory, base):
    """Keep selected publisher fields, with an explicit null for withheld text."""
    import zipfile
    digest = '55b74925654b8287f4a6cb82f4ef843437ae3dff0a752846af760c4da12a5586'
    m = json.loads(pinned(directory/'manifest.json', digest))
    archive = m['archive']
    payload = pinned(directory/archive['filename'], archive['sha256'])
    require(len(payload)==archive['bytes'], 'nhp_archive_size')
    tables = {}
    with zipfile.ZipFile(directory/archive['filename']) as z:
        require(sorted(z.namelist())==sorted(p['filename'] for p in m['members']), 'nhp_archive_inventory')
        for pin in m['members']:
            name = pin['filename']
            raw = z.read(name)
            require(len(raw)==pin['bytes'] and hashlib.sha256(raw).hexdigest()==pin['sha256'], 'nhp_member_pin')
            if name.endswith('.jsonl.gz'):
                tables[name] = [json.loads(line) for line in gzip.decompress(raw).splitlines()]
                require(len(tables[name])==pin['count'], 'nhp_member_count')
    facilities = {r['sr_no']:r for r in tables['facility-locators.jsonl.gz']}
    require(len(facilities)==30273,'nhp_duplicate_source_key')
    links = defaultdict(list)
    keys = {r['facility_id'] for r in base}
    for row in tables['vf-review-leads.jsonl.gz']:
        fid = row['source_sr_no_for_review']
        require(fid in facilities and row['occurrence_key'] in keys and row['campus_review_required'], 'nhp_unresolved_lookup_key')
        links[fid].append(dict(occurrence_key=row['occurrence_key'], campus_id=None, quality='candidate',
                               review_reference=None, source_lookup=row))
    o = m['official']
    eid = 'nhp:'+o['raw_sha256']
    edition = dict(edition_id=eid, content_sha256=o['raw_sha256'], publisher=o['publisher'], source_url=o['resource_url'],
                   reuse_terms=m['attribution'], sharing_scope='private_datathon_four_readers',
                   geographic_scope='India', source_family='nhp', origin_status='known',
                   published_date=o['metadata_published_utc'][:10], retrieved_at=None, source_manifest=m,
                   retrieval_day=o['retrieved_date_et'], packet_sha256=digest)
    output = []
    for row in tables['field-observations.jsonl.gz']:
        fid = row['sr_no']
        require(fid in facilities and row['onsite_decision_effect'] is None, 'nhp_field_scope')
        value = row['verbatim']
        require((value is None)==row['withheld_for_contact_pattern'], 'nhp_withholding_changed')
        if value is not None:
            require(hashlib.sha256(value.encode()).hexdigest()==row['verbatim_sha256'], 'nhp_verbatim_changed')
        r = observation({'observation_id':fid+'/'+row['field']},fid,eid)
        r.update(source_record=row, source_identity=facilities[fid], target_links=links.get(fid,[]),
                 modality='directory_field', claim_type=row['field'], claim_scope='publisher_directory',
                 raw_text=value, raw_text_withheld=row['withheld_for_contact_pattern'], claim_value=value,
                 units=None, independence_status='shared_origin', locator={'official':row['official_locator'],
                    'mirror':row['mirror_locator'], 'field':row['field']}, source_date=row['observation_date'],
                 effective_from=row['effective_from'],effective_until=row['effective_through'])
        output.append(r)
    return dict(schema_version='service-evidence-lane-v1', lane='NHP_181', editions=[edition], observations=output)
