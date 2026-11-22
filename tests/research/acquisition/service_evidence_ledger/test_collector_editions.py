import unittest

from research.acquisition.service_evidence_ledger.collector_editions import host_links
from research.acquisition.service_evidence_ledger.ledger import reconcile


class CollectorEditionTests(unittest.TestCase):
    def test_candidate_host_requires_consistent_geography_and_preserves_twins(self):
        centre = {'source_record_key':'bank1', 'name':'Example Memorial Hospital Blood Bank',
                  'normalized_pin':'400001', 'normalized_state':'maharashtra', 'lat':None, 'lon':None}
        def facility(key, state, pin):
            return {'facility_id':key, 'source_row':{'name':'Example Memorial Hospital',
                    'address_stateOrRegion':state, 'address_zipOrPostcode':pin, 'latitude':None, 'longitude':None}}
        base = [facility(key,'Maharashtra','400001') for key in ['one','two']]
        base.append(facility('wrong-pin','Maharashtra','400002'))
        base.append(facility('wrong-state','Ladakh','400001'))
        links = host_links([centre],base)['bank1']
        self.assertEqual([row['occurrence_key'] for row in links],['one','two'])
        self.assertTrue(all(row['quality']=='candidate' and row['campus_id'] is None for row in links))

    def test_withheld_text_cannot_form_shared_wording_group(self):
        rows = [{'ledger_id':str(i), 'raw':{'raw_text':None, 'modality':'directory_field',
                 'target_links':[], 'multi_campus':False}} for i in range(2)]
        self.assertEqual(reconcile(rows), ([],[]))
