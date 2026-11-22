"""Combine the frozen backend observations and independently rendered fields on one local candidate."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from score import DIGEST, load_cases, score


# These are the rendered fields the driver measures, never replacement values
# for fields that the backend scorer already observed.
DISPLAY_FIELDS = {
    "qualified-completion": ["uncertainty_visible"],
    "contradiction": ["unresolved_visible"],
    "unsupported-age": ["unsupported_visible"],
    "provider-emergency": ["urgent_visible"],
    "terminated-empty": ["terminal_visible"],
    "malformed-provider": ["unavailable_or_review_visible"],
    "no-configuration": ["unavailable_or_review_visible"],
    "outage-after-success": ["unavailable_or_review_visible", "old_result_visible"],
    "expired-session": ["old_result_visible"],
    "same-count-edit": ["old_result_visible"],
    "budget-exhausted": ["budget_stop_visible"],
    "question-loop": ["bounded_stop_visible"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("backend", "browser", "server_log"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    backend = json.loads(args.backend.read_bytes())
    browser = json.loads(args.browser.read_bytes())
    log = args.server_log.read_text().splitlines()
    build = f"AUDIT_BUILD {backend['composition']} {browser['origin']}"
    calibration = [line for line in log if line.startswith("AUDIT_CALIBRATED ")]
    if log.count(build) != 1 or len(calibration) != 1 or not backend["v2_supplement"]["passed"]:
        raise ValueError("Incomplete or mismatched server provenance")
    controls = json.loads(calibration[0].split(" ", 1)[1])
    if controls != backend["calibration"] or backend["packet_sha256"] != DIGEST:
        raise ValueError("Calibration or frozen packet mismatch")
    if (browser["errors"] or browser["external_attempts"] or backend["blocked_process_starts"]
            or any(line.startswith(("AUDIT_EXTERNAL_ATTEMPT", "AUDIT_BOUNDARY")) for line in log)):
        raise ValueError("Inspect observer failure or unexpected side effect before combining")
    observations = deepcopy(backend["observations"])
    for case, fields in DISPLAY_FIELDS.items():
        row = observations[case]["measured"]
        for field in fields:
            value = browser["observations"][case][field]
            if field in row or type(value) is not bool:
                raise ValueError("Invalid supplemental observation")
            row[field] = value
    reset = browser["observations"]["reset-in-flight"]
    if reset["reset_before_release"] is True:
        observations["reset-in-flight"]["measured"]["old_result_visible"] = reset["old_result_visible"]
    if browser["observations"]["provider-instruction-text"]["instruction_rendered"] is True:
        del observations["provider-instruction-text"]["blocker"]
    result = score(load_cases(), dict(candidate_sha=backend["composition"], packet_sha256=DIGEST,
                                      observations=observations))
    print(json.dumps(result, indent=2))
    return int(bool(result["failed"] or result["not_run"]))


if __name__ == "__main__":
    raise SystemExit(main())
