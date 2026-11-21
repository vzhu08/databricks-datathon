# ACQ-A01 handoff · national identity acquisition

Status: ready for review; contract **1.0.0**, parser `acquisition-1.0.0`. Developer A session `01a1ff42-3d8a-7e90-9750-5a4509a378ac`, branch `codex/acq-a-collectors`, task [#3](https://github.com/vzhu08/databricks-datathon/issues/3), [PR #13](https://github.com/vzhu08/databricks-datathon/pull/13). No merge, deployment, board/contract changes or submission performed.

Implementation tested at **`74f61e190b89c2517308a811690e3d1209dd6903`**. The subsequent handoff commit changes only this document; the task issue/PR records its final tested head. Remote board reread at `eea8686` before handoff; A's scope and v1 contract/fixtures were unchanged from the kickoff revision.

Changed paths: `research/acquisition/`, `tests/research/acquisition/`, this handoff. [Collector documentation](../../research/acquisition/README.md) explains installation, interfaces, deterministic IDs, geometry/PIN/name policies, attribution, offline replay and failed-refresh behavior. Dependencies are scoped in `research/acquisition/requirements.txt` (`jsonschema[format]==4.23.0`, `shapely==2.0.7`; Python 3.9+).

## Fixture checks

From `/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-a`:

```sh
source research/acquisition/.venv/bin/activate
python3 -m unittest discover -s tests/research/acquisition -p 'test_*.py' -v
PYTHONPYCACHEPREFIX=data/local/acquisition/pycache python3 -m compileall -q research/acquisition/__init__.py research/acquisition/common.py research/acquisition/fetch.py research/acquisition/parsers.py research/acquisition/run.py tests/research/acquisition
git diff --check
git ls-files data/local research/acquisition/.venv
git diff --name-only origin/main...HEAD
```

**27 tests passed**, byte compilation and whitespace checks passed. Git raw-data/dependency exclusion check returned no tracked files; changed paths are confined to A's three allowed scopes. Fixtures are entirely synthetic. Tests cover duplicate IDs/exact repeats/conflicting variants, separate campuses, null/non-ASCII names, NHP missing sentinels, PIN text/invalid PINs, malformed/swapped/outside coordinates, point/polygon/multipolygon handling, pharmacy/dentist/alternative types, specialty unknowns, metadata dates, contract schema/references, raw hashes, fresh-fetch/offline replay identity and first timestamps, failure isolation across sources, retries/exhaustion, 403/429, HTML/content-type/truncation/size failures, unsafe archives, preservation of accepted snapshots and credential-free logs. The shared synthetic batch passes the normative schema and the separate synthetic base retains unique IDs.

An initial compile check attempted the host's read-only Python cache and failed on cache-file permissions. The exact `PYTHONPYCACHEPREFIX` command above reran successfully inside ignored local storage; no source compilation error remains.

## Public-source results

```sh
python3 -m research.acquisition.run --source all --output-dir data/local/acquisition/public --timeout 45 --attempts 3
```

Both sources completed through the actual collector, then completed again against the committed implementation. First run: `f9cc6e64bf8d4e88b9a313d7154543d7`; committed-code repeat: `0eac1025996c46409dd3b07aeca8e283`. Each current collector HTTP request returned 200. During exploratory inspection, the default Python HTTP user agent received 403 from NHP; an ordinary public request identifying this research collector succeeded. No authentication or access-control bypass was used. The NHP object URL was resolved from matching JSON-LD distribution and download anchor on the observed landing page.

| Metric | HOT/OSM | NHP mirror |
| --- | ---: | ---: |
| Input features | 139,664 | 10,843 |
| Unique output records / distinct source IDs | 136,004 / 136,004 | 10,843 / 10,843 |
| Exact repeats removed | 3,660 | 0 |
| Conflicting source IDs / variants | 0 / 0 | 0 / 0 |
| Populated names (output) | 132,786 | 10,843 |
| Missing names retained as null (output) | 3,218 | 0 |
| Populated addresses (output) | 97,476 | 10,617 |
| Populated specialties (output) | 5,745 | 433 |
| Populated coordinates (output) | 136,003 | 10,843 |
| Missing / invalid coordinate inputs | 0 / 0 | 0 / 0 |
| Unsupported geometry coordinates (output) | 1 | 0 |
| Outside India bounding-envelope candidates (output) | 0 | 171 |
| Open review items | 1 | 171 |

Combined batch: **2 snapshots, 146,847 external rows, 172 reviews, 0 matches and 0 clinical evidence rows**. Output names/addresses are source text, not identity verification. Outside-envelope is a screening flag, not a country-boundary adjudication. Coordinates remain unchanged when WGS84-valid. OSM's single LineString retains raw geometry and emits null normalized coordinates. Polygon/MultiPolygon points are interior representative points, not entrances.

OSM input geometries: 130,808 Point, 8,838 Polygon, 17 MultiPolygon, 1 LineString. Output facility types include 7,462 pharmacy, 5,903 dentist and 1,425 alternative rows. NHP has 9,963 unknown care types; they are not silently relabeled as hospitals. Full source/type denominators and dedup/conflict counts are in the run report.

## Snapshot identity, dates and attribution

- **OSM:** `hot_osm_health:5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3`. SHA-256 is the suffix. First persisted retrieval: `2026-11-21T18:04:39.155206Z`. Upstream capture `2026-10-09`; artifact-created timestamp `2026-10-11T21:31:19Z`; publication date remains null. License **ODbL-1.0**, checked in both embedded and downloaded source metadata. Attribution: © OpenStreetMap contributors; HOT/Geofabrik/oex distribution, with [OSM copyright/attribution](https://www.openstreetmap.org/copyright).
- **NHP:** `nhp_hospitals_mirror:058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47`. First persisted retrieval: `2026-11-21T18:05:04.967879Z`. Mirror-modified date `2026-11-15`; upstream as-of and publication dates remain null. The filename's `2025` is not a precise date. [Landing page](https://bharatlas.com/view/nhp_hospitals) attributes National Health Portal (MoHFW), via data.gov.in, published via Bharatlas, under [GODL-India](https://data.gov.in/government-open-data-license-india).

Both snapshot rows keep `shared_origin` and upstream families `osm`/`nhp`. NHP plus its mirror count once. Independence from VF is unassessed, and no clinical quality or live availability is claimed. Attribution and applicable derivative-database/excerpt terms must travel with downstream exports.

Before comparing the saved OSM artifacts, their hashes were checked against the existing `data/external/sources.json`: ZIP hash `5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3`, item hash `aa766a914d47862528e1ae9873b8508f402e1cc6a913992b763359e4c582de36`. The fresh archive is byte-identical; current 139,664 input / 136,004 distinct IDs equals the saved October 9 profile. No observed content/count drift. The shared manifest records only retrieval **date** `2026-11-21`, so it was not used to fabricate a precise earlier retrieval timestamp. Fresh HTTP retrieval established the precise timestamp above. The shared source directory was only read, never modified.

## Reusable artifacts and replay

All real artifacts are ignored and uncommitted. Absolute artifact root:

```text
/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-a/data/local/acquisition/public/
```

Stable initial combined batch (identical normalized content on repeat acquisition):

```text
runs/f9cc6e64bf8d4e88b9a313d7154543d7/batch.json
```

Final repeat-acquisition batch/report: `runs/0eac1025996c46409dd3b07aeca8e283/{batch,report}.json`, also addressed by `latest-run.json`. The combined batch SHA-256 is `4b5900bad2a57a179d03a6eab88f283db4f44d62a7a13b57ea77c6d445e951aa`; initial and repeated batch bytes match exactly. The report includes per-type dedup/conflict metrics. The local audit summary is `../verification.json` relative to this artifact root. Snapshot directories below that root:

```text
snapshots/hot_osm_health/5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3/
snapshots/nhp_hospitals_mirror/058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47/
```

Each directory contains original bytes, landing/STAC evidence, the manifest with file hashes and first retrieval metadata, its self-contained contract batch and coverage. C can resolve every external record through its raw feature locator. D can load the combined batch after its own validator checks. Copy complete snapshot directories to a permitted location when handing them to another environment; preserve immutable metadata and record any physical relocation in D's run metadata. No permitted Volume path was supplied, so no upload is claimed.

Offline replay commands (from the clone root with the scoped environment activated):

```sh
python3 -m research.acquisition.run --source osm --replay data/local/acquisition/public/snapshots/hot_osm_health/5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3 --output-dir data/local/acquisition/replay-osm
python3 -m research.acquisition.run --source nhp --replay data/local/acquisition/public/snapshots/nhp_hospitals_mirror/058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47 --output-dir data/local/acquisition/replay-nhp
```

Both offline commands exited 0: OSM run `90e31393d7204e5e9c6579a55958c7cb`; NHP run `8ea03ec9ffc644bcb84a8a49b8ac0534`. Each replay batch is byte-identical to its accepted source batch, all artifact hashes verified, and first timestamps retained.

Replay reports/batches are under the corresponding `replay-osm/` and `replay-nhp/` directories, addressed through their `latest-run.json` pointers. Replay verifies every saved file hash and exact rederived normalized content, schema and references. Fresh repeat downloads preserve the first manifest and retrieval timestamp; later attempts are logged separately.

## Remaining work and status separation

- **Fixture checks:** passed as above.
- **Public acquisition:** both sources succeeded; 172 source/geometry review items remain for C. No unresolved public access blocker.
- **Live Databricks:** not attempted by A. D must validate/import into authorized storage and tables; no guessed workspace/table/Volume names or Marketplace rows were used.
- **Matching/clinical interpretation:** C owns identity review against D's preserved base IDs. Missing current Marketplace rows do not block this collector handoff. B owns service evidence; this producer emits no service claims.
- **Submission/deployment:** not performed. Review-ready acquisition code and public-source outputs do not establish a live publication or completed submission.
