# Implement or extend one bounded capability

Use when: A task card and stable contract are Ready.

Inputs to provide: Task card; module ID; exact allowed/reserved paths; base commit; fixtures; acceptance/checks; runtime limits; shared-change steward.

Read first: [Module Authoring](../guides/MODULE_AUTHORING.md) · [Task Card](../templates/TASK_CARD.md) · [Module Readme](../templates/MODULE_README.md) · [Module Manifest](../templates/MODULE_MANIFEST.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Implement or extend one bounded capability.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Confirm the exclusive file claim in the authoritative board before editing. Use a separate branch/checkout from other active writers; distinct ports and demo data are also needed because worktrees do not isolate external state. Do not spawn extra writers unless authorized and independently scoped.

Implement the smallest complete observable capability against the agreed contract. Validate untrusted boundaries, keep server SDKs/keys out of browser entrypoints, bound uploads/requests/retries/work, and preserve provenance/citations where applicable. Provide a real narrow configured adapter when the task requires one, plus clearly marked deterministic fixtures; never replace a live failure silently with fake success.

Include src, behavior tests for normal/failure/empty cases, synthetic fixtures with provenance, runnable examples/demo.ts, eight-question README and schema-valid module.json. Declare actual runtime dependency closure. Ask the steward for exact manifest/lockfile/shared-schema changes rather than editing reserved root files. Record limitations and local/exported/live evidence separately. Run module and affected consumer checks, then inspect the final diff for accidental files.

Required output and acceptance:
Return a reviewable scoped commit or patch, public signatures, changed behavior, requested shared changes, actual checks, unverified prerequisites and next integration action. Acceptance: all task-card outcomes work through their public boundary; an ordinary demo needs no paid credentials; no required adapter is a stub; module metadata and docs agree with code. Do not claim merged/deployed verification from task-branch tests.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
