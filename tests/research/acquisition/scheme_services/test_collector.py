import copy
import unittest
from research.acquisition.scheme_services.collector import mentions, observations, run
from research.matching.common import MatchingError, digest


def source(tag="one", day="2026-10-01", series="synthetic-series"):
    return {"snapshot_id": "synthetic:"+tag, "series_key": series, "document_date": day,
            "local_analysis_allowed": True, "sharing_allowed": False, "rights_reason": "synthetic hold",
            "upstream_origin": "synthetic-scheme", "sha256": "a"*64,
            "retrieved_at": "2026-11-22T00:00:00Z", "url": "https://example.org/synthetic",
            "publisher": "Synthetic Publisher", "artifact_path": "synthetic.pdf"}


def record(s, tag="one", text="MRI; dialysis; orthopaedics; ICU", kind="campus_observation"):
    return {"record_id": "synthetic-row:"+tag, "snapshot_id": s["snapshot_id"],
            "source_sha256": s["sha256"], "document_date": s["document_date"],
            "name_raw": "Synthetic Example Hospital", "address_raw": "1 Fictional Street",
            "city": "Example City", "state": "Delhi", "pin": "110001", "scope_raw": text,
            "record_kind": kind, "fragments": [{"physical_page": 1, "table": 1, "bbox": [0, 2, 20, 12],
                                                 "cells": {"scope_raw": text}}],
            "scheme_id": None, "validity_raw": "synthetic date wording"}


