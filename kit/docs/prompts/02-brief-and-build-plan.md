# Turn the rubric into a project brief and execution plan

Use when: After initial discovery, before implementation lanes diverge.

Inputs to provide: Chosen idea; rubric; deadline/time zone; current repository; owners; runtime/hosting/privacy constraints; allowed planning-output paths.

Read first: [Project Brief](../templates/PROJECT_BRIEF.md) · [Execution Plan](../templates/EXECUTION_PLAN.md) · [Ownership](../templates/OWNERSHIP.md) · [Task Board](../templates/TASK_BOARD.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Turn the rubric into a project brief and execution plan.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Create or update the target project's PROJECT_BRIEF, EXECUTION_PLAN, OWNERSHIP and RISK_AND_CUT_LIST from the supplied evidence. Use the templates as structure, not as prefilled facts. Define one user and one input-to-result judge path, the distinctive capability, success criteria, non-goals and constraints. Map each rubric claim to behavior judges can actually see.

Plan in dependency order: stable contracts and fixtures; thin real end-to-end path; demonstrable differentiator; evaluation and failure handling; rehearsal and submission. Work backward from the actual deadline with a submission buffer. The source playbook's 24-hour schedule is an adaptable event example, not a deadline for building the kit.

Assign Product/UX, Platform/API and Core capability responsibilities to actual people and file sets. Name shared stewards for contracts, manifests/lockfiles, global styling, environment examples, migrations and deployment. Use one authoritative board with Planned, Ready, Running, Review, Queued, Merged, Verified and Blocked. Do not launch writers until their interfaces and exclusive scopes are Ready.

Required output and acceptance:
Deliver a usable project brief, dependency-ordered milestones, real ownership/steward assignments, the first bounded task cards and a cut list. Each task must name its branch/checkout policy, allowed/reserved files, contract, representative fixture, acceptance, checks and integration authority. Acceptance: the first slice can be shown from a fresh session; estimates are labeled targets; no success claim depends on unimplemented or unverified work.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
