"""Generate and validate the single-file Datathon submission from tracked sources."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "submission.ipynb"
DRIVER = "tools/submission_demo.py"
SOURCE_ROOTS = (
    "app/", "contracts/", "databricks/enrichment/", "databricks/ingest/",
    "research/service_status/", "research/acquisition/national_facility_evidence/",
)
SOURCE_FILES = {
    "docs/implementation/SEARCH_CONTRACT.md",
    "docs/implementation/SERVICE_STATUS.md",
    "research/matching/__init__.py",
    "research/matching/common.py",
    "tests/facility_evidence_demo/synthetic_area.json",
    "tests/facility_evidence_demo/synthetic_display.json",
    "tests/intake/scenarios/digest.json",
    "tests/intake/scenarios/journeys.json",
}
ASSET_TYPES = {".woff2"}
BLOCKED_PARTS = {"approved_data", "private", "secrets", "__pycache__", ".env"}
DEPLOYMENT_ONLY = {"app/facility-area-display.json", "app/storm_ui/data/plan.json"}
SENSITIVE = re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|\bdapi[a-f0-9]{32}\b|\bAKIA[A-Z0-9]{16}\b")


CAPABILITY_COVERAGE = """## Outside support for capabilities mentioned by VF

Each denominator is the number of original VF occurrences that mention the capability in the
screened description, specialties, procedure, equipment or capability fields. It includes
occurrences with unresolved geography. A qualifying outside record supports that capability at
the matched facility. Multiple matches count once per original occurrence and capability.
A single occurrence can contribute to several capabilities.

| Capability | VF mentions with outside support | Coverage |
| --- | ---: | ---: |
| Dental care | 1,526 / 4,481 | 34.1% |
| Blood banking | 114 / 567 | 20.1% |
| Eye care | 564 / 3,000 | 18.8% |
| Cancer care / oncology | 186 / 2,370 | 7.8% |
| Radiotherapy (licensed centre) | 38 / 269 | 14.1% |
| Dialysis | 17 / 1,047 | 1.6% |
| MRI | 0 / 949 | 0.0% |
| Trauma care | 12 / 1,042 | 1.2% |

Dental care, blood banking and eye care together cover 2,168 distinct originals with outside
support. Dental includes 1,356 coded, service-field or roster matches and 170 specialist-title
matches. The broader affirmative VF-or-outside screen is a separate measure. The operational
dialysis, MRI and trauma ledger retains 30,264 unconfirmed decisions.

[Published capability table and definitions](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7081776129)
"""

CAPABILITY_APPENDIX = """## Appendix · other measured capabilities

These 49 rows and the eight rows in the main table give all 57 capability results. A zero is
an observed lack of a qualifying match in this comparison. Each row has its own mention cohort.

| Capability | VF mentions with outside support | Coverage |
| --- | ---: | ---: |
| Orthopedics | 207 / 3,888 | 5.3% |
| Cardiology | 198 / 3,247 | 6.1% |
| Maternity | 196 / 4,607 | 4.3% |
| Pediatrics | 180 / 3,573 | 5.0% |
| Dermatology | 160 / 2,428 | 6.6% |
| Fertility care | 157 / 1,474 | 10.7% |
| Ayurveda | 147 / 508 | 28.9% |
| Outpatient care | 137 / 4,255 | 3.2% |
| Laboratory services | 112 / 1,364 | 8.2% |
| Homeopathy | 74 / 355 | 20.8% |
| Kidney transplant programme | 62 / 448 | 13.8% |
| General surgery | 61 / 3,365 | 1.8% |
| Physiotherapy | 53 / 1,259 | 4.2% |
| Audiology | 36 / 352 | 10.2% |
| Emergency care | 35 / 2,772 | 1.3% |
| Intensive care | 29 / 2,295 | 1.3% |
| Liver transplant programme | 24 / 158 | 15.2% |
| Speech therapy | 11 / 177 | 6.2% |
| Prosthetics | 10 / 428 | 2.3% |
| Addiction treatment | 9 / 132 | 6.8% |
| Naturopathy | 9 / 57 | 15.8% |
| Ultrasound | 9 / 2,051 | 0.44% |
| CT | 8 / 1,482 | 0.54% |
| Pharmacy | 8 / 1,083 | 0.74% |
| X-ray | 8 / 2,474 | 0.32% |
| Ambulance | 7 / 1,184 | 0.59% |
| Heart transplant | 6 / 74 | 8.1% |
| IVF | 6 / 855 | 0.70% |
| Eye bank | 5 / 78 | 6.4% |
| Inpatient care | 5 / 1,874 | 0.27% |
| Occupational therapy | 5 / 106 | 4.7% |
| Cornea transplant | 4 / 180 | 2.2% |
| Acupuncture | 3 / 48 | 6.3% |
| LASIK | 3 / 499 | 0.60% |
| Pancreas transplant programme | 3 / 16 | 18.8% |
| Hospice | 2 / 175 | 1.1% |
| Blood transfusion | 1 / 93 | 1.1% |
| Cataract surgery | 1 / 700 | 0.14% |
| Chiropractic | 1 / 16 | 6.3% |
| IUI | 1 / 477 | 0.21% |
| Lung transplant | 1 / 44 | 2.3% |
| Acupressure | 0 / 21 | 0.0% |
| Blood apheresis | 0 / 65 | 0.0% |
| Blood storage | 0 / 37 | 0.0% |
| Chemotherapy | 0 / 290 | 0.0% |
| Dental implants | 0 / 1,494 | 0.0% |
| Haematology lab | 0 / 9 | 0.0% |
| Hair transplant | 0 / 239 | 0.0% |
| ICSI | 0 / 375 | 0.0% |

