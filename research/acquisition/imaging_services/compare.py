"""Run source-control and expanded retrieval over every original VF occurrence."""
from collections import Counter
import gzip
import json
from pathlib import Path

from research.acquisition.common import canonical, digest, file_digest
from research.matching.national import execute_national
from research.service_status.projection import project
from .collector import require


def frozen_reach(base, ledger_root, manifest_sha256, imaging_rows):
    """Compare reach to D's pinned joint trace; do not rerank or adjudicate."""
    from .collector import local
    root = Path(ledger_root)
    require(file_digest(root / "manifest.json") == manifest_sha256, "frozen manifest hash mismatch")
    manifest = json.loads((root / "manifest.json").read_text())
    loaded = {}
    for name, record in manifest["files"].items():
        path = local(root, name)
        require(path.stat().st_size == record["bytes"] and file_digest(path) == record["sha256"],
                "frozen file hash/length mismatch")
        if name.endswith(".jsonl.gz"):
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            require(len(rows) == record["records"], "frozen record count mismatch")
            if name in {"occurrences.jsonl.gz", "decisions.jsonl.gz"}:
                loaded[name] = rows
    occurrences, decisions = loaded["occurrences.jsonl.gz"], loaded["decisions.jsonl.gz"]
    require([r["original"] for r in occurrences] == base, "frozen original payload/order mismatch")
    originals = {r["facility_id"] for r in base}
    images = {r["facility_id"]: r for r in imaging_rows}
    require(len(images) == len(imaging_rows) and set(images) == originals, "imaging occurrence mismatch")
    keys = [(d["occurrence_key"], d["service"]) for d in decisions]
    expected = {(fid, service) for fid in originals for service in ("mri", "dialysis", "trauma_care")}
    require(len(keys) == len(expected) and set(keys) == expected, "frozen three-service product mismatch")
    by_state, overlay = {}, []
    outcomes = Counter()
    for occurrence in occurrences:
        fid = occurrence["original"]["facility_id"]
        joint = occurrence["joint_identity"]
        require(joint["facility_id"] == fid, "joint occurrence mismatch")
        outcome = joint["outcomes"]["joint"]
        require(outcome in {"unmatched", "candidate_only", "ambiguous", "confirmed"}, "unknown joint outcome")
        outcomes[outcome] += 1
        old_reach = outcome != "unmatched"
        imaging_reach = images[fid]["candidate_count"] > 0
        state = joint["state"]
        bucket = by_state.setdefault(state, Counter())
        for key, condition in (("original_rows", True), ("joint_any_candidate", old_reach),
                               ("imaging_any_candidate", imaging_reach), ("union_any_candidate", old_reach or imaging_reach),
                               ("newly_reached", imaging_reach and not old_reach)):
            bucket[key] += condition
        overlay.append(dict(facility_id=fid, state=state, joint_outcome=outcome,
                            imaging_candidate_count=images[fid]["candidate_count"],
                            newly_reached=imaging_reach and not old_reach))
    totals = {k: sum(s[k] for s in by_state.values()) for k in next(iter(by_state.values()))}
    return {"frozen_reach.json": dict(frozen_manifest_sha256=manifest_sha256,
                frozen_occurrences_sha256=manifest["files"]["occurrences.jsonl.gz"]["sha256"],
                joint_outcomes=dict(outcomes), **totals, by_state=by_state,
                unchanged_baseline_decisions=len(decisions),
                baseline_decision_statuses=dict(Counter(d["status"] for d in decisions)),
                service_status_transitions=0, confirmed_campus_gain=0,
                measure="Candidate-reach union only; no joint top-five reranking, new campus review, or service adjudication.",
                baseline_decision_dates=sorted({d["as_of"] for d in decisions})),
            "frozen_reach_rows.json": overlay}


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
