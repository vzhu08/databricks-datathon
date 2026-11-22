"""Stage the pinned server modules and run the offline observer from the repo root."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from score import case_result, load_cases


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = "462e648dd79d3b1fd520d6c2479891f43e582612"
PINS = {
    "M": "6883c439716a42d78521df11e735e08e98415376",
    "N": "b741e9248d93d479aca412788dad9a4aa731bbda",
    "O": "1c7640d6a38fc27bf18d9593f46f7426472bc41f",
    "P": "d5ab8b3883d001b22df664b9b4ab178f07ed6591",
    "Q": "b2e186b384f7c15d438efae874e3ee9417080f46",
    "R": "55b52418533fe7ac1be76108a4888dc88d99ce3f",
}


V2_BASE = "1aac721ecd9dc4f4f7ac5cfb881e5c2af9ff5898"
V2_PINS = {
    "M": "410594eddc6af4685f331d11ca5d7ce81b8b1de5",
    "N": "94974d15291c7764d684baafe550378ffee1fa2a",
    "O": "9315009a3d123864411ff6256d8b2bfc7bd18680",
    "Q": "e7e847811a34d419be7199e23cbe027a4104006d",
}


def export(repo, root, commit, path):
    archive = subprocess.check_output(["git", "archive", "--format=zip", commit, path], cwd=repo)
    with ZipFile(io.BytesIO(archive)) as snapshot:
        snapshot.extractall(root)


def stage_components(repo, root):
    for name in ("M", "O", "P", "Q"):
        subprocess.run(["git", "merge-base", "--is-ancestor", PINS[name], BASE], cwd=repo, check=True)
    for name in ("N", "R"):
        paths = subprocess.check_output(
            ["git", "diff", "--name-only", BASE + "..." + PINS[name], "--", "app"], cwd=repo, text=True)
        if any(name != "N" or not path.startswith("app/patient_intake/providers/") for path in paths.splitlines()):
            raise ValueError("Unaccounted app change in component")
    export(repo, root, BASE, "app")
    export(repo, root, PINS["N"], "app/patient_intake/providers")


def stage_v2(repo, root):
    export(repo, root, V2_BASE, "app")
    seen = set()
    for commit in V2_PINS.values():
        changes = subprocess.check_output(
            ["git", "diff", "--name-status", V2_BASE + "..." + commit, "--", "app"], cwd=repo, text=True)
        for line in changes.splitlines():
            status, path = line.split("\t")
            if status not in {"A", "M"} or path in seen or not path.startswith("app/patient_intake/"):
                raise ValueError("Unexpected pinned v2 change")
            export(repo, root, commit, path)
            seen.add(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", help="Export app/ from this composed candidate instead of individual modules")
    parser.add_argument("--repo", type=Path, default=ROOT, help="Repository containing the composed commit")
    parser.add_argument("--v2", action="store_true", help="Run the approved v2 supplemental checks and frozen packet")
    args = parser.parse_args()
    cases = load_cases()
    with TemporaryDirectory() as temporary:
        app = Path(temporary)
        if args.commit:
            commit = subprocess.check_output(
                ["git", "rev-parse", "--verify", "--end-of-options", args.commit + "^{commit}"],
                cwd=args.repo, text=True).strip()
            export(args.repo, app, commit, "app")
            provenance = {"composition": commit}
        elif args.v2:
            stage_v2(args.repo, app)
            provenance = {"base": V2_BASE, "components": V2_PINS}
        else:
            stage_components(args.repo, app)
            provenance = {"base": BASE, "components": PINS}
        app = app / "app"
        observer = HERE / "runtime_binding.py"
        run = subprocess.run([sys.executable, "-I", "-S", "-B", str(observer), "--app", str(app)],
                             capture_output=True, text=True)
        if not run.stdout:
            raise SystemExit("Observer produced no report")
        report = json.loads(run.stdout)
        rows = report["observations"]
        if set(rows) != {case["id"] for case in cases}:
            raise SystemExit("Incomplete case inventory")
        checks = [case_result(case, rows[case["id"]]) for case in cases]
        differences = {r["id"]: r["failed"] for r in checks if r["failed"]}
        report.update(**provenance, case_coverage=checks, observed_field_disagreements=differences,
                      python=sys.version.split()[0], provider="audit-stub/v2 and prebound MGP terminal fixtures",
                      packet_sha256=hashlib.sha256((HERE / "cases.v1.json").read_bytes()).hexdigest(),
                      observer_sha256=hashlib.sha256(observer.read_bytes()).hexdigest())
        if args.v2:
            supplement = HERE / "v2_observer.py"
            extra = subprocess.run([sys.executable, "-I", "-S", "-B", str(supplement), str(app)])
            report["v2_supplement"] = {"passed": extra.returncode == 0,
                                       "sha256": hashlib.sha256(supplement.read_bytes()).hexdigest()}
            if extra.returncode:
                print(json.dumps(report, indent=2))
                return extra.returncode
        print(json.dumps(report, indent=2))
        return run.returncode or int(bool(differences))


if __name__ == "__main__":
    raise SystemExit(main())
