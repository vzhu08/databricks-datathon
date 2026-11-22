"""Build a metadata-only edition receipt, or replay its permitted raw assets.

The receipt is suitable for Git: source URLs, digests, dates, rights decisions
and aggregate counts only. Raw records, sheet names and excerpts stay private.
This does not upload to Databricks or claim remote verification.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .capture import canonical, fetch, sha256, write_json


def build(root, decisions):
    root = Path(root)
    catalogue = json.loads((root / "catalogue.json").read_text())
    downloads = json.loads((root / "downloads.json").read_text())
    editions = {x["sha256"]: x for x in json.loads((root / "editions.json").read_text())}
    by_digest = defaultdict(list)
    for item in downloads:
        if item.get("download_ok"):
            by_digest[item["sha256"]].append(item)
    if set(decisions) != set(by_digest):
        raise ValueError("an explicit disposition is required for every top-level raw edition")
    files = []
    for digest, receipts in sorted(by_digest.items()):
        decision = decisions[digest]
        if decision.get("status") not in {"permitted", "hold"} or not decision.get("reason"):
            raise ValueError("invalid rights disposition")
        edition = editions[digest]
        urls = sorted(r["url"] for r in receipts)
        entries = [x for x in catalogue if x["url"] in urls]
        files.append({"sha256": digest, "bytes": receipts[0]["bytes"], "urls": urls,
                      "retrieved_at": min(r["retrieved_at"] for r in receipts),
                      "catalogue_entries": [{"entry": x["entry"], "state_printed": x["state_printed"], "url": x["url"]} for x in entries],
                      "publication_date": None, "observation_period": None,
                      "temporal_note": "File/sheet dates are unreviewed; upload and filename dates do not date equipment condition.",
                      "format": edition["suffix"], "declared_format": edition["declared_suffix"],
                      "source_family": edition["source_family"], "extraction_status": edition["status"],
                      "part_count": len(edition["parts"]), "raw_text_record_count": edition["row_count"],
                      "rights": decision})
    return {"receipt_version": "1.0.0", "source": "NHSRC Database of Medical Equipment",
            "publisher": "National Health Systems Resource Centre, Ministry of Health and Family Welfare, Government of India",
            "catalogue_url": "https://nhsrcindia.org/HCT-DME",
            "policy_url": "https://nhsrcindia.org/copyright-policy",
            "policy_capture_sha256": sha256(root / "index/copyright.html"),
            "attribution": "Source: NHSRC, Ministry of Health and Family Welfare, Government of India; original named state/contractor inventory retained with its edition.",
            "sharing_scope": "Private project intake for Vincent, Oliver, Andrew and Ayush; accurate attributed reproduction; no current-service inference.",
            "raw_row_grain": "Source worksheet row / document paragraph / PDF line. Archive/member and catalogue occurrences retained separately.",
            "join_fields": ["edition SHA-256", "sheet/row or page/line locator", "printed facility/district when present", "serial/equipment identifiers when present"],
            "source_family_count": 1, "independence": "Shared NHSRC programme lineage; state/contractor reports are not assumed independent.",
            "counts": {"catalogue_occurrences": len(catalogue), "unique_raw_urls": len(downloads),
                       "raw_byte_editions": len(files), "rights_dispositions": dict(Counter(x["rights"]["status"] for x in files))},
            "files": files, "databricks": {"status": "pending_writer_stage_and_readback", "writer": "Vincent",
                "target_volume": "/Volumes/workspace/default/datathon_vf_research_intake/", "verified_path": None},
            "national_comparison": {"owner": "D on #163, campus linkage Vincent", "status": "pending",
                "original_occurrences": 10088, "distinct_upstream_ids": 10077, "duplicate_pairs": 11,
                "service_decisions": 30264, "matched_occurrences": None, "reviewed_campus_service_pairs": None,
                "new_dated_evidence": None, "status_transitions": None}}


def replay(receipt, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    downloads, catalogue = [], []
    for file in receipt["files"]:
        for entry in file["catalogue_entries"]:
            catalogue.append({**entry, "publication_date": file["publication_date"],
                              "observation_period": file["observation_period"]})
        if file["rights"]["status"] != "permitted":
            continue
        path = root / "blobs" / file["sha256"]
        if path.is_file() and path.stat().st_size == file["bytes"] and sha256(path) == file["sha256"]:
            result = {"download_ok": True, "sha256": file["sha256"], "bytes": file["bytes"],
                      "path": f"blobs/{file['sha256']}", "retrieved_at": file["retrieved_at"], "reused_verified_blob": True}
        else:
            result = fetch(file["urls"][0], root, file["sha256"])
            if not result["download_ok"] or result.get("sha256") != file["sha256"] or result.get("bytes") != file["bytes"]:
                write_json(root / "replay-failure.json", result)
                raise ValueError("publisher edition changed or download failed; do not substitute")
        for url in file["urls"]:
            downloads.append({**result, "url": url})
        write_json(root / "downloads.json", downloads)
    write_json(root / "catalogue.json", sorted(catalogue, key=lambda x: x["entry"]))
    write_json(root / "source-receipt.json", receipt)
    return {"verified_permitted_urls": len(downloads), "held_editions_not_fetched": sum(x["rights"]["status"] == "hold" for x in receipt["files"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "replay"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--decisions", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        if not args.decisions:
            parser.error("build requires --decisions")
        result = build(args.root, json.loads(args.decisions.read_text()))
        write_json(args.receipt, result)
        print(canonical({"receipt_sha256": sha256(args.receipt), "counts": result["counts"]}))
    else:
        print(canonical(replay(json.loads(args.receipt.read_text()), args.root)))


if __name__ == "__main__":
    main()
