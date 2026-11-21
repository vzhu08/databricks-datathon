# Build the frontend while backend work proceeds

Use when: Shared normal/error/empty fixtures exist.

Inputs to provide: Named route/page/component scope; wire contracts and fixture paths; UX acceptance; accessibility/device constraints; ownership of backend files.

Read first: [Contracts](../architecture/CONTRACTS.md) · [Api Contract](../templates/API_CONTRACT.md) · [Acceptance](../templates/ACCEPTANCE.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Build the frontend while backend work proceeds.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Read the shared schemas and representative fixtures first. Build only the assigned frontend scope; backend ownership remains separate. Use the exact same request/response/error shapes at runtime. Mark fixture or replay data visibly and keep development-only controls out of the exported product flow.

Implement the full requested interaction: idle, validation, loading/progress, cancellation, normal result, empty result, useful error and retry. Retain state only for the source/request it belongs to; reset stale edits, streams and citations when that source changes. Validate saves without discarding invalid drafts. Render user text as text, and source highlights only from verified source IDs and exact offsets.

Use existing UI tokens/components where they fit. Check labels, keyboard focus, contrast, responsive layout and cleanup of timers/media/subscriptions. Integrate a real backend response as soon as available and test its behavior against the fixture assumptions. Do not solve a mismatch by silently weakening the client schema or fabricating fields.

Required output and acceptance:
Deliver the page/components, a fixture-driven smoke path, screenshots or browser evidence when available, and an explicit list of backend assumptions. Acceptance: normal and important recovery paths work, source selection belongs to the displayed result, canceled/stale requests cannot replace current state, and no secret/server import crosses the browser boundary. Hardware and browser combinations not exercised remain unverified.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
