# Reusable agent prompts

Choose one bounded prompt for the current task. Replace its input block with actual paths, ownership, acceptance and budgets. Read the target repository's instructions first; these prompts do not grant extra write scope, external spending, deployment or messaging authority. Existing explicit authorization remains valid, so do not repeat permission requests for work it already covers.

For a new hackathon project, a useful sequence is discovery → brief → module selection → bootstrap/adopt → bounded implementation → verification → evaluation → rehearsal → pitch. Review, debugging and handoffs can occur whenever needed. The sequence is guidance, not a compulsory approval workflow or a fabricated toolkit deadline.

| Prompt                                                                                | Use when                                                                   |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| [Discover the event and current project](01-discover-requirements.md)                 | Before choosing an idea or editing code.                                   |
| [Turn the rubric into a project brief and execution plan](02-brief-and-build-plan.md) | After initial discovery, before implementation lanes diverge.              |
| [Select the smallest useful module composition](03-select-modules.md)                 | For a concrete workflow, before creating or adopting code.                 |
| [Bootstrap a selected standalone project](04-bootstrap-project.md)                    | When a new project has been authorized.                                    |
| [Add a capability without breaking an existing app](05-adopt-existing.md)             | For an existing working project.                                           |
| [Implement or extend one bounded capability](06-build-module.md)                      | When a task card and stable contract are Ready.                            |
| [Build the frontend while backend work proceeds](07-frontend-from-fixtures.md)        | When shared normal/error/empty fixtures exist.                             |
| [Review an exact change without becoming another writer](08-review-change.md)         | Before integration or when a risky boundary needs a second reading.        |
| [Debug a failing integration boundary](09-debug-boundary.md)                          | When one real user path fails or disagrees with its contract.              |
| [Verify contracts, standalone exports and the real user path](10-test-and-verify.md)  | After implementation, before marking Verified.                             |
| [Evaluate output quality and cost honestly](11-evaluate-capability.md)                | For comparing a baseline with a changed AI/retrieval/ranking capability.   |
| [Rehearse the actual judge flow and deployment](12-demo-and-deployment.md)            | After a usable core path exists and before submission.                     |
| [Draft a credible pitch, judge Q&A and submission](13-pitch-and-submission.md)        | When implemented capabilities and verification evidence are available.     |
| [Resume after context reset or switch coding tools safely](14-resume-and-handoff.md)  | When continuing from a handoff, or handing an active task to another tool. |
| [Clean the demo safely and promote reusable improvements](15-post-event-cleanup.md)   | After the event or after a completed local iteration.                      |

Each prompt specifies its inputs, relevant real project/template files, observable outputs, acceptance evidence and operating limits. They default to local/fixture checks with zero external API spending. A live test needs the operator's configured test account and explicit request/token/case/concurrency or spending limits; unknown prices remain unknown. Credentials are referred to by variable name only.

In generated projects, templates are copied under `docs/` and selected-module guidance lives at `docs/kit/SELECTED_MODULES.md`. In this toolkit the template sources live under [docs/templates](../templates/) and maintenance instructions start with [AGENTS.md](../../AGENTS.md). Do not overwrite toolkit templates while filling an individual project's documents. Create code with the catalog/CLI so selected snapshots preserve source revisions and dependency closure.

Source coverage: the [build prompt section 10](../resources/source/BUILD_PROMPT.txt) requests rubric planning, selection, bootstrap, adoption, bounded implementation, shared-fixture frontend work, exact-change review, boundary debugging, evaluation, deployed demo checks, submissions, context resumption and tool handoffs. These 15 prompts cover those uses plus discovery, testing and post-event cleanup, while preserving the [source playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt) ownership and evidence rules.
