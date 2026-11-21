"""Capture the observed national register and independently filtered audit views."""
from pathlib import Path

from .common import FAMILY, SourceError, now, require, save
from .fetch import Fetcher
from .national_tables import LANDING, MAP, controls, filtered_url, page
from .tables import POLICY, TERMS

VERSION = "nqas-national-1.0.0"


def capture(root, max_pages=100, fetcher=None):
    root = Path(root)
    require(type(max_pages) is int and 1 <= max_pages <= 100, "national_invalid_page_limit")
    root.mkdir(parents=True, exist_ok=True)
    require(not (root / "national_capture.json").exists(), "national_capture_already_exists")
    client = fetcher or Fetcher(root)
    manifest = {"capture_version": VERSION, "started_at": now(), "source_family": FAMILY,
                "documents": {}, "views": {}, "blockers": [], "intended_use": "held_out_accreditation_audit"}
    for key, url in (("landing", LANDING), ("copyright", POLICY), ("terms", TERMS), ("map", MAP)):
        try:
            manifest["documents"][key] = client.get(url)
        except SourceError as error:
            manifest["blockers"].append({"source": key, "url": url, "reason": str(error)})
    try:
        require("landing" in manifest["documents"], "national_landing_unavailable")
        control = controls((root / manifest["documents"]["landing"]["artifact"]).read_bytes())
        manifest["controls"] = control
        for filter_index, status in enumerate(["All"] + sorted(set(control["status_options"]) - {"All"})):
            url = filtered_url(control, status)
            result = {"pages": [], "row_count": 0, "complete": False, "termination": None, "advertised_totals": []}
            seen = set()
            try:
                for number in range(max_pages):
                    doc = client.get(url)
                    key = "view_" + str(filter_index) + "_" + str(number)
                    manifest["documents"][key] = doc
                    parsed = page((root / doc["artifact"]).read_bytes(), url, number, status)
                    require(parsed["signature"] not in seen, "national_repeated_page_content")
                    seen.add(parsed["signature"])
                    result["pages"].append(key)
                    result["row_count"] += len(parsed["rows"])
                    result["advertised_totals"].append(parsed["advertised_total"])
                    if parsed["next_url"] is None:
                        result.update(complete=True, termination="no_next_link")
                        break
                    url = parsed["next_url"]
                else:
                    raise SourceError("national_pagination_limit_reached")
            except SourceError as error:
                result["termination"] = str(error)
                manifest["blockers"].append({"source": status, "url": url, "reason": str(error)})
            manifest["views"][status] = result
    except SourceError as error:
        manifest["blockers"].append({"source": "landing", "url": LANDING, "reason": str(error)})
    manifest.update(completed_at=now(), attempt_log=client.attempt_log)
    save(root / "national_capture.json", manifest)
    return manifest
