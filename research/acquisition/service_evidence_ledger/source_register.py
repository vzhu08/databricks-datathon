"""Index verified source editions, including row stores awaiting a campus crosswalk."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from .collector_editions import members, verify
from .ledger import canonical, pinned, require

QUALIFICATIONS = {
    '171': 'Punjab PHSC historical aggregate, file-specific row permission pending',
    '172': 'Maharashtra imaging provenance, publisher clearance pending',
    '173': 'NABH listings, issuer scopes and physical campus review pending',
    '174': 'QAI credentials, two programme aggregates and two scope locators',
    '175': 'PMNDP programme aggregates, nationwide facility export pending',
    '176': 'PM RAHAT notice and diagnostic, zero admitted HEM rows',
    '177': 'Krsnaa network-level provenance',
    '178': 'Apollo directory qualification, bulk access and permission pending',
    '179': 'DCDC directory and historical operator lineage',
    '180': 'e-RaktKosh provenance, dated facility-only export pending',
    '182': 'HMIS provenance, facility export pending',
    '183': 'NITI historical aggregate, potential common HMIS origin',
}

def equipment(directory, uri, digest):
    m = verify(directory,digest)
    inventory = json.loads((directory/'editions.json').read_bytes())
    allowed = {r['sha256'] for r in inventory}
    require(len(allowed)==len(inventory)==278, 'equipment_edition_closure')
    counts = {}
    for filename, idname, opener in [('equipment-observations.jsonl.gz','observation_id',gzip.open),
                                     ('mentions.jsonl','mention_id',open)]:
        identities = set()
        modality = Counter()
        explicit_facility = 0
        with opener(directory/filename,'rt',encoding='utf-8') as f:
            for line in f:
                row = json.loads(line)
                require(row['edition_sha256'] in allowed and row['campus_id'] is None
                        and row['service_decision'] is None, 'equipment_scope_or_lineage_changed')
                require(row[idname] not in identities, 'equipment_duplicate_source_id')
                identities.add(row[idname])
                modality.update(row.get('modalities', [row.get('modality')]))
                explicit_facility += int(bool(row.get('source_facility_key')))
        counts[filename] = {'rows':len(identities), 'by_modality_nonexclusive':dict(modality),
                            'source_facility_key_present':explicit_facility if idname=='observation_id' else None}
    require(counts['equipment-observations.jsonl.gz']['rows']==332653 and
            counts['mentions.jsonl']['rows']==18542, 'equipment_rows_changed')
    return {'issue':110, 'uri':uri, 'manifest_sha256':digest, 'scope':m['sharing_scope'],
            'rights':m['rights'], 'attribution':m['attribution'], 'source_grain':m['row_grain'],
            'disposition':'read source-native observations and lexical mentions by reference pending campus linkage',
            'join_fields':m['join_fields'], 'source_editions':len(allowed), 'verified_counts':counts,
            'original_files':m['files'], 'vf_overlap':None, 'admitted_decision_transitions':0}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', type=Path, help='Root with verified source issue-number directories')
    parser.add_argument('locations', type=Path, help='JSON map of issue number to pinned private Volume directory')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    locations = json.loads(args.locations.read_bytes())
    rows = []
    for issue, reason in QUALIFICATIONS.items():
        uri = locations[issue]
        digest = uri.rsplit('-',1)[-1]
        m = verify(args.directories/issue,digest)
        rows.append({'issue':int(issue),'uri':uri,'manifest_sha256':digest,'disposition':reason,
                     'coverage_record_scope':'source qualification, provenance or aggregate only',
                     'member_pins':dict(members(m)), 'admitted_facility_rows':0,
                     'admitted_decision_transitions':0,'physical_campus_overlap':None})
    uri = locations['110d']
    rows.append(equipment(args.directories/'110d',uri,uri.rsplit('-',1)[-1]))
    args.output.write_bytes(canonical(rows)+b'\n')

if __name__=='__main__':
    main()
