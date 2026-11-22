"""Synthetic layout and clinical-inference regressions only."""
import unittest
from research.acquisition.esic_services.extract import observe, stitch


class AnnexureTests(unittest.TestCase):
    def test_continuation_retains_services_and_does_not_create_campus(self):
        pages = [(3, [["Sl.\nNo.", "Hospital", "Beds", "Occupancy", "Services"],
                      ["Example State", None, None, None, None],
                      ["1.", "Example\nNorth", "100", "0.00", "General medicine,"]]),
                 (4, [["", "", "", "", "MRI, Dialysis on PPP Model"],
                      ["Second State", None, None, None, None],
                      ["2.", "Example South", "200", "10.00", "Radiology"]])]
        rows = stitch(pages, 2)
        self.assertEqual(rows[0]["services_original"], "General medicine,\nMRI, Dialysis on PPP Model")
        self.assertEqual(rows[0]["name_original"], "Example\nNorth")
        self.assertEqual([x["pdf_page"] for x in rows[0]["fragments"]], [3, 4])
        self.assertEqual(rows[1]["state_original"], "Second State")

    def test_rejects_missing_duplicate_or_reordered_serials(self):
        for serial in ("0.", "2."):
            with self.assertRaises(ValueError):
                stitch([(3, [["State", None, None, None, None],
                             [serial, "Example", "100", "10", "MRI"]])], 1)
        with self.assertRaises(ValueError):
            stitch([(3, [["", "", "", "", "MRI"]])], 1)

    def test_count_and_layout_drift_fail(self):
        with self.assertRaises(ValueError):
            stitch([(3, [["Unknown", "layout"]])], 1)
        with self.assertRaises(ValueError):
            stitch([], 1)

    def obs(self, text):
        return observe({"record_id": "synthetic:row-1", "services_original": text,
                        "source_family": "synthetic", "publication_date": "2020-01-01",
                        "locator": {"pdf_pages": [1], "serial": 1}})

    def test_adjacent_specialty_never_infers_target_service(self):
        rows = self.obs("Radiology, Nephrology, Orthopaedics, ICU, General Surgery")
        self.assertTrue({"radiology_unspecified", "nephrology", "icu"} <= {r["service"] for r in rows})
        self.assertFalse({"mri", "dialysis", "trauma_mention"} & {r["service"] for r in rows})
        self.assertTrue(all(r["current_service_decision"] == "unconfirmed" for r in rows))

    def test_qualifiers_do_not_bleed_across_comma_and_counts_not_inferred(self):
        rows = self.obs("CT Scan (PPP), MRI, 45 dialysis beds")
        self.assertEqual(next(r for r in rows if r["service"] == "ct")["operator"], "PPP_partner_unspecified")
        self.assertEqual(next(r for r in rows if r["service"] == "mri")["operator"], "not_separately_specified")
        self.assertTrue(all(r["quantity"] is None for r in rows))

    def test_repeats_offsets_and_historical_date_retained(self):
        text = "MRI, MRI, planned Dialysis, referral MRI, no CT Scan"
        rows = self.obs(text)
        self.assertEqual(sum(r["service"] == "mri" for r in rows), 3)
        self.assertEqual(len({r["observation_id"] for r in rows}), len(rows))
        for row in rows:
            self.assertEqual(text[row["start"]:row["end"]], row["mention_original"])
            self.assertEqual(text[row["context_start"]:row["context_end"]], row["context_original"])
            self.assertIsNone(row["service_observation_date"])
        self.assertEqual(next(r for r in rows if r["service"] == "dialysis")["availability"], "planned")
        self.assertEqual(next(r for r in rows if r["service"] == "ct")["availability"], "negation_review")

    def test_spelling_variants_do_not_hide_mentions(self):
        rows = self.obs("Orthopaedics, Orthopedics, Haemodialysis, Hemodialysis")
        self.assertEqual(sum(r["service"] == "orthopaedics" for r in rows), 2)
        self.assertEqual(sum(r["service"] == "dialysis" for r in rows), 2)

    def test_onsite_status_follows_reported_availability(self):
        for negative in ("MRI unavailable", "MRI not available"):
            with self.subTest(negative=negative):
                rows = self.obs(f"{negative}, ICU, Dialysis referred out, proposed CT Scan")
                statuses = {r["service"]: (r["availability"], r["onsite"]) for r in rows}
                self.assertEqual(statuses, {
                    "mri": ("negation_review", "not_established"),
                    "icu": ("reported_available", "source_table_reports_in_hospital"),
                    "dialysis": ("referral_review", "not_established"),
                    "ct": ("planned", "not_established"),
                })
                self.assertEqual(rows[0]["context_original"], negative)
                self.assertTrue(all(r["current_service_decision"] == "unconfirmed" for r in rows))

    def test_exclusion_covers_coordinated_services_in_the_same_item(self):
        text = "ICU except MRI and CT Scan; Dialysis"
        rows = self.obs(text)
        self.assertEqual([(r["service"], r["onsite"]) for r in rows], [
            ("icu", "source_table_reports_in_hospital"),
            ("mri", "not_established"),
            ("ct", "not_established"),
            ("dialysis", "source_table_reports_in_hospital"),
        ])
        for row in rows[1:3]:
            self.assertEqual(row["availability"], "negation_review")
            self.assertEqual(row["context_original"], "ICU except MRI and CT Scan")


if __name__ == "__main__":
    unittest.main()
