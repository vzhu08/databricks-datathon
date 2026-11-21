import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from research.acquisition.common import AcquisitionError, ROOT, file_digest, read_json
from research.acquisition.fetch import Fetcher
from research.acquisition.run import acquire, provenance, run, verify_saved
from fixtures import feature, geojson, landing, osm_archive


class Response(io.BytesIO):
    status = 200

    def __init__(self, content, kind="application/json", status=200, length=None):
        super().__init__(content)
        self.status = status
        self.headers = {"Content-Type": kind, "Content-Length": str(len(content) if length is None else length)}

    def geturl(self):
        return "https://example.invalid/artifact"


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.destination = self.directory / "download"
        self.log = self.directory / "attempts.jsonl"

    def fetcher(self, responses, attempts=3):
        iterator = iter(responses)
        self.calls, self.sleeps = [], []
        def opener(request, timeout):
            self.calls.append((request.full_url, timeout))
            response = next(iterator)
            if isinstance(response, Exception): raise response
            return response
        return Fetcher(self.log, opener=opener, sleep=self.sleeps.append, attempts=attempts, timeout=1)

    def test_timeout_then_success_bounded_retry_and_log(self):
        f = self.fetcher([TimeoutError("secret must never log"), Response(b'{}')])
        f.download("https://example.invalid/data", self.destination, "json", "nhp")
        self.assertEqual(b'{}', self.destination.read_bytes())
        self.assertEqual([1], self.sleeps)
        self.assertEqual(2, len(self.calls))
        self.assertNotIn("secret", self.log.read_text())
        self.assertEqual(2, len(self.log.read_text().splitlines()))

    def test_http_429_retries_but_403_does_not(self):
        f = self.fetcher([urllib.error.HTTPError("https://example.invalid", 429, "secret", {}, None), Response(b'{}')])
        f.download("https://example.invalid/data", self.destination, "json", "nhp")
        self.assertEqual(2, len(self.calls))
        f = self.fetcher([urllib.error.HTTPError("https://example.invalid", 403, "secret", {}, None)])
        with self.assertRaisesRegex(AcquisitionError, "http_error"):
            f.download("https://example.invalid/data", self.destination, "json", "nhp")
        self.assertEqual(1, len(self.calls))
        self.assertFalse(self.destination.exists())
        self.assertNotIn("secret", self.log.read_text())

    def test_timeout_exhaustion_and_retry_limit(self):
        f = self.fetcher([TimeoutError()] * 3)
        with self.assertRaises(AcquisitionError): f.download("https://example.invalid/data", self.destination, "json", "nhp")
        self.assertEqual(3, len(self.calls))
        self.assertEqual([1, 2], self.sleeps)
        self.assertFalse(self.destination.exists())

    def test_html_bad_type_truncation_and_size_limit(self):
        for response, reason in [(Response(b'<html>Error</html>'), "html_masquerading_as_data"),
                                 (Response(b'{}', "text/html"), "unexpected_content_type"),
                                 (Response(b'{}', length=500), "truncated_download")]:
            f = self.fetcher([response], attempts=1)
            with self.assertRaisesRegex(AcquisitionError, reason):
                f.download("https://example.invalid/data", self.destination, "json", "nhp")
            self.assertFalse(self.destination.exists())
        f = self.fetcher([Response(b'12345')], attempts=1)
        f.max_bytes = 2
        with self.assertRaisesRegex(AcquisitionError, "download_size_limit"):
            f.download("https://example.invalid/data", self.destination, "json", "nhp")

    def test_credential_urls_are_never_requested_or_logged(self):
        f = self.fetcher([])
        for u in ("https://user:secret@example.invalid/data", "https://example.invalid/data?token=secret", "http://example.invalid/data"):
            with self.assertRaises(AcquisitionError): f.download(u, self.destination, "json", "nhp")
        self.assertFalse(self.calls)
        self.assertFalse(self.log.exists())


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.raw = geojson([feature("nhp", identifier="1"), feature("nhp", identifier="1"),
                            feature("nhp", identifier="1", Address_Original_First_Line="Different campus")])
        self.registry = {s["source_key"]: s for s in read_json(ROOT / "contracts/enrichment/source_registry.json")["sources"]}

    def fetcher(self, responses, stamp="2020-01-01T00:00:00Z"):
        iterator = iter(responses)
        def opener(request, timeout):
            value = next(iterator)
            if isinstance(value, Exception): raise value
            return value
        return Fetcher(self.directory / "attempts.jsonl", opener=opener, sleep=lambda _: None,
                       clock=lambda: stamp, attempts=1)

    def good(self):
        return self.fetcher([Response(landing(), "text/html"), Response(self.raw)])

    def saved(self):
        report = run(["nhp"], self.directory, fetcher=self.good())
        self.assertEqual("complete", report["status"])
        metrics = report["sources"]["nhp"]["coverage"]["by_facility_type"]["Hospital"]
        self.assertEqual(1, metrics["exact_duplicates_removed"])
        self.assertEqual(2, metrics["conflicting_variants"])
        return Path(report["sources"]["nhp"]["snapshot_directory"])

    def test_public_batch_hash_provenance_and_offline_replay(self):
        saved = self.saved()
        manifest = read_json(saved / "manifest.json")
        self.assertEqual(file_digest(saved / "raw.geojson"), manifest["snapshot"]["sha256"])
        self.assertEqual("nhp", manifest["snapshot"]["source_family"])
        self.assertEqual("shared_origin", manifest["snapshot"]["independence_status"])
        self.assertIsNone(manifest["snapshot"]["published_date"])
        self.assertEqual("2020-01-01", manifest["provenance"]["mirror_modified_date"])
        before = (saved / "batch.json").read_bytes()
        later = self.fetcher([], "2026-01-01T00:00:00Z")
        report = run(["nhp"], self.directory, replay=saved, fetcher=later)
        self.assertEqual("complete", report["status"])
        batch = Path(read_json(self.directory / "latest-run.json")["batch"])
        self.assertEqual(before, batch.read_bytes())
        self.assertEqual(before, (saved / "batch.json").read_bytes())
        self.assertEqual("2020-01-01T00:00:00Z", read_json(batch)["source_snapshots"][0]["retrieved_at"])
        self.assertEqual(2, len(read_json(batch)["external_facilities"]))

    def test_fresh_fetch_same_bytes_preserves_first_manifest_and_rows(self):
        saved = self.saved()
        original = {p.name: p.read_bytes() for p in saved.iterdir()}
        later = self.fetcher([Response(landing(), "text/html"), Response(self.raw)], "2026-01-01T00:00:00Z")
        report = run(["nhp"], self.directory, fetcher=later)
        self.assertEqual("complete", report["status"])
        self.assertEqual(original, {p.name: p.read_bytes() for p in saved.iterdir()})
        attempts = [json.loads(line) for line in (self.directory / "attempts.jsonl").read_text().splitlines()]
        self.assertEqual(4, len(attempts))
        self.assertEqual("2026-01-01T00:00:00Z", attempts[-1]["retrieved_at"])

    def test_failed_refresh_preserves_accepted_snapshot_and_pointer(self):
        saved = self.saved()
        original = {p.name: p.read_bytes() for p in saved.iterdir()}
        pointer = (self.directory / "nhp-latest.json").read_bytes()
        failures = [[TimeoutError()], [Response(b"Bad", status=500)],
                    [Response(landing(), "text/html"), Response(b"<html>Error</html>")],
                    [Response(landing(), "text/html"), Response(b'{"type":"FeatureCollection","features":[]}' )]]
        for responses in failures:
            report = run(["nhp"], self.directory, fetcher=self.fetcher(responses))
            self.assertEqual("partial_or_failed", report["status"])
            self.assertEqual(pointer, (self.directory / "nhp-latest.json").read_bytes())
            self.assertEqual(original, {p.name: p.read_bytes() for p in saved.iterdir()})
            failed = read_json(read_json(self.directory / "latest-run.json")["batch"])
            self.assertFalse(failed["source_snapshots"])
            self.assertEqual("acquisition_failed", failed["review_queue"][0]["reason_code"])

    def test_corrupted_replay_rejected(self):
        saved = self.saved()
        with (saved / "raw.geojson").open("ab") as f: f.write(b" ")
        report = run(["nhp"], self.directory, replay=saved, fetcher=self.fetcher([]))
        self.assertEqual("persisted_artifact_hash_mismatch", report["sources"]["nhp"]["reason"])

    def test_publication_date_only_explicit_field(self):
        f = self.fetcher([Response(landing(date="2019-02-03"), "text/html"), Response(self.raw)])
        report = run(["nhp"], self.directory, fetcher=f)
        saved = Path(report["sources"]["nhp"]["snapshot_directory"])
        self.assertEqual("2019-02-03", read_json(saved / "manifest.json")["snapshot"]["published_date"])

    def test_osm_metadata_geometry_and_unsafe_refresh(self):
        raw, meta = osm_archive([feature(identifier="relation/1")])
        entry = self.registry["hot_osm_health"]
        meta["assets"] = {"geojson": {"href": entry["related_urls"]["download"], "file:size": len(raw)}}
        def fetch(raw_value):
            return self.fetcher([Response(json.dumps(meta).encode()), Response(raw_value, "application/zip")])
        report = run(["osm"], self.directory, fetcher=fetch(raw))
        self.assertEqual("complete", report["status"])
        saved = Path(report["sources"]["osm"]["snapshot_directory"])
        manifest = read_json(saved / "manifest.json")
        self.assertEqual("2020-01-02", manifest["provenance"]["source_capture_date"])
        self.assertIsNone(manifest["snapshot"]["published_date"])
        pointer = (self.directory / "osm-latest.json").read_bytes()
        for invalid in (raw[:-10], osm_archive([feature()], {"../escape": "bad"})[0]):
            result = run(["osm"], self.directory, fetcher=fetch(invalid))
            self.assertEqual("partial_or_failed", result["status"])
            self.assertEqual(pointer, (self.directory / "osm-latest.json").read_bytes())
            self.assertEqual(raw, (saved / "raw.zip").read_bytes())
        verify_saved(saved, "osm")

    def test_all_continues_when_first_source_fails(self):
        f = self.fetcher([TimeoutError(), Response(landing(), "text/html"), Response(self.raw)])
        report = run(["osm", "nhp"], self.directory, fetcher=f)
        self.assertEqual("failed", report["sources"]["osm"]["status"])
        self.assertEqual("accepted", report["sources"]["nhp"]["status"])
        batch = read_json(read_json(self.directory / "latest-run.json")["batch"])
        self.assertEqual(1, len(batch["source_snapshots"]))
        self.assertEqual(2, len(batch["external_facilities"]))
        self.assertTrue(any(r["reason_code"] == "acquisition_failed" for r in batch["review_queue"]))


if __name__ == "__main__": unittest.main()
