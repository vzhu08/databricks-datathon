# Bootstrap a selected standalone project

Use when: A new project has been authorized.

Inputs to provide: New target path; chosen starter/module IDs; ownership; desired local port; already-approved account/deployment actions, if any.

Read first: [Create](../start-here/CREATE.md) · [Quickstart](../templates/QUICKSTART.md) · [Acceptance](../templates/ACCEPTANCE.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Bootstrap a selected standalone project.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Inspect the destination before writing. Do not replace an existing project under a new-project command. From the kit, inspect the chosen starter/modules and use npm run kit -- create <target> --starter <id> --modules <comma-separated-ids> with the agreed choices. Omit the modules flag if the chosen recipe already supplies the intended closure. Preserve the generated source revision and hashes in kit.project.json.

Move into the generated project and use its own README and package scripts. Install reproducibly with the generated lockfile, run doctor and relevant checks, then exercise the actual local input-to-result path. Inspect emitted AGENTS.md/CLAUDE.md, imports, environment examples, docs and assets. Ensure there are no unpublished workspace references, toolkit symlinks, absolute toolkit paths or access to omitted modules.

Test independence outside the toolkit workspace, using an authorized scratch directory and no borrowed node_modules. Select Python or services only when the requested recipe needs them. Configure secrets through ignored files or the operator's existing mechanism; never paste values into a report.

Required output and acceptance:
Return the standalone project's path, selected closure/source revision, exact install/run/check commands, observed core result and separate skipped/live prerequisites. Acceptance: a fresh local project installs, builds and runs independently; disabled optional modules do not require keys or make network calls; generated instructions point only to included real files. If one step fails, keep its logs concise, repair within scope and report the actual final state.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
