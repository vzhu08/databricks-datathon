"""Score private observations against the frozen experimental differential packet."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from .score import score, unique_object


PACKET = Path(__file__).with_name("differential.v1.json")
DIGEST = "49afd268de7a82390a714c0d81f2dc5ee28520b2e613a2fa88b98ec78ff73200"


def report(evidence):
    raw = PACKET.read_bytes()
    if sha256(raw).hexdigest() != DIGEST:
        raise ValueError("Differential packet differs from its independent freeze")
    packet = json.loads(raw, object_pairs_hook=unique_object)
    cases = [
        {**case, "expect": {**packet["common_expect"], **case["expect"]}}
        for case in packet["cases"]
    ]
    result = score(cases, evidence, digest=DIGEST)
    return {**result, "edition": packet["edition"], "clinician_validation": "unmeasured"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, help="Private synthetic observation bundle")
    args = parser.parse_args()
    evidence = {"candidate_sha": None, "packet_sha256": DIGEST, "observations": {}}
    if args.observations:
        evidence = json.loads(args.observations.read_bytes(), object_pairs_hook=unique_object)
    result = report(evidence)
    print(json.dumps(result, indent=2))
    return int(bool(result["failed"] or result["not_run"]))


if __name__ == "__main__":
    raise SystemExit(main())
