# ACQ-D02 handoff

Developer D · `@oliverchennn` · Codex chat `01a1ff42-470d-7f20-a2e2-ed23665cc075` · November 21, 2026.

Task: [issue #22](https://github.com/vzhu08/databricks-datathon/issues/22). Branch: `codex/acq-d-export-adapter`, created from current main at `86fb194` after verifying the prepared Developer D clone was clean. Previous branch `codex/acq-d-databricks` and ignored artifacts were preserved. Implementation SHA: `0cecefe32480798d7bdaad393c0157a7180f6824`. This handoff is a subsequent documentation commit; the issue/PR records the final tested/pushed head without a self-referential SHA in this file.

Status: independent offline adapter work ready for review. Real original-source export and live Databricks checks remain unavailable. Issue #6 remains live workspace acceptance. No merge, deployment or submission performed by D.

## Delivered and scope

`databricks/enrichment/prepare_local_export.py` accepts a bounded authorized UTF-8 JSON array or JSONL row export. It requires explicit source table, observed mapping/ID column, operator/export time, scope and completeness. It reuses the existing `map_base`, `profile_rows` and `verify_base_export` without changing their interfaces or publication notebooks.

The output is `base.json`, compatible `source_metadata.json`, and the exact original `source_export.json`/`.jsonl` bytes. The canonical base retains every exported row and field under `source_row`, original string IDs including leading zeros, and original integer ID values alongside their canonical text IDs. It records byte/ordered-row/order-independent-row/base hashes, counts, missingness and JSON types. No original table/schema/version is inferred: provenance is explicitly `operator_supplied_export`; source schema, directly observed Delta version and inspection time are null. An optional reported version remains labeled operator-reported.

Complete exports require a matching independently supplied selection count. Partial/unknown exports retain their scope and missing-count uncertainty, and are not described as full-source coverage. Truncated syntax is always rejected. Temporary output is hash/consumer-verified before directory publication; ordinary failures clean it up, existing destinations are never overwritten, and hard-interruption cleanup is documented. The CLI confines outputs to a new ignored `data/local/` subdirectory.

Changed files are only the new adapter, its [operator guide](../../databricks/enrichment/LOCAL_EXPORT.md), a two-line README link, `tests/databricks/enrichment/test_local_export.py`, and this handoff. No shared contract/board, original notebook/helper implementation, A/B/C implementation, baseline app, kit, or dependency changes. Contract v1.0.0 remains unchanged. The authoritative board was reread before handoff at `22a4cdbc8301a4299778e7402fdd949aa0ae1f2e`.

## Synthetic/local checks

From `/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-d`:

```sh
source databricks/enrichment/.venv/bin/activate
python3 -m unittest discover -s tests/databricks/enrichment -p 'test_*.py' -v
PYTHONPYCACHEPREFIX=/private/tmp/acq-d02-pycache python -m compileall -q databricks/enrichment -x '/.venv/'
git diff --check
git ls-files data/local databricks/enrichment/.venv
```

**72 tests passed**: 19 adapter cases plus all 53 existing enrichment cases. Compilation and whitespace checks passed. No local input/output/venv artifacts are tracked. New tests cover JSON and JSONL/CRLF, leading-zero/large integer IDs, duplicate/absent/null/empty/boolean/fractional IDs, original Unicode/multiline/null/nested fields, observed mapping requirements, explicit operator metadata, complete/partial/unknown counts, precision/non-finite/duplicate-key/truncated input rejection, bounded imports, failure after the first output write, failed readback cleanup/retry, destination/lock collisions, and the existing validation/publication consumers. The publication compatibility check uses SQLite simulation only.

An additional persisted **synthetic** CLI demonstration used the shared two-row base fixture and this local mapping:

```json
{"id":"facility_id","name":"name","evidence":["original_evidence"]}
```

The mapping is saved in ignored `databricks/enrichment/.venv/d02-mapping.json`. Exact commands:

```sh
python databricks/enrichment/prepare_local_export.py \
  --input contracts/fixtures/enrichment_base.json --format json \
  --source-table synthetic.fixture.facilities \
  --mapping databricks/enrichment/.venv/d02-mapping.json \
  --operator synthetic-fixture-operator --exported-at 2026-11-21T18:30:00Z \
  --completeness complete --expected-row-count 2 \
  --scope 'Complete two-row synthetic fixture only' \
  --output-dir data/local/acq-d02-synthetic-run
python databricks/enrichment/validate_batch.py \
  --batch contracts/fixtures/enrichment.json \
  --base data/local/acq-d02-synthetic-run/base.json --as-of 2026-11-21 \
  > databricks/enrichment/.venv/d02-fixture-consumer.json
```

Both commands exited 0. The adapter prepared 2 preserved base rows; the existing fixture consumer accepted 3 snapshots / 3 external rows / 3 matches / 3 evidence / 1 review against those IDs. `synthetic.fixture.facilities`, the operator and fixed export timestamp above are fixture labels, not observed real workspace metadata. Re-running preparation at the same completed destination correctly refuses to overwrite it; select a new run directory for another demonstration.

- Synthetic input-byte SHA-256: `47fbbdd75bbf8921541cf20659793222a49c63c9734f379e67879726ffa5b9ac`.
- Prepared synthetic base-file SHA-256: `7e760be8d579c6b83c9f3b85c35b7f36a49c34e2a3dd214571d0207f7f858902`.
- Artifacts remain local/ignored under `data/local/acq-d02-synthetic-run/`; no real records were committed.

## Real export and live status

No approved facility export was available in this clone's `data/local/` when work began. No Databricks CLI, `DATABRICKS_*` configuration or `~/.databrickscfg` was found. E's new [issue #23 result](https://github.com/vzhu08/databricks-datathon/issues/23#issuecomment-7067210985), also linked in #6, records the signed-in listing's unsupported-automation warning; actual source/postal table names and the permitted output Volume remain unverified. No browser tokens were accessed and no warning was bypassed.

Real source table, observed mapping/schema, full-source/selection counts, source version and real prepared base: **not observed / not tested**. Live warehouse read/write/publication: **not performed**. A's public reference records are not original Marketplace base rows and were not repurposed for this task. No additional public data acquisition occurred.

Smallest next action: an authorized operator follows [LOCAL_EXPORT.md](../../databricks/enrichment/LOCAL_EXPORT.md) to provide an intact JSON/JSONL original-row export in approved local/Volume storage, the actual table identifier and observed ID/mapping, an export time/operator and a stated selection/count/completeness. Keep the source schema/type receipt alongside the export. The guide includes a bounded manual notebook export using the existing helper, download/hash checks, precise local CLI options, partial/truncated-export handling, consumer verification and eventual Volume import. D/C can then prepare/match the supplied real rows without sharing credentials. Real pilot readiness and live Databricks publication must still be recorded separately.
