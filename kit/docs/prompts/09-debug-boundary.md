# Debug a failing integration boundary

Use when: One real user path fails or disagrees with its contract.

Inputs to provide: Exact failing action; expected/actual behavior; current revision; sanitized logs; permitted files; failure budget; live authority if already granted.

Read first: [Troubleshooting](../guides/TROUBLESHOOTING.md) · [Api Contract](../templates/API_CONTRACT.md) · [Task Card](../templates/TASK_CARD.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Debug a failing integration boundary.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Reproduce the smallest failing path before editing. Trace browser input → route validation → module/provider/storage → response schema → rendering. Record the first boundary where observed data diverges from the contract, including mode, request ID and source revision without private payloads or secrets.

Check likely causes in order: stale build/configuration; wrong origin/callback or browser/server URL; schema/default/unit mismatch; missing module/service; timeout/cancellation; auth scope/ownership; malformed provider output; stale state. Use existing fixtures and local adapters to separate transport from capability behavior. Do not hide a failure with permissive parsing, unbounded retries, fake results or automatic paid calls.

Make the narrow repair in owned files, add a regression that fails for the original defect, and rerun the affected consumer flow. Coordinate shared schema/dependency/route changes with the steward. If the root cause is outside scope, deliver the exact change needed and continue any independent in-scope diagnosis.

Required output and acceptance:
Provide root cause with evidence, before/after behavior, scoped diff, regression and actual check results. Acceptance: the originally failing user action succeeds or now returns the intended actionable error; neighboring empty/failure behavior remains sound; no secret or private upload appears in logs; unresolved external prerequisites are stated precisely.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
