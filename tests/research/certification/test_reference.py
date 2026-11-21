"""Synthetic sources only: no public facility rows or snapshots are checked in."""
from html import escape
import http.client
import io
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from research.certification import run
from research.certification.audit import acquire_audit, compare
from research.certification.build import build, checked_raw
from research.certification.capture import capture
from research.certification.common import ROOT, SourceError, save, sha
from research.certification.episodes import episode, parse_date, relate, sample
from research.certification.fetch import Fetcher, public_url
from research.certification.tables import HEADERS, LANDING, POLICY, REGISTER, TERMS, combined_url, discover, page_rows


def html(mode="full", rows=None, next_page=None):
    rows = rows if rows is not None else [["1", "Rajasthan", "Synthetic District", "Synthetic Campus",
                                          "Synthetic outpatient department", "20-01-2020", "19-01-2023"]]
    table = '<div class="view-nqas view-display-id-page_' + ("1" if mode == "full" else "2") + '">'
    table += "<table><thead><tr>" + "".join("<th>" + h + "</th>" for h in HEADERS) + "</tr></thead><tbody>"
    table += "".join("<tr>" + "".join("<td>" + escape(c) + "</td>" for c in row) + "</tr>" for row in rows)
    table += "</tbody></table>"
    if next_page is not None:
        url = endpoint(mode) + "&page=" + str(next_page)
        table += '<li class="pager__item--next"><a href="' + escape(url, quote=True) + '">next</a></li>'
    return (table + "</div>").encode()


def landing():
    return ("".join('<form method="get" action="/nqas-certification-' + m + '">' +
                    ''.join('<input name="' + f + '">' for f in ("field_state1_value", "field_district1_value", "title")) +
                    '</form>' for m in ("full", "partial"))).encode()


def endpoint(mode):
    return discover(landing())["endpoints"][mode]


class FakeFetcher:
    def __init__(self, root, mapping):
        self.root, self.mapping, self.attempt_log = Path(root), mapping, []
        (self.root / "raw").mkdir(parents=True, exist_ok=True)

    def get(self, url):
        value = self.mapping[url]
        self.attempt_log.append({"url": url, "status": "failed" if isinstance(value, Exception) else "ok"})
        if isinstance(value, Exception):
            raise value
        name = "raw/" + sha(value) + ".html"
        (self.root / name).write_bytes(value)
        return {"url": url, "final_url": url, "http_status": 200, "sha256": sha(value), "bytes": len(value),
                "artifact": name, "retrieved_at": "2026-11-21T00:00:00Z"}


def mapping():
    return {LANDING: landing(), POLICY: b"<p>Synthetic copyright policy</p>", TERMS: b"<p>Synthetic terms</p>",
            REGISTER: SourceError("tls_certificate_expired"), endpoint("full"): html(), endpoint("partial"): html("partial"),
            combined_url(0): html() + html("partial")}


