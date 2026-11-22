"""Read an immutable HOT release without repairing or dropping source rows."""
from hashlib import sha256
from pathlib import Path
import json
import re
import zipfile
from .core import digest, typed_id

FROZEN_SHA256 = '5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3'
URL = 'https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/health_facilities/hotosm_ind_health_facilities_osm_geojson.zip'


def load(path, expected_sha=FROZEN_SHA256):
    raw = Path(path).read_bytes()
    actual = sha256(raw).hexdigest()
    if actual != expected_sha:
        raise ValueError('HOT edition digest mismatch')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError('Unsafe/oversized archive')
        config = archive.read('config.yaml').decode()
        metadata = json.loads(archive.read('metadata.json'))
        features = json.loads(archive.read('health_facilities.geojson'))['features']
    mapping = {column: key for key, column in re.findall(r"tags\['([^']+)'\] AS (\w+)", config)}
    # Only config-declared aliases establish original OSM keys. Extra publisher
    # fields (including language/transliteration columns) remain raw_properties.
    columns = set().union(*(f['properties'].keys() for f in features))
    grouped = {}
    for index, feature in enumerate(features):
        p = feature['properties']; ident = typed_id(p['id'])
        payload = digest(feature)
        key = (ident, payload)
        locator = 'health_facilities.geojson#/features/' + str(index)
        if key in grouped:
            grouped[key]['locators'].append(locator)
            continue
        grouped[key] = {'osm_id': ident, 'payload_sha256': payload,
                        'name': p.get('name'), 'branch': None,
                        'address_fields': {mapping[k]:p.get(k) for k in mapping if k.startswith('addr_')},
                        'state': p.get('adm1_name'), 'state_code': p.get('adm1_pcode'),
                        'state_basis': 'publisher geoBoundaries ADM1 overlay',
                        'tags': {key:p.get(column) for column,key in mapping.items()},
                        'raw_properties': p, 'geometry': feature.get('geometry'),
                        'locators': [locator], 'map_edit_time': None,
                        'service_observation_date': None}
    records = sorted(grouped.values(), key=lambda r:(r['osm_id'],r['payload_sha256']))
    edition = {'publisher': 'HOT / OSM / Geofabrik', 'source_url': URL, 'sha256': actual,
               'byte_length': len(raw), 'snapshot_date': metadata['properties'].get('oex:snapshot'),
               'artifact_created': metadata['properties'].get('created'),
               'first_retrieved_at': '2026-11-21T18:04:39.155206Z',
               'publication_date': None, 'license': metadata['properties']['license'],
               'config_sha256': sha256(config.encode()).hexdigest(),
               'source_metadata': metadata['properties']}
    return records, edition, len(features), columns, mapping
