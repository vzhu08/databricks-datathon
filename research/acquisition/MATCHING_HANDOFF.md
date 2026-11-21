# Portable matching inputs

`matching_handoff` preserves the accepted national batch and both Rajasthan extracts byte for byte. It replays the original snapshots, verifies their union against the pinned national batch, replays regional selection, and resolves district values through each accepted external row's original raw-feature locator. It never joins raw rows by a potentially repeated source identifier.

The packet has seven files: `national.json`, `explicit.json`, `additional_review.json`, `districts.json`, `coverage.json`, `provenance.json`, and `manifest.json`. The three batch hashes/counts are pinned in [matching_inputs.json](matching_inputs.json). Raw source files and contact values are excluded. Original snapshot timestamps, IDs, URLs, attribution, license and historical `artifact_uri` values stay unchanged. `provenance.json` records the raw-file replay requirement separately; a copied packet does not claim its historical absolute URI resolves on the recipient's machine.

Join `districts.json`'s `rows` to an external batch on `external_facility_id`. District values/codes preserve the observed source types and spelling; missing values and NHP zero placeholders become null. `record_locator`, `snapshot_id`, `raw_sha256`, `district_field` and `district_code_field` identify the source of each value. These labels are not validated contemporary boundaries or evidence of a campus match. There are no explicitly classified institutional switchboard fields in the observed snapshots. Generic telephone, personal/mobile, nodal and service-specific contact values are excluded.

## Build and transfer verification

From this repository, with `research/acquisition/requirements.txt` installed:

```sh
python -m research.acquisition.matching_handoff build \
  --snapshot data/local/acquisition/public/snapshots/hot_osm_health/5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3 \
  --snapshot data/local/acquisition/public/snapshots/nhp_hospitals_mirror/058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47 \
  --national-batch data/local/acquisition/public/runs/0eac1025996c46409dd3b07aeca8e283/batch.json \
  --regional-dir data/local/acquisition/rajasthan-v1 \
  --output-dir data/local/acquisition/matching-handoff-v1
python -m research.acquisition.matching_handoff verify \
  --directory data/local/acquisition/matching-handoff-v1 \
  --manifest-sha256 7bcf4d94cbd22c2a6bdb624c576364680f029b0b183735718299d4798848cd78
python -m research.acquisition.matching_handoff archive \
  --directory data/local/acquisition/matching-handoff-v1 \
  --manifest-sha256 7bcf4d94cbd22c2a6bdb624c576364680f029b0b183735718299d4798848cd78 \
  --output data/local/acquisition/matching-handoff-v1.zip
```

The ZIP's SHA-256 is `8d4931d42a0aab9b1e39964695729b68e1ab9c4bc4a59c8032242c5efad1cfce` (29,150,782 bytes). Verify that hash before extracting into a new directory, then run `verify` with the manifest hash from this handoff. Verification checks hashes, counts, contract envelopes, regional replay, sidecar keys/locators/raw hashes and coverage. It does not reproduce district extraction without the original raw snapshots. `build` provides that deeper replay. Existing different output files are refused.

## Databricks delivery

On November 21, 2026, the user authorized creation and delivery in their signed-in [workspace](https://dbc-8e9d86de-9a34.cloud.databricks.com/?o=7474658456464525). The managed Volume is `workspace.datathon_acquisition.matching_inputs`.

```text
/Volumes/workspace/datathon_acquisition/matching_inputs/acq-a03-7bcf4d94/
/Volumes/workspace/datathon_acquisition/matching_inputs/archives/matching-handoff-v1.zip
```

All seven files and the ZIP were downloaded through the authenticated CLI and independently hashed after upload. All matched. The three teammates explicitly named by the user received `USE_CATALOG`, `USE_SCHEMA` and `READ_VOLUME`; permissions were read back. Recipient login was not impersonated. The immutable packet's `coverage.json` describes its local build state; the later upload receipt records delivery.

With an authenticated Databricks CLI profile, copy the packet to a new local directory and verify it:

```sh
databricks fs cp \
  dbfs:/Volumes/workspace/datathon_acquisition/matching_inputs/acq-a03-7bcf4d94 \
  data/local/acquisition/received-a03 --recursive --profile YOUR_PROFILE
python -m research.acquisition.matching_handoff verify \
  --directory data/local/acquisition/received-a03 \
  --manifest-sha256 7bcf4d94cbd22c2a6bdb624c576364680f029b0b183735718299d4798848cd78
```

The CLI requires the `dbfs:/Volumes` prefix ([official file commands](https://docs.databricks.com/aws/en/dev-tools/cli/reference/fs-commands)). No original Marketplace rows, table publication or compute jobs are part of this delivery.

## Separate ADIP institutional reference

The [DEPwD listing](https://depwd.gov.in/en/document-category/cochlear-implant/) links the supplied [ADIP PDF](https://cdnbbsr.s3waas.gov.in/s3e58aea67b01fa747687f038dfde066f6/uploads/2023/12/202406281743840120.pdf). The bounded extraction covers the six Rajasthan rows on PDF page 16, serials 146–151. It preserves only serial, state and institutional name/address, with raw hash and page/table/row/serial locators. Doctor, contact and email columns are not emitted. Audited split offsets preserve the exact original cell's name and address substrings, including source spelling and line breaks.

Install the optional [PDF dependencies](requirements-pdf.txt) in a separate Python 3.12 environment. The supplied raw PDF, receipt and six-row audit are ignored local artifacts:

```sh
python -m research.acquisition.adip \
  --pdf data/local/acquisition/adip/source/panel.pdf \
  --metadata data/local/acquisition/adip/source/receipt.json \
  --audit data/local/acquisition/adip/audit.json \
  --output-dir data/local/acquisition/adip/reference-v1 \
  --explicit-batch data/local/acquisition/rajasthan-v1/explicit.json \
  --overlap-output data/local/acquisition/adip/exact-name-overlap.json
```

The parser scans only the explicitly audited page scope, requires the observed six-column layout, skips repeated headings and fully blank institutional cells, and refuses missing states, stale hashes and unaudited splits. It does not fill down states or normalize source spelling. Other pages contain continuation layouts outside this bounded extraction; this is not a validated nationwide parser. A separate exact normalized-name comparison retains source IDs and emits candidates only, never campus matches.

The website lists December 5, 2023; the PDF's own issue/as-of date is unverified, so the contract publication date stays null and the listing date is retained separately. The PDF filename is not interpreted as a date. The [copyright policy](https://depwd.gov.in/en/copyright-policy/) requires permission for reproduction. Permission has not been established: the PDF and extracted reference remain in local research storage and are not in the shared Volume or matching ZIP. This panel establishes neither current services nor DHIS milestones and is separate from the held-out ESI reference.
