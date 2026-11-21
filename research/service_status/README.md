# National service-status lookup

Run from the repository root with a verified D-prepared base, its metadata and a JSON array of Vincent’s adjudicated reviews. Pass accepted v1 enrichment envelopes with repeated `--batch` arguments. For state/UT coverage and campus conflict flags, pass Andrew’s full `base_rows.json` with `--identity-rows`, its frozen file hash with `--identity-sha256`, and the corresponding `national_report.json` with `--identity-report`. Without these inputs, geography is unknown. An empty review array produces a coverage dry run. Keep the output in authorized private storage.

```sh
python -m research.service_status --base PRIVATE/base.json --metadata PRIVATE/source_metadata.json --reviews PRIVATE/reviews.json --as-of 2026-11-21 --out-dir PRIVATE/status
```

Record sources actually checked with repeated `--checked-source` arguments. These names are shown to patients, so use public display labels. The artifact name is its SHA-256. Replaying identical inputs and assessment date reproduces the same artifact. Each occurrence has three entries and a dated reason. Use `patient_lookup(artifact, occurrence_key)` for the patient-facing fields and `lookup(artifact, occurrence_key)` for the authorized review view. The private artifact binds the base, source metadata, reviews, optional identity outcomes, v1 batches and policy revision.

## Reviewed inputs

For a mixed-campus original, leave the address campus unconfirmed when the service belongs elsewhere. A separate review for the target can use `source.occurrence_key` to point back to the original source row. A cross-occurrence assertion requires a confirmed v1 `source.target_match_id` for the target, its exact name in the cited service excerpt and a reviewer’s `campus_resolution`. If the name or approved campus link cannot be established, keep the claim in review. The original location and wording remain with their source occurrence.

If positive reviews assign overlapping text in one original field to different campuses for the same service, each disputed attribution stays in the private ledger with the competing review IDs. An independent statement can still establish a campus’s status. A reviewer can also document that one passage explicitly establishes onsite service at multiple campuses. In that case, enter a positive review for each target, give each the same `joint_onsite_targets` array of occurrence keys, and cite an excerpt that identifies every target by its distinct name. Each review’s `campus_resolution` must name its own campus and explain how the wording attributes onsite service there. A passage that merely lists the campuses calls for further review. Only active reviews with an applicable onsite finding take part in a competing attribution.

Two differing assessments of the overlapping spans in the same original field, or the same external evidence ID are retained. A disputed statement cannot independently support a decisive status. If a reviewer resolves a prior assessment with a later applicable source, set the prior review’s optional `superseded_by` to the replacement review ID for the same occurrence and service. The private ledger preserves both. Rows from a group or other campus are never copied to another occurrence automatically.

Every review has a unique `review_id`, the prepared `facility_id`, service, finding, reviewer, timezone-aware `reviewed_at`, and the `assessed_for` date. For original text, record the exact field, Python character offsets, verbatim excerpt, and actual source date or null. A source family or effective interval may also be recorded. Record-level URLs remain on the original facility. For an external review, supply `{"kind":"external","evidence_id":"..."}` as its source. The accepted batch must contain a confirmed same-campus match for that service evidence. When a row’s own geography disagrees, a decisive claim from that occurrence requires a documented `campus_resolution`. Competing reference candidates alone do not dispute reviewed text about its own campus. A claim linked from elsewhere still requires campus resolution if any identity conflict is present. An explicit, active dispute about the campus keeps the service unconfirmed.

The finding is the reviewer’s assessment of the cited wording at the specified campus and time. The decisive values are `onsite_service`, `explicit_no_onsite`, and `referral_only`. Other findings include `campus_conflict`, `other_campus`, `historical_only`, `date_unclear`, `planned`, `equipment_only`, and `insufficient`. Inapplicable, expired and disputed evidence remains visible privately. Use the [service rules](../../docs/implementation/SERVICE_STATUS.md) for adjudication.

Synthetic example of an original-source review:

```json
{"review_id":"example-1","facility_id":"synthetic:base:001","service":"mri","finding":"onsite_service","reviewer":"fixture-reviewer","reviewed_at":"2026-11-21T18:00:00Z","assessed_for":"2026-11-21","source":{"kind":"original","field":"description","start":0,"end":10,"excerpt":"Onsite MRI","source_date":"2026-11-18"}}
```
