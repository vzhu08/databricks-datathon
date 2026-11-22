# National OSM service observations — Developer J, #111

This source adapter screens every feature in the pinned Indian HOT export and
the entire public India Geofabrik PBF. It emits reviewable map observations,
never patient-facing service decisions. The NHSRC PMNDP index is a separate
state/UT aggregate context packet. Source rows stay in ignored private working
storage and the authorized team Databricks intake, not Git.

## Sources and reuse

| Edition | Scope and grain | Reuse and lineage | Join fields / limitation |
| --- | --- | --- | --- |
| HOT snapshot 2026-10-09 | India; 139,664 feature occurrences, 136,004 typed IDs | ODbL 1.0; © OpenStreetMap contributors; HOT/Geofabrik/OSM are one origin | Typed `node/`, `way/`, `relation/` IDs, original names, retained addresses, geometry and publisher state overlay. Selected columns omit other OSM keys. |
| Geofabrik India 2026-11-01 | Full public PBF; embedded replication time 2026-11-01T21:21:36Z | Same OSM origin and ODbL; public file omits mapper account/history metadata | Full tag set, typed ID and version, original address, node point or unresolved way/relation topology. No inferred campus identity. |
| NHSRC PMNDP index, retrieved 2026-11-22 | 36 state/UT rows; 1,994 reported functional centres in aggregate | NHSRC permits accurate acknowledged reproduction; third-party material excluded; PMNDP programme lineage | State/UT context only. No named-campus rows or campus IDs; observation/publication date unknown. |

