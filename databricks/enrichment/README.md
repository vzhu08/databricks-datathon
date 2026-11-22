# ACQ-D01: validation and additive publication

Contract: `contracts/enrichment/schema.json`, v1.0.0. This directory owns no source data. Base facilities remain separate from the five enrichment tables. Run commands from the repository root of the isolated Developer D checkout.

For an authorized teammate's local JSON/JSONL export, use the [offline export adapter](LOCAL_EXPORT.md). It produces compatible base/metadata files while preserving operator-reported scope and completeness; live workspace acceptance remains separate.

## Local setup and checks

Python 3.9+; tested on Python 3.9.6. The only local dependency is pinned in this directory. No Spark, credentials, browser tokens, or workspace access is needed for local validation.

```sh
python3 -m venv databricks/enrichment/.venv
source databricks/enrichment/.venv/bin/activate
python -m pip install -r databricks/enrichment/requirements.txt
python3 -m unittest discover -s tests/databricks/enrichment -p 'test_*.py' -v
python databricks/enrichment/validate_batch.py \
  --batch contracts/fixtures/enrichment.json \
  --base contracts/fixtures/enrichment_base.json --as-of 2026-11-21
PYTHONPYCACHEPREFIX=/private/tmp/acq-d-pycache python3 -m compileall -q databricks/enrichment -x '/.venv/'
```

The fixture yields 2 unchanged base rows, 3 source snapshots, 3 external facilities, 3 matches, 3 evidence rows and 1 open review. The first trauma claim is historical; the second is inconclusive. These are synthetic cases, not hospitals inspected in a workspace.

The CLI exits 0 on valid input, 1 on validation/file errors. Errors identify a table, row index and field without echoing excerpts. Repeat `--batch` for A/B/C envelopes; arrays owned by other producers can be empty. References resolve across all batches and `--accepted`. `--accepted-ledger` carries previously committed review transitions. `--transitions` and `--identity-policy` accept separate JSON files. `--plan-out` creates a new restricted file containing the accepted envelope, full preserved base, transition ledger and policy; it refuses existing files or input paths. Never commit this plan with real records.

```sh
python databricks/enrichment/validate_batch.py \
  --batch /approved/local/a.json --batch /approved/local/b.json \
  --batch /approved/local/c.json --base /approved/local/base.json \
  --accepted /approved/local/accepted.json \
  --accepted-ledger /approved/local/accepted-ledger.json \
  --transitions /approved/local/transitions.json \
  --identity-policy /approved/local/identity-policy.json \
  --as-of 2026-11-21 --plan-out /approved/local/new-plan.json
```

Paths above are placeholders, not observed artifacts. Keep real artifacts under ignored `data/local/` or an authorized Volume. A source can validate with an empty base array when it emits only unlinked identity/evidence rows. That checks source-batch compatibility, not original facility coverage.

## Identity, review and replay rules

JSON Schema Draft 2020-12 is evaluated with format checking. Semantic checks add finite numbers, unique base IDs, cross-table references, coherent confirmed links, paired reviewer/time, spatial-only observations, temporal consistency, review queue coherence, and rejection of obvious service upgrades. Source/identity payloads are immutable; content corrections need new IDs. Evidence links and review decisions can change only through the operational ledger.

Ordinary replay deduplicates identical rows and sorts by primary ID. Conflicts fail the whole plan with no silent quarantine. A snapshot whose only changed field is `retrieved_at` retains its first persisted time. With no persisted row, the earliest retrieval instant is selected independent of input order. Later fetch attempts belong in the producer's acquisition log. Review transitions do not authorize conflicting replacements in ordinary batches; omit old transitioned rows or replay the original completed run ID instead of resubmitting obsolete decisions.

