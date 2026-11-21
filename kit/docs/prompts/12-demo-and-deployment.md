# Rehearse the actual judge flow and deployment

Use when: After a usable core path exists and before submission.

Inputs to provide: Judge path; exact deployed URL/revision or local-only target; demo duration; fresh-session procedure; reset/rollback authority; permitted backup policy; deadline/time zone.

Read first: [Demo Runbook](../templates/DEMO_RUNBOOK.md) · [Deployment Runbook](../templates/DEPLOYMENT_RUNBOOK.md) · [Deployment](../guides/DEPLOYMENT.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Rehearse the actual judge flow and deployment.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Inspect the runbook and identify the deployment revision rather than assuming local main is live. Prepare the exact sample input, account state, environment names, callback URLs, reset target and expected output. Verify the judge flow from a fresh session, including loading, one relevant failure/retry, source evidence and the final usable artifact.

Deploy only when existing task authority covers that exact target; otherwise finish the reviewable local build/runbook and report the remaining action. Do not switch hosting providers or create paid services implicitly. Verify server/browser connectivity, persistent-worker placement and service readiness for the chosen composition. Keep a known-good revision and a concrete rollback/smoke procedure.

Rehearse to the supplied duration, measuring observed latency rather than promising it. Prepare a permitted backup recording or fixture/replay fallback with an unmistakable label. Reset only the named local/demo namespace and preserve production/private data. Verify submission fields and receipt/status; leave the agreed deadline buffer. An architecture/feature freeze means repair and convergence, not a new stack or feature expansion.

Required output and acceptance:
Return a step-by-step timed demo runbook, observed fresh-session evidence, deployment SHA/URL when verified, reset/rollback instructions and explicit fallback labels. Acceptance: another teammate can execute the same judge path; every demo claim maps to actual live behavior or disclosed evidence; unrun deployment/hardware/provider checks are separately listed.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