class DatesAndIdentity(unittest.TestCase):
    def item(self, start="2020-01-20", end="2023-01-19", nin=None, name=None, serial="1"):
        row = page_rows(html(), endpoint("full"), "full")[0][0]
        row.update(valid_from_raw=start, valid_until_raw=end, nin=nin, serial=serial)
        row["display_cells"] = list(row["display_cells"])
        row["display_cells"][0], row["display_cells"][5:] = serial, [start, end]
        if name:
            row["facility"] = row["display_cells"][3] = name
        return episode(row, {"sha256": "a" * 64}, "2026-11-21")

    def test_ambiguous_numeric_preserves_both(self):
        d = parse_date(" 02-03-2020 ")
        self.assertEqual(d["candidates"], ["2020-02-03", "2020-03-02"])
        self.assertEqual(d["raw"], " 02-03-2020 ")
        self.assertIsNone(d["iso"])

    def test_exact_calendar_and_named_dates(self):
        for raw, iso in [("20-02-2020", "2020-02-20"), ("2020/02/20", "2020-02-20"),
                         ("02-02-2020", "2020-02-02"), ("20 February 2020", "2020-02-20")]:
            self.assertEqual(parse_date(raw)["iso"], iso)

    def test_invalid_and_short_years_not_repaired(self):
        for raw in ["31-02-2020", "01-02-20", "unknown text"]:
            self.assertEqual(parse_date(raw)["status"], "invalid")
        self.assertEqual(parse_date("")["status"], "missing")

    def test_ambiguous_expiration_not_current_assertion(self):
        row = self.item(end="11-12-2026")
        self.assertEqual(row["expiration"], "ambiguous_at_as_of")
        self.assertIsNone(row["end"]["iso"])

    def test_reversed_interval_flagged(self):
        self.assertFalse(self.item(start="2025-01-20", end="2024-01-19")["interval_coherent"])

    def test_repeated_name_is_not_identity(self):
        result = relate([self.item(), self.item(start="2024-01-20", end="2027-01-19")])
        self.assertEqual(result["verified_identifier_relations"], [])
        self.assertEqual(result["repeated_name_district_groups_without_verified_identity"], 1)

    def test_nin_text_and_nonoverlapping_episodes_retained(self):
        items = [self.item(nin="000123"), self.item(start="2024-01-20", end="2027-01-19", nin="000123")]
        result = relate(items)
        self.assertEqual(len(result["verified_identifier_relations"]), 1)
        self.assertEqual(result["verified_identifier_relations"][0]["nin"], "000123")
        self.assertTrue(result["verified_identifier_relations"][0]["formal_renewal_not_asserted"])
        self.assertEqual(len(items), 2)

    def test_repeated_nin_campus_conflict_preserved(self):
        result = relate([self.item(nin="000123"), self.item(nin="000123", name="Other Synthetic Campus")])
        self.assertEqual(result["identifier_conflicts"][0]["reason"], "same_nin_incompatible_campus_labels")
        self.assertFalse(result["verified_identifier_relations"])

    def test_overlapping_nin_intervals_preserved(self):
        result = relate([self.item(nin="000123"), self.item(nin="000123", serial="2")])
        self.assertEqual(result["identifier_conflicts"][0]["reason"], "same_nin_overlapping_intervals_preserved")

    def test_ambiguous_nin_intervals_not_linked(self):
        result = relate([self.item(nin="000123"), self.item(nin="000123", start="02-03-2024")])
        self.assertEqual(result["identifier_conflicts"][0]["reason"], "same_nin_unresolved_interval")

    def test_stratified_sample_deterministic(self):
        items = [self.item(serial=str(i)) for i in range(30)]
        self.assertEqual(sample(items), sample(list(reversed(items))))
        self.assertEqual(len(sample(items)), 20)


class SourceTables(unittest.TestCase):
    def test_observed_filters(self):
        self.assertEqual(set(discover(landing())["endpoints"]), {"full", "partial"})
        with self.assertRaisesRegex(SourceError, "full_partial_forms_missing"):
            discover(b"<p>Changed website</p>")

    def test_fields_and_next_page(self):
        rows, nxt = page_rows(html(next_page=1), endpoint("full"), "full")
        self.assertTrue(nxt.endswith("&page=1"))
        self.assertIsNone(rows[0]["nin"])
        self.assertIsNone(rows[0]["category"])
        self.assertEqual(rows[0]["original_cells"][4], "Synthetic outpatient department")

    def test_changed_headers_fail(self):
        with self.assertRaisesRegex(SourceError, "source_headers_changed"):
            page_rows(html().replace(b"Validity date", b"New heading"), endpoint("full"), "full")

    def test_ignored_state_filter_fails(self):
        with self.assertRaisesRegex(SourceError, "state_filter_not_applied"):
            page_rows(html().replace(b"Rajasthan", b"Another state"), endpoint("full"), "full")

    def test_cycle_and_filter_loss_fail(self):
        with self.assertRaisesRegex(SourceError, "pagination_not_sequential"):
            page_rows(html(next_page=0), endpoint("full"), "full")
        with self.assertRaisesRegex(SourceError, "pagination_changed_filter"):
            page_rows(html(next_page=1).replace(b"field_state1_value=Rajasthan", b"field_state1_value=All"), endpoint("full"), "full")

    def test_missing_table_not_zero_coverage(self):
        with self.assertRaisesRegex(SourceError, "table_missing_without_empty_marker"):
            page_rows(b'<div class="view-nqas view-display-id-page_1"></div>', endpoint("full"), "full")

    def test_public_url_restrictions(self):
        for url in ["http://qps.nhsrcindia.org/", "https://evil.example/", "https://u:p@qps.nhsrcindia.org/",
                    LANDING + "?access_token=secret", LANDING + "#fragment"]:
            with self.assertRaises(SourceError):
                public_url(url)


