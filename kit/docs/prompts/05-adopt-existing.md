# Add a capability without breaking an existing app

Use when: An existing working project.

Inputs to provide: Target path; module IDs; current working route/demo; allowed integration files; dry-run or explicit apply authority.

Read first: [Adopt](../start-here/ADOPT.md) · [Updating](../guides/UPDATING.md) · [Integration Notes](../templates/INTEGRATION_NOTES.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Add a capability without breaking an existing app.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Inspect the target framework, package manager, routes, import aliases, package versions, environment conventions, instruction files, Git diff and prior kit.project.json. Record a baseline check of the current working behavior. Use kit plan and kit add in their read-only/dry-run modes first, even when application has already been authorized, so the proposed change is concrete and conflict-checked.

Present or record exact file, dependency, route, environment, asset and migration changes. Preserve AGENTS.md and CLAUDE.md; propose a short link/merge rather than replacing them. Preserve downstream edits to previously imported snapshots. Refuse automatic changes to unsupported frameworks or conflicting ownership and give actionable manual steps.

Apply only the supported plan within existing authorization, using the explicit --apply switch. Do not use an approval pause for routine reversible work already authorized. Re-run to verify idempotence. Test the original behavior and new behavior together, including a relevant empty/error case. If resolving a conflict requires reserved files, send the exact proposal to their steward and continue independent work.

Required output and acceptance:
Produce integration notes with before/after files, source revision, conflict decisions, actual commands/results and rollback instructions. Acceptance: original routes/instructions/customizations still work; the new module has a real consumer; a second apply adds no duplicates; a modified imported file is preserved or explicitly flagged. Do not report "compatible" solely because files copied successfully.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
