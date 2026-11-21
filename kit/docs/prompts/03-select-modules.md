# Select the smallest useful module composition

Use when: A concrete workflow, before creating or adopting code.

Inputs to provide: Requested workflow; target framework/package manager; local/live preference; constraints; target path; existing kit.project.json if present.

Read first: [Module Selection](../templates/MODULE_SELECTION.md) · [Architecture](../templates/ARCHITECTURE.md) · [Create](../start-here/CREATE.md) · [Adopt](../start-here/ADOPT.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Select the smallest useful module composition.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Use npm run kit -- search "task words", npm run kit -- list and npm run kit -- inspect <id> from the toolkit. Read only each shortlisted module's minimalRead, contract, fixtures, required environment names and limitations. Treat module.json as the catalog source; do not invent modules or maintained hand-written dependency lists.

Map requirement → capability → rationale → dependency closure → integration changes → failure/empty behavior → check. Compare a credential-free baseline with optional live upgrades. Keep disabled services out of environment validation and exclude unneeded Python, Docker, database or SDK dependencies. Identify route names, CSS/assets, migrations, browser/server boundaries and any credentials by name only.

For an existing project run the read-only kit plan command and inspect conflicts. For a new project choose the actual supported starter. If no supported adapter fits, specify a bounded portable integration or missing module task rather than claiming arbitrary-framework compatibility.

Required output and acceptance:
Produce MODULE_SELECTION and a small architecture/data-flow diagram with exact included paths and checks. Include the command you would run, its dependency closure, expected files, prerequisites and explicit manual work. Acceptance: every selected dependency has a reason; the local judge path needs no paid calls; the plan distinguishes verified compatibility from intended setup and can be reviewed before application.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
