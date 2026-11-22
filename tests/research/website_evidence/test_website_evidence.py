"""Synthetic checks for website service mentions and the Common Crawl index reader."""
import gzip
import json
import unittest

from research.website_evidence import cc_index, domains, extract

PAGE = """<html><head><title>Example Care Hospital</title><script>var mri = 1;</script></head>
<body><nav><a href="/">Home</a><a href="/mri">MRI</a></nav>
<p>We run a 10-bed haemodialysis unit open 24 hours for patients with kidney failure.</p>
<p>Our 1.5T MRI scanner is coming soon to the new imaging block.</p>
<div>Emergency and Trauma Care</div>
<p>The Primrose ward is for day care.</p>
""" + "<p>Filler text about the hospital and its history and values.</p>" * 6 + "</body></html>"


class ExtractTests(unittest.TestCase):
    def test_finds_each_service_with_a_quote(self):
        found = extract.mentions(PAGE)
        self.assertEqual(found["title"], "Example Care Hospital")
        self.assertEqual(set(found["services"]), {"dialysis", "mri", "trauma_care"})
        self.assertIn("haemodialysis unit", found["services"]["dialysis"]["quote"])
        self.assertFalse(found["services"]["dialysis"]["qualified"])

    def test_prefers_a_sentence_over_a_menu_item_and_flags_qualifiers(self):
        mri = extract.mentions(PAGE)["services"]["mri"]
        self.assertIn("scanner", mri["quote"])
        self.assertTrue(mri["qualified"])  # "coming soon"
        self.assertEqual(mri["count"], 2)

    def test_scripts_do_not_count_and_thin_pages_give_nothing(self):
        self.assertEqual(extract.mentions("<script>dialysis MRI</script><p>Please wait</p>")["services"], {})
        self.assertTrue(extract.mentions("<p>Please wait while your request is being verified...</p>")["thin"])

    def test_lowercase_mri_inside_words_is_not_a_match(self):
        self.assertIsNone(extract.SERVICES["mri"].search("Primrose ward"))
        self.assertIsNone(extract.SERVICES["mri"].search("MRIdul Sharma"))