`stable_id(namespace, *parts)` produces `namespace:SHA256(canonical UTF-8 JSON array of parts)` with sorted object keys and no whitespace. For newly generated snapshot IDs use source identity and raw-byte hash, never retrieval time. For record/evidence IDs use stable source identifiers/locators and source content. Existing producer IDs are preserved; the validator does not impose a new producer ID algorithm. Arrays retain semantic order. `digest(row)` uses the same canonical JSON encoding on the row object for audit hashes.

Each transition is an object in a JSON array with exactly these fields:

| Field | Meaning |
| --- | --- |
| `transition_id` | Unique namespaced operational ID; exact replay only |
| `table`, `row_id` | Existing reviewable table/primary ID |
| `prior_payload_sha256`, `new_payload_sha256` | `digest(old_row)`, `digest(replacement)` |
| `actor`, `at`, `reason` | Nonempty reviewer, UTC `...Z` timestamp, explanation |
| `replacement` | Complete new row, not a partial patch |

Allowed fields: matches can change status/method/rationale/shared-identifier proof/reviewer/time; evidence can change base/match links/reviewer/time; queue entries can change status/next action/resolution. Original external/base identities, excerpts, claim wording and polarity cannot be changed in place. Actor/time must equal replacement review metadata. Hash chains are ordered by dependencies; forks, stale hashes, disconnected accepted histories and immutable changes fail. Rejecting a previously linked match requires unlinking its evidence in the same plan. Reopening a queue item uses a transition with null resolution. The trusted publication service owns accepted rows and historical ledgers; producer input is not permitted to replace that history.

Automatic shared-identifier confirmation requires a separately inspected namespace binding, exact text values on both sides, uniqueness and no competing non-rejected base candidate. A proof's self-declared namespace is not sufficient. The policy has this shape (synthetic example only):

```json
{
  "synthetic_registry": {
    "base_field": "source_row.registry_id",
    "external_field": "source_record_id",
    "source_keys": ["synthetic_directory"]
  }
}
```

The operator verifies that these fields actually represent the same namespace and grants policy changes only after review. Dot selectors can address preserved `source_row` fields. No policy is supplied by default: automatic confirmation then fails and manual review is required. A name, address or proximity comparison alone never provides namespace proof.

## Human evidence gate

Schema checks cannot prove arbitrary natural-language claims or that an excerpt occurs in a raw artifact. Before giving a definitive service claim reviewer/time, the reviewer must open the attributed snapshot, check the exact excerpt and locator, verify the same campus, and check negation, referral-only/planned/unavailable services, historical dates and the narrow clinical scope. Cross-snapshot claims are allowed; their assertion/locator must document why the claim source refers to the external identity, and a reviewer must verify it. The validator checks that references exist and review metadata is present, not that this reasoning is true.

Affirmative service claims require an explicit service token in the excerpt and review metadata. Known planned/proposed/referral-only/unavailable phrases are conservatively rejected. This English heuristic is an additional rejection guard, not a complete language classifier: review remains necessary for wording it does not recognize, and non-English excerpts may need a contract-coordinated policy change. Do not rewrite a verbatim excerpt just to pass the guard. General emergency, accreditation, scheme membership and a nearby building do not establish trauma capability. Null links remain permitted but do not contribute base corroboration. Historical/undated evidence never establishes live availability.

## Workspace preparation and minimal access

Live execution requires authorized Databricks compute with Unity Catalog Volumes, PySpark, Delta tables/time travel and named `spark.sql(..., args=...)` parameter markers (target DBR 14.3+ or compatible serverless; Free Edition compatibility has not been executed here). No paid infrastructure is required by this implementation. The notebook imports the same local modules from an absolute Workspace Git folder, with the shared schema present at its repository path.

Use an already installed Marketplace listing through the normal supported UI. An operator must supply the actual original and postal table names; this code does not assume the listing has installed tables. The source principal needs `USE CATALOG`, `USE SCHEMA`, `SELECT` on the original/postal tables and access to the authorized compute. The output principal needs `USE CATALOG`, `USE SCHEMA`, `CREATE TABLE` in a dedicated existing output schema, and `SELECT`/`MODIFY` on the six output tables. The input/output Volume requires `READ VOLUME`/`WRITE VOLUME` as appropriate. Schema/Volume creation can be performed once by an administrator; no source-table `MODIFY`, storage credentials, admin role or external network access is needed by the pipeline.

