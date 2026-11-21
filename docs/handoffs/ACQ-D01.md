# ACQ-D01 handoff

Developer D · `@oliverchennn` · Codex chat `01a1ff42-470d-7f20-a2e2-ed23665cc075` · November 21, 2026.

Branch: `codex/acq-d-databricks`. Task and final PR/head record: [issue #6](https://github.com/vzhu08/databricks-datathon/issues/6). Tested implementation SHA: `ddb17b68f1b92b3b881b44311a3d6dcbe886a7a3`. The handoff is a subsequent documentation commit; the final pushed head and its repeated checks are recorded on the issue/PR to avoid a self-referential commit SHA in this file.

Status: local implementation ready for review. Live original-source inspection and Databricks publication are blocked/unverified. No merge, deployment or submission was performed.

## Scope and compatibility

Only `databricks/enrichment/`, `tests/databricks/enrichment/`, and this handoff were changed in the prepared Developer D clone. No shared schema, registry, fixtures, board, A/B/C paths, original ingestion, app or kit changes. The authoritative board was reread at `origin/main` commit `eea8686d94fcd4b6ca649096f08cf9007ccba86a` before handoff. The implementation consumes the v1.0.0 schema and contract published in PR #8.

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

No real source rows were acquired by D or committed. At this handoff, A's issue #3 reports successful public OSM/NHP acquisition (136,004 + 10,843 external rows after OSM exact-repeat collapse), but its final readiness handoff has not yet been posted. D has not consumed or independently validated those artifacts. Readiness/compatibility is pending, not a fixture-derived public result. A's ignored `data/local/acquisition/` artifacts may be consumed read-only once its handoff confirms readiness. B/C human batches remain later inputs; none were fabricated.

## Live Databricks findings and smallest next action

Inspected configured access without printing credentials: no `databricks` executable, no `DATABRICKS_*` environment configuration, no `~/.databrickscfg`, no repository `.databrickscfg`, and no enabled Databricks connector. A signed-in listing previously observed by the orchestrator is not evidence of table-row access. No browser tokens were extracted and no unsupported automated browser control was attempted.

Actual Marketplace/postal schema, field mapping, version, row count, data missingness, writable catalog/schema/Volume, live table names, run/revision IDs and live artifact IDs: **not observed / unverified**. No live Delta writes or publication/replay checks occurred. No source mapping is invented in the notebooks or this handoff.

Smallest next action: an authorized workspace operator opens notebook `01_inspect_sources.py` in a Workspace Git folder, selects the actually installed original and postal tables in Catalog Explorer, sets their full names plus a permitted Volume output path, runs the schema/profile cell, enters the observed column mapping and runs export. Keep `base.json`/postal rows in the approved Volume; provide the non-sensitive schema/profile, mapping and artifact paths to D/C. This alone unblocks real identity matching without sharing credentials in chat. Alternatively configure an approved Databricks CLI/API connection through normal authentication, then rerun inspection.

With validated producer inputs available, run notebook 02 once for empty-table bootstrap in a dedicated output schema, again for validation/publication, then notebook 03 for hash/count/coverage readback. Run notebook 02 again with identical run ID/inputs to verify live replay. Actual partial-write failure testing must occur in a scratch output schema and be recorded separately from the SQLite simulations. The runbook supplies exact widgets, installation/offline dependency options, input/output paths, privileges, rerun rules and count verification.

## Remaining constraints and submission status

This sprint implementation performs bounded driver-side validation/staging, with operational history in one JSON state row. Published Delta versions must remain available; consumers must not count unfiltered staged attempts. Source changes require a reviewed base revision/output schema. Source truth and clinical interpretation remain human review responsibilities.

Repository artifacts contain code, documentation and synthetic tests only. Dependencies remain in D's scope; real records/credentials are absent. The integration lead owns board updates and merge decisions. Submission status: **not attempted; not verified**.
