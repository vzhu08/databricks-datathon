# Facility service status and provenance

For every version-0 Virtue Foundation occurrence, provide an answer for onsite dialysis, MRI and trauma care. The 10,088 source rows yield 30,264 unique occurrence/service decisions. Keep the original identifiers, including repeated pairs. Report distinct confirmed campuses separately. The patient-facing answer describes what the cited evidence establishes as of its date. Appointment availability, hours and capacity require their own evidence.

## Decisions

| Status | Required evidence at the identified campus | Example |
| --- | --- | --- |
| Yes | Reviewed evidence explicitly documents that the named campus provides that service onsite and applies to the displayed time and service scope. | The campus says it performs MRI scans onsite. Show the dated source and what it says. |
| No | Reviewed evidence explicitly says the named campus does not provide the service onsite, or sends all such cases elsewhere. Any temporary restriction is qualified by its effective period. | The campus explicitly says it refers all dialysis patients elsewhere during a stated period. |
| Unconfirmed | Evidence is absent, insufficient, historical alone, disputed, limited to another claim, or has unresolved campus or time scope. | A roster lists the institution, a group owns a scanner, the MRI inventory records zero machines, a trauma centre is planned, or two comparable sources disagree. Record the reason and preserve the underlying observations. |

Apply these rules to each service independently. Preserve exact source wording and location. A planned centre can also have separate, explicit evidence of current unavailability. Evaluate that statement on its own dates. Keep earlier evidence alongside a later superseding statement. Trust contemporaneous primary evidence only after its date, campus and provenance are reviewed. Unresolved conflicts remain visible.

## Mixed-campus records

Keep original fields unchanged. Compare normalized names, addresses, PINs and coordinates as derived fields. A row can supply an address for one campus and describe an MRI service at another. Record separate location and service claims with their own campus, wording, locator, dates and provenance. Keep both observations. An unresolved attribution affecting a campus leaves its service unconfirmed. Andrew owns geographic conflicts, competing campuses, suspected multi-campus records and zero-candidate outcomes in #57. Vincent adjudicates service evidence in #58 and #67. Oliver verifies the hash and original payload multiset after joins and publishes through #6. Carry unresolved rows through the run. [Scope decision](https://github.com/vzhu08/databricks-datathon/issues/67#issuecomment-7069340126)

## Minimal output

A lookup by occurrence key returns three service entries. Each entry carries the status, plain-language reason, as-of date where known and evidence references. Keep the original ID, URL or private source reference, publisher/family, exact field or page/table/row locator, retrieval date, source date and approved verbatim excerpt in the traceable evidence layer. Mark record-level URLs as record-level. An undated source stays undated. An unconfirmed result with no source records what was checked and why no conclusion was possible. Only permitted excerpts may appear in a public response.

## Nationwide comparison

1. Oliver prepares and verifies the version-0 base. Andrew matches it to the 146,847 existing national references. Vincent screens and adjudicates the original service fields. Freeze input hashes, output hashes, source families, rules and run ID for this baseline.
2. Run baseline plus each approved package independently, then all packages together. Record new confirmed campuses, newly supported campus/service pairs, prior claims corroborated by an independent family, shared-origin overlap and yes/no/unconfirmed transitions. Repeat each comparison by service, state/UT and unknown geography on the same denominator. Show source scope, unmatched rows and ambiguous identities.
3. Every producer hands off a replayable v1 batch. External evidence needs a confirmed campus link. Retain source date, original locator, snapshot hash and reuse terms. Keep ABDM HFR, PM-JAY and HospitalDoor bulk input conditional on authorized access. The four assigned packages can advance independently.
4. Freeze the combined output before the independent audit. Report identity and service conflict counts and unresolved cases by state/UT and unknown geography. Draw a reproducible two-reviewer sample including missed candidates and report deliberately selected challenge cases separately. Verify the original multiset, hashes, resolved references, idempotent imports and all 30,264 unique decisions. Publish validated artifacts through the existing additive tables and completed-run manifest. Record fixture, public-source, live Databricks and submission receipts separately.

[Base and publication](https://github.com/vzhu08/databricks-datathon/issues/6) · [National matching](https://github.com/vzhu08/databricks-datathon/issues/57) · [Service evidence](https://github.com/vzhu08/databricks-datathon/issues/58) · [Derived output and reviews](https://github.com/vzhu08/databricks-datathon/issues/67)
