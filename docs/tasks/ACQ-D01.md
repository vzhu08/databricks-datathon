# ACQ-D01 · Developer D · Databricks integration, validation and coverage

Task issue: https://github.com/vzhu08/databricks-datathon/issues/6

Owner: one separate Codex chat, accountable to Oliver. Branch `codex/acq-d-databricks`. Own only `databricks/enrichment/`, `tests/databricks/enrichment/`, and `docs/handoffs/ACQ-D01.md`. Read the remote board, contract v1.0.0, schema, source registry and synthetic fixture. Do not edit shared contracts, A/B/C implementations, baseline app or original ingest ownership paths.

## Independent stage: implement and test now

1. Implement a local validator CLI `python databricks/enrichment/validate_batch.py --batch <file> --base <file> [--accepted <file>]`. Validate the JSON Schema plus semantic references across staged and accepted rows. Unknown versions, duplicate IDs with different payloads, dangling references, non-finite coordinates, bad date/time formats, invalid review state, and unsupported clinical inference must fail with actionable row/field errors.
2. Evidence linked to a base ID must reference a confirmed match with the same base/external IDs. Non-ID confirmations require a reviewer/timestamp. Spatial observations must stay location evidence and include method/source/units/limitations. Rejected/conflicted candidates cannot corroborate service claims. Null identity links remain permissible for B's unlinked evidence.
3. Implement deterministic staging/merge planning locally. Identical snapshots/rows are replay-safe; conflicting immutable payloads fail; mutable review decisions require explicit audited transitions. Demonstrate input order does not change accepted output. Preserve original base rows/counts/text.
4. Build parameterized Databricks notebooks under your scope for source inspection, original-field mapping/profile, Volume import, five Delta table creation, validation, staged writes and coverage reporting. Parameters include original table, writable output catalog/schema, input Volume/path, contract version and run ID. Validate/quote identifiers and bind values; never interpolate arbitrary user strings into SQL.
5. Publish only a fully validated run. Do not describe five sequential Delta writes as one atomic transaction. Use staging and a completed-run manifest/pointer so consumers retain the previous completed run after a partial failure; document recovery and replay. Keep operational run metadata distinct from the five evidence tables.
6. Document runtime/dependencies, least necessary privileges, exact notebook order, expected inputs/outputs, rerun/recovery commands and how to verify counts. Download externally outside Databricks when its outbound restrictions require it; do not add paid infrastructure or credentials to Git.

## Live stage: inspect rather than assume

7. Check available authorized Databricks access. The orchestrator observed a signed-in browser listing but no accessible facility rows, and the console reported automated browser control unsupported. Use an existing authorized API/connector/CLI if available; otherwise provide precise manual source-export/import/run steps. Do not extract browser tokens, bypass the console warning, invent a configured catalog/table, or wait idle on credentials while local work remains.
8. Inspect the actual Marketplace table and included postal directory when accessible. Record actual schema, version/snapshot, row count, missingness, duplicated IDs, coordinates and evidence fields. Preserve source IDs; document a stable raw-row-derived surrogate only if needed. Hand A/B/C the mapping and non-sensitive profile, with actual records in approved local/Volume locations only.
9. After A/B/C outputs pass validation, run the import in Free Edition and report actual table names, run/revision IDs, source/artifact IDs, table counts, rejected/quarantined rows and row-preservation checks. If blocked, record the exact missing access/action and keep live status explicitly unverified.
10. Produce coverage by state, type, match status, source family, trauma evidence and freshness; include denominators, unknowns and errors. Do not conflate record completeness, identity confirmation, service evidence and live availability.

## Required tests and acceptance

Run `python3 -m unittest discover -s tests/databricks/enrichment -p 'test_*.py' -v` and validate the shared fixture using your CLI. Cover schema rejection, format validation, cross-batch references, unknown base IDs, linked evidence to wrong/rejected match, unreviewed manual confirmation, duplicate replay, conflicting payloads, explicit review transitions, partial-write recovery, unrecognized contract version, and unchanged base identity/text.

Use simulated storage/failures for local recovery tests and report them as simulations. A local mock is not a live Delta proof. A live check must separately test actual write/read/replay and completed-run publication when access exists.

Open a PR with requirements and setup instructions, no merge. The handoff must include exact commands/counts, tested head SHA, synthetic vs live checks, actual access findings, run/table/artifact references, schema compatibility, and the smallest precise user action for remaining live blockers. Complete all unblocked local work even if no credentials exist.
