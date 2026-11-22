"""Run against a local working packet or its mounted Databricks readback."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from .pbf import file_digest


def verify(directory, expected_manifest_sha):
    directory=Path(directory)
    raw=(directory/'manifest.json').read_bytes()
    if sha256(raw).hexdigest()!=expected_manifest_sha:
        raise ValueError('Manifest digest mismatch')
    manifest=json.loads(raw)
    for name, expected in manifest['files'].items():
        path=directory/name
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe manifest path')
        if path.stat().st_size!=expected['bytes'] or file_digest(path)!=expected['sha256']:
            raise ValueError('File digest/size mismatch: '+name)
    if 'packets' in manifest:
        count=0
        for packet in manifest['packets']:
            relative=Path(packet['directory'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe child packet path')
            count+=verify(directory/relative,packet['manifest_sha256'])['verified_rows']
    elif 'ledger_observations' in manifest:
        with (directory/'ledger.jsonl').open() as stream:
            count=0
            for line in stream:
                row=json.loads(line)
                if row['patient_status']!='unconfirmed' or row['campus_id'] is not None:
                    raise ValueError('Source packet cannot adjudicate a campus or patient status')
                count+=1
        if count!=manifest['ledger_observations']:
            raise ValueError('Ledger count mismatch')
    else:
        count=sum(1 for _ in (directory/'state-totals.jsonl').open())
        if count!=manifest['source_edition']['state_ut_rows']:
            raise ValueError('State aggregate count mismatch')
    return {'manifest_sha256':expected_manifest_sha,'verified_files':len(manifest['files']),
            'verified_rows':count,'verification_location':str(directory)}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('directory',type=Path)
    p.add_argument('--manifest-sha256',required=True)
    args=p.parse_args()
    print(json.dumps(verify(args.directory,args.manifest_sha256),sort_keys=True))


if __name__=='__main__':main()
