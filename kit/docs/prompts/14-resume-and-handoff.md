# Resume after context reset or switch coding tools safely

Use when: Continuing from a handoff, or handing an active task to another tool.

Inputs to provide: Task ID; handoff/checkpoint; checkout/branch; authoritative board; last known commits/checks; allowed paths; next tool if switching.

Read first: [Handoff](../templates/HANDOFF.md) · [Task Card](../templates/TASK_CARD.md) · [Collaboration](../playbooks/COLLABORATION.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Resume after context reset or switch coding tools safely.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Read the handoff, current repository instructions, task card, source diff and authoritative ownership state. Identify what is completed, accepted, still being edited, blocked and genuinely unverified. Preserve the original objective and subsequent corrections. Do not restart the design or reimplement work merely because earlier context is unavailable.

Confirm the actual branch/HEAD and compare with the handoff's base/result commit. Investigate any difference before editing. Reuse an appropriate assigned checkout; never reset/rebase an active writer's checkout. Worktrees isolate files, not database state, ports, secrets or deployments.

When switching Codex/Claude Code, stop the original writer, preserve a task checkpoint or patch, and update the shared handoff before the new writer starts. Keep AGENTS.md canonical and use CLAUDE.md import where applicable. A tool switch does not create permission to edit shared files, push, merge or deploy. Continue the next bounded authorized task; route specific shared changes through the steward.

Required output and acceptance:
Output a short recovered-state summary and then perform the next in-scope step when authorized. Before ending, refresh task status, branch/commit, changed files, behavior, exact checks/results, contract/env changes, limitations and next command. Acceptance: a fresh agent can continue without this chat; stale board copies do not establish ownership; Merged, Verified and deployed state remain distinct.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
