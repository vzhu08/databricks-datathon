# Local presenter handoff

The loopback wrapper opens the existing Storm planning view with the four-class condition table, pinned public provenance and offline Pune map used in the Windows rehearsal. Oliver owns demo and release decisions. [Transfer on #40](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7082140192)

The source bundle is based on main at `b9ef14ecfb304694e41264e5b3b8f04c4b00339e`. The rehearsal began with app archive `0e949b54476ff9ba17095fbd6c3a5573d7eac433`. Its final staged Storm page, plan validator and allocator match the bundle base byte for byte. The wrapper imports the checked-out app. [Allocator #328 at `83c8ed8`](https://github.com/vzhu08/databricks-datathon/pull/328) · [Renderer #329 at `848f219`](https://github.com/vzhu08/databricks-datathon/pull/329) · [Independent audit #327 at `9c931d0`](https://github.com/vzhu08/databricks-datathon/pull/327)

## View the handed-off UI

Use Python 3.12 from the repository root. The Windows rehearsal used Streamlit 1.67.0. On macOS, create and activate a fresh environment.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r app/requirements.txt 'streamlit==1.67.0'
```

In the authorized Databricks account, download these three editions using the paths in their custody receipts. Verify the downloads against the member hashes. Stage them in a directory outside the checkout.

| Operator file | Downloaded member | SHA-256 |
| --- | --- | --- |
| `plan.json` | `plan.json` from the [mixed rehearsal](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7082126854) | `20bcdae96fc0368f8119d24317d1b0a31035ba38b3ff1a4b6d1cd09d44ccdc38` |
| `approved-local-provenance-roster.json` | `pune-evidence-enriched-v1.storm-roster-v1.json` from the [enriched roster](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7082022225) | `a9c15cc82590ce3272b006562cad61e92de5d97cba9cbdb5752797839b762047` |
| `plan-evidence.json` | `pune-evidence-enriched-v1.service-provenance-v1.json` from the [enriched roster](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7082022225) | `fa7a23dfb3c9ae47b338b37cfd0f2993ab1f486142edbcafbfbfc49972323748` |
| `pune-roads-v1.geojson` | Same name from the [road edition](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7082183710) | `e1278e1a5a4038d419bd1a73aa5a24250b454d634d789f21e9c3fb6434bd1d5f` |
| `pune-map-context-v1.geojson` | Same name from the [road edition](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7082183710) | `f0fff12d6335178dacac3ba15ea7613cadf59f50a455295d51456a104422611d` |

For example, with the three downloads grouped as `mixed`, `enriched` and `roads` next to the checkout, copy and launch with the following commands. Use the original `pune-roads-v1.geojson` member from the road edition.

```sh
downloads=../datathon-operator-downloads
assets=../datathon-presenter-assets
mkdir -p "$assets"
cp "$downloads/mixed/plan.json" "$assets/plan.json"
cp "$downloads/enriched/pune-evidence-enriched-v1.storm-roster-v1.json" "$assets/approved-local-provenance-roster.json"
cp "$downloads/enriched/pune-evidence-enriched-v1.service-provenance-v1.json" "$assets/plan-evidence.json"
cp "$downloads/roads/pune-roads-v1.geojson" "$downloads/roads/pune-map-context-v1.geojson" "$assets/"
shasum -a 256 "$assets"/*.json "$assets"/*.geojson
python tools/presenter_handoff/run.py --assets "$assets"
```

On Windows, use the same source and destination names with PowerShell `Copy-Item -LiteralPath <source> -Destination <dest>` and verify with `Get-FileHash -Algorithm SHA256`. Run the same Python launcher in the activated environment. On either platform open [the local planning view](http://127.0.0.1:8501/?view=planning). The Storm switch also offers the eight-request replay. The launcher binds to loopback, uses demo finder data and disables live providers. The basemap and overlays load locally. A missing or invalid road file leaves the standard Storm renderer available.

Roads supply display context. The allocation uses simulated demand and staffed capacity, with geodesic travel modeled at 30 km/h. Public location precision and reported service scope appear beside the simulation. The map uses vendored Leaflet 1.9.4 under its [BSD 2-Clause license](map-assets/package/LICENSE). Keep visible OSM contributor and Geofabrik credit and make the displayed machine-readable layers available under ODbL when sharing the map or recording. [OSM attribution](https://www.openstreetmap.org/copyright) · [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)

## Replay and check

Use the neutral instance from the [four-class rehearsal receipt](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7082126854) or the [general referral-day receipt](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7082228989).

```sh
python tools/presenter_handoff/replay.py /path/to/neutral-instance.json
```

The replay uses the checked-out allocator and the independent feasibility and optimality audit. Expected assigned counts for nearest-first and exact are **114 and 120** for the mixed rehearsal and **212 and 220** for the referral day. The receipts include the original producers and rebuild instructions. The general referral-day workflow is a replay here.

For a clean, synthetic UI check, use a fresh directory. The five requests, two site labels and test grid are invented.

```sh
smoke="$(mktemp -d)"
python tools/presenter_handoff/test_handoff.py
python tools/presenter_handoff/replay.py tools/presenter_handoff/synthetic-smoke.json --plan-out "$smoke/plan.json"
python tools/presenter_handoff/run.py --assets "$smoke" --port 8502
```

Open [the synthetic planning view](http://127.0.0.1:8502/?view=planning). The nearest-first and exact policies place four and five requests, respectively.

## Rebuild display roads

Use the public PBF and version pins listed in the [road edition’s method](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7082183710). Check the full PBF SHA-256 before clipping it with Osmium Tool 1.19.1. The extractor reads the clipped PBF alone.

```sh
python -m pip install osmium==4.2.0 shapely==2.1.2
osmium extract --strategy=complete_ways --bbox=73.753,18.424,73.958,18.615 --output=pune-bbox-source.osm.pbf /path/to/india-261101.osm.pbf
python tools/presenter_handoff/build_pune_roads.py --pbf pune-bbox-source.osm.pbf --output ../datathon-roads
```

The named-roster recipes are documented separately. [Public geography #332](https://github.com/vzhu08/databricks-datathon/pull/332) · [Evidence-enriched variant #338](https://github.com/vzhu08/databricks-datathon/pull/338)
