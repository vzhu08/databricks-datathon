# ACQ-D02: prepare an authorized local facility export

Use this path when an authorized teammate can export the installed source but the integration chat cannot query it. `prepare_local_export.py` reuses `map_base`, `profile_rows` and `verify_base_export`; it does not query Databricks or infer an original table/schema. Issue #6 still owns live workspace acceptance.

## Supported input

Supply a UTF-8 **JSON array of row objects** (`--format json`) or **JSONL with one row object per line** (`--format jsonl`). JSONL accepts LF/CRLF and an optional final newline; internal blank lines are rejected. Nested objects/arrays, nulls, booleans, Unicode, whitespace inside text, and escaped multiline strings are preserved. Missing keys remain missing, and explicit nulls remain null. Do not supply a query-response envelope, CSV, an Excel conversion, a sampled display table, or multiple concatenated JSON arrays.

IDs must be nonempty strings or integers in an explicitly mapped source column. Keep leading-zero IDs as quoted strings. The canonical `facility_id` is the unchanged string ID or text representation of the integer; the original value and every original field remain inside `source_row`. Duplicate IDs—including identical repeated rows and integer/string collisions such as `1` and `"1"`—fail without dropping rows. Missing IDs fail; this adapter never invents a surrogate. Coordinate errors are profiled but never silently repaired.

This preserves JSON values and the **exact original file bytes**. It does not recover SQL types or values already lost by an exporter. Fractional numbers must round-trip through the Python JSON representation without changing their decimal value; excessively precise values, overflow and underflow fail. Export exact decimals as strings and retain the source schema/type receipt. Dates/timestamps, binary, and non-finite source values need explicit lossless JSON representations. The existing `json_value` helper preserves decimals as decimal text, dates/timestamps as ISO strings, binary as marked base64 and non-finite numbers as marked strings; retain the observed source schema alongside that export. JSON `NaN`/`Infinity`, malformed/truncated input, duplicate object keys, invalid UTF-8 and lone Unicode surrogates are rejected.

The adapter records observed **JSON** field types separately; it leaves the Databricks schema, directly observed Delta version and live inspection timestamp null. Any supplied Delta version is labeled `reported_delta_version`, never a direct observation by this process.

## Obtain the input through authorized access

An operator should select the actual installed table in Catalog Explorer and record its full `catalog.schema.table` name. Use normal supported authentication and export controls. The automated-browser warning is not an invitation to extract session tokens. Do not place real rows in an issue, PR, chat log or Git.

