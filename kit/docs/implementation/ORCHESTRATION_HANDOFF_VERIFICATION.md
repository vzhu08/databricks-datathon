# Coordinator handoff and decision durability verification

Date: 2026-10-24. Base revision: `25aa6288443ea2c0c29129e90ea775f5c45913f9`.
Branch: `feat/orchestration`; existing draft PR #1. Kit `main` remains at
`8dbca44f8480b6d9375f56d0e18392e66b1325dd`.
Verified implementation revision: `37083e9b0af9568cc6c8166e6cca71a2088c7e08`.

Input: [handoff specification](../resources/orchestration/ORCHESTRATOR_HANDOFF_SPEC.txt).
Attachment SHA256 before Git text normalization:
`4ef6162b6d1f375c723ec732f3552c3625a36c2a22eb184df2d59d55420e655c`.
Its embedded instructions are product requirements, not permission to copy accounts,
invoke inference, send live tasks or deploy.

## What is implemented

- A bounded provider-independent checkpoint is an immutable Git blob referenced by
  the control branch. Non-force fast-forward ref updates provide atomic exclusion.
  Leadership epochs increase on acquisition; stale owners cannot authorize a task.
- Decisions carry user-facing summaries and rationale. New plan rationale is
  mandatory, and a dispatch decision must exist in the previous committed checkpoint
  before a new task lease can be authorized. Checkpoint failure stops dispatch.
- Failed authorization drafts stay local, are hidden from shared snapshots and
  cannot leak through later event saves, retries or handoff while paused.
- Task Issues are mirrors and worker-report channels; the checkpoint is assignment
  authority. A late stale Issue PATCH cannot change ownership or scope.
- Graceful offers designate a successor. Only receiving CAS acquisition establishes
  transfer completion. Recovery takeover requires lease expiry plus 60 seconds and
  still retains existing worker file ownership. No healthy leader is force-replaced.
- Worker heartbeats preserve effective task leases during transfer. Workers wait for
  their report channel, retain immutable task inputs and do not restart due to a
  coordinator epoch change. Results arriving during handoff keep their original token.
- Curated summary, decisions, selected scrubbed request excerpts, answered questions,
  approvals, blockers and recent events survive account/computer changes. Raw private
  turns, native thread IDs, authentication and hidden model state are not checkpointed.
- Private pending inputs require an explicit safe summary before handoff. Preparation
  freezes new shared/model activity; later input stays local and is labeled untransferred.
  Local unshared drafts are retained before restore. Interrupted native approvals are
  reissued rather than copied to another account.
- A local private request/receipt inbox supports one external handoff command while
  chat runs. Receipts are atomic/idempotent; explicit stopped-process recovery archives
  an interrupted inbox. A committed remote offer remains valid after local journal failure.

Primary files: `tools/agents/{coordinator,checkpoint,handoff-contracts,leadership,github,
handoff-request,chat,worker,cli,state}.ts`, typed contracts, agent role, the optional
addon README and [three-computer runbook](../guides/ORCHESTRATION.md).

## Actual checks

- Full `npm test`: **275 passed; one opt-in Supabase service test skipped**.
- Final affected tests: coordinator/handoff **31 passed**; GitHub transport **19 passed**,
  including rejection of credential-pattern reports before posting.
- `npm run check`: strict TypeScript, ESLint, catalog validation and docs links passed.
- `npm run format:check`: passed. Build-generated Next declarations were restored.
- `npm run build`: passed after repeating the identical build once for the existing
  Next.js security advisory reminder; dependency versions were unchanged.
- `npm run test:browser`: **8 passed** with the workspace headless Chromium.
- Offline CLI help includes handoff/coordinate/takeover; `simulate --offline` passed.
- Standalone addon export: **24 managed files / 17 TypeScript runtime files** copied
  into a minimal npm ESM app while preserving its MVP file, AGENTS and existing script.
  Clean `npm install` and `npm ci`, exported help and offline simulation passed with
  only target-local dependencies, no symlinks and no unpublished workspace imports.
  The final source refresh repeated help/simulation without reinstalling unchanged deps.
- Existing five-recipe export/adoption evidence from ORCH-01 remains in
  [the earlier verification](ORCHESTRATION_VERIFICATION.md); project-generator/module
  code and dependency versions were not changed in this extension.

Mocks cover A→B→C→A, simultaneous CAS takeover, healthy/early takeover rejection,
expired takeover, stale reconnect/writes, checkpoint faults, worker completion during
transfer, context/approval continuity, local draft backup and privacy. Windows local
filesystem/process checks used the normal host outside restricted sandbox ACLs.

## Remaining limits and operator steps

Real three-account/laptop handoff, live GitHub task/lease mutations, model entitlement,
usage exhaustion and production integration are **not live verified**. Native worker
children remain disabled as before. The existing pinned Next.js advisory still needs
separate remediation; a successful build retry does not fix it.

The first v1→v2 migration requires the original coordinator and all worker runtimes
to be upgraded at a reviewed task boundary. Later v2 transfers preserve healthy
workers. This cannot retrofit checkpoint authority into an already running v1 process.
Shared history/capacities are bounded and failures are explicit. GitHub repository
write permissions remain the team trust boundary; manual force edits require reconciliation.

On the outgoing computer: `npm run agents -- handoff --to agent-b`.
On B using its own accounts: `npm run agents -- coordinate --resume`.
For a crash: `npm run agents -- takeover` after the displayed expiry/safety window.
Follow the runbook's low-risk private three-computer rehearsal before event reliance;
keep human merge/deployment gates and the original MVP checkpoint.