Keep publisher permissions separate from read-only consumers. Published attempt rows, operational state, and referenced Delta history must not be manually overwritten or vacuumed away. The protocol assumes writes go through this publisher. Serialize the one-time bootstrap; for scheduled imports use job concurrency 1. The pointer compare-and-swap also detects competing publishers and fails a stale publication rather than overwriting the winner.

If outbound package access is permitted, install in the notebook environment:

```python
# Databricks notebook cell; substitute the actual Workspace Git folder.
%pip install -r /Workspace/ACTUAL_REPO/databricks/enrichment/requirements.txt
```

If outbound access is restricted, download dependencies on an authorized external machine with `python -m pip download -r databricks/enrichment/requirements.txt -d /approved/local/wheels`, choosing wheels compatible with the workspace's Python/Linux runtime, upload them to the approved Volume, and install with `%pip install --no-index --find-links /Volumes/CATALOG/SCHEMA/VOLUME/wheels jsonschema[format]==4.23.0`. Restart Python if the environment requires it, then rerun notebook setup. Download source snapshots externally through the owners' permitted acquisition flows; upload approved inputs through the Volume UI. No browser token extraction or unsupported console automation is part of this path.

## Exact notebook order

1. Import/open `notebooks/01_inspect_sources.py`. Set `repo_root` to the absolute Workspace Git folder, `original_table` to the observed `catalog.schema.table`, optional `postal_table`, and `output_path` to a new approved `/Volumes/catalog/schema/volume/run-input` directory. Set `source_version` if known, otherwise the notebook attempts readable Delta history and pins the observed version. Run the schema/profile cell first. It prints aggregate metadata, never sample records. Set `mapping_json` from actual columns (`id`, `name`, `state`, `type`, `pin`, `latitude`, `longitude`, and `evidence` as a list). Run export. Set `postal_mapping_json` separately from the postal schema when supplied.
2. Inspect the profile before sharing a mapping: missingness, duplicate IDs, coordinate validity/anomaly counts, exact schema, version/export hash, nonempty evidence columns and repeated postal PIN counts. Exports contain `base.json`, `source_metadata.json`, and optionally `postal_rows.json`/`postal_metadata.json`. No base/postal join is performed. Postal context must first be aggregated to unique PINs in downstream matching. Share only non-sensitive profiles/mapping with A/B/C; original rows remain in approved storage.
3. Install dependencies and open `notebooks/02_validate_publish.py`. Set `repo_root`, the same `original_table`, a dedicated writable `output_catalog`/`output_schema` different from the source schema, and `contract_version=1.0.0`. Run once with `initialize_only=true`. This creates five schema-explicit Delta tables and the operational `enrichment_publication` table, leaving the pointer empty. Never bootstrap concurrently.
4. Upload ready A/B/C envelopes plus any reviewed transition/policy files. Set `initialize_only=false`, `input_path` to the exported base directory, `batch_files_json` to a JSON list of full Volume paths, `run_id` to a new logical run identifier, and `as_of` to the explicit coverage date. Optional `transitions_file` and `identity_policy_file` are full Volume paths. Run all cells. It checks the base file hash, original row count/text/content hash, ID mapping and accepted-base hash before staging. It reads accepted rows from the current completed pointer automatically.
5. Open `notebooks/03_read_coverage.py` with the same repo/output widgets. It captures the pointer once, reads the five pinned Delta versions for that attempt, verifies their content hash and counts, and prints the completed manifest coverage. Record the actual run/revision, table names/versions, source snapshot/artifact IDs, counts and any errors in the task handoff. Repeat step 4 with identical parameters to verify an actual live replay; the logical run/revision must remain unchanged.

