# Evaluate output quality and cost honestly

Use when: Comparing a baseline with a changed AI/retrieval/ranking capability.

Inputs to provide: Versioned representative dataset; baseline/candidate config; task metrics; max cases/concurrency; latency target; explicit live usage/spend policy if any.

Read first: [Evaluation Report](../templates/EVALUATION_REPORT.md) · [Datasets And Apis](../resources/DATASETS_AND_APIS.md) · [Testing](../guides/TESTING.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Evaluate output quality and cost honestly.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Define evaluation cases before optimizing the implementation. Include ordinary, difficult, empty, conflicting and failure cases drawn from redistributable synthetic or approved data. Document provenance and units. Choose deterministic metrics where possible: supported citation validity, retrieval recall/rank, hard-constraint satisfaction, schema correctness, task accuracy and latency. Treat an LLM judge as an estimate with its own failure modes.

Run the local baseline first using the kit evaluation runner or module evaluator. Record exact dataset version, source commit, model/provider/prompt version when relevant, case count, concurrency, settings, usage and failures. Keep wall-clock measurements tied to the environment. Use a dated configured price table only when applicable; unknown cost remains unknown.

Live comparisons are opt-in and bounded by explicit cases, concurrency, time and token/request/spending limits. A key alone does not authorize a run. If live access is unavailable, complete the local evaluation and provide a runnable plan without inventing provider results. Do not tune on held-out examples and then report them as independent evidence.

Required output and acceptance:
Produce machine-readable results and a readable EVALUATION_REPORT with baseline comparison, error examples, uncertainty, costs and next measured improvement. Acceptance: every headline score has a denominator and dataset/config provenance; a tiny authored sanity set is not a general quality claim; unsupported citations, infeasible cases and provider errors remain visible.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
