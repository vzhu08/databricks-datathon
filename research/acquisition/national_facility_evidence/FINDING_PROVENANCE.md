# Find care provenance at claim grain

## Handoff to the app

Use `project_find_care(response, asked["service"], mode=mode)` with the response and the **stored submitted request** from the same search. Do this before `find_care.present` converts raw card fields to display strings. An edit is still a stale response until the next search. Rebuild panel state when its submitted request changes. [Binding receipt](https://github.com/vzhu08/databricks-datathon/issues/302#issuecomment-7081354377)

Use configured `mode="demo"` only for the shipped demonstration search. Each `findings` entry contains its `result_group` (`direct_results` or `indirect_leads`), zero-based `index`, and separate `location` and `service` claims. Match these positions to the result list for that exact response, including backups and related leads. The result list ordering stays with the finder. Use `mode="warehouse"` only with the output of the existing `find_care.withheld()`. That path returns a result-level `summary` and an empty `findings` list. It allowlists search status and the `direct`/`related` text signal. Counts, provenance, branch and dates are null when unmeasured, including on `no_match` or `unavailable`. Those outcomes supply no affirmative or negative onsite finding. [Warehouse boundary](https://github.com/vzhu08/databricks-datathon/issues/302#issuecomment-7081373797)

The adapter is a standard-library-only file. The app owner can package `finding_provenance.py` alongside the app and import from the deployed app directory. The example generator intentionally relies on the repository fixture and search function. The deployment needs only the mapper. Neither the canonical fixture nor the shared search result shape changes.

## Claim fields and dates

| Field | Interpretation |
| --- | --- |
| `precision` | On a location claim, the finest supported category at that scope. A search-origin PIN, centroid or straight-line distance supplies no facility precision. The demonstration card can supply a reported position, postal area, city/locality or unknown. A reviewed written address, a named campus and a verified entrance use distinct categories. |
| `decision` | On a service claim, `yes`, `no` or `unconfirmed`. The mapper can carry an existing review only at its exact scope and date, with a matching onsite statement or explicit applicable absence/all-cases referral. `review` presents its scope and as-of date separately. The number of sources has no effect on this decision. |
| `strength`, `scope`, `as_of` | `reported` for a relevant single-origin or unresolved-lineage report, `corroborated` for two documented independent origins at the same fact and scope, `conflicting_evidence` for an applicable opposition, or `no_evidence` where the supplied records have no applicable support. Null means the evidence is unmeasured. |
| `sources` | A caller supplies only cleared observations. Each contains publisher, origin or unknown, exact field/page when known, fact, scope, and `support`, `conflict` or `context`. A citation has `claim` or `record` grain. A record pointer adds no observation and no independent origin. Use `match="exact"` only with a documented match to this fact, branch and precision. `reported` retains a native report at its stated scope and `different` keeps another scope as context. |
| `observed_on`, `effective_from`, `effective_to`, `archive_captured_at` | Keep the actual observation date and effective period separate from capture. An as-of comparison uses the observation date itself or a bounded interval covering the comparison date. Unbounded or undated relevant wording can remain reported, with its time scope unresolved. Historic or incompatible exact statements and alternate branches stay as context. |
| `source_records`, `independent_supporting_origins`, `missing_check` | Counts of supplied evidence records and documented independent origins are distinct. Copies share an origin. Unknown lineage or unassessed independence leaves the total null even when a documented subset supports corroboration. Separate the measured zero of a supplied empty set from a missing count. The missing check describes the specific unresolved claim. |

## Reproducible demonstration cases

Run from the repository root. This command reads only the six synthetic facilities and emits JSON for the existing app and withheld-result shapes.

```sh
python -m research.acquisition.national_facility_evidence.finding_examples
```

Render `example.invalid` record references as text. The actual fixture field supplies the displayed claim.

| Actual synthetic search | Location | Requested service |
| --- | --- | --- |
| Dialysis, PIN 302001, 50 km, first direct result | Reported position from the synthetic location fields | Unconfirmed · Reported. The fixture's `procedures` field says North Campus provides hemodialysis. The statement date and exact applicable premises remain unverified. The fixture link is a record pointer. |
| Same request, backup | Reported position from its own synthetic location fields | Unconfirmed · Reported. The backup has its own `capabilities` text and source scope. It inherits neither the first card's link nor any review. |
| Dialysis, PIN 302001, 2 km, related result | Reported position from its own synthetic location fields | Unconfirmed · No evidence of onsite dialysis. The `description` nephrology-consultation mention is context. |
| Both shapes after `withheld()` | Unknown at result grain | Unconfirmed. Direct or related text signal only, without a per-facility record, scope, citation or measured source count. The example uses synthetic input for both gated shapes. |

## Real inputs and existing audience boundary

These are source mappings for the approved grain. The primary app's warehouse output still supplies only its withheld summary. Judge walkthrough clearance follows the two exact approved payloads and their named audience. The writer's separate receipt identifies the minimum field approval eventually required for a real named branch. [Audience and field handoff](https://github.com/vzhu08/databricks-datathon/issues/302#issuecomment-7081373797)

| Existing evidence | Admissible interpretation |
| --- | --- |
| VF v0 original location fields and wording ledger | A native PIN/address/point is a reported field at its own precision. Raw `procedure`, `capability`, `description`, `equipment` or `specialties` can report a service, at the original field/span grain. A VF-only reported statement stays unconfirmed absent applicable branch review. Underlying origin and observation date remain unknown when the fields do not establish them. `source_urls` and prepared `record_source_urls` are record pointers. A copied hospital source or VF pointer to that page supplies one lineage unless independence is documented. [VF metadata limitation](https://github.com/vzhu08/databricks-datathon/issues/86#issuecomment-7070699873) |
| India Post context and directory v4 | Credit Department of Posts, Government of India at postal-area scope. The cleared directory aggregate covers 10,088 original occurrences: 7,418 area-only, 2,524 campus classifications and 146 unresolved. Area breakdown is 6,988 postal, 328 city and 102 locality. A named map listing remains a directory classification. A written-address research rule in #300 has its own cohort/custody and supplies neither occupancy nor service. [Approved v4 projection](https://github.com/vzhu08/databricks-datathon/issues/270#issuecomment-7077111112) · [Address research receipt](https://github.com/vzhu08/databricks-datathon/issues/57#issuecomment-7080921663) |
| Frozen VF/OSM trace | 7 of 52 selected occurrence/service keys on 50 originals share the selected OSM object, split 2/12 dialysis, 0/6 MRI and 5/34 trauma. October HOT and November Geofabrik repeat the OSM lineage. Credit OpenStreetMap contributors. November snapshot/edit dates do not date service. All 104 associations lack a service observation date. NHP and an NHP-derived mirror share their registry origin. Neither repetition supplies a separate onsite statement. [Measured trace and locators](https://github.com/vzhu08/databricks-datathon/issues/58#issuecomment-7075721205) |
| National service decisions and issuer context | The November 21 baseline preserves 10,088 originals, 10,077 upstream IDs, all 11 identical pairs and 30,264 unconfirmed decisions (10,088 per service). Zero of the 497 covered specialist-lead occurrences had reviewed current onsite evidence at the same branch. The specialty screen and dates of capture cannot establish availability. The 49 NABH/QCI dialysis entries have zero exact VF links and zero dated onsite claims. The DMER MRI field is equipment inventory with unverified inventory date. MoHFW trauma programme statements retain their historical scope. [Frozen and joined denominator](https://github.com/vzhu08/databricks-datathon/issues/239#issuecomment-7080419548) · [NABH pilot](https://github.com/vzhu08/databricks-datathon/issues/221#issuecomment-7076224239) · [DMER inventory](https://github.com/vzhu08/databricks-datathon/issues/66#issuecomment-7069323869) · [Trauma programme scope](https://github.com/vzhu08/databricks-datathon/issues/65#issuecomment-7069678017) |
| Separate ESIC public case | The December 12, 2020 branch dedication is historical. The September 2026 report describes a shared complex and pooled 2025–26 activity. The statements share ESIC lineage through PIB. Current branch delivery remains unconfirmed. The public premises form is a link-only contextual reference, and no VF facility binding was established. [Approved public facts and scope](https://github.com/vzhu08/databricks-datathon/issues/252#issuecomment-7076403964) |
