"""Compile frozen HLL directory captures and documentary annotations locally.

No network, source acquisition, transfer, VF matching, or service adjudication.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

VERSION = 'hindlabs-adapter-1'
TABLES = ('source_snapshots','external_facilities','facility_matches','facility_evidence','review_queue')
HOST_RELATIONS = {'onsite', 'nearby', 'remote', 'unresolved'}
NON_OPERATIONAL = {'installation_only', 'proposed_mri', 'historical_proposed_mri',
                   'provider_imaging_operations_closed', 'laboratory_closure',
                   'combined_campus_modality_unresolved', 'mri_date_conflict'}

def encode(value):
    return (json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()

def digest(value):
    return hashlib.sha256(value).hexdigest()

def rid(kind,*values):
    return 'hll_hindlabs:'+kind+':'+digest(encode(values))

def norm(text):
    return ' '.join(text.split())

def label_key(text):
    return ' '.join(re.findall(r'\w+',text.casefold()))

def iso_day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Expected a canonical YYYY-MM-DD date')
    return date.fromisoformat(value)

def local_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Source path outside private corpus')
    return path

def temporal_scope(dates, as_of):
    """Return frozen source status separately from the dated assessment."""
    effective, until = dates.get('effective_date'), dates.get('valid_until')
    if effective is not None: iso_day(effective)
    if until is not None: iso_day(until)
    if effective and until and effective > until:
        raise ValueError('Expiry precedes effective date')
    status = dates.get('temporal_status') or ('dated' if effective else 'historical' if until else 'undated')
    if status not in {'dated', 'undated', 'historical', 'expired'}:
        raise ValueError('Unknown temporal status')
    if status == 'undated' and (effective or until):
        raise ValueError('Undated evidence cannot contain validity dates')
    if status == 'dated' and not effective:
        raise ValueError('Dated evidence needs effective_date')
    if status == 'expired':
        if not until:
            raise ValueError('Expired evidence needs an explicit validity end')
        # Expiry is an assessment, not a changing payload on the frozen claim.
        status = 'dated' if effective else 'historical'
    assessed_status = status
    flags = []
    if until and iso_day(until) < as_of:
        assessed_status = 'expired'; flags.append('expired_claim')
    if effective and iso_day(effective) > as_of: flags.append('not_yet_effective')
    if dates.get('temporal_conflict'): flags.append('temporal_conflict')
    return status, assessed_status, flags

def directory_page_count(raw):
    soup = BeautifulSoup(raw, 'html.parser')
    view = soup.select_one('.view-id-branchlocator_new.view-display-id-page')
    if view is None: raise ValueError('Directory view missing')
    last = view.select_one('.pager-last a')
    if last:
        values = parse_qs(urlparse(last['href']).query).get('page', [])
        if len(values) != 1 or not values[0].isdigit():
            raise ValueError('Invalid final-page link')
        return int(values[0]) + 1
    if view.select_one('.pager-next a'):
        raise ValueError('Cannot establish directory pagination bound')
    return 1

def classify(text):
    """Only explicit unit labels; neither a campus service decision nor absence proof."""
    text=text.upper()
    if re.search(r'\bMRI\b',text): return 'mri_unit_label'
    if 'COLLECTION' in text: return 'collection_point'
    if re.search(r'\bCT\b',text): return 'ct_unit_label'
    if re.search(r'\bUSG\b|ULTRASOUND',text): return 'ultrasound_unit_label'
    if re.search(r'\bLAB\b|LABORATOR|PATHOLOG|COVID TEST',text): return 'laboratory_documented_scope'
    if 'IMAGING' in text: return 'imaging_modality_unspecified'
    return 'modality_unknown'

HOST_CONTEXT = re.compile(
    r'\b(?:near(?:by)?|adjacent\s+to|next\s+to|opposite|opp\.?|beside|'
    r'at|inside|within|hosted\s+by|located\s+(?:at|in)|in\s+the\s+premises\s+of)\b',
    re.I)

def own_unit_text(text):
    """A location/host suffix cannot provide the unit's modality."""
    return HOST_CONTEXT.split(text, maxsplit=1)[0]

