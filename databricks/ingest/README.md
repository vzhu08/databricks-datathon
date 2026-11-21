# DATA-01 · Virtue Foundation preparation

Run `01_prepare_virtue_facilities.py` as a Databricks notebook.

## Parameters

- `SOURCE_TABLE`: fully-qualified Marketplace table (required)
- `repo_root`: path to the Workspace Git folder containing the enrichment helpers
- `OUTPUT_TABLE`: fully-qualified name for a new prepared Delta table. Use a fresh versioned name on a subsequent run.
- `COLUMN_MAPPING_JSON`: optional JSON object mapping prepared field names to actual raw column names

The notebook:

1. Inspects the real schema and sample rows.
2. Resolves or explicitly overrides the raw-column mapping.
3. Preserves original evidence wording and record provenance.
4. Normalizes malformed/missing coordinates without dropping the row.
5. Stores PIN as text.
6. Preserves existing text/integer source IDs. For an ID-less table of up to 500,000 rows, uses the same namespaced raw-row surrogate as the enrichment pipeline. Duplicate or blank mapped IDs require inspection.
7. Profiles missingness and coordinate quality.
8. Reports repeated facility names without deduplicating them.
9. Verifies row-count preservation and unique IDs.
10. Runs a Jaipur survival smoke check.
11. Writes the prepared Delta table.

After the live run, update `data/source-manifests/virtue_foundation.md` with the actual table names, mapping, and profile counts before DATA-01 is marked verified.

The local integration check runs the notebook with synthetic Spark tables, writes and reads Delta, checks preserved IDs and evidence, and exercises the destination guards. With PySpark 3.5, Java 17, and Delta Lake 3.3 configured, run `python tests/ingest/spark_smoke.py` from the repository root.
