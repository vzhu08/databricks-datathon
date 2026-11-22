# Independent readiness audit (#168)

This lane qualifies historical readiness and certification evidence and prepares a reproducible audit of D's frozen national ledger (#163). It cannot change service decisions, approve campus matches, or publish validated accuracy. The earlier #76 holdout is not an input. Do not open, copy, unseal, or compare its labels with this work.

## Current disposition

Source qualification produced rights/access gaps, documented in [SOURCE_QUALIFICATION.md](SOURCE_QUALIFICATION.md). No source rows from these candidates have been admitted. D's immutable row-level handoff is required before the national audit run. The #147 aggregate receipt is not a sample frame. Synthetic tests, including a full-size generated frame, demonstrate mechanics only.

Under the current #161 source allocation, Vincent's Windows collectors own further publisher checks/downloads for supplemental scout editions. L receives permitted readiness inputs and evaluates them; F (#167) reconciles NABH/QAI issuer scopes, and Vincent/B (#145) owns HMIS/NITI acquisition. Share the existing URLs, hashes, locators and rights findings on the receiving issue before any further fetch of the same edition. Do not duplicate collection or transfer restricted local snapshots as though permission were established.

## Private adapter and input checks

`audit.py` consumes L's internal `l-readiness-frame-v1` JSON. This is not a shared contract change. Once D publishes a contract, L must implement and test a read-only adapter, pin its original files, and reconcile counts before running. Do not fabricate a frame from aggregate counts.

The wrapper requires `freeze_sha256`, `original_payload_multiset_sha256`, `input_hashes` (filename to SHA-256), and `decisions`. The multiset hash is carried from D's independently verified receipt; this tool does not have the original payloads and does not itself verify their multiset. Every decision requires:

- `occurrence_key`, `source_id`, `service` (`dialysis`, `mri`, `trauma_care`), and original `status` (`yes`, `no`, `unconfirmed`).
- `state` and `region`, explicitly null when unknown. A documented region mapping belongs in the adapter and its hash; unrecognized state labels remain visible. Do not infer a region from hospital names.
- `conflict`: true, false, or null. False means a reviewed absence of conflict, not merely a missing flag.
- `independent_origin_ids`: reviewed distinct origin IDs, or null when unreviewed. Nonempty lists require an `independence_review_ref`; different publishers/URLs alone do not establish independence.
- `mentions`: all linked mentions, including repeats, negations, inaccessible evidence and superseded editions. Each has `mention_id`, nullable `claimant_id`, `origin_id`, `campus_id`, `observation_id`, and `observed_on`. Dates must be exact observation dates or null; retrieval, publication and selection dates are not substitutes. Preserve all additional original locator, date, unit, negation, scope, rights and campus-quality fields in this private frame.

An `observation_id` identifies one underlying observation, not a webpage, extractor result or occurrence copy. `campus_id` must be an approved link. Repeated editions and facility-authored mirrors share the underlying `origin_id`; a validation event can have its own observation ID while retaining its hospital/HMIS lineage. Uncertain lineage stays null or unresolved. The tool reports mention assignments, unique mention IDs, attributed campus/service/observation triples and origin IDs separately. The count of reviewed origin IDs does not assert that every origin is mutually independent.

National validation requires all 10,088 occurrence keys, all 30,264 decisions, 10,077 upstream IDs with 10,066 singletons and 11 pairs, stable identity/geography across each occurrence's decisions, and no duplicate decision keys. Missing geography, evidence and dates are retained. Only the Python test API permits `fixture=True`; the CLI always enforces national counts.

## Sampling and independent review

The fixed seed is `service-readiness-audit-168-v1`. Register the freeze hash and requested target on #168 before drawing or viewing reviewer outcomes. Each nonempty cross-stratum of service, region, original status, evidence time, claimant count, origin review, repeats and conflicts receives a hash-ranked pseudo-random sample. Use the pinned seed without rerolling. Allocation first takes two from non-singleton strata (one for singletons), then apportions the remaining budget in proportion to residual population using largest remainders. Each unit has probability `n_h / N_h` and weight `N_h / n_h`. Unique occurrence/service decisions remain the population, including the 11 duplicated upstream pairs; do not deduplicate them or claim campus-level accuracy from their weights.

The default hard budget is 30 service decisions, following the existing plan. If the cross-strata require more reviews, the sampler fails with the required minimum rather than expanding the workload, omitting a stratum, or claiming national inference with zero inclusion probability. Record that actual design constraint on #168 for Oliver to allocate more reviews or approve a coarser stratification before sampling. A target above the population produces a census. No production sample has yet been drawn.

The private plan contains predictions and strata. Give two independent human reviewers separate copies of the blank forms and a rights-approved evidence packet without model status, strata, confidence, other reviewer findings, or #76 content. Have reviewers confirm identity, exact service, onsite versus referral/training/equipment scope, applicable time, evidence access and shared origin. Record `yes`, `no`, `unconfirmed`, `uncertain`, or `unreachable`, evidence references and rationale. An inaccessible source is not a negative finding. Reviewer identity, UTC timestamp and independence attestation are mandatory before scoring; model-generated labels do not qualify. A third independent adjudicator resolves disagreements, preserving both initial records and the resolution rationale. Discovery of an original-claim error is not automatically a wrong `unconfirmed` service decision: report claim reliability and decision correctness separately.

Keep missed candidates and deliberately selected challenge cases in a separate register; they never enter probability-sample weights. Publish the complete selected denominator, two-review completion, disagreement, uncertain and unreachable counts, by stratum and service. Do not drop unresolved or unreachable units from a national accuracy denominator. Any later scoring implementation must bind reviewer files and adjudication hashes, use design weights, and report nonresponse bounds plus design-based sampling uncertainty. A confidence interval on only reachable/resolved cases is not national validation. This preparatory tool intentionally leaves accuracy and its interval null, with all selected cases unreviewed. Review and scoring are an explicit remaining dependency, not a successful check.

## Run after D's handoff and adapter review

Keep inputs and outputs in authorized private storage. The output directory must not already exist; reruns use a new directory and byte-compare outputs. Reviewer forms are blank on every initial run and cannot be overwritten in place.

```sh
python -m research.acquisition.service_readiness_audit.audit \
  --frame PRIVATE/frame.json --frame-sha256 EXACT_FRAME_SHA256 \
  --freeze-sha256 D_MANIFEST_SHA256 --as-of 2026-11-22 \
  --target 30 --out-dir PRIVATE/audit-edition
python -m unittest discover -s tests/research/acquisition/service_readiness_audit -v
```

Store shareable editions in the private Databricks intake volume under #160, including provenance, source/adapter hashes, plan and reviewer access separation. Verify remote byte hashes before calling a handoff durable. Restricted PDFs, protected labels and raw source rows are excluded until their own permissions allow transfer. Never commit real frames, source snapshots or reviewer labels. Fixture, live Databricks, independent review and submission status must be reported separately.