Ayurveda includes seven coded or registry-system matches. The other matches used specialist
facility titles. An organ-specific match measures registration at the indicated programme scope.

[Published capability table and definitions](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7081776129)
"""

SOURCE_NOTES = """## What the sources establish

- **Stroke awards give historical recognition a date.** We indexed World Stroke Organization /
  Angels Initiative awards by hospital label, quarter and tier. The India table yielded 545 awards
  under 102 hospital labels from 2019 Q2 through 2026 Q3. Exact normalized names linked seven
  award labels to 11 VF originals. These are historical leads. Physical branch, treatment type
  and current availability remain unresolved. [Award criteria](https://www.world-stroke.org/what-we-do/education-and-research/improving-access-to-quality-stroke-care/wso-awards) · [National join receipt](https://github.com/vzhu08/databricks-datathon/issues/239#issuecomment-7080899299)
- **Radiotherapy licensing and recorded treatment have different dates and meanings.** The June
  2026 AERB list contains 802 licensed centres. Institution name and postal PIN connected 38 of
  269 VF radiotherapy mentions to licensed centres. A separate name, city and state comparison
  connected seven VF originals to ICMR institutions that reported treatment given in 2012–14.
  The licence establishes licensed status in its edition. The treatment records are historical;
  present delivery and equipment uptime require further evidence. [AERB list](https://www.aerb.gov.in/images/PDF/Radiotheraphy/RSD3.pdf) · [ICMR treatment tables](https://www.ncdirindia.org/All_Reports/HBCR_REPORT_2012_2014/ALL_CONTENT/Printed_Version.htm) · [Coverage receipt](https://github.com/vzhu08/databricks-datathon/issues/58#issuecomment-7081734491)
- **Transplant registration is organ- and role-specific.** We checked facility name, location,
  organ and registered role in the NOTTO register. Retrieval-only sites were ineligible for
  transplant evidence. The registered programme comparison matched 62 of 448 kidney-transplant
  mentions and 24 of 158 liver-transplant mentions. Staffing, procedures performed and current
  access need separate evidence. [NOTTO register](https://notto.mohfw.gov.in/hospitals) · [Coverage receipt](https://github.com/vzhu08/databricks-datathon/issues/58#issuecomment-7081734491)
- **Blood banking needs a link to the host hospital.** A named hospital and area supported
  joining historical blood-bank directory entries to 114 of 567 VF banking mentions. Nearby
  collection sites, separate storage units and transfusion wording were insufficient. Repeated
  National Health Portal records counted once per original VF occurrence. Blood-group stock
  remains unknown. [Blood-bank coverage receipt](https://github.com/vzhu08/databricks-datathon/issues/58#issuecomment-7081734491)
- **Directory and map evidence can support a written area.** We compared named records at
  landmark, locality and PIN level, including entries without coordinates. Where nearby points
  agreed within 1 km, we tracked possible shared VF/map lineage. The rule expanded written-area
  support from 3,144 to 7,895 originals. Precise entrances and current onsite services require
  separate observations. [National location replay](https://github.com/vzhu08/databricks-datathon/issues/57#issuecomment-7081461436)
"""


def git(*args, input_bytes=None):
    return subprocess.run(
        ["git", *args], cwd=ROOT, input=input_bytes, stdout=subprocess.PIPE, check=True,
    ).stdout


def selected(raw_paths):
    paths = {part.decode("utf-8") for part in raw_paths.split(b"\0") if part}
    return sorted(path for path in paths if path in SOURCE_FILES or path.startswith(SOURCE_ROOTS))


def tracked_paths():
    return selected(git("ls-files", "-z", "--cached"))


def read_source(path, raw):
    name = PurePosixPath(path)
    if path in DEPLOYMENT_ONLY or name.is_absolute() or any(
        part.lower() in BLOCKED_PARTS or part in {".", ".."} for part in name.parts
    ):
        raise ValueError(f"Unapproved source path: {path}")
    if name.suffix in ASSET_TYPES:
        if not raw.startswith(b"wOF2") or SENSITIVE.search(raw):
            raise ValueError(f"Unexpected font content: {path}")
        return raw
    # Git's text checkout setting can produce CRLF on Windows. The embedded form uses LF.
    raw = raw.replace(b"\r\n", b"\n")
    if b"\r" in raw or b"\0" in raw or SENSITIVE.search(raw):
        raise ValueError(f"Unexpected binary byte or potential credential in {path}")
    raw.decode("utf-8")
    return raw


def working_sources(paths):
    sources = {}
    for path in [*paths, DRIVER]:
        disk = ROOT / path
        if not disk.is_file() or disk.is_symlink():
            raise ValueError(f"Expected a regular tracked source: {path}")
        sources[path] = read_source(path, disk.read_bytes())
    return sources


def verify_commit(revision, sources):
    paths = selected(git("ls-tree", "-r", "--name-only", "-z", revision))
    expected_paths = sorted(set(sources) - {DRIVER})
    if paths != expected_paths:
        raise ValueError("Selected checkout paths differ from the pinned integrated revision")
    references = "".join(f"{revision}:{path}\n" for path in paths).encode("utf-8")
    blobs = io.BytesIO(git("cat-file", "--batch", input_bytes=references))
    for path in paths:
        _, kind, length = blobs.readline().split()
        if kind != b"blob":
            raise ValueError(f"Pinned source is not a blob: {path}")
        raw = blobs.read(int(length))
        if blobs.read(1) != b"\n" or read_source(path, raw) != sources[path]:
            raise ValueError(f"Checkout source does not match {revision}: {path}")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def cell(cell_id, source, kind="code"):
    item = {"cell_type": kind, "id": cell_id, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        item.update(execution_count=None, outputs=[])
    return item


def literal(text):
    # A raw multiline literal leaves almost all source files readable in the notebook.
    if not text.endswith("\\"):
        for quote in ("'''", '"""'):
            if quote not in text and not text.endswith(quote[0]):
                return f"r{quote}{text}{quote}"
    return "(\n" + "\n".join(f"    {line!r}" for line in text.splitlines(keepends=True)) + "\n)"


START = '''from base64 import b64decode
from hashlib import sha256
from pathlib import Path, PurePosixPath
import os
import subprocess
import sys
from tempfile import TemporaryDirectory

_package_space = TemporaryDirectory(prefix="datathon-submission-")
PROJECT_ROOT = Path(_package_space.name)
_expected = {item["path"]: item for item in SOURCE_MANIFEST["files"]}
_materialized = set()

def include(path, payload):
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or path not in _expected:
        raise ValueError(f"Unexpected embedded path: {path}")
    expected = _expected[path]
    if len(payload) != expected["bytes"] or sha256(payload).hexdigest() != expected["sha256"]:
        raise ValueError(f"Embedded source failed verification: {path}")
    destination = PROJECT_ROOT.joinpath(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    _materialized.add(path)

def include_text(path, text):
    include(path, text.encode("utf-8"))

def include_base64(path, text):
    include(path, b64decode(text, validate=True))
'''


RUN = '''import json

if _materialized != set(_expected):
    raise RuntimeError("Run all of the embedded source cells before the demonstration.")
# Inherit only the OS settings needed to start Python. The guarded driver blocks network use.
_os_names = {"path", "systemroot", "windir", "systemdrive", "temp", "tmp", "comspec", "ld_library_path", "dyld_library_path"}
_demo_env = {name: value for name, value in os.environ.items() if name.lower() in _os_names}
result = subprocess.run(
    [sys.executable, "-I", "-B", "-X", "utf8", str(PROJECT_ROOT / "tools/submission_demo.py")],
    cwd=PROJECT_ROOT, env=_demo_env, capture_output=True, encoding="utf-8", timeout=120,
)
if result.returncode:
    raise RuntimeError(result.stderr or result.stdout)
report = json.loads(result.stdout)
print(result.stdout, end="")
'''


EXPLORATION = '''capability = report["published_capability_coverage"]
originals = capability["originals"]
supported_at_area = 7_895
unresolved = originals - supported_at_area
print(f"Published VF baseline: {supported_at_area:,}/{originals:,} ({supported_at_area / originals:.1%}) "
      f"with written-area support, {unresolved:,} unresolved.")
for service in ("Radiotherapy license", "MRI"):
    row = capability["examples"][service]
    supported, mentions = row["supported"], row["mentions"]
    print(f"{service}: {supported}/{mentions:,} VF mentions matched outside support ({supported / mentions:.1%}).")
print("AERB licenses establish licensed status in the published edition. Staffing and live availability are unknown.")
print("The MRI comparison found no outside matches under this method. Onsite MRI status remains unknown.")
'''


MODELING = r'''finder = report["find_care"]
alternative = finder["nearby_alternative"]
print("Fictional request: find dialysis within 50 km of Jaipur, Rajasthan.")
print(f"First result: {finder['facility']}, North Campus, {finder['straight_line_km']} km straight-line.")
print(f"Reported service ({finder['evidence']['field']}): {finder['evidence']['statement']}")
print(finder["explanation"]["location"])
print(finder["explanation"]["service"])
print(f"Alternative: {alternative['facility']}, {alternative['campus']}, "
      f"{alternative['straight_line_km']} km straight-line. Its {alternative['field']} field says "
      f"\"{alternative['statement']}\"")
print(finder["ranking_reason"])

batch = report["storm_batch"]
print(f"\nStorm control: seed {batch['scenario']['seed']}, {batch['requested']} simulated requests, "
      f"{batch['sites']} invented sites, {batch['scenario']['horizon_minutes']} minutes.")
print(batch["scenario"]["objective"] + ".")
print(batch["scenario"]["travel_basis"] + ".")
case = batch["case"]
rescued = case["rescued"]
earlier = case["moved_nearest"]
later = case["moved_exact"]
print(f"Nearest-first ran out of compatible slots for highest-priority {rescued['patient']}. "
      f"Routine {earlier['patient']} had used the sole place in {earlier['slot_id']}.")
print(f"The exact plan gives that dialysis place to {rescued['patient']} "
      f"and moves {earlier['patient']} to {later['slot_id']}, a feasible alternative.")
shared = batch["shared_travel"]
print(f"Across the same {shared['cohort']} assigned requests, modeled travel totals "
      f"{shared['nearest_first_seconds']:,} seconds nearest-first and "
      f"{shared['exact_optimum_seconds']:,} seconds exact.")
'''


IMPACT = r'''print("Health worker: call the exact campus to confirm onsite dialysis, the entrance, and current "
      "staffed availability before advising travel.")
for check in report["find_care"]["verification"]:
    print("  " + check)

print("\nDistrict planner: compare feasible placements and inspect the parts of the shift where stock ran out.")
batch = report["storm_batch"]
for key, label in (("nearest_first", "Nearest-first"), ("exact_optimum", "Exact planning")):
    metrics = batch["policies"][key]
    print(f"{label}: {metrics['assigned']}/{batch['requested']} assigned, {metrics['unmet']} unmet.")
    for priority in ("highest", "time_sensitive", "routine"):
        counts = metrics["by_priority"][priority]
        print(f"  {priority.replace('_', ' ').title()}: {counts['assigned']} assigned, {counts['unmet']} unmet.")
    for reason, count in metrics["unserved_reasons"].items():
        print(f"  Unmet because {reason.replace('_', ' ')}: {count}.")
print("Use the exhausted slot as a staffing sensitivity test. These are modeled appointments for invented demand.")
'''


def notebook(revision, sources):
    files = [
        {"path": path, "bytes": len(raw), "sha256": digest(raw)}
        for path, raw in sorted(sources.items())
    ]
    generator_pin = digest(read_source("tools/submission_notebook.py", Path(__file__).read_bytes()))
    fingerprint = digest(json_bytes({"files": files, "generator_sha256": generator_pin}))
    manifest = {"source_revision": revision, "input_sha256": fingerprint, "generator_sha256": generator_pin, "files": files}
    cells = [
        cell("overview", """# Find care and plan a constrained shift

**Run all** with Python 3.10 or later, then jump to the three judge outputs below. This file checks
and extracts its embedded sources, runs the app logic offline, and needs only the Python standard
library.

| Criterion | What to see after Run all |
| --- | --- |
| [Exploration](#exploration) | Published Virtue Foundation area coverage and two service evidence comparisons, with their denominators. |
| [Modeling](#modeling) | A service-and-location search with its facility claims and alternative, plus exact vs. nearest-first placement on identical simulated inputs. |
| [Impact](#impact) | A health worker's verification step and a planner's view of feasible appointments and unmet requests. |

The [national findings](#national-directory-finding) summarize the restricted VF analysis at
published aggregate scope. The runnable finder uses invented facilities. The Storm control
uses simulated demand, resources and travel. [Organizer criteria](https://cmudsc.com/datathon-fall2026/) · [Challenge brief](https://docs.google.com/document/d/e/2PACX-1vQxhDNQmgZhPgjG0M6LCb_UXNV8CJryqBNQQuqWfIg_dm40ZU1AYAXzZKViC6haFoCmLNiRVfUSBMjf/pub)
""", "markdown"),
        cell("reproducibility", f"""## Execution and source pins

The Databricks and Streamlit implementations are included for review. Run all in a Python notebook
or in an authorized Databricks Free Edition workspace. This offline replay is separate from signed-in
app and workspace verification. It sends no provider, routing, or Databricks requests.

The VF research frame preserves 10,088 original occurrences, including both members of 11 duplicate
pairs, and keeps three service decisions per original. The replay verifies the duplicate-preserving
contract on synthetic records.

Integrated source commit `{revision}`

Canonical input SHA-256 `{fingerprint}`

The setup cell pins each included file. Text inputs use LF for hashing.
""", "markdown"),
        cell("national-area-finding", """## National directory finding

The national comparison found written-area support for the named facility on **7,895/10,088 (78.3%)**
original Virtue Foundation occurrences. **2,193 occurrences remained unresolved** under
that comparison. The denominator counts original occurrences rather than distinct sites.

The finding describes support at the written PIN, locality or landmark area. Precise building and
entrance locations, current onsite services and national match accuracy remain unverified. These
are published national counts. The offline replay uses its own separate scenario and does not
recalculate the national result.

[National result and method](https://github.com/vzhu08/databricks-datathon/issues/57#issuecomment-7081461436)
""", "markdown"),
        cell("capability-coverage", CAPABILITY_COVERAGE, "markdown"),
        cell("source-stories", SOURCE_NOTES, "markdown"),
        cell("setup", "SOURCE_MANIFEST = " + repr(manifest) + "\n\n" + START),
    ]
    for path, raw in sorted(sources.items()):
        asset = PurePosixPath(path).suffix in ASSET_TYPES
        if asset:
            encoded = base64.b64encode(raw).decode("ascii")
            data = "(\n" + "\n".join(f"    {encoded[i:i+88]!r}" for i in range(0, len(encoded), 88)) + "\n)"
            source = f"include_base64({path!r}, {data})\n"
        else:
            source = f"include_text({path!r}, {literal(raw.decode('utf-8'))})\n"
        cells.append(cell("source-" + digest(path.encode("utf-8"))[:24], source))
    cells.extend([
        cell("run-introduction", """## Execute the synthetic demonstration

The first result shows the requested service, selected facility, straight-line distance and the
specific synthetic source field. The independent evidence path, emergency interrupt, and storm
comparisons run immediately afterward.
""", "markdown"),
        cell("run", RUN),
        cell("exploration", """## Exploration

This cell reproduces published **aggregate arithmetic** on the full VF analysis and matched
capability subsets. Radiotherapy uses the Atomic Energy Regulatory Board licensing list.
The published comparison joins institution name and postal PIN using the June 2026 list.
[AERB license list](https://www.aerb.gov.in/images/PDF/Radiotheraphy/RSD3.pdf)
The [coverage table and measured scopes](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7081776129)
and [AERB and other publisher narratives](https://github.com/vzhu08/databricks-datathon/issues/319#issuecomment-7081794326)
describe the evidence represented in the numerators.
""", "markdown"),
        cell("exploration-output", EXPLORATION),
        cell("modeling", """## Modeling

This cell reads outputs from the embedded finder, provenance mapper and Storm allocator. The
offline search uses the demo candidates and straight-line distance. The Storm control compares
arrival-order nearest-first with full-batch assignment on the same feasible appointments and
capacity. The priority-ordered objective and travel values are conditional on that synthetic shift.

The separate Pune benchmark uses public-source geography with simulated patients and staffing.
The public method describes eight mapped facility points and four outline interior anchors.
This notebook's runnable control uses invented sites. [Pune geography recipe](https://github.com/vzhu08/databricks-datathon/blob/d98a601/research/acquisition/pune_planning_geography/README.md)
""", "markdown"),
        cell("modeling-output", MODELING),
        cell("impact", """## Impact

The finder shows which claim to verify before travel. The planner quantifies feasible modeled
appointments and exposes where a staffing change could be tested.
""", "markdown"),
        cell("impact-output", IMPACT),
        cell("optional-ui", """## Optional local browser views

The source reconstructed under `PROJECT_ROOT` remains available for the life of this kernel.
With a local browser that can open files on the same machine, open `app/storm_ui/index.html` inside
that directory for the offline UI. The Overpass fonts ship with their SIL Open Font License.

An environment with Streamlit can also run `python -m streamlit run app/app.py` from
`PROJECT_ROOT`. Set `FIND_CARE_DATA=demo` and leave provider configuration empty. A local
browser and Streamlit are optional. The cells above install no packages and start no web server.

The full enrichment schema validator uses the separate optional dependency in
databricks/enrichment/requirements.txt. The default run executes only the local coverage code.
""", "markdown"),
        cell("capability-appendix", CAPABILITY_APPENDIX, "markdown"),
    ])
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "file_extension": ".py", "mimetype": "text/x-python"},
            "submission": {key: manifest[key] for key in ("source_revision", "input_sha256", "generator_sha256")},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


SCRATCH_RUN = '''import json
from pathlib import Path
assert {item.name for item in Path.cwd().iterdir()} == {"submission.ipynb"}
book = json.loads(Path("submission.ipynb").read_text(encoding="utf-8"))
cells = book["cells"]
assert book["nbformat"] == 4 and len({cell["id"] for cell in cells}) == len(cells)
scope = {"__name__": "__main__"}
for cell in cells:
    if cell["cell_type"] == "code":
        assert cell["outputs"] == [] and cell["execution_count"] is None
        exec(compile("".join(cell["source"]), "<notebook:" + cell["id"] + ">", "exec"), scope)
'''


def execute():
    with tempfile.TemporaryDirectory(prefix="submission-isolated-") as directory:
        shutil.copyfile(NOTEBOOK, Path(directory) / "submission.ipynb")
        subprocess.run([sys.executable, "-I", "-B", "-c", SCRATCH_RUN], cwd=directory, check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ref", help="Generate from this clean, integrated Git revision")
    parser.add_argument("--check", action="store_true", help="Check all tracked inputs and exact notebook bytes")
    parser.add_argument("--execute", action="store_true", help="Run the notebook with only the notebook in an isolated folder")
    args = parser.parse_args()
    if args.check == bool(args.source_ref):
        parser.error("Choose either --source-ref REF to regenerate or --check")
    paths = tracked_paths()
    try:
        sources = working_sources(paths)
        if args.check:
            existing = NOTEBOOK.read_bytes()
            revision = json.loads(existing)["metadata"]["submission"]["source_revision"]
            if not re.fullmatch(r"[a-f0-9]{40}", revision):
                raise ValueError("Invalid source revision in notebook manifest")
            unstaged = set(git("diff", "--name-only", "-z", "--").decode("utf-8").split("\0"))
            if unstaged.intersection({*paths, DRIVER, "tools/submission_notebook.py"}):
                raise ValueError("Packaged source differs between the index and working tree")
            verify_commit(revision, sources)
        else:
            revision = git("rev-parse", "--verify", "--end-of-options", args.source_ref + "^{commit}").decode().strip()
            verify_commit(revision, sources)
        content = notebook(revision, sources)
        generated = json_bytes(content)
        if args.check:
            if generated != existing:
                raise ValueError("Submission notebook drifted. Refresh from the current integrated revision.")
        else:
            NOTEBOOK.write_bytes(generated)
        print(f"{'Verified' if args.check else 'Wrote'} submission.ipynb: "
              f"{len(sources)} input files, {len(generated)} bytes, SHA-256 {digest(generated)}", flush=True)
        if args.execute:
            execute()
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
