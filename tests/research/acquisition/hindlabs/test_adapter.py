import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bs4 import BeautifulSoup

from research.acquisition.hindlabs.adapter import (
    compile_packet, directory_rows, digest, encode, rid, run, source_text,
)

FIXTURE = Path(__file__).parent / 'fixtures' / 'synthetic_directory.html'
REPO = Path(__file__).resolve().parents[4]


def claim(key, name, kind='named_mri_service', **record_fields):
    paragraph = BeautifulSoup(FIXTURE.read_bytes(), 'html.parser').select_one('#' + key)
    return dict(annotation_key=key, source='branchlocator', selector='#' + key,
                locator='HTML p#' + key, excerpt=paragraph.get_text(' ', strip=True), kind=kind,
                record={'name_original': name, 'unit_class': 'diagnostic_unit', 'mri_scope': True,
                        **record_fields},
                assertion='Synthetic documentary scope only; campus/service review required.')


def corpus(root, annotations=None, raw=None):
    raw = FIXTURE.read_bytes() if raw is None else raw
    (root / 'raw').mkdir(exist_ok=True)
    (root / 'raw' / 'directory.html').write_bytes(raw)
    source = dict(key='branchlocator', url='https://example.invalid/synthetic-directory',
                  path='raw/directory.html', sha256=digest(raw),
                  retrieved_at='2026-11-21T01:00:00Z', publication_date=None,
                  publisher='Synthetic HLL-format fixture', status='ok',
                  reuse_basis='Synthetic fixture created for tests; no original rows.')
    manifest = dict(sources=[source], directory_pages=1, limitations=['Synthetic test only.'])
    (root / 'manifest.json').write_bytes(encode(manifest))
    (root / 'annotations.json').write_bytes(encode(annotations or []))
    return manifest


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def compile(self, annotations=None, raw=None, as_of='2026-11-21'):
        corpus(self.root, annotations, raw)
        return compile_packet(self.root, as_of)

    def test_node_and_host_remain_distinct_even_with_onsite_wording(self):
        annotation = claim('onsite', 'Example MRI Unit', host_campus='Example East Campus',
                           host_relation='onsite', host_locator='p#onsite',
                           host_excerpt='Example MRI Unit operates inside Example East Campus.')
        result = self.compile([annotation])
        batch = result['batch.json']
        self.assertEqual(len(batch['external_facilities']), 4)
        self.assertNotIn('Example East Campus', [r['name_original'] for r in batch['external_facilities']])
        ledger = next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')
        self.assertEqual(ledger['host_campus'], 'Example East Campus')
        self.assertEqual(ledger['host_relation'], 'onsite')
        self.assertFalse(ledger['host_identity_confirmed'])
        self.assertTrue(ledger['onsite_mri_documentary_candidate'])
        self.assertEqual(batch['facility_matches'], [])
        self.assertTrue(all(e['facility_id'] is None and e['polarity']=='inconclusive'
                            for e in batch['facility_evidence']))

    def test_nearby_hospital_mri_does_not_make_lab_an_mri_unit(self):
        result = self.compile([claim('nearby', 'Example Laboratory Node', 'laboratory_documented_scope',
                                    mri_scope=False,
                                    host_campus='Example MRI Hospital', host_relation='nearby',
                                    host_locator='p#nearby',
                                    host_excerpt='Example Laboratory Node is near Example MRI Hospital.')])
        first = directory_rows(FIXTURE.read_bytes(), 0)[0]
        self.assertEqual(first['unit_class'], 'laboratory_documented_scope')
        self.assertIsNone(first['city'])
        self.assertEqual(first['district'], 'EXAMPLE DISTRICT')
        ledger = next(r for r in result['claim_ledger.json'] if r['kind']=='laboratory_documented_scope')
        self.assertIn('nearby_host_is_not_node_location', ledger['review_flags'])
        self.assertFalse(ledger['onsite_mri_documentary_candidate'])
        evidence = next(e for e in result['batch.json']['facility_evidence'] if e['evidence_id']==ledger['evidence_id'])
        self.assertIsNone(evidence['service'])

    def test_nearby_relation_cannot_support_onsite_candidate(self):
        result = self.compile([claim('nearby', 'Example Laboratory Node',
                                    host_campus='Example MRI Hospital', host_relation='nearby',
                                    host_locator='p#nearby',
                                    host_excerpt='Example Laboratory Node is near Example MRI Hospital.')])
        self.assertEqual(result['summary.json']['named_mri_documentary_candidates'], 0)

    def test_remote_reporting_keeps_mri_but_never_onsite_support(self):
        annotation = claim('remote', 'Example Remote Node', 'teleradiology_only',
                           host_campus='Example East Campus', host_relation='remote', host_locator='p#remote',
                           host_excerpt='Example Remote Node provides MRI teleradiology reporting for Example East Campus.')
        result = self.compile([annotation])
        row = next(r for r in result['claim_ledger.json'] if r['kind']=='teleradiology_only')
        self.assertFalse(row['onsite_mri_documentary_candidate'])
        self.assertIn('remote_reporting_not_onsite_service', row['review_flags'])
        evidence = next(e for e in result['batch.json']['facility_evidence'] if e['evidence_id']==row['evidence_id'])
        self.assertEqual((evidence['service'], evidence['polarity']), ('mri', 'inconclusive'))

    def test_expiry_uses_explicit_validity_not_retrieval(self):
        annotation = claim('expiry', 'Example MRI Unit')
        annotation['dates'] = dict(effective_date='2023-01-01', valid_until='2024-12-31', temporal_status='dated')
        result = self.compile([annotation])
        row = next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')
        self.assertEqual(row['temporal_status'], 'expired')
        self.assertFalse(row['onsite_mri_documentary_candidate'])
        evidence = next(e for e in result['batch.json']['facility_evidence'] if e['evidence_id']==row['evidence_id'])
        self.assertEqual(evidence['valid_until'], '2024-12-31')
        self.assertEqual(evidence['effective_date'], '2023-01-01')
        self.assertIsNone(evidence['facility_id'])
        boundary = compile_packet(self.root, '2024-12-31')
        self.assertEqual(boundary['summary.json']['temporal_status_counts']['dated'], 1)

    def test_partial_dates_are_not_fabricated(self):
        annotation = claim('expiry', 'Example MRI Unit')
        annotation['dates'] = dict(operating_end='2024-12', source_date_text='FY 2024-25',
                                   date_precision='month', temporal_status='historical')
        result = self.compile([annotation])
        evidence = next(e for e in result['batch.json']['facility_evidence'] if e['claim_type']=='service')
        self.assertIsNone(evidence['valid_until'])
        self.assertIsNone(evidence['effective_date'])
        self.assertEqual(evidence['temporal_status'], 'historical')

    def test_proposed_and_installed_equipment_are_not_operating_services(self):
        result = self.compile([claim('proposal', 'Example Proposed Unit', 'proposed_mri'),
                               claim('installation', 'Example Installed Unit', 'installation_only')])
        scoped = [r for r in result['claim_ledger.json'] if r['kind']!='directory_identity']
        self.assertEqual(len(scoped), 2)
        for row in scoped:
            self.assertFalse(row['onsite_mri_documentary_candidate'])
            self.assertIn('documentary_scope_not_operating_service', row['review_flags'])
        self.assertEqual({e['polarity'] for e in result['batch.json']['facility_evidence']}, {'inconclusive'})

    def test_closure_does_not_close_host_or_emit_mri_negative(self):
        result = self.compile([claim('closure', 'Example Operator Unit', 'provider_imaging_operations_closed')])
        self.assertEqual(result['batch.json']['facility_matches'], [])
        self.assertFalse(any(e['polarity']=='contradicts' for e in result['batch.json']['facility_evidence']))

    def test_temporal_conflict_prevents_candidate(self):
        annotation = claim('onsite', 'Example MRI Unit')
        annotation['dates'] = dict(temporal_conflict='Synthetic start/end disagreement')
        result = self.compile([annotation])
        self.assertEqual(result['summary.json']['named_mri_documentary_candidates'], 0)

    def test_future_effective_date_prevents_candidate(self):
        annotation = claim('onsite', 'Example MRI Unit')
        annotation['dates'] = dict(effective_date='2027-01-01')
        result = self.compile([annotation])
        row = next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')
        self.assertIn('not_yet_effective', row['review_flags'])
        self.assertFalse(row['onsite_mri_documentary_candidate'])

    def test_unlocated_or_wrong_host_binding_is_rejected(self):
        annotation = claim('onsite', 'Example MRI Unit', host_campus='Example East Campus', host_relation='onsite')
        with self.assertRaisesRegex(ValueError, 'located exact'): self.compile([annotation])
        annotation['record'].update(host_locator='p#onsite', host_excerpt=annotation['excerpt'], host_campus='Other Campus')
        with self.assertRaisesRegex(ValueError, 'Host campus label'): self.compile([annotation])

    def test_fabricated_source_quote_and_wrong_selector_are_rejected(self):
        annotation = claim('onsite', 'Example MRI Unit')
        annotation['excerpt'] = 'Invented service claim'
        with self.assertRaisesRegex(ValueError, 'Excerpt fails'): self.compile([annotation])
        annotation = claim('onsite', 'Example MRI Unit'); annotation['selector'] = '#missing'
        with self.assertRaisesRegex(ValueError, 'Missing selector'): self.compile([annotation])

    def test_missing_name_and_invalid_pin_are_preserved(self):
        raw = FIXTURE.read_bytes().replace(b'<h3>Example Laboratory Node</h3>', b'<h3></h3>', 1)
        raw = raw.replace(b'600001', b'600-001', 1)
        result = self.compile(raw=raw)
        row = next(r for r in result['batch.json']['external_facilities'] if r['source_record_id']=='101')
        self.assertIsNone(row['name_original']); self.assertIsNone(row['pin'])
        self.assertIn('missing_unit_name', row['quality_flags'])
        self.assertIn('invalid_source_pin', row['quality_flags'])
        self.assertEqual(result['summary.json']['directory_unique_nodes'], 3)

    def test_collection_point_is_not_promoted_from_shared_campus_address(self):
        rows = directory_rows(FIXTURE.read_bytes(), 0)
        self.assertEqual(rows[1]['unit_class'], 'collection_point')
        self.assertEqual(rows[2]['unit_class'], 'mri_unit_label')
        self.assertNotEqual(rows[1]['source_record_id'], rows[2]['source_record_id'])

    def test_repeated_names_keep_nodes_and_conflicting_node_stops(self):
        raw = FIXTURE.read_bytes().replace(b'<h3>Example Collection Point</h3>', b'<h3>Example MRI Unit</h3>')
        result = self.compile(raw=raw)
        self.assertEqual(result['summary.json']['directory_unique_nodes'], 3)
        self.assertEqual(result['summary.json']['repeated_directory_names']['Example MRI Unit'], 2)
        with self.assertRaisesRegex(ValueError, 'Conflicting directory node'):
            self.compile(raw=raw.replace(b'viewdetails102', b'viewdetails101'))

    def test_wrong_page_and_missing_page_bound_fail(self):
        with self.assertRaisesRegex(ValueError, 'Pagination'):
            directory_rows(FIXTURE.read_bytes(), 1)
        raw = FIXTURE.read_bytes().replace(b'<span class="pager-current">1</span>',
            b'<span class="pager-current">1</span><li class="pager-last"><a href="?page=1">last</a></li>')
        with self.assertRaisesRegex(ValueError, 'pagination differs'): self.compile(raw=raw)

    def test_modified_raw_and_outside_source_fail(self):
        manifest = corpus(self.root)
        (self.root/'raw/directory.html').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): compile_packet(self.root, '2026-11-21')
        manifest['sources'][0]['path']='../outside.html'
        (self.root/'manifest.json').write_bytes(encode(manifest))
        with self.assertRaisesRegex(ValueError, 'outside private'): compile_packet(self.root, '2026-11-21')

    def test_restricted_sources_not_opened_and_not_available_to_annotations(self):
        manifest = corpus(self.root)
        manifest['sources'].append(dict(key='restricted', delivery_status='restricted_hold', status='ok'))
        (self.root/'manifest.json').write_bytes(encode(manifest))
        result = compile_packet(self.root, '2026-11-21')
        self.assertEqual(len(result['batch.json']['source_snapshots']), 1)
        self.assertEqual(result['summary.json']['restricted_files_held'], 1)
        annotation = claim('onsite','Example MRI Unit'); annotation['source']='restricted'
        (self.root/'annotations.json').write_bytes(encode([annotation]))
        with self.assertRaises(KeyError): compile_packet(self.root, '2026-11-21')

    def test_noncanonical_dates_and_vf_links_are_rejected(self):
        corpus(self.root)
        for invalid in ('20261121', '2026-W47-6', '2026-02-30'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): compile_packet(self.root, invalid)
        annotation = claim('onsite','Example MRI Unit',facility_id='synthetic-vf-id')
        with self.assertRaisesRegex(ValueError,'cannot accept VF'): self.compile([annotation])
        for invalid in (dict(valid_until='2024-12'), dict(temporal_status='expired'),
                        dict(effective_date='2026-01-01', valid_until='2025-12-31')):
            annotation=claim('expiry','Example MRI Unit');annotation['dates']=invalid
            with self.subTest(dates=invalid),self.assertRaises(ValueError):self.compile([annotation])

    def test_ids_use_source_bytes_and_not_retrieval_clock(self):
        result=self.compile(); manifest=json.loads((self.root/'manifest.json').read_text())
        manifest['sources'][0]['retrieved_at']='2026-11-22T01:00:00Z'
        (self.root/'manifest.json').write_bytes(encode(manifest))
        later=compile_packet(self.root,'2026-11-21')
        self.assertEqual(result['batch.json']['source_snapshots'][0]['snapshot_id'],later['batch.json']['source_snapshots'][0]['snapshot_id'])
        self.assertNotEqual(rid('snapshot','https://example.invalid',digest(b'a')),rid('snapshot','https://example.invalid',digest(b'b')))

    def test_replay_is_identical_and_conflict_does_not_write_partial_files(self):
        corpus(self.root)
        output=self.root/'release'
        first=run(self.root,output,'2026-11-21')
        before={p.name:p.read_bytes() for p in output.iterdir()}
        self.assertEqual(first,run(self.root,output,'2026-11-21'))
        with self.assertRaisesRegex(ValueError,'conflicting output'):run(self.root,output,'2026-11-22')
        self.assertEqual(before,{p.name:p.read_bytes() for p in output.iterdir()})

    def test_pdf_quote_is_bound_to_its_page(self):
        import fitz
        path=self.root/'synthetic.pdf'
        with fitz.open() as doc:
            doc.new_page().insert_text((72,72),'Example page one.')
            doc.new_page().insert_text((72,72),'Example MRI Unit is proposed.')
            doc.save(path)
        self.assertNotIn('MRI',source_text(path,dict(page=1)))
        self.assertIn('MRI',source_text(path,dict(page=2)))
        for page in (0,-1,3,True):
            with self.subTest(page=page),self.assertRaises(ValueError):source_text(path,dict(page=page))

    def test_shared_validator_accepts_duplicate_import_of_synthetic_output(self):
        annotations=[claim('remote','Example Remote Node','teleradiology_only'),
                     claim('proposal','Example Proposed Unit','proposed_mri'),
                     claim('expiry','Example MRI Unit')]
        annotations[-1]['dates']=dict(effective_date='2023-01-01',valid_until='2024-12-31')
        corpus(self.root,annotations);output=self.root/'release';run(self.root,output,'2026-11-21')
        base=self.root/'base.json';base.write_text('[]')
        proc=subprocess.run([sys.executable,str(REPO/'databricks/enrichment/validate_batch.py'),
            '--batch',str(output/'batch.json'),'--batch',str(output/'batch.json'),
            '--base',str(base),'--as-of','2026-11-21'],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        report=json.loads(proc.stdout)
        self.assertEqual(report['counts']['external_facilities'],6)
        self.assertEqual(report['counts']['facility_evidence'],6)
        self.assertEqual(report['counts']['facility_matches'],0)


if __name__=='__main__':unittest.main()
