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
| `--source-metadata` | D's `source_metadata.json` for this base (written by notebook 01 or `prepare_local_export.py`). Its observed mapping supplies `name`, `state`, `type`, `pin`, `latitude`, `longitude`. The row count must equal the base file's. |
| `--base-mapping` | JSON object from role to the base column D observed. Adds to or overrides the roles from `--source-metadata`; D's mapping has no address, city, district, phone or alias role, so supply those here. Roles: `name`, `alt_names`, `address`, `city`, `district`, `state`, `pin`, `latitude`, `longitude`, `phone`, `type`. Dot paths reach into `source_row`. |
| `--external-attributes` | Optional sidecar keyed by `external_facility_id` with `aliases`, `phones`, `district`. These values exist only in a producer's raw artifact; the contract has no column for them. |
| `--identity-policy` | D-format namespace policy. Without it no identifier is used and nothing confirms automatically. |
| `--postal`, `--postal-mapping` | Postal directory rows and their observed column mapping (`pin`, `state`, `district`). |
| `--config` | JSON object overriding the retrieval settings listed below. |
| `--sample-size` | Review sample limit, default 50. |

A real export nests original columns under `source_row`. With that shape the run stops unless `--source-metadata` or `--base-mapping` is supplied: no source column is ever guessed.

With D's prepared package and A's Rajasthan extract the pilot run is:

```sh
python -m research.matching.run \
  --base data/local/base-exports/NEW_RUN/base.json \
  --source-metadata data/local/base-exports/NEW_RUN/source_metadata.json \
  --base-mapping data/local/matching/base-mapping-extra.json \
  --external data/local/acquisition/rajasthan-v1/explicit.json \
  --output-dir data/local/matching/rajasthan-explicit-v1
```

`NEW_RUN` and the extra mapping are placeholders until an authorized export exists. Add `--external .../additional_review.json` for recall, or the national batch for a full pass. The shared synthetic base already uses role names as keys, so it runs without a mapping. See `examples/` for the file shapes.

Outputs, all canonical JSON, byte-identical on rerun:

- `batch.json`: the contract envelope with match rows and open review items. Give this to D.
- `candidates.json`: every kept pair with its signals, flags, rank and counts of alternatives.
- `review_worksheet.json`: the review sample with both source rows side by side. Contains source text.
- `geography_report.json`: coordinate flags, proposed corrections, coordinate clusters and postal context for base and external records.
- `report.json`: denominators and counts. `manifest.json`: SHA-256 of every input and output.

## Nationwide run (NAT-C01)

```sh
python -m research.matching.national --base <file> --external <batch> --output-dir <path>
```

This wraps the matching run for the full base and writes one output row for every original base row. It takes every argument of the matching run, plus:

| Argument | Meaning |
| --- | --- |
| `--duplicate-groups` | D's duplicate-group sidecar. An array of groups, or an object holding one such array. A group is an array of row handles, or an object with exactly one array of row handles and optional `original_id` and `multiplicity`. The run fails unless these groups equal the ones found in the base, each declared `multiplicity` equals the number of handles, and each declared `original_id` is the ID every member row carries (the ID column comes from `--source-metadata`). Other fields are not verified and are listed in the report. |
| `--expect-duplicate-groups` | Fail unless exactly this many identical-payload groups exist. Use 11 for facilities version 0. |
| `--state` | Limit the run to base rows with this state label. This is the scoped pilot. |
| `--missed-sample-size` | Limit for the sample of unmatched rows, default 50. |

With `--source-metadata`, the metadata must record `base_file_sha256` and it must equal the hash of the base file given to the run.

**Identical repeated rows.** The pinned base holds a few rows that repeat one full payload under different row handles. Matched as separate rows, each copy would count the other as a competing base row for the same reference, which flags a campus ambiguity that is not in the data. The nationwide run therefore groups rows whose whole payload is identical (everything except `facility_id`), retrieves candidates for the first handle of each group in sorted order, and copies that result to every handle in the group. The copies are interchangeable. A copy is never a second campus and never independent evidence. Rows that share an ID but differ in payload are not grouped.

