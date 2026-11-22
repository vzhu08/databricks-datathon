"""PBF handler exercised using an invented OSM XML file, without network."""
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
try:
    import osmium
except ImportError:
    osmium=None
from research.acquisition.osm_services.pbf import load, compare_editions
from research.acquisition.osm_services.core import observations, screen


@unittest.skipUnless(osmium,'optional pinned osmium dependency required')
class PbfTests(unittest.TestCase):
    def test_full_scan_negative_counts_and_topology(self):
        raw=b'''<osm version="0.6">
        <node id="1" lat="1" lon="2" version="1" timestamp="2000-01-01T00:00:00Z"><tag k="healthcare" v="dialysis"/></node>
        <node id="2" lat="2" lon="3" version="1" timestamp="2000-01-01T00:00:00Z"/>
        <way id="1" version="1" timestamp="2000-01-01T00:00:00Z"><nd ref="1"/><nd ref="2"/><tag k="mri:count" v="0"/></way>
        <relation id="1" version="1" timestamp="2000-01-01T00:00:00Z"><member type="way" ref="1" role="outer"/><tag k="proposed:healthcare" v="dialysis"/></relation>
        </osm>'''
        prior=[{'osm_id':'node/2','tags':{'healthcare':'hospital'},'state':None},
               {'osm_id':'node/3','tags':{},'state':None}]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.osm';path.write_bytes(raw)
            args=(path,sha256(raw).hexdigest(),'https://example.invalid/synthetic.osm','2000-01-01','2000-01-02',prior,Path(directory)/'cache')
            records,edition,count,columns,mapping=load(*args)
            self.assertEqual(load(*args),(records,edition,count,columns,mapping))
            ledger,report=screen(records,edition,count,columns,mapping)
            self.assertEqual(edition['scan_counts']['node'],2)
            self.assertEqual(len(records),4)
            self.assertEqual(report['services']['dialysis']['explicit_qualifying_objects'],1)
            self.assertEqual(report['required_key_audit']['emergency']['status'],'absent_in_full_snapshot')
            self.assertEqual({r['category'] for r in ledger},{'explicit_service_tag','negative_or_unavailable','future'})
            self.assertEqual(next(r for r in records if r['osm_id']=='way/1')['topology'],{'nodes':[1,2]})
            drift=compare_editions(prior,records)
            self.assertEqual(drift['hot_ids_absent_from_pbf'],['node/3'])
            self.assertEqual(drift['changed_exported_tag_objects'],1)
            with self.assertRaises(ValueError):load(path,'bad','url','date','time')


if __name__=='__main__':unittest.main()