Every widget starts empty unless it is a format/version/default bound. Uppercase path components above are placeholders, never claimed installed resources. Identifiers accept only simple letters/digits/underscores and are quoted; SQL values are bound via named parameters or DataFrame literals. Arbitrary SQL fragments, dotted multipart components beyond the expected count, and Volume traversal paths are rejected.

## Source preservation and bounded processing

The source is read-only. `base.json` uses `facility_id` plus `source_row`, containing every original column/value. Text whitespace and IDs are not normalized. Integer IDs are exposed as text while their original value is retained in `source_row`. Date/timestamp values become ISO strings, decimals retain their decimal text, binary becomes explicitly marked base64, and invalid non-finite source values become marked strings in the lossless export; source schema records their types. No enriched data is written into source rows.

When no usable source ID exists, `allow_surrogate=true` explicitly permits `stable_id("base", original_table, canonical_source_row)` after review. Content changes yield a new surrogate. Identical duplicate raw rows cannot acquire stable distinct identities without another source locator; export fails rather than using row order or silently dropping them. A new original-source revision/base hash requires a separately reviewed output schema; existing published runs cannot silently rebind base IDs/text.

The explicitly reviewed VF version-0 exception uses interchangeable occurrence handles to preserve identical-row multiplicity. It does not assign physical source identities or cross-version continuity. See [NATIONAL_BASE.md](NATIONAL_BASE.md) for its narrow opt-in, private export, replay and consumer requirements; default duplicate rejection is unchanged.

Inspection defaults to a maximum of 500,000 rows (hard cap 1,000,000) and does one bounded collection. Missing Delta history is recorded as `single_read_export`, with an exact export hash; no revision is invented and subsequent runs use the export. Validation/staging also use driver memory: this is a bounded sprint implementation for the national batches, not an unbounded distributed ingest service. Operational manifest history and ledgers are stored in one JSON state row, suitable for this finite sprint. Move to an independently reviewed scalable metadata design before sustained large-volume use.

## Publication, consumers, failure and recovery

The five physical tables are `source_snapshots`, `external_facilities`, `facility_matches`, `facility_evidence`, `review_queue`. They contain typed contract columns plus `_attempt_id` and `_payload_json` (the lossless original encoding). Each attempt gets a fresh UUID. All five writes append; none deletes a previous attempt. The operational table `enrichment_publication` contains one row: singleton, revision, and JSON with `current_run` plus completed manifests. Each manifest stores parent run, versions, counts, content/base hashes, source/artifact metadata, review ledger, identity policy and coverage.

The sequence is validate combined inputs → append five isolated attempt partitions logically → read back/compare all five → atomically compare-and-swap one operational row. The tables are not physically partitioned; the attempt column is the isolation key. The five writes are **not an atomic multi-table transaction**. A crash leaves unpublished rows; readers retain the previous completed manifest. Newer Databricks transaction features are not assumed or enabled here.

Consumers must use `publication.current(store)` (as notebook 03 does), or capture the same manifest once and filter every table on its `_attempt_id` at its recorded `versionAsOf`. Never read the raw physical tables unfiltered, query each table's independent latest run, or count all staged attempts as accepted rows. Never overwrite published attempts or remove their time-travel history with VACUUM. An empty validated run is valid only with consistent base/input semantics and still includes all five tables.

On validation failure there are no staged writes. On partial-write/readback failure, rerun notebook 02 with the same original input paths, run ID and coverage date; a fresh isolated attempt is used. After a lost publication response, the same request returns the recorded manifest after hash-verified readback, without another revision. Reusing a completed run ID with changed inputs is rejected. A replay of an older completed run does not move the pointer backward. If another publisher wins, reload the accepted state and rerun; no automatic replacement of the winning pointer occurs. Keep orphan attempts during the sprint; any later cleanup must prove an attempt is unreferenced by every retained manifest and coordinate retention first.

