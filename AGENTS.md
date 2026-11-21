# Working on the Datathon

- Use GitHub repository issues and the message board on `main` at `docs/implementation/OWNERSHIP.md` as the only team communication channels. Record assignments, review requests, operator questions, decisions, blockers and handoff receipts there. Link PRs and technical evidence from the relevant issue. This standard applies to all team members and their coding chats.

- Start with `docs/implementation/PLAN.md`, the current board on `origin/main` at `docs/implementation/OWNERSHIP.md`, and your prompt in `docs/KICKOFF_PROMPTS.md`.
- Apply all new work to the full Indian Virtue Foundation snapshot. The pinned facilities table has 10,088 original rows and 10,077 distinct upstream IDs. Preserve every row, including records with missing geography or service evidence. Use the [national acceptance criteria](docs/implementation/PLAN.md) when opening tasks, reviewing PRs and reporting results.
- Select new datasets for repeatable, authorized bulk use across India. Record geographic scope, usable join fields, provenance, reuse terms and the national coverage gain or gap the source can measure. Close or redirect standalone state, district and campus investigations. Use small samples only for quality checks of outputs drawn from the nationwide run.
- Use the approved source packages and [service-status rules](docs/implementation/SERVICE_STATUS.md). A jurisdiction-specific source can supplement a nationwide run with documented scope and measured incremental coverage. Preserve all three service decisions for every original occurrence.
- Oliver (`oliverchennn`) leads integration and owns A/D. Andrew owns C, Vincent (`vzhu08`) owns B, and Ayush owns E. Read the board on current `main` before starting an assignment or merging. Preserve contributor branches and work within the listed paths.
- Use one task branch per owner. Write within the paths on the board. The integration lead edits the board, shared contract, and shared fixtures after coordinating with their consumers. Leave a handoff with the branch or PR, checks, and blockers.
- Use synthetic fixtures in Git. Keep Marketplace rows, partner source snapshots, workspace credentials, and patient or incident details out of the repository. Preserve source provenance in Databricks and follow source terms for any public excerpts or artifacts.
- Preserve the full upstream kit under `kit/`. Consult its scoped instructions only if working on the kit itself.
- Report fixture checks, live Databricks checks, and submission status separately. Record results in the board as the work progresses.
