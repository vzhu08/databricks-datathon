"""Entirely synthetic documents, campuses, populations, and review receipts."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from research.acquisition.cghs.collector import compile_collection, run, validity
from research.acquisition.common import AcquisitionError, canonical, digest


def location(row, section="main", page=1):
    return {"page": page, "table": 1, "section": section, "row": str(row)}


def campus(number=1, **changes):
    return {"locator": location(number), "name_raw": "Synthetic Example Campus",
            "address_raw": "Example Lane, Synthetic City", "city": "Synthetic City", "state": "Synthetic State",
            "kind": "campus", "institution_type": "hospital", "scope_raw": "Synthetic scheme scope only",
            "validity_raw": "01.01.2025 to 31.12.2027", **changes}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sequence = 0

    def source(self, rows=None, **changes):
        self.sequence += 1
        n = self.sequence
        raw = f"SYNTHETIC SOURCE DOCUMENT {n}; never a real CGHS row.\n".encode()
        raw_sha = digest(raw)
        extracted = {"raw_sha256": raw_sha, "review_status": "producer_checked", "reviewer": "synthetic-reviewer",
                     "rows": rows if rows is not None else [campus()]}
        rows_bytes = canonical(extracted)
        (self.root / f"source-{n}.txt").write_bytes(raw)
        (self.root / f"rows-{n}.json").write_bytes(rows_bytes)
        return {"source_key": "synthetic_cghs", "source_family": "cghs_empanelment", "publisher": "Synthetic Publisher",
                "issuer": "Synthetic Issuer A", "series_key": "synthetic-directory",
                "eligible_population": "Synthetic employees", "coverage_scope": "Synthetic jurisdiction",
                "url": f"https://example.org/synthetic-source-{n}.pdf", "retrieved_at": "2026-11-01T00:00:00Z",
                "document_date": "2026-10-01", "sha256": raw_sha, "raw_file": f"source-{n}.txt",
                "rows_file": f"rows-{n}.json", "rows_sha256": digest(rows_bytes),
                "reuse": {"status": "permitted", "reason": "Invented test content", "third_party_rights": "cleared",
                          "license": "Synthetic fixture only", "attribution": "Synthetic fixture author"}, **changes}

    def compile(self, *sources, as_of="2026-11-21"):
        return compile_collection({"manifest_version": "1.0.0", "as_of": as_of, "sources": list(sources)}, self.root)

    def test_groups_children_repeated_scopes_and_bilingual_rows(self):
        source = self.source([
            campus(1, kind="group_summary", name_raw="Synthetic Umbrella", address_raw=None, city=None, state=None),
            campus(2, parent_locator=location(1), scope_raw="Synthetic eye scope"),
            campus(3, parent_locator=location(1), scope_raw="Synthetic dental scope"),
            campus(4, kind="multi_campus_group", name_raw="Synthetic Network", branch_labels=["Example East", "Example West"]),
            campus(5, representation_of=location(2), representation_reason="Synthetic duplicate language representation",
                   name_raw="Synthetic translated label"),
        ])
        result = self.compile(source)
        report = result["report.json"]
        self.assertEqual((report["selected_campus_observations"], report["selected_group_records"],
                          report["selected_duplicate_representations"]), (2, 2, 1))
        self.assertEqual(report["selected_snapshot_observations"], 5)
        self.assertEqual(len(result["repeated_identity_groups.json"]), 1)
        self.assertEqual(len(result["repeated_identity_groups.json"][0]["record_ids"]), 2)
        self.assertEqual(sum(x["rows"] for x in report["by_issuer_city_state_kind"]), 5)
        self.assertTrue(any(x["city"] == "Unknown" for x in report["by_issuer_city_state_kind"]))
        self.assertEqual(len(result["batch.json"]["external_facilities"]), 2)
        self.assertTrue(all("repeated_name_address_preserved" in r["quality_flags"] for r in result["batch.json"]["external_facilities"]))

    def test_same_name_different_campuses_are_not_collapsed(self):
        result = self.compile(self.source([campus(1), campus(2, address_raw="Another Synthetic Street")]))
        self.assertEqual(len(result["batch.json"]["external_facilities"]), 2)
        self.assertEqual(result["repeated_identity_groups.json"], [])

    def test_snapshot_selection_is_per_issuer_population_and_scope(self):
        old = self.source(document_date="2025-01-01", retrieved_at="2026-11-21T00:00:00Z")
        new = self.source(document_date="2026-01-01", retrieved_at="2026-02-01T00:00:00Z")
        issuer = self.source(issuer="Synthetic Issuer B", document_date="2024-01-01")
        population = self.source(eligible_population="Different synthetic beneficiaries", document_date="2023-01-01")
        scope = self.source(coverage_scope="Other synthetic jurisdiction", document_date="2022-01-01")
        result = self.compile(old, new, issuer, population, scope)
        self.assertEqual(result["report.json"]["retained_snapshot_observations"], 5)
        self.assertEqual(result["report.json"]["selected_campus_observations"], 4)
        selected = {s["sha256"] for s in result["batch.json"]["source_snapshots"]}
        self.assertNotIn(old["sha256"], selected)
        self.assertEqual(selected, {s["sha256"] for s in (new, issuer, population, scope)})

    def test_same_date_variants_are_unresolved_until_explicitly_selected(self):
        a, b = self.source(), self.source()
        result = self.compile(a, b)
        self.assertEqual(result["report.json"]["unresolved_snapshot_series"], 1)
        self.assertEqual(result["batch.json"]["external_facilities"], [])
        self.assertEqual(len(result["observations.json"]), 2)
        a.update(selected=True, selection_reason="Synthetic reviewer selected this documented variant")
        selected = self.compile(a, b)
        self.assertEqual(selected["batch.json"]["source_snapshots"][0]["sha256"], a["sha256"])
        b.update(selected=True, selection_reason="Conflicting synthetic selection")
        with self.assertRaisesRegex(AcquisitionError, "multiple_explicit"):
            self.compile(a, b)

    def test_historical_cutoff_retains_future_edition_but_selects_eligible_revision(self):
        august = self.source(document_date="2026-08-01")
        november = self.source(document_date="2026-11-01")
        result = self.compile(august, november, as_of="2026-10-01")
        self.assertEqual([s["sha256"] for s in result["batch.json"]["source_snapshots"]], [august["sha256"]])
        self.assertEqual(len(result["source_inventory.json"]), 2)
        self.assertEqual(len(result["observations.json"]), 2)
        future = next(r for r in result["observations.json"] if r["document_date"] == "2026-11-01")
        self.assertFalse(future["selected_snapshot"])
        selection = result["snapshot_selection.json"][0]
        self.assertEqual(selection["future_snapshot_ids"], [future["snapshot_id"]])
        self.assertEqual(result["report.json"]["future_dated_permitted_snapshots"], 1)
        later = self.compile(august, november, as_of="2026-11-01")
        self.assertEqual([s["sha256"] for s in later["batch.json"]["source_snapshots"]], [november["sha256"]])
        self.assertEqual(later["report.json"]["future_dated_permitted_snapshots"], 0)

    def test_future_only_series_produces_review_without_campus_candidates(self):
        result = self.compile(self.source(document_date="2026-11-01"), as_of="2026-10-01")
        self.assertEqual(result["batch.json"]["source_snapshots"], [])
        self.assertEqual(result["batch.json"]["external_facilities"], [])
        self.assertEqual(len(result["observations.json"]), 1)
        self.assertEqual(result["snapshot_selection.json"][0]["reason"], "no_snapshot_on_or_before_as_of")
        self.assertEqual(result["report.json"]["unresolved_snapshot_series"], 1)

    def test_manual_selection_cannot_override_historical_cutoff(self):
        future = self.source(document_date="2026-11-01", selected=True, selection_reason="Synthetic explicit choice")
        with self.assertRaisesRegex(AcquisitionError, "cannot_select_future_snapshot"):
            self.compile(future, as_of="2026-10-01")

    def test_cutoff_includes_same_day_and_preserves_tie_and_unknown_date_rules(self):
        older = self.source(document_date="2026-08-01")
        boundary = self.source(document_date="2026-10-01")
        future = self.source(document_date="2026-11-01")
        result = self.compile(older, boundary, future, as_of="2026-10-01")
        self.assertEqual(result["batch.json"]["source_snapshots"][0]["sha256"], boundary["sha256"])
        variant = self.source(document_date="2026-10-01")
        tied = self.compile(older, boundary, variant, future, as_of="2026-10-01")
        self.assertEqual(tied["snapshot_selection.json"][0]["reason"], "same_date_variants_require_selection")
        unknown = self.source(document_date=None)
        undated = self.compile(boundary, unknown, future, as_of="2026-10-01")
        self.assertEqual(undated["snapshot_selection.json"][0]["reason"], "undated_snapshot_requires_selection")

    def test_undated_snapshot_never_uses_retrieval_date_as_freshness(self):
        a = self.source(document_date="2026-10-01")
        b = self.source(document_date=None, retrieved_at="2026-11-21T18:00:00Z")
        result = self.compile(a, b)
        self.assertEqual(result["snapshot_selection.json"][0]["reason"], "undated_snapshot_requires_selection")
        self.assertEqual(result["batch.json"]["external_facilities"], [])
        b.update(selected=True, selection_reason="Synthetic explicit selection of undated document")
        selected = self.compile(a, b)
        self.assertIsNone(selected["batch.json"]["source_snapshots"][0]["published_date"])

    def test_held_sources_are_not_opened_or_selected(self):
        allowed = self.source(document_date="2025-01-01")
        held = self.source(document_date="2026-01-01")
        held["reuse"].update(status="hold", reason="Synthetic permission unresolved")
        rejected = self.source(issuer="Synthetic Issuer B")
        rejected["reuse"].update(status="rejected", reason="Synthetic mixed population")
        for source in (held, rejected):
            (self.root / source["raw_file"]).unlink()
            (self.root / source["rows_file"]).unlink()
        result = self.compile(allowed, held, rejected)
        self.assertEqual(result["report.json"]["source_dispositions"], {"parsed": 1, "held": 1, "rejected": 1})
        self.assertEqual(len(result["observations.json"]), 1)
        self.assertEqual(result["batch.json"]["source_snapshots"][0]["sha256"], allowed["sha256"])
        held.update(selected=True, selection_reason="Should fail")
        with self.assertRaisesRegex(AcquisitionError, "cannot_select_held"):
            self.compile(allowed, held)

    def test_document_third_party_hold_and_row_hold_do_not_export_content(self):
        held = self.source([campus(name_raw="DO NOT EXPORT SOURCE")])
        held["reuse"]["third_party_rights"] = "unresolved"
        source = self.source([campus(1), campus(2, rights="unresolved", name_raw="DO NOT EXPORT ROW")])
        result = self.compile(held, source)
        serialized = canonical(result).decode()
        self.assertNotIn("DO NOT EXPORT", serialized)
        self.assertEqual(result["report.json"]["held_rows"], 1)
        self.assertEqual(len(result["held_rows.json"]), 1)
        self.assertEqual(result["report.json"]["selected_campus_observations"], 1)

    def test_missing_identity_and_invalid_pin_are_retained_as_unknown(self):
        result = self.compile(self.source([campus(name_raw=None, city=None, state=None, pin="000XYZ")]))
        row = result["batch.json"]["external_facilities"][0]
        self.assertIsNone(row["name_original"])
        self.assertIsNone(row["name_normalized"])
        self.assertIsNone(row["pin"])
        self.assertIn("invalid_pin", row["quality_flags"])
        self.assertEqual(result["observations.json"][0]["pin"], "000XYZ")
        self.assertEqual(result["report.json"]["by_issuer_city_state_kind"][0]["state"], "Unknown")

    def test_scheme_id_requires_namespace_and_never_uses_printed_serial(self):
        plain = self.compile(self.source())
        self.assertIsNone(plain["batch.json"]["external_facilities"][0]["source_record_id"])
        scoped = self.compile(self.source([campus(scheme_id="synthetic-001", scheme_id_namespace="synthetic_hco")]))
        self.assertEqual(scoped["batch.json"]["external_facilities"][0]["source_record_id"], "synthetic_hco:synthetic-001")
        with self.assertRaisesRegex(AcquisitionError, "scheme_id_namespace_required"):
            self.compile(self.source([campus(scheme_id="1")]))

    def test_events_and_scope_do_not_emit_clinical_confirmation(self):
        event = {"kind": "suspension", "excerpt": "Synthetic scheme suspension", "effective_date": "2025-06-01", "authority": "Synthetic authority"}
        source = self.source([campus(scope_raw="Synthetic scheme suspension; MRI and dialysis words", events=[event])])
        result = self.compile(source)
        self.assertEqual(result["batch.json"]["facility_evidence"], [])
        self.assertEqual(result["batch.json"]["facility_matches"], [])
        row = result["observations.json"][0]
        self.assertEqual(row["events"], [event])
        self.assertEqual(set(row["clinical_service_status"].values()), {"unconfirmed"})
        self.assertEqual(row["live_availability"], "unknown")
        self.assertIsNone(result["report.json"]["vf_overlap"])
        self.assertEqual(result["report.json"]["national_target_rows"], 10088)
        event["excerpt"] = "Not present in the source cell"
        with self.assertRaisesRegex(AcquisitionError, "event_excerpt_not_in_row"):
            self.compile(self.source([campus(events=[event])]))

    def test_validity_episodes_and_malformed_dates_remain_distinct(self):
        episodes, flags = validity("01.01.2025 to 31.12.2025; 01/01/2026 to 31/12/2026")
        self.assertEqual(len(episodes), 2)
        self.assertIn("multiple_validity_episodes", flags)
        episodes, flags = validity("01.01.2025 to 31.12.2025\n01.01.2025 to 31.12.2025")
        self.assertEqual(len(episodes), 2)
        self.assertIn("repeated_printed_validity_interval", flags)
        for raw in ("01.01.2025 to 31,12.2025", "31.02.2025 to 01.03.2025", "31.12.2025 to 01.01.2025", "2025", "01.01.2025 or 02.01.2025"):
            with self.subTest(raw=raw):
                self.assertEqual(validity(raw), ([], ["validity_needs_review"]))

    def test_excluded_or_suspended_periods_are_held_with_exact_wording(self):
        for raw in (
            "Valid 01.01.2026 to 31.12.2026 except 01.03.2026 to 31.03.2026",
            "Suspended from 01.03.2026 to 31.03.2026",
            "Not valid 01.03.2026 to 31.03.2026",
            "Valid 01.01.2026 to 31.12.2026 subject to renewal",
        ):
            with self.subTest(raw=raw):
                result = self.compile(self.source([campus(validity_raw=raw)]))
                row = result["observations.json"][0]
                self.assertEqual(row["validity_raw"], raw)
                self.assertEqual(row["validity_episodes"], [])
                self.assertIn("validity_needs_review", row["quality_flags"])
                self.assertTrue(any(r["reason_code"] == "validity_needs_review" for r in result["batch.json"]["review_queue"]))

    def test_plain_positive_validity_labels_and_multiple_periods_still_parse(self):
        for raw in ("Valid 01.01.2026 to 31.12.2026", "Validity: 01/01/2026 to 31/12/2026",
                    "Validity period from 01-01-2026 until 31-12-2026."):
            with self.subTest(raw=raw):
                self.assertEqual(validity(raw), ([{"valid_from": "2026-01-01", "valid_to": "2026-12-31"}], []))
        episodes, flags = validity("Valid 01.01.2025 to 31.12.2025; valid from 01.01.2026 to 31.12.2026")
        self.assertEqual(len(episodes), 2)
        self.assertEqual(flags, ["multiple_validity_episodes"])

    def test_invalid_group_links_duplicate_locators_and_representation_cycles_fail(self):
        cases = [
            [campus(parent_locator=location(9))],
            [campus(1), campus(2, parent_locator=location(1))],
            [campus(1), campus(1, scope_raw="Conflicting variant")],
            [campus(1, representation_of=location(2), representation_reason="Synthetic"),
             campus(2, representation_of=location(1), representation_reason="Synthetic")],
            [campus(1, kind="group_summary", parent_locator=location(1))],
            [campus(1, branch_labels=["Synthetic East"])],
        ]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(AcquisitionError):
                self.compile(self.source(rows))

    def test_duplicate_snapshot_receipts_and_tampered_capture_fail(self):
        source = self.source()
        with self.assertRaisesRegex(AcquisitionError, "duplicate_snapshot_receipt"):
            self.compile(source, source)
        (self.root / source["raw_file"]).write_text("Changed synthetic document")
        with self.assertRaisesRegex(AcquisitionError, "raw_hash_mismatch"):
            self.compile(source)

    def test_tampered_extraction_or_binding_fails(self):
        source = self.source()
        path = self.root / source["rows_file"]
        path.write_text('{"rows":[]}')
        with self.assertRaisesRegex(AcquisitionError, "extraction_hash_mismatch"):
            self.compile(source)
        source["rows_sha256"] = digest(path.read_bytes())
        with self.assertRaisesRegex(AcquisitionError, "extraction_source_mismatch"):
            self.compile(source)

    def test_invalid_dates_timezones_and_paths_fail(self):
        source = self.source()
        for change in ({"document_date": "2026-02-30"}, {"retrieved_at": "2026-01-01T00:00:00+05:30"},
                       {"raw_file": "../escape"}, {"raw_file": "C:\\example\\source"},
                       {"url": "https://user:secret@example.org/source"}, {"selected": "yes"}):
            with self.subTest(change=change), self.assertRaises(AcquisitionError):
                self.compile({**source, **change})

    def test_input_order_does_not_change_outputs(self):
        a = self.source(issuer="Synthetic A")
        b = self.source(issuer="Synthetic B")
        self.assertEqual(canonical(self.compile(a, b)), canonical(self.compile(b, a)))

    def test_replay_is_identical_and_never_overwrites_conflicting_output(self):
        source = self.source()
        manifest = self.root / "manifest.json"
        manifest.write_bytes(canonical({"manifest_version": "1.0.0", "as_of": "2026-11-21", "sources": [source]}))
        first, second = self.root / "release-one", self.root / "release-two"
        hashes = run(manifest, first)
        self.assertEqual(hashes, run(manifest, first))
        self.assertEqual(hashes, run(manifest, second))
        self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()}, {p.name: p.read_bytes() for p in second.iterdir()})
        (first / "unexpected.txt").write_text("Do not overwrite me")
        with self.assertRaisesRegex(AcquisitionError, "existing_cghs_release_differs"):
            run(manifest, first)
        self.assertEqual((first / "unexpected.txt").read_text(), "Do not overwrite me")

    def test_generated_envelope_passes_independent_databricks_checks(self):
        # The shared validator uses script-local imports. Isolate its common module.
        root = Path(__file__).resolve().parents[4]
        module_dir = root / "databricks/enrichment"
        prior = sys.modules.pop("common", None)
        sys.path.insert(0, str(module_dir))
        try:
            spec = importlib.util.spec_from_file_location("cghs_independent_validation", module_dir / "validation.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            batch = self.compile(self.source([campus(1), campus(2, kind="multi_campus_group")]))["batch.json"]
            module.semantic_check(batch, [])
        finally:
            sys.path.pop(0)
            sys.modules.pop("common", None)
            if prior is not None:
                sys.modules["common"] = prior


if __name__ == "__main__":
    unittest.main()
