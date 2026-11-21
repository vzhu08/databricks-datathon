# HUMAN-01: reusable human–AI team workflow

Source: operator-supplied `HUMAN_AI_TEAM_WORKFLOW.md` (2026-10-24).
Branch: `feat/orchestration`; lead owns all edits. Delegated review is read-only.

Outcome: new projects contain `docs/HUMAN_AI_TEAM_WORKFLOW.md`, with working
agent/quickstart/kickoff links. Human accountability and approval owners are
explicitly independent of worker accounts and coordinator transfers.

Scope: workflow template, README and collaboration/kickoff/quickstart links,
the two generated instruction strings in `tools/project.ts`, optional orchestrator
profile/runbook guidance, targeted generator regression and implementation records.
The existing generic template-copy loop is unchanged. Preserve every existing
technical ownership and approval rule, minimal generation, and customized adopted
project documents. No dependencies or runtime orchestration changes.

Acceptance: check links in the kit and an actual generated minimal project; verify
that no orchestration is installed and customized human/agent instructions survive
subsequent module adoption. Run `npm run docs:check`, `npm run check`, the existing
core/adoption tests and the new generated-workflow regression. Record actual results
and skips, then create a scoped commit and update draft PR #1. Main, teammate
branches, live inference, deployment and merge are outside this task.

## Result and verification

Implemented against source revision `3c312b2059788912217dd675c701e7d4176bc66e`.
The supplied workflow retains its schedule, evidence cadence, blocker formats,
approval ownership and feedback loop. An integration note clarifies optional worker
startup, independent human roles and existing runtime authority. The generic
template-copy loop is unchanged; only the generated AGENTS and quickstart strings
were extended. No dependency, lockfile or orchestration runtime changes were made.

Changed files:

- `docs/templates/HUMAN_AI_TEAM_WORKFLOW.md`: supplied playbook plus integration note.
- `README.md`, `docs/playbooks/COLLABORATION.md`,
  `docs/playbooks/DEVELOPMENT_PLAYBOOK.md`, `docs/templates/COLLABORATION.md`,
  `docs/templates/DEVELOPMENT_PLAYBOOK.md`, `docs/templates/QUICKSTART.md`: references.
- `tools/project.ts`: two generated instruction paragraphs.
- `.codex/agents/orchestrator.toml`, `docs/guides/ORCHESTRATION.md`: flexible human
  lanes, actual assignments, independent approval owners and existing controls.
- `tests/project-workflow.test.ts`: actual minimal generation, portable links,
  absence of optional orchestration, and preservation of customized workflow and
  agent instructions on module adoption.
- This task card, `PLAN.md`, `STATUS.md`, `OWNERSHIP.md`: scope and actual evidence.

Checks (2026-10-24):

- `npm run docs:check`: passed, 116 Markdown files / 699 links / zero failures.
- `npm run check`: passed (types, lint, 15-module catalog, documentation).
- `npm run format:check` and `git diff --check`: passed.
- `npx vitest run tests/core.test.ts tests/project-workflow.test.ts tests/orchestration/chat.test.ts`:
  27 passed. The initial sandbox run passed 26 and failed the existing Windows
  junction fixture with EPERM; the same command passed with junction access.
- `npx vitest run tests/orchestration/install.test.ts`: 5 passed.
- Loaded the shipped orchestrator profile through `loadLeadInstructions`: passed;
  human accountability guidance is present and within the loader's size limit.
- The generator regression materialized a minimal project, checked all generated
  Markdown links, compared the copied playbook with the template, checked the four
  unchanged base dependencies and verified preserving adoption. Fixture cleanup
  removes the generated temporary project after the assertions.

The full suite, browser workflows, production builds and clean-install recipe
exports were not repeated for this documentation-only change; prior orchestration
verification is recorded separately. Live three-account/laptop inference and
coordinator transfer remain unverified. No provider calls, remote task dispatch,
merge or deployment occurred. Next action: human review of draft PR #1, followed
by a deliberate three-account rehearsal before event use.