**Identifiers are counted over every original row.** D's validator counts identifier uniqueness across the full base. The nationwide run does the same, including copies and rows outside a `--state` scope. An identifier carried by two copies is therefore not unique on the base side, so a group of copies confirms nothing automatically: its candidate stays a candidate with the review reason `identifier_not_unique`, and both rows are reported as `ambiguous`. `national_report.json` counts these groups under `identical_payload_groups_detail`. Confirming such a group needs a reviewed, group-aware rule agreed with D and the integration lead. Until then the envelope passes D's validator on the full base.

Outputs are the six files of the matching run, computed on one row per distinct payload, plus:

- `base_rows.json`: one row per original base row in scope, in base order. `matched_as` is the handle whose result the row carries, `duplicate_group` and `duplicate_multiplicity` describe its group, and `outcome` is one of the four values below. It also lists the outcome per source, any automatically confirmed external IDs and the row's input problems.
- `duplicate_groups.json`: every identical-payload group with its members and representative.
- `missed_sample.json`: unmatched distinct payloads for adjudication, round-robin across states, ordered inside a state by the SHA-256 of the row handle.
- `national_report.json`: outcome counts overall, by state and by source, input problems, source overlap, and both denominators (original rows and distinct payloads).
- `timing.json`: load time, matching time and peak memory. It depends on the machine, so it is not listed in `manifest.json`.

`batch.json` names only the representative of each group. Join `base_rows.json` on `matched_as` to reach the other handles.

| Outcome | Meaning |
| --- | --- |
| `confirmed` | An automatic shared-identifier confirmation under the supplied identity policy. Without a policy this is always zero. |
| `ambiguous` | At least one candidate is flagged `ambiguous_campus`, or an identifier was blocked (`identifier_not_unique`, `identifier_conflict`, `identifier_campus_conflict`). |
| `candidate_only` | At least one candidate and neither of the above. |
| `unmatched` | No candidate was retrieved. |

Input problems are counted separately and overlap the outcomes: `name_missing`, `coordinates_missing`, and the base geography findings (`coordinates_incomplete`, `possible_swapped_axes`, `state_disagrees_with_pin` and the others listed under Geographic checks). In the by-source table, a row is `unmatched` for a source when that source returned no candidate for it, so every source row adds up to the same denominator.

These are retrieval outcomes. None of them is a reviewed identity decision.

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

`footprints.select_cases` picks up to 10 disputed pairs (name strong or moderate, coordinates more than 1 km apart) and 10 controls (name strong, within 150 m, no conflict or ambiguity) from a run's candidates, ordered by SHA-256 of the match ID, and returns all eligible cases when there are fewer. Each selected case carries the base ID, match ID, claimed base point and, when different, the external point. The observer links a footprint only through that same confirmed campus pair. Claimed base coordinates stay in the review ledger until their campus pair is confirmed. Observations for rejected or competing pairs also stay in the ledger.

The extract script reads only 500 m boxes around at most 40 points from one pinned release and selects `id`, `sources`, `subtype`, `class` and geometry. It selects no height, floor count or area. `building_snapshot` builds the snapshot row from the extract's bytes, with independence `shared_origin` because Overture reuses OpenStreetMap and other inputs.

For each point the check records the nearest footprint within the radius, the distance in metres to its boundary (0 inside) and the feature's upstream datasets. The evidence row has claim type `location`, no service and no excerpt. Polarity is `supports` only when the point is inside a footprint, the feature identifies its upstream dataset and has no known shared OpenStreetMap origin with the identity record, and it is not older than `--stale-before`; otherwise `inconclusive`. It is never `contradicts`. No footprint within the radius writes no evidence, only a ledger line and a low-severity review item: absence is unknown. Capture date stays null unless the feature states one. Rows are written only with reviewer metadata, because the claim comes from a different source than the identity record; they are linked to a base row only when its match is confirmed.

## Limits

- Fixture results, public-source results and live Databricks results are separate. The handoff states which exist.
- Retrieval coverage is not match precision. Thresholds are uncalibrated.
- Name folding handles Latin script and common English abbreviations. Other scripts fall back to exact folded comparison.
- Phone numbers, districts and aliases for external records need the sidecar until a producer supplies them.
- The Overture extract script follows the documented release layout and has not been run against the live bucket from this checkout.
