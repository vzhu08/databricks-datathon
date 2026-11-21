# Create a lean project

From the toolkit root, run `npm ci`, then `npm run kit -- create /tmp/my-demo --starter web`. Inspect module metadata before adding capabilities: `npm run kit -- inspect voice`. Add `--modules voice` or choose `document`, `document-python`, `group`, `media`, or `full`. The full recipe is a reference convenience; most hackathons should choose a smaller closure.

Generation writes only an empty target. It preserves canonical modules/ and packages/ import paths, adds project-specific AGENTS.md/CLAUDE.md, environment names, docs and kit.project.json with revision/hashes. Module dependencies are resolved transitively; unrelated SDKs stay out of package.json. Python is exported only with document-python or an explicit export that requires it.

Inside the generated directory, follow README.md, install the exact dependency set, commit package-lock.json, run `npm run check` and `npm run dev`. The standalone app works with the original toolkit unavailable. Recipe interfaces are at /kit. Base web is at /. Readiness checks describe the enabled local path and do not imply configured live services are healthy.

Fill PROJECT_BRIEF, MODULE_SELECTION, OWNERSHIP, API_CONTRACT, TASK_BOARD and DEMO_RUNBOOK before parallel feature work. Review local/live differences and the deployment runbook before connecting real data.
