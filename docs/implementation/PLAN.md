# Implementation plan · evidence acquisition sprint

## Outcome

Deliver nationwide identity/location corroboration and a Rajasthan trauma pilot as reproducible collection code, source snapshots outside Git, reviewed links, five Databricks Delta tables, and a coverage report. Building footprints are a secondary location check. [Board](OWNERSHIP.md) · [Contract](ACQUISITION_CONTRACT.md)

The human superseded the original first-pass assignments. Retain their useful practices: exact excerpts, campus preservation, synthetic fixtures, isolated write scopes, bound SQL parameters, and distinct local/live verification. Keep the existing search contract unchanged. App ranking, UI, deployment, and numerical authenticity-score calibration are downstream work, not silently included here.

## Acquisition and parallel execution

1. **D inspects the original data.** Use the authorized Marketplace table and included postal directory. Preserve original IDs, text, URLs, and campus distinctions. Record actual schema and missingness. Use a documented stable surrogate only if the source lacks an ID. No guessed live table names or fixture schema presented as real.
2. **A collects national identity references.** Download/reuse HOT OSM healthcare features and the NHP hospital-directory mirror. Capture provenance, dates, raw hashes, attribution, type coverage, duplicates, invalid coordinates, and normalized records. A mirror is not an additional independent source.
3. **B leads deep Rajasthan research through five chats.** Collect state trauma listings, RGHS identities, national trauma-program records, targeted NABH scopes/official hospital pages, and an independent audit. See B's task for planning, goal, subtask isolation, and evidence requirements.
4. **C resolves identities and geography.** Propose candidates against D's base IDs. Confirm only unambiguous same-namespace identifiers without conflicts automatically; other pilot links require review. Check postal context without row multiplication. Obtain small building extracts around ten disputed sites and ten clear controls when available.
5. **D publishes additive enrichment.** Validate and stage `source_snapshots`, `external_facilities`, `facility_matches`, `facility_evidence`, and `review_queue`, then publish a completed run after checks. Preserve the original facility table.

6. **E handles a small support task.** Ayuush checks eight source links and prepares a brief demo reference. This does not block acquisition or integration.

A/B public work and C/D fixture work start independently. Actual matching needs A/B batches plus D's base mapping; live publication needs workspace access. Download public snapshots locally and import them to a permitted Volume so execution does not depend on unrestricted outbound access from Free Edition.

Use public/free sources. Do not add paid imagery, patient data, hospital outreach, or portal automation that bypasses access controls. HFR/PM-JAY bulk integration is deferred; access failures must be documented, not hidden with synthetic substitutions.

## Quality and release gates

- Preserve original row IDs, count, and evidence wording; external/postal joins must not multiply base rows.
- Every external row/evidence item resolves to a source snapshot and locator. Confirmed links include method/rationale and required reviewer/timestamp.
- Deduplicate identical records deterministically; retain conflicting variants under repeated IDs and queue them. Replaying identical inputs creates no duplicates or conflicting replacements.
- Missing registry entries, dates, certificates, coordinates, or footprints remain unknown. Scheme suspension does not establish closure; appearance does not establish clinical quality. General emergency care does not establish a trauma level.
- Separate publication, retrieval, effective, and expiry dates. Old functional status remains historical; never label it current because the PDF was downloaded today.
- Audit up to 50 identity candidates and 30 trauma claims, or all available if fewer. Include same-name campuses, weak matches, conflicting coordinates, and undated evidence. Report denominators and actual coverage without manufacturing matches to meet targets.
- Run contract, referential, idempotency, failure-handling, raw-data exclusion, and attribution checks before publishing. Report public-source results and live Databricks results separately from fixture tests.
- Footprint sampling follows usable identity/service evidence; unavailable footprint checks do not block the core five-table handoff.

The pre-existing team target is November 22 at 11:45 a.m. ET, before the organizer's tentative 12:30 p.m. ET deadline. The orchestrator must reconfirm before submission. Acquisition completion does not imply app deployment or submission.
