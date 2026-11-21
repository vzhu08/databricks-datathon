"""V1 identity/accreditation output plus a lossless typed episode ledger."""
from collections import Counter
from pathlib import Path

from .common import FAMILY, VERSION, canonical, identity, read, require, sha
from .episodes import episode, relate, sample
from .tables import POLICY, page_rows

TABLES = ("source_snapshots", "external_facilities", "facility_matches", "facility_evidence", "review_queue")


def checked_raw(root, document):
    path = (Path(root) / document["artifact"]).resolve()
    require(path.is_relative_to(Path(root).resolve()), "artifact_path_escape")
    raw = path.read_bytes()
    require(sha(raw) == document["sha256"] and len(raw) == document["bytes"], "raw_artifact_hash_mismatch")
    return raw


def build(root, as_of):
    root = Path(root)
    capture = read(root / "capture.json")
    require(capture["capture_version"] == "1.0.0", "unknown_capture_version")
    for document in capture["documents"].values():
        checked_raw(root, document)
    batch = {"contract_version": "1.0.0", **{table: [] for table in TABLES}}
    ledger = []
    snapshots = {}
    for mode in ("full", "partial"):
        view = capture["views"].get(mode, {"pages": [], "row_count": 0})
        count = 0
        for number, key in enumerate(view["pages"]):
            document = capture["documents"][key]
            rows, _ = page_rows(checked_raw(root, document), document["url"], mode, number)
            count += len(rows)
            sid = "nqas-qps:" + document["sha256"]
            snapshots[sid] = {
                "snapshot_id": sid, "source_key": "nqas_qps_" + mode,
                "publisher": "National Health Systems Resource Centre / National Health Mission",
                "source_family": FAMILY, "url": document["url"], "retrieved_at": document["retrieved_at"],
                "published_date": None, "license": "NHSRC website copyright policy; accurate attributed reuse; third-party exception: " + POLICY,
                "attribution": "NHSRC, Ministry of Health & Family Welfare, Government of India; NQAS programme. QPS and certificate register are one family.",
                "sha256": document["sha256"], "artifact_uri": (root / document["artifact"]).resolve().as_uri(),
                "parser_version": VERSION, "independence_status": "shared_origin",
            }
            for row in rows:
                item = episode(row, document, as_of)
                ext_id = identity("nqas-external", document["sha256"], item["episode_id"], row["row_index"])
                item.update(snapshot_id=sid, external_facility_id=ext_id)
                batch["external_facilities"].append({
                    "external_facility_id": ext_id, "snapshot_id": sid, "source_record_id": row["nin"],
                    "record_locator": item["source_locator"], "name_original": row["facility"],
                    "name_normalized": row["facility"].casefold(), "address_original": None,
                    "facility_type": row["category"] or "unknown", "city": None, "state": row["state"],
                    "pin": None, "latitude": None, "longitude": None, "coordinate_method": None,
                    "quality_flags": sorted(set(["held_out_nqas_audit", "district_is_not_city", "coordinates_not_exposed"] + item["review_reasons"])),
                })
                evidence_id = None
                # Invalid dates/intervals and ambiguity spanning the assessment date
                # remain in the ledger: v1 has no explicit ambiguous-interval type.
                acceptable = item["interval_coherent"] and all(item[k]["status"] != "invalid" for k in ("start", "end"))
                exact_end = item["end"]["iso"]
                exact_start = item["start"]["iso"]
                if exact_end and exact_end < as_of and acceptable:
                    temporal = "expired"
                elif item["expiration"] == "expired_under_all_parses" and acceptable:
                    temporal = "historical"
                elif exact_start and item["end"]["status"] in {"exact", "missing"} and acceptable:
                    temporal = "dated"
                elif item["start"]["status"] == item["end"]["status"] == "missing":
                    temporal = "undated"
                else:
                    temporal = None
                item["v1_evidence_withheld_reason"] = None if temporal else "v1_cannot_express_unresolved_interval_without_misleading_temporal_label"
                if temporal:
                    evidence_id = identity("nqas-evidence", sid, item["episode_id"], row["row_index"],
                                           temporal, exact_start, exact_end)
                    batch["facility_evidence"].append({
                        "evidence_id": evidence_id, "external_facility_id": ext_id, "snapshot_id": sid,
                        "facility_id": None, "match_id": None, "claim_type": "accreditation", "service": None,
                        "polarity": "supports", "assertion": "NHSRC QPS " + mode + "-facility table lists this named facility for the printed department scope and validity fields " +
                            row["valid_from_raw"] + " to " + row["valid_until_raw"] + ". Ambiguous dates remain unresolved in the episode ledger. This is programme-specific documentary certification, not NABH, clinical capability or live availability.",
                        "excerpt": row["original_cells"][4], "observation": None, "locator": item["source_locator"],
                        "source_url": row["source_url"], "effective_date": exact_start, "valid_until": exact_end,
                        "temporal_status": temporal, "reviewer": None, "reviewed_at": None,
                    })
                item["evidence_id"] = evidence_id
                batch["review_queue"].append({
                    "review_id": identity("nqas-review", ext_id, evidence_id), "facility_id": None, "external_facility_id": ext_id,
                    "evidence_id": evidence_id, "match_id": None, "reason_code": "held_out_certification_review",
                    "severity": "medium", "status": "open", "resolution": None,
                    "next_action": "Reserve for the blinded NQAS audit after predictions are frozen. Verify campus/NIN, department scope and unresolved original dates; do not use as a matching feature or clinical service claim.",
                })
                ledger.append(item)
        require(count == view["row_count"], "capture_row_count_changed")
    batch["source_snapshots"] = list(snapshots.values())
    id_fields = ("snapshot_id", "external_facility_id", "match_id", "evidence_id", "review_id")
    for table, key in zip(TABLES, id_fields):
        batch[table].sort(key=lambda r: r[key])
        require(len({r[key] for r in batch[table]}) == len(batch[table]), "duplicate_batch_id")
    ledger.sort(key=lambda e: (e["episode_id"], e["source_locator"]))
    relations = relate(ledger)
    selected = sample(ledger)
    report = {
        "as_of": as_of, "source_family": FAMILY, "intended_use": "held_out_accreditation_audit",
        "excluded_from_matching_features": True, "not_nabh": True, "no_clinical_service_claims": True,
        "table_counts": {table: len(batch[table]) for table in TABLES},
        "qps_views": capture["views"], "blockers": capture["blockers"],
        "public_export_links": capture.get("controls", {}).get("public_export_links", []),
        "coverage_denominator": "Accessible Rajasthan QPS full/partial table rows, not all Rajasthan facilities or current programme coverage",
        "episode_rows": len(ledger), "by_mode": dict(Counter(e["mode"] for e in ledger)),
        "by_district": dict(sorted(Counter(e["district"] or "unknown" for e in ledger).items())),
        "by_expiration": dict(Counter(e["expiration"] for e in ledger)),
        "date_status": {field: dict(Counter(e[field]["status"] for e in ledger)) for field in ("start", "end")},
        "nin_missing": sum(e["nin"] is None for e in ledger), "category_missing": sum(e["category"] is None for e in ledger),
        "publication_dates_unknown": len(snapshots), "verified_identifier_relations": len(relations["verified_identifier_relations"]),
        "identifier_conflicts": len(relations["identifier_conflicts"]),
        "repeated_name_district_groups_without_verified_identity": relations["repeated_name_district_groups_without_verified_identity"],
        "evidence_withheld_for_v1_temporal_limits": sum(e["evidence_id"] is None for e in ledger),
        "audit_sample_rows": len(selected), "audit_sample_sha256": sha(canonical([e["episode_id"] for e in selected])),
    }
    return {"batch": batch, "episodes": ledger, "relations": relations, "report": report,
            "audit_sample": [{"episode_id": e["episode_id"], "mode": e["mode"], "page": e["page"],
                              "source_locator": e["source_locator"]} for e in selected]}