def classify_unit(name, category):
    label_scope = classify(own_unit_text(name or ''))
    category_scope = classify(own_unit_text(category))
    generic = {'modality_unknown', 'imaging_modality_unspecified'}
    if label_scope not in generic and category_scope not in generic and label_scope != category_scope:
        return 'modality_unknown', ['conflicting_unit_modality_labels']
    if category_scope not in generic:
        return category_scope, []
    if label_scope != 'modality_unknown':
        return label_scope, []
    return category_scope, []

def mentions_label(text, label):
    return bool(label and re.search(r'(?<!\w)' + re.escape(norm(label)) + r'(?!\w)', norm(text), re.I))

def binds_mri_to_unit(excerpt, name, host):
    """Require MRI and the named unit in one clause, excluding host suffixes."""
    text = norm(excerpt)
    if host:
        text = re.sub(r'(?<!\w)' + re.escape(norm(host)) + r'(?!\w)', '[host]', text, flags=re.I)
    for clause in re.split(r'(?<=[.!?;])\s+', text):
        own = own_unit_text(clause)
        if mentions_label(own, name) and re.search(r'\bMRI\b|magnetic resonance', own, re.I):
            return True
    return False

def source_scope_flags(text):
    """Conservative source-wording vetoes; annotation labels cannot override them."""
    flags = []
    if re.search(r'\bnear(?:by)?\b|\badjacent\s+to\b|\bnext\s+to\b|\bopposite\b|\bbeside\b', text, re.I):
        flags.append('source_nearby_wording_not_onsite')
    if re.search(r'\bteleradiology\b|\bremote\b|\boff[- ]site\b|\bacquired\s+elsewhere\b|\breferred?\s+(?:out|to)\b', text, re.I):
        flags.append('source_remote_wording_not_onsite')
    if re.search(r'\bproposed\b|\bplanned\b|\bnot\s+(?:yet\s+)?operating\b|\bno\s+MRI\b|\bMRI\s+unavailable\b', text, re.I):
        flags.append('source_nonoperating_wording')
    return flags

def taxonomy(soup):
    index=defaultdict(list); state=city=None
    select=soup.select_one('#edit-term-node-tid-depth')
    if select is None: raise ValueError('Missing directory geography taxonomy')
    for option in select.select('option'):
        if option.get('value')=='All': continue
        text=option.get_text(' ',strip=True)
        level=len(text)-len(text.lstrip('-'))
        value=text.lstrip('-').strip()
        if level==0: state=value;city=None
        elif level==1: city=value
        elif level==2: index[label_key(value)].append((state,city,option.get('value')))
    return index

def directory_rows(raw, page_number):
    soup=BeautifulSoup(raw,'html.parser')
    view=soup.select_one('.view-id-branchlocator_new.view-display-id-page')
    if view is None: raise ValueError('Directory view missing')
    current=view.select_one('.pager-current')
    if current is None or int(current.get_text())!=page_number+1:
        raise ValueError('Pagination mismatch')
    geo=taxonomy(soup); records=[]
    for row_number,modal in enumerate(view.select('[id^=viewdetails]'),1):
        title=modal.select_one('h3')
        name=norm(title.get_text(' ',strip=True)) if title else None
        name=name or None; values={}
        for p in modal.select('p'):
            label=p.select_one('span.branchcal')
            if label:
                key=norm(label.get_text(' ',strip=True))
                text=norm(p.get_text(' ',strip=True))
                values[key]=text[len(key):].lstrip(' :')
        detail=modal.select_one('.tests-info')
        details=norm(detail.get_text(' ',strip=True)) if detail else ''
        address=values.get('Address') or None
        pin=values.get('Pincode') or None
        flags=['unlinked_source_identity','undated_directory','unit_not_entire_host_campus']
        if name is None: flags.append('missing_unit_name')
        if pin and not re.fullmatch(r'[0-9]{6}',pin): pin=None;flags.append('invalid_source_pin')
        candidates=geo.get(label_key(name or ''),[])
        state=city=None
        if len(candidates)==1:
            state,city,_=candidates[0]
            flags.append('geography_from_unique_punctuation_normalized_directory_taxonomy_name')
        elif address:
            states=set(x[0] for v in geo.values() for x in v)|{'ASSAM','ODISHA','TELANGANA','ARUNACHAL PRADESH'}
            found=[s for s in states if re.search(r'(?<!\w)'+re.escape(s)+r'(?!\w)',address.upper())]
            if len(found)==1: state=found[0];flags.append('state_explicit_in_address')
        state_original=state
        if state=='UTTARPRADESH':state='UTTAR PRADESH';flags.append('state_label_spacing_normalized')
        if state is None: flags.append('state_unknown')
        if city is None: flags.append('district_unknown')
        district=city
        # Publisher calls this taxonomy level District. Never copy it into city.
        city=None
        if state=='MAHARASHTRA': flags.append('potential_dmer66_campus_overlap_not_independent_confirmation')
        # Generic host/address MRI wording cannot supply the node's modality.
        category, modality_flags=classify_unit(name,values.get('Category',''))
        flags.extend(modality_flags)
        if not modality_flags and category in ('modality_unknown','imaging_modality_unspecified') and re.search(r'^HINDLABS\s+(?:FAIR PRICE\s+)?MRI\s+(?:SCAN\s+)?CENTRE\b',address or '',re.I):
            category='mri_unit_address_label'
        locator=f'page query={page_number}; row={row_number}; div#{modal["id"]}'
        # Exact name excerpt, with original address/PIN in external identity fields.
        # Do not manufacture a verbatim quote by joining labels with new punctuation.
        excerpt=name or address or norm(modal.get_text(' ',strip=True))
        if not excerpt: raise ValueError('Directory node has no usable source text')
        records.append(dict(source_record_id=modal['id'].removeprefix('viewdetails'),
            record_locator=locator,name_original=name,address_original=address,pin=pin,
            state=state,city=city,district=district,unit_class=category,quality_flags=flags,excerpt=excerpt,
            raw_pin=values.get('Pincode'),unit_details=details or None,host_campus=None,state_original=state_original))
    if not records: raise ValueError('Empty directory page')
    return records

