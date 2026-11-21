import copy
from pathlib import Path
import unittest

from research.trauma.national.__main__ import (
    add_snapshot, compare_documents, document_dates, interpretations, reviewed_rows, validate_batch,
)
from research.trauma.national.parser import Document, GridRow, Section, parse_rows


def synthetic_row(page, *cells):
    return GridRow(page, cells)


class NationalProgrammeTests(unittest.TestCase):
    def setUp(self):
        self.section = Section(2, "completed", "Construction completed", 1, 3)
        self.rows = parse_rows(self.section, [
            synthetic_row(1, "S. No", "Hospital", "Level", "Status"),
            synthetic_row(1, "Rajasthan", None, None, ""),
            synthetic_row(1, "1.", "Synthetic Community\nHospital", "II", "Functional"),
            synthetic_row(2, "S. No", "Hospital", "Level", "Status"),
            synthetic_row(2, "2.", "Synthetic Campus II", None, "", None, "Functional"),
            synthetic_row(2, "Other State"),
            synthetic_row(2, "3.", "Synthetic District Hospital", "III", "Functional"),
        ])

    def test_state_header_carries_and_replaced_on_continuation(self):
        self.assertEqual([(r.state, r.state_page) for r in self.rows],
                         [("Rajasthan", 1), ("Rajasthan", 1), ("Other State", 2)])
        self.assertIn("PDF p. 2, serial 2", self.rows[1].locator)

    def test_wrapped_name_and_blank_level_preserved(self):
        self.assertEqual(self.rows[0].excerpt, "1.\nSynthetic Community\nHospital\nII\nFunctional")
        self.assertEqual(self.rows[0].level, "II")
        self.assertIsNone(self.rows[1].level)
        self.assertEqual(self.rows[1].name, "Synthetic Campus II")
        self.assertEqual([kind for kind, _ in interpretations(self.rows[1])], ["reported_functionality"])

    def test_merged_state_column_carries_and_support_is_inconclusive(self):
        section = Section(3, "supported", "Facilities supported", 3, 3)
        rows = parse_rows(section, [
            synthetic_row(3, "1.", "Rajasthan", "Synthetic Campus", "L- III."),
            synthetic_row(4, "2.", None, "Synthetic Hospital", ""),
            synthetic_row(4, "3.", "Other State", "Synthetic Ward", "L-II"),
        ])
        self.assertEqual([row.state for row in rows], ["Rajasthan", "Rajasthan", "Other State"])
        self.assertIsNone(rows[0].printed_status)
        self.assertEqual([kind for kind, _ in interpretations(rows[0])],
                         ["programme_level", "programme_stage"])
        self.assertIn("programme support", dict(interpretations(rows[0]))["programme_stage"])

    def test_new_table_cannot_inherit_previous_state(self):
        section = Section(2, "under_construction", "Under construction", 3, 1)
        with self.assertRaisesRegex(ValueError, "Missing state"):
            parse_rows(section, [synthetic_row(3, "1.", "Synthetic Campus", "II")])

    def test_detects_dropped_last_row_and_serial_gap(self):
        with self.assertRaisesRegex(ValueError, "discontinuous serial"):
            parse_rows(self.section, [
                synthetic_row(1, "Rajasthan"),
                synthetic_row(2, "2.", "Synthetic Campus", "II", "Functional"),
            ])
        with self.assertRaisesRegex(ValueError, "found 1 rows, expected 3"):
            parse_rows(self.section, [
                synthetic_row(1, "Rajasthan"),
                synthetic_row(2, "1.", "Synthetic Campus", "II", "Functional"),
            ])

    def test_conflicting_dates_stay_unresolved_and_separate(self):
        def observed(kind, date, page):
            return {"kind": kind, "date": date, "locator": f"PDF p. {page}", "excerpt": f"{kind} {date}"}

        publication = observed("publication", "2020-07-01", 1)
        earlier = observed("status_as_of", "2020-01-01", 2)
        later = observed("status_as_of", "2020-02-01", 3)
        mixed = document_dates([publication, earlier, later])
        self.assertEqual(mixed["published_date"], "2020-07-01")
        self.assertIsNone(mixed["status_as_of"])
        self.assertIsNone(mixed["valid_until"])
        self.assertEqual(mixed["conflicts"], ["status_as_of"])
        self.assertIsNone(document_dates([])["published_date"])
        impossible = document_dates([publication, observed("status_as_of", "2021-01-01", 2)])
        self.assertEqual(impossible["conflicts"], ["status_after_publication"])
        self.assertIsNone(impossible["status_as_of"])

    def test_negated_functionality_preserves_what_the_source_says(self):
        row = parse_rows(Section(2, "completed", "Completed", 1, 1), [
            synthetic_row(1, "Rajasthan"),
            synthetic_row(1, "1.", "Synthetic Campus", "", "Not Functional"),
        ])[0]
        self.assertEqual([kind for kind, _ in interpretations(row)], ["reported_functionality"])
        self.assertIn("as Not Functional.", dict(interpretations(row))["reported_functionality"])

    def test_visual_review_rejects_wrong_column_or_missing_pages(self):
        document = Document({"completed": self.section}, self.rows, ["First", "Second"], {})
        review = {
            "rows": [{"key": r.key, "page": r.page, "name": r.name, "printed_level": r.printed_level,
                      "printed_status": r.printed_status} for r in self.rows[:2]],
            "rajasthan_counts": {"completed": 2, "under_construction": 0,
                                 "construction_not_started": 0, "supported": 0},
            "annexure_1_facility_rows": 0, "pages_reviewed": [1, 2], "issues": [],
        }
        self.assertEqual(reviewed_rows(document, review), self.rows[:2])
        missing = {**review, "pages_reviewed": [1]}
        with self.assertRaisesRegex(ValueError, "visual review"):
            reviewed_rows(document, missing)
        review["rows"][0]["printed_level"] = "I"
        with self.assertRaisesRegex(ValueError, "visual review"):
            reviewed_rows(document, review)

    def test_lineage_keeps_substantive_variants(self):
        document = Document({}, self.rows, ["One"], {})
        primary = {"document": document, "sha256": "a", "dates": document_dates([])}
        self.assertTrue(compare_documents(primary, primary)["same_edition"])
        self.assertTrue(compare_documents(primary, {**primary, "sha256": "b"})["same_edition"])
        variant = Document({}, self.rows[1:], ["Two"], {})
        compared = compare_documents(primary, {**primary, "sha256": "b", "document": variant})
        self.assertFalse(compared["same_edition"])
        self.assertEqual(compared["changed_rajasthan_row_locators"], ["completed:1"])

    def test_contract_envelope_stable_historical_and_unlinked(self):
        acquired = {
            "sha256": "a" * 64, "dates": document_dates([]), "rows": self.rows[:2],
            "resolved_url": "https://example.invalid/programme.pdf", "path": Path(__file__).resolve(),
            "retrieved_at": "2026-01-10T12:00:00Z",
            "review": {"issues": [], "reviewer": "synthetic-reviewer", "reviewed_at": "2026-01-11T12:00:00Z"},
        }
        registry = {"publisher_hint": "Synthetic publisher", "source_family_hint": "synthetic-family"}
        lineage = {"changed_rajasthan_row_locators": [], "date_metadata_differs": False}

        def envelope():
            batch = {"contract_version": "1.0.0", "source_snapshots": [], "external_facilities": [],
                     "facility_matches": [], "facility_evidence": [], "review_queue": []}
            add_snapshot(batch, [], acquired, registry, lineage)
            return batch

        batch = envelope()
        validate_batch(batch)
        self.assertEqual(batch, envelope())
        for claim in batch["facility_evidence"]:
            self.assertEqual(claim["temporal_status"], "historical")
            self.assertEqual(claim["polarity"], "inconclusive")
            self.assertIsNone(claim["effective_date"])
            self.assertIsNone(claim["facility_id"])
            self.assertIsNone(claim["match_id"])
        malformed = copy.deepcopy(batch)
        malformed["facility_evidence"][0]["external_facility_id"] = "synthetic:absent"
        with self.assertRaisesRegex(ValueError, "Unknown evidence facility"):
            validate_batch(malformed)
