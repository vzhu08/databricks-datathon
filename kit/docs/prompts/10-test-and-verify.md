# Verify contracts, standalone exports and the real user path

Use when: After implementation, before marking Verified.

Inputs to provide: Candidate/current-main revision; selected modules/recipe; acceptance plan; target environments; time/case budget; allowed scratch paths; approved live checks.

Read first: [Testing](../guides/TESTING.md) · [Test Plan](../templates/TEST_PLAN.md) · [Acceptance](../templates/ACCEPTANCE.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Verify contracts, standalone exports and the real user path.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Build a risk-based verification plan from the changed behavior. Use existing checks before adding new tests. Cover normal, important failure, meaningful empty/edge behavior and actual runtime contract agreement. For documents inspect exact citation spans/UTF-16 offsets; for auth use distinct users; for jobs exercise state transitions/retry/cancel; for webhooks signatures/replay; for streams parsing/cancellation.

For toolkit work run relevant module tests plus configured type/lint/catalog/docs checks and affected production builds. For generated apps use their own scripts. Verify a generated selected composition outside the toolkit directory with its own install/lockfile, imports, assets and docs. For adoption, verify a working baseline route survives, dry-run/conflicts are safe and re-running is idempotent.

Exercise the actual UI path in a fresh browser session when available, including recovery and cleanup. Browser automation is not proof that a physical microphone/camera or another browser works. Ordinary checks use fixtures/local services only; live/native/deployment checks require their actual prerequisites and authority. Record skipped checks as skipped, with the next exact command or setup action.

Required output and acceptance:
Deliver a verification record containing revision, environment, commands, observed outputs, pass/fail/skip and scope. Counts come from execution, never estimates. Acceptance: Merged and Verified are separate, source/fixture/live provenance is explicit, and every important claim has an observable test or a named remaining limitation. Do not declare production-ready from a successful build.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
