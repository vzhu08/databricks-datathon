# Clean the demo safely and promote reusable improvements

Use when: After the event or after a completed local iteration.

Inputs to provide: Exact cleanup targets; retained artifacts; project/source revisions; useful changes; active owners; authorization for deletion or publication.

Read first: [Post Event Review](../templates/POST_EVENT_REVIEW.md) · [Maintenance](../guides/MAINTENANCE.md) · [Updating](../guides/UPDATING.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Clean the demo safely and promote reusable improvements.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Inventory the named project's generated files, temporary caches, demo namespaces, worktrees, local processes and retained outputs. Inspect Git status and ownership before deleting anything. Separate reversible local cleanup from destructive deletion, remote data changes and publication; perform only the authority already given. Never treat the entire parent workspace, production database or unrelated worktrees as a demo target.

Use the kit's scoped reset operation where appropriate and verify idempotence. Preserve private data according to its retention policy and keep secrets out of reusable fixtures. Record what caused waiting, integration failures, review bottlenecks, weak acceptance checks and actual demo surprises. Measure useful accepted capabilities rather than commits or agent count.

Compare downstream customizations with their kit.project.json source revision/hashes. Propose only generalizable improvements for canonical modules, with provenance, public API compatibility, dependency implications, synthetic fixtures and behavioral tests. Assign a separate scoped module task rather than overwriting imported code or publishing a project wholesale. Keep third-party notices and event attribution.

Required output and acceptance:
Return a cleanup log with exact targets and verification, retained artifacts, POST_EVENT_REVIEW and a prioritized promotion plan. Acceptance: unrelated work and active writers are untouched; destructive/remote actions are explicit; reusable changes have evidence and provenance; the next iteration has a smaller, clearer set of improvements rather than a speculative framework rewrite.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
