"""Full national public PBF scan; no API sampling or mapper identifiers.

All objects pass through the reader. Retain medical objects and target-service
mentions, plus HOT IDs for drift accounting. Way node references and relation
members are retained; unresolved geometry is never invented.
"""
from collections import Counter
from hashlib import sha256
from pathlib import Path
from .core import MENTION, REQUIRED_KEYS, digest, typed_id


def file_digest(path):
    h = sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def relevant(tags):
    return (any('healthcare' in k for k in tags)
            or tags.get('amenity') in {'hospital', 'clinic', 'doctors', 'dentist', 'pharmacy', 'blood_bank'}
            or any(pattern.search(k.replace(':', ' ') + ' ' + v)
                   for k, v in tags.items() for pattern in MENTION.values()))


def load(path, expected_sha, source_url, snapshot_date, retrieved_at, hot_records=()):
    import osmium  # Optional dependency, pinned in requirements-pbf.txt.
    path = Path(path)
    actual = file_digest(path)
    if actual != expected_sha:
        raise ValueError('PBF edition digest mismatch')
    hot = {r['osm_id']: r for r in hot_records}

    class Reader(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.counts = Counter()
            self.required_counts = Counter()
            self.records = []
            self.seen_hot = set()

        def collect(self, obj, kind):
            self.counts[kind] += 1
            # Never retain osmium views beyond their callback lifetime.
            if not obj.tags and kind + '/' + str(obj.id) not in hot:
                return
            if obj.tags:
                self.counts['tagged_objects'] += 1
            tags = dict(obj.tags)
            self.required_counts.update(k for k in REQUIRED_KEYS if tags.get(k))
            ident = typed_id(kind + '/' + str(obj.id))
            previous = hot.get(ident)
            if previous:
                self.seen_hot.add(ident)
            if not previous and not relevant(tags):
                return
            geometry = None
            topology = None
            if kind == 'node' and obj.location.valid():
                geometry = {'type': 'Point', 'coordinates': [obj.location.lon, obj.location.lat]}
            elif kind == 'way':
                topology = {'nodes': [n.ref for n in obj.nodes]}
            elif kind == 'relation':
                topology = {'members': [{'type': m.type, 'ref': m.ref, 'role': m.role} for m in obj.members]}
            payload = {'osm_id': ident, 'tags': tags, 'geometry': geometry, 'topology': topology,
                       'map_edit_time': obj.timestamp.isoformat(), 'version': obj.version}
            state = tags.get('addr:state') or (previous or {}).get('state')
            self.records.append({**payload, 'payload_sha256': digest(payload),
                'name': tags.get('name'), 'branch': tags.get('branch'),
                'address_fields': {k: v for k, v in tags.items() if k.startswith('addr:')},
                'state': state, 'state_code': None,
                'state_basis': ('current addr:state tag' if tags.get('addr:state') else
                                'prior HOT edition overlay for same typed ID; not a new geocode' if state else 'unknown'),
                'locators': [path.name + '#'+ident+'@v'+str(obj.version)],
                'geometry_basis': 'current node point' if geometry else 'not resolved; topology retained',
                'service_observation_date': None})

        def node(self, obj): self.collect(obj, 'node')
        def way(self, obj): self.collect(obj, 'way')
        def relation(self, obj): self.collect(obj, 'relation')

    reader = Reader()
    reader.apply_file(str(path), locations=False)
    records = sorted(reader.records, key=lambda r: (r['osm_id'], r['payload_sha256']))
    keys = set().union(*(r['tags'].keys() for r in records))
    edition = {'publisher': 'Geofabrik / OpenStreetMap', 'source_url': source_url,
               'sha256': actual, 'byte_length': path.stat().st_size, 'snapshot_date': snapshot_date,
               'first_retrieved_at': retrieved_at, 'publication_date': None,
               'license': 'ODbL-1.0', 'complete_tag_schema': True,
               'scan_counts': dict(reader.counts), 'scope': 'entire public India PBF',
               'selection': 'medical objects, target mentions and prior HOT IDs; no geography filter',
               'national_required_key_counts': dict(reader.required_counts)}
    return records, edition, len(records), keys, {k: k for k in keys}


def compare_editions(hot_records, pbf_records):
    """Compare typed IDs and retained HOT keys; a changed payload is not corroboration."""
    before = {r['osm_id']: r for r in hot_records}
    after = {r['osm_id']: r for r in pbf_records}
    overlap = before.keys() & after.keys()
    changes = []
    for ident in sorted(overlap):
        old, new = before[ident]['tags'], after[ident]['tags']
        changed = {k: {'before': v, 'after': new.get(k)} for k, v in old.items()
                   if (v or None) != (new.get(k) or None)}
        if changed:
            changes.append({'osm_id': ident, 'changed_exported_tags': changed})
    return {'shared_typed_ids': len(overlap), 'hot_ids_absent_from_pbf': sorted(before.keys()-after.keys()),
            'pbf_retained_ids_not_in_hot': sorted(after.keys()-before.keys()),
            'changed_exported_tag_objects': len(changes), 'changes': changes,
            'interpretation': 'Edition/selection drift; same OSM origin. Absence is not proof of closure.'}
