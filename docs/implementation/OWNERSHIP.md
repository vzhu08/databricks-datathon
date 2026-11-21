# Team message and task board

This board is authoritative on `origin/main`. Each developer reads it at kickoff and every five minutes while working. Dev 4 maintains it and appends updates after they are agreed. Post proposed updates and handoffs in the task PR for Dev 4 to record. Work on the assigned branch and send changes through a PR.

## Latest messages

| When (ET) | From | Applies to | Update |
| --- | --- | --- | --- |
| Nov 21 · kickoff | Repo setup | Everyone | Claim one of the four roles with the team. Start the board checker and read the search contract. Begin with the first task in your kickoff prompt. |
| Nov 21 · first pass | Repo setup | Everyone | [First-pass brief](../FIRST_PASS_PROMPT.md) sets the scope. Use only Virtue Foundation nationwide for dialysis, MRI, and trauma care. Dev 4 handles integration in a separate session while Devs 1–3 use the orchestrator’s worker slots. |

## Task ownership

| ID | Owner | Branch | Write scope | Start from | Deliverable and handoff | State |
| --- | --- | --- | --- | --- | --- | --- |
| DATA-01 | Dev 1 · Data and evidence | `work/data` | `databricks/ingest/`, `data/source-manifests/` | Marketplace access and contract | Configurable preparation notebook, real column mapping, campus checks, prepared table and sample results for Devs 2/4 | Ready |
| RANK-01 | Dev 2 · Search and ranking | `work/ranking` | `app/ranking/`, `tests/ranking/` | Synthetic search fixtures | Service matcher, location resolver, ranking callable, and regression checks. Hand contract and callable to Devs 3/4 | Ready |
| APP-01 | Dev 3 · Search interface | `work/search-ui` | `app/app.py`, `app/ui/`, `app/app.yaml`, `app/requirements.txt`, `tests/app/` | Synthetic search fixtures | Streamlit flow, warehouse setup, and judge-access check. Hand app URL or exact blocker to Dev 4 | Ready |
| EVAL-01 | Dev 4 · Evaluation and integration | `work/evaluation` | `databricks/demo/`, `evaluation/`, `docs/submission/` | Test contract and event brief | Real Jaipur review when available, end-to-end checks, deploy notes, and submission artifacts. Review and integrate the other three lanes | Ready |

Dev 4 stewards `contracts/`, `docs/implementation/`, and `docs/KICKOFF_PROMPTS.md`. Dev 1 reviews provenance and matching. Dev 2 reviews ranking correctness. Dev 3 reviews the user flow. Dev 4 coordinates cross-role edits and updates shared Databricks resources with their owners.

Use `Ready`, `In progress`, `Review`, `Verified`, or `Blocked`. For each update, include task ID, owner, what changed, and the next action. When handing off, include branch or PR, commit SHA, exact check and result, and any blocked dependency.
