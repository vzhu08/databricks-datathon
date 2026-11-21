"""Documentary comparison of a challenge sample against the alternate QPS view."""
from collections import Counter
from pathlib import Path

from .build import checked_raw
from .common import SourceError, canonical, now, read, require, save, sha
from .episodes import sample
from .fetch import Fetcher
from .tables import combined_url, page_rows


def acquire_audit(root, episodes, fetcher=None):
    root = Path(root)
    require(not (root / "audit_capture.json").exists(), "audit_capture_already_exists")
    client = fetcher or Fetcher(root)
    manifest = {"audit_version": "1.0.0", "documents": {}, "blockers": []}
    for page in sorted({e["page"] for e in sample(episodes)}):
        url = combined_url(page)
        try:
            manifest["documents"][str(page)] = client.get(url)
        except SourceError as error:
            manifest["blockers"].append({"page": page, "url": url, "reason": str(error)})
    manifest.update(completed_at=now(), attempt_log=client.attempt_log)
    save(root / "audit_capture.json", manifest)
    return compare(root, episodes)


def compare(root, episodes):
    manifest = read(Path(root) / "audit_capture.json")
    require(manifest["audit_version"] == "1.0.0", "unknown_audit_version")
    for doc in manifest["documents"].values():
        checked_raw(root, doc)
    results, parsed = [], {}
    selected = sample(episodes)
    for item in selected:
        result = {"episode_id": item["episode_id"], "mode": item["mode"], "page": item["page"],
                  "primary_locator": item["source_locator"], "primary_sha256": item["snapshot_sha256"],
                  "register_comparison": "unavailable_unparsed_register", "expiration": item["expiration"],
                  "ambiguous_date": any(item[k]["status"] == "ambiguous" for k in ("start", "end"))}
        document = manifest["documents"].get(str(item["page"]))
        if document is None:
            result.update(status="unavailable", reason="alternate_view_fetch_failed")
        else:
            result.update(alternate_url=document["url"], alternate_sha256=document["sha256"])
            key = (item["mode"], item["page"])
            try:
                if key not in parsed:
                    parsed[key], _ = page_rows(checked_raw(root, document), document["url"], *key)
                candidates = [r for r in parsed[key] if r["display_cells"] == item["display_cells"]]
                if len(candidates) == 1:
                    result.update(status="exact_display_fields_agree", alternate_row=candidates[0]["row_index"])
                else:
                    result.update(status="unresolved", reason="row_not_uniquely_present_in_alternate_view")
            except SourceError as error:
                result.update(status="unavailable", reason=str(error))
        results.append(result)
    return {"method": "Deterministic stratified documentary challenge sample; automated seven-column comparison of original HTML table views.",
            "independence": "Both QPS presentations share programme origin; agreement is not independent corroboration.",
            "not_blinded_human_validation": True, "population_accuracy_estimate": None,
            "sample_sha256": sha(canonical([e["episode_id"] for e in selected])), "sample_rows": len(selected),
            "by_mode": dict(Counter(e["mode"] for e in selected)),
            "by_status": dict(Counter(r["status"] for r in results)),
            "ambiguous_date_rows": sum(r["ambiguous_date"] for r in results),
            "by_expiration": dict(Counter(r["expiration"] for r in results)),
            "register_comparisons_completed": 0, "blockers": manifest["blockers"], "rows": results}
