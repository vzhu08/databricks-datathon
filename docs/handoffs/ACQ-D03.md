# ACQ-D03 · Rajasthan NQAS held-out reference

Owner: Developer D, Codex chat `01a1ff42-470d-7f20-a2e2-ed23665cc075`. [Task #32](https://github.com/vzhu08/databricks-datathon/issues/32). Branch `codex/acq-d-nqas-reference`. Implementation and tested code: `dc54cea44e54d38648ebdf3ab7ee9c922d9f3b10`; the following commit adds this handoff only. PR and final head are linked in the issue handoff. Contract `1.0.0`, parser `nqas-reference-1.0.0`. Remote board reread at `488c137` before handoff. The integration lead owns review, board updates and merge.

## Actual public-source result

The final run acquired the [QPS Rajasthan full/partial tables](https://qps.nhsrcindia.org/nqas-facility-list) from `2026-11-21T19:09:27.509127Z` through `19:09:38.209919Z`; alternate-table acquisition finished at `19:09:41.855298Z`. It followed both actual GET forms and every observed next link. Full: two pages, 20 rows. Partial: one page, 3 rows. Both end with no next link. No public export link was observed on the landing page.

The [certificate register](https://nqas.nhsrcindia.org/facilities/list) failed verified TLS with `tls_certificate_expired`. Its filters, pagination, exports, NIN/category fields and current coverage remain unobserved. No TLS bypass was used. This limits the result to the accessible QPS subset; it is not a claim of complete/current NQAS or Rajasthan facility coverage.

| Measure | Actual result and denominator |
| --- | --- |
| Source snapshots / external rows | 3 / 23 |
| Accreditation evidence / open reviews / matches | 23 / 23 / 0 |
| Full / partial rows | 20 / 3, out of 23 accessible rows |
| Districts represented | 13 printed district labels |
| NIN / dedicated category unavailable | 23 / 23 each |
| Coordinates / PIN unavailable | 23 / 23 each |
| Publication date unknown | 3 / 3 evidence snapshots |
| Ambiguous start / end dates | 11 / 13, out of 23 intervals |
| Expired under every supported date interpretation | 23 / 23 as of 2026-11-21 |
| V1 temporal classifications | 10 `expired`; 13 `historical` with ambiguous expiry retained in the ledger |
| V1 evidence withheld for temporal limitations | 0 / 23 in this capture; invalid or unresolved current intervals are tested separately |
| Repeated name/district groups / verified renewal or identifier links | 0 / 0; NINs are unavailable, so renewal coverage is unmeasured |
| Original base facilities supplied / preserved links | 0 / 0; original-population validation is unmeasured |

All evidence is the programme's dated documentary listing for the named facility and printed department scope. One family, `nhsrc_nqas`, with `shared_origin`; QPS and the certificate register are not independent sources. No NABH, clinical-capability or live-availability claims. The complete reference remains held out of matching-feature construction, threshold selection and adjudication until predictions are frozen. Do not import this batch into the ordinary candidate pipeline.

## Documentary check

The deterministic stratified challenge sample contains 20 of the 23 rows: 17 full, all 3 partial, 11 with an ambiguous date, and all 20 expired under every supported parse. No observed renewal or unexpired rows were available to sample. All **20/20** agree on all seven displayed fields between the standalone QPS table and the alternate combined QPS table, with both raw hashes and row locators recorded. Zero certificate-register comparisons completed because that endpoint was unavailable.

This is an automated documentary extraction check within one source family, not independent corroboration, blinded human review or a population accuracy estimate. The assessment labels must remain withheld for the independent pilot described in the validation plan. Original date strings, candidate parses, department text, district and null unexposed fields remain in `episodes.json`. The sample-ID hash is `9e7233b95dcd932d04c3aef9bbdaa65a44226e03dddf6a1485ffbf4e4b2c492e`.

## Artifacts and hashes

Authoritative final local directory, accessible on this machine:

```text
/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-d/data/local/certification/acq-d03-final-20261121
```

All raw HTML, parsed records, exact excerpts, dates and audit rows remain ignored. Earlier `inspection/`, `qps-capture-20261121/` and `acq-d03-20261121/` are development captures, not additional independent evidence or the final handoff. The final directory has eight content-addressed raw HTML files: three evidence pages, landing, two policy pages and two audit pages. Exact locators, UTC retrieval times, bytes and failures are in `capture.json` and `audit_capture.json`. Publication dates remain null. Snapshot ID is `nqas-qps:` followed by the corresponding raw hash.

| Evidence page | Raw SHA-256 | Retrieval UTC |
| --- | --- | --- |
| Full page 0 | `61c751db3c2a07fa4d6dad9d396f519a11f69e83c80e13be81a3586b849e7cb9` | 2026-11-21T19:09:34.741490Z |
| Full page 1 | `d7224eef9f37a8cf099afab4f1d9299dfb78e7ad756631f1abe8a5a607f8a6ac` | 2026-11-21T19:09:36.446099Z |
| Partial page 0 | `c44975f3f3974f607c211e4728417b7eaf58fc942854feb816bbd7db043b423f` | 2026-11-21T19:09:38.188405Z |

| Final artifact | File SHA-256 |
| --- | --- |
| `run_manifest.json` | `5269d0f02bfd27b368b492440cc9cdf1883e2c4492d571bc1d0557b28310c22c` |
| `batch.json` | `34d5f5badb2eb5058826acaa056082bff444e685283359ad237cbc2ce5186792` |
| `episodes.json` | `59c4402d96a06d84aaf841eed0753221dde129ed251c5b5230306b6a7bca146d` |
| `relations.json` | `87681d92d7b3b1456ca398c5d120cd3ff8fe1d992a724c70bcf477055e9fbb98` |
| `report.json` | `4f07bb69dd1fa07426acaca1ac571b9e910a97b1fa6a948030d8ebea4c3f2d1b` |
| `audit.json` | `74afa32c1ffed2b17e6f6d601474f1cbeb2a1ab5c2818846c30e02d311c2f58a` |
| `validation.json` | `b7948efca1d32f2191e6a2f120a42fbacccd95b153449b3e0145bc52bef050ed` |

The run manifest hashes the seven derived outputs plus both capture manifests. `validation.json` is the separately saved D CLI result. Replay verifies all referenced raw hashes and all seven derived artifacts byte-for-byte, retaining persisted retrieval times. It performs zero network requests. Absolute raw artifact URIs require the original location; transfer/republication to another path or an approved Volume must explicitly rebind URIs and issue a new manifest. No portable publication to another machine has been claimed.

The [NHSRC copyright policy](https://nhsrcindia.org/copyright-policy) permits accurate attributed reproduction of its own material, subject to the third-party exception. This is not a blanket open-data license. Policy and [terms](https://nhsrcindia.org/terms-and-conditions) snapshots are preserved locally; no source rows or excerpts are committed.

## Exact checks

Run from the developer-D clone, using the environment installed from `research/certification/requirements.txt`:

```sh
research/certification/.venv/bin/python -m unittest discover -s tests/research/certification -v
research/certification/.venv/bin/python -m unittest discover -s tests/databricks/enrichment -v
research/certification/.venv/bin/python -m research.certification.run acquire \
  --output-dir data/local/certification/acq-d03-final-20261121 --as-of 2026-11-21
research/certification/.venv/bin/python -m research.certification.run replay \
  --run-dir data/local/certification/acq-d03-final-20261121
research/certification/.venv/bin/python databricks/enrichment/validate_batch.py \
  --batch data/local/certification/acq-d03-final-20261121/batch.json \
  --base data/local/certification/acq-d03-final-20261121/empty_base.json --as-of 2026-11-21
```

The acquisition command was executed; it refuses overwrite if repeated. Use replay for this run or a fresh directory for new acquisition. Fixture checks: **35 certification tests and 72 existing enrichment tests pass**. The public batch passes schema and D cross-table validation with zero errors and an explicit empty base, keeping all evidence unlinked. Compile checks and `git diff --check` pass. The empty base is not a substitute for Marketplace rows.

Live Databricks: **not run or published for this task**. Real original-base coverage, campus matching and an independent blinded pilot remain unverified. Submission: **not performed**. Remaining source blockers are the certificate-register TLS failure, missing NIN/category/publication fields, ambiguous original dates and unobserved current/renewal coverage. The implementation and replayable accessible subset are ready for lead review.
