# Virtue Foundation Marketplace source manifest

## Purpose

DATA-01 prepares the Virtue Foundation India healthcare-facility dataset for the first-pass Datathon search flow. The prepared table is the sole facility data source for dialysis, MRI, and trauma-care search in this pass.

## Source

- Provider: Virtue Foundation
- Access: Databricks Marketplace
- Marketplace listing: https://login.databricks.com/signin?intent=SIGN_IN&auto_login=true&destination_url=%2Fmarketplace%2Fconsumer%2Flistings%2F19326b3d-db63-4627-abc0-cf4e8131a305
- Source table: **fill from notebook run**
- Prepared table: **fill from notebook run**
- Inspected at: **fill from notebook run**

Do not commit Marketplace facility rows, source snapshots, workspace credentials, or patient/incident data to Git.

## Prepared contract

The preparation notebook emits one preserved upstream facility/campus candidate per row with:

- `facility_id`
- `raw_row_ref`
- `name`
- `city`
- `state`
- `pin` (string)
- `latitude`
- `longitude`
- `description`
- `capabilities`
- `procedures`
- `equipment`
- `record_source_urls`

Original evidence wording is retained. Missing or invalid coordinates are normalized to null but rows are preserved. Facilities are not deduplicated by name.

## Real raw → prepared mapping

Run `databricks/ingest/01_prepare_virtue_facilities.py` against the Marketplace table and replace the placeholders below with the notebook's resolved mapping.

| Prepared field | Raw Marketplace field |
| --- | --- |
| raw_row_ref | **TBD from live schema** |
| name | **TBD from live schema** |
| city | **TBD from live schema** |
| state | **TBD from live schema** |
| pin | **TBD from live schema** |
| latitude | **TBD from live schema** |
| longitude | **TBD from live schema** |
| description | **TBD from live schema** |
| capabilities | **TBD from live schema** |
| procedures | **TBD from live schema** |
| equipment | **TBD from live schema** |
| record_source_urls | **TBD from live schema** |

## Live quality profile

Complete from the notebook output before marking DATA-01 verified:

- Total source rows: **TBD**
- Prepared rows: **TBD**
- Jaipur rows: **TBD**
- Missing latitude: **TBD**
- Missing longitude: **TBD**
- Out-of-range latitude: **TBD**
- Out-of-range longitude: **TBD**
- (0, 0) coordinate pairs: **TBD**
- Repeated-name groups: **TBD**
- Row-count preservation check: **TBD**
- Unique `facility_id` check: **TBD**

## Campus preservation

A shared facility name is not treated as proof of duplication. The notebook reports repeated names and distinct location signatures for manual inspection and retains every upstream row unless the team later approves a campus-resolution rule.

## Handoff to RANK-01

Vincent needs:

1. Fully-qualified prepared table name.
2. Real raw → prepared mapping.
3. Completed live quality profile.
4. Confirmation that evidence text and record-source provenance are preserved.
5. Any unresolved Marketplace/schema issue that could affect search.
