"""Synthetic packet transfer, provenance, privacy and tamper acceptance cases."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from research.acquisition.common import AcquisitionError, ROOT, canonical, file_digest, read_json, write_json
from research.acquisition.matching_handoff import archive, build, district_rows, verify
from research.acquisition.parsers import make_batch
from research.acquisition.rajasthan import write_extract
from research.acquisition.run import acquire
from fixtures import feature, geojson, landing, snapshot


class DistrictTests(unittest.TestCase):
    def test_first_locator_exact_duplicate_and_identifier_variants(self):
        a = feature(adm2_name="  Example District  ", adm2_pcode="001")
        b = feature(adm2_name="Other District", adm2_pcode="002", name="Other Campus")
        features = [a, copy.deepcopy(a), b]
        batch = make_batch(features, "health.geojson", snapshot(), "osm")[0]
        rows = district_rows(features, "health.geojson", snapshot(), "osm", batch)
        self.assertEqual(2, len(rows))
        self.assertEqual({"zip:health.geojson#/features/0", "zip:health.geojson#/features/2"}, {r["record_locator"] for r in rows})
        self.assertEqual({"  Example District  ", "Other District"}, {r["district_original"] for r in rows})

    def test_nhp_zero_missing_codes_and_contacts_never_copied(self):
        features = [feature("nhp", District="0", District_ID=0, Telephone="PRIVATE_SENTINEL", Mobile_Number="PRIVATE_SENTINEL"),
                    feature("nhp", identifier="2", District=" Example ", District_ID=42)]
        batch = make_batch(features, None, snapshot(), "nhp")[0]
        rows = district_rows(features, None, snapshot(), "nhp", batch)
        self.assertNotIn(b"PRIVATE_SENTINEL", canonical(rows))
        self.assertEqual({None, " Example "}, {r["district_original"] for r in rows})
        self.assertEqual({None, 42}, {r["district_code_original"] for r in rows})

    def test_wrong_out_of_range_and_negative_locators_rejected(self):
        features = [feature(adm2_name="Example")]
        batch = make_batch(features, None, snapshot(), "osm")[0]
        for locator in ("raw#/features/-1", "raw#/features/1", "zip:x#/features/0"):
            changed = copy.deepcopy(batch)
            changed["external_facilities"][0]["record_locator"] = locator
            with self.assertRaises(AcquisitionError): district_rows(features, None, snapshot(), "osm", changed)

    def test_wrong_feature_identity_rejected(self):
        features = [feature(adm2_name="Example")]
        batch = make_batch(features, None, snapshot(), "osm")[0]
        features[0]["properties"]["adm2_name"] = "Changed"
        with self.assertRaisesRegex(AcquisitionError, "district_feature_identity_mismatch"):
            district_rows(features, None, snapshot(), "osm", batch)


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source_output = self.root / "source"; source_output.mkdir()
        (source_output / ".staging").mkdir()
        raw = geojson([feature("nhp", State="Rajasthan", District="Example District", District_ID=42, Telephone="PRIVATE_SENTINEL"),
                       feature("nhp", identifier="2", State="0", District="0", Nodal_Person_Info="PRIVATE_SENTINEL")])
        class SyntheticFetcher:
            def download(self, url, destination, kind, source):
                destination.write_bytes(landing() if kind == "html" else raw)
                return {"retrieved_at": "2020-01-01T00:00:00Z"}
        entry = next(s for s in read_json(ROOT / "contracts/enrichment/source_registry.json")["sources"] if s["source_key"] == "nhp_hospitals_mirror")
        batch, _, directory, _ = acquire("nhp", source_output, entry, SyntheticFetcher())
        self.snapshot = Path(directory)
        self.national = self.root / "inputs" / "national.json"; write_json(self.national, batch)
        self.regional = self.root / "regional"
        write_extract([self.snapshot], self.national, self.regional)
        self.pins = self.root / "pins.json"
        pins = {}
        for name, path in {"national.json": self.national, "explicit.json": self.regional / "explicit.json",
                           "additional_review.json": self.regional / "additional_review.json"}.items():
            value = read_json(path)
            pins[name] = {"sha256": file_digest(path), **{table: len(value[table]) for table in ("external_facilities", "source_snapshots", "review_queue")}}
        write_json(self.pins, pins)
        self.output = self.root / "packet"

    def build(self):
        return build([self.snapshot], self.national, self.regional, self.output, self.pins)

    def test_build_transfer_replay_archive_and_no_input_changes(self):
        before = {p: p.read_bytes() for p in self.snapshot.iterdir()}
        result = self.build()
        self.assertEqual(result, self.build())
        self.assertEqual(before, {p: p.read_bytes() for p in self.snapshot.iterdir()})
        for path in self.output.iterdir(): self.assertNotIn(b"PRIVATE_SENTINEL", path.read_bytes())
        relocated = self.root / "relocated"; shutil.copytree(self.output, relocated)
        counts = verify(relocated, result["manifest_sha256"])
        self.assertEqual(2, counts["national.json"]["external_facilities"])
        self.assertEqual(self.national.read_bytes(), (relocated / "national.json").read_bytes())
        first, second = self.root / "one.zip", self.root / "two.zip"
        self.assertEqual(archive(self.output, first, result["manifest_sha256"]), archive(relocated, second, result["manifest_sha256"]))
        with zipfile.ZipFile(first) as stream:
            self.assertEqual({p.name for p in self.output.iterdir()}, set(stream.namelist()))
            self.assertEqual(self.national.read_bytes(), stream.read("national.json"))
        report = read_json(self.output / "coverage.json")
        self.assertEqual(1, report["coverage"]["national.json"]["nhp_hospitals_mirror"]["district_missing"])
        self.assertEqual(0, report["coverage"]["national.json"]["nhp_hospitals_mirror"]["explicit_institutional_switchboards"])

    def test_tampered_input_rejected_before_output(self):
        self.national.write_bytes(self.national.read_bytes() + b" ")
        with self.assertRaisesRegex(AcquisitionError, "accepted_input_hash_mismatch"): self.build()
        self.assertFalse(self.output.exists())

    def test_corrupt_raw_rejected_before_output(self):
        (self.snapshot / "raw.geojson").write_bytes(b"corrupt")
        with self.assertRaisesRegex(AcquisitionError, "persisted_artifact_hash_mismatch"): self.build()
        self.assertFalse(self.output.exists())

    def test_wrong_accepted_count_rejected(self):
        pins = read_json(self.pins); pins["national.json"]["external_facilities"] = 3; write_json(self.pins, pins)
        with self.assertRaisesRegex(AcquisitionError, "accepted_input_count_mismatch"): self.build()

    def test_existing_packet_corruption_not_overwritten(self):
        result = self.build(); target = self.output / "districts.json"; target.write_bytes(b"preserve")
        with self.assertRaisesRegex(AcquisitionError, "portable_file_hash_mismatch"): self.build()
        self.assertEqual(b"preserve", target.read_bytes())
        with self.assertRaises(AcquisitionError): verify(self.output, result["manifest_sha256"])

    def test_manifest_trust_anchor_and_extra_file_required(self):
        result = self.build()
        with self.assertRaisesRegex(AcquisitionError, "portable_manifest_hash_mismatch"): verify(self.output, "0" * 64)
        (self.output / "extra").write_text("unexpected")
        with self.assertRaisesRegex(AcquisitionError, "portable_file_set_mismatch"): verify(self.output, result["manifest_sha256"])

    def test_sidecar_wrong_reference_rejected_even_if_manifest_rehashed(self):
        self.build()
        rows = read_json(self.output / "districts.json"); rows["rows"][0]["record_locator"] = "raw#/features/99"
        write_json(self.output / "districts.json", rows)
        manifest = read_json(self.output / "manifest.json"); manifest["files"]["districts.json"] = file_digest(self.output / "districts.json")
        write_json(self.output / "manifest.json", manifest)
        with self.assertRaisesRegex(AcquisitionError, "district_sidecar_provenance_mismatch"):
            verify(self.output, file_digest(self.output / "manifest.json"))

    def test_different_archive_preserved(self):
        result = self.build(); destination = self.root / "packet.zip"; destination.write_bytes(b"preserve")
        with self.assertRaisesRegex(AcquisitionError, "existing_archive_not_identical"):
            archive(self.output, destination, result["manifest_sha256"])
        self.assertEqual(b"preserve", destination.read_bytes())


if __name__ == "__main__": unittest.main()
