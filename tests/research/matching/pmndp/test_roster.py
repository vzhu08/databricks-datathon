"""SRC-C01 roster importer. Entirely synthetic: no centre, district, date or
count here comes from a real roster."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from matching_fixtures import ROOT

from research.matching.common import MatchingError
from research.matching.pmndp.extract import clean, lines_above
from research.matching.pmndp.roster import build, centre_key, ingest, remark

sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from validation import semantic_check  # noqa: E402  (D's validator, read-only)

SHA = {"ap_est": "a" * 64, "ap_reg": "b" * 64, "ts_list": "c" * 64}


def document(key, kind, columns, **extra):
    family = "synthetic_ap_parliament" if key.startswith("ap") else "synthetic_ts_health"
    base = {"key": key, "kind": kind, "state": "Andhra Pradesh" if key.startswith("ap") else "Telangana",
            "publisher": "Synthetic publisher", "family": family, "url": f"https://example.invalid/{key}.pdf",
            "sha256": SHA[key], "retrieved_at": "2026-11-21T21:00:00Z", "published_date": "2023-03-01",
            "source_date": "2023-03-01", "license": "Synthetic fixture", "rows": f"{key}.rows.json",
            "independence_status": "shared_origin" if key.startswith("ap") else "unassessed",
            "profile": {"columns": columns, "skip": ["^sl"], "carry": ["district"]}}
    base.update(extra)
    return base


def rows(*lines):
    return [{"page": 1 + i // 6, "table": 1, "row": 1 + i, "cells": list(cells)} for i, cells in enumerate(lines)]


def fixture():
    documents = [
        document("ap_est", "establishment", {"serial": 0, "district": 1, "name": 2, "established": 3}),
        document("ap_reg", "registrations", {"serial": 0, "district": 1, "name": 2,
                                             "registrations": {"2020-21": 3, "2021-22": 4}}),
        document("ts_list", "listing", {"serial": 0, "district": 1, "name": 2, "address": 3}),
    ]
    tables = {
        "ap_est": rows(("Sl. No", "District", "Name of the centre", "Date of establishment"),
                       ("1", "North District", "Larkspur Area Hospital", "05-03-2018"),
                       ("2", None, "Marigold District Hospital", "17/08/2019"),
                       ("3", "South District", "Larkspur Area Hospital", "sometime in 2020"),
                       ("4", "South District", "Juniper Community Health Centre", "01-01-2021"),
                       (None, None, "", None),
                       ("5", "South District", None, "02-02-2022"),
                       ("x", "South District", "Quillon Hospital", "02-02-2022"),
                       ("Total", None, "4", None),
                       ("6", "East District")),
        "ap_reg": rows(("Sl. No", "District", "Centre", "2020-21", "2021-22"),
                       ("1", "North District", "Larkspur Area Hosp.", "120", "1,340"),
                       ("2", "South District", "Juniper Community Health Centre", "0", "15"),
                       ("3", "South District", "Larkspur Area Hospital", "-", "abc"),
                       ("4", "West District", "Tamarind Hospital", "7", "9"),
                       ("Total", None, None, "127", "1,364")),
        "ts_list": rows(("Sl. No", "District", "Centre", "Address"),
                        ("1", "Central District", "Area Hospital", "Old Town Road, Central 500001"),
                        ("2", "Central District", "Area Hospital", "Riverside Colony, Central 500002"),
                        ("4", "Hill District", "District Hospital", "Hill Town")),
    }
    return {"documents": documents}, tables


def run(manifest, tables):
    return build(copy.deepcopy(manifest), lambda d: {"source_sha256": d["sha256"], "rows": tables[d["key"]]})


class RosterTests(unittest.TestCase):
    def test_rows_campuses_and_claims_stay_separate_layers(self):
        result = run(*fixture())
        report = result["report"]
        self.assertEqual((11, 3, 2), (report["programme_rows"], report["rejected_rows"], report["aggregate_rows"]))
        self.assertEqual({"name_missing": 1, "serial_unreadable": 1, "too_few_cells": 1},
                         report["documents"]["ap_est"]["rejected_by_reason"])
        self.assertEqual({"denominator": 8, "in_more_than_one_document": 3},
                         {k: report["campus_candidates"][k] for k in ("denominator", "in_more_than_one_document")})
        self.assertEqual({"centre_established": 3, "historical_registrations": 6, "programme_listing": 11},
                         report["claims"]["by_kind"])
        self.assertEqual({"external_facilities": 11, "facility_evidence": 20, "facility_matches": 0,
                          "review_queue": 4, "source_snapshots": 3}, report["table_counts"])
        for summary in report["documents"].values():      # every extracted row is accounted for
            self.assertEqual(summary["rows_read"], summary["header_or_blank_rows"] + summary["aggregate_rows"]
                             + summary["programme_rows"] + summary["rejected_rows"])
        located = result["raw_rows"][0]
        self.assertEqual(("ap_est", 1, 1, 2, 1, "Larkspur Area Hospital"),
                         tuple(located[k] for k in ("document", "page", "table", "row", "serial", "name_original")))

    def test_cross_annex_overlap_is_one_campus_with_shared_origin(self):
        result = run(*fixture())
        north = [c for c in result["campus_candidates"]
                 if c["district_original"] == "North District" and "Larkspur" in c["name_original"]]
        self.assertEqual(1, len(north))                       # 'Hosp.' and 'Hospital' are one centre
        self.assertEqual((["ap_est", "ap_reg"], True, ["Larkspur Area Hosp.", "Larkspur Area Hospital"]),
                         (north[0]["documents"], north[0]["shared_origin_overlap"], north[0]["names_seen"]))
        externals = [e for e in result["batch"]["external_facilities"] if "shared_origin_overlap" in e["quality_flags"]]
        self.assertEqual(6, len(externals))                   # one external per document, never merged evidence
        snapshot = {e["external_facility_id"]: e["snapshot_id"] for e in result["batch"]["external_facilities"]}
        self.assertTrue(all(snapshot[e["external_facility_id"]] == e["snapshot_id"]
                            for e in result["batch"]["facility_evidence"]))
        self.assertEqual({"shared_origin"}, {s["independence_status"] for s in result["batch"]["source_snapshots"]
                                             if s["source_key"].startswith("ap")})

    def test_same_name_in_another_district_or_at_another_address_is_another_campus(self):
        result = run(*fixture())
        larkspur = [c for c in result["campus_candidates"] if c["name_original"].startswith("Larkspur")]
        self.assertEqual({"North District", "South District"}, {c["district_original"] for c in larkspur})
        branches = [c for c in result["campus_candidates"] if c["name_original"] == "Area Hospital"]
        self.assertEqual(2, len(branches))
        self.assertEqual([["same_name_branch"], ["same_name_branch"]], [c["flags"] for c in branches])
        self.assertEqual({"500001", "500002"}, {e["pin"] for e in result["batch"]["external_facilities"]
                                                if e["name_original"] == "Area Hospital"})

    def test_branch_without_an_address_is_not_guessed(self):
        manifest, tables = fixture()
        manifest["documents"] = [document("ap_est", "listing", {"serial": 0, "district": 1, "name": 2, "address": 3}),
                                 document("ap_reg", "listing", {"serial": 0, "district": 1, "name": 2})]
        tables = {"ap_est": rows(("1", "North District", "Area Hospital", "Old Town Road"),
                                 ("2", "North District", "Area Hospital", "Riverside Colony")),
                  "ap_reg": rows(("1", "North District", "Area Hospital"))}
        result = run(manifest, tables)
        self.assertEqual(3, len(result["campus_candidates"]))
        loose = [c for c in result["campus_candidates"] if c["documents"] == ["ap_reg"]][0]
        self.assertIn("same_name_branch_unreconciled", loose["flags"])
        self.assertEqual(["pmndp_same_name_branch_unreconciled"], [r["reason_code"] for r in result["batch"]["review_queue"]])

    def test_zero_and_unreadable_values(self):
        result = run(*fixture())
        zero = [c for c in result["claims"] if c["kind"] == "historical_registrations" and c["value"]["patients"] == 0]
        self.assertEqual(1, len(zero))
        self.assertEqual(({"period": "2020-21", "patients": 0}, "unconfirmed"), (zero[0]["value"], zero[0]["present_day_access"]))
        self.assertIn("records 0 patients", zero[0]["assertion"])
        self.assertEqual(1, result["report"]["claims"]["zero_registration_claims"])
        self.assertEqual({"count_missing": 1, "count_unreadable": 1, "district_inherited_from_previous_row": 1,
                          "established_unreadable": 1}, result["report"]["row_flag_counts"])
        south = [r for r in result["raw_rows"] if r["document"] == "ap_est" and r["serial"] == 3][0]
        self.assertEqual(("sometime in 2020", None), (south["established_original"], south["established_date"]))
        self.assertEqual({"pmndp_row_unreadable": 3, "pmndp_serial_numbers_do_not_reconcile": 1},
                         {r: sum(q["reason_code"] == r for q in result["batch"]["review_queue"])
                          for r in {q["reason_code"] for q in result["batch"]["review_queue"]}})
        self.assertEqual(([3], []), (result["report"]["documents"]["ts_list"]["serial_missing"],
                                     result["report"]["documents"]["ts_list"]["serial_repeated"]))

    def test_no_claim_asserts_present_day_access_and_d_accepts_the_batch(self):
        batch = run(*fixture())["batch"]
        for row in batch["facility_evidence"]:
            self.assertEqual(("service", "dialysis", "inconclusive", "historical", None, None, None),
                             (row["claim_type"], row["service"], row["polarity"], row["temporal_status"],
                              row["facility_id"], row["match_id"], row["reviewer"]))
            self.assertIn("does not show that patients can get dialysis there today", row["assertion"])
        self.assertEqual([], batch["facility_matches"])
        semantic_check(batch, [])                              # raises on any contract violation

    def test_repeat_import_is_identical_and_double_listing_fails(self):
        manifest, tables = fixture()
        first, second = run(manifest, tables), run(manifest, tables)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        reordered = {"documents": list(reversed(manifest["documents"]))}
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(run(reordered, tables), sort_keys=True))
        twice = copy.deepcopy(manifest)
        twice["documents"].append(dict(twice["documents"][0], key="ap_est_again"))
        tables["ap_est_again"] = tables["ap_est"]
        with self.assertRaisesRegex(MatchingError, "one document is listed twice"):
            run(twice, tables)
        with self.assertRaisesRegex(MatchingError, "not extracted from the document"):
            build(copy.deepcopy(manifest), lambda d: {"source_sha256": "0" * 64, "rows": tables[d["key"]]})

    def test_profile_and_descriptor_are_checked(self):
        manifest, tables = fixture()
        broken = copy.deepcopy(manifest)
        del broken["documents"][0]["profile"]["columns"]["established"]
        with self.assertRaisesRegex(MatchingError, "needs the established column"):
            run(broken, tables)
        broken = copy.deepcopy(manifest)
        broken["documents"][2]["source_date"] = "June 2020"
        with self.assertRaisesRegex(MatchingError, "ISO date or null"):
            run(broken, tables)
        undated = copy.deepcopy(manifest)
        undated["documents"][2]["source_date"] = None
        statuses = {e["temporal_status"] for e in run(undated, tables)["batch"]["facility_evidence"]
                    if e["source_url"].endswith("ts_list.pdf")}
        self.assertEqual({"undated"}, statuses)
        self.assertEqual("Old Town Road", clean("  Old   Town\nRoad "))
        self.assertIsNone(clean("   "))

    def test_abbreviated_and_run_together_names_are_one_centre(self):
        """One annex abbreviates and the other spells out; PDF text often loses its spaces."""
        for names in (("CHC-Larkspur", "C.H.C. Larkspur", "CommunityHealthCenterLarkspur", "COMMUNITYHEALTHCENTRELARKSPUR"),
                      ("A.H.Marigold", "AHMarigold", "Area Govt Hospital Marigold", "Area Hosipital Marigold"),
                      ("D.H.Juniper", "DISTIRICTHOSPITALJUNIPER", "District Hospital Juniper"),
                      ("GGHQuillon", "Government General Hospital Quillon")):
            self.assertEqual(1, len({centre_key(n) for n in names}), names)
        self.assertNotEqual(centre_key("A.H.Marigold"), centre_key("D.H.Marigold"))        # another kind of facility
        self.assertEqual(centre_key("CHC-Larkspur"), centre_key("CHC-Larkspur (Established under the programme)"))
        self.assertEqual("Established under the programme", remark("CHC-Larkspur (Established under the programme)"))
        self.assertIsNone(remark("CHC-Larkspur"))

    def test_real_layout_pages_missing_district_and_near_matches(self):
        est = document("ap_est", "establishment", {"serial": 0, "name": 1, "district": 2, "established": 3})
        est["profile"]["pages"] = [2]
        reg = document("ap_reg", "registrations", {"serial": 0, "name": 1, "registrations": {"FY-A": 2}},
                       count_label="new patients registered")
        tables = {"ap_est": [{"page": 1, "table": 1, "row": 1, "cells": ["1", "Some State", "12.5", "9.0"]},
                             *[dict(r, page=2) for r in rows(("S.No.", "FacilityName", "DistrictName", "EstablishedDate"),
                                                             ("1", "CHC-Larkspur (Now under another scheme)", "North District", "05-03-2018"),
                                                             ("2", "A.H.Marigold", "South District", "17-08-2019"),
                                                             ("3", "A.H.Saffronpur", "South District", "17-08-2019"),
                                                             ("4", "D.H.Tamarind", "East District", "17-08-2019"))]],
                  "ap_reg": [dict(r, **({"recovered": "text_above_table"} if r["row"] == 2 else {}))
                             for r in rows(("S.No", "NameoftheDialysisFacility", "NoofNewPatientsRegistered"),
                                           ("1", "CommunityHealthCenterLarkspur", "12"),
                                           ("2", "Area Hospital Saffronpuram", "0"),
                                           ("3", "Area Hospital Tamarind", "4"),
                                           ("4", "Area Hospital Quillon", "7"))]}
        result = run({"documents": [est, reg]}, tables)
        report = result["report"]
        self.assertEqual((1, 4), (report["documents"]["ap_est"]["rows_on_other_pages"], report["documents"]["ap_est"]["programme_rows"]))
        by_key = {c["centre_key"]: c for c in result["campus_candidates"]}
        self.assertEqual(7, len(by_key))
        shared = by_key["chc:larkspur"]                              # exact key: one campus, district taken from the other annex
        self.assertEqual((["ap_est", "ap_reg"], "North District", ["district_from_other_document"]),
                         (shared["documents"], shared["district_original"], shared["flags"]))
        reg_row = [r for r in result["raw_rows"] if r["document"] == "ap_reg" and r["serial"] == 1][0]
        self.assertIsNone(reg_row["district_original"])              # the row itself stays as printed
        self.assertEqual("Now under another scheme", result["raw_rows"][0]["remark_original"])
        # A similar place name, or the same place with another kind of facility, is flagged and never merged.
        self.assertEqual({"ah:saffronpur": ["ah:saffronpuram"], "ah:saffronpuram": ["ah:saffronpur"],
                          "dh:tamarind": ["ah:tamarind"], "ah:tamarind": ["dh:tamarind"]},
                         {k: [x["centre_key"] for x in result["campus_candidates"] if x["campus_id"] in c["possible_overlap_with"]]
                          for k, c in by_key.items() if c["possible_overlap_with"]})
        self.assertEqual(["district_not_printed"], by_key["ah:quillon"]["flags"])
        self.assertEqual(4, sum(r["reason_code"] == "pmndp_possible_overlap_unreconciled" for r in result["batch"]["review_queue"]))
        self.assertEqual({"recovered_from_text_above_table": 1}, report["row_flag_counts"])
        self.assertTrue(any("0 new patients registered" in c["assertion"] for c in result["claims"]))
        semantic_check(result["batch"], [])
        with self.assertRaisesRegex(MatchingError, "list of page numbers"):
            broken = copy.deepcopy(est)
            broken["profile"]["pages"] = "2"
            run({"documents": [broken, reg]}, tables)

    def test_a_row_printed_above_a_continued_table_is_recovered(self):
        columns = [(50, 80), (80, 300), (300, 360)]
        word = lambda text, x0, top: {"text": text, "x0": x0, "x1": x0 + 6 * len(text), "top": top}
        words = [word("Annexure", 150, 40), word("9", 55, 70.2), word("Area", 85, 70.0), word("Hospital", 115, 70.4),
                 word("Larkspur", 170, 70.1), word("12", 310, 70.3), word("10", 55, 120), word("Later", 85, 120), word("3", 310, 120)]
        self.assertEqual([["9", "Area Hospital Larkspur", "12"]], lines_above(words, columns, 0, 100))
        self.assertEqual([], lines_above(words, columns, 0, 60))        # a heading alone is not a row

    def test_cli_writes_reproducible_private_outputs(self):
        manifest, tables = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "in").mkdir()
            (tmp / "in/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            for key, table in tables.items():
                (tmp / f"in/{key}.rows.json").write_text(json.dumps({"source_sha256": SHA[key], "rows": table}), encoding="utf-8")
            outputs = []
            for name in ("one", "two"):
                done = subprocess.run([sys.executable, "-m", "research.matching.pmndp.roster", "--manifest",
                                       str(tmp / "in/manifest.json"), "--output-dir", str(tmp / name)],
                                      cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(0, done.returncode, done.stderr)
                outputs.append({p.name: p.read_bytes() for p in sorted((tmp / name).iterdir())})
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual({"batch.json", "campus_candidates.json", "claims.json", "manifest.json", "raw_rows.json",
                              "rejects.json", "report.json"}, set(outputs[0]))
            refused = subprocess.run([sys.executable, "-m", "research.matching.pmndp.roster", "--manifest",
                                      str(tmp / "in/manifest.json"), "--output-dir", str(tmp / "in")],
                                     cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(1, refused.returncode)


if __name__ == "__main__":
    unittest.main()