def located_text(path,spec):
    if ('page' in spec) == ('selector' in spec):
        raise ValueError('Use exactly one PDF page or HTML selector')
    if 'page' in spec:
        import fitz
        with fitz.open(path) as doc:
            if type(spec['page']) is not int or not 1 <= spec['page'] <= len(doc):
                raise ValueError('PDF page outside document')
            return doc[spec['page']-1].get_text(), f'PDF page={spec["page"]}'
    soup=BeautifulSoup(path.read_bytes(),'html.parser')
    for el in soup.select('script,style'): el.decompose()
    if spec.get('selector'):
        elements=soup.select(spec['selector'])
        if not elements: raise ValueError('Missing selector '+spec['selector'])
        if len(elements) != 1: raise ValueError('Selector must identify one source location')
        return elements[0].get_text(' ',strip=True), 'HTML selector='+spec['selector']
    raise ValueError('Documentary HTML evidence requires a CSS selector')

def source_text(path,spec):
    return located_text(path,spec)[0]

def bind_annotation(spec, sources, index):
    """Validate the claim and independently resolve any host source location."""
    source = spec['source']
    _, path, _ = sources[source]
    text, locator = located_text(path, spec)
    excerpt = spec['excerpt']
    if not excerpt or norm(excerpt) not in norm(text):
        raise ValueError(f'Excerpt fails original locator check: annotation {index}, {source}')
    record = dict(spec['record'])
    name = record.get('name_original')
    if name and not mentions_label(excerpt, name):
        raise ValueError('Unit label is absent from the located claim excerpt')
    record['source_record_id'] = spec['annotation_key']
    record['record_locator'] = locator
    record['quality_flags'] = list(record.get('quality_flags', [
        'unlinked_source_identity', 'documentary_scope_requires_review', 'shared_hll_origin']))
    if not name: record['quality_flags'].append('missing_unit_name')
    relation = record.get('host_relation', 'unresolved')
    if relation not in HOST_RELATIONS: raise ValueError('Unknown node-to-host relation')
    host = record.get('host_campus')
    host_excerpt = record.get('host_excerpt')
    host_location = record.get('host_location')
    if host or relation != 'unresolved' or host_excerpt or host_location or record.get('host_locator'):
        if not host or not host_excerpt or not isinstance(host_location, dict):
            raise ValueError('A node-to-host claim needs a campus and located exact excerpt via host_location')
        host_source = host_location.get('source', source)
        if host_source not in sources:
            raise ValueError('Host source is missing or restricted')
        host_sid, host_path, host_manifest = sources[host_source]
        host_text, host_locator = located_text(host_path, host_location)
        if norm(host_excerpt) not in norm(host_text):
            raise ValueError('Node-to-host excerpt does not match its own source location')
        if not mentions_label(host_excerpt, host):
            raise ValueError('Host campus label is absent from the relation excerpt')
        if not name or not mentions_label(host_excerpt, name):
            raise ValueError('Unit label is absent from the relation excerpt')
        record.update(host_locator=host_locator, host_source=host_source,
                      host_snapshot_id=host_sid, host_source_url=host_manifest['url'])
    requested_mri = bool(record.get('mri_scope') or spec['kind'] in (
        'named_mri_service', 'installation_only', 'proposed_mri', 'mri_date_conflict'))
    record['mri_scope'] = requested_mri and binds_mri_to_unit(excerpt, name, host)
    if requested_mri and not record['mri_scope']:
        record['quality_flags'].append('mri_not_bound_to_named_unit')
    scope_flags = source_scope_flags(excerpt + ' ' + (host_excerpt or ''))
    record['quality_flags'].extend(scope_flags)
    record['source_scope_blocks_onsite'] = bool(scope_flags)
    record['declared_host_relation'] = relation
    if host:
        observed = []
        if 'source_nearby_wording_not_onsite' in scope_flags: observed.append('nearby')
        if 'source_remote_wording_not_onsite' in scope_flags: observed.append('remote')
        if observed:
            record['host_relation'] = observed[0] if len(observed) == 1 else 'unresolved'
            if record['host_relation'] != relation:
                record['quality_flags'].append('host_relation_annotation_conflicts_with_source')
    return record, locator

