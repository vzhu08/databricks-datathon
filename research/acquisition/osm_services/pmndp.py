"""NHSRC state totals are programme context, never a facility roster."""
import argparse
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from .core import canonical

INDEX_SHA = '66ac91c51b03947606277960830b42d3a5c63658ec6176f30ae0e25735e8cc85'
POLICY_SHA = '2395efc853e589270a80c6a4d212d0f97df2953baab95708ba7ff581fcb9d5ac'
HEADERS = ['States/UTs', 'Total No of Districts',
           'Total No of Districts (where Dialysis services are functional)',
           'Total No of functional Dialysis centers', 'PPP/IN-HOUSE']


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        elif tag in {'td', 'th'} and self.row is not None: self.cell = []

    def handle_data(self, text):
        if self.cell is not None: self.cell.append(text)

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse(raw, expected_sha=INDEX_SHA):
    if sha256(raw).hexdigest() != expected_sha:
        raise ValueError('NHSRC index edition digest mismatch')
    parser = TableReader()
    parser.feed(raw.decode('utf-8'))
    if not parser.rows or parser.rows[0] != HEADERS:
        raise ValueError('Unexpected PMNDP table schema')
    rows = []
    for i, row in enumerate(parser.rows[1:], 1):
        if len(row) != 5 or not all(v.isdigit() for v in row[1:4]):
            raise ValueError('Unexpected PMNDP row width/numeric cell')
        rows.append({'raw_cells': row, 'source_locator': 'table/tr['+str(i+1)+'] (1-based including header)',
                     'state_ut': row[0], 'districts': int(row[1]),
                     'functional_districts': int(row[2]), 'reported_functional_centres': int(row[3]),
                     'programme_model': row[4], 'source_unit': 'aggregate centres per state/UT',
                     'campus_id': None, 'facility_id': None, 'service_observed_date': None,
                     'source_family': 'PMNDP programme via NHSRC',
                     'patient_status': 'unconfirmed'})
    if len({r['state_ut'] for r in rows}) != len(rows):
        raise ValueError('Repeated state label requires review; not silently deduplicated')
    return rows


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--index', type=Path, required=True)
    p.add_argument('--policy', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args=p.parse_args()
    raw=args.index.read_bytes(); policy=args.policy.read_bytes()
    if sha256(policy).hexdigest()!=POLICY_SHA: raise ValueError('Policy edition digest mismatch')
    rows=parse(raw)
    report={'source_url':'https://nhsrcindia.org/pmndp-map-table','publisher':'NHSRC / PMNDP',
            'geographic_scope':'India; state/UT aggregate rows','source_family':'PMNDP programme',
            'raw_sha256':INDEX_SHA,'retrieved_at':'2026-11-22T05:03:31.298320Z',
            'publication_date':None,'service_observation_date':None,'state_ut_rows':len(rows),
            'sum_reported_functional_centres':sum(r['reported_functional_centres'] for r in rows),
            'named_campus_rows':0,'campus_join_keys':0,'vf_coverage':'not measurable from state totals',
            'service_decision_transitions':0,'interpretation':'Programme context; do not allocate totals to VF campuses or compare as a map coverage denominator.',
            'reuse':{'url':'https://nhsrcindia.org/copyright-policy','sha256':POLICY_SHA,
                     'retrieved_at':'2026-11-22T05:03:32.631179Z',
                     'scope':'NHSRC material may be reproduced accurately with acknowledgment; third-party material excluded.',
                     'attribution':'National Health Systems Resource Centre (NHSRC), PMNDP index'}}
    files={'index.html':raw,'copyright-policy.html':policy,
           'state-totals.jsonl':b''.join(canonical(r) for r in rows),'aggregate.json':canonical(report)}
    args.out.mkdir(parents=True,exist_ok=True)
    for name,data in files.items():
        path=args.out/name
        if path.exists() and path.read_bytes()!=data: raise ValueError('Refusing to overwrite edition')
        path.write_bytes(data)
    manifest={'publisher':'NHSRC','source_edition':report,'row_grain':'state/UT programme aggregate',
              'join_keys':['state_ut (context only; no campus linkage)'],
              'permitted_audience':'four-person private research team',
              'files':{name:{'bytes':len(data),'sha256':sha256(data).hexdigest()} for name,data in files.items()}}
    (args.out/'manifest.json').write_bytes(canonical(manifest))
    print(canonical({'rows':len(rows),'centres':report['sum_reported_functional_centres'],
                     'manifest_sha256':sha256(canonical(manifest)).hexdigest()}).decode(),end='')


if __name__=='__main__':main()
