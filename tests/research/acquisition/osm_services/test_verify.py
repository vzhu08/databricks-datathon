from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from research.acquisition.osm_services.core import canonical
from research.acquisition.osm_services.verify import verify


class VerifyTests(unittest.TestCase):
    def test_remote_readback_detects_tamper_and_count_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            ledger=canonical({'patient_status':'unconfirmed','campus_id':None})
            (path/'ledger.jsonl').write_bytes(ledger)
            manifest={'files':{'ledger.jsonl':{'bytes':len(ledger),'sha256':sha256(ledger).hexdigest()}},'ledger_observations':1}
            raw=canonical(manifest);(path/'manifest.json').write_bytes(raw)
            self.assertEqual(verify(path,sha256(raw).hexdigest())['verified_rows'],1)
            manifest['ledger_observations']=2
            raw=canonical(manifest);(path/'manifest.json').write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'count'):verify(path,sha256(raw).hexdigest())
            (path/'ledger.jsonl').write_bytes(ledger+b' ')
            with self.assertRaisesRegex(ValueError,'digest/size'):verify(path,sha256(raw).hexdigest())

    def test_nested_manifest_must_be_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'child').mkdir()
            child=canonical({'files':{},'packets':[]})
            (path/'child'/'manifest.json').write_bytes(child)
            parent=canonical({'files':{},'packets':[{'directory':'child','manifest_sha256':sha256(child).hexdigest()}]})
            (path/'manifest.json').write_bytes(parent)
            self.assertEqual(verify(path,sha256(parent).hexdigest())['verified_rows'],0)
            (path/'child'/'manifest.json').write_bytes(child+b' ')
            with self.assertRaisesRegex(ValueError,'Manifest digest'):verify(path,sha256(parent).hexdigest())


if __name__=='__main__':unittest.main()
