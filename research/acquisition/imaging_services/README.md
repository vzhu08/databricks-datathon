# Imaging service evidence

Developer K's #166 offline collector preserves source observations and compares them across every original VF occurrence. New publisher acquisition is assigned to Vincent's Windows collectors under #161. This package has no network client, credentials, upload action, or clinical adjudication logic. It does not import or modify the unmerged #81 HINDLABS adapter.

Use Python 3.12 and `requirements.txt`. Only code, synthetic tests and source URLs belong in Git. Put manifests, annotations, originals, extracts, source rows, comparisons and rendered source pages in ignored `data/local/` or an authorized private Volume. A local path is not a Databricks receipt.

## Inputs and provenance

`collect` takes a JSON object with a `sources` array. Each successful capture supplies `key`, `url`, relative `path`, raw-byte `sha256`, UTC `retrieved_at`, nullable `published_date`, `publisher`, `source_family`, `geography`, `status: "ok"`, `sharing_status`, `reuse_reason`, and `pursue_or_stop`. Failed attempts remain in the register and cannot produce observations. Record `last_success` and the precise access failure in the private manifest. Sharing status is `permitted_private`, `restricted` or `pending_review`; collection does not authorize transfer.

Set `parser: "dmer"` only for the official DMER CT/MRI inventory. The existing MRI compiler retains its source IDs, aliases and group flags; this wrapper adds both CT and MRI equipment observations. Equipment zero is not hospital-wide service absence. Misaligned cells and malformed counts remain unknown. Repeated headers cannot shift CT/MRI attribution.

Other sources use a private annotation array. Required fields are shown in the synthetic test. Preserve the exact whitespace-normalized excerpt, a PDF page or unique HTML selector, source key, original subject, grain, modality, kind, period, unit, reported value, date fields, flags, interpretation reviewer and interpretation note. The collector verifies raw hashes and checks the excerpt at that locator. A PDF chart interpretation still requires visual review: text extraction alone cannot reliably associate chart values and periods. The reviewer records the source interpretation, not a confirmed VF identity or clinical service decision.

Allowed modalities are MRI, CT, combined CT/MRI, reporting and unknown. Allowed kinds distinguish equipment counts, commissioned/onsite reports, planned capacity, reporting only, offsite care, unavailable/closed services, network capacity and unknown. Network totals emit ledger observations only. Campus observations emit unresolved contract v1 evidence; CT remains separate in the ledger because the shared service enum does not include CT. CT never implies trauma care.

Snapshot identity uses source key and raw hash, never retrieval time. Persist the first capture timestamp on replay. A changed timestamp with the same snapshot ID is not a second independent source and an existing output cannot be overwritten. Stable annotation keys distinguish observations within the snapshot. Different source editions remain separate. Repeated publisher/subject/modality/period observations are counted separately from literal campus keys and never labeled independent confirmation. Literal campus keys are not reviewed campus deduplication.

## Commands

Run from the repository root, with `PRIVATE` replaced by the authorized private directory:

```sh
python -m research.acquisition.imaging_services collect \
  --manifest PRIVATE/manifest.json --annotations PRIVATE/annotations.json \
  --out PRIVATE/release

python -m research.acquisition.imaging_services reconcile \
  --legacy-root PRIVATE/hindlabs --current-manifest PRIVATE/manifest.json \
  --out PRIVATE/hll-reconciliation

python -m research.acquisition.imaging_services compare \
  --base PRIVATE/base.json --metadata PRIVATE/source_metadata.json \
  --control PRIVATE/hindlabs/release-final/batch.json \
  --addition PRIVATE/release/batch.json --as-of 2026-11-22 \
  --out PRIVATE/national

python databricks/enrichment/validate_batch.py \
  --base PRIVATE/base.json --batch PRIVATE/hindlabs/release-final/batch.json \
  --batch PRIVATE/release/batch.json --as-of 2026-11-22

python -m unittest discover -s tests/research/acquisition/imaging_services -v
```

`reconcile` audits the retained private HLL batch and raw snapshot hashes, separates directory rows from documentary observations, and preserves the nine-unit claim's conflict category. Held tenders are refused. Refreshed pages are compared by raw hash and normalized visible text; text equality is a repeat-content finding, not a semantic audit of the whole site.

`compare` uses the existing national matcher and service-status producer. It requires 10,088 occurrences, 10,077 upstream IDs and 11 identical pairs. The output retains every occurrence, unknown geography, duplicate membership, conflicts and all 30,264 decisions. Its control is exactly the supplied source batches. It does **not** claim incremental gain over the frozen #147 NHP/OSM/Overture release. D owns that integration and needs the pinned trace. An empty review ledger deliberately leaves all services unconfirmed and the list of clinically checked sources empty.

Output hashes include file newlines; `control_batch_hashes` and `addition_batch_hashes` in comparison metadata hash canonical JSON content without a newline. Outputs are deterministic and refuse an incompatible overwrite. Keep private candidate rows and service projections out of Git. Stage only source-authorized subsets and metadata with manifest hashes, readback and recipient-access receipts; restricted corpora require a separately permitted handoff.

Once D's verified `service-evidence-ledger-v1` baseline is readable, measure reach against its retained joint trace without rerunning a completed source comparison:

```sh
python -m research.acquisition.imaging_services frozen-reach \
  --base PRIVATE/base.json --ledger-root PRIVATE/d-ledger-readback \
  --manifest-sha256 PINNED_MANIFEST_SHA256 \
  --imaging-rows PRIVATE/national/expanded_rows.json --out PRIVATE/frozen-reach
```

This verifies all listed file hashes/counts, untouched original payload/order and the complete three-service decision product. It reports the candidate-reach union, including unknown geography, while preserving D's baseline dates. It does not rerank the joint top five, reconcile the service ledger or update any decision. The earlier comparison artifact remains an honest record of its unavailable-input boundary; this separate receipt supplies the subsequently available frozen-reach measurement.

## Source entry points and current boundaries

- [HINDLABS network](https://hindlabs.in/networks) and [HLL diagnostics](https://www.lifecarehll.com/page/render/reference/Diagnostic_Services_Division): one operator lineage; inherited raw/derivative sharing restrictions remain in force.
- [DMER equipment inventory](https://dmer.maharashtra.gov.in/english/list-of-hospitals-with-ct-mri-facilities/) and [current policy](https://dmer.maharashtra.gov.in/english/website-content-management-policy/): a Maharashtra supplement. Attribute the institutional table; private fair-use research does not authorize public/commercial release or third-party imagery.
- [Krsnaa annual-report index](https://krsnaadiagnostics.com/2026-annual-report/) and [terms](https://krsnaadiagnostics.com/terms-conditions/): written consent dependency for raw, excerpt and row-level sharing. Annual totals, reporting hubs, planned expansion and actual campus commissioning are different quantities.
- [Chandigarh commissioning notice](https://chdpr.gov.in/press/1944): historical named-host MRI notice; preserve the displayed publication/event chronology conflict. Reuse clearance and current availability are unresolved.

Punjab/Maharashtra service annexures and the failed NSE filing acquisition remain with Vincent's Windows collector. K receives permitted editions and source locators; Vincent reviews physical-campus identity and permissions; D reconciles the frozen national service ledger. Fixture checks, live warehouse readback and submission status are separate receipts on #166 and #160.