def compile_packet(root, as_of, annotations='annotations.json'):
    root=Path(root).resolve()
    assessment=iso_day(as_of)
    manifest=json.loads((root/'manifest.json').read_text())
    batch=dict(contract_version='1.0.0',**{k:[] for k in TABLES})
    sources={}; ledger=[]; rejects=[]; duplicates=[]
    source_keys=set()
    for s in manifest['sources']:
        if s['key'] in source_keys: raise ValueError('Duplicate source key')
        source_keys.add(s['key'])
        if s.get('delivery_status')=='restricted_hold': continue
        if s.get('status')!='ok': raise ValueError('Unsuccessful source capture')
        path=local_path(root,s['path'])
        if digest(path.read_bytes())!=s['sha256']: raise ValueError('Source hash mismatch '+s['key'])
        stamp=s['retrieved_at'].replace('+00:00','Z')
        if not stamp.endswith('Z'):
            raise ValueError('Retrieval timestamp must be UTC')
        parsed=datetime.fromisoformat(stamp[:-1]+'+00:00')
        if parsed.tzinfo is None or parsed.utcoffset()!=timezone.utc.utcoffset(parsed):
            raise ValueError('Retrieval timestamp must be UTC')
        if s.get('publication_date'): iso_day(s['publication_date'])
        sid=rid('snapshot',s['url'],s['sha256']); sources[s['key']]=(sid,path,s)
        batch['source_snapshots'].append(dict(snapshot_id=sid,source_key=s['key'],
            publisher=s['publisher'],source_family='hll_hindlabs',url=s['url'],
            retrieved_at=stamp,published_date=s.get('publication_date'),
            license=s['reuse_basis'],attribution='HLL Lifecare Limited / HINDLABS; source wording retained privately.',
            sha256=s['sha256'],artifact_uri='urn:sha256:'+s['sha256'],parser_version=VERSION,
            independence_status='shared_origin'))

    def add(record,source,kind,excerpt,locator,assertion,dates=None):
        sid,_,s=sources[source]
        if record.get('facility_id') or record.get('match_id'):
            raise ValueError('The source adapter cannot accept VF links')
        dates=dates or {}
        source_temporal, temporal, time_flags=temporal_scope(dates,assessment)
        relation=record.get('host_relation','unresolved')
        if relation not in HOST_RELATIONS: raise ValueError('Unknown node-to-host relation')
        flags=list(record['quality_flags'])
        if record.get('host_campus'):
            flags.append('host_campus_claim_not_confirmed_identity')
        remote=kind=='teleradiology_only' or relation=='remote'
        if remote: flags.append('remote_reporting_not_onsite_service')
        if kind in NON_OPERATIONAL: flags.append('documentary_scope_not_operating_service')
        if relation=='nearby': flags.append('nearby_host_is_not_node_location')
        eid=rid('external',sid,record['source_record_id'],record['record_locator'])
        facility=dict(external_facility_id=eid,snapshot_id=sid,
            source_record_id=record['source_record_id'],record_locator=record['record_locator'],
            name_original=record['name_original'],name_normalized=norm(record['name_original']).casefold() if record['name_original'] else None,
            address_original=record.get('address_original'),facility_type=record['unit_class'],
            city=record.get('city'),state=record.get('state'),pin=record.get('pin'),
            latitude=None,longitude=None,coordinate_method=None,quality_flags=sorted(set(flags)))
        batch['external_facilities'].append(facility)
        is_mri=bool(record.get('mri_scope'))
        evidence=dict(external_facility_id=eid,snapshot_id=sid,facility_id=None,match_id=None,
            claim_type='service' if is_mri else 'identity',
            service='mri' if is_mri else None,
            polarity='inconclusive',assertion=assertion,excerpt=excerpt,observation=None,
            locator=locator,source_url=s['url'],effective_date=dates.get('effective_date'),
            valid_until=dates.get('valid_until'),temporal_status=source_temporal,reviewer=None,reviewed_at=None)
        claimid=rid('evidence',evidence);batch['facility_evidence'].append(dict(evidence_id=claimid,**evidence))
        batch['review_queue'].append(dict(review_id=rid('review',claimid),facility_id=None,
            external_facility_id=eid,evidence_id=claimid,match_id=None,reason_code='campus_time_and_service_scope_review',
            severity='medium',status='open',next_action='Review host campus, specific unit, source date, permission and shared lineage before any VF link or patient-facing decision.',resolution=None))
        ledger.append(dict(evidence_id=claimid,external_facility_id=eid,source=source,kind=kind,
            unit_class=record['unit_class'],state=record.get('state'),district=record.get('district'),city=record.get('city'),
            host_campus=record.get('host_campus'),unit_key=record.get('unit_key'),
            host_relation=relation,host_identity_confirmed=False,
            declared_host_relation=record.get('declared_host_relation'),
            host_excerpt=record.get('host_excerpt'),host_locator=record.get('host_locator'),
            host_source=record.get('host_source'),host_snapshot_id=record.get('host_snapshot_id'),
            host_source_url=record.get('host_source_url'),claim_locator=locator,
            onsite_mri_documentary_candidate=bool(kind=='named_mri_service' and is_mri
                and not remote and relation!='nearby' and not record.get('source_scope_blocks_onsite')
                and kind not in NON_OPERATIONAL and not time_flags),
            review_flags=sorted(set(flags + time_flags)),temporal_status=temporal,as_of=as_of,
            source_temporal_status=source_temporal,declared_temporal_status=dates.get('temporal_status'),
            unit_details=record.get('unit_details'),raw_pin=record.get('raw_pin'),
            state_original=record.get('state_original'),
            source_date_text=dates.get('source_date_text'),date_precision=dates.get('date_precision'),
            operating_start=dates.get('operating_start'),operating_end=dates.get('operating_end'),
            temporal_conflict=dates.get('temporal_conflict'),population_linked=False))

    seen={}
    page_count=manifest.get('directory_pages',0)
    if type(page_count) is not int or not 0 <= page_count < 100:
        raise ValueError('Invalid directory pagination count')
    if page_count and directory_page_count(sources['branchlocator'][1].read_bytes())!=page_count:
        raise ValueError('Manifest pagination differs from original final-page link')
    for page in range(page_count):
        key='branchlocator' if page==0 else f'branchlocator_{page:02}'
        sid,path,s=sources[key]
        for r in directory_rows(path.read_bytes(),page):
            node=r['source_record_id']
            signature={k:v for k,v in r.items() if k!='record_locator'}
            if node in seen:
                if signature!=seen[node]: raise ValueError('Conflicting directory node across pages '+node)
                duplicates.append(dict(source=key,source_record_id=node,reason='repeated_node_same_payload'))
                continue
            seen[node]=signature
            add(r,key,'directory_identity',r['excerpt'],r['record_locator'],
                'HLL directory lists this specific unit and address. Modality classification is limited to explicit unit labels; no campus-level service, opening, closure or appointment inference.')

    for index,spec in enumerate(json.loads(local_path(root,annotations).read_text()),1):
        r,locator=bind_annotation(spec,sources,index)
        add(r,spec['source'],spec['kind'],spec['excerpt'],locator,spec['assertion'],spec.get('dates'))
    # IDs cannot silently overwrite or collide.
    for table,pk in [('source_snapshots','snapshot_id'),('external_facilities','external_facility_id'),('facility_evidence','evidence_id'),('review_queue','review_id')]:
        ids=[r[pk] for r in batch[table]]
        if len(ids)!=len(set(ids)): raise ValueError('Duplicate immutable IDs in '+table)
        batch[table].sort(key=lambda r:r[pk])
    directory=[x for x in ledger if x['kind']=='directory_identity']
    curated=[x for x in ledger if x['kind']!='directory_identity']
    name_counts=Counter(r['name_original'] for r in batch['external_facilities'] if r['source_record_id'] in seen)
    report=dict(contract_version='1.0.0',parser_version=VERSION,as_of=as_of,
        source_inventory=len(manifest['sources']),retrieved_files=sum(s['status']=='ok' for s in manifest['sources']),
        restricted_files_held=sum(s.get('delivery_status')=='restricted_hold' for s in manifest['sources']),
        directory_pages=page_count,directory_rows_before_dedupe=len(directory)+len(duplicates),
        directory_unique_nodes=len(directory),duplicate_nodes=len(duplicates),rejected_rows=len(rejects),
        repeated_directory_names={k:v for k,v in name_counts.items() if k is not None and v>1},
        directory_by_state=dict(Counter(x['state'] or 'UNKNOWN' for x in directory)),
        directory_by_unit_class=dict(Counter(x['unit_class'] for x in directory)),
        curated_claims=len(curated),curated_by_kind=dict(Counter(x['kind'] for x in curated)),
        curated_by_state=dict(Counter(x['state'] or 'UNKNOWN' for x in curated)),
        all_rows_unresolved_for_vf=len(ledger),unresolved_by_state=dict(Counter(x['state'] or 'UNKNOWN' for x in ledger)),
        named_mri_documentary_candidates=sum(x['onsite_mri_documentary_candidate'] for x in curated),
        temporal_status_counts=dict(Counter(x['temporal_status'] for x in ledger)),
        vf_baseline_available=False,vf_matches=None,new_campus_service_pairs=None,national_incremental_coverage=None,
        live_databricks='not run',publication='not performed',submission='not performed',
        limitations=manifest.get('limitations',[]))
    return {'batch.json':batch,'claim_ledger.json':sorted(ledger,key=lambda x:x['evidence_id']),
            'summary.json':report,'duplicates.json':duplicates,'rejects.json':rejects}

