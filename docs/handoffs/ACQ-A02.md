# ACQ-A02 · Rajasthan candidates for B/C

Ready for review: [PR #26](https://github.com/vzhu08/databricks-datathon/pull/26), task [#21](https://github.com/vzhu08/databricks-datathon/issues/21), C's matching task [#5](https://github.com/vzhu08/databricks-datathon/issues/5). Branch `codex/acq-a-rajasthan-extract`, Developer A session `01a1ff42-3d8a-7e90-9750-5a4509a378ac`. The previous task/branch and all accepted ACQ-A01 artifacts are preserved.

Tested implementation: **`a2736f7e4334882d7e202d9dd64d63ec5b0fcb56`**. The final documentation commit/head and final test rerun are recorded in the PR and task issue. Branch started from clean `origin/main` at `86fb194135d89aa39f41be8e5f40eddbe0a8e218`; remote board reread before handoff at `22a4cdbc8301a4299778e7402fdd949aa0ae1f2e`. No intervening changes to the consumed contract, D validator or acquisition files were observed. No board/shared-contract edits, merge or deployment performed.

## Result and selection limits

The offline extractor verifies the two accepted #13 snapshots, keeps all selected external rows byte-equivalent as JSON values, retains their IDs/locators/source references/first timestamps, and emits two separate v1.0.0 envelopes. The complete national batch remains unchanged for recall. [Reproduction and rule documentation](../../research/acquisition/RAJASTHAN.md) and the frozen [rule file](../../research/acquisition/rajasthan_rules.json) explain every decision.

Explicit candidates have a full Rajasthan state label (including accented Latin/Hindi) or a Rajasthan address suffix, with no detected text/coordinate conflict. Name-only, district-only, postal-prefix-only and street-name mentions are not selection proof. Additional candidates contain text/coordinate disagreements or missing/other-state labels inside the broad geographic screening rectangle. Source fields are never repaired or relabeled. Selection reasons live in `decisions.json` and new advisory review items, not rewritten identity rows.

| Reconciliation | HOT/OSM | NHP mirror | Total |
| --- | ---: | ---: | ---: |
| Original raw features | 139,664 | 10,843 | 150,507 |
| Exact repeats removed by ACQ-A01 | 3,660 | 0 | 3,660 |
| Accepted national external rows | 136,004 | 10,843 | 146,847 |
| Explicit candidates | **8,191** | **0** | **8,191** |
| Additional review candidates | 12,102 | 1,605 | 13,707 |
| Excluded from these smaller extracts | 115,711 | 9,238 | 124,949 |
| Duplicate candidate input occurrences removed in this run | 0 | 0 | 0 |

For each source, explicit + additional + excluded equals the accepted national row count. Raw counts reconcile through A01's exact-repeat count. All 21,898 selected external IDs are disjoint across the two outputs, and their complete row payloads equal the national originals.

The accepted NHP mirror has **no explicit Rajasthan state/address candidates**; this is a source coverage gap, not evidence that facilities do not exist. Of 8,192 Rajasthan-labeled OSM rows, one has a competing recognized address-state suffix and is isolated for review. The remaining **13,706** additional candidates are other-state rows inside the rectangle. They are **not 13,706 confirmed location/state errors**. No missing-state row landed in either subset with these inputs/rules; missing-state handling was verified synthetically.

The inclusive longitude 69.4–78.35 / latitude 23.0–30.25 rectangle rounds outward from the [Rajasthan State GIS portal's stated extent](https://rajdharaa.rajasthan.gov.in/), inspected November 21, 2026. It includes neighboring-state territory and is not a state boundary. C should start with the explicit batch, use the additional batch selectively for recall/review, and keep the full national batch available. A polygon refinement would need its own pinned artifact/rule revision. No matches, service evidence, clinical quality or live availability are asserted.

## Artifacts and hashes

All real rows remain in ignored storage. Absolute artifact root:

```text
/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-a/data/local/acquisition/
```

| File below that root | SHA-256 |
| --- | --- |
| `public/runs/0eac1025996c46409dd3b07aeca8e283/batch.json` (unchanged national recall input) | `4b5900bad2a57a179d03a6eab88f283db4f44d62a7a13b57ea77c6d445e951aa` |
| `rajasthan-v1/explicit.json` | `de9f6d9ebd163680af00ba1482cc6b868f57a46e2091be3c876e1a4f08c15c31` |
| `rajasthan-v1/additional_review.json` | `a1e43991463114c4a3dd55d7e374af9c4413cea2114299fbd129c1be27e5228b` |
| `rajasthan-v1/decisions.json` | `d118fd94b2bdacfeb8612f8e2454bef6f254811b1c65cb24599e63b2af508ca4` |
| `rajasthan-v1/report.json` | `dd599ca5b208c374147ea613f66c48f8f9c6cba5c3e271db7365b5a7a308cf47` |
| `rajasthan-v1/manifest.json` | `fc390b4b7bdd1a677aa5c8cb9d65018d9a823d8c5b1dcffb764a6248ee2f032a` |

Rule version `rajasthan-candidates-1.0.0`, canonical rule hash `ec09daca013f16e3feec7f4431f101f77ee22c57f47806736de823c5953ec69e`.

Accepted source IDs and raw hashes remain:

- `hot_osm_health:5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3`, source family `osm`, ODbL-1.0, first retrieval `2026-11-21T18:04:39.155206Z`.
- `nhp_hospitals_mirror:058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47`, source family `nhp`, GODL-India per the mirror attribution, first retrieval `2026-11-21T18:05:04.967879Z`.

Complete source directories remain under `public/snapshots/<source_key>/<raw_hash>/`. Both output envelopes retain both original source-snapshot rows, even where NHP has zero explicit candidates. Publication dates remain null; source-capture/mirror dates and shared-origin assessments are unchanged. Original attribution and applicable redistribution terms remain attached. Copy complete snapshots and the national batch into approved storage when transferring to another environment; preserve immutable metadata and record any physical relocation separately.

## Exact checks and reproduction

Run from `/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-a`:

```sh
source research/acquisition/.venv/bin/activate
python3 -m unittest discover -s tests/research/acquisition -p 'test_*.py' -v
acq_public=data/local/acquisition/public
python3 -m research.acquisition.rajasthan \
  --snapshot "$acq_public/snapshots/hot_osm_health/5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3" \
  --snapshot "$acq_public/snapshots/nhp_hospitals_mirror/058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47" \
  --national-batch "$acq_public/runs/0eac1025996c46409dd3b07aeca8e283/batch.json" \
  --output-dir data/local/acquisition/rajasthan-v1
python3 databricks/enrichment/validate_batch.py \
  --batch data/local/acquisition/rajasthan-v1/explicit.json \
  --batch data/local/acquisition/rajasthan-v1/additional_review.json \
  --base data/local/acquisition/empty-base.json --as-of 2026-11-21 \
  > data/local/acquisition/rajasthan-validation.json
PYTHONPYCACHEPREFIX=data/local/acquisition/pycache python3 -m compileall -q research/acquisition/rajasthan.py tests/research/acquisition/test_rajasthan.py
git diff --check
git ls-files data/local research/acquisition/.venv
```

`empty-base.json` contains `[]`, solely to validate these unlinked producer outputs. It is not a Marketplace export. The command to create that local file is in the reproduction documentation.

**Fixture checks:** 43 tests passed: 27 prior collector cases and 16 new regional cases. New cases cover missing state, conflicting state/address/coordinates, accented/Hindi state labels, ambiguous street/name text, exact duplicate candidates, repeated-ID variants/separate campuses, original references/reviews/timestamps, count reconciliation, stable replay, corrupt-input rejection, output preservation, and D's validator on synthetic extracts.

**Real-source processing:** first extraction exited 0. Repeating the full extraction at implementation SHA above exited 0 and verified byte equality for all five output files, including the manifest/report/decision index. All source artifact hashes, output hashes, unchanged national hash, 21,898 original row payloads, original source reference rows and both per-source reconciliations were independently checked. No new download was substituted.

**D v1 validation:** exited 0 with `status=valid`, contract `1.0.0`, 2 deduplicated source snapshots, 21,898 external facilities, 13,707 advisory reviews, 0 matches, 0 evidence, 0 base rows and 0 ledger rows. Output is `data/local/acquisition/rajasthan-validation.json`. These are local compatibility checks, not live Databricks or base-coverage verification.

Compilation/whitespace checks passed. The raw-data/dependency tracking check returned no files; only the assigned acquisition code/tests and this handoff changed.

## Remaining work

No unresolved source-access or extraction blocker. C owns candidate triage and campus matching against D's authorized base IDs/mapping; B owns service research. The geographic review group is deliberately broad and must not be imported as confirmed Rajasthan identity evidence. D's live publication and the original Marketplace base mapping remain separate work. No Volume upload, live Databricks publication, deployment or submission was performed.
