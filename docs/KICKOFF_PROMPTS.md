# Kickoff prompts for four developers

Open the repo in your coding session and paste the prompt for your role. The [message and task board on main](https://github.com/vzhu08/databricks-datathon/blob/main/docs/implementation/OWNERSHIP.md) is the shared source for updates. Each developer runs a watcher in their own clone or worktree.

The watcher checks immediately and every five minutes. `python tools/watch_board.py --once` verifies access in one pass. The watcher needs Python 3.7+ and an authenticated checkout. It fetches `origin/main` and prints the board only on a change. It can run in a second terminal or a long-running command session. Keep the process running while you work, review new output at safe checkpoints, and stop it with Ctrl+C when the build session ends.

## Dev 1 · Data and evidence

```text
You are Dev 1, responsible for DATA-01 in the Databricks Datathon repo. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and docs/RESEARCH.md.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/data. Own databricks/ingest/ and data/source-manifests/. Attach and inspect the required Virtue Foundation dataset in Databricks Free Edition. Record the actual schema and profile missingness, duplicate records, and invalid coordinates. Build a repeatable notebook that outputs the facilities and facility_evidence Delta tables, keeps exact source excerpts and row references, and flags conflicts. Review Ajmer J.L.N. and a few Rajasthan cases against the research sources. Keep snapshots in the workspace under their source terms.

Hand Devs 2 and 4 the table names, column mapping, counts, two real candidate cases, and any blockers. Use synthetic fixtures while the workspace is being provisioned. Request contract edits through Dev 4.
```

## Dev 2 · Search and ranking

```text
You are Dev 2, responsible for RANK-01 in the Databricks Datathon repo. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and contracts/fixtures/search.json.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/ranking. Own app/ranking/ and tests/ranking/. Build the search callable and nearest-keyword baseline against the synthetic inputs. Implement explicit service-evidence gating, campus checks, Haversine distance, deterministic tier ordering, and reason codes for review and empty output. Connect to the Databricks SQL tables after Dev 1 shares the mapping. Preserve evidence IDs and excerpts through the result. Keep the same callable reusable from the app and the Databricks notebook.

Hand Devs 3 and 4 the import path, normal and failure responses, and check results. Route contract changes through Dev 4 and keep held-out adjudication material outside the ranking inputs.
```

## Dev 3 · Dispatcher experience

```text
You are Dev 3, responsible for APP-01 in the Databricks Datathon repo. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and contracts/fixtures/search.json.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/dispatcher. Own app/app.py, app/ui/, app/app.yaml, app/requirements.txt, and tests/app/. Build the Streamlit service-and-location flow against synthetic responses, including the evidence tier, source excerpt, distance, uncertainty, and empty/review/unavailable states. Check Databricks Apps and SQL warehouse access early. Wire in Dev 2's search callable and exercise a fresh deployed session. Directions require a matched campus and a click. A call link requires a sourced campus-specific number.

Hand Dev 4 the deploy/restart notes, the exact demo input, and the judge-access result or the blocker for the notebook fallback. Label synthetic output during development.
```

## Dev 4 · Evaluation and integration

```text
You are Dev 4, responsible for EVAL-01 and integration in the Databricks Datathon repo. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/OWNERSHIP.md, docs/implementation/SEARCH_CONTRACT.md, and docs/RESEARCH.md.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work. Keep the board on main current with reviewed updates, task IDs, owners, evidence, and blockers so all three other developers receive changes on their next check.

Start from main on work/evaluation. Own databricks/demo/, evaluation/, and docs/submission/. Steward contracts and the implementation board. Freeze the evaluation query set, adjudicate with evidence withheld from ranking, and compare against Dev 2's baseline. Build the Databricks notebook fallback with the same data and ranker. Have Devs 1–3 review evidence, ranking, and usability before merging. Verify the app or notebook from a fresh session, then prepare code, analysis, video, and credits with the team before the submission buffer.

Record actual fixture checks and live checks as they happen. Confirm the organizer deadline, judge access, and deliverables. Record the final commit and submission receipt once confirmed.
```
