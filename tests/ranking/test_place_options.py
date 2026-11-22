import io
import unittest

from app.ranking import search_facilities
from app.ranking.gazetteer import gazetteer_fallback, load_gazetteer
from app.ranking.location import majority_state, resolve_place


def row(facility_id, state, lat=10.0, lon=20.0, city="Sample City", pin="111111"):
    return {"facility_id": facility_id, "name": "Synthetic Hospital", "city": city, "state": state, "pin": pin,
            "latitude": lat, "longitude": lon, "procedures": "The clinic performs dialysis."}


# Synthetic gazetteer rows in the built file's shape (kind, key, state, latitude, longitude).
GAZETTEER = """kind,key,state,latitude,longitude
pin,222222,Karnataka,10.2,20.2
city,Sample Town,Karnataka,10.1,20.1
city,Shared Town,Karnataka,10.0,20.0
city,Shared Town,Kerala,12.0,22.0
"""


class MajorityStateTests(unittest.TestCase):
    def test_a_city_field_in_the_state_column_no_longer_forces_a_question(self):
        rows = [row(str(i), "Maharashtra") for i in range(9)] + [row("x", "Pune")]
        self.assertEqual("maharashtra", majority_state(rows))
        self.assertEqual("ambiguous_location", search_facilities("dialysis", {"city": "Sample City"}, facilities=rows)["status"])
        found = search_facilities("dialysis", {"city": "Sample City"}, facilities=rows, prefer_majority_state=True)
        self.assertEqual("ok", found["status"])
        self.assertTrue(found["approximate_location"])

    def test_a_real_split_between_states_still_asks(self):
        rows = [row(str(i), "Maharashtra") for i in range(6)] + [row(f"k{i}", "Karnataka", 12.0, 22.0) for i in range(4)]
        self.assertEqual("", majority_state(rows))
        point, choices = resolve_place(rows, "city", "", prefer_majority_state=True)
        self.assertIsNone(point)
        self.assertEqual(["Karnataka", "Maharashtra"], [choice["state"] for choice in choices])

    def test_a_typed_state_wins_over_the_majority(self):
        rows = [row(str(i), "Maharashtra") for i in range(9)] + [row("k", "Karnataka", 12.0, 22.0)]
        point, _ = resolve_place(rows, "city", "karnataka", prefer_majority_state=True)
        self.assertEqual((12.0, 22.0), point)


class GazetteerTests(unittest.TestCase):
    def setUp(self):
        self.fallback = gazetteer_fallback(load_gazetteer(io.StringIO(GAZETTEER)))
        self.rows = [row("a", "Karnataka", 10.21, 20.21)]

    def test_a_pin_missing_from_the_records_resolves_from_the_gazetteer(self):
        self.assertEqual("unresolved_location", search_facilities("dialysis", {"pin": "222222"}, facilities=self.rows)["status"])
        found = search_facilities("dialysis", {"pin": "222222"}, facilities=self.rows, place_fallback=self.fallback)
        self.assertEqual("ok", found["status"])
        self.assertTrue(found["approximate_location"])
        self.assertEqual("a", found["direct_results"][0]["facility_id"])

    def test_a_town_resolves_only_when_its_state_is_clear(self):
        self.assertEqual((10.1, 20.1), self.fallback("city", "sample town", ""))
        self.assertIsNone(self.fallback("city", "shared town", ""))
        self.assertEqual((12.0, 22.0), self.fallback("city", "Shared Town", "kerala"))
        self.assertIsNone(self.fallback("city", "sample town", "kerala"))
        self.assertIsNone(self.fallback("pin", "999999", ""))

    def test_records_still_come_first(self):
        rows = [row("a", "Karnataka", 1.0, 1.0, city="Sample Town")]
        found = search_facilities("dialysis", {"city": "Sample Town"}, facilities=rows, place_fallback=self.fallback)
        self.assertEqual(0.0, found["direct_results"][0]["distance_km"])