Recovery checks in `PublicationSimulationTests` use SQLite solely to simulate this protocol, including interruption after writes 1–5, process restart, no first-run pointer, replay, readback corruption and compare-and-swap conflict. These tests are **not live Databricks/Delta transaction proof**. Actual write/read/replay/failure verification in a scratch output schema remains a separate workspace acceptance step.

## Coverage interpretation

Coverage reports base identity confirmation and linked trauma separately from external row completeness. State/type/source-family distributions use the external-row denominator; match status uses match rows; trauma polarity uses trauma evidence rows; temporal status/effective-age use evidence rows. Unknowns remain explicit. Historical supports are labeled as including historical evidence. Freshness uses the evidence effective date relative to `as_of`, never the download timestamp. Source-family grouping does not award independence for multiple URLs. Error handling rejects an entire invalid run; successful manifests show zero errors/quarantined rows, not silently dropped records. Failed attempts return actionable errors and cannot publish a partial coverage report.

## Optional service-status artifact binding

Notebook 02 accepts `status_artifact_path`, `status_artifact_sha256` and an optional independently accepted `status_identity_rows_sha256`. Leave all three empty for a retrieval-only run. The artifact remains separate from the five v1 tables. Its complete file hash, original input-metadata digest, base/source/version/date, identity pin, every original occurrence and exactly three services per occurrence are checked. Global and state totals must reconcile. The artifact's batch hash must match the entire merged batch, including previously accepted rows, before any staging write. The completed manifest retains the checked reference.

The original metadata is copied before the notebook adds operational producer references. Those references cannot replace the artifact's original metadata digest. A replay rechecks the artifact and cannot silently accept changed bytes. Notebook 03 requires the original `input_path` when a status reference is present and verifies that artifact against the captured completed manifest. API consumers use `status_artifact.read_status_artifact(manifest, base, input_metadata)`. This verifies structural binding; acceptance of reviewed clinical labels and a patient release remain separate decisions.

The binder also checks the fields required by the producer's private and patient lookup functions: checked sources, reason text, review lists, nullable supersession and dates, and original-field or external-publisher citations. Missing or malformed fields fail before staging. The integration regression invokes both real consumers after publication/readback; it runs when `research.service_status.projection` is available, including a combined checkout with PR #79.

## Private Delta rehearsal

Notebook `04_private_rehearsal.py` requires an explicitly confirmed schema ending in `_validation`, with no existing tables, independently accepted base/frame/batch hashes, and private receipt storage. It verifies the full occurrence frame and original payloads before initialization. It accepts only a retrieval batch with zero evidence and zero confirmed identities. It publishes the requested run, checks all five version-pinned tables, verifies an identical replay creates no new versions, interrupts a separate `RUN_ID-recovery` attempt after its third table, and proves that the previous manifest remains readable. Recovery must preserve the same payloads; replaying the older run must leave the recovered pointer in place. Orphan attempts and all retained Delta versions remain intact.

The rehearsal requires a new store and an unused receipt path. After an interruption, inspect state and receipts before retrying; the notebook deliberately refuses to reuse a populated schema. It does not create the schema, change permissions, configure a recurring job, bind patient-status controls or submit an entry. `rehearsal.rehearse` is also exercised with the SQLite store, which is protocol simulation and not live Delta proof.

## Reference documentation

The adapter uses documented [named SQL parameters](https://docs.databricks.com/aws/en/pyspark/reference/classes/sparksession/sql), [Volume file access](https://docs.databricks.com/aws/en/files), [notebook dependencies](https://docs.databricks.com/aws/en/libraries/notebooks-python-libraries), and [Delta time travel/history](https://docs.databricks.com/aws/en/delta/tutorial). Databricks also documents [multi-table transaction requirements](https://docs.databricks.com/aws/en/transactions/transaction-modes); this implementation intentionally does not depend on those features being available or enabled in the target workspace.
