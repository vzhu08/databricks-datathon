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

    def test_dental_menu_and_byline_entries_do_not_count(self):
        page = ("<html><body><div>Dr. Meera Iyer</div><div>BDS, MDS (Orthodontics)</div>"
                "<div>Dr. Sunil Rao</div><div>Book an Appointment Department Cardiology Neurology Nephrology</div>"
                "<div>Dr. Anil Gupta July 16, 2026 orthopaedic 0 Comments</div>"
                "<div>Dr. Ravi Menon</div><div>Consultant Nephrologist</div>" + FILLER + "</body></html>")
        self.assertEqual(specialists.count_page(page)["specialties"], {"nephrology": 1})

    def test_first_specialty_named_wins_over_a_department_heading(self):
        page = ("<html><body><div>Dr. Asha Verma</div><div>Consultant Nephrologist</div>"
                "<div>Department of Orthopaedics &amp; Joint Replacement</div>"
                "<div>Dr. Kiran Das</div><div>Department: Neurology</div><div>Speciality: Neuro Surgeon</div>"
                "<div>Dr. Mohan Lal</div><div>B.P.Th., M.P.Th. (Ortho.)</div><div>Neuro Surgeon</div>"
                + FILLER + "</body></html>")
        self.assertEqual(specialists.count_page(page)["specialties"], {"nephrology": 1, "neurosurgery": 1})

    def test_long_paragraph_needs_the_specialty_next_to_the_name(self):
        para = ("Dr. Vikram Tiwari is the founder of the hospital and has served the town for thirty years with "
                "dedication to patients from all walks of life, and today the hospital has a busy neurosurgery "
                "department and an intensive care unit run by a large team.")
        page = "<html><body><p>" + para + "</p>" + FILLER + "</body></html>"
        self.assertEqual(specialists.count_page(page)["specialties"], {})

    def test_mask_covers_long_names_and_initials(self):
        self.assertEqual(specialists.mask("Dr. Rajesh Kumar Singh Bhalla, MS"), "Dr. ▇, MS")
        self.assertEqual(specialists.mask("Dr.S.S. Abilash (Ortho)"), "Dr. ▇ (Ortho)")

    def test_profile_urls_lose_the_name(self):
        r = specialists.redact_url
        self.assertEqual(r("https://x.in/team/dr-arun-p-s/"), "https://x.in/team/[name removed]/")
        self.assertEqual(r("https://x.in/doctor/sarojini-devi"), "https://x.in/doctor/[name removed]")
        self.assertEqual(r("https://x.in/doctor.php?slug=dr-a-b"), "https://x.in/doctor.php?slug=[removed]")
        self.assertEqual(r("https://x.in/doctor-vikas-k.html"), "https://x.in/[name removed]")
        self.assertEqual(r("https://x.in/doctors/page/2/"), "https://x.in/doctors/page/2/")
        self.assertEqual(r("https://x.in/departments/neuro-surgery"), "https://x.in/departments/neuro-surgery")

    def test_row_records_and_report(self):
        rows = [{"facility_id": "r1", "domains": ["a.in"]}, {"facility_id": "r2", "domains": ["b.in"]},
                {"facility_id": "r3", "domains": ["c.in"]}]
        run = {"a.in": {"doctor_pages_read": 2, "doctors": 5, "specialties": {
                   "nephrology": {"count": 2, "url": "https://a.in/team/dr-x-y", "captured": "20260910101010"}}},
               "b.in": {"doctor_pages_read": 0, "doctors": 0, "specialties": {}}}
        recs, rep = specialists.records(rows, run, "CC-TEST")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["supports_service"], "dialysis")
        self.assertEqual(recs[0]["source"]["url"], "https://a.in/team/[name removed]")
        self.assertEqual(recs[0]["source"]["captured_at"], "2026-09-10T10:10:10Z")
        self.assertEqual(recs[0]["status_effect"], "none_until_reviewed")
        self.assertEqual(rep["rows_by_state"], {"named_doctors_listed": 1, "at_least_one_target_specialist": 1,
                                                "no_doctor_page": 1, "no_html_capture": 1})


if __name__ == "__main__":
    unittest.main()
