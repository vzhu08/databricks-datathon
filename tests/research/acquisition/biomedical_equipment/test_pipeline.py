"""Synthetic-only fixtures for the NHSRC transport, row and review boundaries."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from research.acquisition.biomedical_equipment.capture import parse_catalogue
from research.acquisition.biomedical_equipment.dashboards import parse_index
from research.acquisition.biomedical_equipment.extract import modality_hits, safe_members, workbook_rows, scalar
from research.acquisition.biomedical_equipment.observations import classify_rows, condition
from research.acquisition.biomedical_equipment.handoff import replay
from research.acquisition.biomedical_equipment.capture import sha256


def catalogue(number, link="/synthetic.xlsx", state="Rajasthan"):
    return f'<table class="views-table"><caption>{state}</caption><tr><td>{number}</td><td>Synthetic</td><td><a href="{link}">File</a></td></tr></table>'


def synthetic_xlsx(path):
    """Minimal OOXML, deliberately stale A1 dimension and a far-away row."""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Synthetic" sheetId="1" state="hidden" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', f'''<worksheet xmlns="{ns}"><dimension ref="A1"/><sheetData>
          <row r="1"><c r="A1" t="inlineStr"><is><t>MRI</t></is></c><c r="B1"><v>0</v></c></row>
          <row r="2"><c r="A2" t="inlineStr"><is><t>MRI</t></is></c><c r="B2"><f>1-1</f><v>0</v></c><c r="C2"><f>1+1</f></c></row>
          <row r="1048576"><c r="D1048576" t="inlineStr"><is><t>Last record</t></is></c></row>
          </sheetData><mergeCells><mergeCell ref="A1:A2"/></mergeCells></worksheet>''')


def rows(values):
    for i, cells in enumerate(values, 1):
        yield {"kind": "sheet_row", "sheet": "Synthetic", "row": i,
               "cells": {str(j): v for j, v in enumerate(cells, 1) if v is not None},
               "record_id": f"synthetic:{i}", "edition_sha256": "a" * 64}


class CatalogueTests(unittest.TestCase):
    def test_repeat_url_keeps_both_numbered_occurrences(self):
        result = parse_catalogue({0: catalogue(1), 1: catalogue(2)})
        self.assertEqual([x["entry"] for x in result], [1, 2])
        self.assertEqual(result[0]["url"], result[1]["url"])
        self.assertIsNone(result[0]["observation_period"])

    def test_duplicate_index_number_fails(self):
        with self.assertRaises(ValueError):
            parse_catalogue({0: catalogue(1), 1: catalogue(1)})

    def test_other_publisher_requires_separate_review(self):
        with self.assertRaises(ValueError):
            parse_catalogue({0: catalogue(1, "https://example.org/file.xlsx")})

    def test_joint_jurisdiction_remains_joint(self):
        page = '<table><tr><td>Jammu and Kashmir + Ladakh</td><td>PPP</td><td>Synthetic</td><td><a href="https://example.org/">Dashboard</a></td></tr></table>'
        result = parse_index(page)
        self.assertEqual(result[0]["jurisdictions"], ["Jammu and Kashmir", "Ladakh"])
        self.assertEqual(result[0]["bulk_permission"], "not_established")
        self.assertFalse(result[0]["export_attempted"])


class ExtractionTests(unittest.TestCase):
    def test_sparse_rows_zero_formula_cache_and_hidden_sheet_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.xlsx'; synthetic_xlsx(path)
            sheets = []; result = list(workbook_rows(path, '.xlsx', sheets))
        self.assertEqual([x['row'] for x in result], [1, 2, 1048576])
        self.assertEqual(result[0]['cells']['2'], 0)
        self.assertEqual(result[1]['cells']['2'], 0)
        self.assertIsNone(result[1]['cells']['3'])
        self.assertEqual(result[1]['formulas']['2']['text'], '1-1')
        self.assertTrue(sheets[0]['hidden'])
        self.assertEqual(sheets[0]['merged_ranges'], ['A1:A2'])

    def test_html_disguised_as_xls_retains_scope_and_spans(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.xls'
            path.write_text('<html><body>Period: 2010-2015<table><tr><td colspan="2">Equipment</td><td>Qty</td></tr><tr><td>Dialysis</td><td></td><td>0</td></tr></table></body></html>')
            result = list(workbook_rows(path, '.xls', []))
        self.assertEqual(result[0]['kind'], 'html_heading')
        self.assertIn('2010-2015', result[0]['cells']['1'])
        self.assertEqual(result[1]['cells']['3'], 'Qty')
        self.assertEqual(result[2]['cells']['3'], '0')

    def test_archive_traversal_rejected_before_extraction(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z: z.writestr('../escape.xlsx', b'no')
        with zipfile.ZipFile(stream) as z:
            with self.assertRaises(ValueError): safe_members(z)

    def test_repeated_modality_hits_remain_located(self):
        result = modality_hits('No MRI service; MRI planned; dialysis unavailable.')
        self.assertEqual([x[0] for x in result], ['mri', 'mri', 'dialysis'])
        self.assertEqual([x[1] for x in result[:2]], [3, 16])

    def test_time_cell_is_json_serializable(self):
        from datetime import time
        self.assertEqual(json.loads(json.dumps(scalar(time(12, 30))))['value'], '12:30:00')


class ObservationTests(unittest.TestCase):
    def test_duplicate_rows_missing_quantity_and_zero_are_distinct(self):
        result = list(classify_rows(rows([
            ['Institute Name', 'Equipment Name', 'Qty', 'Status'],
            ['Synthetic A', 'MRI', 0, 'Functional'],
            ['Synthetic A', 'MRI', None, 'Non Functional Not Repairable'],
            ['Synthetic A', 'MRI', 0, 'Functional']])) )
        self.assertEqual(len(result), 3)
        self.assertEqual(len({x['observation_id'] for x in result}), 3)
        self.assertEqual(result[0]['quantity_fields'][0]['value'], 0)
        self.assertIsNone(result[1]['quantity_fields'][0]['value'])
        self.assertEqual(result[1]['condition_fields'][0]['interpretation'], 'nonfunctional_not_repairable')
        self.assertTrue(all(x['service_decision'] is None for x in result))
        self.assertTrue(all(x['observation_period'] is None for x in result))

    def test_blank_facility_is_not_filled_down_and_group_not_campus(self):
        result = list(classify_rows(rows([
            ['Institution Name', 'Equipment Description', 'Qty'],
            ['Synthetic and Associated Hospitals', 'Dialysis Unit', 1],
            [None, 'MRI', 2]])))
        self.assertIn('possible_group_not_campus', result[0]['flags'])
        self.assertIsNone(result[1]['facility_printed'])
        self.assertIsNone(result[1]['source_facility_key'])

    def test_ambiguous_equipment_headers_are_not_selected(self):
        self.assertEqual(list(classify_rows(rows([
            ['Equipment Name', 'Equipment Description'], ['MRI', 'Dialysis']]))), [])

    def test_installation_date_never_becomes_condition_date(self):
        result = list(classify_rows(rows([
            ['Equipment Name', 'Installation date', 'Status'], ['MRI', '2015', 'W']])))[0]
        self.assertEqual(result['dates_and_coverage_fields'][0]['value'], '2015')
        self.assertIsNone(result['observation_period'])
        self.assertEqual(result['condition_fields'][0]['interpretation'], 'uninterpreted')

    def test_negation_is_not_positive(self):
        self.assertEqual(condition('Non Functional Not Repairable'), 'nonfunctional_not_repairable')
        self.assertEqual(condition('Not installed'), 'not_installed')


class HandoffTests(unittest.TestCase):
    def test_held_bytes_never_fetched_and_cached_digest_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'blobs').mkdir()
            source = root/'blobs'/'source'; source.write_bytes(b'synthetic')
            digest = sha256(source); source.rename(root/'blobs'/digest)
            permitted = {"sha256": digest, "bytes": 9, "urls": ["https://nhsrcindia.org/synthetic.xlsx"],
                         "retrieved_at": "2026-01-01T00:00:00Z", "catalogue_entries": [],
                         "publication_date": None, "observation_period": None, "rights": {"status": "permitted"}}
            held = {**permitted, "sha256": "b"*64, "rights": {"status": "hold"}}
            with patch('research.acquisition.biomedical_equipment.handoff.fetch') as fetch:
                result = replay({"files": [permitted, held]}, root)
                fetch.assert_not_called()
            self.assertEqual(result['held_editions_not_fetched'], 1)
            self.assertEqual(result['verified_permitted_urls'], 1)

    def test_changed_publisher_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = {"sha256": "a"*64, "bytes": 9, "urls": ["https://nhsrcindia.org/synthetic.xlsx"],
                    "retrieved_at": "2026-01-01T00:00:00Z", "catalogue_entries": [],
                    "publication_date": None, "observation_period": None, "rights": {"status": "permitted"}}
            with patch('research.acquisition.biomedical_equipment.handoff.fetch', return_value={"download_ok": True, "sha256": "c"*64, "bytes": 9}):
                with self.assertRaises(ValueError): replay({"files": [file]}, tmp)


if __name__ == '__main__':
    unittest.main()
