# Identity matching and geographic checks (ACQ-C01)

This producer proposes links between the original base rows and the external records collected by A and B, under contract v1.0.0. It emits `facility_matches`, location-only `facility_evidence` and `review_queue` rows. It never edits a base row, an external record or another producer's evidence.

A candidate is a retrieval result. It is not an identity decision and carries no probability. Only one path confirms a link without a person: an exact identifier shared in an inspected namespace, unique on both sides, with no geography conflict and no competing campus. Every other link needs a named reviewer, a timestamp and a reason.

## Install and test

Python 3.9+. Matching and geography use the standard library; `jsonschema` is needed only to check outputs against the shared schema.

```sh
python3 -m venv research/matching/.venv
source research/matching/.venv/bin/activate
python3 -m pip install -r research/matching/requirements.txt
python3 -m unittest discover -s tests/research/matching -p 'test_*.py' -v
```

Run every command from the repository root. Tests use invented data only and import D's validator read-only to check that it accepts C's outputs.

## Matching run

```sh
python -m research.matching.run --base <file> --external <batch> --output-dir <path>
```

| Argument | Meaning |
| --- | --- |
| `--base` | D's base adapter file: a JSON array of objects with a unique nonempty `facility_id`. |
| `--external` | A contract envelope from A or B. Repeat it for several. Identical rows deduplicate; a different payload under one ID fails. |
| `--output-dir` | Keep real runs under ignored `data/local/matching/`. It must not be a directory that holds an input. |
| `--base-mapping` | JSON object from role to the base column D observed. Roles: `name`, `alt_names`, `address`, `city`, `district`, `state`, `pin`, `latitude`, `longitude`, `phone`, `type`. Dot paths reach into `source_row`. |
| `--external-attributes` | Optional sidecar keyed by `external_facility_id` with `aliases`, `phones`, `district`. These values exist only in a producer's raw artifact; the contract has no column for them. |
| `--identity-policy` | D-format namespace policy. Without it no identifier is used and nothing confirms automatically. |
| `--postal`, `--postal-mapping` | Postal directory rows and their observed column mapping (`pin`, `state`, `district`). |
| `--config` | JSON object overriding the retrieval settings listed below. |
| `--sample-size` | Review sample limit, default 50. |

A real export nests original columns under `source_row`. With that shape the run stops unless `--base-mapping` is supplied: no source column is ever guessed. The shared synthetic base already uses role names as keys, so it runs without a mapping. See `examples/` for the file shapes.

Outputs, all canonical JSON, byte-identical on rerun:

- `batch.json`: the contract envelope with match rows and open review items. Give this to D.
- `candidates.json`: every kept pair with its signals, flags, rank and counts of alternatives.
- `review_worksheet.json`: the review sample with both source rows side by side. Contains source text.
- `geography_report.json`: coordinate flags, proposed corrections, coordinate clusters and postal context for base and external records.
- `report.json`: denominators and counts. `manifest.json`: SHA-256 of every input and output.

## How candidates are retrieved

Names are folded (NFKC, case, punctuation), common abbreviations expanded and dotted initials joined, so `J.L.N. Govt. Hosp.` becomes `jln government hospital`. Words that describe a kind of facility (`hospital`, `government`, `district`, ...) do not count as name evidence. Name evidence has four levels:

| Level | Meaning |
| --- | --- |
| strong | Same folded name, same distinguishing tokens, or the same tokens ignoring spaces. |
| moderate | Most distinguishing tokens shared, or very similar spelling. |
| weak | Some tokens shared, similar spelling, or only an acronym. A name made of generic words alone is never more than weak. |
| none | No name evidence. |

A pair is kept when one of these holds: an identifier matches in a policy namespace; a phone number matches and is not a switchboard; name evidence is strong or moderate and the states do not conflict (a state conflict is tolerated only with the same PIN or within 5 km); name evidence is weak and PIN, place, address or a distance within 1 km agrees; or the records are within 100 m with no name evidence (`proximity_only`). Missing or unusable coordinates never remove a textual candidate.

Candidates for a base row are ordered by identifier, name level, number of conflicts, number of agreements, distance and external ID, then cut to `top_k`. Identifier hits are never cut, and competing base rows are counted before the cut.

| Setting | Default | Use |
| --- | ---: | --- |
| `top_k` | 5 | Candidates kept per base row. |
| `max_token_df` | 2000 | A name token on more external records than this cannot retrieve on its own. |
| `max_block` | 5000 | Largest PIN or grid cell used for retrieval. |
| `cell_deg` | 0.02 | Grid cell for proximity retrieval. |
| `same_site_m`, `near_m`, `area_m`, `far_m` | 150, 1000, 5000, 25000 | Distance bands in metres. |
| `proximity_only_m` | 100 | Radius for name-free candidates; 0 turns them off. |
| `switchboard_min` | 3 | A phone on this many records on one side is a switchboard. |

These are retrieval heuristics. They decide what a reviewer sees, not what is true, and must not be reported as confidence.

## Automatic confirmation

A match is written as `confirmed` with method `shared_identifier` only when all of these hold, mirroring D's validator:

1. The namespace is in the supplied identity policy and the external record's source is listed for it.
2. The value is text on both sides and exactly equal.
3. The value occurs once in the base and once among that namespace's external records.
4. No other namespace disagrees for the pair.
5. State, place and PIN do not conflict and the coordinates are within 5 km when both exist.
6. No other base row retrieved the same external record.

