# Maps and location

## 1. What problem does this solve, and when should I use it?

Display markers, line routes and polygon GeoJSON without requiring a map service to start. Filter nearby locations by great-circle distance. When configured, query Mapbox for actual geocoding and traversable walking, cycling or driving routes. Local fixtures and live provider results carry different mode labels.

## 2. What is the smallest working example?

```sh
node --import tsx modules/maps/examples/demo.ts
```

In React, render `GeoMap({data:toGeoJSON(sampleLocations,sampleRoute), mode:'fixture'})` using [components.tsx](src/components.tsx) and [index.ts](src/index.ts). The fixture uses invented venue names and an authored schematic line. It has not fetched tiles or travel directions.

## 3. How do I add it to a fresh project or an existing project?

Select `maps` from the catalog or copy the module and shared `packages/runtime`/`packages/contracts` preserving their repository-relative layout. Install pinned Zod/React dependencies from [module.json](module.json). Add the pure distance functions to your existing location records. Add `GeoMap` to an existing client route and call [server.ts](src/server.ts) only from server handlers. Existing database/location schemas do not need to be replaced.

## 4. What does the API accept and return?

Coordinates are `[longitude,latitude]` in decimal WGS84 degrees. `haversineKm(a,b)` returns approximate spherical straight-line kilometers with a 6371.0088 km mean Earth radius. `filterByRadius(locations,center,radiusKm)` returns distance-sorted records with `straightLineKm`. It does not estimate travel time.

`toGeoJSON(locations, route?)` returns a validated FeatureCollection. The UI accepts Point, LineString and Polygon geometries, closed polygon rings, up to 2,000 features and 20,000 coordinates total. `GeoMap({data,mode?,attribution?})` renders a zoomable SVG schematic with markers/labels/routes/polygons; invalid or empty collections have explicit states.

`geocode(query,{token,signal?,fetcher?})` calls Mapbox v6 forward geocoding and returns `{mode:'live',locations,attribution,storage}`. It requests five results and no autocomplete. `routeBetween(from,to,profile,options)` calls Mapbox Directions v5 with GeoJSON and returns geometry, `distanceMeters`, `durationSeconds`, profile, mode and attribution. `NoRoute` becomes `KitError('NO_ROUTE',...,422)`, not a straight-line fallback. All network responses are bounded and schema-validated.

## 5. What prerequisites, environment variables, or credentials are needed?

Local mode requires no credentials. Live server adapters require `MAPBOX_ACCESS_TOKEN`; pass it explicitly as `options.token`. Keep it out of logs/query telemetry (Mapbox requires the token as a query parameter). Review current account pricing and provider permissions before use. To deliberately exercise the live example:

```sh
KIT_ALLOW_LIVE=1 node --import tsx modules/maps/examples/live.ts 'New York Public Library'
```

This may incur usage. The example geocodes, then requests a walking route only if two locations were returned. It never changes to fixtures on error.

## 6. What changes must I make to routes, schema, storage, or UI?

Connect a submitted search to an authenticated server handler, apply an application rate limit and return provider errors through your normal API error boundary. Call on submit/debounce rather than every keystroke. Pass provider attribution into the map UI and display the mode visibly. Distinguish meters/seconds from approximate kilometers.

Mapbox temporary geocoding results **must not be cached or stored**. The adapter explicitly requests `permanent=false`. A persistent geocoding product needs a deliberate permanent-storage contract and adapter change. The local schematic is an independent geographic display; review Mapbox terms for your intended use of their search/directions data and attribution. No raster tile SDK is installed or claimed.

## 7. How do I verify it and handle expected failures?

```sh
npx vitest run modules/maps/tests
```

Tests cover zero/antipodal/dateline distances, empty/radius results, real API URL/response contracts with injected fetch, no results, no route and rate-limit errors. The examples use [synthetic locations](fixtures/locations.json) and [GeoJSON](fixtures/map.geojson). Invalid coordinates, negative radius and malformed geometry fail validation; unsupported projection/geometries do not render misleading output.

Implementation: implemented. Observed local verification: `npx tsc --noEmit` passed on the module checkout; `npx eslint modules` passed; `npx vitest run modules/maps/tests` passed (5 tests as part of the combined 35-test module run); `node --import tsx modules/maps/examples/demo.ts` completed without credentials. Exported-project verification: passed 2026-10-09 in the standalone full recipe (clean npm ci, types, module tests, production build and local HTTP). Live geocoding/routing: **not run**, requires operator account credentials and authorization. Mocked fetch responses are contract checks, not proof of service access.

## 8. What does it depend on, and what are its limits?

Zod, React and shared runtime/contracts; no native or tile dependencies. The map is a schematic coordinate view with zoom, not a basemap/navigation product; it does not handle world wrapping, projection distortion, panning or multipolygon geometry. Provider caps: query <=256 characters/20 whitespace-separated words, up to 5 results, route responses bounded to 1 MB. Synthetic route distances/times are illustrative. Live rates/costs depend on the account; no price claims are bundled.

Official contracts checked during implementation: [Mapbox Geocoding v6](https://docs.mapbox.com/api/search/geocoding/) and [Directions v5](https://docs.mapbox.com/api/navigation/directions/). Original code and synthetic fixture data: MIT. Live data remains subject to provider terms and attribution.
