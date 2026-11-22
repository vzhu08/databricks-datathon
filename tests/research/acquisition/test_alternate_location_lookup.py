"""Synthetic publisher-first eligibility checks."""
import gzip
import io
import json
import unittest
import zipfile

from research.acquisition.alternate_location_lookup.eligibility import evaluate
from research.acquisition.alternate_location_lookup.sample import sha


class EligibilityTests(unittest.TestCase):
    def test_freeze_does_not_copy_vf_locality_or_promote_competing_rows(self):
        rows = [{"facility_id": str(i), "source_row": {
            "name": {0: "Public Hospital", 1: "Ambiguous Hospital"}.get(i, "Other"),
            "address_zipOrPostcode": "123456", "address_city": "Private locality",
        }} for i in range(24)]
        base = json.dumps(rows).encode()
        frozen = json.dumps({"summary": {"base_sha256": sha(base)}, "sample_private": [
            {"occurrence": str(i), "stratum": "missed" if i < 12 else "competing"}
            for i in range(24)]}).encode()
        record = {"Hospital_Name": "Public Hospital", "Pincode": "123456",
                  "official_locator": "csv:data-record=1;line-end=2", "Town": None,
                  "Subdistrict": None, "District": "Issuer district", "sr_no": "1",
                  "Address_Original_First_Line": "Institution premises", "State": "Synthetic"}
        records = [record, dict(record, Hospital_Name="Ambiguous Hospital", sr_no="2"),
                   dict(record, Hospital_Name="Ambiguous Hospital", sr_no="3")]
        member = gzip.compress("\n".join(map(json.dumps, records)).encode())
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("facility-locators.jsonl.gz", member)
        data = buf.getvalue()
        manifest = json.dumps({"archive": {"sha256": sha(data)}, "members": [{
            "filename": "facility-locators.jsonl.gz", "count": 3, "sha256": sha(member)
        }]}).encode()
        result = evaluate(base, frozen, data, manifest)
        self.assertEqual(result["publisher_freeze"][0]["query"], "Public Hospital Issuer district")
        self.assertNotIn("Private locality", json.dumps(result))
        self.assertEqual(result["private_results"][0]["status"], "needs_branch_review")
        self.assertEqual(result["private_results"][1]["status"], "ambiguous_issuer_records")
        with self.assertRaisesRegex(ValueError, "archive differs"):
            evaluate(base, frozen, data + b"altered", manifest)


if __name__ == "__main__":
    unittest.main()