Otherwise the pair stays a candidate with a high-severity review item: `identifier_not_unique`, `identifier_conflict` or `identifier_campus_conflict`.

## IDs

- `match_id = 'acq-c-match:' + SHA256(canonical([facility_id, external_facility_id]))`. One row per pair; status changes never change the ID.
- Match review items: `'acq-c-review:' + SHA256(canonical([reason_code, match_id]))`. Base geography items: `'acq-c-geo-review:' + SHA256(canonical([flag, facility_id]))`.
- Spatial evidence: `'acq-c-spatial:' + SHA256(canonical([external_facility_id, building_snapshot_id, feature_id, point_label, latitude, longitude]))`.
- Transitions: `'acq-c-transition:' + SHA256(canonical([table, row_id, prior_hash, new_hash]))`.

Canonical JSON is the encoding D documents: UTF-8, sorted keys, compact separators. No ID includes a clock value.

## Review workflow

1. Open `review_worksheet.json`. The sample takes up to 50 candidates round-robin across strata: easy, alias, ambiguous name, conflicting geography, missing geography, non-hospital type, shared identifier, proximity only, other. Inside a stratum the order is the SHA-256 of the match ID. If there are 50 or fewer candidates, all are sampled.
2. For each pair, read both source rows and any campus evidence from B, then record `confirmed`, `rejected` or `conflict` with reviewer, UTC time and a reason in a decisions file (`examples/decisions.example.json`).
3. Apply the decisions:

```sh
python -m research.matching.review --matches <run>/batch.json --decisions decisions.json \
  --external <a-batch> --external <b-batch> --output-dir <path>
```

This writes `reviewed_batch.json`, `transitions.json`, `evidence_transitions.json`, `review_ledger.json` and `review_summary.json`. Hand D exactly one of two sets:

- First submission, D has not accepted C's candidates: `reviewed_batch.json` with `--transitions evidence_transitions.json`.
- D already accepted `batch.json`: the same `batch.json` with `--transitions transitions.json`.

Evidence from A or B is linked to a base row only when a reviewer confirmed the match for its external record. A rejected or conflicting match unlinks any evidence that pointed at it in the same plan. Endorsing an automatic confirmation in the decisions file does not rewrite the match; it supplies the reviewer needed to link evidence. D's transition rule stamps the linking reviewer and time on the evidence row; the earlier claim review stays recoverable through the prior payload hash.

`review_summary.json` reports reviewed counts, every rejected candidate as an observed false match, and final statuses. Its rates use reviewed decisions as the denominator and say nothing about unreviewed candidates.

## Geographic checks

`geography_report.json` screens base and external coordinates: missing, incomplete, not finite numbers, outside WGS84, outside the broad India envelope (latitude 6-38, longitude 68-98, a screening cue and not a border test), 0,0, possible swapped axes, two-decimal precision, PIN text in the address that differs from the PIN field, and three or more differently named records on one point. A proposed correction is listed beside the original pair. No coordinate is changed anywhere, and distances in match signals always use the original values; a swapped pair also gets `distance_if_base_axes_swapped_m` as a cue for the reviewer.

Postal rows are collapsed to one entry per PIN, keeping every state and district seen for it, before any lookup. The join returns exactly one result per input record and fails if the count changes. Without postal data, PIN, state and district consistency is reported as unknown.

## Building footprints

Footprints come after usable matches and never block them.

```sh
python -m research.geography.overture --cases cases.json --release <inspected release> --output extract.sql
# run extract.sql with DuckDB on a machine that can reach the Overture bucket
python -m research.geography.footprints --cases cases.json --buildings <extract> --snapshot snapshot.json \
  --matches reviewed_batch.json --external <a-batch> --reviewer <handle> --reviewed-at <UTC> --output-dir <path>
```

`footprints.select_cases` picks up to 10 disputed pairs (name strong or moderate, coordinates more than 1 km apart) and 10 controls (name strong, within 150 m, no conflict or ambiguity) from a run's candidates, ordered by SHA-256 of the match ID, and returns all eligible cases when there are fewer. Each case carries the claimed base point and, when different, the external point.

The extract script reads only 500 m boxes around at most 40 points from one pinned release and selects `id`, `sources`, `subtype`, `class` and geometry. It selects no height, floor count or area. `building_snapshot` builds the snapshot row from the extract's bytes, with independence `shared_origin` because Overture reuses OpenStreetMap and other inputs.

For each point the check records the nearest footprint within the radius, the distance in metres to its boundary (0 inside) and the feature's upstream datasets. The evidence row has claim type `location`, no service and no excerpt. Polarity is `supports` only when the point is inside a footprint, the footprint does not share OpenStreetMap origin with the identity record, and it is not older than `--stale-before`; otherwise `inconclusive`. It is never `contradicts`. No footprint within the radius writes no evidence, only a ledger line and a low-severity review item: absence is unknown. Capture date stays null unless the feature states one. Rows are written only with reviewer metadata, because the claim comes from a different source than the identity record; they are linked to a base row only when its match is confirmed.

## Limits

- Fixture results, public-source results and live Databricks results are separate. The handoff states which exist.
- Retrieval coverage is not match precision. Thresholds are uncalibrated.
- Name folding handles Latin script and common English abbreviations. Other scripts fall back to exact folded comparison.
- Phone numbers, districts and aliases for external records need the sidecar until a producer supplies them.
- The Overture extract script follows the documented release layout and has not been run against the live bucket from this checkout.
