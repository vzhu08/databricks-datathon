# Issuer address and named campus geometry

Issue #234 starts from the 49 frozen #221 issuer listings, including 47 eligible
printed address keys and 46 linked numeric points. The NABH directory freeze and
derived linkage are for the four authorized team readers. The sealed review set
is outside this method. The OSM inputs are the verified #111 October HOT archive
and November Geofabrik India PBF, © OpenStreetMap contributors, ODbL 1.0. Treat
both map editions as one origin. The selected raw map source tags and edition
locators remain in private candidate records.

The native reader scans the full November PBF. It retains eligible nearby
features whose nodes or members hit the padded point grid, plus nationwide
features whose name, English name, official name or alternate name exactly
matches a normalized issuer branch name. The grid extends at least two cells
past each occupied cell before comparison within 300 m. A second pass recovers
relation member ways and a third resolves referenced node coordinates. An
extremely large polygon that has no vertex in the padded grid and lacks an
exact branch label can be missed. Nested relations and incomplete rings may
have unavailable geometry, which stays unknown. October HOT is screened in
full with a national name and explicit address comparison and the same 300 m
geometric search. PBF address-only objects without a nearby issuer point or
a matching name lie outside the candidate set. An entrance candidate is a mapped
entrance within the search area. Its connection to the issuer listing is unknown.

Exact agreement requires a normalized complete branch name and a matching
full address or explicit house, street and PIN, plus a mapped site and no
competing plausible same-name premise or direct address conflict. A matching
polygon that covers the linked point can support the named footprint with
entrance unknown. Same-name objects on intersecting footprints are grouped
as one mapped premises hypothesis. Spatial coincidence alone is recorded
separately. Full names may miss aliases or language variants. A same-name site
with incompatible mapped postal or house identifiers stays unresolved.
Distances are a local longitude/latitude approximation. A six-decimal point
repeat and a within-one-metre repeat are reported separately. An exact
coordinate repeat cannot determine copying direction or independent origin.
The test measures agreement in a bounded issuer cohort. The national location
accuracy and onsite service status are outside its denominators.

Use Python with the pinned optional packages. Inputs and outputs below are
private working paths. The November extract is a reproducible working cache.
The comparison verifies the frozen extract SHA-256
`c62d1841d5fc2133c32f8c5541a44becd54f5337bbaace4e448264a39fcb8920`
before parsing it or writing results. This pin belongs to the #221 issuer
freeze and #111 PBF editions above.

```sh
python -m pip install -r research/acquisition/issuer_campus_geometry/requirements.txt
python -m research.acquisition.issuer_campus_geometry.scan \
  /private/issue-221/source-freeze /private/india-261101.osm.pbf /private/234-pbf-window.json
python -m research.acquisition.issuer_campus_geometry.compare \
  /private/issue-221/source-freeze /private/hotosm_ind_health_facilities_osm_geojson.zip \
  /private/234-pbf-window.json /private/issue-221/inputs/vf /private/234-result
python -m unittest discover -s tests/research/acquisition/issuer_campus_geometry -v
```

The comparison reads and verifies the two frozen national baseline files without
editing them. The 49-listing results contain no new VF assignments. D can
reproduce the aggregate and candidate ledger using the exact inputs in the
handoff. The JSONL ledger contains source listing IDs and mapped premises and
must remain in the four-reader audience. Git contains only the method and
invented controls.
