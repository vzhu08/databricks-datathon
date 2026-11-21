# Acquisition developer kickoff prompts

The current [board on main](https://github.com/vzhu08/databricks-datathon/blob/main/docs/implementation/OWNERSHIP.md) supersedes the old first-pass assignments. A and D run in separate Codex chats; B and C are human roles. No named-account mapping is assumed. Read AGENTS.md, the current plan, acquisition contract, and your task card. One executor per task; use an isolated clone and your assigned branch.

## Every developer

Read the remote board at kickoff and before handoff. If it cannot be read, report that blocker before starting a new assignment. Work within your path scope. Propose shared contract changes to Oliver. Do not overwrite another branch, modify kit/, merge PRs, deploy, or commit real data. No recurring automation is required for this finite sprint. Report exact checks and distinguish fixtures, public data, and live Databricks.

## Developer A · Codex

```text
Implement ACQ-A01 in this checkout. Read its complete task card and contract v1.0.0, then start the work rather than returning a plan. Own only research/acquisition/, tests/research/acquisition/, and docs/handoffs/ACQ-A01.md on codex/acq-a-collectors. Produce working OSM/NHP collectors and normalized batches with reproducible provenance. Run all acceptance cases, attempt the real public-source acquisitions, record actual outcomes, and open a PR. Keep working through recoverable problems; surface exact external blockers. Do not merge or change shared contracts. Post the handoff on your task issue.
```

## Developer B · human research lead

Open your own coding chat in Plan mode and paste the planning kickoff from [ACQ-B01](tasks/ACQ-B01.md). After approving its plan, switch out of Plan mode and paste the explicit completion-goal kickoff. Launch the five research chats described there in your own account, each in a separate checkout and non-overlapping scope. You own synthesis and acceptance; do not declare done merely because the five chats finished.

## Developer C · human identity/geography owner

```text
Claim ACQ-C01 in its issue with your handle/session. Read its full task card and the current main board. Implement conservative identity matching and geographic review on codex/acq-c-matching, within the listed paths. Start with the synthetic fixtures while A/B/D prepare real handoffs. Do not auto-confirm name-only or proximity-only matches. Test all required adversarial cases, then audit real candidates when available. Keep original coordinates and record footprint uncertainty. Open a PR and provide exact results and live blockers; do not merge.
```

## Developer D · Codex

```text
Implement ACQ-D01. Read the complete task card and contract v1.0.0. Own databricks/enrichment/, tests/databricks/enrichment/, and docs/handoffs/ACQ-D01.md on codex/acq-d-databricks. Start with a strict schema/referential validator and local fixture tests, then parameterized staged Delta ingestion and source profiling. Inspect authorized Databricks access if available; do not invent a table, credentials, or successful live run. Complete every unblocked local component and provide the exact remaining user action for any live access blocker. Open a PR with evidence; do not merge or change shared contracts.
```

## Orchestrator

Keep the main board and shared contract current, inspect task progress, review scope/quality, and integrate accepted PRs in dependency order. Record exact branch heads and results. Never translate a fixture pass into a live-data or deployed-app claim. B/C claim their roles; A/D chat IDs belong in their issue/board records once created.

## Developer E · Ayuush

> You are Developer E, Ayuush (`ayushrgupta906`). Read the board and `docs/tasks/ACQ-E01.md`, claim the task issue, and complete the small eight-link check plus three-sentence demo reference. Use branch `codex/acq-e-source-links`; edit only your two listed documentation files. Report actual failures and open one scoped PR. No pipeline code or extra chats are needed.
