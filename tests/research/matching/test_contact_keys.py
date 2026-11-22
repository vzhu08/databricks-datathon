"""Contact-key join prototype. Every facility, number, host and email here is invented."""
import unittest

from research.matching.contact_keys import (emails_from, geography, host_key, join, phone_e164,
                                            phones_from)


def vf(fid, name, phones=(), hosts=(), emails=(), listed_phones=(), state="rajasthan", pin="302001", point=None):
    official = {"phone": set(phones), "host": set(hosts), "email": set(emails)}
    listed = {"phone": set(phones) | set(listed_phones), "host": set(hosts), "email": set(emails)}
    return {"id": fid, "name": name, "official": official, "listed": listed, "state": state, "pin": pin,
            "city": None, "point": point}


def ext(eid, name, phones=(), hosts=(), emails=(), state="rajasthan", pin="302001", point=None):
    return {"id": eid, "name": name, "state": state, "pin": pin, "point": point, "district": None,
            "keys": {"phone": set(phones), "host": set(hosts), "email": set(emails)}}


class NormaliseTest(unittest.TestCase):
    def test_phone_forms(self):
        for text in ("+91 98290 12345", "098290-12345", "0091 9829012345", "91-9829012345", "9829012345"):
            self.assertEqual(phone_e164(text), "+919829012345", text)
        self.assertEqual(phone_e164("0141 2560291"), "+911412560291")

    def test_phone_rejects(self):
        for text in ("222765", "1800 123 4567", "9999999999", "", None, "true", "0000012345"):
            self.assertIsNone(phone_e164(text), text)

    def test_phone_lists(self):
        self.assertEqual(phones_from('["+919829012345","0141-2560291"]'), {"+919829012345", "+911412560291"})
        self.assertEqual(phones_from("0141 2560291, 98290 12345"), {"+911412560291", "+919829012345"})

    def test_hosts(self):
        self.assertEqual(host_key("https://www.ExampleHospital.org/contact/"), "examplehospital.org")
        self.assertEqual(host_key("examplehospital.org"), "examplehospital.org")
        self.assertEqual(host_key("http://unit.example.nic.in/"), "unit.example.nic.in")
        for shared in ("https://www.facebook.com/123", "https://www.justdial.com/x", "nhp.gov.in",
                       "https://abc.blogspot.com", "true", "2024-07-11", "null", "info@x.org"):
            self.assertIsNone(host_key(shared), shared)

    def test_emails(self):
        self.assertEqual(emails_from("Info@ExampleHospital.org, x"), {"info@examplehospital.org"})
        self.assertEqual(emails_from("null"), set())


class JoinTest(unittest.TestCase):
    def test_unique_key_with_agreeing_place_would_confirm(self):
        rows = join([vf("v1", "Asha Devi Hospital", hosts=["ashadevi.example"])],
                    [ext("e1", "Asha Devi Hospital", hosts=["ashadevi.example"])])
        self.assertEqual([r["outcome"] for r in rows], ["would_confirm"])

    def test_chain_host_is_not_unique(self):
        bases = [vf("v1", "Chain Hospital North", hosts=["chain.example"]),
                 vf("v2", "Chain Hospital South", hosts=["chain.example"])]
        rows = join(bases, [ext("e1", "Chain Hospital North", hosts=["chain.example"])])
        self.assertEqual({r["outcome"] for r in rows}, {"not_unique"})

    def test_listed_number_on_another_row_blocks_uniqueness(self):
        bases = [vf("v1", "Asha Devi Hospital", phones=["+919829012345"]),
                 vf("v2", "Other Clinic", listed_phones=["+919829012345"])]
        rows = join(bases, [ext("e1", "Asha Devi Hospital", phones=["+919829012345"])])
        self.assertEqual([r["outcome"] for r in rows], ["not_unique"])

    def test_geography_conflict_and_unknown(self):
        conflict = join([vf("v1", "Asha Devi Hospital", hosts=["a.example"])],
                        [ext("e1", "Asha Devi Hospital", hosts=["a.example"], pin="110001")])
        self.assertEqual(conflict[0]["outcome"], "geo_conflict")
        unknown = join([vf("v1", "Asha Devi Hospital", hosts=["a.example"], state=None, pin=None)],
                       [ext("e1", "Asha Devi Hospital", hosts=["a.example"], state=None, pin=None)])
        self.assertEqual(unknown[0]["outcome"], "geo_unknown")

    def test_distance(self):
        self.assertEqual(geography(vf("v", "x", pin=None, point=(26.9, 75.8)),
                                   ext("e", "x", pin=None, state=None, point=(26.91, 75.8))), "agree")
        self.assertEqual(geography(vf("v", "x", pin=None, point=(26.9, 75.8)),
                                   ext("e", "x", pin=None, state=None, point=(27.5, 75.8))), "conflict")

    def test_names_without_evidence_go_to_review(self):
        rows = join([vf("v1", "Asha Devi Hospital", hosts=["a.example"])],
                    [ext("e1", "Kamla Nursing Home", hosts=["a.example"])])
        self.assertEqual(rows[0]["outcome"], "name_disagrees")

    def test_two_outside_records_compete(self):
        rows = join([vf("v1", "Asha Devi Hospital", hosts=["a.example"], phones=["+919829012345"])],
                    [ext("e1", "Asha Devi Hospital", hosts=["a.example"]),
                     ext("e2", "Asha Devi Hospital", phones=["+919829012345"])])
        self.assertEqual({r["outcome"] for r in rows}, {"competing"})

    def test_two_vf_rows_on_one_outside_record_compete(self):
        # Same institution, two campuses, different unique keys, one outside record.
        bases = [vf("v1", "Asha Devi Hospital", hosts=["ashadevi.example"]),
                 vf("v2", "Asha Devi Hospital", emails=["office@ashadevi-trust.example"])]
        rows = join(bases, [ext("e1", "Asha Devi Hospital", hosts=["ashadevi.example"],
                               emails=["office@ashadevi-trust.example"])])
        self.assertEqual({r["outcome"] for r in rows}, {"competing"})

    def test_state_only_agreement_is_not_enough(self):
        rows = join([vf("v1", "Asha Devi Hospital", hosts=["a.example"], pin=None)],
                    [ext("e1", "Asha Devi Hospital", hosts=["a.example"], pin=None)])
        self.assertEqual(rows[0]["geography"], "state_only")
        self.assertEqual(rows[0]["outcome"], "geo_unknown")


if __name__ == "__main__":
    unittest.main()
