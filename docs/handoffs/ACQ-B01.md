# ACQ-B01 · Rajasthan trauma evidence handoff

Vincent Zhu (`vzhu08`), Developer B, froze this contract v1.0.0 release on November 21, 2026. The package gives Andrew source-local campus identities to investigate and Oliver a validated five-table batch. It contains 74 external facility records drawn from nine snapshots. The number of distinct physical campuses is unknown. All 65 released trauma observations have inconclusive capability polarity. The app can describe a dated or historical source finding with its original locator. Current trauma level, live acceptance and statewide coverage remain unknown. [Task #4](https://github.com/vzhu08/databricks-datathon/issues/4) · [PR #19](https://github.com/vzhu08/databricks-datathon/pull/19)

## Collection and interpretation

| Source | What the team established | What remains open |
| --- | --- | --- |
| Rajasthan Road Safety Cell | All 57 directory listings parsed across 32 source-spelled district labels. Designation comes from the heading. Two captures agree on the rows. | Effective date, formal level and live service or ambulance availability are unknown. The publisher's HTTPS hostname validation failed. B1 and B5 cross-checked the public HTTP table. |
| RGHS and official campus records | Both government-hospital PDF endpoints timed out. Three original procurement records supply three possible administrative identities for one directory entry in Ajmer. B2 delivered the PDF parser, acquisition log and crosswalk for all 57 entries. | One ambiguous entry, 56 unmatched. Original RGHS bytes and evidence sufficient to resolve the campus are outstanding. |
| Ministry trauma programme | All 10 Rajasthan rows in the relevant annexure were reconciled visually. Four report level II, six report level III and ten contain a historical functionality entry. The legacy archive and ministry download match byte for byte. | Exact facility as-of dates are unknown. A later hosting date supplies no update to the historical observations. |
| Accreditation and hospital materials | B4 reviewed 20 candidates across 13 districts, including 19 directory entries and one private comparison. The selection covered six campus conflicts, six district/ownership cases and eight remaining places. One campus-specific accreditation scope documents general emergency medicine. | For 19 candidates the review located no matching scope. A hospital's self-published post-trauma resuscitation statement needs human review. Selection preceded live VF overlap and cannot estimate prevalence. |

A's NHP mirror and underlying NHP dataset have one lineage. B did not ingest either. The two ministry copies share an upstream report, the three procurement records share a publishing family, and NABH directory and issuer material share a source. Pages from one hospital share its self-published account. Documentary audit establishes what those sources say. It provides no independent clinical verification. [A's national collection](https://github.com/vzhu08/databricks-datathon/issues/3) · [B5's source review](../../research/trauma/handoffs/B5.md)

## Audit, release and coverage

The claim ledger preserves 86 original claims, comprising 79 service, six identity and one accreditation claim. Of the 86, 65 are undated, 20 historical and one dated. B5 reopened public originals and deliberately sampled 29 service claims and the accreditation claim, covering 30 of 80 eligible claims. The sample includes conflicting campuses and documentary controls. The pass rate does not estimate Rajasthan-wide accuracy.

| Producer | Eligible | Audited | Documentary pass | Uncertain after re-review |
| --- | ---: | ---: | ---: | ---: |
| B1 | 57 | 14 | 7 | 7 |
| B2 | 0 | 0 | 0 | 0 |
| B3 | 20 | 13 | 6 | 7 |
| B4 | 3 | 3 | 3 | 0 |

B5 recorded 27 preliminary failures where row excerpts relied on a separate heading for trauma context. B1 corrected designation polarity and versioned the affected IDs. B3 corrected the historical interpretation, retaining the original IDs and recording new payload hashes before the freeze. B2 removed inferred effective dates from its identity assertions. B5 re-reviewed all 27 revised sampled claims. Final results were 16 documentary passes, 14 uncertain campus attributions and zero failed. All 14 uncertain claims remain in the claim ledger and have open review items. The release contains the 16 passes plus 56 unsampled claims. Coverage identifies each pass explicitly.

D accepted nine snapshots, 74 external records, zero VF matches, 72 evidence rows and 132 open review items. The 72 comprise 58 undated, 13 historical and one dated. All 74 external rows lack latitude, and 68 lack PIN. D ran against an empty base, so a VF coverage rate cannot be calculated.

B1 directory rows by district, preserving source labels and spelling (57 total) — Ajmer 3, Alwar 2, Banswara 1, Baran 1, Barmer 1, Bharatpur 1, Bhilwnra 1, Bikaner 1, Bundi 2, Chittorgarh 1, Churu 3, Dausa 3, Dholpur 1, Dungarpur 1, Ganganagar 2, Hanumangarh 2, Jaipur 7, Jaisalmer 1, Jalore 1, Jhunjhunu 1, Jodhpur 2, Karauli 1, Kota 1, Nagaur 2, Pali 2, Pratapgarh 1, Rajsamand 3, Sawai Madhopur 1, Sikar 2, Sirohi 1, Tonk 2, Udaipur 3.

B4 lookup attempts by district (20 total) — Ajmer 3, Alwar 2, Banswara 1, Baran 1, Bharatpur 1, Bhilwara 1, Bikaner 1, Jaipur 3, Jhunjhunu 1, Jodhpur 1, Kota 1, Sikar 1, Udaipur 3. B2's alternative identity evidence concerns Ajmer. B3's annexure identifies the state and facilities but does not establish reliable district counts. The private lookup ledgers preserve these different denominators.

## Frozen source inventory

The raw digest identifies the exact original bytes supplied to the release. Each snapshot's contract ID, attribution, terms and retrieval metadata are in the private batch. B4 documents its namespaced IDs separately. [B4 inventory](../../research/trauma/handoffs/B4.md)

| Source key | Raw SHA-256 | External records | Original claims | Released claims |
| --- | --- | ---: | ---: | ---: |
| `rajasthan_sms_college_profile` | `5a6ba378bc3cb017c72795335ebd095e581d5bfeff2ad63cd1c6e7fcd0e798dc` | 1 | 1 | 1 |
| `jaipuria_citizen_charter` | `045cffec8b5f94efe516daee1ed2cc45f74f7b88434b5f94718799159ecefa99` | 1 | 1 | 1 |
| `nabh_directory` | `c315c98ec89295803954519b9ca300cb5e638258348171dc6add1d0ae958576a` | 1 | 1 | 1 |
| `geetanjali_emergency` | `4f84aa1b51395576ea3f800ee9db55285d9c4427354d55e563dbbeb46e2a00f1` | 1 | 1 | 1 |
| `mohfw_trauma_program` | `fb0deb83f24ee85612a10cdcb491a14b6d667e02874e8800f341d3ba33236586` | 10 | 20 | 13 |
| `rajasthan_jln_associated_group_tender` | `696d1bdd6512dc7b9b06820a8a0df2cf90445e0cc8083276d79b7940ed30ef14` | 1 | 2 | 2 |
| `rajasthan_jln_college_tender` | `2c74c54efff7f627061f24d46b935af67df791840173d67b33203e43404fd9af` | 1 | 1 | 1 |
| `rajasthan_jln_hospital_tender` | `c5c450dc706a90ab1dad4f6be63bf912d08dc5d74f2a61d8cf3ddea85276187d` | 1 | 2 | 2 |
| `rajasthan_trauma` | `52a07ca2abdac5e6e0bc0a27ca8a1db90e9252d51b2da1c8b5bda0c090076485` | 57 | 57 | 50 |

## Tested revisions and research handoffs

The four producers and the independent audit were integrated on `codex/acq-b-trauma-evidence`. The tested implementation is `e4d638661c426df1b8e1786d479b6d45a8f910bf`. Python 3.12 recursive discovery passed all 73 tests, including 11 lead release tests. Each linked handoff gives its acquisition methods, public sources, parsing checks and limitations.

| Handoff | Local research chat | Branch | Integrated head | Tests |
| --- | --- | --- | --- | ---: |
| [B1 · Rajasthan state trauma directory](../../research/trauma/handoffs/B1.md) | [01a1ff49-96a1-7593-ac19-b2e684cf6d3f](codex://threads/01a1ff49-96a1-7593-ac19-b2e684cf6d3f) | `codex/acq-b1-state` | `9141783c2867bdec8489f45defb304bf80ddb03f` | 13 |
| [B2 · RGHS campus identity crosswalk](../../research/trauma/handoffs/B2.md) | [01a1ff49-b3f6-7712-a963-bb8951817f26](codex://threads/01a1ff49-b3f6-7712-a963-bb8951817f26) | `codex/acq-b2-identity` | `0d94ad055af6cc52480b5d3478cf04b265ecfdcb` | 15 |
| [B3 · National trauma programme history](../../research/trauma/handoffs/B3.md) | [01a1ff49-ecd6-7da2-9890-c6d547aa02a6](codex://threads/01a1ff49-ecd6-7da2-9890-c6d547aa02a6) | `codex/acq-b3-national` | `4d379854dff56209229192183917801b97f73b81` | 10 |
| [B4 · Accreditation and hospital scope](../../research/trauma/handoffs/B4.md) | [01a1ff4a-0444-7dd0-8e42-d1ae9c1df961](codex://threads/01a1ff4a-0444-7dd0-8e42-d1ae9c1df961) | `codex/acq-b4-accreditation` | `ed6cca79a96866e302099de4c6a29f1c07cb014d` | 12 |
| [B5 · Independent trauma evidence audit](../../research/trauma/handoffs/B5.md) | [01a1ff4a-3c94-7232-91a8-eaa8b3abbd91](codex://threads/01a1ff4a-3c94-7232-91a8-eaa8b3abbd91) | `codex/acq-b5-audit` | `7a4393d828fce844feee71c7a88647211a8225c8` | 12 |

## Replay from the frozen files

The canonical local package is `data/local/trauma/acq-b01/lead/` under Vincent's primary project checkout. The integration checkout is `data/local/trauma/orchestration/integration/`. Set the two path variables below to the package and to a checkout containing D's validator at `85b570292b693b94b1aabd0e0aa1b00ed44732f3`. The sibling file `empty-base.json` contains `[]`. D's merged implementation is available through [PR #17](https://github.com/vzhu08/databricks-datathon/pull/17).

```powershell
# Run at the root of Vincent's integration checkout.
$package = (Resolve-Path '../../acq-b01/lead').Path
$validator = (Resolve-Path '../validator').Path
python -m pip install -r research/trauma/requirements.txt
python -m unittest discover -s tests/research/trauma -p 'test_*.py' -v
python -m research.trauma.pipeline --input-dir "$package/inputs" --output-dir "$package/release-01"
python "$validator/databricks/enrichment/validate_batch.py" --batch "$package/release-01/batch.json" --base ../empty-base.json --as-of 2026-11-21
```

The release replay verified the frozen output, and supplying the batch twice to D's validator produced identical counts with zero validation errors. The audit decisions, review queue, decision history, sample selection, source-dependence map and summary also reproduced byte for byte from the saved observations. To repeat that calculation, run the following commands in the integration checkout.

```powershell
$observations=Join-Path $package 'audit-replay/work'
$auditArgs=@('-m','research.trauma.audit','--out',"$package/audit-check")
foreach ($lane in 'B1','B2','B3','B4') { $auditArgs+=@('--batch',"$package/inputs/$lane/batch.json") }
$auditArgs+=@('--strata',"$observations/strata.json",'--observations',"$observations/observations.json",'--prior-history',"$observations/prior-history.json",'--lineage',"$observations/lineage.json")
foreach ($original in (Get-ChildItem -File "$package/audit-replay/originals")) { $auditArgs+=@('--artifact',$original.FullName) }
python @auditArgs
```

| Local artifact under the package | Purpose |
| --- | --- |
| `inputs/` | Four original envelopes, B5 decisions and queue, checksum-verified raw files and their portable path map |
| `audit-replay/` | Frozen audit strata, observations, pre-correction history, original sources and page renderings |
| `ledgers/` | Crosswalk, lookup outcomes, source-access logs and audit history. All 29 sidecars verified against `manifest.json`. |
| `release-01/claim_ledger.json` | All 86 claims and their audit status. SHA-256 `130f0b5d8cbef282f37fa6c5d0ff498a36b2fff895eb56dea2cf919b8ca082dc`. |
| `release-01/batch.json` | D ingestion envelope. SHA-256 `cde57eb095a426143d4dd32d005daa1432e7ec351b459531ccafedcf0684ab89`. |
| `release-01/coverage.json`, `source_review_ledger.json`, `sha256.json` | Denominators, original issues and the release file inventory. All four listed hashes were verified. |
| `d-validation.json` | D's local schema, reference and semantic validation report |

## Handoff to C and D

**Andrew (C)** can use the 74 source-local records for candidate generation. Review ambiguous campus alternatives with their source locators and use the B2/B4 ledgers when deciding identity. All links to VF remain open. Keep quarantined claims out of verified use. [C's task](https://github.com/vzhu08/databricks-datathon/issues/5)

**Oliver (D/integration)** can replay the local five-table envelope against the approved base once the workspace mapping and permitted destination are available. The Git branch carries source code, synthetic tests and aggregate results. The evidence package remains on Vincent's machine. Cross-machine transfer of source material requires an approved destination and applicable source permissions. Live Databricks verification, publication and Datathon submission are pending. [D's task](https://github.com/vzhu08/databricks-datathon/issues/6)
