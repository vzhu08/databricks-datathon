import json
from pathlib import Path
import tempfile
import unittest

from research.acquisition.hindlabs.inventory import build_inventory, file_hash


class LocalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        sources=[]
        for key,status in [('open','private_research'),('held_one','restricted_hold'),('held_two','restricted_hold')]:
            path=self.root/'raw'/f'{key}.pdf';path.parent.mkdir(exist_ok=True);path.write_bytes(b'Synthetic bytes '+key.encode())
            sources.append(dict(key=key,path=f'raw/{key}.pdf',url=f'https://example.invalid/{key}',
                                reuse_basis='Synthetic test restriction',delivery_status=status))
        (self.root/'manifest.json').write_text(json.dumps(dict(sources=sources)))

    def test_inventory_hashes_types_and_excludes_both_held_originals(self):
        result=build_inventory(self.root,self.root/'inventory.json')
        rows={r['path']:r for r in result['files']}
        self.assertEqual(len(result['restricted_originals_present']),2)
        self.assertEqual(rows['raw/open.pdf']['sha256'],file_hash(self.root/'raw/open.pdf'))
        self.assertEqual(rows['raw/open.pdf']['material_type'],'original_pdf')
        self.assertEqual(rows['raw/open.pdf']['disposition'],'pending_oliver_exact_file_decision')
        for key in ('held_one','held_two'):
            self.assertEqual(rows[f'raw/{key}.pdf']['disposition'],'excluded')
            self.assertIn('Restricted tender',rows[f'raw/{key}.pdf']['exclusion_reason'])
        self.assertEqual(result['transferred_files'],0)
        self.assertTrue(all(not r['transfer_authorized'] for r in rows.values()))

    def test_restricted_derivatives_and_mixed_archive_excluded(self):
        (self.root/'extracted').mkdir()
        (self.root/'extracted/held_one_p002.txt').write_text('Synthetic restricted derivative')
        (self.root/'mixed.zip').write_bytes(b'Synthetic mixed archive')
        result=build_inventory(self.root,self.root/'inventory.json')
        rows={r['path']:r for r in result['files']}
        self.assertEqual(rows['extracted/held_one_p002.txt']['disposition'],'excluded')
        self.assertIn('Mixed-content',rows['mixed.zip']['exclusion_reason'])

    def test_no_symlink_target_read_and_no_external_inventory_destination(self):
        (self.root/'outside-link').symlink_to('/does-not-exist')
        result=build_inventory(self.root,self.root/'inventory.json')
        self.assertTrue(any(r['path']=='outside-link' for r in result['skipped']))
        with self.assertRaises(ValueError):build_inventory(self.root,self.root.parent/'inventory.json')

    def test_inventory_is_read_only_and_deterministic(self):
        before={p.relative_to(self.root).as_posix():file_hash(p) for p in self.root.rglob('*') if p.is_file()}
        first=build_inventory(self.root,self.root/'inventory.json')
        self.assertEqual(first,build_inventory(self.root,self.root/'inventory.json'))
        after={p.relative_to(self.root).as_posix():file_hash(p) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)


if __name__=='__main__':unittest.main()
