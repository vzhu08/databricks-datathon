# Nationwide facility validation plan

## Population and deliverable

Process every row of `databricks_virtue_foundation_dataset_dais_2026_databricks.virtue_foundation_dataset.facilities VERSION AS OF 0`. The verified denominator is **10,088 original rows**, with **10,077 distinct nonblank upstream IDs**. Keep all 11 pairs of identical rows. The sibling `india_post_pincode_directory VERSION AS OF 0` contains 165,627 rows and 19,586 distinct PINs. Group it by PIN before joining. Keep the original ID and fields alongside each unique processing key. [Source receipt](https://github.com/vzhu08/databricks-datathon/issues/36#issuecomment-7069028113) · [Row-preservation proof](https://github.com/vzhu08/databricks-datathon/issues/6#issuecomment-7069026841)

Produce a reproducible national matching and evidence run plus a coverage report for dialysis, MRI and trauma care. A row counts as processed when it receives an explicit outcome. Missing fields, ambiguous candidates and unsupported services remain visible. Report the number of processed original rows out of 10,088 separately from the number with a confirmed campus or supported service.

## Work by owner

| Owner | Deliverable |
| --- | --- |
| Oliver · A/D and integration | Own the board, assignments, reviews, merges and release coordination. [Integration handoff](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7070988307). Supply the complete versioned base, source mapping and hash. Apply the reviewed occurrence-key rule for identical repeats and prove zero lost or added payloads. Validate and publish the five additive tables through the completed-run manifest. [Preparation](https://github.com/vzhu08/databricks-datathon/issues/6) |
| Oliver · transferred C work | Own [storm and finder UI](https://github.com/vzhu08/databricks-datathon/issues/356). The existing campus matcher and controls are available to Vincent. |
| Vincent · campus verification | Run the indexed matcher on all 10,088 rows against the 146,847 national OSM and National Health Portal references. Carry missing-geography and zero-candidate rows through to the report. Record runtime, versions, state/UT counts and mutually exclusive identity outcomes. [National matching](https://github.com/vzhu08/databricks-datathon/issues/57) |
| Vincent · B | Maintain the three-service status producer and its coverage report. Assess original service fields across the full base. Preserve exact wording, field, URL, date and upstream family. Separate direct onsite support, planned/unavailable/referred-out wording and unresolved evidence. Link external service evidence only to a reviewed campus. [Coverage report](https://github.com/vzhu08/databricks-datathon/issues/58) |
| Ayush · E | Unavailable until his return is confirmed. The MRI check, NMC scout and shared-base account read are complete. [Account check](https://github.com/vzhu08/databricks-datathon/issues/60) |

## Source integration and patient information

Freeze the 10,088-row original-text and NHP/OSM identity baseline. Then compare it with each of the four assigned packages individually and with all four together. A bounded register can contribute when a repeatable national join measures its actual reach. Keep its observed jurisdiction, service and date on each result. The deliverable is **30,264 row/service decisions** across dialysis, MRI and trauma care, each carrying a reason and traceable provenance. The [patient-status rules](SERVICE_STATUS.md) define yes, no and unconfirmed. [Registers](https://github.com/vzhu08/databricks-datathon/issues/63) · [Dialysis](https://github.com/vzhu08/databricks-datathon/issues/64) · [Trauma](https://github.com/vzhu08/databricks-datathon/issues/65) · [MRI](https://github.com/vzhu08/databricks-datathon/issues/66) · [Integration](https://github.com/vzhu08/databricks-datathon/issues/67)

## Criteria for new datasets

Prioritize India-wide facility-level snapshots, permitted bulk downloads and documented APIs that can be compared with the entire original table. A nationwide specialist register may cover a subset of facilities; state its eligible population and measure overlap and incremental yield against all originals. Before adoption, verify permission, source family, snapshot date/hash, joint coverage with existing sources, and the states or facility types left uncovered. Count unique original records reached. A publisher’s row total alone cannot establish overlap.

Standalone regional collection and case studies have ended. Retain completed work as historical material with its geographic scope. Keep reserved evaluation sources independent of feature tuning. Where local evidence already exists, apply it only to eligible linked rows and keep its limited coverage explicit.

## Dataset storage and handoff

Use `workspace.default.datathon_vf_research_intake` for project sources and derived datasets cleared for Vincent, Oliver, Andrew and Ayush. Reuse a verified reference to an authorized, team-readable Delta table at an exact version or a pinned Volume edition when one already exists. Keep the Virtue Foundation facilities and India Post directory pinned to Delta version 0.

1. **Backfill existing datasets once.** Each owner inventories the sources and derived datasets their work depends on, including eligible local-only editions. Reuse verified Databricks copies. Stage the remaining authorized editions once and skip duplicate worktree copies and reproducible caches.
2. **Hand off new datasets when acquired or generated.** Store each new edition under a content-addressed path in the intake Volume and preserve prior editions. If your account is read-only, hand the edition to an existing Volume writer and keep ownership of the receipt. Include the publisher and edition, row grain, join fields, source URL and input lineage, sharing scope and reuse terms, file sizes and SHA-256 hashes, and record counts in the manifest.
3. **Verify from Databricks.** Read back the manifest and check remote file sizes, hashes and counts against it. For existing references, verify team read access, the exact version or edition, and the expected counts or file digests. Record the verified location, manifest digest or version, and any access or rights blocker in the owning issue. [Primary intake receipt](https://github.com/vzhu08/databricks-datathon/issues/67#issuecomment-7073773911) · [Supplement receipt](https://github.com/vzhu08/databricks-datathon/issues/67#issuecomment-7073806108)

Follow source-specific licenses and embargoes. When full rows cannot be shared, record the restriction and preserve permitted provenance and aggregates in Databricks. Keep the sealed independent audit within its existing reviewer scope. Keep source rows and credentials out of Git. Website display, public release and submission follow their own approval and source-use rules.

## Acceptance checks

1. Verify both pinned input versions, processing-key uniqueness, unchanged original text and equality of the original row multiset before and after joins. Repeated source IDs do not supply independent campus confirmations.
2. Keep normalized names, addresses, PINs and coordinates alongside original fields. Route mixed-campus, conflicting-geography and disputed service claims to the existing review queue with separate campus attribution. Include conflict and unresolved counts in the geographic breakdown. [Quality decision](https://github.com/vzhu08/databricks-datathon/issues/67#issuecomment-7069340126)
3. Reconcile mutually exclusive identity outcomes to 10,088, including unresolved and unmatched rows. Report state/UT breakdowns plus an unknown-geography group. For each service report supported, excluded and unknown outcomes using the same national denominator, with source-family overlap and missingness.
4. Freeze nationwide outputs before auditing accuracy. Draw a reproducible sample across the national population (up to 50 campus pairs and 30 service claims), include missed candidates, and keep deliberate challenge cases separate. Two reviewers check campus identity, wording, time and independence. Report audited denominators independently from population coverage.
5. Validate references, attribution, replay, idempotency and failure recovery before publishing. Keep source IDs, snapshots and row-level evidence in authorized private storage. Record local fixtures, public-source checks, live Databricks results, deployment and submission separately. [Contract](ACQUISITION_CONTRACT.md) · [Validation methods](VALIDATION_RESEARCH.md) · [Team board](OWNERSHIP.md)

The team’s submission target is November 22 at 10:00 a.m. ET. [Oliver’s deadline update](https://github.com/vzhu08/databricks-datathon/issues/223#issuecomment-7076669521) Reconfirm the organizer deadline before submission.