class StrengthTests(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(extract.strength("We provide 24/7 dialysis service with six haemodialysis machines."), "direct")
        self.assertEqual(extract.strength("Dialysis Unit"), "listed")
        self.assertEqual(extract.strength("Your doctor may order an MRI scan if X-rays do not show the cause."), "weak")
        self.assertEqual(extract.strength("Our dialysis unit is one of the best in the city and it is open.",
                                          "https://x.in/blog/kidney-tips"), "weak")
        self.assertEqual(extract.strength("We are planning to start a dialysis unit for the district next year.",
                                          qualified=True), "weak")

    def test_menus_are_weak(self):
        menu = ("Department Select a Department Cardiology Nephrology Dialysis Unit Neurology Orthopaedics "
                "Paediatrics Urology Oncology Radiology")
        self.assertTrue(extract.looks_like_menu(menu))
        self.assertEqual(extract.strength(menu), "weak")
        self.assertFalse(extract.looks_like_menu(
            "A specialised Dialysis Unit, Air Conditioned Dialysis Unit, Team of qualified doctors, Technicians, "
            "Nurses and Assistants, ICU Back-UP"))


def _line(key, ts, **j):
    return f"{key} {ts} {json.dumps(j)}"


class IndexTests(unittest.TestCase):
    def setUp(self):
        block0 = "\n".join([
            _line("in,co,examplecare)/", "20260917010101", url="https://examplecare.co.in/", status="200",
                  mime="text/html", filename="w0", offset="0", length="10"),
            _line("in,co,examplecare)/dialysis", "20260917010202", url="https://examplecare.co.in/dialysis",
                  status="200", mime="text/html", filename="w0", offset="10", length="10"),
            _line("in,co,examplecare,m)/x.css", "20260917010303", url="https://m.examplecare.co.in/x.css",
                  status="200", mime="text/css", filename="w0", offset="20", length="10"),
            _line("in,co,examplecare-other)/", "20260917010404", url="https://examplecare-other.co.in/",
                  status="200", mime="text/html", filename="w0", offset="30", length="10"),
        ])
        self.blob = gzip.compress(block0.encode())
        cluster = "in,co,a)/ 2026\tcdx-00000.gz\t0\t%d\t1\nzz,z)/ 2026\tcdx-00000.gz\t%d\t1\t2\n" % (
            len(self.blob), len(self.blob))
        self.crawl = cc_index.Crawl("CC-TEST", fetch=lambda url, start=None, length=None: self.blob)
        self.crawl.load_cluster(cluster)

    def test_captures_cover_domain_and_subdomains_only(self):
        rows = self.crawl.captures("www.examplecare.co.in")
        self.assertEqual([r["url"] for r in rows], [
            "https://examplecare.co.in/", "https://examplecare.co.in/dialysis", "https://m.examplecare.co.in/x.css"])
        self.assertEqual(rows[1]["timestamp"], "20260917010202")

    def test_pick_pages_home_first_then_service_paths(self):
        picked = cc_index.pick_pages(self.crawl.captures("examplecare.co.in"))
        self.assertEqual([p["url"] for p in picked], ["https://examplecare.co.in/", "https://examplecare.co.in/dialysis"])

    def test_page_strips_warc_and_http_headers(self):
        record = b"WARC/1.0\r\nWARC-Type: response\r\n\r\nHTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<p>hi</p>"
        crawl = cc_index.Crawl("CC-TEST", fetch=lambda *a, **k: gzip.compress(record))
        self.assertEqual(crawl.page({"filename": "w", "offset": 0, "length": 1}), "<p>hi</p>")


class DomainTests(unittest.TestCase):
    def test_keeps_own_domain_and_drops_listings(self):
        rows = [
            {"facility_id": "1", "source_row": {"name": "Sunrise Kidney Hospital", "officialWebsite": "www.sunrisekidney.in",
                                                 "websites": '["https://www.justdial.com/x", "sunrisekidney.in", "randomblog.com"]'}},
            {"facility_id": "2", "source_row": {"name": "Asha Clinic", "officialWebsite": "ashaclinic-vizag.com", "websites": None}},
        ]
        out = domains.first_party(rows)
        self.assertEqual(out[0]["domains"], ["sunrisekidney.in"])
        self.assertEqual(out[1]["domains"], ["ashaclinic-vizag.com"])

    def test_surt(self):
        self.assertEqual(cc_index.surt_host("www.Example.co.in"), "in,co,example")


class BuildTests(unittest.TestCase):
    def test_rows_get_one_dated_record_per_service_and_never_a_yes(self):
        from research.website_evidence import build
        rows = [{"facility_id": "r1", "domains": ["a.in"]}, {"facility_id": "r2", "domains": ["a.in"]},
                {"facility_id": "r3", "domains": ["b.in"]}, {"facility_id": "r4", "domains": ["c.in"]}]
        hits = {("a.in", "dialysis"): {"timestamp": "20260917010203", "url": "https://a.in/", "quote": "Dialysis Unit",
                                        "pages_with_mention": 1, "strength": "listed", "qualified": False, "review": "B"}}
        evidence, report = build.build(rows, ["a.in", "b.in", "c.in"], "310", hits, "CC-TEST")
        self.assertEqual([e["facility_id"] for e in evidence], ["r1", "r2"])
        self.assertEqual(evidence[0]["source"]["captured_at"], "2026-09-17T01:02:03Z")
        self.assertEqual(evidence[0]["campus_attribution"], "needs_review")  # domain shared by two rows
        self.assertEqual({e["status_effect"] for e in evidence}, {"none_until_reviewed"})
        self.assertEqual(report["rows_read"], 3)
        self.assertEqual(report["rows_by_archive_state"], {"readable": 2, "no_capture": 1, "not_read": 1})


if __name__ == "__main__":
    unittest.main()