Source links: [HOT archive](https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/health_facilities/hotosm_ind_health_facilities_osm_geojson.zip),
[public PBF](https://download.geofabrik.de/asia/india/india-261101.osm.pbf),
[OSM licence](https://www.openstreetmap.org/copyright),
[specialty semantics](https://wiki.openstreetmap.org/wiki/Key:healthcare:speciality),
[NHSRC index](https://nhsrcindia.org/pmndp-map-table),
[NHSRC terms](https://nhsrcindia.org/copyright-policy).
The current HOT URL is mutable: the digest gate prevents using a new edition
as the frozen one. Reuse the already pinned team intake edition when available.

## Replay

Run from the repository root, with eligible input files already acquired.
Python 3.10+ handles HOT and NHSRC. PBF additionally needs the isolated optional
dependency in `requirements-pbf.txt`; no dependency changes to the demo app.

```sh
python -m pip install -r research/acquisition/osm_services/requirements-pbf.txt
python -m research.acquisition.osm_services \
  --hot /private/input/hotosm_ind_health_facilities_osm_geojson.zip \
  --out data/local/osm-services/hot-20261009-final
python -m research.acquisition.osm_services \
  --pbf /private/input/india-261101.osm.pbf \
  --sha256 c0a4a9382e67c8afc8427ab865358dcf42226ab3876f8477667585eaab6731b7 \
  --source-url https://download.geofabrik.de/asia/india/india-261101.osm.pbf \
  --snapshot-date 2026-11-01 \
  --retrieved-at 2026-11-22T05:06:50.543264Z \
  --prior-hot /private/input/hotosm_ind_health_facilities_osm_geojson.zip \
  --pbf-cache data/local/osm-services/pbf-extraction-cache \
  --out data/local/osm-services/pbf-20261101-final
python -m research.acquisition.osm_services.pmndp \
  --index /private/input/pmndp-index.bin \
  --policy /private/input/pmndp-policy.bin \
  --out data/local/osm-services/pmndp-context-v1
python -m unittest discover -s tests/research/acquisition/osm_services -v
```

The HOT digest is
`5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3`.
The CLI writes deterministic `ledger.jsonl`, `aggregate.json`, and `manifest.json`;
PBF with `--prior-hot` also writes `edition-drift.json`. Different output bytes
cannot silently replace an existing packet. Every exact repeated HOT payload
retains all original feature locators; conflicting payloads remain separate.
PBF records retain the source ID/version locator and raw tags. No bounding-box,
state, geocoding-success or campus-match filter removes source observations.
The native reader visits the whole PBF and passes every tagged object to Python.
A second native-ID pass recovers untagged prior HOT objects. Scan counters cover
all tagged objects plus those recovered IDs; unrelated topology-only objects
remain in the raw PBF and are not counted as medical records. The optional
private cache checkpoints retained records before classification and verifies
the input/reader/record hashes on reuse.

## Interpretation and consumer contract

`explicit_service_tag` means explicit map wording only. Dialysis specialty,
MRI and explicit trauma-care tokens are separate from bare trauma/surgeon scope,
names/operator branding, descriptions, numeric tags, referral/offsite, home/mobile,
future, negative and defunct observations. Generic nephrology, radiology,
emergency and orthopaedics do not assert the three target services. Other explicit
CT/ICU/blood/specialty tokens are retained as separate capabilities, not inferred
trauma provision. Categories count objects nonexclusively; one object can have
several raw claims or conflicting categories.
The lexicon covers the listed English spellings/tokens; it does not translate
unrecognized languages or assert that all unrecognized tag grammars were found.
Negation/lifecycle/scope categories are conservative text-screen flags for review,
not semantic adjudications of an entire sentence or a current campus status.
The full PBF includes `facility:mri` and `facility:trauma` yes/no fields, which
HOT omits. Their declared source is a 2019 Indore field visit; preserve that raw
source tag and its historical scope. Recognizing a boolean map field does not
establish current function, a precise observation date or independent evidence.

All observations have `patient_status=unconfirmed`, no adjudicated campus or VF
ID, and no inferred service observation date. Map edit dates, source versions,
retrieval times and survey tags are retained without converting them into proof
of current function, staffing, admissions, machines or patient slots. Absence of
a target mention is unknown. HOT missing columns mean `not_preserved_by_export`;
PBF missing keys are measured across the complete scan, never absence of a service.

PBF state labels use current `addr:state` when supplied, otherwise the earlier
HOT state overlay for the same typed ID, explicitly labelled as such. Remaining
states and way/relation geometry stay unknown. Prior overlay reuse is not campus
linkage. `edition-drift.json` records ID overlap, absent IDs and changed retained
tags; missing IDs do not establish closure. Additional PBF observations can
reflect both omitted HOT columns and edition drift, not an independent source.

Vincent owns campus linkage and D (#163) owns comparison with the frozen
#57/#58/#67 baseline. They must retain all 10,088 original occurrences, 10,077
upstream IDs, 11 identical pairs and exactly 30,264 decisions. This adapter does
not read or mutate VF rows. Incremental VF/campus coverage is explicitly
unmeasured until that consumer replay; source-object counts have a different
denominator. NHSRC state totals cannot be allocated to particular campuses.

## Databricks handoff

Use `/Volumes/workspace/default/datathon_vf_research_intake/` with an immutable
edition path derived from its manifest digest. Preserve the raw PBF, input
provenance and allowed source captures with their hashes; reuse the already
staged HOT raw edition. Keep earlier working caches out of duplicate intake.
Vincent is the requested existing writer; J retains receipt follow-through.
New PMNDP/Apollo/DCDC acquisition is assigned to Vincent's Windows collectors;
J receives their authorized editions. NephroPlus #73 rows remain permission-held.

After upload, run the same verifier against the mounted Volume or downloaded
readback, supplying the previously recorded manifest digest:

```sh
python -m research.acquisition.osm_services.verify /Volumes/workspace/default/datathon_vf_research_intake/EDITION \
  --manifest-sha256 EXPECTED_MANIFEST_SHA256
```

The verifier checks every listed file size/hash, ledger counts and unconfirmed
status/campus-null invariants. Record four-person read access separately; file
integrity alone does not prove permissions. Link the actual location, manifest
digest, remote checks and recipient receipt on #111 and #160. A local verification
is not a live Databricks receipt. Publication, clinical release and submission
remain Oliver's decisions.
