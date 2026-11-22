"""Inventory local source/derived files for a future human file-selection decision.

This reports hashes and restrictions. It cannot clear, package, upload or transfer.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path


def file_hash(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def material_type(relative, source):
    path = Path(relative)
    if source and relative.endswith(source['path']):
        return 'original_' + path.suffix.lstrip('.')
    if path.suffix == '.headers': return 'http_response_headers'
    if path.suffix in {'.zip', '.gz', '.tar'}: return 'mixed_material_archive'
    if path.suffix in {'.png', '.jpg'}: return 'rendered_source_page'
    if relative.startswith('extracted/'): return 'extracted_source_text'
    if path.name in {'annotations.json', 'adapter-annotations.json', 'make_annotations.py'}:
        return 'private_documentary_annotations_or_recipe'
    if path.name in {'batch.json', 'claim_ledger.json', 'sample_to_check.json', 'sample-audit.json'}:
        return 'row_level_derived_material'
    if path.suffix == '.py': return 'local_code_requires_content_review'
    if path.suffix == '.json': return 'metadata_or_derived_json_requires_content_review'
    return 'local_document_or_log_requires_content_review'


def build_inventory(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not output.is_relative_to(root):
        raise ValueError('Inventory output must remain inside the private corpus')
    sources = json.loads((root / 'manifest.json').read_text())['sources']
    protected = {s['key'] for s in sources if s.get('delivery_status') == 'restricted_hold'}
    protected_paths = {s['path'] for s in sources if s['key'] in protected}
    rows = []
    skipped = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if name in {'.venv', '__pycache__', '.git'} or path.is_symlink():
                dirs.remove(name)
                skipped.append(dict(path=path.relative_to(root).as_posix(),
                                    reason='runtime/cache or symbolic-link directory; not source delivery material'))
        for name in files:
            path = Path(directory) / name
            if path == output: continue
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                skipped.append(dict(path=relative, reason='symbolic link; target not read'))
                continue
            source = next((s for s in sources if relative == s['path'] or
                           relative.endswith('/' + s['path']) or
                           name.startswith(s['key'] + '_p') or name == s['key'] + '.json' or
                           name == s['key'] + '.headers' or name == s['key'] + '.txt'), None)
            restricted = bool(source and source['key'] in protected)
            kind = material_type(relative, source)
            reason = None
            if restricted:
                reason = 'Restricted tender original or derivative; excluded, including excerpts and renders.'
            elif kind == 'mixed_material_archive':
                reason = 'Mixed-content archive has no recipient clearance; select exact individual files only after Oliver decides.'
            elif kind == 'http_response_headers':
                reason = 'Unnecessary response/session metadata; exclude from recipient source package.'
            elif relative.startswith(('portable-check/', 'replay-')) or relative.startswith('release-0'):
                reason = 'Duplicate or superseded local replay; exclude from future selected file set.'
            elif not source and kind in {'extracted_source_text', 'rendered_source_page'}:
                reason = 'Derived material without an identified source/rights mapping; exclude pending provenance review.'
            rows.append(dict(
                path=relative, sha256=file_hash(path), bytes=path.stat().st_size,
                material_type=kind, source_key=source['key'] if source else None,
                publisher_url=source['url'] if source else None,
                known_reuse_basis=source['reuse_basis'] if source else
                    'No file-specific recipient clearance recorded; derived data inherit the applicable source restrictions.',
                exclusion_reason=reason,
                disposition='excluded' if reason else 'pending_oliver_exact_file_decision',
                transfer_authorized=False, transferred=False))
    found = {r['path'] for r in rows if r['path'] in protected_paths}
    result = dict(
        inventory_version='hindlabs-local-inventory-1',
        decision='Local-only inventory; no recipient, transfer authorization or delivery has been selected.',
        files=sorted(rows, key=lambda r: r['path']),
        skipped=sorted(skipped, key=lambda r: r['path']),
        counts=dict(files=len(rows), by_material_type=dict(Counter(r['material_type'] for r in rows)),
                    by_disposition=dict(Counter(r['disposition'] for r in rows))),
        restricted_originals_present=sorted(found),
        restricted_originals_absent=sorted(protected_paths - found),
        transferred_files=0)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.root.resolve() / 'manifest.json':
        raise ValueError('Do not replace the source manifest')
    if args.output.exists():
        raise ValueError('Use a new inventory filename; preserve prior human decisions')
    inventory = build_inventory(args.root, args.output)
    args.output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + '\n')
    args.output.chmod(0o600)
    print(json.dumps(dict(sha256=file_hash(args.output), **inventory['counts']), sort_keys=True))


if __name__ == '__main__': main()
