# National identity acquisition (ACQ-A01)

This producer emits contract v1.0.0 source snapshots, external facilities, and review items. Matches and evidence arrays remain empty. It does not establish that a record matches a VF campus, independently corroborates VF, offers a clinical service, or is currently operating.

## Install and run

Python 3.9+ on macOS/Linux, with the two scoped dependencies in `requirements.txt`:

```sh
python3 -m venv research/acquisition/.venv
source research/acquisition/.venv/bin/activate
python3 -m pip install -r research/acquisition/requirements.txt
python3 -m unittest discover -s tests/research/acquisition -p 'test_*.py' -v
python3 -m research.acquisition.run --source all --output-dir data/local/acquisition/public
```

Run from the repository root. `--source osm` and `--source nhp` also work. Network access is necessary only for acquisition. Defaults are three attempts with 30-second socket/deadline checks and exponential backoff of 1/2 seconds; configurable timeout is capped at 120 seconds and attempts at five. A blocked socket can last one timeout beyond the checked wall-clock deadline. The downloader rejects credentialed URLs, HTTP downgrade redirects, unexpected status/content types, empty/oversized/truncated responses and HTML returned as data. Temporary status errors (408/429/5xx in the documented retry set) and transport errors are retried; permanent 403/404 responses are recorded without access-control workarounds. Failed sources do not prevent the other source from completing. Exit code is 1 for a partial/failed acquisition.

Source URLs and families come from `contracts/enrichment/source_registry.json`. OSM uses the registered ZIP/STAC URLs and checks the ZIP's embedded metadata against the downloaded STAC item and byte length. NHP resolves the unique GeoJSON distribution in the landing page's Dataset JSON-LD and requires the same URL in an observed anchor. No object URL is guessed. HTML/metadata changes that break those assumptions fail visibly.

## Files and handoff to C/D

All real data belongs in ignored `data/local/acquisition/` or a permitted Volume, never Git. An output directory contains:

- `attempts.jsonl`: one append-only event per HTTP attempt plus replay/acquisition failure events. No response body, exception text, headers, credentials, or facility rows. Separate from immutable snapshot metadata.
- `snapshots/<source_key>/<raw_sha256>/`: original `raw.zip` or `raw.geojson`, original metadata/landing page, `manifest.json`, `batch.json`, and `coverage.json`. The directory appears atomically after parsing and validation. Manifest hashes cover every sibling artifact, including normalized batch and coverage.
- `<source>-latest.json`: the last successful snapshot directory for that source. A failed refresh cannot overwrite this pointer or the prior snapshot.
- `runs/<run_id>/batch.json`: a self-contained contract envelope for sources accepted/replayed **in this invocation**, plus acquisition failure reviews. A failed source contributes no stale rows. `report.json` supplies separate source results, per-type coverage/dedup/conflict counts and provenance details. Previously accepted sources can be recovered through their unchanged source pointers.
- `latest-run.json`: an atomic pointer to the latest completed attempt's batch/report. Check its `status`; a partial report is not a completed acquisition. Each successful snapshot remains usable even if later aggregate writing is interrupted.

Supply the complete `runs/<run_id>/batch.json` to D's validator/importer and C's matching workflow. Every row refers to its included snapshot. `record_locator` is either `zip:<member>#/features/<zero-based-index>` or `raw#/features/<zero-based-index>`, resolving into the original bytes. The entire source feature, including geometry, all tags, specialties, original invalid PIN/coordinate values and NHP's unnormalized fields, stays in that raw artifact. The contract does not have a specialty column; coverage and `specialty_unknown` describe missingness without inventing service evidence.

This synthetic interface example uses an accepted snapshot directory from a test or prior run:

```sh
python3 -m research.acquisition.run --source nhp \
  --replay /absolute/path/to/snapshots/nhp_hospitals_mirror/<sha256> \
  --output-dir data/local/acquisition/replay
```

`--replay` is fully offline. It checks all stored hashes, the raw-byte snapshot ID, regenerates the normalized batch/coverage and checks exact equality with the accepted artifacts, then validates the shared schema and references. It retains **all** first-persisted snapshot fields, including retrieval time and artifact URI. Later attempts live only in the log. Copy the complete snapshot directory, not just its raw file, when transferring it. For a Volume transfer, keep the original manifest intact and record the new physical location in D's import/run metadata; do not silently rewrite the immutable artifact URI under the same snapshot ID. Replay requires the same parser version.

