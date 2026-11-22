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
                           host_relation='onsite', host_location={'selector': 'p#onsite'},
                           host_excerpt='Example MRI Unit performs MRI scans inside Example East Campus.')
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
                                    host_location={'selector': 'p#nearby'},
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
                                    host_location={'selector': 'p#nearby'},
                                    host_excerpt='Example Laboratory Node is near Example MRI Hospital.')])
        self.assertEqual(result['summary.json']['named_mri_documentary_candidates'], 0)

    def test_remote_reporting_keeps_mri_but_never_onsite_support(self):
        annotation = claim('remote', 'Example Remote Node', 'teleradiology_only',
                           host_campus='Example East Campus', host_relation='remote', host_location={'selector': 'p#remote'},
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
        annotation['record'].update(host_location={'selector': 'p#onsite'}, host_excerpt=annotation['excerpt'], host_campus='Other Campus')
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


class CliRegressionTests(unittest.TestCase):
    """Exercise the submitted annotations through the public CLI and D import."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_cli(self, output='release', as_of='2026-11-21', succeeds=True):
        target = self.root / output
        proc = subprocess.run([
            sys.executable, '-m', 'research.acquisition.hindlabs.adapter',
            '--root', str(self.root), '--output', str(target), '--as-of', as_of,
        ], cwd=REPO, capture_output=True, text=True, timeout=20)
        if not succeeds:
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(target.exists(), 'Invalid annotation must not publish partial output')
            return proc.stderr
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return {p.name: json.loads(p.read_text()) for p in target.iterdir()}

    def validate_together(self, *outputs):
        base = self.root / 'base.json'
        base.write_text('[]')
        command = [sys.executable, str(REPO / 'databricks/enrichment/validate_batch.py')]
        for output in outputs:
            command.extend(['--batch', str(self.root / output / 'batch.json')])
        command.extend(['--base', str(base), '--as-of', '2026-11-21'])
        proc = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_cli_and_d_repeat_import_across_validity_boundaries(self):
        annotation = claim('expiry', 'Example MRI Unit')
        annotation['dates'] = dict(effective_date='2023-01-01', valid_until='2024-12-31',
                                   temporal_status='dated')
        corpus(self.root, [annotation])
        dates = [('future', '2022-12-31'), ('effective', '2023-01-01'),
                 ('last_day', '2024-12-31'), ('expired', '2025-01-01')]
        results = [self.run_cli(output, day) for output, day in dates]
        for result in results[1:]:
            self.assertEqual(results[0]['batch.json'], result['batch.json'])
        self.assertTrue(all((self.root/'future/batch.json').read_bytes() ==
                            (self.root/output/'batch.json').read_bytes() for output, _ in dates))
        ledgers = [next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')
                   for result in results]
        self.assertEqual([r['onsite_mri_documentary_candidate'] for r in ledgers],
                         [False, True, True, False])
        self.assertEqual([r['as_of'] for r in ledgers], [day for _, day in dates])
        self.assertEqual(ledgers[-1]['temporal_status'], 'expired')
        self.assertEqual(ledgers[-1]['source_temporal_status'], 'dated')
        self.assertIn('expired_claim', ledgers[-1]['review_flags'])
        self.assertFalse(any('expired_claim' in r['quality_flags'] or
                             'not_yet_effective' in r['quality_flags']
                             for r in results[-1]['batch.json']['external_facilities']))
        self.assertEqual(results[-1], self.run_cli('expired', '2025-01-01'))
        report = self.validate_together('future', 'effective', 'last_day', 'expired', 'expired')
        self.assertEqual(report['counts'], dict(source_snapshots=1, external_facilities=4,
                         facility_matches=0, facility_evidence=4, review_queue=4))

    def test_cli_rejects_unrelated_unit_even_when_excerpt_is_real(self):
        annotation = claim('onsite', 'Completely Different Synthetic Unit')
        annotation['locator'] = 'HTML p#missing-claim'
        corpus(self.root, [annotation])
        self.assertIn('Unit label is absent', self.run_cli(succeeds=False))

    def test_cli_derives_claim_locator_from_validated_selector(self):
        annotation = claim('onsite', 'Example MRI Unit')
        annotation['locator'] = 'HTML p#missing-claim'
        corpus(self.root, [annotation])
        result = self.run_cli()
        row = next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')
        evidence = next(r for r in result['batch.json']['facility_evidence']
                        if r['evidence_id']==row['evidence_id'])
        external = next(r for r in result['batch.json']['external_facilities']
                        if r['external_facility_id']==row['external_facility_id'])
        self.assertEqual(evidence['locator'], 'HTML selector=#onsite')
        self.assertEqual(external['record_locator'], evidence['locator'])
        self.assertEqual(row['claim_locator'], evidence['locator'])
        self.assertNotIn('missing-claim', json.dumps(result))

    def test_cli_requires_host_location_and_rejects_nonexistent_or_wrong_selector(self):
        annotation = claim('nearby', 'Example Laboratory Node', host_campus='Example MRI Hospital',
                           host_relation='onsite', host_locator='p#does-not-exist',
                           host_excerpt='Example Laboratory Node is near Example MRI Hospital.')
        corpus(self.root, [annotation])
        self.assertIn('host_location', self.run_cli(succeeds=False))
        for selector, message in [('p#does-not-exist', 'Missing selector'),
                                  ('p#onsite', 'its own source location')]:
            with self.subTest(selector=selector):
                annotation['record']['host_location'] = dict(selector=selector)
                corpus(self.root, [annotation])
                self.assertIn(message, self.run_cli(succeeds=False))

    def test_cli_nearby_and_remote_wording_override_onsite_annotation(self):
        for key, name, host, flag in [
            ('nearby', 'Example Laboratory Node', 'Example MRI Hospital', 'source_nearby_wording_not_onsite'),
            ('remote', 'Example Remote Node', 'Example East Campus', 'source_remote_wording_not_onsite'),
        ]:
            with self.subTest(key=key):
                annotation = claim(key, name, host_campus=host, host_relation='onsite',
                                   host_location=dict(selector='#'+key))
                annotation['record']['host_excerpt'] = annotation['excerpt']
                corpus(self.root, [annotation])
                result = self.run_cli(key)
                row = next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')
                self.assertFalse(row['onsite_mri_documentary_candidate'])
                self.assertIn(flag, row['review_flags'])
                self.assertEqual(row['host_relation'], key)
                self.assertEqual(row['declared_host_relation'], 'onsite')
                self.assertEqual(result['summary.json']['named_mri_documentary_candidates'], 0)
                if key=='nearby':
                    evidence = next(r for r in result['batch.json']['facility_evidence']
                                    if r['evidence_id']==row['evidence_id'])
                    self.assertIsNone(evidence['service'])
                    self.assertIn('mri_not_bound_to_named_unit', row['review_flags'])

    def test_cli_binds_host_quote_at_separate_source_and_preserves_its_provenance(self):
        annotation = claim('onsite', 'Example MRI Unit', host_campus='Example East Campus',
                           host_relation='onsite', host_location=dict(source='host_document', selector='#campus'),
                           host_locator='invented display locator',
                           host_excerpt='Example MRI Unit is located inside Example East Campus.')
        manifest = corpus(self.root, [annotation])
        raw = b'<p id="campus">Example MRI Unit is located inside Example East Campus.</p>'
        (self.root/'raw/host.html').write_bytes(raw)
        manifest['sources'].append(dict(manifest['sources'][0], key='host_document',
            url='https://example.invalid/host', path='raw/host.html', sha256=digest(raw)))
        (self.root/'manifest.json').write_bytes(encode(manifest))
        result = self.run_cli()
        row = next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')
        snapshot = next(r for r in result['batch.json']['source_snapshots'] if r['source_key']=='host_document')
        self.assertEqual(row['host_locator'], 'HTML selector=#campus')
        self.assertEqual(row['host_snapshot_id'], snapshot['snapshot_id'])
        self.assertEqual(row['host_source_url'], 'https://example.invalid/host')
        self.assertFalse(row['host_identity_confirmed'])
        self.assertNotIn('invented display locator', json.dumps(result))
        # The same quote exists only in the host file, never in the claim file.
        annotation['record']['host_location']['source'] = 'branchlocator'
        (self.root/'annotations.json').write_bytes(encode([annotation]))
        self.assertIn('Missing selector', self.run_cli('wrong-source', succeeds=False))
        annotation['record']['host_location']['source'] = 'host_document'
        (self.root/'annotations.json').write_bytes(encode([annotation]))
        manifest['sources'][-1]['delivery_status'] = 'restricted_hold'
        (self.root/'manifest.json').write_bytes(encode(manifest))
        self.assertIn('missing or restricted', self.run_cli('held-host', succeeds=False))

    def test_cli_host_pdf_location_is_validated_independently(self):
        import fitz
        annotation = claim('onsite', 'Example MRI Unit', host_campus='Example East Campus',
                           host_relation='onsite', host_location=dict(source='host_pdf', page=2),
                           host_excerpt='Example MRI Unit is inside Example East Campus.')
        manifest = corpus(self.root, [annotation])
        pdf = self.root/'raw/host.pdf'
        with fitz.open() as doc:
            doc.new_page().insert_text((72,72), 'Example unrelated first page.')
            doc.new_page().insert_text((72,72), annotation['record']['host_excerpt'])
            doc.save(pdf)
        manifest['sources'].append(dict(manifest['sources'][0], key='host_pdf',
            url='https://example.invalid/host.pdf', path='raw/host.pdf', sha256=digest(pdf.read_bytes())))
        (self.root/'manifest.json').write_bytes(encode(manifest))
        result = self.run_cli()
        row = next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')
        self.assertEqual(row['host_locator'], 'PDF page=2')
        annotation['record']['host_location']['page'] = 1
        (self.root/'annotations.json').write_bytes(encode([annotation]))
        self.assertIn('its own source location', self.run_cli('wrong-page', succeeds=False))

    def test_cli_derives_pdf_claim_locator_and_rejects_wrong_page(self):
        import fitz
        annotation = claim('onsite', 'Example MRI Unit')
        annotation.pop('selector')
        annotation.update(source='claim_pdf', page=2, locator='PDF page=999')
        manifest = corpus(self.root, [annotation])
        pdf = self.root/'raw/claim.pdf'
        with fitz.open() as doc:
            doc.new_page().insert_text((72,72), 'Example unrelated first page.')
            doc.new_page().insert_text((72,72), annotation['excerpt'])
            doc.save(pdf)
        manifest['sources'].append(dict(manifest['sources'][0], key='claim_pdf',
            url='https://example.invalid/claim.pdf', path='raw/claim.pdf', sha256=digest(pdf.read_bytes())))
        (self.root/'manifest.json').write_bytes(encode(manifest))
        result = self.run_cli()
        evidence = next(r for r in result['batch.json']['facility_evidence'] if r['service']=='mri')
        self.assertEqual(evidence['locator'], 'PDF page=2')
        self.assertNotIn('page=999', json.dumps(result))
        annotation['page'] = 1
        (self.root/'annotations.json').write_bytes(encode([annotation]))
        self.assertIn('Excerpt fails', self.run_cli('wrong-page', succeeds=False))

    def test_cli_nearby_heading_does_not_change_directory_modality(self):
        raw = FIXTURE.read_bytes().replace(b'<h3>Example Laboratory Node</h3>',
            b'<h3>Example Laboratory Node near Example MRI Hospital</h3>')
        corpus(self.root, raw=raw)
        result = self.run_cli()
        row = next(r for r in result['batch.json']['external_facilities'] if r['source_record_id']=='101')
        self.assertEqual(row['facility_type'], 'laboratory_documented_scope')
        self.assertEqual(row['name_original'], 'Example Laboratory Node near Example MRI Hospital')
        self.assertEqual(result['summary.json']['directory_by_unit_class']['mri_unit_label'], 1)

    def test_cli_modality_conflict_and_unrelated_mri_clause_remain_unresolved(self):
        raw = FIXTURE.read_bytes().replace(b'<h3>Example Laboratory Node</h3>',
                                           b'<h3>Example MRI Unit</h3>')
        raw = raw.replace(b'Example MRI Unit performs MRI scans inside Example East Campus.',
            b'Example Laboratory Node provides blood tests. Example MRI Unit performs MRI scans inside Example East Campus.')
        annotation = claim('onsite', 'Example Laboratory Node')
        annotation['excerpt'] = ('Example Laboratory Node provides blood tests. '
                                 'Example MRI Unit performs MRI scans inside Example East Campus.')
        corpus(self.root, [annotation], raw)
        result = self.run_cli()
        row = next(r for r in result['batch.json']['external_facilities'] if r['source_record_id']=='101')
        self.assertEqual(row['facility_type'], 'modality_unknown')
        self.assertIn('conflicting_unit_modality_labels', row['quality_flags'])
        self.assertEqual(result['summary.json']['named_mri_documentary_candidates'], 0)

    def test_cli_rejects_selector_that_combines_separate_rows(self):
        annotation = claim('onsite', 'Example MRI Unit')
        annotation['selector'] = '#onsite, #nearby'
        corpus(self.root, [annotation])
        self.assertIn('one source location', self.run_cli(succeeds=False))

    def scope_corpus(self, html, excerpt, selector='#scope', record_fields=None):
        annotation = claim('onsite', 'Example MRI Unit', **(record_fields or {}))
        annotation.update(selector=selector, excerpt=excerpt)
        raw = FIXTURE.read_bytes().replace(b'</body>', html.encode()+b'</body>')
        corpus(self.root, [annotation], raw)
        return annotation

    def scope_row(self, result):
        return next(r for r in result['claim_ledger.json'] if r['kind']=='named_mri_service')

    def test_cli_full_and_clipped_qualifiers_cannot_create_onsite_candidates(self):
        statements = [
            ('remote', 'Example MRI Unit provides MRI teleradiology reporting only. Images are acquired elsewhere.',
             'Example MRI Unit provides MRI', 'source_remote_wording_not_onsite'),
            ('nearby', 'Example MRI Unit is near the hospital where all MRI scans are performed.',
             'Example MRI Unit', 'source_nearby_wording_not_onsite'),
            ('closed', 'Example MRI Unit is closed and does not perform MRI.',
             'Example MRI Unit', 'source_nonoperating_wording'),
            ('negative', 'Example MRI Unit does not perform MRI scans.',
             'Example MRI Unit', 'source_nonoperating_wording'),
            ('referral', 'Example MRI Unit provides MRI referrals only; scans are performed elsewhere.',
             'Example MRI Unit provides MRI', 'source_remote_wording_not_onsite'),
            ('referral-only', 'Example MRI Unit is a referral-only service for MRI.',
             'Example MRI Unit', 'source_remote_wording_not_onsite'),
        ]
        for key, full, clipped, flag in statements:
            for label, excerpt in [('full', full), ('clipped', clipped)]:
                with self.subTest(key=key, quote=label):
                    self.scope_corpus('<p id="scope">'+full+'</p>', excerpt)
                    result = self.run_cli(key+'-'+label)
                    row = self.scope_row(result)
                    self.assertFalse(row['onsite_mri_documentary_candidate'])
                    self.assertIn(flag, row['review_flags'])
                    evidence = next(e for e in result['batch.json']['facility_evidence']
                                    if e['evidence_id']==row['evidence_id'])
                    self.assertEqual(evidence['excerpt'], excerpt)
                    self.assertEqual(evidence['locator'], 'HTML selector=#scope')
                    self.assertEqual(evidence['polarity'], 'inconclusive')
                    self.assertEqual(result['batch.json']['facility_matches'], [])

    def test_cli_inline_selector_cannot_clip_enclosing_statement(self):
        excerpt = 'Example MRI Unit provides MRI'
        html = '<p><span id="scope">'+excerpt+'</span> teleradiology reporting only.</p>'
        self.scope_corpus(html, excerpt)
        result = self.run_cli()
        row = self.scope_row(result)
        self.assertFalse(row['onsite_mri_documentary_candidate'])
        self.assertIn('teleradiology reporting only.', row['claim_scope_context'])
        self.assertEqual(row['claim_locator'], 'HTML selector=#scope')
        self.assertIn('p:nth-of-type', row['claim_scope_locator'])

    def test_cli_clipped_host_uses_its_own_complete_statement(self):
        excerpt = 'Example MRI Unit serves Example East Campus'
        for key, suffix, flag in [
            ('remote', ' with MRI teleradiology reporting only.', 'source_remote_wording_not_onsite'),
            ('nearby', ' from a nearby office.', 'source_nearby_wording_not_onsite'),
            ('closed', ' but is closed and does not perform MRI.', 'source_nonoperating_wording'),
            ('referral', ' through referral-only MRI services.', 'source_remote_wording_not_onsite'),
        ]:
            with self.subTest(key=key):
                html = '<p><span id="host-scope">'+excerpt+'</span>'+suffix+'</p>'
                self.scope_corpus(html, 'Example MRI Unit performs MRI scans inside Example East Campus.',
                    selector='#onsite', record_fields=dict(host_campus='Example East Campus',
                    host_relation='onsite', host_excerpt=excerpt,
                    host_location=dict(selector='#host-scope')))
                result = self.run_cli(key)
                row = self.scope_row(result)
                self.assertFalse(row['onsite_mri_documentary_candidate'])
                self.assertIn(flag, row['review_flags'])
                self.assertEqual(row['host_excerpt'], excerpt)
                self.assertEqual(row['host_locator'], 'HTML selector=#host-scope')
                self.assertIn(suffix.strip(), row['host_scope_context'])

    def test_cli_unrelated_adjacent_statement_does_not_veto_actual_onsite_claim(self):
        own = 'Example MRI Unit provides MRI scans onsite.'
        neighbors = [
            'Other Diagnostic Unit is closed and provides referral-only teleradiology from a nearby office.',
            'Other Diagnostic Unit performs MRI scans only at another hospital.',
        ]
        for index, other in enumerate(neighbors):
            for key, text in [('before', other+' '+own), ('after', own+' '+other)]:
                for label, excerpt in [('clipped', 'Example MRI Unit provides MRI'), ('full', text)]:
                    with self.subTest(neighbor=index, key=key, quote=label):
                        self.scope_corpus('<p id="scope">'+text+'</p>', excerpt)
                        result = self.run_cli(f'{index}-{key}-{label}')
                        row = self.scope_row(result)
                        self.assertTrue(row['onsite_mri_documentary_candidate'])
                        self.assertEqual(row['claim_scope_context'], own)
                        self.assertFalse(any(flag.startswith('source_') for flag in row['review_flags']))

    def test_cli_external_only_performance_is_not_onsite(self):
        own = 'Example MRI Unit performs MRI scans'
        for index, place in enumerate([
            'offsite only', 'off-site only', 'off site only', 'off‑site only',
            'only at another hospital', 'only at a separate facility',
            'at a different campus only', 'elsewhere only', 'elsewhere',
        ]):
            full = f'{own} {place}.'
            for label, excerpt in [('full', full), ('clipped', own)]:
                with self.subTest(place=place, quote=label):
                    self.scope_corpus(f'<p id="scope">{full}</p>', excerpt)
                    result = self.run_cli(f'offsite-{index}-{label}')
                    row = self.scope_row(result)
                    self.assertTrue(row['affirmative_mri_operation'])
                    self.assertFalse(row['onsite_mri_documentary_candidate'])
                    self.assertIn('source_remote_wording_not_onsite', row['review_flags'])
                    self.assertEqual(row['claim_scope_context'], full)
                    self.assertEqual(result['summary.json']['named_mri_documentary_candidates'], 0)

    def test_cli_external_only_host_statement_vetoes_onsite_claim(self):
        host = 'Example MRI Unit serves Example East Campus'
        self.scope_corpus(f'<p id="host-scope">{host}. Its scans are performed only at another hospital.</p>',
            'Example MRI Unit performs MRI scans inside Example East Campus.', selector='#onsite',
            record_fields=dict(host_campus='Example East Campus', host_relation='onsite', host_excerpt=host,
                               host_location=dict(selector='#host-scope')))
        row = self.scope_row(self.run_cli())
        self.assertFalse(row['onsite_mri_documentary_candidate'])
        self.assertIn('source_remote_wording_not_onsite', row['review_flags'])
        self.assertEqual(row['host_relation'], 'remote')

    def test_cli_unrelated_host_neighbor_does_not_veto_onsite_claim(self):
        own = 'Example MRI Unit is inside Example East Campus.'
        other = 'Other Diagnostic Unit is closed and provides remote reporting only.'
        self.scope_corpus('<p id="host-scope">'+own+' '+other+'</p>',
            'Example MRI Unit performs MRI scans inside Example East Campus.', selector='#onsite',
            record_fields=dict(host_campus='Example East Campus', host_relation='onsite',
                               host_excerpt=own, host_location=dict(selector='#host-scope')))
        result = self.run_cli()
        row = self.scope_row(result)
        self.assertTrue(row['onsite_mri_documentary_candidate'])
        self.assertEqual(row['host_scope_context'], own)
        self.assertEqual(row['host_excerpt'], own)

    def test_cli_broad_selector_does_not_choose_between_repeated_row_fragments(self):
        html = ('<table id="scope"><tr><td>Example MRI Unit</td><td>Performs MRI onsite.</td></tr>'
                '<tr><td>Example MRI Unit</td><td>Closed.</td></tr></table>')
        self.scope_corpus(html, 'Example MRI Unit')
        self.assertIn('multiple source contexts', self.run_cli(succeeds=False))

    def test_cli_same_unit_continuation_cannot_be_dropped(self):
        own = 'Example MRI Unit provides MRI.'
        continuation = 'Images are acquired elsewhere.'
        self.scope_corpus('<p id="scope">'+own+' '+continuation+'</p>', own)
        result = self.run_cli()
        row = self.scope_row(result)
        self.assertFalse(row['onsite_mri_documentary_candidate'])
        self.assertIn(continuation, row['claim_scope_context'])

    def test_cli_complete_table_row_applies_but_neighboring_row_does_not(self):
        for key, status, expected in [('closed', 'Closed; referral-only MRI.', False),
                                      ('onsite', 'Performs MRI scans onsite.', True)]:
            with self.subTest(key=key):
                html = ('<table><tr><td><span id="scope">Example MRI Unit</span></td><td>'+status+
                        '</td></tr><tr><td>Other Diagnostic Unit</td>'
                        '<td>Nearby teleradiology reporting only; closed.</td></tr></table>')
                self.scope_corpus(html, 'Example MRI Unit')
                result = self.run_cli(key)
                row = self.scope_row(result)
                self.assertEqual(row['onsite_mri_documentary_candidate'], expected)
                self.assertIn(status, row['claim_scope_context'])
                self.assertNotIn('Other Diagnostic Unit', row['claim_scope_context'])
                self.assertIn('tr:nth-of-type', row['claim_scope_locator'])

    def test_cli_pdf_statement_scope_preserves_excerpt_and_excludes_unrelated_neighbor(self):
        import fitz
        for key, statement, expected in [
            ('remote', 'Example MRI Unit provides MRI teleradiology reporting only.', False),
            ('closed', 'Example MRI Unit is closed and does not perform MRI.', False),
            ('onsite', 'Example MRI Unit provides MRI scans onsite.', True),
        ]:
            with self.subTest(key=key):
                annotation = claim('onsite', 'Example MRI Unit')
                annotation.pop('selector')
                annotation.update(source='scope_pdf', page=1, excerpt='Example MRI Unit')
                manifest = corpus(self.root, [annotation])
                pdf = self.root/('raw/scope-'+key+'.pdf')
                with fitz.open() as doc:
                    page = doc.new_page()
                    page.insert_text((72,72), statement)
                    page.insert_text((72,110), 'Other Diagnostic Unit is closed and provides teleradiology only.')
                    doc.save(pdf)
                manifest['sources'].append(dict(manifest['sources'][0], key='scope_pdf',
                    url='https://example.invalid/scope.pdf', path=pdf.relative_to(self.root).as_posix(),
                    sha256=digest(pdf.read_bytes())))
                (self.root/'manifest.json').write_bytes(encode(manifest))
                result = self.run_cli(key)
                row = self.scope_row(result)
                self.assertEqual(row['onsite_mri_documentary_candidate'], expected)
                self.assertEqual(row['claim_scope_context'], statement)
                self.assertEqual(row['claim_locator'], 'PDF page=1')

    def test_cli_requires_affirmative_operation_beyond_mri_in_unit_name(self):
        statements = [
            'Example MRI Unit cannot perform MRI scans.',
            'Example MRI Unit no longer performs MRI.',
            'Example MRI Unit provides MRI. However, it is now closed.',
            'Example MRI Unit.',
            'Example MRI Unit is inside Example East Campus.',
            'Example MRI Unit operates inside Example East Campus.',
            'Example MRI Unit performs blood tests.',
            'Example MRI Unit offers laboratory services.',
            'Example MRI Unit can perform MRI scans.',
            'Example MRI Unit may provide MRI.',
            'Example MRI Unit will provide MRI.',
            "Example MRI Unit doesn't perform MRI scans.",
            'Example MRI Unit provides MRI referral services.',
            'Example MRI Unit provides MRI reports.',
            'Example MRI Unit provides MRI teleradiology reporting only.',
            'Example MRI Unit offers MRI equipment.',
            'Example MRI Unit provides MRI training.',
        ]
        for index, text in enumerate(statements):
            for label, excerpt in [('full', text), ('clipped', 'Example MRI Unit')]:
                with self.subTest(statement=text, quote=label):
                    self.scope_corpus('<p id="scope">'+text+'</p>', excerpt)
                    result = self.run_cli(str(index)+'-'+label)
                    row = self.scope_row(result)
                    self.assertFalse(row['onsite_mri_documentary_candidate'])
                    if 'However' in text:
                        self.assertIn('However, it is now closed.', row['claim_scope_context'])
                        self.assertIn('source_nonoperating_wording', row['review_flags'])
                    else:
                        self.assertFalse(row['affirmative_mri_operation'])
                        self.assertIn('no_affirmative_operating_mri_statement', row['review_flags'])
                    evidence = next(e for e in result['batch.json']['facility_evidence']
                                    if e['evidence_id']==row['evidence_id'])
                    self.assertEqual(evidence['excerpt'], excerpt)
                    self.assertEqual(evidence['locator'], 'HTML selector=#scope')

    def test_cli_affirmative_operating_predicates_and_objects_remain_candidates(self):
        for index, text in enumerate([
            'Example MRI Unit provides MRI.',
            'Example MRI Unit performs MRI scans onsite.',
            'Example MRI Unit performs MRI scans only at Example East Campus.',
            'Example MRI Unit performs MRI scans at another time of day.',
            'Example MRI Unit performs MRI scans onsite for patients from another hospital.',
            'Example MRI Unit offers MRI services.',
            'Example MRI Unit conducts magnetic resonance imaging.',
            'Example MRI Unit is currently performing MRI scans.',
            'Example MRI Unit provided MRI services.',
            'Example MRI Unit is inside Example East Campus. It performs MRI scans onsite.',
        ]):
            with self.subTest(statement=text):
                self.scope_corpus('<p id="scope">'+text+'</p>', 'Example MRI Unit')
                row = self.scope_row(self.run_cli(str(index)))
                self.assertTrue(row['affirmative_mri_operation'])
                self.assertTrue(row['onsite_mri_documentary_candidate'])

    def test_cli_connectives_keep_same_subject_closure_but_exclude_other_subject(self):
        own = 'Example MRI Unit provides MRI.'
        for index, connector in enumerate(['However, ', 'Nevertheless, ', 'But ', 'Yet ']):
            for subject, expected in [('it', False), ('this unit', False),
                                      ('the facility', False), ('Other Diagnostic Unit', True)]:
                with self.subTest(connector=connector, subject=subject):
                    continuation = connector+subject+' is now closed and cannot perform MRI.'
                    self.scope_corpus('<p id="scope">'+own+' '+continuation+'</p>', own)
                    row = self.scope_row(self.run_cli(str(index)+'-'+subject.replace(' ', '-')))
                    self.assertEqual(row['onsite_mri_documentary_candidate'], expected)
                    if expected:
                        self.assertEqual(row['claim_scope_context'], own)
                    else:
                        self.assertIn(continuation, row['claim_scope_context'])
                        self.assertIn('source_nonoperating_wording', row['review_flags'])

    def test_cli_same_subject_host_continuation_vetoes_operative_claim(self):
        host = 'Example MRI Unit is inside Example East Campus.'
        self.scope_corpus('<p id="host-scope">'+host+' However, it is now closed.</p>',
            'Example MRI Unit performs MRI scans inside Example East Campus.', selector='#onsite',
            record_fields=dict(host_campus='Example East Campus', host_relation='onsite',
                               host_excerpt=host, host_location=dict(selector='#host-scope')))
        row = self.scope_row(self.run_cli())
        self.assertTrue(row['affirmative_mri_operation'])
        self.assertFalse(row['onsite_mri_documentary_candidate'])
        self.assertIn('However, it is now closed.', row['host_scope_context'])
        self.assertEqual(row['host_excerpt'], host)

    def test_cli_prior_same_subject_closure_is_retained_for_a_later_clipped_claim(self):
        excerpt = 'Example MRI Unit performs MRI scans onsite.'
        text = 'Example MRI Unit provides MRI. However, it is now closed. '+excerpt
        self.scope_corpus('<p id="scope">'+text+'</p>', excerpt)
        row = self.scope_row(self.run_cli())
        self.assertTrue(row['affirmative_mri_operation'])
        self.assertFalse(row['onsite_mri_documentary_candidate'])
        self.assertIn('However, it is now closed.', row['claim_scope_context'])

    def test_cli_operation_is_not_inferred_from_conditions_or_another_unit(self):
        cases = [
            ('Example MRI Unit provides MRI if approval is granted.', False),
            ('Example MRI Unit provides MRI subject to future approval.', False),
            ('Other Diagnostic Unit is closed. However, it cannot perform MRI. '
             'Example MRI Unit provides MRI scans onsite.', True),
            ('Example MRI Unit is located in Example East Campus. '
             'Other Diagnostic Unit provides MRI scans onsite.', False),
        ]
        for index, (text, expected) in enumerate(cases):
            with self.subTest(statement=text):
                self.scope_corpus('<p id="scope">'+text+'</p>', 'Example MRI Unit')
                row = self.scope_row(self.run_cli(str(index)))
                self.assertEqual(row['onsite_mri_documentary_candidate'], expected)
                if expected:
                    self.assertEqual(row['claim_scope_context'], 'Example MRI Unit provides MRI scans onsite.')


if __name__=='__main__':unittest.main()
