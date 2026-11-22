"""Local Leaflet map for the simulated Pune planning comparison."""

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "map-assets"
ROADS = "pune-roads-v1.geojson"
ROAD_PIN = "e1278e1a5a4038d419bd1a73aa5a24250b454d634d789f21e9c3fb6434bd1d5f"
CONTEXT = "pune-map-context-v1.geojson"
CONTEXT_PIN = "f0fff12d6335178dacac3ba15ea7613cadf59f50a455295d51456a104422611d"
LEAFLET = ASSETS / "package" / "dist"
LEAFLET_FILES = {
    "leaflet.js": "db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a",
    "leaflet.css": "a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6",
}
GROUPS = {
    "trauma_care": "High-acuity trauma and stabilization",
    "minor_injury_urgent_care": "Minor injury and urgent care",
    "dialysis": "Scheduled dialysis",
    "ophthalmic_treatment": "Scheduled ophthalmic treatment",
}


def json_script(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")


@lru_cache(maxsize=4)
def source_file(path, pin):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != pin:
        raise ValueError(f"{path.name} differs from its pinned source")
    return raw.decode("utf-8")


def road_data(assets):
    content = source_file(assets / ROADS, ROAD_PIN)
    shape = json.loads(content)
    if shape["type"] != "FeatureCollection" or not shape["features"]:
        raise ValueError("The pinned Pune road clip is empty")
    return shape


def model_data(plan):
    labels = {row["category"]: row["label"] for row in plan.get("condition_breakdown", [])} or GROUPS
    sites = {
        row["id"]: {
            "id": row["id"], "name": row["label"], "lat": row["latitude"], "lon": row["longitude"],
            "precision": row["precision"], "source": (row.get("source") or {}).get("url"),
        }
        for row in plan["facilities"]
    }
    origins = {
        row["id"]: {
            "id": row["id"], "group": row.get("condition_category", row["service"]),
            "lat": row["latitude"], "lon": row["longitude"], "priority": row["priority"],
        }
        for row in plan["patients"]
    }
    allocations = {
        key: {
            "name": name,
            "assignments": {a["patient"]: {"site": a["facility"], "seconds": a["travel_seconds"]}
                            for a in plan["policies"][key]["assignments"]},
            "unserved": {a["patient"]: a["reason"] for a in plan["policies"][key]["unserved"]},
        }
        for key, name in (("nearest_first", "Nearest first"), ("exact_optimum", "Exact optimum"))
    }
    return {"sites": sites, "origins": origins, "groups": labels, "policies": allocations}


def page(plan, assets):
    roads = road_data(assets)
    context_path = assets / CONTEXT
    context = json.loads(source_file(context_path, CONTEXT_PIN)) if context_path.is_file() else None
    styles = source_file(LEAFLET / "leaflet.css", LEAFLET_FILES["leaflet.css"])
    library = source_file(LEAFLET / "leaflet.js", LEAFLET_FILES["leaflet.js"])
    library = library.split("//# sourceMappingURL=", 1)[0]
    script = (ASSETS / "pune-map.js").read_text(encoding="utf-8")
    css = (ASSETS / "pune-map.css").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pune street map</title><style>{styles}\n{css}</style></head>
<body>
<div class="toolbar">
  <label>Simulated group <select id="group"><option value="">All groups</option></select></label>
  <label>Placement policy <select id="policy"></select></label>
  <label>Simulated request <select id="request"><option value="">Select a request</option></select></label>
  <button type="button" id="reset">Reset map</button>
</div>
<div id="map" aria-label="Pune street map with mapped hospital locations and simulated patient origins"></div>
<div class="legend" aria-label="Map legend">
  <span><i class="site-symbol"></i> Mapped facility point</span>
  <span><i class="anchor-symbol"></i> Campus simulation anchor</span>
  <span><i class="patient-symbol"></i> Simulated patient start</span>
  <span><i class="unassigned-symbol"></i> Unmet in selected policy</span>
</div>
<p id="count" role="status" aria-live="polite"></p>
<p class="credit">Street data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>{', Geofabrik extract dated 1 November 2026' if roads else ''}.
  Roads and hospital locations are mapped. Patient starts, placement links and travel are modeled.
  Dashed placement links show straight connections between points.</p>
<script>{library}</script>
<script id="model" type="application/json">{json_script(model_data(plan))}</script>
<script id="roads" type="application/json">{json_script(roads)}</script>
<script id="context" type="application/json">{json_script(context)}</script>
<script>{script}</script>
</body></html>"""


def render(ui, content, assets):
    ui.markdown("### Pune street map")
    ui.caption("Select a condition group or placement policy, then open a hospital or simulated patient marker.")
    if hasattr(ui, "iframe"):
        ui.iframe(content, height=644)
    else:
        ui.components.v1.html(content, height=644)
    ui.download_button("Download clipped OSM road data", source_file(assets / ROADS, ROAD_PIN).encode("utf-8"),
                       file_name=ROADS, mime="application/geo+json")
    if (assets / CONTEXT).is_file():
        ui.download_button("Download OSM map context", source_file(assets / CONTEXT, CONTEXT_PIN).encode("utf-8"),
                           file_name=CONTEXT, mime="application/geo+json")
    ui.caption("Map layers are available under the Open Database License (ODbL 1.0).")
