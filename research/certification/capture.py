"""Capture the observed Rajasthan filters, with explicit completion per view."""
from pathlib import Path

from .common import SourceError, now, require, save
from .fetch import Fetcher
from .tables import LANDING, POLICY, REGISTER, TERMS, discover, page_rows, row_signature


def capture(root, max_pages=100, fetcher=None):
    root = Path(root)
    require(type(max_pages) is int and 1 <= max_pages <= 100, "invalid_page_limit")
    root.mkdir(parents=True, exist_ok=True)
    require(not (root / "capture.json").exists(), "capture_already_exists")
    client = fetcher or Fetcher(root)
    manifest = {"capture_version": "1.0.0", "started_at": now(), "documents": {}, "views": {},
                "blockers": [], "source_family": "nhsrc_nqas", "use": "held_out_accreditation_audit"}
    for key, url in (("landing", LANDING), ("copyright", POLICY), ("terms", TERMS), ("register", REGISTER)):
        try:
            manifest["documents"][key] = client.get(url)
        except SourceError as error:
            manifest["blockers"].append({"source": key, "url": url, "reason": str(error)})
    if "landing" not in manifest["documents"]:
        manifest["completed_at"] = now()
        manifest["attempt_log"] = client.attempt_log
        save(root / "capture.json", manifest)
        return manifest
    landing = root / manifest["documents"]["landing"]["artifact"]
    try:
        controls = discover(landing.read_bytes())
    except SourceError as error:
        manifest["blockers"].append({"source": "landing", "url": LANDING, "reason": str(error)})
        manifest["completed_at"] = now()
        manifest["attempt_log"] = client.attempt_log
        save(root / "capture.json", manifest)
        return manifest
    manifest["controls"] = controls
    # An accessible register is retained, but never parsed using an invented layout.
    if "register" in manifest["documents"]:
        manifest["blockers"].append({"source": "register", "url": REGISTER,
                                    "reason": "accessible_register_requires_observed_layout_adapter"})
    for mode in ("full", "partial"):
        url = controls["endpoints"][mode]
        view = {"pages": [], "row_count": 0, "complete": False, "termination": None}
        seen = set()
        try:
            for number in range(max_pages):
                document = client.get(url)
                key = mode + "_" + str(number)
                manifest["documents"][key] = document
                records, next_url = page_rows((root / document["artifact"]).read_bytes(), url, mode, number)
                signature = row_signature(records)
                require(signature not in seen, "repeated_page_content")
                seen.add(signature)
                view["pages"].append(key)
                view["row_count"] += len(records)
                if next_url is None:
                    view.update(complete=True, termination="no_next_link")
                    break
                url = next_url
            else:
                raise SourceError("pagination_limit_reached")
        except SourceError as error:
            view["termination"] = str(error)
            manifest["blockers"].append({"source": mode, "url": url, "reason": str(error)})
        manifest["views"][mode] = view
    manifest["completed_at"] = now()
    manifest["attempt_log"] = client.attempt_log
    save(root / "capture.json", manifest)
    return manifest
