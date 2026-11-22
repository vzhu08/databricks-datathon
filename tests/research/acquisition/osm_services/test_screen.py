"""Invented map objects; no real facility/source rows."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from research.acquisition.osm_services.core import classify, family, observations, screen, typed_id
from research.acquisition.osm_services.hot import load
from research.acquisition.osm_services.__main__ import reconcile_facility_key_counts


def record(ident='node/1', tags=None):
    return {'osm_id':ident,'tags':tags or {},'state':None,'locators':['synthetic#/features/0'],
            'payload_sha256':'abc','name':'Invented clinic','branch':None}


class ClassifierTests(unittest.TestCase):
    def test_exact_service_tokens(self):
        for service,value in [('dialysis',' dialysis ; nephrology'),('mri','radiology;mri_scan'),('trauma_care','trauma care')]:
            self.assertEqual(classify({},'healthcare:speciality',value,service),'explicit_service_tag')

    def test_generic_specialties_do_not_assert_target(self):
        for service,value in [('dialysis','nephrology'),('mri','radiology'),('trauma_care','emergency')]:
            self.assertIsNone(classify({},'healthcare:speciality',value,service))

    def test_trauma_specialist_scope(self):
        self.assertEqual(classify({},'healthcare:speciality','trauma','trauma_care'),'specialty_scope_review')
        self.assertEqual(classify({},'healthcare:speciality','consultant_orthopedic_and_trauma_surgeon','trauma_care'),'free_text_review')

    def test_names_never_transfer_services_to_hospital(self):
        r=record(tags={'name':'Invented Hospital near Dialysis Clinic','healthcare':'hospital'})
        self.assertEqual([o['category'] for o in observations(r)],['name_or_operator_only'])
        self.assertEqual(classify({},'name','Trauma Nursing Home','trauma_care'),'name_or_operator_only')

    def test_negative_and_zero(self):
        for value in ['no','false','0']:
            self.assertEqual(classify({},'healthcare:mri',value,'mri'),'negative_or_unavailable')
        self.assertEqual(classify({},'healthcare:speciality','no dialysis','dialysis'),'negative_or_unavailable')

    def test_future_and_defunct(self):
        self.assertEqual(classify({},'proposed:healthcare','dialysis','dialysis'),'future')
        self.assertEqual(classify({},'disused:healthcare','dialysis','dialysis'),'defunct_or_closed')
        tags={'healthcare':'dialysis','disused':'yes'}
        self.assertEqual(classify(tags,'healthcare','dialysis','dialysis'),'defunct_or_closed')
        self.assertEqual([o['category'] for o in observations(record(tags=tags))],['defunct_or_closed'])
        self.assertEqual(observations(record(tags={'construction':'yes','disused':'yes'})),[])

    def test_referral_gate(self):
        tags={'healthcare':'dialysis','description':'Dialysis patients are referred offsite.'}
        self.assertEqual(classify(tags,'healthcare','dialysis','dialysis'),'referral_or_offsite')

    def test_unrelated_description_does_not_negate_service(self):
        self.assertEqual(classify({'description':'No MRI; referred elsewhere.'},'healthcare','dialysis','dialysis'),'explicit_service_tag')

    def test_home_and_numeric_not_onsite(self):
        self.assertEqual(classify({},'healthcare:speciality','home dialysis','dialysis'),'home_or_mobile_scope')
        self.assertEqual(classify({},'mri','2','mri'),'numeric_tag_review')

    def test_missing_tags_stay_unknown(self):
        self.assertEqual(observations(record()),[])

    def test_facility_fields_keep_yes_no_and_cached_national_counts(self):
        records=[record(tags={'facility:mri':'yes','source':'Invented field visit 2000'}),
                 record('node/2',{'facility:mri':'no','facility:trauma':'yes'})]
        self.assertEqual(observations(records[0])[0]['category'],'explicit_service_tag')
        self.assertEqual({o['category'] for o in observations(records[1])},{'negative_or_unavailable','explicit_service_tag'})
        edition={'national_required_key_counts':{}}
        reconcile_facility_key_counts(records,edition)
        self.assertEqual(edition['national_required_key_counts'],{'facility:mri':2,'facility:trauma':1})
        edition['national_required_key_counts']['facility:mri']=3
        with self.assertRaises(ValueError):reconcile_facility_key_counts(records,edition)

    def test_distributor_does_not_increase_independence(self):
        self.assertEqual({family(x) for x in ['hot','geofabrik','osm','overture_osm']},{'osm'})

    def test_typed_ids_disambiguate_node_and_way(self):
        self.assertNotEqual(typed_id('node/1'),typed_id('way/1'))
        with self.assertRaises(ValueError):typed_id('1')

    def test_state_unknown_and_repeats_are_preserved(self):
        r=record(tags={'healthcare':'dialysis'});r['locators'].append('synthetic#/features/1')
        ledger,report=screen([r],{'sha256':'edition'},2,{'healthcare'},{'healthcare':'healthcare'})
        self.assertEqual(len(ledger),1)
        self.assertEqual(report['services']['dialysis']['raw_mentions_including_repeats'],2)
        self.assertEqual(report['services']['dialysis']['by_source_state']['UNKNOWN']['explicit_objects'],1)
        self.assertEqual(ledger[0]['patient_status'],'unconfirmed')

    def test_present_zero_separate_from_omitted_key(self):
        _,report=screen([record(tags={'healthcare':'hospital','capacity:persons':None})],{'sha256':'x'},1,{'healthcare','capacity_persons'},{'healthcare':'healthcare','capacity_persons':'capacity:persons'})
        self.assertEqual(report['required_key_audit']['capacity:persons']['status'],'present_all_null_or_empty')
        self.assertEqual(report['required_key_audit']['mri']['status'],'not_preserved_by_export')
        self.assertEqual(report['services']['mri']['explicit_qualifying_objects'],0)

    def test_hot_repeats_conflicts_and_digest_gate(self):
        f={'type':'Feature','properties':{'id':'node/1','name':'Invented clinic','healthcare':'dialysis','name_hi':'Invented publisher-derived label'},'geometry':None}
        other=copy.deepcopy(f);other['properties']['name']='Different invented branch'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('config.yaml',"- tags['name'] AS name\n- tags['healthcare'] AS healthcare\n")
                z.writestr('metadata.json',json.dumps({'properties':{'license':'ODbL-1.0','oex:snapshot':'2000-01-01'}}))
                z.writestr('health_facilities.geojson',json.dumps({'features':[f,f,other]}))
            h=sha256(path.read_bytes()).hexdigest()
            records,edition,count,columns,mapping=load(path,h)
            _,report=screen(records,edition,count,columns,mapping)
            self.assertEqual(count,3);self.assertEqual(len(records),2)
            self.assertEqual(report['conflicting_object_ids'],1)
            self.assertEqual(sum(len(r['locators']) for r in records),3)
            self.assertNotIn('name:hi',records[0]['tags'])
            self.assertIn('name_hi',records[0]['raw_properties'])
            with self.assertRaises(ValueError):load(path,'wrong digest')


if __name__=='__main__':unittest.main()
