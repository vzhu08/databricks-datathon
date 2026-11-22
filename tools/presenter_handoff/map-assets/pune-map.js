(function () {
  "use strict";

  const model = JSON.parse(document.getElementById("model").textContent);
  const roads = JSON.parse(document.getElementById("roads").textContent);
  const context = JSON.parse(document.getElementById("context").textContent);
  const groups = document.getElementById("group");
  const policy = document.getElementById("policy");
  const request = document.getElementById("request");
  const count = document.getElementById("count");
  const places = Object.values(model.sites);
  const origins = Object.values(model.origins);
  const patientMarkers = new Map();
  const map = L.map("map", { preferCanvas: true, zoomSnap: .5, minZoom: 10, maxZoom: 18 });
  const home = L.latLngBounds(places.concat(origins).map(p => [p.lat, p.lon]));
  const layers = L.layerGroup().addTo(map);
  const labels = L.layerGroup().addTo(map);
  const placesLayer = L.layerGroup().addTo(map);
  const connector = L.layerGroup().addTo(map);
  map.createPane("sites");
  map.getPane("sites").style.zIndex = 620;
  L.control.scale({ imperial: false, maxWidth: 120 }).addTo(map);

  const rank = {
    motorway: 7, trunk: 6, primary: 5, secondary: 4, tertiary: 3, unclassified: 2,
    residential: 2, service: 1, living_street: 1,
  };
  const color = { 7: "#c99543", 6: "#d8a44f", 5: "#ddb45e", 4: "#d3b18a", 3: "#bfae9a", 2: "#afbabf", 1: "#c7cecb" };
  const roadRank = feature => rank[(feature.properties.highway || "").replace(/_link$/, "")] || 1;
  const roadName = feature => feature.properties["name:en"] || feature.properties.name || feature.properties.ref;

  function node(tag, value) {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = value;
    return element;
  }

  function appendSource(box, url) {
    if (typeof url !== "string" || !url.startsWith("https://")) return;
    const source = node("a", "Public location source");
    source.href = url;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    box.append(source);
  }

  function midpoint(feature) {
    const geometry = feature.geometry;
    const lines = geometry.type === "LineString" ? [geometry.coordinates] : geometry.coordinates;
    const points = lines.reduce((largest, line) => line.length > largest.length ? line : largest, []);
    const middle = points[Math.floor(points.length / 2)];
    return middle && L.latLng(middle[1], middle[0]);
  }

  function updateRoadLabels() {
    if (!roads) return;
    labels.clearLayers();
    const zoom = map.getZoom();
    const threshold = zoom >= 15 ? 2 : zoom >= 13 ? 3 : 4;
    const seen = new Set();
    const cells = new Set();
    const bounds = map.getBounds();
    const candidates = roads.features.filter(f => roadRank(f) >= threshold && roadName(f));
    candidates.sort((a, b) => roadRank(b) - roadRank(a));
    for (const feature of candidates) {
      const name = roadName(feature);
      if (seen.has(name)) continue;
      const center = midpoint(feature);
      if (!center || !bounds.contains(center)) continue;
      const pixel = map.latLngToContainerPoint(center);
      const cell = Math.floor(pixel.x / 135) + ":" + Math.floor(pixel.y / 50);
      if (cells.has(cell)) continue;
      cells.add(cell);
      seen.add(name);
      L.tooltip({ permanent: true, direction: "center", className: "road-label", opacity: 1 })
        .setLatLng(center).setContent(node("span", name)).addTo(labels);
      if (seen.size >= 24) break;
    }
  }

  function updatePlaceLabels() {
    if (!context) return;
    placesLayer.clearLayers();
    const zoom = map.getZoom();
    const bounds = map.getBounds();
    const cells = new Set();
    for (const feature of context.features) {
      if (feature.geometry.type !== "Point") continue;
      const {place, name} = feature.properties;
      if (place !== "city" && place !== "suburb" && zoom < 14) continue;
      const [longitude, latitude] = feature.geometry.coordinates;
      const position = L.latLng(latitude, longitude);
      if (!name || !bounds.contains(position)) continue;
      const pixel = map.latLngToContainerPoint(position);
      const cell = Math.floor(pixel.x / 135) + ":" + Math.floor(pixel.y / 70);
      if (cells.has(cell)) continue;
      cells.add(cell);
      L.tooltip({ permanent: true, direction: "center", className: place === "city" ? "city-label" : "place-label" })
        .setLatLng(position).setContent(node("span", feature.properties["name:en"] || name)).addTo(placesLayer);
    }
  }

  if (roads) {
    L.geoJSON(roads, {
      style(feature) {
        const level = roadRank(feature);
        return { color: color[level], opacity: level >= 4 ? .93 : .75, weight: level >= 5 ? 2.45 : level >= 3 ? 1.5 : .75 };
      },
      onEachFeature(feature, layer) {
        if (roadName(feature)) layer.bindTooltip(node("span", roadName(feature)), { sticky: true });
      },
    }).addTo(map).bringToBack();
    if (context) {
      L.geoJSON(context, {
        filter(feature) { return feature.geometry.type !== "Point"; },
        style(feature) { return { color: "#77acbd", opacity: .8, weight: feature.properties.waterway === "river" ? 3 : 1.4 }; },
      }).addTo(map).bringToBack();
      map.on("moveend zoomend", updatePlaceLabels);
    }
    if (Array.isArray(roads.bbox) && roads.bbox.length === 4) {
      const [west, south, east, north] = roads.bbox;
      map.setMaxBounds([[south, west], [north, east]]);
    }
    map.on("moveend zoomend", updateRoadLabels);
    map.attributionControl.addAttribution("Local road geometry · © OpenStreetMap contributors");
  }
  map.attributionControl.setPrefix("Leaflet");

  for (const [key, name] of Object.entries(model.groups)) {
    const option = node("option", name);
    option.value = key;
    groups.append(option);
  }
  for (const [key, values] of Object.entries(model.policies)) {
    const option = node("option", values.name);
    option.value = key;
    policy.append(option);
  }
  policy.value = "exact_optimum";

  function popup() {
    const box = node("div");
    box.className = "map-popup";
    return box;
  }

  function draw() {
    layers.clearLayers();
    connector.clearLayers();
    map.closePopup();
    patientMarkers.clear();
    const showing = origins.filter(p => !groups.value || p.group === groups.value);
    request.replaceChildren(node("option", "Select a request"));
    request.firstChild.value = "";
    const visible = new Set(showing.map(p => p.id));
    const current = model.policies[policy.value];
    const bySite = {};
    for (const patient of showing) {
      const option = node("option", patient.id);
      option.value = patient.id;
      request.append(option);
      const chosen = current.assignments[patient.id];
      if (chosen) bySite[chosen.site] = (bySite[chosen.site] || 0) + 1;
      const marker = L.circleMarker([patient.lat, patient.lon], {
        radius: chosen ? 3.6 : 5, color: chosen ? "#166682" : "#a04620", weight: chosen ? 1 : 2,
        fillColor: chosen ? "#166682" : "#ffffff", fillOpacity: chosen ? .74 : 1,
      }).addTo(layers);
      patientMarkers.set(patient.id, marker);
      const detail = popup();
      detail.append(node("strong", "Simulated request " + patient.id), node("span", model.groups[patient.group] || patient.group));
      for (const method of Object.values(model.policies)) {
        const a = method.assignments[patient.id];
        const result = a ? model.sites[a.site].name + " · " + (a.seconds / 60).toFixed(1) + " modeled min"
          : "unmet · " + (method.unserved[patient.id] || "no placement").replaceAll("_", " ");
        detail.append(node("span", method.name + ": " + result));
      }
      marker.bindPopup(detail);
      marker.on("popupopen", () => {
        connector.clearLayers();
        if (chosen && model.sites[chosen.site]) {
          const site = model.sites[chosen.site];
          L.polyline([[patient.lat, patient.lon], [site.lat, site.lon]], {
            color: "#166682", dashArray: "5 5", weight: 2.4, opacity: .8, interactive: false,
          }).addTo(connector);
        }
      });
    }
    for (const site of places) {
      const marker = site.precision === "campus_anchor" ? L.marker([site.lat, site.lon], {
        pane: "sites", icon: L.divIcon({ className: "map-anchor", iconSize: [13, 13] }), title: site.name,
      }) : L.circleMarker([site.lat, site.lon], {
        pane: "sites", radius: 7, color: "#fff", weight: 2, fillColor: "#8d2d62", fillOpacity: 1,
      });
      const detail = popup();
      detail.append(node("strong", site.name),
        node("span", site.precision === "campus_anchor" ? "Campus simulation anchor" : "Mapped facility point"));
      for (const method of Object.values(model.policies)) {
        const total = Object.entries(method.assignments).filter(([pid, a]) => a.site === site.id && visible.has(pid)).length;
        detail.append(node("span", method.name + ": " + total + " simulated placements in this view"));
      }
      appendSource(detail, site.source);
      marker.bindTooltip(node("span", site.name), { className: "map-facility-label" });
      marker.bindPopup(detail).addTo(layers);
    }
    const assigned = Object.values(bySite).reduce((sum, total) => sum + total, 0);
    count.textContent = places.length + " mapped facilities · " + showing.length + " simulated requests shown · " +
      current.name + " " + assigned + "/" + showing.length + " placed.";
  }

  groups.addEventListener("change", draw);
  policy.addEventListener("change", draw);
  request.addEventListener("change", () => {
    const marker = patientMarkers.get(request.value);
    if (marker) marker.openPopup();
  });
  document.getElementById("reset").addEventListener("click", () => map.fitBounds(home, { padding: [30, 30] }));
  map.on("popupclose", () => connector.clearLayers());
  map.fitBounds(home, { padding: [32, 32] });
  updateRoadLabels();
  updatePlaceLabels();
  draw();
}());
