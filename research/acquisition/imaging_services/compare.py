"""Run source-control and expanded retrieval over every original VF occurrence."""
from collections import Counter
import json
from pathlib import Path

from research.acquisition.common import canonical, digest, file_digest
from research.matching.national import execute_national
from research.service_status.projection import project
from .collector import require


def compare(base, metadata, base_sha256, control, additions, as_of, expected_rows=10088,
            expected_ids=10077, expected_pairs=11):
    require(len(base) == expected_rows, "wrong original-row denominator")
    id_field = metadata["mapping"]["id"]
    require(len({r["source_row"][id_field] for r in base}) == expected_ids, "wrong upstream-ID denominator")
    args = dict(source_metadata=metadata, base_file_sha256=base_sha256,
                expect_duplicate_groups=expected_pairs)
    before = execute_national(base, control, **args)
    after = execute_national(base, control + additions, **args)
    require(all(g["multiplicity"] == 2 for g in after["duplicate_groups"]), "expected identical pairs")
    old = {r["facility_id"]: r for r in before["base_rows"]}
    new = {r["facility_id"]: r for r in after["base_rows"]}
    require(set(old) == set(new) == {r["facility_id"] for r in base}, "lost original occurrence")
    # No clinical adjudication is performed by retrieval. Do not mark sources as
    # clinically checked when this lane has supplied only unresolved observations.
    services = project(base, metadata, [], control + additions, as_of=as_of,
                       base_file_sha256=base_sha256, checked_sources=[],
                       identity_rows=after["base_rows"], identity_report=after["national_report"])
    by_state = {}
    for row in after["base_rows"]:
        bucket = by_state.setdefault(row["state"], Counter())
        bucket["original_rows"] += 1
        bucket["control_any_candidate"] += bool(old[row["facility_id"]]["candidate_count"])
        bucket["expanded_any_candidate"] += bool(row["candidate_count"])
        bucket["newly_retrieved_occurrences"] += bool(row["candidate_count"] and not old[row["facility_id"]]["candidate_count"])
        bucket["expanded_conflict_occurrences"] += bool(row["conflicts"])
    summary = dict(
        scope="All original VF occurrences; control is the supplied source batches, not the frozen #147 release",
        base_file_sha256=base_sha256, original_occurrences=len(base), distinct_upstream_ids=expected_ids,
        identical_pairs=expected_pairs, service_decisions=services["decision_count"],
        control=before["national_report"]["outcomes"], expanded=after["national_report"]["outcomes"],
        newly_retrieved_occurrences=sum(x["newly_retrieved_occurrences"] for x in by_state.values()),
        by_state=by_state, service_coverage=services["coverage"],
        service_coverage_by_state=services["coverage_by_state"],
        confirmed_service_gain=0, reviewed_campus_service_pairs=0, independent_accuracy=None,
        frozen_147_incremental_gain=None,
        frozen_147_blocker="Pinned occurrence-level #147 trace and authenticated Databricks access not supplied",
        control_batch_hashes=[digest(canonical(x)) for x in control],
        addition_batch_hashes=[digest(canonical(x)) for x in additions],
        limitation="Candidate gain is retrieval only. Empty clinical review ledger leaves all three decisions unconfirmed; it is not a completed clinical evidence review.")
    return {"comparison.json": summary, "control_report.json": before["national_report"],
            "expanded_report.json": after["national_report"], "control_rows.json": before["base_rows"],
            "expanded_rows.json": after["base_rows"], "expanded_candidates.json": after["candidates"],
            "service_projection.json": services, "duplicate_groups.json": after["duplicate_groups"]}


def reconcile_legacy(root, current_manifest=None):
    """Audit retained HLL editions without importing the unmerged #81 adapter."""
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    batch_path, ledger_path = root / "release-final/batch.json", root / "release-final/claim_ledger.json"
    batch, ledger = json.loads(batch_path.read_text()), json.loads(ledger_path.read_text())
    require(not batch["facility_matches"], "legacy matches need separate review")
    require(all(e["facility_id"] is None and e["polarity"] == "inconclusive" for e in batch["facility_evidence"]),
            "legacy evidence must remain unresolved")
    from .collector import local
    raw = {s["sha256"]: s for s in manifest["sources"] if s.get("status") == "ok" and s.get("sha256")}
    for snapshot in batch["source_snapshots"]:
        source = raw[snapshot["sha256"]]
        require(source["key"] not in {"installed_tender", "proposed_tender"}, "held tender cannot be used")
        require(file_digest(local(root, source["path"])) == snapshot["sha256"], "legacy source hash mismatch")
    documentary = [r for r in ledger if r["kind"] != "directory_identity"]
    directory = [r for r in ledger if r["kind"] == "directory_identity"]
    require(len(ledger) == len(batch["external_facilities"]), "legacy ledger/identity count mismatch")
    latest_mri = [r for r in documentary if r["source"] == "annual_report" and r["kind"] in {"named_mri_service", "mri_date_conflict"}]
    edition_comparison = []
    if current_manifest is not None:
        from bs4 import BeautifulSoup
        from .collector import checked_source, norm

        def visible_text(raw_bytes):
            soup = BeautifulSoup(raw_bytes, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            return norm(soup.get_text(" ", strip=True))

        current_path = Path(current_manifest)
        for new in json.loads(current_path.read_text())["sources"]:
            if new["status"] != "ok" or new["source_family"] != "hll_hindlabs":
                continue
            new_path = checked_source(current_path.parent, new)
            for prior in manifest["sources"]:
                if prior.get("status") == "ok" and prior["url"] == new["url"]:
                    prior_path = local(root, prior["path"])
                    require(file_digest(prior_path) == prior["sha256"], "prior capture hash mismatch")
                    edition_comparison.append(dict(url=new["url"], prior_sha256=prior["sha256"],
                        new_sha256=new["sha256"], raw_bytes_equal=prior["sha256"] == new["sha256"],
                        normalized_visible_text_equal=visible_text(prior_path.read_bytes()) == visible_text(new_path.read_bytes()),
                        independence="same operator origin; no new independent verification"))
    return dict(directory_nodes=len(directory), documentary_observations=len(documentary),
                retained_unlinked_identities=len(batch["external_facilities"]),
                latest_report_named_mri_unit_keys=len({r["unit_key"] for r in latest_mri}),
                latest_report_mri_by_kind=dict(Counter(r["kind"] for r in latest_mri)),
                documentary_by_kind=dict(Counter(r["kind"] for r in documentary)),
                documentary_by_source=dict(Counter(r["source"] for r in documentary)),
                unique_documentary_unit_keys=len({r["unit_key"] for r in documentary if r["unit_key"]}),
                claimed_independent_origins=None, known_publisher_families=1,
                source_snapshot_hashes_verified=len(batch["source_snapshots"]),
                refreshed_editions=edition_comparison,
                batch_sha256=file_digest(batch_path), ledger_sha256=file_digest(ledger_path),
                status="Retained private #75 corpus; no #81 correction or current availability claim.")
