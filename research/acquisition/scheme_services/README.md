# Scheme specialty scope research

This offline collector inventories literal service terms in checked CGHS scope
transcriptions and runs the existing national identity matcher against every
original VF occurrence. It retains all revisions, source scope cells, dates,
validity wording, scheme identifiers (when printed), page/table locators and
wording variants privately. All three clinical decisions remain unconfirmed.
Empanelment scope, accreditation and procedure eligibility do not establish
performed procedures, staffed readiness or current availability.

The input is an explicit, hash-bound manifest. `inputs` names `records`, `base`,
`metadata` and `duplicate_groups`, each with a `path` and raw-file `sha256`.
`sources` contains one provenance record per original PDF: `snapshot_id`,
`sha256`, `artifact_path`, `series_key`, nullable `document_date`, UTC
`retrieved_at`, `url`, `publisher`, `upstream_origin`, `local_analysis_allowed`,
`sharing_allowed` and `rights_reason`. Paths resolve relative to the manifest;
absolute authorized working-copy paths are also supported. Original bytes,
transcriptions, prepared VF base and metadata are verified before processing.

Source records use the checked #68 transcription fields: `record_id`,
`snapshot_id`, `source_sha256`, `document_date`, `record_kind`, `name_raw`,
`address_raw`, `scope_raw`, geography, and either PDF `fragments` or an explicit
`physical_page` with `locator`. Additional fields are retained unchanged.
Only `campus_observation` records from the newest dated edition on or before
`as_of` in each explicit series enter exploratory matching. Tied latest editions
remain unresolved. Groups, future/undated editions and older revisions stay in
the ledger. Printed serials are locators, never invented scheme IDs.

```sh
python -m research.acquisition.scheme_services \
  --manifest data/local/scheme-services/run_manifest.json \
  --out-dir data/local/scheme-services/run
python -m unittest discover -s tests/research/acquisition/scheme_services -v
```

The CLI requires 10,088 occurrences, 10,077 source IDs and 11 identical-payload
pairs. The shared matcher uses the inspected roles in D's metadata (name, state,
PIN, coordinates and type); this first pass does not add address/premises
retrieval or reuse the frozen NHP/OSM candidate set. It reports source-specific
candidate overlap, not incremental identity gains over that set. The shared
status producer reproduces an empty-adjudication baseline over the frozen VF
base, consistent with #147's zero approved campus-service pairs. It is not a
replay of #147's complete original-text ledger. No source rows or scheme terms
are admitted as clinical evidence. Consequently eligible clinical gains are
zero; no absence is interpreted as a negative service finding.

The term screen covers dialysis, MRI, trauma, CT, emergency surgery,
orthopedics, neurosurgery, ICU/critical care, ventilation, blood/components,
burns and pediatrics. It does not infer dialysis from nephrology or MRI from
radiology. Offsets and exact matched text refer to the original scope cell;
the complete cell is retained even when no term matches. Cell-wide exclusion,
referral, procurement and scheme-change cues remain unadjudicated flags. Long
exception lists and PDF line wraps are not automatically interpreted as
positive or negative statements. This vocabulary screen is not exhaustive
semantic extraction. Procedure count and unit stay null because these rosters
supply no admitted activity measurements.

`summary.json` distinguishes all-edition mentions, selected campus-record
service observations, exact name/address/geography identity proxies, upstream
families, independent corroboration and original VF candidate occurrences.
Identity proxies are not verified physical campuses. Historical revisions,
bilingual repetitions already identified in the input and shared scheme origins
must not become independent corroboration. Wording variants remain in a
separate private output without an inferred conflict verdict.

All generated files are private working artifacts, including
`candidate_batch_PRIVATE_NOT_ADMITTED.json`. Its v1 shape is solely an adapter
for the shared matcher, not an approved enrichment release. Local-analysis
permission and four-person sharing permission are separate. Held editions may
be analyzed only when `local_analysis_allowed` is explicitly true; outputs
retain the sharing hold. The six restricted originals in #68 are not inputs.
The dated [receipt](RECEIPT.md) contains only aggregate findings and public source
metadata. Rights and writer dependencies are tracked in #160.
