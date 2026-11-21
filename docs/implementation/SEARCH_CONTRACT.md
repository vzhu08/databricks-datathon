# Search contract · v0

Dev 4 coordinates changes with Devs 1–3. Use the [synthetic fixture](../../contracts/fixtures/search.json) before shared Databricks data is available. Each case has a query, candidate rows with nested evidence, and expected response fields. The fixture leaves out echoed evidence records and rounds displayed distances to one decimal. Replace workspace schema placeholders after Marketplace inspection.

## Inputs

`service` is a service ID. The initial value is `trauma_care`. The UI resolves a labeled pickup preset or user-entered WGS84 coordinates to `latitude` and `longitude`, both finite and within valid bounds. For the MVP, use the Ajmer/Jaipur pilot area. `radius_km` defaults to 100 and `limit` defaults to 3. Validate and cap the limit at 3. Use the same radius, geometry, and maximum result count in the baseline and the evidence ranker.

## Data handoff

| Delta table | Fields required for v0 |
| --- | --- |
| `facilities` | `facility_id`, `vf_row_id`, `name`, `city`, `district`, `state`, `latitude`, `longitude`, `campus_status` (`matched`, `unverified`, `conflict`), optional `phone` and `phone_source_url` |
| `facility_evidence` | `evidence_id`, `facility_id`, `service`, `source_kind` (`virtue_foundation`, `external`), `source_name`, `source_url` (nullable if unavailable), `source_ref` (row/field or page/entry), `excerpt`, `source_date` (nullable), `observed_on`, `signal` (`explicit`, `weak`, `contradiction`) |

- Join on stable `facility_id`. For Virtue Foundation, preserve the original row identifier when present. If absent, derive and record a reproducible row key from stable source fields.
- An `explicit` claim identifies the requested service at the campus. Generic ER wording and referrals belong in `weak`. Explicit denial or an incompatible campus belongs in `contradiction`. Keep unresolved external rows outside the accepted evidence join.
- Every ranked result requires valid coordinates and an explicit Virtue Foundation excerpt. A corroborated tier additionally requires explicit independent service evidence and matched campus identity. Exact excerpt text links to its source or to the dataset row and field where no URL exists. A documented source date and the date the team observed the source are distinct.

## Ranking and response

1. Filter to the configured radius using Haversine distance in kilometers. Exclude invalid coordinates, deduplicate by campus ID, and exclude campus conflicts or contradictory service evidence from ranked results.
2. Rank `corroborated` ahead of `facility_text`. Within a tier, use distance ascending, then `facility_id` ascending for ties. The rank explanation states which evidence tier and distance produced the ordering. Tier and rank describe evidence quality and proximity. Current availability is `unknown`.
3. Return `status`, `results`, and `reason_codes`. Status is `ok` when candidates are ranked, `needs_review` when candidates exist but evidence or campus conflicts prevent a recommendation, `no_match` when the search yields no candidate in scope, `invalid_input` for unsupported/invalid values, or `unavailable` when the live source cannot be queried. An empty result for the evidence threshold uses `needs_review`. A live source error stays `unavailable` until live access works again.

Each result has `rank`, `facility_id`, `name`, `distance_km`, `evidence_tier`, `availability`, `directions_allowed`, and a list of `evidence_ids` plus the corresponding evidence records for rendering. Use `directions_allowed=true` only with `campus_status=matched`. Display distances as approximate straight-line distance. Relevant reason codes include `weak_service_evidence`, `campus_conflict`, `service_conflict`, `no_candidates_in_radius`, `unsupported_service`, `invalid_location`, and `data_unavailable`.
