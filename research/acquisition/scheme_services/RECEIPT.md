# Developer F · scheme scope receipt · 2026-11-22

Assignment: [#167](https://github.com/vzhu08/databricks-datathon/issues/167), under
[#161](https://github.com/vzhu08/databricks-datathon/issues/161).
This is a reproducible national candidate comparison and an auditable service
evidence gap. It does not approve a campus, procedure count or routing change.

## National result

The verified VF v0 input SHA is
`27e4a79de42ec56c76cc676ed45494a52497d179858bc50549a461434c45e9d8`.
All **10,088 occurrences / 10,077 source IDs / 11 identical pairs** survive.
The output retains **30,264 three-service decisions**, all unconfirmed, with
zero eligible new yes/no decisions relative to the
[#147 approved-pair baseline](https://github.com/vzhu08/databricks-datathon/issues/147#issuecomment-7074224222).
This reproduces the empty-adjudication status over the frozen base, not the full
#147 original-text/identity analysis. Incremental identity coverage against the
NHP/OSM/Overture candidate sets has not been measured.

The shared matcher returned 101 candidate links across 82 original occurrences:
51 candidate-only, 31 ambiguous, zero confirmed; 10,006 unmatched. These are
exploratory candidates from sharing-held source editions. They are not eligible
coverage gains or independent campus confirmations. State summaries retain all
36 state/UT buckets, including zero-count buckets, plus 390 unrecognized labels
and 58 missing labels. Source scope remains Delhi/NCR and a Kolkata employer
subset; there is no India-wide roster-completeness claim.

| Literal service screen | All-edition mentions | Selected campus-record observations | Exact identity proxies | VF candidate occurrences |
| --- | ---: | ---: | ---: | ---: |
| Dialysis | 186 | 62 | 61 | 18 |
| MRI | 49 | 16 | 16 | 3 |
| Trauma | 6 | 2 | 2 | 0 |
| CT | 99 | 23 | 23 | 4 |
| Orthopedics | 283 | 94 | 93 | 28 |
| Neurosurgery | 203 | 69 | 68 | 23 |
| ICU / critical care | 69 | 19 | 19 | 4 |
| Blood / components | 12 | 3 | 3 | 0 |
| Burns | 3 | 1 | 1 | 0 |
| Pediatrics | 223 | 60 | 59 | 16 |
| Emergency surgery / ventilation | 0 | 0 | 0 | 0 |

Counts overlap across services. The 1,133 literal mentions include exclusions
and revisions; they are not positive capability assertions. Each represented
service has one observed common CGHS origin and zero independently established
corroborating origins. Identity proxies are exact normalized
name/address/geography combinations, not verified physical campuses. The ledger
retains two wording-variant groups, all original scope cells, validity wording,
page/table locators and cue flags. Absence from the vocabulary screen is not
absence of service.

## Opened editions and access gaps

Four previously captured BIS editions were hash-verified: HQ October 29,
November 2 and November 10, 2026, plus ERO Kolkata April 19, 2024. All 884 record
observations remain; newest-per-series selection retains 301 records, comprising
297 campus observations and four group records. Selected campus geography is
Delhi 202, Uttar Pradesh 58, Haryana 31 and West Bengal 6. The three HQ revisions
and their common upstream scheme are not independent evidence.

The [BIS October edition](https://www.bis.gov.in/wp-content/uploads/2026/10/Circular-and-224-cghs-cashless-hospitals-as-on-29-Oct-2026.pdf)
is an employer cashless/empanelment compilation. Its scope and dates do not
establish performed procedures or current operational readiness. The
[BIS reuse policy](https://www.bis.gov.in/copyright-policy/?lang=en) retains a
third-party exception; four-person redistribution of original rows remains
under review. All six restricted original PDFs in #68 remain excluded.

The 13 direct public endpoint attempts are frozen in `source_attempts.json`:

- NHA PM-JAY and HEM hospital search returned 403; the PM-JAY public dashboard
  timed out. No campus procedure-activity export was obtained. No patient-list
  endpoint was queried.
- OGD direct access was refused. Inconsistent/stale indexed catalogue responses
  do not establish that the catalogue is empty.
- NABH's programme page opened directly, while its linked certified-list URL
  returned 404. The older applicant and status indexes display 348 and 567
  city/category rows respectively, not hospital totals. The recommendation page
  displayed a header without records; the underlying register is not declared
  empty.
- The programme page links a seven-page
  [February 17, 2026 notification](https://nabh-portal-live.s3.ap-south-1.amazonaws.com/wp-content/uploads/2026/04/23171218/Notification-for-CGHS-Empanelement-February-2026-1.pdf).
  It supersedes the January notification and describes eligibility/application
  processing, not observations of delivered services at named campuses. Page 1
  was visually checked. The older September 2024 notice is retained as history.
- [NABH terms](https://nabh.co/terms-and-conditions/) require prior consent for
  commercial redistribution. This receipt does not infer a blanket prohibition
  on noncommercial use; applicability to four-person raw sharing is unresolved.

## Verification and handoff

Eight synthetic collector tests and 23 shared service-status tests pass. The
shared matcher suite ran 120 tests successfully (two optional tests skipped).
The national offline replay reproduced all ten JSON outputs byte for byte. Source
and base hashes were checked before the run. Public Git files contain only
code, synthetic test values, aggregate results and public provenance metadata.
The unredacted observations, VF rows and candidate links remain private.

Private summary SHA:
`28e62406564f82f61eedc6f3b80563844828da47b09b41815d7730d49d526019`.
Three-service artifact SHA:
`666a652f20f8c8930d7a202b782798ea32a9e0e9ef0e09e4622a1c9daa1852f1`.
The public aggregate receipt records the remaining private output digests.

**Live Databricks:** not performed; F has no configured CLI profile. The
[staged writer handoff](https://github.com/vzhu08/databricks-datathon/issues/160#issuecomment-7074617801)
contains six eligible files (6,262,639 payload bytes) plus a manifest, SHA
`eea92b588c4093d1fa3ea84a858ebf230aee10213af00e3d53d9ac56888ddd64`.
The package contains authorized VF-derived unconfirmed status and current/prior
provenance and aggregate inventories, with no source originals or excerpts.
The existing writer must upload and return hash/size/count readback; F retains
receipt ownership. Raw source sharing and campus review remain separate holds.

**Submission:** not performed. Vincent reviews evidence and rights; Oliver owns
merge, release and readiness decisions. No routing inputs were changed.