class SchemeTests(unittest.TestCase):
    def test_offsets_and_repeated_mentions_are_literal(self):
        text = "☀ MRI and MRI; magnetic\nresonance imaging; haemodialysis; CT scan"
        items = mentions(text)
        self.assertEqual(sum(i['service'] == 'mri' for i in items), 3)
        for item in items:
            self.assertEqual(text[item['start']:item['end']], item['excerpt'])
            self.assertEqual(item['clinical_status'], 'unconfirmed')

    def test_long_exception_lists_are_never_affirmative(self):
        items = mentions("Except " + "synthetic scope, " * 50 + "MRI, dialysis and trauma care")
        self.assertEqual(len(items), 3)
        self.assertTrue(all('negation_or_exclusion_cue' in i['cue_flags'] for i in items))
        self.assertTrue(all(i['polarity'] == 'unadjudicated' for i in items))

    def test_referral_planned_and_scheme_suspension_remain_flags(self):
        items = mentions("MRI planned; dialysis referred elsewhere; trauma empanelment suspended")
        self.assertTrue(all(len(i['cue_flags']) == 3 for i in items))
        self.assertTrue(all(i['procedure_count'] is None for i in items))

    def test_no_inference_from_adjacent_specialties(self):
        self.assertEqual(mentions("Radiology, nephrology, general surgery, laboratory medicine"), [])
        self.assertEqual({i['service'] for i in mentions("pediatrics, neurosurgery, burns, ventilation, blood bank")},
                         {'pediatrics', 'neurosurgery', 'burns', 'ventilation', 'blood_bank'})

    def test_historical_future_and_tied_editions(self):
        old, new, future = source(), source('new', '2026-11-01'), source('future', '2026-12-01')
        rows, ledger, selected, unresolved = observations([record(old), record(new,'new'), record(future,'future')],
                                                         [old,new,future], '2026-11-22')
        self.assertEqual(selected, {new['snapshot_id']})
        self.assertEqual(len(rows),3)
        self.assertEqual(len(ledger),12)
        tied=source('tied','2026-11-01')
        _,_,selected,unresolved=observations([], [new,tied], '2026-11-22')
        self.assertEqual(selected,set())
        self.assertEqual(unresolved,['synthetic-series'])

    def test_fail_closed_on_rights_hash_and_duplicates(self):
        s=source();r=record(s)
        for key,value in [('local_analysis_allowed',False),('sharing_allowed',None),('rights_reason','')]:
            bad={**s,key:value}
            with self.assertRaises(MatchingError): observations([r],[bad],'2026-11-22')
        with self.assertRaises(MatchingError): observations([{**r,'source_sha256':'b'*64}],[s],'2026-11-22')
        with self.assertRaises(MatchingError): observations([r,r],[s],'2026-11-22')

    def test_manual_page_locator_retained_and_missing_locator_rejected(self):
        s=source(); r=record(s); r.pop('fragments')
        with self.assertRaises(MatchingError): observations([r],[s],'2026-11-22')
        r.update(physical_page=4,locator='Synthetic page 4 table row 7')
        rows,_,_,_=observations([r],[s],'2026-11-22')
        self.assertEqual(rows[0]['record']['locator'],r['locator'])
        self.assertEqual(rows[0]['record']['validity_raw'],'synthetic date wording')

    def test_unusable_pdf_and_manual_locators_are_rejected(self):
        s = source()
        row = record(s)
        fragment = row["fragments"][0]
        overrides = [{"fragments": value} for value in ("page 1", [{}], fragment, [None])]
        for field, bad in (("physical_page", True), ("table", False), ("table", 0),
                           ("bbox", [0, 0, 0, 5]), ("bbox", [0, 0, True, 5]),
                           ("bbox", [0, 0, float("inf"), 5]), ("bbox", None)):
            overrides.append({"fragments": [{**fragment, field: bad}]})
        for page, locator in ((True, "row 1"), (0, "row 1"), ("1", "row 1"), (1, "   ")):
            overrides.append({"fragments": [], "physical_page": page, "locator": locator})
        for override in overrides:
            with self.subTest(override=override), self.assertRaisesRegex(MatchingError, "locator"):
                observations([{**row, **override}], [s], "2026-11-22")

    def test_multi_page_fragments_preserved_verbatim(self):
        s = source()
        row = record(s)
        fragments = [*row["fragments"], {**row["fragments"][0], "physical_page": 2}]
        expected = copy.deepcopy(fragments)
        rows, _, _, _ = observations([{**row, "fragments": fragments}], [s], "2026-11-22")
        self.assertEqual(rows[0]["record"]["fragments"], expected)

    def test_full_occurrences_and_groups_preserved_without_clinical_promotion(self):
        s=source(); r=record(s)
        original={'unique_id':'same','name':'Synthetic Example Hospital','address_stateOrRegion':'Delhi',
                  'address_zipOrPostcode':'110001'}
        base=[{'facility_id':'synthetic:1','source_row':original},
              {'facility_id':'synthetic:2','source_row':copy.deepcopy(original)},
              {'facility_id':'synthetic:3','source_row':{'unique_id':'sparse'}}]
        metadata={'mapping':{'id':'unique_id','name':'name','state':'address_stateOrRegion','pin':'address_zipOrPostcode'},
                  'row_count':3,'base_file_sha256':digest(base),'original_table':'synthetic.base','observed_delta_version':0}
        result=run([r,record(s,'group',kind='multi_campus_group')],[s],base,metadata,
                   as_of='2026-11-22',base_sha256=digest(base),expected_rows=3,expected_ids=2,expected_duplicates=1)
        self.assertEqual(result['summary']['decision_count'],9)
        self.assertEqual(result['summary']['selected_campus_records'],1)
        self.assertEqual(result['summary']['service_mentions']['mri']['raw_mentions_all_editions'],2)
        self.assertEqual(result['summary']['service_mentions']['mri']['selected_campus_record_service_observations'],1)
        self.assertEqual(result['summary']['service_mentions']['mri']['observed_upstream_origins'],1)
        self.assertTrue(all(x == {'yes':0,'no':0,'unconfirmed':3} for x in result['summary']['coverage'].values()))
        self.assertEqual(len(result['national_rows']),3)
        self.assertEqual(len(result['service_status']['facilities']),3)
        self.assertEqual(result['candidate_batch_PRIVATE_NOT_ADMITTED']['facility_evidence'],[])


if __name__ == '__main__': unittest.main()
