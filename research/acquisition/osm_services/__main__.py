import argparse
from pathlib import Path
from hashlib import sha256
import json
from .core import canonical, screen
from .hot import load, FROZEN_SHA256


def write_packet(out, ledger, report, extras=None):
    out.mkdir(parents=True, exist_ok=True)
    files = {'ledger.jsonl': b''.join(canonical(row) for row in ledger), 'aggregate.json':canonical(report), **(extras or {})}
    for name, data in files.items():
        path = out/name
        if path.exists() and path.read_bytes() != data:
            raise ValueError('Refusing to replace a different edition: ' + name)
        path.write_bytes(data)
    manifest = {'source_edition': report['edition'], 'row_grain': 'typed OSM object + payload + raw key/value + service; repeated locators retained',
                'join_key': 'osm_id; reviewed campus mapping still required',
                'permitted_audience': 'four-person private research team; OSM-derived ledger remains ODbL-1.0',
                'attribution': '© OpenStreetMap contributors; HOT/Geofabrik distribution',
                'license_url': 'https://opendatacommons.org/licenses/odbl/1-0/',
                'public_release': 'Separate decision; retain attribution and ODbL obligations; no VF rows in this source packet',
                'files':{name:{'bytes':len(data),'sha256':sha256(data).hexdigest()} for name,data in files.items()},
                'ledger_observations':len(ledger), 'service_status':'unconfirmed; map review leads only'}
    (out/'manifest.json').write_bytes(canonical(manifest))
    print(json.dumps({'manifest_sha256':sha256(canonical(manifest)).hexdigest(), 'objects':report['distinct_typed_objects'],
                      'observations':len(ledger), 'services':{k:{'explicit':v['explicit_qualifying_objects'],'mentioned':v['unique_mentioned_objects']} for k,v in report['services'].items()}}))


def main():
    p=argparse.ArgumentParser()
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--hot', type=Path)
    source.add_argument('--pbf', type=Path)
    p.add_argument('--sha256', default=FROZEN_SHA256)
    p.add_argument('--prior-hot', type=Path)
    p.add_argument('--pbf-cache', type=Path, help='private parsed-record checkpoint, hash-gated before reuse')
    p.add_argument('--source-url')
    p.add_argument('--snapshot-date')
    p.add_argument('--retrieved-at')
    p.add_argument('--out', type=Path, required=True)
    args=p.parse_args()
    extras={}
    if args.hot:
        records,edition,count,columns,mapping=load(args.hot,args.sha256)
    else:
        if not all([args.source_url,args.snapshot_date,args.retrieved_at]):
            p.error('PBF requires source URL, snapshot date and retrieval time')
        from .pbf import load as load_pbf, compare_editions
        prior=load(args.prior_hot)[0] if args.prior_hot else []
        records,edition,count,columns,mapping=load_pbf(args.pbf,args.sha256,args.source_url,args.snapshot_date,args.retrieved_at,prior,args.pbf_cache)
        if prior:
            extras['edition-drift.json']=canonical(compare_editions(prior,records))
    ledger,report=screen(records,edition,count,columns,mapping)
    if args.pbf:
        for key,audit in report['required_key_audit'].items():
            audit['retained_objects_nonempty']=audit.pop('nonempty_objects')
            audit['national_objects_nonempty']=edition['national_required_key_counts'].get(key,0)
            audit['status']='present_with_values' if audit['national_objects_nonempty'] else 'absent_in_full_snapshot'
        report['input_occurrences_scope']='retained medical/target/prior objects; complete scan counts in edition'
    write_packet(args.out,ledger,report,extras)


if __name__ == '__main__':
    main()