Concurrent writers to one output directory are rejected with an advisory lock. Use separate output directories for independent jobs. HTTP responses go only into a staging directory; validation/normalization failure removes staging. ZIP members are never extracted to filesystem paths. Member count and unpacked size are bounded; traversal, absolute/Windows paths, symlinks, encrypted entries, duplicate member names and CRC/truncation failures are rejected. A failed rerun preserves accepted files byte for byte.

## IDs and normalization

Canonical JSON is UTF-8, sorted keys, compact separators, with nonfinite JSON constants rejected. SHA-256 always hashes the original download bytes for a snapshot:

- `snapshot_id = source_key + ':' + SHA256(original bytes)`.
- `external_facility_id = 'acq-external:' + SHA256(canonical([snapshot_id, original_source_id, complete_source_feature]))`.
- Review IDs hash their reason and affected deterministic ID. Acquisition failure reviews additionally identify the attempt's run ID; each failed invocation is separately auditable.

The raw hash scopes every external ID to its snapshot, so the same feature in a changed source snapshot cannot overwrite an old row's snapshot reference. Retrieval timestamps never enter content-derived IDs. First occurrence locators resolve exact duplicate features; identical canonical features are removed even if input object key order differs. Conflicting variants with the same original source ID survive with distinct IDs and each receives a review item. Same names at different addresses are never deduplicated by name. OSM `node/`, `way/`, and `relation/` identifiers retain their namespaces. Missing IDs stay null; the full feature content still gives a deterministic external ID.

Names/addresses preserve their original text, apart from empty/whitespace-only values becoming null. Missing OSM native names do not fall back to translated names. Normalized names use NFKC, casefold and whitespace collapse. NHP `0` is treated as an observed missing-value sentinel in descriptive fields, not as a clinical negative. Source IDs remain literal, and invalid PINs—including `0`—become null with flags; leading-zero six-character PINs remain strings. Town is not filled from District. OSM healthcare type is preferred when informative, otherwise amenity; both original type tags are retained in quality flags and raw data. NHP care type, category and medicine system remain separately available. Unknown care type is `unknown`, not a guessed hospital classification.

Finite WGS84 points retain their original coordinates. Malformed/out-of-range coordinates become null with flags; nothing is silently swapped or repaired. The broad India envelope (longitude 68–98, latitude 6–38) flags outside-country **candidates**, including possible swaps, without asserting a political boundary test. Outside-envelope but WGS84-valid points retain their source coordinates. Polygon/MultiPolygon vertices and topology are checked, then Shapely's planar `representative_point()` produces an interior point. The method is `polygon_representative_point` for both; geometry-type and `representative_point_not_entrance` flags distinguish them. No entrance or geodesic measurement is asserted. Unsupported lines retain their original geometry externally, emit null normalized coordinates and enter review. Geometry/source-ID anomalies are queued; ordinary missing names/addresses/specialties are flagged and counted.

## Provenance and limits

OSM and NHP retain upstream families `osm`/`nhp` and `shared_origin`: another OSM derivative or another NHP mirror is not independent confirmation. Independence from the VF dataset is unassessed. OSM license comes from matching embedded/external metadata; NHP attribution/license come from the observed landing page. Attribution must travel with exported batches. Source-specific redistribution terms still apply to downstream derived databases and excerpts.

Both current sources lack a verified publication date, so `published_date` is null. OSM source-capture date and export-created/metadata-updated timestamps are separately recorded in manifest provenance. NHP mirror modification date is separate from its unknown upstream as-of date; `2025` in the filename is not promoted into a precise date. Neither download time nor historical source date establishes current clinical availability.

Coverage reports include input and deduplicated output denominators by source/type, populated name/address/specialty/coordinate counts, missing/invalid/unavailable coordinates, outside-envelope candidates, distinct IDs, exact repeats and conflicting variants. The public results and exact reusable artifact locations are in `docs/handoffs/ACQ-A01.md`. Fixture passes, public acquisition, live Databricks checks and submission status must be reported separately.