def run(root, output, as_of, annotations='annotations.json'):
    root,output=Path(root).resolve(),Path(output).resolve()
    # Output is always a new sibling/child directory, never an input file/tree.
    if output==root or root.is_relative_to(output) or output.is_relative_to(root/'raw'):
        raise ValueError('Output would overlap source inputs')
    payload={name:encode(value) for name,value in compile_packet(root,as_of,annotations).items()}
    payload['output_hashes.json']=encode({name:digest(value) for name,value in payload.items()})
    if output.exists():
        if not output.is_dir() or set(p.name for p in output.iterdir())!=set(payload):
            raise ValueError('Existing output is not the same release')
        if any((output/name).read_bytes()!=value for name,value in payload.items()):
            raise ValueError('Refuse conflicting output')
    else:
        output.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
            stage=Path(tmp)/'release';stage.mkdir(mode=0o700)
            for name,value in payload.items():
                target=stage/name;target.write_bytes(value);target.chmod(0o600)
            stage.rename(output)
    return json.loads(payload['output_hashes.json'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='Private frozen corpus directory')
    parser.add_argument('--output',type=Path,required=True,help='Private local output directory')
    parser.add_argument('--as-of',required=True,help='Explicit canonical YYYY-MM-DD expiry assessment')
    parser.add_argument('--annotations',default='annotations.json',help='Annotation JSON path inside the corpus')
    args=parser.parse_args()
    print(json.dumps(run(args.root,args.output,args.as_of,args.annotations),sort_keys=True,indent=2))

if __name__=='__main__': main()
