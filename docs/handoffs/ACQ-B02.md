# ACQ-B02 · Rajasthan dialysis evidence

Vincent Zhu (`vzhu08`) prepared this unlinked v1.0.0 release on November 21, 2026. Four private hospitals describe dialysis services at a named campus. Two institution-affiliated studies describe historical activity. The independent government audit supports a historical charge. A public hospital charter and a workshop agenda leave patient services unknown. Current acceptance is unknown in all nine cases. [Assignment #33](https://github.com/vzhu08/databricks-datathon/issues/33)

## Sources and coverage

The inventory considered 18 distinct dialysis documents. Retrieval attempts included alternative hosts for three documents. The collector stored original bytes for 13 of 18, including four context documents and nine documents selected for campus-level review. The separate DHIS facility directory belongs to A03 and is excluded from these totals.

| Denominator | Result |
| --- | --- |
| Nine selected claims | All nine original hashes, verbatim passages and locators passed independent documentary review. The sample includes Jaipur, Udaipur and Jodhpur, with public and private institutions. |
| Nine released external records | Four name a service in a hospital’s own listing, two describe an institutional study, one records a historical charge, one concerns training and one leaves dialysis unknown. Source records can describe the same campus. |
| Nine dated or undated observations | Four have a documented historical period or event date. Five are undated. The study publication date is distinct from the period observed. |
| Nine claims assessed for independence | One independent auditor supports the narrow claim about historical charges. The prespecified historical reference overlaps one campus and supports a scheme recommendation there. It confirms zero full producer assertions. |
| Nine claims assessed for contradiction and live availability | Zero comparable clinical contradictions were found. All nine remain inconclusive for current capability, with zero VF matches and zero live acceptance checks. |

The private and public campuses on opposite sides of a Jaipur street remain separate. The two Udaipur documents share an institutional origin. A financial charge, an event agenda and a catheter-insertion study each describe a different activity. Their time and place do not automatically establish where treatment took place. An incoming referral to a tertiary hospital is compatible with onsite treatment. The inventory located no verified standalone outgoing-referral-only campus claim.

The national programme page, the national model procurement document, a parliamentary reply and a national programme review were retained for context. The bid specifies how states can procure services. Geographic totals do not establish campus operations. Retrieving the Rajasthan budget, state tender, state programme page, AIIMS annual report and ESIC tender originals from Vincent’s machine failed. Indexed portions and an alternative national bid informed the access log. They were excluded from the nine accepted originals. Collectors retained institutional observations and aggregate scholarship only. [National programme](https://nhsrcindia.org/pradhan-mantri-national-dialysis-program) · [Official procurement template](https://nhsrcindia.org/sites/default/files/2023-06/FINAL%20DIALYSIS%20REVISED%2006%20JUN%2023.pdf)

## Reproduce the public-source release

Use Python 3.12. The [source recipe](../../research/dialysis/release02_recipe.json) contains the nine publisher URLs, SHA-256 digests, original capture metadata and source locators. Obtain permitted originals from the publishers or a permitted archive and put them directly inside one directory. Filenames may differ. Changed web pages require an archived copy with the published digest. The program checks every input hash and the two output hashes. Its extraction rules do not require Vincent’s private manifest.

```sh
python -m pip install -r research/dialysis/requirements.txt
python -m research.dialysis.replay_sources --originals PATH_TO_EXACT_ORIGINALS --out PATH_TO_NEW_RELEASE
python -m unittest discover -s tests/research/dialysis -p "test_*.py" -v
```

On Vincent's primary machine the canonical files are under `data/local/dialysis/b02/`. Use `raw/` as the originals directory. The frozen candidate and corrected release are in `release-01/` and `release-02/`. Re-running the source-only command with nine renamed originals in a clean directory reproduced the following values.

| File | SHA-256 |
| --- | --- |
| `release-02/batch.json` | `198c8049d950b093c7a6916168481310cd3ebc8e877dd967b90a2346b45b3a4b` |
| `release-02/claim_ledger.json` | `a47e7bb6f645c808dba351d16c04467b51d4f360c90629cacc2ac6489a2f8113` |
| `release-02/sha256.json` | `4dfaf8faad74ee7d245dcd6d83eafd219bd201270640bae9937d34b24591d737` |

## Independent review and checks

The reviewer reserved an external Jaipur scheme document before seeing producer claims, recorded its original hash and coded 35 historical entries before receiving the candidate release. All nine producer claims were examined, including the adjacent-campus case and same-origin overlaps. The review found one missing source publication date, July 13, 2026. Vincent corrected the snapshot date and retained the original candidate bytes. All nine evidence payloads retained their original hashes. The independent audit ledger binds the source and claim hashes and reproduced twice.

The local audit folder is `data/local/dialysis/b02-audit/`. Its `final-audit.json` SHA-256 is `49770109ce67c8a170430cb53d0bc81ebc1d6c25aae0252898fb51b1e174debc`. The `final-summary.json` SHA-256 is `45306d2b6e39c7a99b1209ed9e024fb16b08fdb0325d2caa35d2f63b850b3c3a`. The source-level auditor used the same available originals plus the reserved reference. Its historical and geographic limits preclude a statewide accuracy estimate.

```sh
python -m research.dialysis.audit --batch PATH_TO_RELEASE/batch.json --decisions PATH_TO_AUDIT/final-audit.json --summary PATH_TO_AUDIT/final-summary.json
python databricks/enrichment/validate_batch.py --batch PATH_TO_RELEASE/batch.json --batch PATH_TO_RELEASE/batch.json --base PATH_TO_EMPTY_JSON_ARRAY --as-of 2026-11-21
```

Twelve synthetic tests cover proposal/referral language, missing and changed originals, locator mismatches, identity separation, outcome binding, immutable output and replay from renamed originals. D’s validator accepted the repeated real envelope on an empty base, with nine snapshots, nine external records, nine evidence rows, nine open review items and zero matches. The archive contains no VF base rows. No live Delta publication or submission was performed.

## Andrew’s trauma input

Use the B01 [source and replay handoff](ACQ-B01.md) and `research/trauma/requirements.txt`. Vincent’s frozen inputs are in `data/local/trauma/acq-b01/lead/inputs/`. In an approved location with that input tree, run `python -m research.trauma.pipeline --input-dir PATH_TO_INPUTS --output-dir PATH_TO_NEW_TRAUMA_RELEASE`. Verify the B01 batch SHA-256 `cde57eb095a426143d4dd32d005daa1432e7ec351b459531ccafedcf0684ab89`. The A03 team ZIP contains A’s inputs. The B research originals and excerpts remain in permitted research storage, subject to the respective source terms. [Andrew's pilot](https://github.com/vzhu08/databricks-datathon/issues/5)
