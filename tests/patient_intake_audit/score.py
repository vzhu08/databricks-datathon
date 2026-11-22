"""Score observations of the #230 synthetic patient intake release candidate."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

PACKET = Path(__file__).with_name("cases.v1.json")
DIGEST = "c712c5fc110ddd0e027ad8f4903a211edc1e707ca3c2f6adae58b79e8ee6a28b"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def load_cases():
    raw = PACKET.read_bytes()
    if sha256(raw).hexdigest() != DIGEST:
        raise ValueError("Packet differs from the v1 GitHub freeze")
    return json.loads(raw, object_pairs_hook=unique_object)["cases"]


def case_result(case, observation):
    """Return failed/missing field names. Never echo captured values or exception text."""
    expected = case["expect"]
    if observation is None:
        return dict(id=case["id"], status="NOT_RUN", reason="no_observation")
    if type(observation) is not dict or set(observation) - {"measured", "error", "blocker"}:
        raise ValueError("Malformed observation")
    measured = observation.get("measured", {})
    if type(measured) is not dict or set(measured) - expected.keys():
        raise ValueError("Unknown measurement field")
    if "error" in observation and type(observation["error"]) is not bool:
        raise ValueError("Invalid execution error flag")
    blocker = observation.get("blocker")
    if blocker is not None and blocker not in (
        "unsupported_surface", "observer_missing", "candidate_missing", "dependency_missing"
    ):
        raise ValueError("Unknown blocker")
    missing = sorted(expected.keys() - measured.keys())
    failed = []
    for key, actual in measured.items():
        target = expected[key]
        if type(actual) is not type(target):
            failed.append(key)
        elif key.endswith("_min"):
            if actual < target:
                failed.append(key)
        elif actual != target:
            failed.append(key)
    if observation.get("error"):
        failed.append("execution_error")
    if failed:
        status = "FAIL"
    elif missing or blocker:
        status = "NOT_RUN"
    else:
        status = "PASS"
    return dict(id=case["id"], status=status, missing=missing, failed=failed,
                blocker=blocker, measured_fields=len(measured))


def score(cases, evidence, *, digest=DIGEST):
    if type(evidence) is not dict or set(evidence) != {"candidate_sha", "packet_sha256", "observations"}:
        raise ValueError("Expected candidate_sha, packet_sha256 and observations")
    sha = evidence["candidate_sha"]
    if sha is not None and (type(sha) is not str or not re.fullmatch("[a-f0-9]{40}", sha)):
        raise ValueError("Supply a full candidate commit SHA")
    if evidence["packet_sha256"] != digest:
        raise ValueError("Wrong packet edition")
    observations = evidence["observations"]
    ids = {c["id"] for c in cases}
    if type(observations) is not dict or set(observations) - ids:
        raise ValueError("Invalid observations or unknown case ID")
    if sha is None and observations:
        raise ValueError("Observations require a candidate commit")
    rows = [case_result(c, observations.get(c["id"])) for c in cases]
    counts = Counter(row["status"] for row in rows)
    return {"stage": "synthetic_engineering", "candidate_sha": sha, "packet_sha256": digest,
            "total": len(cases), "passed": counts["PASS"], "failed": counts["FAIL"],
            "not_run": counts["NOT_RUN"], "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, help="Path to private, instrumented observations")
    args = parser.parse_args()
    evidence = {"candidate_sha": None, "packet_sha256": DIGEST, "observations": {}}
    if args.observations:
        evidence = json.loads(args.observations.read_bytes(), object_pairs_hook=unique_object)
    report = score(load_cases(), evidence)
    print(json.dumps(report, indent=2))
    return int(report["not_run"] > 0 or report["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
