# Draft a credible pitch, judge Q&A and submission

Use when: Implemented capabilities and verification evidence are available.

Inputs to provide: Event rubric/fields; user/problem evidence; actual implementation; verification report; demo timing; sponsor use; contribution/AI credits; output paths.

Read first: [Pitch](../templates/PITCH.md) · [Judge Qa](../templates/JUDGE_QA.md) · [Submission](../templates/SUBMISSION.md)

Copy the prompt below, filling in the inputs and preserving the task's existing authority. It applies to the target project; toolkit templates remain source material unless this task explicitly edits them.

```text
Task: Draft a credible pitch, judge Q&A and submission.
Inputs: [supply the inputs listed above, including actual target and allowed output paths]

Start by reading the target repository's AGENTS.md, CLAUDE.md where applicable, relevant scoped instructions, the task card and current diff. Identify the checkout, branch, base commit, allowed paths and authoritative ownership board. Preserve unrelated changes. A generated project uses its own instructions and docs/kit/SELECTED_MODULES.md, not stale toolkit paths.

Honor the supplied time/token/case/latency limits; do not invent a 24-hour toolkit deadline or a target number of agents. Default external spending is zero. A configured key or coding-assistant subscription is not authorization to spend, publish, deploy, send real messages or mutate a remote account. Reuse explicit authority already recorded for this task; keep independent local work moving when one action is unavailable. Never print secrets. Mark synthetic, cached, replayed and live results accurately.

Read the actual implementation and latest verification record before making claims. Draft adaptable two-minute and three-minute scripts built around a user's painful moment, the demonstrated workflow, one distinctive technical behavior and its evidence. Reserve time for the real result rather than a long architecture tour. Treat durations as rehearsal targets until measured.

Explain what was built during the event versus reused from the kit or other sources. Accurately name sponsor/provider usage, dataset licenses, AI/tool assistance, limitations and future work. Do not turn configured adapters into claims of live verification, describe synthetic data as real users, invent traction, claim guaranteed accuracy or imply a prerecorded backup is live.

Prepare concise answers about architecture, contracts, security/privacy, evaluation baseline, costs, scale limits and what would change next. Match the event's actual submission fields, links and eligibility/attribution requirements. This drafting task does not publish or submit externally unless that action has been explicitly authorized.

Required output and acceptance:
Deliver both pitch scripts, a demo cue sheet, evidence-linked judge Q&A and submission draft. Acceptance: every measurable or integration claim cites implemented behavior/evidence or is clearly labeled a target; links and credits are real; the scripts fit the requested story and leave space for the demo. List only actual missing submission inputs.
```

Source constraints: [build prompt](../resources/source/BUILD_PROMPT.txt), especially sections 2, 10–12 and 14–15; [development playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt), sections 1–7. Use current project instructions and source evidence; this reusable prompt does not override them.