class CaptureAndReplay(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = mapping()

    def tearDown(self):
        self.temp.cleanup()

    def capture(self):
        return capture(self.root, fetcher=FakeFetcher(self.root, self.data))

    def test_complete_pages_and_register_failure_separate(self):
        cap = self.capture()
        self.assertEqual(cap["views"]["full"]["row_count"], 1)
        self.assertTrue(cap["views"]["full"]["complete"])
        self.assertEqual(cap["blockers"][0]["reason"], "tls_certificate_expired")

    def test_follow_all_pages(self):
        self.data[endpoint("full")] = html(next_page=1)
        self.data[endpoint("full") + "&page=1"] = html().replace(b"Synthetic Campus", b"Synthetic Other Campus")
        self.assertEqual(self.capture()["views"]["full"]["row_count"], 2)

    def test_repeated_page_not_double_counted(self):
        self.data[endpoint("full")] = html(next_page=1)
        self.data[endpoint("full") + "&page=1"] = html()
        view = self.capture()["views"]["full"]
        self.assertEqual((view["row_count"], view["complete"], view["termination"]), (1, False, "repeated_page_content"))

    def test_page_limit_explicit_partial_result(self):
        self.data[endpoint("full")] = html(next_page=1)
        view = capture(self.root, max_pages=1, fetcher=FakeFetcher(self.root, self.data))["views"]["full"]
        self.assertEqual(view["termination"], "pagination_limit_reached")
        self.assertFalse(view["complete"])

    def test_later_page_failure_preserves_captured_rows(self):
        self.data[endpoint("full")] = html(next_page=1)
        self.data[endpoint("full") + "&page=1"] = SourceError("http_503")
        cap = self.capture()
        self.assertEqual(cap["views"]["full"]["row_count"], 1)
        self.assertEqual(len(build(self.root, "2026-11-21")["episodes"]), 2)

    def test_changed_controls_still_write_failure_manifest(self):
        self.data[LANDING] = b"<p>Different site</p>"
        cap = self.capture()
        self.assertEqual(cap["blockers"][-1]["reason"], "full_partial_forms_missing")
        self.assertTrue((self.root / "capture.json").exists())

    def test_corrupt_raw_and_escape_rejected(self):
        doc = self.capture()["documents"]["full_0"]
        (self.root / doc["artifact"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(SourceError, "hash_mismatch"):
            build(self.root, "2026-11-21")
        with self.assertRaisesRegex(SourceError, "artifact_path_escape"):
            checked_raw(self.root, {**doc, "artifact": "../outside.html"})

    def test_audit_exact_disagreement_and_unavailable(self):
        self.capture()
        data = build(self.root, "2026-11-21")
        self.data[combined_url(0)] = html() + html("partial").replace(b"Synthetic Campus", b"Changed Campus")
        audit = acquire_audit(self.root, data["episodes"], FakeFetcher(self.root, self.data))
        self.assertEqual(audit["by_status"], {"exact_display_fields_agree": 1, "unresolved": 1})
        self.assertEqual(audit, compare(self.root, data["episodes"]))
        self.assertEqual(audit["register_comparisons_completed"], 0)

    def test_real_v1_validator_and_holdout_contract(self):
        self.capture()
        data = build(self.root, "2026-11-21")
        batch = data["batch"]
        self.assertEqual(batch["facility_matches"], [])
        self.assertTrue(all(e["claim_type"] == "accreditation" and e["service"] is None and e["facility_id"] is None
                            for e in batch["facility_evidence"]))
        self.assertTrue(all(e["matching_feature_use"] == "excluded" for e in data["episodes"]))
        self.assertEqual({s["source_family"] for s in batch["source_snapshots"]}, {"nhsrc_nqas"})
        save(self.root / "batch.json", batch)
        save(self.root / "base.json", [])
        result = subprocess.run([sys.executable, str(ROOT / "databricks/enrichment/validate_batch.py"),
                                 "--batch", str(self.root / "batch.json"), "--base", str(self.root / "base.json"),
                                 "--as-of", "2026-11-21"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ambiguous_current_interval_withheld_but_row_retained(self):
        self.data[endpoint("full")] = html().replace(b"19-01-2023", b"11-12-2026")
        self.capture()
        data = build(self.root, "2026-11-21")
        self.assertEqual(len(data["batch"]["external_facilities"]), 2)
        self.assertEqual(data["report"]["evidence_withheld_for_v1_temporal_limits"], 1)

    def test_expiration_change_versions_evidence_without_changing_source_identity(self):
        self.capture()
        earlier = build(self.root, "2021-11-21")["batch"]
        later = build(self.root, "2026-11-21")["batch"]
        self.assertEqual(earlier["source_snapshots"], later["source_snapshots"])
        self.assertEqual(earlier["external_facilities"], later["external_facilities"])
        self.assertTrue({e["evidence_id"] for e in earlier["facility_evidence"]}.isdisjoint(
            {e["evidence_id"] for e in later["facility_evidence"]}))
        self.assertTrue({e["review_id"] for e in earlier["review_queue"]}.isdisjoint(
            {e["review_id"] for e in later["review_queue"]}))

    def test_cli_offline_replay_and_no_overwrite(self):
        target = self.root / "run"
        def fake_capture(root, **kwargs):
            return capture(root, fetcher=FakeFetcher(root, self.data), **kwargs)
        def fake_audit(root, episodes):
            return acquire_audit(root, episodes, FakeFetcher(root, self.data))
        with patch.object(run, "local_path", side_effect=lambda p: Path(p).resolve()), \
             patch.object(run, "capture", side_effect=fake_capture), patch.object(run, "acquire_audit", side_effect=fake_audit):
            run.acquire(target, "2026-11-21")
            with patch.object(Fetcher, "get", side_effect=AssertionError("Network in replay")):
                self.assertEqual(run.replay(target)["status"], "byte_identical_replay")
            with self.assertRaisesRegex(SourceError, "output_already_exists"):
                run.acquire(target, "2026-11-21")
            (target / "batch.json").write_text("{}")
            with self.assertRaisesRegex(SourceError, "hash_mismatch"):
                run.replay(target)

    def test_output_cannot_be_tracked_source_tree(self):
        with self.assertRaisesRegex(SourceError, "ignored_data_local"):
            run.local_path(ROOT / "research/certification/source-data")


class Transport(unittest.TestCase):
    @staticmethod
    def response(raw=b"<p>Synthetic page</p>", length=None):
        response = io.BytesIO(raw)
        response.status = 200
        response.headers = {"Content-Type": "text/html", "Content-Length": str(len(raw) if length is None else length)}
        response.geturl = lambda: LANDING
        return response

    def test_hash_and_first_retrieval_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            fetcher = Fetcher(root, opener=lambda *a, **k: self.response())
            self.assertEqual(fetcher.get(LANDING), fetcher.get(LANDING))

    def test_response_size_and_truncation_guards(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(SourceError, "response_size_limit"):
                Fetcher(root, max_bytes=3, opener=lambda *a, **k: self.response()).get(LANDING)
            with self.assertRaisesRegex(SourceError, "truncated_response"):
                Fetcher(root, opener=lambda *a, **k: self.response(length=500)).get(LANDING)

    def test_expired_certificate_not_bypassed_or_retried(self):
        with tempfile.TemporaryDirectory() as root:
            error = urllib.error.URLError(ssl.SSLCertVerificationError("certificate has expired"))
            with patch("urllib.request.OpenerDirector.open", side_effect=error) as opened:
                fetcher = Fetcher(root, sleep=lambda _: None)
                with self.assertRaisesRegex(SourceError, "tls_certificate_expired"):
                    fetcher.get(REGISTER)
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(len(fetcher.attempt_log), 1)

    def test_incomplete_response_retried_boundedly(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("urllib.request.OpenerDirector.open", side_effect=http.client.IncompleteRead(b"part")) as opened:
                with self.assertRaisesRegex(SourceError, "truncated_response"):
                    Fetcher(root, attempts=2, sleep=lambda _: None).get(LANDING)
                self.assertEqual(opened.call_count, 2)


if __name__ == "__main__":
    unittest.main()
