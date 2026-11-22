"""Synthetic checks for specialist counts: counts and dates only, never names."""
import json
import unittest

from research.website_evidence import specialists

FILLER = "<p>Our hospital has served the district for many years with care and dedication.</p>" * 5
DOCTORS = """<html><body>
<div><h3>Dr. Asha Verma</h3><p>MD, DM (Nephrology)</p><p>Senior Consultant Nephrologist</p></div>
<div><h3>Dr. Ravi K. Menon</h3><p>MBBS, MS (Ortho)</p><p>Orthopaedic Surgeon</p></div>
<div><h3>Dr. Neel Shah</h3><p>MD Radiology</p></div>
<div><h3>Dr. Asha Verma</h3><p>Nephrology OPD on Mondays</p></div>
<div><h3>Dr. Priya Rao</h3><p>Gynaecologist</p></div>
""" + FILLER + "</body></html>"
NEURO = "<html><body><div>Dr. Kiran Das</div><div>Neuro Surgeon</div><div>Dr. Asha Verma</div><div>Nephrologist</div>" + FILLER + "</body></html>"


class SpecialistTests(unittest.TestCase):
    def test_counts_each_doctor_once_per_specialty(self):
        page = specialists.count_page(DOCTORS)
        self.assertEqual(page["doctors"], 4)
        self.assertEqual(page["specialties"], {"nephrology": 1, "orthopaedics": 1, "radiology": 1})

    def test_hand_check_context_masks_names(self):
        page = specialists.count_page(DOCTORS)
        for text in page["context"].values():
            self.assertNotIn("Asha", text)
            self.assertNotIn("Menon", text)
            self.assertIn("Dr. ▇", text)

    def test_domain_aggregate_keeps_no_names(self):
        pages = [({"url": "https://x.in/our-doctors", "timestamp": "20260910101010"}, DOCTORS),
                 ({"url": "https://x.in/departments/neuro", "timestamp": "20260911101010"}, NEURO)]
        out = specialists.count_domain(pages)
        self.assertEqual(out["specialties"]["nephrology"]["count"], 1)  # same doctor on both pages
        self.assertEqual(out["specialties"]["neurosurgery"],
                         {"count": 1, "url": "https://x.in/departments/neuro", "captured": "20260911101010"})
        self.assertEqual(out["doctors"], 5)
        blob = json.dumps(out)
        for name in ("Asha", "Verma", "Ravi", "Menon", "Neel", "Kiran", "Priya"):
            self.assertNotIn(name, blob)

    def test_thin_page_counts_nothing(self):
        self.assertTrue(specialists.count_page("<p>Dr. A Nephrologist</p>")["thin"])

    def test_pick_doctor_pages(self):
        caps = [{"url": u, "status": "200", "mime": "text/html", "timestamp": "1"} for u in (
            "https://x.in/", "https://x.in/departments/nephrology", "https://x.in/our-doctors",
            "https://x.in/blog/our-doctors-tips", "https://x.in/contact")]
        self.assertEqual([c["url"] for c in specialists.pick_doctor_pages(caps)],
                         ["https://x.in/our-doctors", "https://x.in/departments/nephrology"])


if __name__ == "__main__":
    unittest.main()
