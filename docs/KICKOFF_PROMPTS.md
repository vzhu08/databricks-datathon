# Kickoff prompts for four developers

Open the repo in your coding session and paste the prompt for your role. The [message and task board on main](https://github.com/vzhu08/databricks-datathon/blob/main/docs/implementation/OWNERSHIP.md) is the shared source for updates. Each developer runs a watcher in their own clone or worktree.

The watcher checks immediately and every five minutes. `python tools/watch_board.py --once` verifies access in one pass. The watcher needs Python 3.7+ and an authenticated checkout. It fetches `origin/main` and prints the board only on a change. It can run in a second terminal or a long-running command session. Keep the process running while you work, review new output at safe checkpoints, and stop it with Ctrl+C when the build session ends.

## Ayush · Data preparation

```text
Help Ayush (`ayushrgupta906`) complete DATA-01 in Codex. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and docs/RESEARCH.md.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/data. Own databricks/ingest/ and data/source-manifests/. Inspect the configured Virtue Foundation Marketplace table in Databricks Free Edition. Record its actual schema and profile missingness, duplicate records, and invalid coordinates. Build a repeatable prep notebook with a configurable source table. Retain evidence wording, original field mapping, record URLs, city, state, PIN, and campus identity. Check that same-name campuses remain distinct. Use only Virtue Foundation for the first pass.

Hand Vincent the prepared table name, column mapping, and campus checks. Tell Oliver what is verified and flag any Marketplace or workspace blocker. Use synthetic fixtures while workspace access is being arranged. Ask Oliver to review shared contract edits.
```

## Vincent · Core search and ranking

```text
Help Vincent (`vzhu08`) complete RANK-01 in Codex. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and contracts/fixtures/search.json.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/ranking. Own app/ranking/, app/data_access/, tests/ranking/, and tests/data_access/. Build deterministic matchers for dialysis, MRI, and trauma care. Preserve the best verbatim evidence excerpt and source field. Exclude planned, unavailable, and referred-out claims. Resolve city and state, PIN, or coordinates from the dataset and return choices for ambiguous cities. Use Haversine within a 50 km default radius and sort direct matches by distance. Return indirect leads only when direct matches are empty. Build the parameterized warehouse adapter against Ayush’s prepared table. Keep core logic and the data adapter testable outside Streamlit.

Hand Andrew the search callable, warehouse environment names and dependency requirements, and example responses for each UI state. Hand Oliver regression results and the tested revision. Route shared contract changes through Oliver.
```

## Andrew · UI and UX

```text
Help Andrew (`andrewhgu`) complete APP-01 in his Claude Max session. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and contracts/fixtures/search.json. Coordinate with Oliver through the shared board and PRs.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work, apply confirmed updates to your scope, and surface blockers in your task PR. If GitHub access fails, report it and do a one-shot check after reconnecting.

Start from main on work/search-ui. Own app/app.py, app/ui/, app/app.yaml, app/requirements.txt, and tests/app/. Own the entire Streamlit UI and UX for a community health worker, including the layout, input labels and validation, ambiguity flow, results, empty states, and errors. Render all three service choices, city/state or PIN or coordinates, a 50 km default with radius expansion, and direct or “Needs confirmation” results. Show verbatim evidence and its field, approximate distance where relevant, record-source links, and unknown availability. Build against synthetic responses, then wire in Vincent’s callable and exercise the app from a fresh session with Oliver.

Hand Oliver the UI verification results, exact demo input, app startup notes, and any access blocker. Label synthetic output during development.
```

## Oliver · Orchestration and integration

```text
Help Oliver (`oliverchennn`) lead orchestration and complete EVAL-01. Open docs/FIRST_PASS_PROMPT.md in the lead conversation. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/OWNERSHIP.md, docs/implementation/SEARCH_CONTRACT.md, and docs/RESEARCH.md.

Before coding, run `python tools/watch_board.py` in a second terminal or persistent command session and verify that the first read succeeds. Keep the checker running so it reads the shared board from origin/main every five minutes for updates and new tasks. Check its output during work. Keep the board on main current with reviewed updates, task IDs, owners, evidence, and blockers so all three other developers receive changes on their next check.

Coordinate Vincent’s and Ayush’s Codex tasks and Andrew’s Claude Max work. Use GitHub PRs and the board for handoffs. Use a separate coding session on work/evaluation for databricks/demo/, evaluation/, and docs/submission/. Steward the shared contract and fixtures. Run dialysis near Jaipur with the real dataset when access is available and inspect the exact excerpts. Verify direct before indirect, ambiguous cities, invalid coordinates, no direct matches, and same-name campuses. Have Ayush review provenance, Vincent review ranking and warehouse integration, and Andrew review the user flow before merging. Verify the deployed app when configured, then prepare code, analysis, video, and credits with the team before the submission buffer.

Record actual fixture checks and live checks as they happen. Confirm the organizer deadline, judge access, and deliverables. Record the final commit and submission receipt once confirmed.
```
