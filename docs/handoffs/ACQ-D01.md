# ACQ-D01 handoff

## Private rehearsal preparation and artifact binding · November 21

PR #85 follow-up addresses Vincent's [consumer-shape review](https://github.com/vzhu08/databricks-datathon/pull/85#pullrequestreview-6008598001). The binder now rejects missing or malformed checked-source lists, reasons, review lists and original/external citation fields before staging. The positive fixture has the producer's complete lookup shape. A combined checkout with #79 at `4352d17bfd02df4427b96e00728f77d13c6495b7` passes all **107 enrichment tests**, including actual producer output through publication/readback and both real lookup functions. D's branch alone passes 106 with that integration test explicitly skipped until #79 is present. Both real consumers also read every one of the 10,088 occurrences / 30,264 decisions from the unchanged downloaded structural artifact after the stricter binding checks. The separate live-approval request remains pending.

Vincent accepted the frozen retrieval inputs and `workspace.datathon_vf_v0_validation` destination in [#6](https://github.com/vzhu08/databricks-datathon/issues/6#issuecomment-7069928655). D prepared notebook 04 for run `vf-in-retrieval-v0-20261121-01` and its isolated `-recovery` attempt. It uses the existing five additive tables and operational manifest, retains partial attempts, verifies all five pinned readbacks, checks replay without new versions and checks recovery without original-payload drift. It excludes service-status controls, second-pass identity rows and supplementary sources.

Read-only workspace checks found that the target schema does not exist, catalog-level grants contain no inherited data-read privilege, and there is no existing cluster/job to reuse. Automatic approval review rejected the attempted schema/notebook/serverless-run creation because direct user authorization is required for those persistent and potentially usage-bearing mutations. That command did not execute. The exact requests and code bundle are prepared in ignored `data/local/publication-rehearsal-20261121/`; direct user approval is pending. No validation schema, live table, notebook or run was created by that rejected action. No live publication or submission is claimed.

The separately authorized status-artifact binding is implemented in D's publisher and notebooks 02/03. It preserves the original input-metadata digest before operational references are added; verifies the artifact bytes, base/version/date/identity pins and every occurrence/service; reconciles counts; and requires the entire merged batch hash before staging. The completed manifest retains the separate artifact reference. Consumer reads and replay recheck it. These are structural checks, not clinical adjudication or release approval.

**Local validation:** all 104 enrichment tests pass on Python 3.12.16, including seven status-binding tests and a persistent rehearsal simulation. The binding also passes against the previously downloaded structural artifact `9428f87d55547fdf51256a2b73c0db1a9551dd00c02fdd1096ba21b3a5798767`, preserving all 10,088 occurrences / 30,264 unconfirmed decisions and the accepted batch hash. This was a local read of the existing private readback, not a new live storage or Delta check. Compilation and diff checks pass. Earlier handoff sections below record historical checkpoints; the duplicate-metadata, portability and original source-access blockers are resolved in their later issue receipts.

## Portability correction and joint validation · November 21

PR [#74](https://github.com/vzhu08/databricks-datathon/pull/74) now writes and compares manifest-relative paths with `as_posix()`, addressing Vincent's [native Windows reproducer](https://github.com/vzhu08/databricks-datathon/issues/6#issuecomment-7069398792). Tested code commit: `f08f4711a0724daca26ba495d8294e3f93daac7a`. All **96 enrichment tests** pass on Python 3.9.6; compilation and diff checks pass. Two nested-path regressions exercise Windows relative-path formatting on this macOS host, fail against the previous implementation, and pass with the correction. Native Windows execution remains Vincent's independent check.

The downloaded 70-file national package passes normal replay and replay with Windows relative-path formatting. All six derived outputs remain byte-identical, with 10,088 original rows, 10,077 distinct payloads, 11 duplicate groups and zero lost or added rows. The frozen prepared-manifest SHA-256 remains `9493372df8e4f34004bef4d7651f3885ae6a1e11621c008eb7cf0a8cc36912f8`; no package was regenerated, uploaded or changed.

D independently checked C head `6ee81bc60f921140878f9f964cf89825e45b962c` with D head `77b9061e4aa78f7a385669dcb1e1e14af8b63963`. All 11 national matching tests pass. A further fixture used C's five original synthetic rows with D-generated occurrence handles and sidecar, source metadata, both normal CLIs, and D's SQLite publication/readback/idempotent-replay simulation. All five rows and their original-payload multiset remain; outcomes are 1 confirmed, 2 ambiguous, 1 candidate-only and 1 unmatched. This verifies the full-base duplicate correction without changing the shared uniqueness rule.

The [remaining C metadata mismatch](https://github.com/vzhu08/databricks-datathon/issues/57#issuecomment-7069459685) is separate: C validates `original_id`, but D emits `original_unique_id`. Changing that emitted field to a false synthetic ID is accepted and reported as unverified. Andrew owns the correction. The real base-file digest, original multiset and all 11 sidecar handle groups were independently checked by D. Private synthetic receipt: `data/local/reviews/joint-twins-6ee81bc/verification.json`.

The remote board was reread at `5a5b88b`. Vincent owns merge/readiness decisions. Accepted national matching and service outputs, live five-table Delta publication, completed-pointer/failure checks and submission remain pending; local simulation does not establish those results.

## National version-0 base · November 21 follow-up

The original-source access blocker is resolved. D implemented Vincent's [reviewed occurrence-key policy](https://github.com/vzhu08/databricks-datathon/issues/6#issuecomment-7069026841), exported both pinned sources, prepared the complete national base and delivered it through the existing private team Volume. Tested implementation: `16a0190ba594a9239d4439024caa23fc7de9d9e0` on `codex/acq-d-databricks`, started from main `e9c83bc`. The remote board was reread through `6c1d721` for handoff. The follow-up handoff commit changes documentation only; the final head and PR are recorded on #6.

All 10,088 original facility rows remain, including the 11 pairs with identical original IDs and full payloads. Singletons retain their original ID as `facility_id`. All 22 repeated occurrences receive the reviewed `base-occurrence:` hash of `[source_table, "0", original_id, ordinal_string]`. Every original field, null and `unique_id` remains in `source_row`. Ordinals express interchangeable copies within this snapshot, not separate campuses, physical source identities, independent confirmations or cross-version continuity. Default duplicate rejection remains in force for other inputs. The private duplicate-group sidecar binds each shared original ID/payload to its multiplicity and row handles.

### Live source and preservation results

Source catalog/schema: `databricks_virtue_foundation_dataset_dais_2026_databricks.virtue_foundation_dataset`. Both `facilities` and `india_post_pincode_directory` were read with **VERSION AS OF 0** on the existing warehouse `8bac239c2de8f8da`, through Oliver's authorized CLI session supplied in [A's non-secret operator handoff](https://github.com/vzhu08/databricks-datathon/issues/6#issuecomment-7069116214). No credentials were copied, no grants were changed, and no source table was written.

Capture ran **2026-11-21T21:00:47.199571Z–21:01:37.009669Z**. Eight facilities buckets and sixteen postal buckets completed without truncation. The capture retains all 51 facility columns and 11 postal columns, exact SQL-generated row JSON, statement IDs, queries, UTC retrieval times, schemas and hashes. A's 14-file metadata packet was downloaded and fully hash-verified before acquisition. It has manifest SHA-256 `538f3602e84526ef1df2492c78c5f9d22d55644195b7462f2f5f6f983f51dcf5`.

| Check | Observed result |
| --- | ---: |
| Original / prepared facility rows | 10,088 / 10,088 |
| Unique internal row handles | 10,088 |
| Distinct original IDs / full payloads | 10,077 / 10,077 |
| Identical duplicate groups / generated occurrence keys | 11 / 22 |
| Original rows lost / added | 0 / 0 |
| Original PIN-directory rows retained | 165,627 |
| Distinct postal PINs / maximum offices per PIN | 19,586 / 153 |
| Rows preserved by grouped PIN lookup | 10,088 |
| Base rows with exact six-digit postal context | 9,568 |

The complete prepared key set independently matches the approved SQL formula on the live version-0 source. Sorted-key SHA-256: `96ffb861cd0a2d4092889289d58574d1e512157c907724e46e70a6eb869850b9`. Statement: `01f1e5ef-654e-1a3e-b625-7e21a67e2567`. The aggregate proof is retained privately at `data/local/national-v0/proofs/row-key-proof.json`, SHA-256 `abc40f35c711cb2d20f2539574a02e7bbae966672cf061c0ee2cbe3921d2d94a`. This is D's direct check under Oliver's account, not another teammate-account receipt.

Original facilities canonical multiset SHA-256: `30d32fa927f5d43753ea6d42f3685ea62e1b416a6cffce7e11ebd1d83b905ca6`. Raw JSON bytes and canonical logical-value hashes are recorded separately. The preserved JSON types, field sets and original-row multiset are checked before preparation. Postal values are unchanged; only the contextual lookup trims exact six-digit facility postcodes and groups directory entries to one PIN key.

### Verified private delivery

```text
/Volumes/workspace/datathon_acquisition/matching_inputs/national-base-v0-20261121-d01/
```

All **70 files / 265,584,762 bytes** were uploaded, with `prepared_manifest.json` written last. D downloaded the package into a separate ignored directory and verified the manifest plus every listed file hash. C must separately acknowledge its own-account download/readback. Relative artifact paths permit transfer without changing row keys or hashes.

| File | SHA-256 |
| --- | --- |
| prepared_manifest.json | `9493372df8e4f34004bef4d7651f3885ae6a1e11621c008eb7cf0a8cc36912f8` |
| capture_manifest.json | `977832fc184804007bba66a1e553003de549c77041ad041e2d11c4fb72bd4b59` |
| base.json | `27e4a79de42ec56c76cc676ed45494a52497d179858bc50549a461434c45e9d8` |
| source_metadata.json | `f3cb10bee47de40ac886523456229a0121de8843c7ff574e53ffb963f40860c1` |
| duplicate_groups.json | `f2a443a625bdea68e0e3b09a76875f17b05ff9e6b942db5a0db1c3b6f3e49a63` |
| postal_rows.json | `af41bd5f7a20653f4af877ebd9c878d4cc162fb683e7fb7253bda24564d56343` |
| postal_metadata.json | `81ee248f3dd6f8c913cbf801f4eecd7dc929066348534c360d0839550a34af8f` |
| validation_report.json | `928e17acf564eee3b4af07ea0c695deafdee4fb66e1451e4a4833afcca1009c8` |

Authoritative ignored local root: `/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-d/data/local/national-v0/capture-20261121/`. Independent storage readback: sibling `readback-20261121/`. No real source records, raw snapshots or credentials are tracked in Git. The private package preserves the source's provenance; it does not grant public redistribution rights.

### Checks, reproduction and next consumer

Fixture checks: **94 enrichment tests pass** on Python 3.9.6, including occurrence keys, collisions, changed payload/snapshot rejection, default duplicate rejection, SQL chunk/truncation checks, postal cardinality, original-field preservation, package integrity and replay. Compilation and `git diff --check` pass. All tests use synthetic rows.

Live/local checks: the real prepared base passes the D validator with zero errors. Its validation envelope is intentionally empty: this verifies the 10,088-row base, not matching or service support. All six derived files replay byte-identically without network. The private upload and full hash-verified download/readback are separate successful live storage checks.

```sh
research/certification/.venv/bin/python -m unittest discover -s tests/databricks/enrichment -q
research/certification/.venv/bin/python databricks/enrichment/prepare_versioned_base.py replay \
  --run-dir data/local/national-v0/capture-20261121
research/certification/.venv/bin/python databricks/enrichment/prepare_versioned_base.py replay \
  --run-dir data/local/national-v0/readback-20261121
research/certification/.venv/bin/python databricks/enrichment/validate_batch.py \
  --batch data/local/national-v0/proofs/empty-enrichment.json \
  --base data/local/national-v0/capture-20261121/base.json --as-of 2026-11-21
```

[NATIONAL_BASE.md](../../databricks/enrichment/NATIONAL_BASE.md) documents fresh acquisition, explicit policy activation, observed mapping, portable replay, private delivery and failure handling. Existing captures/finalized outputs refuse overwrite. Notebook 01 now accepts the explicit occurrence policy and an independent postal-version widget; the successful live run used the SQL/CLI exporter, not Spark notebook execution.

Andrew receives `base.json`, its source metadata, `duplicate_groups.json`, `postal_rows.json` and postal metadata for the full **10,088-row** national run. Retain unknown geography and zero-candidate rows. Shared duplicates count once for independent campus/evidence review while every original occurrence remains in output. The ordinary v1 validator currently allows one confirmed base ID per external record; duplicating confirmations across occurrence handles requires Vincent/C coordination before publication. D flagged this in [#6](https://github.com/vzhu08/databricks-datathon/issues/6#issuecomment-7069237153), and this source-preparation patch leaves that rule unchanged.

Five-table enrichment publication, a completed-run pointer update, live Delta replay/failure testing and submission: **not performed in this follow-up**. They remain downstream of the accepted C/B outputs and the coordinated service-status work in #67. The integration lead owns PR review, board updates and readiness decisions.

## Earlier D01 handoff · historical record

The following record predates source access. Its original-source blockers are superseded by the version-0 results above; its fixture/publication-simulation distinctions remain applicable.

Developer D · `@oliverchennn` · Codex chat `01a1ff42-470d-7f20-a2e2-ed23665cc075` · November 21, 2026.

Branch: `codex/acq-d-databricks`. [PR #17](https://github.com/vzhu08/databricks-datathon/pull/17) · [issue #6](https://github.com/vzhu08/databricks-datathon/issues/6). Tested implementation SHA: `ddb17b68f1b92b3b881b44311a3d6dcbe886a7a3`. Tests, fixture validation and real public-batch validation also passed at `fa7136455ebe53be881f37524b0e261f7c57d006` (same implementation plus initial handoff). This final handoff update changes documentation only; the final pushed head is recorded on the issue/PR to avoid a self-referential commit SHA in this file.

Status: local implementation ready for review. Live original-source inspection and Databricks publication are blocked/unverified. No merge, deployment or submission was performed.

## Scope and compatibility

Only `databricks/enrichment/`, `tests/databricks/enrichment/`, and this handoff were changed in the prepared Developer D clone. No shared schema, registry, fixtures, board, A/B/C paths, original ingestion, app or kit changes. The authoritative board was last reread at `origin/main` commit `18ba546878b28fe78f792e050facef123e729a81`; that board confirms A's PR #13 is merged and its batch is ready. The shared contract/schema/fixtures remain unchanged from PR #8. A merge-tree check against that main completed without conflicts; GitHub reported PR #17 `MERGEABLE` / `CLEAN`. No merge was performed by D.

Delivered: format-aware JSON Schema and semantic CLI; additive deterministic merge; explicit hashed review transitions; original-row preservation; bounded source inspection/export and postal profiles; typed five-table Delta staging; a separate completed-run operational manifest/pointer; coverage with denominators/unknowns; and three parameterized notebooks. [Setup, privileges, notebook order and recovery](../../databricks/enrichment/README.md) document the full workflow.

Evidence snapshots may differ from identity snapshots. All references must resolve, linked evidence must agree with a confirmed base/external match, cross-source claims require review, and spatial observations remain location-only. Unlinked evidence stays permissible. Automatic shared-identifier confirmation additionally requires an inspected namespace policy and unambiguous exact values. Clinical token/phrase checks reject known invalid upgrades but cannot prove arbitrary text: reviewers must inspect the source, exact excerpt, campus and scope before supplying review metadata. That limitation is explicit in the runbook.

## Fixture and local checks

Environment: Python 3.9.6; scoped venv with `jsonschema[format]==4.23.0`. Run from the Developer D clone:

```sh
source databricks/enrichment/.venv/bin/activate
python3 -m unittest discover -s tests/databricks/enrichment -p 'test_*.py' -v
python databricks/enrichment/validate_batch.py \
  --batch contracts/fixtures/enrichment.json \
  --base contracts/fixtures/enrichment_base.json --as-of 2026-11-21
PYTHONPYCACHEPREFIX=/private/tmp/acq-d-pycache python3 -m compileall -q databricks/enrichment -x '/.venv/'
git diff --check
```

Results: **53 tests passed** at the tested implementation SHA; shared fixture CLI exited 0; Python modules/notebooks compiled; whitespace check passed. The host Python cache initially targeted a sandbox-restricted Library directory; the explicit temporary cache prefix above resolved compilation without changing source or permissions.

| Synthetic result | Count |
| --- | ---: |
| Original base rows preserved | 2 |
| Source snapshots | 3 |
| External facilities | 3 |
| Matches | 3: 1 confirmed, 1 candidate, 1 rejected |
| Evidence | 3 |
| Review queue | 1 open, 0 resolved |
| Trauma evidence | 2: 1 historical supports, 1 undated inconclusive |
| Base identity confirmed | 1 / 2 |
| Base linked trauma evidence, including historical | 1 / 2 |
| Evidence with unknown effective date | 2 / 3 |
| Successful-run validation errors / quarantined rows | 0 / 0 |

Base canonical hash: `4bf2616c4625d06f2c99de8898b6f51b629f375db0835179e103bed23c4a53fd`. Synthetic snapshot IDs:

- `synthetic:directory:430aecf9171c7ed9de49e30109a99022ff93cc26a63682d21450c0cb86fbc892`
- `synthetic:program:f296582b770dee757db07bd6992fd837c5324636f9297002245a7e81be6763a5`
- `synthetic:buildings:b974d3d93b325b4b1ac8c3ce39d890a4a69867eafad6029fb7e48bc11f29346b`

Tests cover malformed schema/version/date/URI/non-finite values, missing references, cross-batch references, wrong/rejected linked matches, unreviewed confirmations, spatial/service misuse, unsupported clinical upgrades, namespace proof/ambiguity, duplicate/conflicting replay, deterministic order/timestamp handling, audited transitions/hash chains, unchanged original text, and unsafe identifiers/Volume paths.

SQLite **simulations** interrupt publication after each of writes 1–5, verify the previous completed pointer remains readable, reopen persistent local storage, recover/replay, reject changed run IDs/base text, detect readback corruption and handle a competing publisher. They do not test live Spark, Delta transactions, Unity Catalog, permissions or Free Edition behavior. The five data writes are sequential; only the operational completed-pointer change is one atomic update. The published consumer reads one captured manifest and its five pinned versions.

## Real public inputs

After A posted its final readiness handoff on issue #3, D read A's handoff and consumed its ignored combined batch read-only. No source files or A-owned paths were modified, and no real records were committed. A's batch file SHA-256 independently matched `4b5900bad2a57a179d03a6eab88f283db4f44d62a7a13b57ea77c6d445e951aa`.

From the Developer D clone, with the scoped environment active and an intentionally empty base JSON array at `databricks/enrichment/.venv/empty-base.json`:

```sh
python databricks/enrichment/validate_batch.py \
  --batch ../developer-a/data/local/acquisition/public/runs/0eac1025996c46409dd3b07aeca8e283/batch.json \
  --base databricks/enrichment/.venv/empty-base.json --as-of 2026-11-21 \
  > databricks/enrichment/.venv/public-validation.json
```

**Exited 0:** 2 snapshots, 146,847 external records (OSM 136,004; NHP 10,843), 172 open reviews, 0 matches, 0 evidence, 0 base rows. The empty base is a source-batch compatibility check, not a substitute Marketplace dataset or original-facility coverage claim. Missing external values: 3,218 names, 1 coordinate pair, 136,235 PINs, 1,292 states. Both snapshots preserve `shared_origin`; the 172 reviews remain unresolved. No D evidence review or source recrawl is implied by this validator pass.

Real public snapshot IDs:

- `hot_osm_health:5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3`
- `nhp_hospitals_mirror:058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47`

Artifact root remains `/Users/oliverchen/Documents/ChatGPT/databricks hack/.workspaces/developer-a/data/local/acquisition/public/`. A's [handoff](https://github.com/vzhu08/databricks-datathon/blob/main/docs/handoffs/ACQ-A01.md) records raw snapshot paths, download/replay provenance and attribution. D's aggregate validation report is local/ignored at the path above. B/C human batches remain later inputs; none were fabricated. Real Marketplace matching, authorized Volume upload and live Delta publication remain blocked.

## Live Databricks findings and smallest next action

Inspected configured access without printing credentials: no `databricks` executable, no `DATABRICKS_*` environment configuration, no `~/.databrickscfg`, no repository `.databrickscfg`, and no enabled Databricks connector. A signed-in listing previously observed by the orchestrator is not evidence of table-row access. No browser tokens were extracted and no unsupported automated browser control was attempted.

Actual Marketplace/postal schema, field mapping, version, row count, data missingness, writable catalog/schema/Volume, live table names, run/revision IDs and live artifact IDs: **not observed / unverified**. No live Delta writes or publication/replay checks occurred. No source mapping is invented in the notebooks or this handoff.

Smallest next action: an authorized workspace operator opens notebook `01_inspect_sources.py` in a Workspace Git folder, selects the actually installed original and postal tables in Catalog Explorer, sets their full names plus a permitted Volume output path, runs the schema/profile cell, enters the observed column mapping and runs export. Keep `base.json`/postal rows in the approved Volume; provide the non-sensitive schema/profile, mapping and artifact paths to D/C. This alone unblocks real identity matching without sharing credentials in chat. Alternatively configure an approved Databricks CLI/API connection through normal authentication, then rerun inspection.

With validated producer inputs available, run notebook 02 once for empty-table bootstrap in a dedicated output schema, again for validation/publication, then notebook 03 for hash/count/coverage readback. Run notebook 02 again with identical run ID/inputs to verify live replay. Actual partial-write failure testing must occur in a scratch output schema and be recorded separately from the SQLite simulations. The runbook supplies exact widgets, installation/offline dependency options, input/output paths, privileges, rerun rules and count verification.

## Remaining constraints and submission status

This sprint implementation performs bounded driver-side validation/staging, with operational history in one JSON state row. Published Delta versions must remain available; consumers must not count unfiltered staged attempts. Source changes require a reviewed base revision/output schema. Source truth and clinical interpretation remain human review responsibilities.

Repository artifacts contain code, documentation and synthetic tests only. Dependencies remain in D's scope; real records/credentials are absent. The integration lead owns board updates and merge decisions. Submission status: **not attempted; not verified**.
