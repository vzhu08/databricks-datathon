import json
import tempfile
import unittest
from pathlib import Path

from research.dialysis.release import compile_batch, digest, encode
from research.dialysis.replay_sources import read_fields, replay, source_claim


class SourceReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.originals = self.root / "originals"
        self.originals.mkdir()
        self.file = self.originals / "download.without-extension"
        self.file.write_text("<h1>Example Campus</h1><script>excluded</script><p>Example City</p>"
                             "<p>Planned   service.</p>", encoding="utf-8")
        self.source = dict(
            key="example", url="https://example.invalid/source", publisher="Example publisher",
            family="example", retrieved_at="2026-01-01T00:00:00Z",
            sha256=digest(self.file.read_bytes()), independence_status="unassessed", format="html",
            fields={"name": [0, 0, 14], "city": [1, 0, 12], "excerpt": [2, 0, 16]},
            name_format="{name}", identity_locator="Service paragraph under campus header",
        )
        self.rules = [dict(contains="planned", assertion="The source describes a proposal.",
                           kind="proposal", ownership="public", time_specific=False)]
        self.recipe = self.root / "recipe.json"

    def prepare_recipe(self):
        claim = source_claim(self.file, self.source, self.rules)
        metadata = self.source | {"path": self.file.name}
        manifest = self.originals / "test-only-manifest.json"
        manifest.write_bytes(encode({"sources": [metadata], "claims": [claim]}))
        batch, ledger = compile_batch(manifest)
        manifest.unlink()
        expected = {"batch.json": digest(encode(batch)), "claim_ledger.json": digest(encode(ledger))}
        self.recipe.write_bytes(encode({"format_version": 1, "release_sha256": expected,
                                        "interpretation_rules": self.rules, "sources": [self.source]}))
        return expected

    def test_rebuilds_and_verifies_existing_release_from_renamed_original(self):
        expected = self.prepare_recipe()
        self.file.rename(self.originals / "renamed")
        out = self.root / "release"
        self.assertEqual(replay(self.originals, self.recipe, out), expected)
        self.assertEqual(replay(self.originals, self.recipe, out), expected)
        batch = json.loads((out / "batch.json").read_bytes())
        self.assertEqual(batch["facility_evidence"][0]["excerpt"], "Planned service.")
        self.assertEqual(batch["external_facilities"][0]["name_original"], "Example Campus")
        self.assertEqual(digest((out / "batch.json").read_bytes()), expected["batch.json"])
        (out / "claim_ledger.json").write_bytes(b"mismatch")
        with self.assertRaisesRegex(ValueError, "Existing output differs"):
            replay(self.originals, self.recipe, out)

    def test_changed_source_or_selector_never_publishes(self):
        self.prepare_recipe()
        out = self.root / "release"
        original = self.file.read_bytes()
        self.file.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "Missing exact original"):
            replay(self.originals, self.recipe, out)
        self.file.write_bytes(original)
        spec = json.loads(self.recipe.read_bytes())
        spec["sources"][0]["fields"]["excerpt"][2] -= 1
        self.recipe.write_bytes(encode(spec))
        with self.assertRaisesRegex(ValueError, "differs from the frozen release"):
            replay(self.originals, self.recipe, out)
        self.assertFalse(out.exists())

    def test_rejects_invalid_views_or_overlapping_interpretations(self):
        for selector in ([2000, 0, 1], [1, -1, 2], [0, 10, 99], [-1, 0, 1]):
            source = self.source | {"fields": {"name": selector}}
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                read_fields(self.file, source)
        for rules in ([], self.rules * 2):
            with self.subTest(rules=rules), self.assertRaisesRegex(ValueError, "single frozen interpretation"):
                source_claim(self.file, self.source, rules)
