# National trauma and burn programme observations · #164

This reader preserves dated programme evidence and compares it with every original VF occurrence. It does not adjudicate a campus or replace the reviewed service-status producer. A functional trauma unit, a sanctioned unit, a blood-centre licence and live clinical availability are separate observations.

## Verified editions and measured result

| Edition | Parsed mentions | Meaning |
| --- | ---: | --- |
| [Existing #65 programme freeze](https://github.com/vzhu08/databricks-datathon/issues/65#issuecomment-7069678017) | 196 | 105 construction-completed rows also say functional; 7 under construction, 4 not started, 80 supported. Publication date remains unknown. |
| [Lok Sabha UQ 982, July 25, 2025](https://sansad.in/getFile/loksabhaquestions/annex/185/AU982_6nsyH6.pdf?source=pqals) | 243 | 196 trauma rows: 168 functional, 28 non-functional. 47 burn rows: 31 functional, 16 non-functional. |
| [Rajya Sabha UQ 2048, March 10, 2026](https://sansad.in/getFile/annex/270/AU2048_OvVj2M.pdf?source=pqars) | 196 | Sanctions only; no facility-level operational status. |

The November 22 replay retains **635 mentions**, 258 distinct normalized label/resource keys across editions, and one common Ministry programme-return origin. These keys are not verified campuses. There are no duplicate label/resource mentions within an edition. All 196 July trauma names pair with the March names. Each newer list pairs with 181 names in the freeze; the 15 unmatched names require alias, wording or historical-geography review, not a claim of new facilities. Two paired functionality assertions differ. Because the freeze date is unknown, they are neither verified chronological transitions nor same-date conflicts.

The base is the previously verified version-0 export with SHA-256 `27e4a79de42ec56c76cc676ed45494a52497d179858bc50549a461434c45e9d8`. All **10,088 occurrences, 10,077 original IDs and 30,264 incremental service decisions** survive. The original row payloads remain unchanged. Exact compact-name/state comparison gives eight source-mention edges to four original occurrences, including two beyond the freeze's two candidate occurrences. None is a confirmed campus link. All three service decisions per occurrence remain unconfirmed in this incremental layer. Existing team adjudications are not rewritten.

The report uses the existing national matcher's original-label geography policy: 36 state/UT buckets (including zero-count buckets), 58 missing-label occurrences and 390 non-state-label occurrences. Source spelling cleanup is recorded separately; it does not rewrite the baseline. Missing names, ambiguous names, aliases and absent candidates do not imply missing services. Burn candidates remain separate from trauma decisions.

## Reading and replay

Use Python 3.10+; the actual run used Python 3.12.14 and pdfplumber 0.11.9. Install `requirements.txt` in a private environment. Run from the repository root.

```sh
python -m research.acquisition.trauma_support.packet acquire --sources PRIVATE/raw
python -m research.acquisition.trauma_support.packet build \
  --sources PRIVATE/raw \
  --base PRIVATE/prepared/base.json \
  --prepared-manifest PRIVATE/prepared/prepared_manifest.json \
  --as-of 2026-11-22 --output PRIVATE/release
python -m unittest discover -s tests/research/acquisition/trauma_support -v
```

Use existing verified bytes before acquiring. New publisher acquisition for the scout belongs to Vincent's Windows collectors under [#161](https://github.com/vzhu08/databricks-datathon/issues/161#issuecomment-7074538347). The acquisition command rejects changed bytes and creates UTC retrieval receipts; it never silently replaces an edition. Existing receipts belong beside their PDF as `FILE.pdf.receipt.json`. Changed editions need a reviewed parser/spec update.

The July reader was checked against complete PDF pages 7–17; the March reader against pages 2–7. July p.9 has a missing right border, recovered at the verified column edge in this hash-pinned edition. State cells carry across pages, including July row 182 remaining under Uttar Pradesh. Printed line breaks, spelling, negative status wording and locators survive in the private ledger. One misspelled negative burn status is explicitly handled. Unknown status text, lost serials, unexpected widths and changed source hashes fail closed. The existing #65 reader is reused, with its p.5 disagreements visually rechecked.

`published_date` is the parliamentary answer date. `reported_as_of` retains that reporting date; `effective_date` stays null because a separate facility-observation date is not supplied. The freeze's URL upload directory is not a publication date. Plan/level strings, construction stage, functional status, negation, source family and retrieval time remain separate. Units are programme facilities; no capacity, 24-hour operation, commissioning date, current inventory or trauma designation is inferred from another resource.

`local-only/` holds raw printed mentions, candidate links, all incremental decisions and paired-edition locators. `shareable/` holds only aggregate counts, edition provenance, curated source-access gaps and a manifest. Generic input JSON cannot be copied into the shareable packet. A label key removes case, whitespace and punctuation for candidate comparison; it is deliberately insufficient for clinical linkage.

## Rights, source gaps and delivery

[Sansad's policy](https://sansad.in/poi/privacyPolicy) requires permission to reproduce portal contents. Raw PDFs and printed-name extracts remain in local working storage pending Vincent's rights decision. The #65 raw-source restriction remains in force. The checked-in `handoff/` contains provenance and aggregate statistics only; no source rows, facility names, original VF IDs, contact values or credentials are included.

[source_gaps.json](source_gaps.json) records the selected-procedure HMIS catalogue's missing resource/API dependency, CDSCO's state-total-only edition, e-RaktKosh's unqualified bulk route, and the IndiaDigital NIHFW edition awaiting Vincent's Windows collector. The reported IndiaDigital count/date are marked unverified. No coverage gain is assigned to those gaps. The opened 2016 parliamentary answer, February 2026 training answer and DGHS programme page were qualification material, not additional parsed inventories; their local copies remain restricted and do not add origins or observations to this run.

Vincent is the named existing Volume writer for the permitted aggregate handoff. This Mac's CLI has no configured authentication profile; no upload or remote readback is claimed. The packet is concrete and available in this branch without needing to retrieve the restricted source text again. Its manifest SHA-256 is:

`1c447ad661af6cb3764971b7d7960d0226234ef1786114fdb4a64f089c636736`

Use this immutable destination:

`/Volumes/workspace/default/datathon_vf_research_intake/trauma-support-164-1c447ad661af6cb3764971b7d7960d0226234ef1786114fdb4a64f089c636736/`

From the writer's authenticated checkout, copy only the four `handoff/` files, then download into a fresh local directory and verify:

```sh
databricks fs cp research/acquisition/trauma_support/handoff/ \
  dbfs:/Volumes/workspace/default/datathon_vf_research_intake/trauma-support-164-1c447ad661af6cb3764971b7d7960d0226234ef1786114fdb4a64f089c636736/ --recursive
databricks fs cp \
  dbfs:/Volumes/workspace/default/datathon_vf_research_intake/trauma-support-164-1c447ad661af6cb3764971b7d7960d0226234ef1786114fdb4a64f089c636736/ \
  PRIVATE/fresh-readback/ --recursive
python -m research.acquisition.trauma_support.verify_packet PRIVATE/fresh-readback \
  1c447ad661af6cb3764971b7d7960d0226234ef1786114fdb4a64f089c636736
```

Do not overwrite a mismatched remote edition. Verify effective `USE_CATALOG`, `USE_SCHEMA` and `READ_VOLUME` access for Oliver, Vincent, Andrew and Ayush, and request D's independent readback. Post the path, digest, four-file verification and access result on #164/#160. Current verification levels: synthetic fixtures and full national local replay passed; live Databricks upload/readback pending; enrichment publication and submission not performed. Oliver owns PR disposition and release.
