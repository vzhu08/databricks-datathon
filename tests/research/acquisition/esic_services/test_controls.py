import unittest
from research.acquisition.esic_services.controls import historical_rows, release_paragraphs, quantity_observation


class ControlTests(unittest.TestCase):
    def test_historical_ppp_does_not_change_inhouse_following_bullets(self):
        table = [["Serial", "State", "Hospital", "Services"],
                 ["1.", "Example State", "Example Hospital", "\uf0d8 Dialysis on PPP mode\nIn-house services:\n\uf0d8 Neurology"]]
        row = historical_rows(table, 1)[0]
        self.assertEqual([m["operator"] for m in row["mentions"]], ["PPP_partner_unspecified", "in_house"])
        self.assertTrue(all(m["current_service_decision"] == "unconfirmed" for m in row["mentions"]))

    def test_print_duplicate_is_excluded(self):
        doc = b'<div id="pibReleaseBody"><p>Example ICU</p></div><div id="PdfDiv"><p>Example ICU</p></div>'
        self.assertEqual(len(release_paragraphs(doc)), 1)
        with self.assertRaises(ValueError):
            release_paragraphs(b'<p>No identified body</p>')

    def test_pooled_beds_are_not_machines_or_branch_capacity(self):
        p = {"paragraph_index_zero_based": 2, "text_whitespace_normalized": "A campus has 12 dialysis beds."}
        row = quantity_observation(p, "12 dialysis beds", 12, "beds", "pooled_twin_hospitals")
        self.assertIsNone(row["derived_machine_count"])
        self.assertIsNone(row["allocation_to_other_campuses"])
        with self.assertRaises(ValueError):
            quantity_observation(p, "12 machines", 12, "machines", "pooled_twin_hospitals")
        with self.assertRaises(ValueError):
            quantity_observation(p, "12 dialysis beds", 12, "machines", "pooled_twin_hospitals")
        with self.assertRaises(ValueError):
            quantity_observation(p, "12 dialysis beds", 15, "beds", "pooled_twin_hospitals")


if __name__ == "__main__":
    unittest.main()
