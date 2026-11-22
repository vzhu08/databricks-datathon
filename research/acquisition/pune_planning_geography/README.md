# Reproduce the Pune Storm planning geography

The Storm planning simulation uses 12 mapped Pune locations with agreement between two public data sources. The geography supplies fixed anchors for modeled travel. Demand, facility capabilities, staffed capacity and travel are simulation inputs. The agreement measures names and mapped positions, and source independence is unknown. Treat entrances, current operations, and services as unverified.

This recipe reproduces the original geographic roster. A separately pinned variant adds two civic-address matches and reviews operator evidence for four care classes. [Pune evidence-enriched v1](PUNE_EVIDENCE_ENRICHED_V1.md)

## Why Pune

The national comparison applied the same 735 India ADM2 shapes to all 10,088 original Virtue Foundation (VF) occurrences. Pune led with 267 named-in-area occurrences and 177 occurrences with an admitted point cluster within one district. The next district, Ahmadabad, had 251 and 173, respectively. Neither measure establishes physical-site uniqueness. The 7,895 of 10,088 national named-in-area result measures supported area geography. [National district comparison](https://github.com/vzhu08/databricks-datathon/issues/323#issuecomment-7081734925)

The separate public-only OSM extraction ranked Bangalore first with 1,108 mapped named hospital sites and Pune second with 934. It processed 139,664 export features and measured 50,918 mapped named sites under its deduplication rule. Of these, 50,908 had one district across 714 nonempty districts and 10 had no unique district. The reproduction below uses the three public sources only.

## Get the pinned public inputs

| File | Publisher and edition | SHA-256 |
| --- | --- | --- |
| `india-health.zip` | Humanitarian OpenStreetMap Team (HOT), Geofabrik OSM snapshot 2026-10-09, oex 0.4.16 | `5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3` |
| `india-adm2.geojson` | geoBoundaries `IND-ADM2-76128533`, India 2021 districts, revision `9469f09` | `8bef6929fd65432e7dc775e7c44473e84efff064ebddbfd6b834e6291546db40` |
| `hospital_directory.csv` | National Health Portal (NHP) via Open Government Data Platform India, resource `98fa254e-c5f8-4910-a19b-4828939b477d`, revision `14506484` | `1ddcad9f9b922142a4374c7b89b70fb6cefd8a257448c70a61e1c07d98845134` |

Run from the repository root with Python 3.12. This example uses a Bash shell and a temporary directory outside the checkout for all inputs and outputs.

```bash
data_dir="$(mktemp -d)"
curl -fL 'https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/health_facilities/hotosm_ind_health_facilities_osm_geojson.zip' -o "$data_dir/india-health.zip"
curl -fL 'https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09592ced973a3448cf66b6100b741b64c0d/releaseData/gbOpen/IND/ADM2/geoBoundaries-IND-ADM2.geojson' -o "$data_dir/india-adm2.geojson"
curl -fL -A 'Mozilla/5.0' 'https://www.data.gov.in/sites/default/files/datafile/hospital_directory.csv' -o "$data_dir/hospital_directory.csv"

python3.12 -m venv "$data_dir/venv"
python="$data_dir/venv/bin/python"
"$python" -m pip install -r research/acquisition/pune_planning_geography/requirements.txt
"$python" -m research.acquisition.pune_planning_geography.rank_hospitals \
  --osm "$data_dir/india-health.zip" --boundaries "$data_dir/india-adm2.geojson" \
  --output-dir "$data_dir/osm"
"$python" -m research.acquisition.pune_planning_geography.match \
  --osm-roster "$data_dir/osm/pune-full.storm-roster-v1.json" \
  --boundaries "$data_dir/india-adm2.geojson" --nhp "$data_dir/hospital_directory.csv" \
  --output-dir "$data_dir/agreement"
```

The CLIs check input hashes before parsing, including the OSM intermediate. All three downloads matched on November 22, 2026. The HOT export URL and the legacy NHP CSV URL can change in place. If a download differs, request the recorded edition through the HOT catalogue or the NHP resource's publisher contact, or use a lawfully retained copy with the same hash. Treat a newer download, or a separately rebuilt OSM extract, as a new edition. [HOT export catalogue](https://data.humdata.org/dataset/hotosm_ind_health_facilities) · [HOT build report](https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/health_facilities/hotosm_ind_health_facilities_report.html) · [NHP catalogue and publisher contact](https://www.data.gov.in/resource/national-hospital-directory-geo-code-and-additional-parameters-updated-till-last-month)

## How the replay works

1. Read `health_facilities.geojson` from the HOT ZIP. Keep hospital-tagged points or outlines with a usable name and assign a district when exactly one polygon covers the source point or the outline's interior point. Deduplicate literal OSM object IDs. Within each district, collapse groups with a shared normalized name when each pair overlaps or falls within 150 m. Prefer an outline, then the lexically first typed ID. The national report also shows 50 m and 250 m sensitivity. Pune uses `shapeID=76128533B71380851181380`.
2. Parse WGS 84 point pairs from the NHP CSV as latitude, longitude. Screen against the Pune polygon and the printed Maharashtra and Pune labels. Group exact normalized names and point pairs. Fold Unicode and case, coalesce dotted initials, normalize punctuation and plural hospital, and remove terminal company suffixes. Keep branch and locality words. Of 30,273 official listings, 10,843 had a valid coordinate pair, 471 fell in Pune alone and 201 grouped sites met the publisher-label and unique-coordinate screens.
3. Examine exact normalized names with distinctive tokens in both sources. Require a unique site group for the name and a unique coordinate in both sources, a mapped-point separation of at most 100 m, and no variant-name rival within 300 m in either source. A variant rival shares a subset or superset of the distinctive tokens. The 192 shared name keys yielded 15 agreements. For the planning subset, start with the site with the most agreements within 12 km. Repeatedly select the site in that radius that maximizes its minimum distance to the chosen anchors, with a 200 m separation floor and OSM ID tie-break. Twelve sites were selected, comprising eight mapped points and four outline interior anchors.

Check the output hashes reported by the CLIs. The nationwide ranking and screening counts are in each stage's `report.json`. Keep generated records in the local output directories.

| Output | SHA-256 |
| --- | --- |
| `osm/pune-full.storm-roster-v1.json` | `31a26839d0122ec532cc8c41c261198b3df984c79e405689b27a49700533d439` |
| `agreement/pune-planning-agreement-roster.storm-roster-v1.json` | `b62f377a61f9dee796ff0a4c56afcad96195a3ad196c1e4806dcc8c119e63f35` |
| `agreement/pune-planning-agreement-sites.json` | `5cb4b231db5b8ee1aecb0a4155bc16935948c7fae7db09fdac7acc1cda179978` |

The replay used Python 3.12.10, Shapely 2.1.2 and GEOS 3.13.1. The OSM stage fixes CRLF and the agreement stage fixes LF to reproduce the frozen files across platforms. Run the synthetic checks with the same environment.

```bash
"$python" -m unittest research.acquisition.pune_planning_geography.test_replay
```

## Attribution for maps and recordings

On the map and while its geography is visible in a recording, show **© OpenStreetMap contributors (ODbL 1.0)** and the corresponding link or URL. Credit **Humanitarian OpenStreetMap Team, via Geofabrik and oex** for the export. For the district geometry, credit **geoBoundaries / Pathways Data Pvt. Ltd. / Local Government Directory**. The pinned India ADM2 edition lists ODbL 1.0. Credit **National Health Portal, Government of India, via data.gov.in** for the name and position comparison under the Government Open Data License – India. [OSM attribution](https://www.openstreetmap.org/copyright) · [OSMF display guidance](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines) · [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) · [India ADM2 terms](https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/) · [GODL-India](https://www.data.gov.in/Godl)

Keep the source credits and this recipe with the map. When publicly using an OSM-derived database or a produced work based on it, follow ODbL §4.6 by offering the derived database or a reproducible account of its alterations. If the pinned inputs leave public download, an appropriately licensed out-of-Git distribution may be needed for exact replay. See the project issue for release custody and decisions. [ODbL §4.6](https://opendatacommons.org/licenses/odbl/1-0/) · [Storm planning issue](https://github.com/vzhu08/databricks-datathon/issues/323)
