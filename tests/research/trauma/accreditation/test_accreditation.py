import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from research.trauma.accreditation.__main__ import build_release, sha256, validate
from research.trauma.accreditation.documents import document_pages, parse_certificate, scope_type


HEADER = """Scope of Accreditation
Certificate No. H-2020-0123
Fictional Banyan Hospital
West Branch, 12 Example Road, Example District 309999
Date of First Accreditation: January 1, 2020
Valid from: 1 January 2020
Valid thru: December 31, 2024
"""


class AccreditationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "scope.pdf"
        self.path.write_bytes(b"synthetic scope bytes")
        self.scope = "Emergency Medicine including Trauma Care"
        self.manifest = {
            "as_of": "2025-01-01", "selection": {"source_count": 1},
            "sources": {"scope": {
                "path": "scope.pdf", "kind": "certificate", "sha256": sha256(self.path),
                "source_key": "synthetic_scope", "publisher": "Fictional Accreditation Council",
                "source_family": "synthetic", "url": "https://example.test/scope.pdf",
                "retrieved_at": "2025-01-01T00:00:00Z", "published_date": None,
                "license": None, "attribution": "Synthetic", "independence_status": "unassessed",
            }},
            "cases": [{"case_id": "west", "district": "Example District", "gaps": [], "documents": [{
                "source": "scope", "campus_name": "Fictional Banyan Hospital",
                "campus_address": "West Branch, 12 Example Road, Example District 309999",
                "campus_status": "matched", "campus_basis": "West Branch and Example Road match the worksheet",
                "city": "Example Town", "campus_locator": "PDF p. 1 · hospital address",
                "reviewer": "Fixture reviewer", "reviewed_at": "2025-01-01T01:00:00Z",
                "quotes": [{"excerpt": self.scope, "locator": "Clinical services", "interpretation": "explicit_trauma",
                            "assertion": "The certificate lists the quoted service for its stated cycle."}],
            }]}],
        }

    def compile(self, text=None):
        return build_release(self.manifest, self.root, lambda path, kind: [text or HEADER + self.scope])

    def document(self):
        return self.manifest["cases"][0]["documents"][0]

    def test_expired_scope_preserves_dates_and_does_not_link_to_base(self):
        batch, ledger = self.compile()
        row = batch["facility_evidence"][0]
        self.assertIsNone(row["facility_id"])
        self.assertIsNone(row["match_id"])
        self.assertEqual((row["effective_date"], row["valid_until"], row["temporal_status"]),
                         ("2020-01-01", "2024-12-31", "expired"))
        self.assertEqual(ledger["cases"][0]["documents"][0]["certificate"]["certificate_number"], "H-2020-0123")
        self.assertEqual(batch["review_queue"][0]["reason_code"], "expired_scope")
        schema = json.loads(Path("contracts/enrichment/schema.json").read_text(encoding="utf-8"))
        validate(batch, schema)

    def test_expiry_date_is_inclusive(self):
        self.manifest["as_of"] = "2024-12-31"
        batch, _ = self.compile()
        self.assertEqual(batch["facility_evidence"][0]["temporal_status"], "dated")

    def test_same_name_different_branch_remains_unlinked_and_queued(self):
        self.document().update(campus_status="branch_mismatch", campus_basis="Candidate is the East Branch")
        batch, ledger = self.compile()
        self.assertFalse(batch["facility_evidence"])
        self.assertFalse(batch["external_facilities"])
        self.assertEqual(ledger["cases"][0]["review_reasons"], ["branch_mismatch"])

    def test_negative_and_qualified_scope_types(self):
        cases = {
            "This facility refers trauma patients to the main hospital.": "referral",
            "A trauma centre is planned for this campus.": "planned",
            "Trauma care is not available here.": "negated",
            "General Emergency Medicine": "general_emergency",
            "Trauma care training and simulation": "unresolved_interpretation",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(scope_type(text), expected)

    def test_referral_planned_negated_do_not_emit_support(self):
        self.manifest["sources"]["scope"]["kind"] = "institution"
        for passage, category, polarity in (
            ("This campus refers trauma patients to an affiliate.", "referral", "inconclusive"),
            ("A trauma unit is planned.", "planned", "inconclusive"),
            ("Trauma care is unavailable.", "negated", "contradicts"),
        ):
            self.document()["quotes"][0].update(excerpt=passage, interpretation=category,
                                                  human_review={"reviewer": "Fixture reviewer",
                                                                "reviewed_at": "2025-01-01T01:00:00Z"})
            batch, _ = self.compile(HEADER + passage)
            self.assertEqual(batch["facility_evidence"][0]["polarity"], polarity)

    def test_human_service_check_remains_pending_for_explicit_text(self):
        self.manifest["sources"]["scope"]["kind"] = "institution"
        batch, _ = self.compile()
        row = batch["facility_evidence"][0]
        self.assertEqual((row["polarity"], row["service"]), ("inconclusive", "trauma_care"))
        self.assertEqual(batch["review_queue"][0]["reason_code"], "human_service_review_pending")

    def test_unavailable_and_no_certificate_are_recorded_separately(self):
        self.manifest["cases"][0].update(documents=[], gaps=["source_unavailable", "certificate_not_located"])
        batch, _ = self.compile()
        self.assertEqual({row["reason_code"] for row in batch["review_queue"]},
                         {"source_unavailable", "certificate_not_located"})
        self.assertEqual(batch["facility_evidence"], [])

    def test_bad_excerpt_and_invalid_page_fail_closed(self):
        self.document()["quotes"][0]["excerpt"] = "fabricated trauma centre"
        with self.assertRaisesRegex(ValueError, "does not occur"):
            self.compile()
        self.document()["quotes"][0].update(excerpt=self.scope, page=2)
        with self.assertRaisesRegex(ValueError, "outside the source"):
            self.compile()

    def test_duplicate_or_tampered_input_is_rejected(self):
        first, _ = self.compile()
        second, _ = self.compile()
        self.assertEqual(first, second)
        self.path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.compile()
        self.manifest["cases"].append(deepcopy(self.manifest["cases"][0]))
        with self.assertRaisesRegex(ValueError, "unique campus"):
            self.compile()

    def test_header_and_dates_are_read_from_labelled_fields(self):
        self.assertIsNone(parse_certificate("Emergency Medicine"))
        self.assertEqual(parse_certificate(HEADER)["first_certification_date"], "2020-01-01")
        self.assertIsNone(parse_certificate("Scope of Accreditation\nCertificate No.: H-2020-0123")["valid_until"])
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            parse_certificate(HEADER + "Valid thru: April 5, 2026")

    def test_visual_transcript_requires_matching_document(self):
        transcript = self.root / "visual.json"
        review = {"pdf_sha256": sha256(self.path), "reviewer": "Fixture reviewer",
                  "pages": [{"page": 1, "text": HEADER + self.scope}]}
        transcript.write_text(json.dumps(review), encoding="utf-8")
        source = self.manifest["sources"]["scope"]
        source["visual_transcript"] = {"path": transcript.name, "sha256": sha256(transcript)}
        batch, _ = self.compile("image-only page")
        self.assertEqual(batch["facility_evidence"][0]["excerpt"], self.scope)
        review["pdf_sha256"] = "0" * 64
        transcript.write_text(json.dumps(review), encoding="utf-8")
        source["visual_transcript"]["sha256"] = sha256(transcript)
        with self.assertRaisesRegex(ValueError, "matching source hash"):
            self.compile("image-only page")

    def test_html_text_preserves_visible_wording(self):
        self.path.write_text('<h2>Emergency &amp; Trauma</h2><p>We treat trauma patients.</p>'
                             '<script>Wrong campus</script><div hidden>Hidden text</div>', encoding="utf-8")
        self.assertEqual(document_pages(self.path, "institution"),
                         ["Emergency & Trauma We treat trauma patients."])