The existing [workspace setup](README.md#workspace-preparation-and-minimal-access) supports a practical bounded JSON export. In a manually operated notebook with the repository and dependencies installed, set the actual values below and run:

```python
import sys
from datetime import datetime, timezone

# Replace these placeholders with observed/permitted values.
sys.path.insert(0, "/Workspace/ACTUAL_REPO/databricks/enrichment")
from source_inspection import inspect_table, json_value, write_new_json

source_table = "CATALOG.SCHEMA.TABLE"
export_dir = "/Volumes/CATALOG/SCHEMA/VOLUME/NEW_EXPORT_DIRECTORY"
rows, receipt = inspect_table(spark, source_table, max_rows=500000)
# inspect_table pins readable Delta history; otherwise it records a single-read export.
# A table exceeding the bound fails, rather than returning a truncated success.
receipt["exported_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
receipt["export_file_sha256"] = write_new_json(export_dir + "/facilities.json", json_value(rows))
write_new_json(export_dir + "/source_receipt.json", receipt)
print({"row_count": receipt["row_count"], "exported_at": receipt["exported_at"],
       "observed_delta_version": receipt["observed_delta_version"],
       "export_file_sha256": receipt["export_file_sha256"]})
```

Download the two files through the approved Volume/file interface into ignored `data/local/` storage. Keep `source_receipt.json` with the original input as the source type/version/count receipt. Verify the downloaded raw file hash against that receipt before use. Map fields from the actual schema, never from the synthetic examples. Do not run this example with placeholder names and report them as real tables. If the source requires a filtered pilot, make that selection explicitly in an authorized export, record its predicate/scope and count from the same snapshot, and preserve every selected row/field.

For an exporter that already produces JSONL, [Spark's JSON writer](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrameWriter.json.html) writes one row per line. Preserve explicit nulls with `ignoreNullFields=false`, retain all source fields/types, and account for every part file. This adapter takes one file; concatenate complete JSONL part files with line boundaries and retain the part-file manifest/hashes. Never concatenate JSON arrays. [Notebook downloads](https://docs.databricks.com/gcp/en/notebooks/notebook-outputs) and [SQL editor downloads](https://docs.databricks.com/aws/en/sql/user/sql-editor/results) may be CSV/Excel rather than the required lossless JSON; request a supported export instead of using a spreadsheet's inferred ID types. If an interface truncates or samples results, follow the partial-export rules below.

## Run locally

Use the existing scoped Python environment from [README.md](README.md#local-setup-and-checks). No new dependencies are required. Save the observed mapping as JSON in the approved local input directory. The mapping supports `id`, `name`, `state`, `type`, `pin`, `latitude`, `longitude`, and `evidence` (a list of original text-column names). `id` is mandatory. This example is entirely synthetic:

```json
{"id":"source_id","name":"source_name","evidence":["original_description"]}
```

Run from the repository root, replacing paths, table, operator, time, count and scope with actual observations. The adapter treats scope as descriptive text, never SQL:

```sh
source databricks/enrichment/.venv/bin/activate
python databricks/enrichment/prepare_local_export.py \
  --input data/local/source-export/facilities.json --format json \
  --source-table CATALOG.SCHEMA.TABLE \
  --mapping data/local/source-export/mapping.json \
  --operator OPERATOR_HANDLE --exported-at ACTUAL_UTC_TIME_ENDING_IN_Z \
  --completeness complete --expected-row-count ACTUAL_SELECTION_COUNT \
  --scope 'Actual full-table or filtered selection, including any predicate' \
  --output-dir data/local/base-exports/NEW_RUN
```

Optional `--reported-delta-version N` records a version supplied by the operator. Omit it if unobserved. `--max-rows` defaults to 500,000 and `--max-bytes` to 512 MiB; limits may be lowered, never bypassed by silent truncation. Oversized inputs need a deliberately bounded selection and scope/count receipt. Empty exports are rejected because they cannot establish the observed ID mapping for a pilot.

Exit 0 means the local package passed readback verification. Exit 1 means validation/file failure; argparse usage errors use exit 2. Standard output contains only counts, hashes, completeness and `live_databricks_verified=false`. Errors do not echo source rows. Source names, mapping and operator details remain in approved artifacts.

## Complete, partial and unknown exports

- `complete`: the operator supplies an independent count for the **stated selection**, and the parsed row count must match. A complete Rajasthan selection is not a complete national table; record that scope explicitly. The CLI cannot prove the operator's count or predicate is truthful.
- `partial`: an intact but incomplete selection is usable for a limited local pilot. Supply the expected selection count if known; it must exceed the parsed count. Metadata records the missing count. Omit the expected count when unknown; missing count remains null. Recover missing rows into a new export/run before claiming full-selection coverage.
- `unknown`: use when completeness cannot be established, even if a displayed/exported count happens to match. Counts cover the supplied rows only. Do not relabel it complete based on the adapter's success.

No completeness flag rescues syntactically truncated JSON/JSONL or a malformed final row. Re-export the file; do not trim damaged rows until it parses. A result-table row cap, omitted part files or missing records must remain explicit. C's matches and coverage can concern only the exported rows. Missing source records do not establish absent services or facilities. Changing from a partial to a larger base changes the existing publication base hash: prepare a new reviewed source revision/output schema rather than silently enlarging an accepted run.

## Outputs, verification and recovery

The completed directory contains:

| File | Meaning |
| --- | --- |
| `base.json` | Source IDs plus every original exported row in `source_row`; sorted by canonical ID |
| `source_metadata.json` | Compatible existing-consumer metadata; hashes/counts/profile/mapping plus operator/export scope and completeness |
| `source_export.json` or `source_export.jsonl` | Exact bytes that were hashed and parsed, including original row order and text formatting |

`row_count` is the count of supplied rows, not an independently verified full-table count. `source_rows_sha256` is the existing order-independent canonical row hash; the operator-export section additionally records the ordered-row hash and original-byte SHA-256. Raw inputs are read once so hashing, parsing and the preserved copy use the same bytes. The source input is never modified. The original schema/type receipt remains with the operator's input and should accompany any transfer of the package.

The CLI requires a new subdirectory of this checkout's ignored `data/local/`. Files are written with mode 0600 in a mode-0700 staging directory. After hash checks and `verify_base_export` pass on the written pair, a same-filesystem directory rename publishes the final path. Existing output directories are never updated/replaced; choose a new run path for new inputs. Ordinary failures remove staging and leave no final output. A hard process termination can leave `.NEW_RUN.staging-*` and `.NEW_RUN.lock`; confirm no adapter is running before removing only that attempt's hidden remnants, then rerun the same command. Do not consume hidden staging directories.

For local verification, call the existing consumer without treating this as a live check:

```python
import sys
sys.path.insert(0, "databricks/enrichment")
from common import load
from source_inspection import verify_base_export
base = load("data/local/base-exports/NEW_RUN/base.json")
metadata = load("data/local/base-exports/NEW_RUN/source_metadata.json")
verify_base_export(base, metadata)
```

Use the prepared `base.json` with the existing `validate_batch.py --base ... --batch ...` for real matching batches. To run notebook 02 later, upload the package to an authorized Volume and set `input_path` to that directory and `original_table` to the same operator-reported table. No schema or notebook change is needed: notebook 02 checks the base-file hash, count, original fields and mapped IDs, then carries the full `source_metadata` into its run manifest. Relative artifact names in the package remain valid after relocation. Consumers/reviewers must retain the `operator_export.scope`, `completeness`, expected count and warning; the baseline coverage denominator alone describes only supplied base rows. A later workspace run is separate from this offline preparation and still requires issue #6 acceptance.

## Checks and current real-data status

`python3 -m unittest discover -s tests/databricks/enrichment -p 'test_*.py' -v` covers JSON/JSONL fidelity, leading-zero/large integer IDs, duplicate/missing IDs, explicit mapping/metadata, count/completeness rules, precision and parser errors, bounded imports, output interruption/readback cleanup, destination/lock collisions, and compatibility with the existing validator/publication consumer. Publication compatibility uses the existing SQLite simulation; it is not a live Delta test.

No approved facility export was available when this adapter was implemented. No actual Marketplace table/schema/row mapping or successful live run is claimed. E's [workspace-access check on issue #23](https://github.com/vzhu08/databricks-datathon/issues/23) reports that table names and the permitted Volume still require manual verification. A's public reference batch is not a replacement for original Marketplace base rows.
