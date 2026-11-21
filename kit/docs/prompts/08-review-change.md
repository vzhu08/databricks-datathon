# Review an exact change without becoming another writer

Use when: Before integration or when a risky boundary needs a second reading.

Inputs to provide: Commit/range or PR; base revision; acceptance criteria; relevant module contracts; requested review focus; read-only scope.

Read first: [Collaboration](../playbooks/COLLABORATION.md) · [Acceptance](../templates/ACCEPTANCE.md) · [Handoff](../templates/HANDOFF.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Review an exact change without becoming another writer.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Remain read-only. Identify the exact candidate/base commits and inspect its diff plus affected consumers, instructions, contracts and fixtures. Do not assume earlier passing checks cover a changed candidate. Reproduce suspicious behavior with local safe inputs where possible; distinguish observed defects from hypotheses.

Prioritize user-visible correctness, regressions, isolation/security, source attribution, malformed/empty handling, cancellation/idempotency, browser/server boundaries and export independence. Check whether documentation, manifest and verification claims match actual behavior. Avoid style-only findings unless they impede correctness or maintainability materially.

Report only concrete actionable issues with path/line, triggering condition, consequence and a small reproduction or missing behavioral test. State what was reviewed and what was not. If a fix is needed, propose the bounded writer scope; do not start editing under a read-only task. Different tools agreeing is not verification.

Required output and acceptance:
Return prioritized findings followed by inspected revision and evidence/limits. Acceptance: a reviewer can locate and reproduce each defect; absence of findings is not phrased as proof of correctness; local contract tests and live service tests stay distinct. If no actionable issue is found, say so plainly and list remaining verification boundaries.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
