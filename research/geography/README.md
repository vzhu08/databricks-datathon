# Building-footprint coverage on public locations (ACQ-C02)

This measures how often a public reference coordinate has a mapped building next to it, how far away the nearest one is, and where each building record came from. It supports one narrow statement: a building is mapped at this place by a source other than the one that supplied the coordinate. It links nothing to an original facility row and says nothing about services, quality or whether a facility operates there.

The matching workflow, the coordinate screening and the per-match footprint check from ACQ-C01 are documented in [`research/matching/README.md`](../matching/README.md).

## Install

Sampling, measuring and the tests use the standard library plus the `jsonschema` pin from `research/matching/requirements.txt`. The three live steps need the extra pins here:

```sh
source research/matching/.venv/bin/activate
python3 -m pip install -r research/geography/requirements.txt
```

All real inputs and outputs stay under ignored `data/local/` or an authorized Volume.

## Steps

```sh
out=data/local/geography/c02

# 1. Freeze the sample from one external batch (here A's explicit Rajasthan extract).
python -m research.geography.coverage freeze --frame data/local/acquisition/rajasthan-v1/explicit.json --output-dir $out

# 2. Bounded building read from one pinned Overture release.
python -m research.geography.overture_read --cases $out/sample.json --release 2026-11-18.0 \
  --index data/local/geography/overture/index-2026-11-18.0.json --output $out/overture_buildings.ndjson

# 3. Optional: bounded Google Open Buildings comparison and Sentinel-2 imagery details.
python -m research.geography.open_buildings --sample $out/sample.json --output $out/google_buildings.ndjson \
  --manifest $out/google_manifest.json
python -m research.geography.imagery --sample $out/sample.json --output $out/imagery.json

# 4. Measure.
python -m research.geography.coverage measure --sample $out/sample.json --overture $out/overture_buildings.ndjson \
  --release 2026-11-18.0 --google $out/google_buildings.ndjson --google-manifest $out/google_manifest.json \
  --imagery $out/imagery.json --output-dir $out
```

`freeze` refuses to overwrite an existing `sample.json`. The other steps give byte-identical files for the same inputs.

## The frozen sample

The frame is every external record in the supplied batch. A record is eligible when its type is `hospital`, it has a source name, and its coordinates are finite and inside A's Rajasthan screening rectangle (longitude 69.4 to 78.35, latitude 23.0 to 30.25, which is not a state boundary). Each eligible record gets the first stratum that applies:

| Stratum | Role | Rule |
| --- | --- | --- |
| `mapped_area_control` | control | The coordinate is the producer's interior point of an area mapped in the source. |
| `coarse_coordinate` | challenge | A source point with at most 4 decimals on either axis, about 11 m or coarser. |
| `ambiguous_neighbour` | challenge | A source point with another frame record of a different name within 150 m. |
| `isolated_point_control` | control | A source point with at least 6 decimals on both axes, a name used once in the frame and no other frame record within 500 m. |

Other eligible records are counted and not sampled. Inside a stratum the order is the SHA-256 of `[sample version, external_facility_id]`, and the first five are taken, so the sample has at most 20 points. `sample.json` records the frame's snapshot hashes, every exclusion count, the size of each stratum and `sample_sha256`, the hash of the whole document. Names are not copied into the sample.

## Building sources

`overture_read` applies the predicate of the DuckDB script written by `research.geography.overture`: a building's bounding box touches the 500 m box around a listed point, for at most 40 points, selecting `id`, `sources`, `subtype`, `class` and geometry. It reads each release file's footer once over HTTPS range requests, caches the row-group bounding boxes in `--index`, then reads only the row groups that can touch a box. Use it where the DuckDB `httpfs` and `spatial` extensions cannot be installed. No height, floor count or area is read.

`open_buildings` reads Google Open Buildings v3, published as one compressed CSV per level-6 S2 cell. It covers each search rectangle, including the 100 m margin for published building centres. It gives priority to cells intersecting the most sample areas, then the smallest files within `--max-bytes` (default 1.6 GB). A point enters the comparison denominator only after every cell intersecting its padded rectangle has been read. The manifest lists the required cells per point. Measurement verifies the manifest version, frozen sample hash, extract hash, radius and comparison denominator. Older centre-cell manifests require a fresh Google extract.

## What is measured

For each point, per source: the number of buildings within 500 m, the count within 25, 100 and 500 m, the count by origin, the nearest building with its feature ID, distance in metres to its outline (0 inside), containment, upstream datasets and upstream record update time, and the nearest building from an origin other than the reference record's.

Upstream dataset names collapse to one origin each: OpenStreetMap, Google Open Buildings, Microsoft ML Buildings, Esri Community Maps. A Google building seen through Overture and again in Google's own files is one origin. A building with no stated lineage counts as not independent.

| Finding | Meaning |
| --- | --- |
| `inside_footprint_of_other_origin` | The point is inside a building whose origin differs from the reference record's. Supports building-location plausibility. |
| `inside_footprint_reference_origin_unknown` | A building contains the coordinate and the coordinate's lineage is unknown. Source independence is undetermined. |
| `inside_footprint_of_reference_origin_only` | Every containing building shares the reference record's origin or has none stated. No independent support. |
| `footprint_nearby_point_outside` | Buildings exist within the radius and none contains the point. Inconclusive; the distance is recorded. |
| `no_footprint_within_radius` | Nothing mapped within the radius in the sources compared. Unknown. |

`capture_date` is always null: neither source publishes an image date per building. The upstream record update time is kept separately and is an edit time.

`summary.json` reports every count with its denominator, overall and by stratum. It describes the frozen sample only and is not a rate for Rajasthan.

## Imagery

`imagery` records, per point, the newest Sentinel-2 L2A scene in which the scene classification layer marks the point as clear: acquisition time, 10 m pixel size, scene cloud cover, the class at the point and the licence link carried by the scene. It looks at up to six scenes. A point that is cloud, shadow or outside the swath in all of them stays unknown. Ten-metre pixels cannot outline a building, so `can_resolve_building` is always false; the record shows only that a recent clear observation exists.

## Limits

- A mapped roof is location context. It is not evidence of a hospital, a service or current operation.
- A point can mark an entrance, a campus centre or an address, so a point outside every outline is not a negative finding.
- Machine-derived footprints miss buildings and merge or split them. Absence is unknown.
- Where OpenStreetMap already has a building outline around a facility point, an Overture extract tends to carry only that outline there. Overture alone then adds no independent origin, and a second source such as Google's own files is needed.
- The strata are challenge and control sets chosen by rule. They are not a probability sample of facilities.
