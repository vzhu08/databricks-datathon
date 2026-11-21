# Clinical Establishments register acquisition

SRC-A01 ([#63](https://github.com/vzhu08/databricks-datathon/issues/63)) inventories the
[Ministry index](https://clinicalestablishments.mohfw.gov.in/en/node/1390), captures
access outcomes and raw hashes, and produces unlinked v1 identity references from
explicitly cleared, reviewed PDF layouts. Real documents, parsed rows and manifests
belong in ignored `data/local/` or an independently authorized private location.

## Current source intake

The November 21 inspection reconciled 28 linked jurisdictions: 13 in the first
section and 15 in the second. Punjab adds a notice-only 29th printed entry. There
are 35 substantive destinations: 28 PDFs and seven portals. Gujarat has three PDF
parts and Tamil Nadu six. The 28 empty/icon-only anchors are retained separately;
their repeated unrelated targets do not establish the surrounding jurisdiction's
coverage.

All 28 PDFs were fetched (5,857 pages). Three portals responded, three timed out,
and Mizoram returned HTTP 403. The 31 successful destination captures have distinct
SHA-256 hashes. Nine pages lack extractable text (six Meghalaya, three Jharkhand);
they need visual/OCR review if rights are cleared. Portal discovery records 34
unique Kerala document links and 41 Odisha links (35 have substantive labels,
including administrative documents). These child files have not been fetched or
admitted. Madhya Pradesh exposes a directory form, not a captured bulk file.

**No real source is cleared for the accepted batch.** The Ministry's
[copyright policy](https://clinicalestablishments.mohfw.gov.in/en/copyright-policy)
requires permission requested by email before reproduction and excludes third-party
material. Its [terms](https://clinicalestablishments.mohfw.gov.in/term-conditions)
also defer linked-site rights to their owners. Portal rights remain unassessed.
Vincent owns the permission/intake decision. Public accessibility, attribution or a
registration statute alone is not recorded as reproduction permission.

Private seed inspection reconciles 2,827 Rajasthan serials across 134 pages and
331 Telangana serials across 11 pages. Neither seed supplies a registration-ID
column: printed serials are retained as locators, never relabeled registration IDs.
The first pages label their data August 2026 and June 2026 respectively. Exact
publication/effective dates remain null. The Telangana document covers two printed
district labels, not the whole state's population. A source spelling anomaly in
one state cell remains verbatim and flagged. No VF overlap, campus confirmation,
incremental national yield or live service status has been established.

## Commands

Use Python 3.9+ and install `requirements.txt` in an isolated environment. Run from
the repository root. `PRIVATE` below is an ignored private directory, not a tracked
fixture directory. Capture the index HTML there before inventorying it.

```sh
python -m research.acquisition.clinical_establishments.inventory \
  --index "$PRIVATE/raw/index.html" --out "$PRIVATE/inventory.json"
python -m research.acquisition.clinical_establishments.fetch \
  --inventory "$PRIVATE/inventory.json" --root "$PRIVATE"
python -m research.acquisition.clinical_establishments.audit \
  --acquisition "$PRIVATE/acquisition.json" --root "$PRIVATE" \
  --out "$PRIVATE/document-audit.json"
python -m research.acquisition.clinical_establishments.inventory \
  --acquisition "$PRIVATE/acquisition.json" --root "$PRIVATE" \
  --out "$PRIVATE/portal-inventory.json"
python -m research.acquisition.clinical_establishments.parser \
  --pdf "$PRIVATE/raw/SHA256.pdf" --seed rajasthan \
  --out "$PRIVATE/rajasthan-inspection.json"
python -m research.acquisition.clinical_establishments.producer \
  --root "$PRIVATE" --manifest "$PRIVATE/release-input.json" \
  --out "$PRIVATE/release-v1"
python -m pytest -q tests/research/acquisition/clinical_establishments
```

`fetch` retains the first successful bytes and retrieval timestamp. Changed cached
bytes fail verification. `--retry-failed` records previous failed attempts before
retrying transient errors; HTTP access restrictions are not retried. Downloads use
two workers, time and size bounds, and no authentication or access-control bypass.
`audit`, `parser` and `producer` are offline. The parser output is inspection data;
it is not a rights decision or an accepted acquisition batch.

## Release manifest and gates

Each `documents` entry in `release-input.json` names a relative `capture_receipt`
and a `rights` decision. An absent/non-cleared decision emits a hold in
`release-report.json`, with no source, facility or evidence row. A cleared entry
also requires a reviewed `profile` and `metadata`. All paths stay inside the
private package; raw hashes are verified before checking clearance.

```json
{
  "documents": [{
    "capture_receipt": "receipts/example.json",
    "rights": {"status": "permission_required"}
  }]
}
```

A real clearance must identify `status: "cleared"`, the exact source `url` and
`sha256`, `intended_use: "private_acquisition_and_team_review"`, `basis`,
`basis_uri`, `reviewer` and UTC `reviewed_at`. This does not authorize public
publication. Metadata requires `publisher`, `source_family`, `source_key`,
`layout_reviewer` and UTC `layout_reviewed_at`; `published_date`, `effective_date`,
`source_date_text` and `source_date_locator` preserve distinct temporal evidence.
The synthetic tests demonstrate a complete cleared manifest without implying that
any public source has been cleared.

Profiles declare exact permitted column counts, non-contact column mappings,
registration namespace, index jurisdiction and reviewed header rows. An optional
`sha256` binds a profile to a snapshot. Additional layouts require inspection and
an explicit mapping; there is no guessed catch-all PDF parser. Telangana's split
tables are joined only when left/right column counts and every physical row's
vertical bounds agree. Unknown layouts, unresolved continuation rows, missing
serials and pages without detected tables withhold the whole source from release.
Rejects retain locators and reasons in private inspection output.

## Identity and evidence semantics

- Snapshot IDs hash source URL and raw content. Facility IDs hash snapshot ID and
  page/table/physical-row locator. Different registration namespaces and repeated
  registration values cannot collapse records. Raw-byte aliases count once.
- `source_record_id` preserves a supplied registration ID or null. The identity
  sidecar preserves its namespace, printed serial, district, original state, source
  date wording and selected fields. Original names/addresses remain intact; name
  normalization is a separate field. Contact columns are excluded.
- Missing names/addresses and invalid PINs remain visible. PINs are text; invalid
  source values stay in the sidecar and become null in the normalized field. The
  parser never invents a PIN from an address or repairs source geography silently.
- Registration and generic medical categories support identity only. Only an
  explicit service-column mention produces a service observation, always unlinked
  and `inconclusive`, with exact wording, a locator and an open review. Referral,
  planned or negative wording is never converted automatically to a positive claim.
  A name containing MRI/dialysis/trauma does not produce service evidence.
- Every producer build invokes D's schema/cross-table validator with the batch
  supplied twice. It writes `batch.json`, `identity-sidecar.json` and
  `release-report.json` atomically and refuses a conflicting overwrite. The same
  raw bytes, capture receipt, profile, rights and metadata replay identically.

Fixture validation, private public-source inspection, accepted source intake,
Databricks publication and submission are separate receipts. The current empty
accepted batch expresses the permission holds; it is not an acquired national
facility dataset. Andrew owns original-campus linkage in #57; Vincent owns source
acceptance and national comparison in #58.
