# ACQ-D04 handoff · national-level Rajasthan NQAS register

Owner: Developer D. Review and integration: Vincent Zhu (`vzhu08`) through [task #39](https://github.com/vzhu08/databricks-datathon/issues/39) and [handoff #40](https://github.com/vzhu08/databricks-datathon/issues/40).

Branch: `codex/acq-d-national-register`, started from `8e8320a`. Tested implementation: `6dd333c45bdfabf11820d7876f17e506161aad24`; the following handoff commit is documentation only. The remote ownership board was reread at `33ab2f8` before handoff. Changes are confined to `research/certification/`, `tests/research/certification/` and this file. The integration lead retains board and merge ownership.

## Result and limits

The complete observed Rajasthan All-status pagination contains **585 occurrences and 585 distinct displayed name/status/end payloads**, matching its stable advertised total. This is coverage of the retrieved register, not a count of current certifications or verified campuses. There are 413 printed `Certified` and 172 printed `Conditionality` records. They remain separate from D03's 23 older full/partial episodes, within the same `nhsrc_nqas` family.

All rows are held out of candidate generation, matching features, threshold selection and candidate adjudication until predictions are frozen. No campus matches, base links, service-capability claims or NABH claims were created. Missing start dates and explicit department scope remain null; a future validity end does not establish current certification.

## Actual public capture

Sources: [national-level register](https://qps.nhsrcindia.org/quality-certification/national-level-certificate), [Rajasthan filter](https://qps.nhsrcindia.org/quality-certification/national-level-certificate?field_state_target_id=38&field_certified_value=All), [map report](https://qps.nhsrcindia.org/nqas-map-report), [NHSRC copyright policy](https://nhsrcindia.org/copyright-policy), and [terms](https://nhsrcindia.org/terms-and-conditions).

The observed GET form uses Rajasthan value `38`. Actual next links use comma-prefixed page values such as `,1`; the collector follows those links and verifies controls, caption and headers on every response. The four columns are serial, facility name, status and validity end. Serial is a presentation counter, not a stable facility ID.

Capture: **2026-11-21T20:24:47.673035Z–20:25:37.977323Z**. Seventeen content-addressed raw HTML files total 2,069,148 bytes: landing, copyright, terms, map, six All pages, five Certified pages and two Conditionality pages. All three views terminated at no-next-link; no capture/network blockers occurred. The source's update label is **30-09-2026**, separately retained from retrieval time, publication date and validity dates. Publication dates remain unknown.

| View | Pages | Advertised total on every page | Parsed occurrences | Distinct payloads |
| --- | ---: | ---: | ---: | ---: |
| All | 6 | 585 | 585 | 585 |
| Certified | 5 | 413 | 413 | 412 |
| Conditionality | 2 | 172 | 172 | 172 |

Exact primary duplicates: **0**. Normalized name groups: **583**, including **two repeated name groups with four differing record variants**. These are review groups only: zero verified campuses and zero verified renewal links. Payload identity excludes the presentation serial; every original occurrence and locator survives in private artifacts.

| Printed status | Certainly expired end | End certainly in future | Ambiguous across cutoff | Total |
| --- | ---: | ---: | ---: | ---: |
| Certified | 135 | 271 | 7 | 413 |
| Conditionality | 159 | 9 | 4 | 172 |
| Total | 294 | 280 | 11 | 585 |

Assessment cutoff: **2026-11-21**. There are **332 exact** and **253 ambiguous** end-date parses, with zero missing or invalid ends and zero ends exactly on the cutoff. Day/month alternatives are preserved rather than guessed. Every row lacks a start date, source NIN, district, facility category and explicit department scope. These fields are not inferred from names.

## Persistent source discrepancy and bounded audit

The Certified presentation repeats one name/status/end payload at its page boundary: zero-based page 1, tbody row 100, serial 200, and page 2, tbody row 1, serial 201. It omits a different payload present in All page 2, tbody row 3, serial 203. `discrepancies.json` retains both payload IDs and all affected original locators locally. Re-fetching the three implicated pages at approximately 20:27:34–20:27:38Z returned **identical raw bytes**. The discrepancy is persistent across these observations; its underlying cause is unproven. The All capture was preserved without repair.

The deterministic 20-row challenge sample round-robins strata of status, cutoff classification, date ambiguity and repeated name labels. It includes 12 Certified / 8 Conditionality records and 7 expired / 9 future-end / 4 cutoff-ambiguous records. **19 comparisons agree on displayed fields; one remains unresolved because the payload is absent from its status-filtered view.** Sample-ID SHA-256: `1d3e89dc49fb21c2814cd05032355559ae751a001eaf55f531788261d20d7699`.

This is an automated documentary extraction check against separately acquired original presentations from one programme family. It is not independent corroboration, a blinded human review or a population accuracy estimate. The unresolved row is included, not excluded to improve the result.

## Map comparison

The map's Rajasthan row is tbody row 29. It reports 6 DH, 4 SDH, 35 CHC, 278 AAM-PHC, 88 AAM-UPHC and 403 AAM-SHC: **814 total**, or **229 more than the observed register rows**. Its update label also reads 30-09-2026. The map presents facility-category counts; it does not state conditionality inclusion, deduplication or expiry rules, or expose campus identifiers for this comparison. The shared update label does not reconcile those definitions. The difference remains unresolved, with no invented campuses or inferred additions.

## V1 projection and explicit ledger

The actual derived batch passes the existing D validator with zero errors and an explicitly empty original base:

| Table | Rows |
| --- | ---: |
| source_snapshots | 6 |
| external_facilities | 585 |
| facility_matches | 0 |
| facility_evidence | 294 |
| review_queue | 585 |

Evidence comprises **178 expired** and **116 historical** records. The 135 Certified records support their printed historical listings; 159 Conditionality records use inconclusive polarity. **291 future-end/cutoff-ambiguous intervals with no start withhold v1 evidence**, because neither `dated` nor `undated` safely represents them. All 585 records remain in the typed ledger and have open held-out reviews. The empty base is solely for unlinked source-batch validation, never a substitute for the original Marketplace population.

## Private artifacts and reproduction

Authoritative ignored local directory:

```text
/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-d/data/local/certification/acq-d04-20261121/
```

This is a local handoff path, not a recipient-download or Databricks publication claim. `national_capture.json` maps every URL, retrieval timestamp, byte count and raw hash to its local artifact. `national_recheck.json` records the later discrepancy observations. `national_run_manifest.json` hashes both manifests and eight derived outputs. `validation.json` is the separately saved D CLI result. Raw bytes, real facility rows and excerpts remain outside Git; this handoff contains aggregate counts and digests only. NHSRC attribution and its third-party exception are preserved; no blanket open-data license is inferred.

| File | SHA-256 |
| --- | --- |
| national_run_manifest.json | `282c749e39e0be450877483b090276d3c71c603e46eb23d53dfd9572710395ba` |
| national_capture.json | `109f121323fd1e192d974abd6ac4e659223c066ae0f2df94a4e483d149883d6e` |
| national_recheck.json | `c6723b353e7ac370ad8eaca59728058be9099afc74c0d6734c044af2e5cd74b0` |
| batch.json | `67c1d87e9977b3409295f541fd0e1b30b9bc2d1f466007b6f54673eeff30456e` |
| ledger.json | `b53d63deae8933e6d4e60b5ccc6aa7e50d98078a61ed11d2e79bf3708232ebc6` |
| report.json | `66f31589b71863300357eecd96c680268e9c60f028dec9799574beed2432a106` |
| audit.json | `e9a063a5dbb3807b2cc978a7f86f32c112b99ebb466485de5b998ef8223a29e5` |
| discrepancies.json | `e95bb73112cf634e914df84ef854157e7f235cdaf18203ae2f1d72fb03081f12` |
| occurrences.json | `9eda9cfb5fe1041087746e50beb712b931d2b345dceb440487e65bd12cf4dd8b` |
| unresolved_groups.json | `f514b2171fafb37f4625f48fca8c44a035a6e4fa2681c7d46d4a2081f4406578` |
| empty_base.json | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| validation.json | `a1a4837dfb05fb92b487c36fb0b4a6ee2e43baae00c3173aea49e7a385c86e03` |

Primary page raw hashes (zero-based); snapshot IDs and retrieval timestamps are in `batch.json` and the capture manifest:

| Page | Raw SHA-256 |
| --- | --- |
| 0 | `c226ca3908a636282924d7829807a91b00581170bbb6a156d8f12afe01139a3f` |
| 1 | `466c28c18541e7e35d08ac6fba66a5b34382de4b9899833154957e718b2eb07f` |
| 2 | `f1baeaee3e65c7848375a5a2a96ced84d860d0d1e575d4ed626c93bcbcf167a8` |
| 3 | `e6ef86de810b4a2f8fc4f2568a7622981659dbe146d4c727edb124c1e9e36e91` |
| 4 | `7a1bd79675e49cb422a0268a608d0e0f23608f0bbcd3aa0b859975cf71e508a1` |
| 5 | `39232a53f674ff84c9554ba6e77b0e892be7227e8e8267fcc8668b4123d86137` |

The actual run used `national_capture.capture` followed by the CLI `recheck` and `finalize` commands. The CLI also combines these steps as `acquire` for a **new** destination; see [NATIONAL.md](../../research/certification/NATIONAL.md). Existing captures and finalized outputs refuse overwrite. Run these verification commands from the Developer D clone:

```sh
research/certification/.venv/bin/python -m unittest discover -s tests/research/certification -v
research/certification/.venv/bin/python -m unittest discover -s tests/databricks/enrichment -q
research/certification/.venv/bin/python databricks/enrichment/validate_batch.py \
  --batch data/local/certification/acq-d04-20261121/batch.json \
  --base data/local/certification/acq-d04-20261121/empty_base.json --as-of 2026-11-21
research/certification/.venv/bin/python -m research.certification.national_run replay \
  --run-dir data/local/certification/acq-d04-20261121
research/certification/.venv/bin/python -m research.certification.run replay \
  --run-dir data/local/certification/acq-d03-final-20261121
```

Fixture checks: **61 certification tests pass** (26 national, 35 preserved D03) and **72 enrichment tests pass**. Tests use synthetic facilities and cover filter/pager drift, partial acquisition, changed totals, repeats, temporal uncertainty, source discrepancies, raw corruption, no-overwrite behavior and validator compatibility. Compilation and `git diff --check` also passed.

Public-source checks: actual v1 validation passes; D04 replays all **eight derived files byte-identically with zero network requests**. D03 replays its **seven original files byte-identically**, with unchanged run-manifest hash `5269d0f02bfd27b368b492440cc9cdf1883e2c4492d571bc1d0557b28310c22c`. The D04 source discrepancy and map difference remain explicit limitations.

Artifact URIs are absolute. Moving the run to another machine or an approved Volume requires deliberate URI republication and a new manifest; replay currently requires the recorded original location. Recipient download/readback has not been performed.

Live Databricks checks: **not run**. Original-base validation and publication remain dependent on the authorized original-data access work in [#36](https://github.com/vzhu08/databricks-datathon/issues/36). Submission: **not performed**. Vincent should review the scoped PR, preserve these limits in readiness reporting, and decide any further source investigation or private publication work.
