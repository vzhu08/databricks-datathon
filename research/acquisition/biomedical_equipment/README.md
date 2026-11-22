# NHSRC biomedical equipment collection

Developer I owns collection and replay for [#110](https://github.com/vzhu08/databricks-datathon/issues/110). This package captures the full public NHSRC equipment catalogue and indexes historical equipment records. It does not emit confirmed campus matches or service decisions. Vincent owns campus linkage and the Databricks writer handoff; D owns reconciliation on #163. Oliver owns integration and release.

The 2026-11-22 catalogue has 94 numbered entries under 16 state/UT headings, 88 unique URLs and 87 byte editions. All numbered entries are retained. Six repeated links and one byte-identical pair of Kerala PDF URLs do not count as independent evidence. Archives are recursively enumerated without executing their contents. The programme's national headline totals are not an export denominator.

## Replay the cleared handoff

Use Python 3.10+ with the package-local requirements. Keep every output under ignored `data/local/` or an authorized private Volume. No source workbooks, document excerpts or facility rows belong in Git.

```sh
python -m pip install -r research/acquisition/biomedical_equipment/requirements.txt
python -m research.acquisition.biomedical_equipment.handoff replay \
  --receipt research/acquisition/biomedical_equipment/receipts/2026-11-22-catalogue.json \
  --root data/local/new-sources/biomedical_equipment/permitted
python -m research.acquisition.biomedical_equipment.extract \
  --root data/local/new-sources/biomedical_equipment/permitted
python -m research.acquisition.biomedical_equipment.observations \
  --root data/local/new-sources/biomedical_equipment/permitted
python -m unittest discover -s tests/research/acquisition/biomedical_equipment -v
```

The receipt contains public URLs, SHA-256, sizes, retrieval dates, file-level sharing decisions and aggregate counts. It contains no equipment rows. Replay fetches **82 permitted byte editions** and excludes **five held editions**. A changed publisher asset fails the hash check rather than replacing the pinned edition. Existing matching blobs are verified and reused. The catalogue still records held entries as gaps.

The complete collection, including sources held locally for rights review, was obtained with:

```sh
python -m research.acquisition.biomedical_equipment.capture index --root PRIVATE_ROOT
python -m research.acquisition.biomedical_equipment.capture collect --root PRIVATE_ROOT
python -m research.acquisition.biomedical_equipment.extract --root PRIVATE_ROOT
python -m research.acquisition.biomedical_equipment.observations --root PRIVATE_ROOT
python -m research.acquisition.biomedical_equipment.dashboards --root PRIVATE_ROOT
```

`capture collect` stops if the pinned five-page, 94-entry pagination changes. Review a new catalogue before changing that guard. Acquisition attempts retain transport status, redirect destination, byte length and digest. Content-addressed source bytes are immutable working copies. These commands do not upload anything.

## What the outputs mean

| Private output | Grain and limits |
| --- | --- |
| `catalogue.json`, `downloads.json` | Every numbered entry and every attempted URL; failures remain visible. |
| `file-occurrences.json`, `editions.json` | Catalogue/archive-member occurrence versus byte edition, source parts, notices, date cues and extraction errors. |
| `extracted/<sha>.jsonl.gz` | Original nonempty physical worksheet rows, PDF text lines or DOCX paragraphs with exact locators. Hidden sheets, sparse coordinates, merged-range metadata, typed dates, zero values and cached/formula distinctions survive. |
| `mentions.jsonl` | Every regex hit and character offset for eight equipment categories. Includes negated, planned, summary and header mentions. A hit is not a device or service count. |
| `equipment-observations.jsonl.gz` | One explicit equipment-name row under a recognized header. Printed facility, serial, quantity, condition and date fields remain separate. Missing and merged cells are not filled down. |
| `sheet-dispositions.json` | Every workbook/HTML table part, original nonempty row count, explicit equipment-row count, or raw-only layout review. |
| `duplicate-serial-groups.json` | Repeated non-placeholder serial strings within/across editions. These are review leads, not proof of device identity. |
| `dashboard-register.json` | Every BEMMP index row, published operator, landing response, redirects and visible terms/export links. No login, hidden endpoint or export is used. |
| `jurisdiction-coverage.json` | All 36 jurisdictions, catalogue/index presence and explicit unmeasured national linkage. The joint J&K+Ladakh and separate Ladakh entries remain distinct. |

The XLSX reader follows physical XML rows, including cells outside inaccurate worksheet dimensions. It does not expand formatted blank ranges or calculate formulas. XLS uses cached BIFF values. OLE/BIFF content served under `.xlsx` and HTML served under `.xls` are detected. HTML vertical spans reserve their columns on later rows without filling down names or quantities. Mixed horizontal/vertical spans retain every reserved column; malformed overlapping spans require manual review. The HTML path does not require xlrd; BIFF extraction does. PDF extraction includes rotated text. PDF line order and DOCX paragraph order are not asserted to be table row order.

The tested extraction runtime used Python 3.12, lxml 6.1.1, openpyxl 3.1.5, xlrd 2.0.2 and pypdf 6.21.4. The optional PDF renderer used pypdfium2 5.13.0. Parser 1.0.1 adds the HTML vertical-span correction; replay receipts identify whether a pinned source actually contains those spans.

Each equipment observation keeps an immutable edition/record key, source locator, original equipment name and modality hits. A row-level facility key is produced only when one explicit facility column supplies a nonblank value. It is scoped to the edition and printed district/name, not a globally approved campus. Facility names in headings or sheet tabs need review. District/group summaries, blank continuation labels and unrecognized layouts stay in the raw ledger and review index.

Quantity zero remains zero; missing remains null. Working/nonworking count columns are separate. Symbolic condition codes are not interpreted without a source legend. Installation, supply, warranty, breakdown and form dates are preserved as printed; none automatically dates condition. Retrieval, filename years and upload-directory dates never become observation dates. No stock, condition, planned replacement, procedure, hours or staffing statement establishes current patient availability or trauma capability.

All sources share the NHSRC equipment-mapping programme lineage until upstream independence is reviewed. Repeated records and contradictions are retained, including source mirrors and repeated device serials. Raw mentions, explicit source rows, physical devices, approved campuses and campus-service pairs are different measures.

## OCR and visual checks

Four scanned pages in one hospital PDF have no text layer. On macOS, the optional helper records OCR text, page, normalized bounding box, confidence, render digest and engine/platform. Its output stays separate and never feeds the equipment parser or service producer.

```sh
swiftc -module-cache-path /tmp/biomedical-swift-cache \
  research/acquisition/biomedical_equipment/vision_ocr.swift -o PRIVATE_ROOT/vision-ocr
python -m research.acquisition.biomedical_equipment.ocr \
  --root PRIVATE_ROOT --binary PRIVATE_ROOT/vision-ocr
```

Install `pypdfium2` for this optional step. The engine requires access to macOS Vision; a sandboxed call may fail. Windows/Linux collectors can retain the original PDF and record this OCR dependency or use a separately documented local OCR engine. OCR is not byte-identical across engines. Original documents are never modified. Rendered PDF covers, embedded illustrations and the two parliamentary fallback pages were reviewed locally.

## Rights and durable storage

[NHSRC's policy](https://nhsrcindia.org/copyright-policy) permits accurate attributed reproduction except identified third-party copyright. Keep attribution and the original named state/contractor lineage. Two PDFs marked Confidential and three DOCX reports with unresolved third-party maps/illustrations are held from the raw shared package. Their permitted metadata is retained in the receipt. Manufacturer labels containing the word “Confidential” are not document restrictions; corrupt text hits are flagged for quality review rather than treated as licenses.

The two additional Sansad documents are pointers pending reproduction permission under [its portal policy](https://sansad.in/poi/privacyPolicy): [2021 question 2329](https://sansad.in/getFile/annex/253/AU2329.pdf?source=pqars) and [2026 committee 171](https://sansad.in/getFile/rsnew/Committee_site/Committee_File/ReportFile/14/212/171_2026_3_18.pdf?source=rajyasabha#page=51). The 2021 institute stock table and 2026 institute-level hours, replacement and installation claims have different scopes. They cannot support a stock trend, a resolved campus, or a present staffed slot.

The public dashboard index is an access register, not permission for bulk download. [J&K's manual](https://jk.bmmp.in/help_jk.pdf), page 2, requires credentials for Excel/service-report downloads. The official qualification route is [NHSRC contact](https://nhsrcindia.org/contact-us) and [Healthcare Technology](https://www.nhsrcindia.org/hc-technology). Request the dated facility/equipment export, publisher and state-owner authorization, four-person private matching/storage rights, and definitions of condition/observation dates. A contact route grants no permission. No outreach is sent by this package.

The raw publisher URLs plus pinned hashes provide Vincent's authorized replay route. Stage permitted raw assets, extracts, derived rows and summaries under an immutable edition in `/Volumes/workspace/default/datathon_vf_research_intake/`; read back hashes, sizes, counts and team access. Keep the receipt open on #110 and #160 until that verification arrives. The checked-in receipt does **not** claim a live upload.

The national comparison remains with Vincent/D and the frozen #147 baseline: **10,088 occurrences, 10,077 upstream IDs, 11 duplicate pairs and 30,264 service decisions**. No VF base was available in this collector checkout. Matched occurrences, reviewed campus-service pairs, added dated evidence, independent origins and service transitions are null until their full-cohort comparison. Missing geography and both duplicate occurrences must remain in that run.
