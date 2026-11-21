# ACQ-A03 · Matching delivery and bounded institutional reference

Developer A / `@oliverchennn`, session `01a1ff42-3d8a-7e90-9750-5a4509a378ac`, branch `codex/acq-a-matching-handoff`, task [#30](https://github.com/vzhu08/databricks-datathon/issues/30), consumer [#5](https://github.com/vzhu08/databricks-datathon/issues/5). This work remains in the isolated Developer A clone. The final PR/head and test results are recorded in both issues. The branch started at main `a82d8c1`; the remote board was reread at `df28bfbc1c2ca496ea8e475a5c9addac20da0882`, which names Vincent as integration lead and records the ADIP fallback scope. Scope: acquisition code/tests and this handoff only.

## Delivery result

The three accepted batches and a provenance-backed district sidecar are available in the user's Databricks workspace at:

```text
/Volumes/workspace/datathon_acquisition/matching_inputs/acq-a03-7bcf4d94/
/Volumes/workspace/datathon_acquisition/matching_inputs/archives/matching-handoff-v1.zip
```

The user explicitly authorized creating this Volume and using their account. Databricks blocked console automation; the official CLI v1.27.0, verified against its vendor digest, authenticated through normal browser OAuth. The managed schema/Volume were created under the existing `workspace` catalog. All seven uploaded files and the ZIP were downloaded and matched their local SHA-256 values. The three user-named teammates have verified catalog/schema use and Volume read grants. No teammate login was impersonated, and no source table was modified.

The preliminary Drive folder remains empty and unshared because the user changed delivery to Databricks before any upload or sharing. No GPU or compute job was started. The [challenge brief](https://docs.google.com/document/d/e/2PACX-1vQxhDNQmgZhPgjG0M6LCb_UXNV8CJryqBNQQuqWfIg_dm40ZU1AYAXzZKViC6haFoCmLNiRVfUSBMjf/pub) requires Free Edition; no separate GPU allotment was found in the brief or event email inspected. See [Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations).

| Accepted rows | HOT/OSM | NHP mirror | Total |
| --- | ---: | ---: | ---: |
| National | 136,004 | 10,843 | 146,847 |
| National with district | 134,712 | 10,842 | 145,554 |
| National district unknown | 1,292 | 1 | 1,293 |
| Explicit Rajasthan / with district | 8,191 / 8,191 | 0 / 0 | 8,191 / 8,191 |
| Additional review / with district | 12,102 / 12,102 | 1,605 / 1,605 | 13,707 / 13,707 |

District codes are populated for 134,712 OSM and 10,539 NHP national rows; all 8,191 explicit rows; and 12,102 OSM plus 1,552 NHP additional rows. The sidecar has one row for each accepted national external ID. Exact raw duplicate removal and variant identity from A01 are preserved.

OSM raw features expose `adm2_name`/`adm2_pcode`; NHP exposes `District`/`District_ID`. No explicitly institutional switchboard field was observed. The raw NHP feature counts include 688 generic Telephone values, 83 mobile values, 3 nodal-person records, 3 nodal telephone values, 2 nodal emails, 16 ambulance contacts and 5 blood-bank contacts. None of those values is copied into the sidecar or packet. Raw snapshots are excluded from transfer. District labels are source observations, not verified current districts. NHP still supplies zero explicit Rajasthan candidates; the broad additional rectangle includes neighboring states.

## Hashes and local artifacts

Local root: `/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-a/data/local/acquisition/`.

| Artifact | SHA-256 |
| --- | --- |
| `matching-handoff-v1/national.json` | `4b5900bad2a57a179d03a6eab88f283db4f44d62a7a13b57ea77c6d445e951aa` |
| `matching-handoff-v1/explicit.json` | `de9f6d9ebd163680af00ba1482cc6b868f57a46e2091be3c876e1a4f08c15c31` |
| `matching-handoff-v1/additional_review.json` | `a1e43991463114c4a3dd55d7e374af9c4413cea2114299fbd129c1be27e5228b` |
| `matching-handoff-v1/districts.json` | `00c69c0404a9d71e11b4752ecb440fedbef508dc510f6155359e9c6ebc63fe32` |
| `matching-handoff-v1/manifest.json` | `7bcf4d94cbd22c2a6bdb624c576364680f029b0b183735718299d4798848cd78` |
| `matching-handoff-v1.zip` (29,150,782 bytes) | `8d4931d42a0aab9b1e39964695729b68e1ab9c4bc4a59c8032242c5efad1cfce` |
| `adip/source/panel.pdf` (364,550 bytes) | `f0ab908cc411707c3d5770c52ee10051ebe6a8f99f883196bc1cf3e9cb4580e8` |
| `adip/reference-v1/batch.json` | `0272266cb4c066f91d03f1d0eb860e8622e954a0900888f308f80247b5446b35` |
| `adip/reference-v1/manifest.json` | `3cdfe2e7f29382f631af95c3eb3f60a74d5ba1b8d5517d6b1232b6d31bd37253` |
| `adip/audit.json` | `74da723d610baa823f67011198b957ff9e4178914409797ab0e61f651833ba9e` |
| `adip/exact-name-overlap.json` | `25d44375458a23bc15d1aece22a2fb15abcb49d0e3af87916947dd51297efa4f` |

The source IDs/raw hashes are unchanged: `hot_osm_health:5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3` and `nhp_hospitals_mirror:058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47`. Full attribution, licenses, first retrieval timestamps and historical raw URIs remain in all accepted envelopes. `databricks-upload-receipt.json` records later physical delivery without rewriting immutable packet metadata. [Copy/replay instructions](../../research/acquisition/MATCHING_HANDOFF.md).

## ADIP fallback and original DHIS blocker

The integration lead supplied an [official ADIP hospital-panel PDF](https://cdnbbsr.s3waas.gov.in/s3e58aea67b01fa747687f038dfde066f6/uploads/2023/12/202406281743840120.pdf). Its bytes matched the supplied hash before copying into ignored local storage. The bounded page-16 extraction yields six Rajasthan institutional rows, serials 146–151, one source snapshot, six open campus reviews, zero matches and zero service evidence. **All 6/6 rows were visually checked** against the original rendering; no institutional-cell wording was corrected. Original name/address boundaries are retained in an audit with cell hashes and split offsets. One row's college/group/hospital wording remains ambiguous. Printed district is unavailable for all six; it is not inferred from the address. An exact normalized-name comparison against 8,191 explicit OSM candidates finds one candidate pair for one reference row; all six campus decisions remain unresolved. The other five are unmatched by that narrow equality rule, not demonstrated absent from OSM.

The [listing page](https://depwd.gov.in/en/document-category/cochlear-implant/) dates the listing December 5, 2023. The PDF issue/as-of date is unverified; contract publication date stays null. The initial remote download time is unknown; `2026-11-21T19:08:50.151135Z` is the observed local-copy time. The [copyright policy](https://depwd.gov.in/en/copyright-policy/) requires reproduction permission, which is unconfirmed. This reference stays in local research storage and is excluded from the shared Volume/ZIP. It is not DHIS, held-out ESI evidence, or proof of dialysis, trauma, cochlear surgery availability or present care capacity.

The [DHIS letter](https://rajswasthya.rajasthan.gov.in/admin/upload/letter/2025/07/96%20Dt.09.06.2025%20Letter%20to%20CMHO%20for%20DHIS%20%281%29.pdf) was not acquired: three 45-second direct attempts and a separate 10-second IPv4 connection attempt yielded HTTP 000 / zero bytes; ordinary browser navigation timed out. The web fetcher recognized a 29-page cached document whose searchable text begins on PDF page 10. Screenshot requests did not expose readable annexures. Thus no DHIS hash, annexure parser, per-annexure count, district disagreement finding, status milestone, row audit or overlap is asserted. **DHIS manual audit: 0 rows, denominator unknown.** A readable original PDF is still required; the fallback does not complete that source's acceptance criteria.

## Verification and remaining scope

**Fixture checks:** `research/acquisition/.venv/bin/python -m unittest discover -s tests/research/acquisition -p 'test_*.py' -q` passed **61 tests**, including 12 portable-transfer and 6 bounded-PDF cases. Cases cover relocation/ZIP byte stability, accepted hashes/counts, corrupted source/output rejection, first raw locator/duplicate variants, contact exclusion, missing-state refusal, long names, repeated headings, changed layouts, stale or incomplete audit bindings and unconfirmed name candidates.

**Public-source processing:** the packet builder replayed both accepted raw snapshots, confirmed the national union and original regional output hashes, and produced the district coverage above. The archive was independently streamed and checked against its seven-file manifest. Repeating the ADIP extraction at the existing destination verified identical artifacts. D's local validator accepted the national plus both regional envelopes: 2 snapshots, 146,847 deduplicated external rows, 13,879 reviews, 0 matches/evidence, empty base. It also accepted the separate ADIP batch: 1 snapshot, 6 external, 6 reviews, 0 matches/evidence, empty base. These are source-compatibility checks, not original-facility coverage checks.

**Live Databricks:** managed storage creation, eight uploaded artifacts, full download/hash readback and three teammates' read grants are verified. No Marketplace original rows were exported, no Delta tables published and no scoring/app behavior changed. C/D still own matching and publication against authorized base IDs.

**Submission:** not attempted. DHIS source acquisition and ADIP redistribution permission remain open. No board/shared-contract edits, merge or deployment performed. No real source rows, PDF, credentials, contact details or local dependency directories are tracked in Git.
