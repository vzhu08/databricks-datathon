# DATA-01 · Virtue Foundation preparation

Run `01_prepare_virtue_facilities.py` as a Databricks notebook.

## Parameters

- `SOURCE_TABLE`: fully-qualified Marketplace table (required)
- `OUTPUT_TABLE`: fully-qualified prepared Delta table
- `COLUMN_MAPPING_JSON`: optional JSON object mapping prepared field names to actual raw column names

The notebook:

1. Inspects the real schema and sample rows.
2. Resolves or explicitly overrides the raw-column mapping.
3. Preserves original evidence wording and record provenance.
4. Normalizes malformed/missing coordinates without dropping the row.
5. Stores PIN as text.
6. Creates a stable `facility_id` and `raw_row_ref`.
7. Profiles missingness and coordinate quality.
8. Reports repeated facility names without deduplicating them.
9. Verifies row-count preservation and unique IDs.
10. Runs a Jaipur survival smoke check.
11. Writes the prepared Delta table.

After the live run, update `data/source-manifests/virtue_foundation.md` with the actual table names, mapping, and profile counts before DATA-01 is marked verified.
