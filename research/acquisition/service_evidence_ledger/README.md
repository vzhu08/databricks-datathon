# National service evidence ledger

Developer D owns this private, read-only artifact under [#163](https://github.com/vzhu08/databricks-datathon/issues/163). It preserves the pinned VF population, original payloads and baseline service decisions, and accepts separately pinned collector observations. It does not adjudicate services or modify the shared enrichment contract, routing inputs or service-status producer. Vincent owns campus/service review; L owns independent evaluation; Andrew consumes the documented output. Oliver owns integration and release.

## Current input boundary

The initial build uses the #147 manifest `735d089ae8926e98a8e4e22fe125aa48e51ebcb7fabdbe35ee087f3102fc8fec`, its six files, the referenced intake manifest `b2c5f30d4e517ff1589f64f316756fbbca502a05a7debc3329a4eed9c6b0a2fa`, the byte-pinned D base and all eight members of `vf-campus-service-research-v3.zip`. These establish 10,088 original occurrences, 10,077 upstream IDs, all 11 repeated-ID pairs and exactly 30,264 unconfirmed baseline decisions as of November 21, 2026. The original payload multiset must remain `30d32fa927f5d43753ea6d42f3685ea62e1b416a6cffce7e11ebd1d83b905ca6`.

The older B statement package was not readable under Oliver's existing profile at the first receipt. The additional-term and dated-triage row files are also required. #163 records the precise writer handoff request. Until those bytes are available, `original_statement_coverage` is `missing_packet`, verified span counts and incremental leads over original text are **null**, and zero loaded observations means **no observations imported**, not no evidence exists. The 15 repeat locators retained inside the v3 decisions remain there; they are not presented as the complete statement inventory. The national target is 3,038 dialysis, 3,136 MRI and 2,026 trauma field spans. These are distinct statement locators, not term-hit counts or reviewed clinical observations.

The baseline `identity` fields are explicitly the pinned LOC-04 v3 frame. Their geography, mixed-campus indicators and conflicts retain their original meaning. The newer joint Overture occurrence trace is preserved separately as `joint_identity`, with its original order, hashes, state labels and baseline service context verified. Its full candidate trace is referenced by the pinned `vf-joint-matching.zip` and every archive member is verified. This module does not silently relabel the older frame as the newer one.

## Reproduce

Run from the repository root on Python 3.12 with authorized local copies. All paths below are placeholders for private files. Do not commit source data.

```sh
python -m research.acquisition.service_evidence_ledger \
  --base PRIVATE/base.json \
  --intake-manifest PRIVATE/intake-manifest.json \
  --intake-sha256 b2c5f30d4e517ff1589f64f316756fbbca502a05a7debc3329a4eed9c6b0a2fa \
  --coverage-dir PRIVATE/coverage147 \
  --coverage-sha256 735d089ae8926e98a8e4e22fe125aa48e51ebcb7fabdbe35ee087f3102fc8fec \
  --research-dir PRIVATE/vf-campus-service-research-v3 \
  --joint-dir PRIVATE/vf-joint-matching \
  --out-dir PRIVATE/ledger-edition

python -m unittest discover -s tests/research/acquisition/service_evidence_ledger -v
```

Each input member is hash/size checked before use. The build verifies exact occurrence order, every payload hash and upstream ID, all duplicate multiplicities, state/decision joins, original multiset and the complete three-service key product. It uses no network or clock. Gzip timestamps are fixed. Identical inputs and code reproduce identical output bytes. An existing output directory is accepted only if every file matches; changed releases require a new directory.

## Read-only consumer contract: `service-evidence-ledger-v1`

Read `manifest.json` first, verify every listed file hash and size, and check `report.json` for missing inputs. JSONL files are UTF-8, gzip-compressed; null values mean unknown/unavailable. Facility keys refer to original occurrences. Two occurrences of an identical original row remain distinct keys and do not establish distinct campuses.

| File | Grain and consumer use |
| --- | --- |
| `occurrences.jsonl.gz` | One row per original, in input order. `original` retains the complete D-prepared row and untouched `source_row`; `identity` retains the complete pinned v3 row; `joint_identity` retains the newer joint matching comparison. Original ID, ordinal, payload hash, geography, candidate/campus state, conflicts and mixed-campus evidence remain in their source frame. |
| `decisions.jsonl.gz` | Exactly three unchanged baseline entries per occurrence: join `occurrence_key`, `service`. Existing reasons, as-of dates, reviews and repeated-wording locators are preserved. No collector observation changes these decisions. |
| `editions.jsonl.gz` | One immutable source edition. Publisher, content hash, originating family or unknown lineage, publication/retrieval dates, scope, source URL and private reuse terms. |
| `observations.jsonl.gz` | Every submitted observation occurrence, without deduplication. `ledger_id = SHA256(canonical([lane, observation_id]))`. `raw` retains the entire submitted object: wording, exact locator, dates, units, polarity, campus links and relationship references. |
| `reconciliation.jsonl.gz` | Groups by reviewed campus, modality, claim type, claim scope, value and units. Includes all observation IDs, known family counts, explicitly reviewed independent families and comparable opposing-polarity pairs. A group is not a clinical decision or a count of independent observations. |
| `shared_wording.jsonl.gz` | Exact same-modality text repeats, including repeated originals/editions. A shared text hash flags review; it does not prove copying or independence. Explicit `mirror_of` relationships remain in observations. |
| `facility_counts.jsonl.gz` | Every original occurrence, including those without imported evidence. Loaded observations, known families, unknown origins, mixed-campus and conflict indicators. `single_known_origin` counts known families only; inspect unknown-origin observations before claiming a single origin. |
| `report.json` | Population, statement completeness, zero baseline decision transitions, state/service counts including unknown geography, per-lane lead gains, family coverage and unmeasured independent accuracy. |

The manifest binds input editions, file counts, byte sizes, hashes and producer code hashes. The raw baseline files remain private. Public claims must use separately permitted aggregates; this artifact is not a patient care or availability feed.

## Adding collector editions

Use repeated `--lane PRIVATE/lane.json SHA256`. This is D's adapter input inside the assigned directory, not a replacement for another owner's producer schema. Adapters must preserve source rows and obtain the source owner's permission/edition receipt before asserting the exact `private_datathon_four_readers` sharing scope. Existing producer envelopes can be transformed into this representation by an explicitly reviewed adapter; no guessed campus joins are permitted.

Each JSON package contains `schema_version: "service-evidence-lane-v1"`, a unique nonempty `lane`, `editions` and `observations` arrays. Identical edition IDs across lanes must have identical metadata. Every observation has an ID unique within its lane. Distinct observations are retained even when text and all other attributes repeat.

An edition requires `edition_id`, `content_sha256`, `publisher`, `source_url`, `reuse_terms`, `sharing_scope`, `geographic_scope`, `source_family` (or null), `origin_status` (`known`/`unknown`), `published_date` (ISO day or null) and `retrieved_at` (timezone-aware timestamp or null). Source capture and publication dates are never substituted for service-effective dates.

An observation requires:

- `observation_id`, `edition_id`, `source_facility_id`, `modality`, `claim_type`, `claim_scope`, `claim_value`, `units` (or null), verbatim `raw_text` and nonempty `locator` object.
- `source_date`, `effective_from`, `effective_until`: ISO days or null. Preserve more precise/partial source wording in additional raw fields; never invent a full day from a partial date.
- `polarity`: `supports`, `contradicts` or `inconclusive`. These are supplied source assessments; no keyword/number-based inference occurs here.
- `independence_status`: `unassessed`, `shared_origin` or `reviewed_independent`. The last requires a known originating family and nonempty `independence_review` reference. Several mirrors of one family still contribute one family.
- `multi_campus`: boolean; `original_occurrence_key`: null for external records, otherwise an original key with `locator.field/start/end` resolving exactly to `raw_text` in the unchanged original (Python character offsets, end-exclusive).
- `target_links`: zero or more objects with `occurrence_key`, `campus_id`, `quality` (`unresolved`/`candidate`/`confirmed`) and `review_reference`. Confirmed links require a campus ID and review reference. Unlinked and ambiguous observations remain in the ledger.
- `mirror_of`, `supersedes`: arrays of imported `ledger_id` values. These preserve source-owner assessments; supersession never deletes the earlier observation or changes baseline decisions.

Only a single reviewed campus on a non-multi-campus observation enters a comparable group. Conflicts require equal modality, claim type, scope, value and units, opposite supplied polarities, and overlapping explicitly bounded effective intervals. Here `claim_value` is the proposition or measurement being supported/contradicted; the original wording is separately preserved. Missing/partial dates, separate time periods, equipment versus service, multi-campus and unresolved candidates do not create an automatic conflict. Numeric-value differences and differently phrased claims are retained for review rather than automatically equated. Known families and reviewed independence are reported separately. No likelihood or accuracy score is inferred.

Lane gains count linked **occurrence/modality leads**, including candidate/unresolved links. They are not reviewed campus/service gains. Gains over the original-text baseline stay null while that packet is unavailable. Empty lanes report zero imported leads. Additional modalities can be retained without adding or deleting any of the three baseline service decisions. `--complete-original-statements` is only valid after the pinned original and additional statement packages have been adapted and verified; national distinct locator counts must then equal the frozen 8,200-span target.

## Storage and handoff

Store an authorized edition under a content-addressed directory in `workspace.default.datathon_vf_research_intake`; preserve previous editions. If the receiving profile is read-only, hand the edition to Vincent's existing writer, retain ownership of the receipt and verify the eventual download. Record exact manifests, files, hashes/counts, access blockers and local-only disposition on #163 and #160. Fixture checks, local national replay, live Volume readback, Delta publication and submission are distinct receipts. This CLI performs neither remote writes nor Delta jobs.

## First external adapter: J's HOT/OSM packet

`hot_adapter` consumes J's pinned `hot-20261009-v2` manifest `f8b21b0396a06417178f45ba1381b64767766a4a4eb920dbb6676b9aae8a68a4`. It preserves every source row and all original locators, including name-only, broad specialty and generic capability categories. These categories are never promoted to onsite service evidence. OSM remains one shared originating family under its attribution/ODbL terms. The source map capture date never becomes a service-effective date.

The adapter joins only the same typed OSM ID in the same pinned snapshot to existing `joint` candidates. It expands retrieval representatives back to every original occurrence, including both identical rows. Retained and pre-cut candidates remain distinguished in each link's untouched `frozen_candidate` trace. No new matcher runs or confirmed campuses are created. The result is an attributed candidate lead, including when the evidence merely appears in a name. J's NHSRC state totals remain context outside the facility-claim ledger because they have no named campuses or campus join keys.

```sh
python -m research.acquisition.service_evidence_ledger.hot_adapter \
  --packet PRIVATE/hot-20261009-v2 \
  --packet-sha256 f8b21b0396a06417178f45ba1381b64767766a4a4eb920dbb6676b9aae8a68a4 \
  --intake-manifest PRIVATE/intake-manifest.json \
  --intake-sha256 b2c5f30d4e517ff1589f64f316756fbbca502a05a7debc3329a4eed9c6b0a2fa \
  --joint-dir PRIVATE/vf-joint-matching --out PRIVATE/j-hot-lane.json
```

Pass the output and its printed SHA-256 to the main build with `--lane`. The original statement packet is still required before measuring new leads over VF text. A replay with this lane retains the same 10,088 originals and 30,264 baseline decisions.
