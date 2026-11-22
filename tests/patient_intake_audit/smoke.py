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
PINS = {
    "M": ("6883c439716a42d78521df11e735e08e98415376", "patient_intake", ["__init__", "contracts", "service"]),
    "Q": ("b2e186b384f7c15d438efae874e3ee9417080f46", "patient_intake", ["interview", "evidence"]),
    "O": ("1c7640d6a38fc27bf18d9593f46f7426472bc41f", "patient_intake", ["session", "privacy"]),
    "P": ("45666fe0275074c6bcc87f97ca7289ce0a531051", "patient_intake", ["handoff"]),
}
RANKING = ["__init__", "evidence", "location", "search", "urgency"]


def stage(root, commit, package, modules):
    directory = root / package
    directory.mkdir(exist_ok=True)
    for module in modules:
        path = f"app/{package}/{module}.py"
        source = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
        (directory / f"{module}.py").write_bytes(source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", help="Export app/ from this composed candidate instead of individual modules")
    parser.add_argument("--repo", type=Path, default=ROOT, help="Repository containing the composed commit")
    args = parser.parse_args()
    cases = load_cases()
    with TemporaryDirectory() as temporary:
        app = Path(temporary)
        if args.commit:
            commit = subprocess.check_output(
                ["git", "rev-parse", "--verify", "--end-of-options", args.commit + "^{commit}"],
                cwd=args.repo, text=True).strip()
            archive = subprocess.check_output(["git", "archive", "--format=zip", commit, "app"], cwd=args.repo)
            with ZipFile(io.BytesIO(archive)) as snapshot:
                snapshot.extractall(app)
            app = app / "app"
            provenance = {"composition": commit}
        else:
            for commit, package, modules in PINS.values():
                stage(app, commit, package, modules)
            stage(app, PINS["P"][0], "ranking", RANKING)
            provenance = {"components": {key: value[0] for key, value in PINS.items()}}
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
        report.update(**provenance, observed_field_disagreements=differences,
                      python=sys.version.split()[0], provider="audit-stub/v1",
                      packet_sha256=hashlib.sha256((HERE / "cases.v1.json").read_bytes()).hexdigest(),
                      observer_sha256=hashlib.sha256(observer.read_bytes()).hexdigest())
        print(json.dumps(report, indent=2))
        return run.returncode or int(bool(differences))


if __name__ == "__main__":
    raise SystemExit(main())
