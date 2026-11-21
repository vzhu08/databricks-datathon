# Pinned national base · reviewed version-0 occurrence policy

Vincent's [D/C decision](https://github.com/vzhu08/databricks-datathon/issues/6#issuecomment-7069026841) authorizes a snapshot-specific exception for the 11 identical duplicate-ID pairs. The source is `databricks_virtue_foundation_dataset_dais_2026_databricks.virtue_foundation_dataset.facilities`, **VERSION AS OF 0**. Its 10,088 rows have 10,077 original `unique_id` values. The sibling `india_post_pincode_directory` is also pinned to version 0 and contains 165,627 rows. The older unsuffixed catalog is not this installed source.

## Identity and multiplicity

`map_base(..., id_policy="vf_v0_identical_occurrences", source_version=0)` preserves the original ID for each singleton. For each repeated ID, every original field must be identical. All N copies remain, with internal handles:

```text
base-occurrence:SHA256(UTF8(compact_JSON([fully_qualified_source_table, "0", original_id, decimal_ordinal_string])))
```

Ordinals range from 1 through N. JSON uses unescaped Unicode and compact separators, matching the reviewed SQL array encoding. All copies in the repeated group receive generated handles, including the first. Retained/generated key collisions, blank/nontext IDs, different payloads under the same ID, an unknown policy, a different table/version, or combining this policy with generic surrogates fail. The existing default still rejects duplicate IDs.

The copies are interchangeable. Ordinals express the multiplicity of a fixed snapshot; they are not physical row locations, separate campuses, independent match confirmations or cross-version identities. `source_row` retains every original field/value, including `unique_id` and nulls. `duplicate_groups.json` carries each original ID, full-payload hash, multiplicity and ordered generated handles. Its group ID hashes the table, version and original ID under `base-duplicate-group`.

The complete version-0 preparation also checks the reviewed totals: 10,088 unique internal keys, 10,077 original IDs/payloads, 11 groups of two, and 22 generated keys. Changed inputs require a new integration decision. Neither the shared contract nor the ordinary publication validator is weakened by this exception.

## Capture and prepare

Use the existing enrichment Python dependencies and an authorized Databricks CLI/profile. Never copy credentials into the repository or artifacts. The metadata packet from [A's source handoff](https://github.com/vzhu08/databricks-datathon/issues/36#issuecomment-7069022083) is required. Its manifest SHA-256 is pinned in the collector; all 14 downloaded files are verified before capture.

```sh
python databricks/enrichment/export_sql_snapshot.py \
  --output-dir data/local/national-v0/new-capture \
  --receipt-dir data/local/national-v0/source-receipt \
  --cli /path/to/existing/databricks --profile authorized-profile \
  --warehouse 8bac239c2de8f8da
python databricks/enrichment/prepare_versioned_base.py finalize \
  --run-dir data/local/national-v0/new-capture
python databricks/enrichment/prepare_versioned_base.py replay \
  --run-dir data/local/national-v0/new-capture
```

The collector issues read-only SQL through [Statement Execution](https://docs.databricks.com/api/statement-execution/v1/execute-statement). Facilities are partitioned into eight hash buckets and postal rows into sixteen, always at version 0. `to_json(struct(*), map('ignoreNullFields','false'))` preserves all observed columns and explicit nulls; the SQL-generated row JSON strings are frozen in private JSONL files. The strict local reader preserves JSON types and refuses lossy numeric conversion. No source columns, text, IDs or PIN values are normalized in the saved rows.

Each bucket must report success without truncation. Chunk offsets/counts and the final row/chunk totals are checked. Queries, statement IDs, retrieval times, raw hashes, field sets and source counts are recorded; a completed capture manifest is written last. An existing capture is never overwritten. A failed or interrupted run lacks a completed manifest; retain it for diagnosis and choose a fresh destination. No new warehouse, grants or source-table mutation is performed.

Preparation verifies the packet, every raw part/query hash, full field sets, source counts and canonical source-row multiset hashes. It then verifies the exact base ID mapping and both directions of original-row multiset equality. It writes a prepared manifest last. Interrupted preparation has no completed prepared manifest. Finalization refuses existing outputs rather than repairing them silently.

## Private package

| Artifact | Purpose |
| --- | --- |
| `base.json` | One JSON array of 10,088 `{facility_id, source_row}` records |
| `source_metadata.json` | Observed mapping/schema, pinned source, row count, base/source hashes and policy binding |
| `duplicate_groups.json` | Eleven shared groups, multiplicities and all 22 generated row handles |
| `postal_rows.json` | All 165,627 original postal rows as a JSON array, preserving repeated PINs |
| `postal_metadata.json` | Pinned postal source, observed schema/mapping and original-row/file hashes |
| `validation_report.json` | Preservation, identity multiplicity and postal lookup counts; publication/submission status |
| `capture_manifest.json`, `raw/`, `queries/`, `source-receipt/` | Frozen source data and acquisition provenance |
| `prepared_manifest.json` | Hash inventory for the entire package and aggregate report |

The original field mapping is `unique_id`, `name`, `address_stateOrRegion`, `facilityTypeId`, `address_zipOrPostcode`, `latitude`, `longitude`, and the observed service-text fields `description`, `specialties`, `procedure`, `equipment`, `capability`. C reads these bare column names from `source_metadata.json` and accesses them under `source_row`. Other matching roles remain C's explicit schema-based mapping.

Postal mapping is `pincode`, `statename`, `district`. The lookup uses one grouped entry per PIN and only exact six-digit trimmed facility postcode strings. It retains all original values and preserves the base's 10,088 rows, with 9,568 matching a postal group. The postal source remains 165,627 rows; the 19,586 grouped PIN keys are contextual references, not facilities or coordinates for a campus.

Offline replay verifies the complete file inventory and reproduces all six derived files byte-for-byte without network. Paths in this package are relative, so a private transfer does not rebind row identities or require a new artifact hash. Upload into a fresh subdirectory of the existing approved Volume, download it into ignored local storage, and verify the prepared-manifest hash plus every listed file before claiming delivery. C must separately acknowledge readback from its own account.

## Matching and publication boundary

C should compare the duplicate sidecar with full payload equality and count twins once for independent evidence/campus review while retaining every original occurrence in per-row output. The ordinary v1 validator currently permits only one confirmed `facility_id` per external record. Copying confirmed matches to multiple occurrence handles needs a coordinated envelope/validation decision before enrichment publication; this preparation patch does not make that decision.

Source preparation and private delivery do not publish the five enrichment tables. Later publication requires C's matching and B's evidence to pass the agreed contract and integrity checks. Record fixture checks, live SQL/storage checks, recipient readback and submission separately.
