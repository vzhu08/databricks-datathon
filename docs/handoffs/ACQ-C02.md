# ACQ-C02 handoff · building-footprint coverage on public Rajasthan locations

Developer C · `@andrewhgu` · Claude Code session `session_01LWLtujoz3kp3Vn9YqdtKp8` · November 21, 2026.

Task [#34](https://github.com/vzhu08/databricks-datathon/issues/34), branch `codex/acq-c-footprint-research`. Implementation tested at **`eb110d1fb40df5ab2d7f88b0ec61f1728f2191e1`**; this handoff is a later documentation-only commit, and the final head is recorded on the issue and PR. The remote board was reread at `df28bfb` before handoff. Changed paths: `research/geography/`, `tests/research/matching/test_coverage.py`, this file. No merge, deployment, board or shared-contract change was made.

Status: **The contributor's public-source counts below are preliminary pending replay of the corrected Google comparison on the frozen 20-point sample.** The original run inspected each coordinate's centre cell. A radius extending across a cell boundary can require additional files. Version 1.1 records those cells and binds each accepted comparison to the sample and extract hashes. The real-campus audit remains open in [#5](https://github.com/vzhu08/databricks-datathon/issues/5).

### Replay requested from Andrew

Run these commands with the updated geography code on the machine holding the frozen artifacts. They create a sibling output directory, retain the published Overture and imagery inputs, and rebuild the Google extraction with its original download budget. The original sample file SHA-256 is `91999ea77892483ea69ce601d959c3d485594bdcf835fddf282dd1c2be7c2a6d`.

```sh
old=data/local/geography/c02
new=data/local/geography/c02-v1.1
mkdir "$new" &&
cp "$old/sample.json" "$old/overture_buildings.ndjson" "$old/imagery.json" "$new/" &&
python -m research.geography.open_buildings --sample "$new/sample.json" --output "$new/google_buildings.ndjson" --manifest "$new/google_manifest.json" --max-bytes 4000000000 &&
python -m research.geography.coverage measure --sample "$new/sample.json" --overture "$new/overture_buildings.ndjson" --release 2026-11-18.0 --google "$new/google_buildings.ndjson" --google-manifest "$new/google_manifest.json" --imagery "$new/imagery.json" --output-dir "$new" &&
python -m research.geography.coverage manifest --dir "$new"
```

Report the new manifest hash, compared counts by stratum, points whose required cells were skipped, and any changes in independent-origin findings on #34. If the original files are unavailable, reconstruct the frame and verify the frozen cases hash before a new run. Label a new frame, extraction or acquisition date explicitly.

[Workflow, rules and limits](../../research/geography/README.md)

## Result in one paragraph

All 20 sampled public coordinates have a mapped building within 100 m in Overture release `2026-11-18.0`, and 16 lie inside an Overture outline. For 14 of those 16 the outline comes from OpenStreetMap, the same origin as the coordinate, so Overture alone gives independent support at only **2 of 20** points. Reading Google Open Buildings from Google's own files raises that to **14 of 20**. Two points stay inside a same-origin outline only, four have outlines nearby and none containing the point, and none has no building within 500 m. No source publishes an image date per building, so capture date is unknown for all 20.

## Sampling frame and frozen sample

- **Source:** the registered OSM health extract (`hot_osm_health`), downloaded from its registered URL with A's merged collector. The raw file hash equals A's accepted snapshot, `5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3`. Licence ODbL 1.0.
- **Geography:** the 8,191 records A's frozen rule `rajasthan-candidates-1.0.0` marks as explicitly in Rajasthan, reproduced with A's merged extractor from the OSM snapshot alone. The count equals A's handoff. A's own `explicit.json` was not available to this session, so the frame file here (`07d9c7be…8e56`) is an OSM-only envelope with a different file hash and the same rows by construction. This is the alternate frame the task allows; it has not been compared byte for byte with A's file.
- **Eligible:** 2,725 records with type `hospital`, a source name and coordinates inside A's screening rectangle. **Excluded:** 5,422 other facility types and 44 unnamed hospitals. The NHP mirror contributes no explicit Rajasthan rows and is not in the frame.
- **Strata, eligible and sampled:** `isolated_point_control` 686 and 5; `mapped_area_control` 79 and 5; `ambiguous_neighbour` 1,042 and 5; `coarse_coordinate` 14 and 5. Another 904 eligible records fit no stratum and are not sampled.
- **Selection:** inside a stratum, order by SHA-256 of `[sample version, external_facility_id]`, take five. Rule text and every count are stored in the sample.
- **Hashes:** `sample_sha256` `b56f0bc3f3fe3cb3db024b57f8db76bb7d2a49cb23e0882597ed29084d1b15c0` covers the whole document including the frame file hash. `cases_sha256` `855479cd77dbefc739c57fc5fde894587bcfa282d3b5aedbd472aec2aa394bad` covers the 20 points alone and should be equal when the sample is frozen from A's own extract.
- **Coordinate precision:** the 15 source points carry 4 to 7 decimals, about 11 m to 1 cm. The frame has no coordinate coarser than 4 decimals, so the coarse stratum is the coarsest available. The five mapped-area points are interior points computed by the producer and are not entrances.

## Coverage by stratum

Radius 500 m, distances in metres to the building outline, 0 when inside. Each row's denominator is its five sampled points.

| Stratum | Overture building within 25 m | Inside any Overture outline | Nearest Overture outline is OpenStreetMap | Inside an outline in Google's own files | Inside an outline of another origin | Same-origin outline only | Outlines nearby, point outside | No building within 500 m |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `isolated_point_control` | 5 | 5 | 5 | 5 | 5 | 0 | 0 | 0 |
| `mapped_area_control` | 4 | 2 | 0 | 2 | 2 | 0 | 3 | 0 |
| `ambiguous_neighbour` | 5 | 5 | 5 | 4 | 4 | 1 | 0 | 0 |
| `coarse_coordinate` | 4 | 4 | 4 | 3 | 3 | 1 | 1 | 0 |
| All 20 | 18 | 16 | 14 | 14 | 14 | 2 | 4 | 0 |

- With Overture alone the last four columns read 2, 14, 4 and 0 for all 20.
- The four points outside every outline are 6.5, 9.5, 35.3 and 45.0 m from the nearest one. The two same-origin-only points are 0.6 and 4.0 m from the nearest Google outline. Each of the six has its reason recorded: a point can mark an entrance, a campus centre or an address.
- All five mapped areas carry no building tag in the source, so the area itself is not an Overture building. Two of their interior points fall inside a Microsoft or Google outline and three fall between outlines.
- The 14 OpenStreetMap outlines containing a source point were last edited in 2019 (3), 2020 (10) and 2021 (1). That is an edit time and is not a capture date.
- These are counts for a rule-selected control and challenge sample. They are not a rate for Rajasthan or for the original facilities.

## Source lineage and overlap

- Every feature in the Overture extract names its upstream dataset. The 29,356 extracted features are 20,794 Google Open Buildings (dataset version `2024-04-16`), 7,407 Microsoft ML Buildings (`2026-08-11`) and 1,155 OpenStreetMap (`2026-11-01`). Only OpenStreetMap records carry an update time.
- Within 500 m of the 20 points Overture has 23,165 buildings: 16,441 from Google, 5,796 from Microsoft and 928 from OpenStreetMap.
- All 16,441 Google buildings carried by Overture appear under the same building code in Google's own v3 files. They are one origin and are counted once.
- Google's own files hold 42,812 buildings within 500 m of the points. 26,371 of them are not carried by Overture, including the outlines under most sampled points, where Overture carries the OpenStreetMap outline.
- A footprint supports building-location plausibility only when its origin differs from the coordinate's. An OpenStreetMap outline around an OpenStreetMap point adds nothing.

## Imagery

Sentinel-2 L2A scenes from the public archive, read for all 20 points. Each point is classified clear and `not_vegetated` in a scene acquired between November 14 and November 20, 2026. Fourteen points were clear in the newest scene, five in the second and one in the third. Scene cloud cover is at most 9.8 percent. Pixel size is 10 m, and 20 m for the classification layer. Every scene carries the Copernicus Sentinel data legal notice link, which is recorded per point. **This imagery cannot outline a building**, so `can_resolve_building` is false for all 20; it shows only that a recent clear observation exists. No sub-metre imagery with a usable licence was obtained.

## Commands and results

Python 3.13.18 in `research/matching/.venv`, with `research/geography/requirements.txt` added for the live steps.

```sh
python3 -m unittest discover -s tests/research/matching -p 'test_*.py' -v      # 76 passed (56 existing, 20 new)
python3 -m unittest discover -s tests/databricks/enrichment -p 'test_*.py' -v  # 72 passed, unchanged
python3 -m unittest discover -s tests/research/acquisition -p 'test_*.py' -v   # 43 passed, unchanged
git diff --check origin/main...HEAD                                            # clean
git ls-files data/local                                                        # nothing tracked
```

The 20 new tests use invented records and buildings only. Without `pyarrow` one reader test is skipped and 19 run. They cover the strata and exclusion counts, repeatable and order-independent sampling, the 20-point bound, tamper detection, each finding, same-origin and unstated lineage, Google reuse counted once, points outside the compared cells, summary denominators, the range reader against a locally written parquet file, row-group selection, the 40-point and 500 m bounds, well-known binary and text parsing, cell selection within a byte budget, scene ordering, and obstructed or missing imagery staying unknown.

Public-source run, from the repository root:

```sh
python3 -m research.acquisition.run --source osm --output-dir data/local/acquisition/public
python3 -m research.acquisition.rajasthan --snapshot data/local/acquisition/public/snapshots/hot_osm_health/5b2c0367…6deff3 \
  --national-batch data/local/acquisition/public/runs/<run_id>/batch.json --output-dir data/local/acquisition/rajasthan-osm-v1
out=data/local/geography/c02
python -m research.geography.coverage freeze --frame data/local/acquisition/rajasthan-osm-v1/explicit.json --output-dir $out
python -m research.geography.overture_read --cases $out/sample.json --release 2026-11-18.0 \
  --index data/local/geography/overture/index-2026-11-18.0.json --output $out/overture_buildings.ndjson
python -m research.geography.open_buildings --sample $out/sample.json --output $out/google_buildings.ndjson \
  --manifest $out/google_manifest.json --max-bytes 4000000000
python -m research.geography.imagery --sample $out/sample.json --output $out/imagery.json
python -m research.geography.coverage measure --sample $out/sample.json --overture $out/overture_buildings.ndjson \
  --release 2026-11-18.0 --google $out/google_buildings.ndjson --google-manifest $out/google_manifest.json \
  --imagery $out/imagery.json --output-dir $out
python -m research.geography.coverage manifest --dir $out
```

- The Overture read, the Google read and the measurement were each run twice and gave the same bytes.
- **The DuckDB script from `research.geography.overture` was generated for the sample (SHA-256 `ece65f24…dc8b`) and not executed**: the DuckDB extension host is blocked in this environment. `overture_read` applies the same bounding-box predicate and column list to the same release files. The two have not been compared on live output.
- Release `2026-11-18.0` exists in the public bucket with 512 building files, 2,544,125,628 rows and 277.6 GB. The registry's release prefix is therefore verified as present.

## Access, cost and blockers

| Step | Transferred | Time | Notes |
| --- | ---: | ---: | --- |
| OSM health extract | 9.5 MB | 64 s | Registered URL, no credentials |
| Overture footers, once per release | 700.6 MB | 88 s | 512 files, 80,384 row groups, cached locally |
| Overture bounded read | 131.1 MB | 51 s | 9 files, 24 row groups, 968,898 rows scanned, 60 requests |
| Google Open Buildings | 3,885.7 MB | about 3.5 min | 11 level-6 cells streamed once, 40,793,668 rows read, 75,589 kept |
| Sentinel-2 details | a few MB | 30 s | One value per scene and point |

No paid service, account or credential was used. The Google comparison is the only heavy step; its default budget is 1.6 GB, which covered 12 of the 20 points, and this run raised it to cover all 20. Blocked in this environment: the DuckDB extension host, the Overture documentation and catalogue sites, Overpass and Nominatim. None was needed for the result.

## Local artifacts for A and D

Under ignored `data/local/geography/c02/` in this session's checkout. The session's storage is temporary, so the files are reproducible from the commands above and are not a durable hand-over location. `manifest.json` lists each file with its hash and size.

| File | SHA-256 |
| --- | --- |
| `sample.json` | `91999ea77892483ea69ce601d959c3d485594bdcf835fddf282dd1c2be7c2a6d` |
| `overture_buildings.ndjson` | `7aedb83d4fceeab4b426d07c086dbd49da688fd11028533f636868be6fb15ec1` |
| `google_buildings.ndjson` | `448fc913fdd500120b37a16c8bdd9554c27f6410490dd8550469f0529d8abd76` |
| `google_manifest.json` | `a55d045f05dc4a645615b0d87e6305c8fb297befe4807e24567a0059acade80e` |
| `imagery.json` | `928218938921d848c9ab5d5c8273da6707cb30e54041209ef367e386e4d1ef12` |
| `observations.json` | `e1ab8a4cf45c62c2f8063c237b0871eb563f71db6a12fd32269c34817cbfbee5` |
| `summary.json` | `9acc4b7776217ab9b287ae9dfd583acf0195e205f5e57f3553d04e85fcfa6fc7` |
| `manifest.json` | `dc3f54eab6aa15b0e6cab7c521f18eb1795c14e71d44313720075b014826ca41` |
| `data/local/geography/overture/index-2026-11-18.0.json` | `186eb14d7058870d80652d09aaa73a282f8ccdbaeb92e7b728a86d0c8cbf8acb` |

The files derive from OpenStreetMap (ODbL 1.0), Overture Maps, Google Open Buildings (CC BY 4.0 and ODbL 1.0 as recalled from its dataset page, which was not reachable from this session) and Copernicus Sentinel data. Overture labels all three upstream datasets in this extract `ODbL-1.0`. Confirm each source's terms before moving a file to another environment. Nothing from the run is in Git.

## Requests and notes for other owners

- **A:** freezing from your own `explicit.json` should give `cases_sha256` `855479cd…4bad`. A different value means the frame rows differ and is worth a look.
- **D:** no batch is emitted. Observations are a local ledger with no evidence rows, because nothing here is linked to a campus pair or reviewed. The ACQ-C01 observer remains the path to contract evidence.
- **Integration lead:** for the real audit in #5, plan on Google's own files as the second source. Overture alone will mostly return the OpenStreetMap outline wherever the external record came from OpenStreetMap.

## Limits

- A mapped roof is location context. It does not show a hospital, a service or current operation.
- Twenty rule-selected points from one source family. No population estimate, no interval.
- Machine-derived outlines can be missing, merged or split. Absence is unknown and no point was treated as a negative finding.
- A point inside a Google outline and an OpenStreetMap outline has one independent origin beyond its own. Both were drawn from imagery, by a person and by a model.
- The Google dataset version differs between Overture's copy (`2024-04-16`) and Google's own v3 files (published June 2023). Records were matched on the published building code.
- The Google extract keeps buildings whose published centre is within 600 m of a point, so a very large building centred further away could be missed.

Submission status: not attempted.
