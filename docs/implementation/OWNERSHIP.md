# Team message and task board

This board is authoritative on `origin/main`. Each developer reads it at kickoff and every five minutes while working. Oliver maintains it and appends agreed updates. Post proposed updates and handoffs in the task PR for Oliver to record. Work on the assigned branch and send changes through a PR.

## Latest messages

| When (ET) | From | Applies to | Update |
| --- | --- | --- | --- |
| Nov 21 · kickoff | Repo setup | Everyone | Check your assignment, start the board checker, and read the search contract. Begin with the first task in your kickoff prompt. |
| Nov 21 · first pass | Repo setup | Everyone | [First-pass brief](../FIRST_PASS_PROMPT.md) sets the scope. Use only Virtue Foundation nationwide for dialysis, MRI, and trauma care. |
| Nov 21 · team assignments | Repo setup | Everyone | Oliver leads orchestration. Vincent owns the core search and warehouse adapter. Ayush owns the preparation notebook. Andrew owns the UI/UX in Claude Max and coordinates through this board and PRs. |

## Task ownership

| ID | Owner | Branch | Write scope | Start from | Deliverable and handoff | State |
| --- | --- | --- | --- | --- | --- | --- |
| DATA-01 | Ayush (`ayushrgupta906`) · Data preparation | `work/data` | `databricks/ingest/`, `data/source-manifests/` | Marketplace access and contract | Configurable preparation notebook, real column mapping, campus checks, and prepared table handoff to Vincent | Ready |
| RANK-01 | Vincent (`vzhu08`) · Core search | `work/ranking` | `app/ranking/`, `app/data_access/`, `tests/ranking/`, `tests/data_access/` | Synthetic search fixtures | Matcher, location resolver, ranking, warehouse adapter, and regression tests. Hand the callable to Andrew and Oliver | Ready |
| APP-01 | Andrew (`andrewhgu`) · UI and UX | `work/search-ui` | `app/app.py`, `app/ui/`, `app/app.yaml`, `app/requirements.txt`, `tests/app/` | Synthetic search fixtures | Streamlit inputs, ambiguity flow, results cards, and empty or error states. Hand the verified flow to Oliver | Ready |
| EVAL-01 | Oliver (`oliverchennn`) · Orchestration and integration | `work/evaluation` | `databricks/demo/`, `evaluation/`, `docs/submission/` | Test contract and event brief | Coordinate the three lanes, verify the real Jaipur flow and deployed app when available, and own the submission artifacts | Ready |

Oliver stewards `contracts/`, `docs/implementation/`, and `docs/KICKOFF_PROMPTS.md`. Ayush reviews source provenance and campus preservation. Vincent reviews matching and ranking correctness. Andrew reviews the user flow. Oliver coordinates cross-role edits and shared Databricks resources with their owners.

Use `Ready`, `In progress`, `Review`, `Verified`, or `Blocked`. For each update, include task ID, owner, what changed, and the next action. When handing off, include branch or PR, commit SHA, exact check and result, and any blocked dependency.
