from hashlib import sha256
import unittest
from research.acquisition.osm_services.pmndp import HEADERS, parse


class PmndpTests(unittest.TestCase):
    def test_totals_are_not_campus_evidence(self):
        raw=('<table><tr>'+''.join('<th>'+h+'</th>' for h in HEADERS)+
             '</tr><tr><td>Invented state</td><td>2</td><td>1</td><td>4</td><td>PPP</td></tr></table>').encode()
        row=parse(raw,sha256(raw).hexdigest())[0]
        self.assertEqual(row['reported_functional_centres'],4)
        self.assertIsNone(row['campus_id'])
        self.assertEqual(row['patient_status'],'unconfirmed')
        self.assertEqual(row['source_locator'],'table/tr[2] (1-based including header)')
        with self.assertRaises(ValueError):parse(raw,'bad')

    def test_changed_schema_rejected(self):
        raw=b'<table><tr><th>Clinic</th></tr><tr><td>Invented</td></tr></table>'
        with self.assertRaises(ValueError):parse(raw,sha256(raw).hexdigest())


if __name__=='__main__':unittest.main()
