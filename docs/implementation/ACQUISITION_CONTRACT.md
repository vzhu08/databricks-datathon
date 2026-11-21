# Acquisition contract · v1.0.0

The orchestrator owns this contract, `contracts/enrichment/`, and `contracts/fixtures/enrichment.json`. All four data-producing roles consume the same version. Breaking changes must be coordinated; do not silently rename fields. The existing [search contract](SEARCH_CONTRACT.md) is unchanged.

## Interface

Each producer emits a UTF-8 JSON object with `contract_version: "1.0.0"` and five arrays: `source_snapshots`, `external_facilities`, `facility_matches`, `facility_evidence`, `review_queue`. Unowned arrays are empty. [schema.json](../../contracts/enrichment/schema.json) is normative. D exposes these as five Delta tables plus operational run metadata.

A emits nationwide source and identity references. B evaluates service evidence across the complete nationwide original facility population. Existing geographically limited evidence retains its original scope. C emits matches, spatial evidence, and reviewed links. D combines batches with accepted upstream rows, validates references, and publishes. Identical IDs/payloads are idempotent; a conflicting payload under the same ID must fail or be explicitly versioned, never silently overwrite. Review state transitions must be explicit, auditable updates. D defines a separate operational transition ledger (prior ID/payload hash, new payload hash, actor, UTC time, reason); it is not silently encoded as a conflicting ordinary batch replay.

Base facilities are separate input, not a sixth enrichment table. D preserves source `facility_id` and original evidence. A documented stable surrogate is required before linking if the source lacks an ID. The base input for local validation is a JSON array of objects with unique nonempty `facility_id` values; additional original fields must be preserved. `contracts/fixtures/enrichment_base.json` is the separate synthetic base input; `contracts/fixtures/enrichment.json` is a producer envelope. These rows do not imply a real Marketplace schema.

## Meaning of the five tables

| Table / primary ID | Meaning |
| --- | --- |
| `source_snapshots` / `snapshot_id` | Source key, publisher, upstream source family, URL, UTC retrieval time, nullable publication date, license/attribution, raw-byte SHA-256, external artifact URI, parser version, assessed source independence |
| `external_facilities` / `external_facility_id` | Snapshot, original identifier/locator, original name/address, normalized name, type, city/state/PIN, nullable WGS84 coordinates, quality flags |
| `facility_matches` / `match_id` | Original base ID, external ID, candidate/confirmed/rejected/conflict status, method, rationale, review metadata |
| `facility_evidence` / `evidence_id` | External ID/snapshot, optional confirmed base and match IDs, claim/service/polarity, assertion, exact excerpt or spatial observation, locator/source URL, temporal status/dates, review metadata |
| `review_queue` / `review_id` | Optional affected IDs, reason code, severity, open/resolved status, next action, nullable resolution |

IDs are deterministic and namespaced. Snapshot identity derives from source identity and raw content hash, not the retrieval clock. Record/evidence IDs derive from stable source identifiers/locators plus source content. Replays retain the first persisted snapshot retrieval timestamp; later download attempts belong in an acquisition log outside the immutable row. Preserve conflicting variants rather than overwriting repeated IDs. Document and test the chosen ID derivation.

## Invariants

- References resolve in the combined staged/accepted dataset. Linked evidence requires a `confirmed` match with the same base and external IDs. Its snapshot identifies the source of the claim and may differ from the external identity record’s snapshot; cross-source identity must be documented in the assertion/locator and reviewed. Unresolved evidence remains unlinked and cannot corroborate a recommendation.
- Automatic confirmation requires an unambiguous shared identifier in the same namespace and no branch conflict. Other confirmations require manual review, reason, reviewer, and timestamp. Shared-ID matches also supply `shared_identifier` namespace/value/base-field/external-field proof; D checks these fields against available inputs and rejects unverifiable automatic confirmation. A name/fuzzy match alone is only a candidate.
- Every textual claim preserves an exact excerpt and page/row locator. Spatial evidence may use `observation` instead, recording method, source feature, units, coordinate basis, and limitations. Spatial evidence can concern location only, never clinical service capability.
- Polarity is `supports`, `contradicts`, or `inconclusive`. Claim types: `identity`, `service`, `location`, `accreditation`, `scheme_status`. Services: `trauma_care`, `dialysis`, `mri`, or null. This sprint prioritizes trauma.
- Temporal status is `dated`, `undated`, `historical`, or `expired`; none asserts live availability. Dates are ISO or null. Keep retrieval, publication, effective, and expiry distinct. Unknown capture dates remain null.
- Absent names stay null with quality flags; never drop an otherwise usable feature or fabricate a name. Preserve source-invalid PINs/coordinates in the raw snapshot and locator, emit null normalized values with flags, and do not silently repair them.
- PIN is text. Coordinates are finite and valid WGS84 or null. Flag outside-country/source anomalies; do not silently repair them. Spatial measurements use metres and state that unit; baseline search distances remain kilometres.
- General emergency, planned capacity, referral-only services, and explicitly unavailable services cannot be upgraded into affirmative trauma capability. Missing entries/certificates/footprints are unknown; scheme suspension is not closure or fraud.
- Preserve upstream `source_family` and independence assessment. Different URLs do not establish independence. NHP and its mirror count once; reused OSM/building inputs require a shared-origin flag when known.

## Storage and handoff

Real snapshots, parsed facility rows, evidence excerpts, and Marketplace exports live in ignored `data/local/` or an authorized Databricks Volume. Git holds only code, synthetic fixtures, source registry URLs, and non-sensitive aggregate results. Record licenses and redistribution restrictions; do not put credentials or patient/incident information in artifacts, issues, or logs.

The registry at `contracts/enrichment/source_registry.json` supplies research entry points, not prevalidated claims. All freshness and independence statements must come from actual inspection.

Handoff: contract version; snapshot IDs/counts; permitted artifact locations; exact commands/results; review and unresolved counts; limitations; branch/PR/SHA. D adds live table/Volume/run identifiers only when actually tested. New producers must pass the schema and cross-table checks implemented by D. Structural validation cannot prove that a natural-language claim is true; unsupported clinical inference requires a documented review gate alongside machine-checkable invariants.
