# Kickoff prompts for four developers

Open the repo in your coding session and paste the prompt for your role. The [message and task board on main](https://github.com/vzhu08/databricks-datathon/blob/main/docs/implementation/OWNERSHIP.md) is the shared source for updates. Each developer runs a watcher in their own clone or worktree.

The watcher checks immediately and every five minutes. `python tools/watch_board.py --once` verifies access in one pass. The watcher needs Python 3.7+ and an authenticated checkout. It fetches `origin/main` and prints the board only on a change. It can run in a second terminal or a long-running command session. Keep the process running while you work, review new output at safe checkpoints, and stop it with Ctrl+C when the build session ends.

## Dev 1 · Data and evidence

```text
You are Dev 1, responsible for DATA-01 in the Databricks Datathon repo. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and docs/RESEARCH.md.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/data. Own databricks/ingest/ and data/source-manifests/. Inspect the configured Virtue Foundation Marketplace table in Databricks Free Edition. Record its actual schema and profile missingness, duplicate records, and invalid coordinates. Build a repeatable prep notebook with a configurable source table. Retain evidence wording, original field mapping, record URLs, city, state, PIN, and campus identity. Check that same-name campuses remain distinct. Use only Virtue Foundation for the first pass.

Hand Devs 2–4 the table names, column mapping, counts, and any blockers. Use synthetic fixtures while the workspace is being provisioned. Request contract edits through Dev 4.
```

## Dev 2 · Search and ranking

```text
You are Dev 2, responsible for RANK-01 in the Databricks Datathon repo. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and contracts/fixtures/search.json.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/ranking. Own app/ranking/ and tests/ranking/. Build deterministic matchers for dialysis, MRI, and trauma care. Preserve the best verbatim evidence excerpt and source field. Exclude planned, unavailable, and referred-out claims. Resolve city and state, PIN, or coordinates from the dataset and return choices for ambiguous cities. Use Haversine within a 50 km default radius and sort direct matches by distance. Return indirect leads only when direct matches are empty. Keep the callable testable outside Streamlit.

Hand Devs 3 and 4 the import path, normal and failure responses, and check results. Integrate with Dev 1’s approved row mapping and route shared contract changes through Dev 4.
```

## Dev 3 · Search interface

```text
You are Dev 3, responsible for APP-01 in the Databricks Datathon repo. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and contracts/fixtures/search.json.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/search-ui. Own app/app.py, app/ui/, app/app.yaml, app/requirements.txt, and tests/app/. Build the Streamlit workflow for a community health worker. Render all three service choices, city/state or PIN or coordinates, ambiguous city selection, a 50 km default with radius expansion, and direct or “Needs confirmation” results. Show the verbatim evidence and its field, approximate distance where relevant, record-source links, and unknown availability. Check Databricks Apps and SQL warehouse access early. Wire in Dev 2's search callable and exercise a fresh deployed session.

Hand Dev 4 the deploy/restart notes, the exact demo input, and the judge-access result or recorded blocker. Label synthetic output during development.
```

## Dev 4 · Evaluation and integration

```text
You are Dev 4, responsible for EVAL-01 and integration in the Databricks Datathon repo. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/OWNERSHIP.md, docs/implementation/SEARCH_CONTRACT.md, and docs/RESEARCH.md.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work. Keep the board on main current with reviewed updates, task IDs, owners, evidence, and blockers so all three other developers receive changes on their next check.

Start from main on work/evaluation in a separate coding session. The orchestrator’s three worker slots cover Devs 1–3. Own databricks/demo/, evaluation/, and docs/submission/. Steward contracts and the implementation board. Run dialysis near Jaipur with the real dataset when access is available and inspect the exact excerpts. Verify direct before indirect, ambiguous cities, invalid coordinates, no direct matches, and same-name campuses. Have Devs 1–3 review evidence, ranking, and usability before merging. Verify the deployed app when configured, then prepare code, analysis, video, and credits with the team before the submission buffer.

Record actual fixture checks and live checks as they happen. Confirm the organizer deadline, judge access, and deliverables. Record the final commit and submission receipt once confirmed.
```
