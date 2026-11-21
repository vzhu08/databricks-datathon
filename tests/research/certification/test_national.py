"""Synthetic national-register fixtures; no real facility data."""
from html import escape
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from research.certification.common import ROOT, SourceError, read, save, sha
from research.certification.fetch import Fetcher
from research.certification.national_build import build, challenge_sample, date_class
from research.certification.national_capture import capture
from research.certification.national_run import acquire, finalize, recheck, replay
from research.certification.national_tables import HEADERS, LANDING, MAP, MAP_HEADERS, controls, filtered_url, map_summary, page
from research.certification.episodes import parse_date
from research.certification.tables import POLICY, TERMS

ROWS = [["1", "Synthetic Alpha", "Certified", "24/11/2027"],
        ["2", "Synthetic Beta", "Conditionality", "20/01/2020"],
        ["3", "Synthetic Gamma", "Certified", "11/12/2026"]]


def fixture(status="All", rows=None, total=None, next_page=None, state="38"):
    rows = [r[:] for r in ROWS if status == "All" or r[2] == status] if rows is None else rows
    total = len(rows) if total is None else total
    form = '<form method="get" action="/quality-certification/national-level-certificate"><select name="field_state_target_id">'
    form += ''.join('<option value="' + val + '"' + (' selected' if state == val else '') + '>' + label + '</option>'
                    for val, label in [('All', 'Any'), ('38', 'Rajasthan')]) + '</select><select name="field_certified_value">'
    form += ''.join('<option value="' + val + '"' + (' selected' if status == val else '') + '>' + val + '</option>'
                    for val in ['All', 'Certified', 'Conditionality']) + '</select></form>'
    table = '<table><caption>Rajasthan</caption><thead><tr>' + ''.join('<th>' + h + '</th>' for h in HEADERS) + '</tr></thead><tbody>'
    table += ''.join('<tr>' + ''.join('<td>' + escape(c) + '</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table>'
    link = '' if next_page is None else '<li class="pager__item--next"><a href="' + escape(url(status, next_page)) + '">Next</a></li>'
    return ('<div class="view-national-level-certificate view-display-id-page_1"><div class="view-header">Total Number of facility : ' +
            str(total) + '</div>' + form + table + link + '</div><div class="views-field-changed"><span class="field-content">30-09-2026</span></div>').encode()


def url(status="All", number=None):
    result = LANDING + '?field_state_target_id=38&field_certified_value=' + status
    return result if number is None else result + '&page=%2C' + str(number)


def map_fixture(values=None):
    values = ["1", "2", "3", "4", "5", "6"] if values is None else values
    return ('<div class="view-map-report"><table><thead><tr>' + ''.join('<th>' + h + '</th>' for h in MAP_HEADERS) +
            '</tr></thead><tbody><tr><td>Rajasthan</td>' + ''.join('<td>' + v + '</td>' for v in values) +
            '</tr></tbody></table></div><div class="views-field-changed"><span class="field-content">30-09-2026</span></div>').encode()


class FakeFetcher:
    def __init__(self, root, mapping):
        self.root, self.mapping, self.attempt_log = Path(root), mapping, []
        (self.root / "raw").mkdir(parents=True, exist_ok=True)

    def get(self, url):
        value = self.mapping[url]
        self.attempt_log.append({"url": url})
        if isinstance(value, Exception):
            raise value
        name = 'raw/' + sha(value) + '.html'
        (self.root / name).write_bytes(value)
        return {"url": url, "final_url": url, "http_status": 200, "sha256": sha(value), "artifact": name,
                "bytes": len(value), "retrieved_at": "2026-11-21T00:00:00Z"}


class Tables(unittest.TestCase):
    def test_observed_filter_value_and_status_options(self):
        c = controls(fixture(state="All"))
        self.assertEqual(c['state_value'], '38')
        self.assertEqual(filtered_url(c), url())
        self.assertEqual(set(c['status_options']), {'All', 'Certified', 'Conditionality'})

    def test_comma_pager_and_caption(self):
        p = page(fixture(next_page=1), url())
        self.assertEqual(p['next_url'], url(number=1))
        self.assertEqual(p['advertised_total'], 3)
        self.assertEqual(p['updated_till']['iso'], '2026-09-30')
        self.assertIsNone(p['rows'][0]['valid_from_raw'])
        self.assertIsNone(p['rows'][0]['department_scope'])

    def test_plain_page_and_lost_filters_fail(self):
        for bad in [url(number=1).replace('%2C1','1'), url().replace('=38','=All')]:
            with self.assertRaises(SourceError):
                page(fixture(), bad, 1)
        with self.assertRaisesRegex(SourceError, 'selected_filter'):
            page(fixture(state='All'), url())

    def test_wrong_caption_and_headers_fail(self):
        for old,new in [(b'<caption>Rajasthan',b'<caption>Other'),(b'Validity Till Date',b'Unexpected heading')]:
            with self.assertRaises(SourceError):
                page(fixture().replace(old,new),url())

    def test_cycle_and_foreign_next_link_fail(self):
        with self.assertRaisesRegex(SourceError,'next_changed_filter_or_page'):
            page(fixture(next_page=0),url())
        with self.assertRaises(SourceError):
            page(fixture(next_page=1).replace(b'qps.nhsrcindia.org',b'other.example'),url())

    def test_status_filter_cannot_return_other_status(self):
        with self.assertRaisesRegex(SourceError,'status_filter_not_applied'):
            page(fixture('Certified', rows=ROWS),url('Certified'),status='Certified')

    def test_record_identity_excludes_serial_but_preserves_variants(self):
        first=page(fixture(rows=[ROWS[0]]),url())['rows'][0]
        duplicate=page(fixture(rows=[['99']+ROWS[0][1:]]),url())['rows'][0]
        changed=page(fixture(rows=[['1',ROWS[0][1],'Conditionality',ROWS[0][3]]]),url())['rows'][0]
        self.assertEqual(first['record_id'],duplicate['record_id'])
        self.assertNotEqual(first['record_id'],changed['record_id'])

    def test_map_blank_is_unknown_not_zero(self):
        m=map_summary(map_fixture(['1','','3','4','5','6']))
        self.assertIsNone(m['counts']['No. of SDH'])
        self.assertIsNone(m['sum_of_displayed_categories'])
        self.assertEqual(m['inclusion_of_conditionality'],'not_stated')

    def test_future_end_is_not_current_status(self):
        self.assertEqual(date_class(parse_date('24/11/2027'),'2026-11-21'),'end_in_future_under_all_parses')
        self.assertEqual(date_class(parse_date('11/12/2026'),'2026-11-21'),'ambiguous_at_cutoff')
        self.assertEqual(date_class(parse_date('21/11/2026'),'2026-11-21'),'end_on_cutoff')
        self.assertEqual(date_class(parse_date('invalid'),'2026-11-21'),'unknown')
        with self.assertRaisesRegex(SourceError, 'cutoff_must_be_YYYY_MM_DD'):
            date_class(parse_date('24/12/2026'), '20261121')


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.mapping={LANDING:fixture(state='All'),MAP:map_fixture(),POLICY:b'<p>Synthetic policy</p>',TERMS:b'<p>Synthetic terms</p>',
                      **{url(s):fixture(s) for s in ['All','Certified','Conditionality']}}

    def tearDown(self):
        self.temp.cleanup()

    def capture(self,limit=100):
        return capture(self.root,max_pages=limit,fetcher=FakeFetcher(self.root,self.mapping))

    def test_complete_three_views_and_conservative_projection(self):
        self.capture();r=build(self.root,'2026-11-21')
        self.assertEqual(r['report']['distinct_record_payloads'],3)
        self.assertTrue(r['report']['status_views_multiset_equals_all'])
        self.assertEqual(len(r['batch']['facility_evidence']),1)
        e=r['batch']['facility_evidence'][0]
        self.assertEqual(e['polarity'],'inconclusive')
        self.assertIsNone(e['effective_date'])
        self.assertEqual(r['report']['evidence_withheld_for_v1_temporal_limits'],2)
        self.assertEqual(r['report']['verified_campuses'],0)

    def december_capture(self):
        rows = [['1', 'Synthetic December', 'Certified', '24/12/2026']]
        self.mapping[url()] = fixture(rows=rows)
        self.mapping[url('Certified')] = fixture('Certified', rows=rows)
        self.mapping[url('Conditionality')] = fixture('Conditionality', rows=[])
        self.capture()

    def test_compact_cutoff_rejected_before_projection_or_output(self):
        self.december_capture()
        with self.assertRaisesRegex(SourceError, 'cutoff_must_be_YYYY_MM_DD'):
            build(self.root, '20261121')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('research.certification.national_run.local_path', side_effect=lambda p: Path(p).resolve()):
            for operation in (recheck, finalize):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaisesRegex(SourceError, 'cutoff_must_be_YYYY_MM_DD'):
                        operation(self.root, '20261121')
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_canonical_cutoff_keeps_december_end_out_of_expired_projection(self):
        self.december_capture()
        result = build(self.root, '2026-11-21')
        self.assertEqual(result['ledger'][0]['date_class'], 'end_in_future_under_all_parses')
        self.assertIsNone(result['ledger'][0]['evidence_id'])
        self.assertEqual(result['batch']['facility_evidence'], [])
        self.assertEqual(len(result['batch']['review_queue']), 1)
        with patch('research.certification.national_run.local_path', side_effect=lambda p: Path(p).resolve()):
            finalize(self.root, '2026-11-21')
            self.assertEqual(replay(self.root)['status'], 'byte_identical_replay')
        self.assertEqual(read(self.root / 'batch.json')['facility_evidence'], [])
        checked = subprocess.run([sys.executable, str(ROOT / 'databricks/enrichment/validate_batch.py'),
                                  '--batch', str(self.root / 'batch.json'), '--base', str(self.root / 'empty_base.json'),
                                  '--as-of', '2026-11-21'], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_acquisition_rejects_noncanonical_cutoffs_before_any_write(self):
        target = self.root / 'new-run'
        with patch('research.certification.national_run.local_path', side_effect=lambda p: Path(p).resolve()), \
                patch('research.certification.national_run.capture') as capture_call:
            for cutoff in ('20261121', '2026-W47-6', '2026-11-21\n'):
                with self.subTest(cutoff=cutoff):
                    with self.assertRaisesRegex(SourceError, 'cutoff_must_be_YYYY_MM_DD'):
                        acquire(target, cutoff)
                    self.assertFalse(target.exists())
            capture_call.assert_not_called()

    def test_pagination_total_reconciliation(self):
        self.mapping[url()]=fixture(rows=ROWS[:2],total=3,next_page=1)
        self.mapping[url(number=1)]=fixture(rows=ROWS[2:],total=3)
        self.capture();r=build(self.root,'2026-11-21')['report']
        self.assertTrue(r['views']['All']['parsed_equals_advertised'])

    def test_changed_total_preserved_not_reconciled(self):
        self.mapping[url()]=fixture(rows=ROWS[:2],total=3,next_page=1)
        self.mapping[url(number=1)]=fixture(rows=ROWS[2:],total=4)
        self.capture();r=build(self.root,'2026-11-21')['report']
        self.assertTrue(r['advertised_total_changed_during_capture'])
        self.assertEqual(r['views']['All']['advertised_totals'],[3,4])
        self.assertFalse(r['views']['All']['parsed_equals_advertised'])

    def test_duplicate_records_keep_all_occurrences(self):
        self.mapping[url()]=fixture(rows=ROWS+[['4']+ROWS[0][1:]])
        self.capture();r=build(self.root,'2026-11-21')
        self.assertEqual(r['report']['source_row_occurrences'],4)
        self.assertEqual(r['report']['distinct_record_payloads'],3)
        self.assertEqual(r['report']['exact_duplicate_occurrences'],1)
        self.assertEqual(sum(len(x['occurrences']) for x in r['ledger']),4)

    def test_same_name_different_status_or_date_never_links(self):
        self.mapping[url()]=fixture(rows=ROWS+[['4',ROWS[0][1],'Conditionality','20/01/2020']])
        self.capture();r=build(self.root,'2026-11-21')
        self.assertEqual(r['report']['repeated_label_groups'],1)
        self.assertEqual(r['report']['unresolved_record_variants_in_repeated_label_groups'],2)
        self.assertFalse(r['batch']['facility_matches'])
        self.assertEqual(r['report']['verified_renewal_links'],0)

    def test_status_view_duplicate_and_missing_row_are_reported(self):
        self.mapping[url('Certified')]=fixture('Certified',rows=[ROWS[0],['2']+ROWS[0][1:]])
        self.capture();r=build(self.root,'2026-11-21')
        self.assertFalse(r['report']['status_views_multiset_equals_all'])
        self.assertEqual(r['report']['status_view_missing_occurrences'],1)
        self.assertEqual(r['report']['status_view_additional_occurrences'],1)
        self.assertEqual(r['audit']['counts']['unresolved_not_found_in_status_view'],1)
        self.assertTrue(r['discrepancies']['source_rows'])

    def test_page_cap_and_transport_failure_mark_incomplete(self):
        self.mapping[url()]=fixture(total=4,next_page=1)
        c=self.capture(1)
        self.assertFalse(c['views']['All']['complete'])
        self.assertEqual(c['views']['All']['termination'],'national_pagination_limit_reached')

    def test_later_page_failure_retains_initial_rows(self):
        self.mapping[url()]=fixture(total=4,next_page=1)
        self.mapping[url(number=1)]=SourceError('http_503')
        c=self.capture();r=build(self.root,'2026-11-21')
        self.assertEqual(c['views']['All']['termination'],'http_503')
        self.assertEqual(len(r['ledger']),3)

    def test_repeated_page_is_not_silently_counted(self):
        self.mapping[url()]=fixture(total=6,next_page=1)
        self.mapping[url(number=1)]=fixture(total=6)
        c=self.capture()
        self.assertEqual(c['views']['All']['row_count'],3)
        self.assertEqual(c['views']['All']['termination'],'national_repeated_page_content')

    def test_unknown_labels_and_missing_names_preserved(self):
        self.mapping[url()]=fixture(rows=[['1','','Unspecified programme label',''],['2','Synthetic Epsilon','','20/01/2020']])
        self.capture();r=build(self.root,'2026-11-21')
        self.assertEqual(len(r['ledger']),2)
        self.assertTrue(any(x['facility'] is None for x in r['ledger']))
        self.assertTrue(any(x['v1_evidence_withheld_reason']=='missing_printed_status' for x in r['ledger']))

    def test_historical_ambiguous_end_not_guessed(self):
        self.mapping[url()]=fixture(rows=[['1','Synthetic Old','Certified','03/04/2020']])
        self.capture();r=build(self.root,'2026-11-21')
        self.assertEqual(r['batch']['facility_evidence'][0]['temporal_status'],'historical')
        self.assertIsNone(r['batch']['facility_evidence'][0]['valid_until'])
        self.assertEqual(len(r['ledger'][0]['end']['candidates']),2)

    def test_sample_determinism_and_strata(self):
        self.capture();rows=build(self.root,'2026-11-21')['ledger']
        self.assertEqual(challenge_sample(rows),challenge_sample(list(reversed(rows))))
        self.assertEqual({r['status_original'] for r in challenge_sample(rows)},{'Certified','Conditionality'})

    def test_changed_map_is_explicit_blocker(self):
        self.mapping[MAP]=b'<p>Changed source</p>'
        self.capture();r=build(self.root,'2026-11-21')['report']
        self.assertIsNotNone(r['map_parse_error'])
        self.assertIsNone(r['map'])

    def test_raw_corruption_fails_replay(self):
        c=self.capture();doc=c['documents']['view_0_0']
        (self.root/doc['artifact']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(SourceError,'hash_mismatch'):
            build(self.root,'2026-11-21')

    def test_offline_replay_no_overwrite_and_exact_manifest(self):
        self.capture()
        with patch('research.certification.national_run.local_path',side_effect=lambda p:Path(p).resolve()):
            finalize(self.root,'2026-11-21')
            with patch.object(Fetcher,'get',side_effect=AssertionError('network on replay')):
                self.assertEqual(replay(self.root)['status'],'byte_identical_replay')
            with self.assertRaisesRegex(SourceError,'outputs_already_exist'):
                finalize(self.root,'2026-11-21')
            (self.root/'ledger.json').write_text('[]')
            with self.assertRaisesRegex(SourceError,'file_hash_mismatch'):
                replay(self.root)

    def test_discrepancy_recheck_preserves_original_snapshot(self):
        self.mapping[url('Certified')]=fixture('Certified',rows=[ROWS[0],['2']+ROWS[0][1:]])
        self.capture();before=(self.root/'national_capture.json').read_bytes()
        with patch('research.certification.national_run.local_path',side_effect=lambda p:Path(p).resolve()):
            checks=recheck(self.root,'2026-11-21',FakeFetcher(self.root,self.mapping))
            self.assertTrue(all(c['raw_bytes_unchanged'] for c in checks))
            self.assertEqual(before,(self.root/'national_capture.json').read_bytes())
            finalize(self.root,'2026-11-21')
            self.assertEqual(replay(self.root)['verified_derived_files'],8)

    def test_existing_d_validator_accepts_projection(self):
        self.capture();r=build(self.root,'2026-11-21')
        save(self.root/'batch.json',r['batch']);save(self.root/'base.json',[])
        p=subprocess.run([sys.executable,str(ROOT/'databricks/enrichment/validate_batch.py'),'--batch',str(self.root/'batch.json'),
                          '--base',str(self.root/'base.json'),'--as-of','2026-11-21'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)


if __name__=='__main__':
    unittest.main()
