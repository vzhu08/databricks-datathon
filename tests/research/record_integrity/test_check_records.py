import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.record_integrity.check_records import FAMILIES, WEIGHTS, run, write

GOOD_TEXT = ("Sunrise Hospital is a multispeciality hospital offering general medicine, surgery, "
             "obstetrics and paediatrics with an outpatient department and pharmacy on site.")


def row(fid, name, lat, lon, **extra):
    src = {"source": "kie", "address_country": "India", "organization_type": "facility",
           "facilityTypeId": "hospital", "operatorTypeId": "private", "name": name,
           "address_city": "Jaipur", "address_stateOrRegion": "Rajasthan", "address_zipOrPostcode": "302001",
           "latitude": lat, "longitude": lon,
           "coordinates": json.dumps({"type": "Point", "coordinates": [lon, lat]}),
           "phone_numbers": json.dumps(["+919812345670"]), "description": None}
    src.update(extra)
    return {"facility_id": fid, "source_row": src}


class RecordIntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        postal = [{"pincode": 302001, "statename": "RAJASTHAN", "latitude": str(26.91 + i / 1000), "longitude": "75.79"}
                  for i in range(5)]
        postal += [{"pincode": 400001, "statename": "MAHARASHTRA", "latitude": str(18.93 + i / 1000), "longitude": "72.83"}
                   for i in range(5)]
        (self.root / "postal.json").write_text(json.dumps(postal))
        corr = self.root / "corr.csv"
        with open(corr, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["vf_id", "n_agreeing"])
            w.writerow(["corroborated", "2"])
        self.corr = corr

    def check(self, base):
        (self.root / "base.json").write_text(json.dumps(base))
        rows = run(self.root / "base.json", self.root / "postal.json", None, [self.corr])
        return {r["facility_id"]: r for r in rows}

    def test_every_reason_has_a_family(self):
        self.assertEqual(set().union(*FAMILIES.values()), set(WEIGHTS))

    def test_clean_row_is_not_flagged(self):
        out = self.check([row("clean", "Sunrise Hospital", 26.912345, 75.791234, description=GOOD_TEXT)])
        self.assertEqual(out["clean"]["reasons"], {})
        self.assertEqual(out["clean"]["tier"], "none")

    def test_planted_style_rows_are_high(self):
        out = self.check([
            row("abroad", "Sunrise Hospital", 2.95, 41.38),
            row("masked", "Bhagat Hospital", 26.912345, 75.791234,
                description="Bhagat Hospital is situated at XXXXXXX XXXXXXXX 000000."),
            row("shifted", "Moon Clinic", 26.912345, 75.791234, address_country="76.98", source="0f3a"),
            row("mumbai_pin", "Star Hospital", 18.931234, 72.831234),
        ])
        self.assertIn("coords_outside_india", out["abroad"]["reasons"])
        self.assertIn("placeholder_text", out["masked"]["reasons"])
        self.assertIn("malformed_row", out["shifted"]["reasons"])
        self.assertIn("far_from_pin_100km", out["mumbai_pin"]["reasons"])
        self.assertIn("point_in_other_state", out["mumbai_pin"]["reasons"])
        for fid in ("abroad", "masked", "shifted", "mumbai_pin"):
            self.assertEqual(out[fid]["tier"], "high", fid)

    def test_shared_values_only_count_between_unrelated_names(self):
        tmpl = GOOD_TEXT.replace("Sunrise Hospital", "{}")
        out = self.check([
            row("a", "Apollo Clinic Malviya Nagar", 26.912345, 75.791234, description=tmpl.format("Apollo Clinic")),
            row("b", "Apollo Clinic Vaishali", 26.912345, 75.791234, description=tmpl.format("Apollo Clinic")),
            row("c", "Ganesh Dental Care", 26.912345, 75.791234, description=tmpl.format("Ganesh Dental Care")),
        ])
        self.assertIn("coords_shared_unrelated", out["c"]["reasons"])
        self.assertIn("description_duplicate_unrelated", out["c"]["reasons"])
        self.assertIn("coords_shared_unrelated", out["a"]["reasons"])  # shares a point with "c"

    def test_corroboration_lowers_soft_flags_but_not_hard_ones(self):
        out = self.check([
            row("corroborated", "Star Hospital", 18.931234, 72.831234),
            row("other", "Star Hospital", 18.931234, 72.831234),
        ])
        self.assertEqual(out["corroborated"]["score"], out["other"]["score"])
        self.assertLess(out["corroborated"]["adjusted"], out["other"]["adjusted"])
        out = self.check([row("corroborated", "Sunrise Hospital", 2.95, 41.38)])
        self.assertEqual(out["corroborated"]["tier"], "high")

    def test_phone_and_plausibility_checks(self):
        out = self.check([
            row("p", "Sunrise Hospital", 26.912345, 75.791234, phone_numbers=json.dumps(["+919999999999"]),
                capacity="200000", yearEstablished="7"),
            row("landline", "Lotus Hospital", 26.913345, 75.792234, phone_numbers=json.dumps(["+911412345678"])),
        ])
        self.assertIn("phone_placeholder", out["p"]["reasons"])
        self.assertIn("capacity_implausible", out["p"]["reasons"])
        self.assertIn("year_implausible", out["p"]["reasons"])
        self.assertNotIn("phone_invalid", out["landline"]["reasons"])

    def test_output_has_no_contact_columns_and_keeps_every_row(self):
        base = [row(str(i), f"Hospital {i}", 26.912345, 75.791234) for i in range(3)]
        base.append({"facility_id": "empty", "source_row": {}})
        (self.root / "base.json").write_text(json.dumps(base))
        summary = write(run(self.root / "base.json", None, None, []), self.root / "out")
        with open(self.root / "out" / "integrity_flags.csv", newline="") as fh:
            reader = csv.DictReader(fh)
            out = list(reader)
        self.assertEqual(len(out), 4)
        self.assertEqual(summary["rows"], 4)
        self.assertFalse({"phone", "email", "phone_numbers", "officialPhone"} & set(reader.fieldnames))


if __name__ == "__main__":
    unittest.main()
