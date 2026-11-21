# Kickoff prompts for four developers

Open the repo in your coding chat and follow the instructions for your role. Each timer wakes that same chat to read the [message and task board on main](https://github.com/vzhu08/databricks-datathon/blob/main/docs/implementation/OWNERSHIP.md) and start assigned work when the chat is free.

Vincent, Ayush, and Oliver use a scheduled follow-up in their own Codex desktop coding chats. Andrew uses `/loop 5m` in his Claude Code session. Keep the desktop app or Claude Code session running with access to the checkout and GitHub. End the timers when the team submits or the event ends. [Codex scheduled tasks inside a chat](https://learn.chatgpt.com/docs/automations#schedule-a-task-inside-a-chat) · [Claude Code session scheduling](https://code.claude.com/docs/en/scheduled-tasks)

## What happens on each check

1. Read the latest `docs/implementation/OWNERSHIP.md` directly from GitHub `main` or fetch `origin/main` and read the file from that ref. If the read fails, surface the blocker without acting on a stale board.
2. Check updates for your GitHub login. If you have unfinished work, continue it within its existing scope. If you are free, take the first `Ready` task assigned to you whose dependencies are met and whose task ID you have not already started or finished. Record the ID in your chat and **start the work in this turn** within the listed branch and paths.
3. Use one coding session per task. If another session or kit worker is already handling it, leave the task with that session. Report started tasks, changed assignments, and blockers. End the check quietly when nothing has changed and no task is available.

## Ayush · Data preparation

```text
Help Ayush (`ayushrgupta906`) complete DATA-01 in Codex. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and docs/RESEARCH.md.

Create a scheduled follow-up in this same Codex desktop chat every five minutes through the Datathon, ending Sunday, November 22 at 12:30 p.m. ET or when I stop it. Use this as the scheduled prompt: “Apply ‘What happens on each check’ in docs/KICKOFF_PROMPTS.md for ayushrgupta906. Start the next eligible task in this chat when free.” Verify the schedule and do the first board check now.

Start from main on work/data. Own databricks/ingest/ and data/source-manifests/. Inspect the configured Virtue Foundation Marketplace table in Databricks Free Edition. Record its actual schema and profile missingness, duplicate records, and invalid coordinates. Build a repeatable prep notebook with a configurable source table. Retain evidence wording, original field mapping, record URLs, city, state, PIN, and campus identity. Check that same-name campuses remain distinct. Use only Virtue Foundation for the first pass.

Hand Vincent the prepared table name, column mapping, and campus checks. Tell Oliver what is verified and flag any Marketplace or workspace blocker. Use synthetic fixtures while workspace access is being arranged. Ask Oliver to review shared contract edits.
```

## Vincent · Core search and ranking

```text
Help Vincent (`vzhu08`) complete RANK-01 in Codex. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and contracts/fixtures/search.json.

Create a scheduled follow-up in this same Codex desktop chat every five minutes through the Datathon, ending Sunday, November 22 at 12:30 p.m. ET or when I stop it. Use this as the scheduled prompt: “Apply ‘What happens on each check’ in docs/KICKOFF_PROMPTS.md for vzhu08. Start the next eligible task in this chat when free.” Verify the schedule and do the first board check now.

Start from main on work/ranking. Own app/ranking/, app/data_access/, tests/ranking/, and tests/data_access/. Build deterministic matchers for dialysis, MRI, and trauma care. Preserve the best verbatim evidence excerpt and source field. Exclude planned, unavailable, and referred-out claims. Resolve city and state, PIN, or coordinates from the dataset and return choices for ambiguous cities. Use Haversine within a 50 km default radius and sort direct matches by distance. Return indirect leads only when direct matches are empty. Build the parameterized warehouse adapter against Ayush’s prepared table. Keep core logic and the data adapter testable outside Streamlit.

Hand Andrew the search callable, warehouse environment names and dependency requirements, and example responses for each UI state. Hand Oliver regression results and the tested revision. Route shared contract changes through Oliver.
```

## Andrew · UI and UX

Run this once in Andrew’s Claude Code chat, then paste the kickoff prompt below in the same chat.

```text
/loop 5m Apply “What happens on each check” in docs/KICKOFF_PROMPTS.md for andrewhgu. Start the next eligible UI/UX task in this chat when free. Stop this loop when the team submits or by Sunday, November 22 at 12:30 p.m. ET.
```

```text
Help Andrew (`andrewhgu`) complete APP-01 in his Claude Max session. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/SEARCH_CONTRACT.md, and contracts/fixtures/search.json. Coordinate with Oliver through the shared board and PRs.

Use the five-minute /loop in this Claude Code session. Apply “What happens on each check” for andrewhgu and do the first board check now.

Start from main on work/search-ui. Own app/app.py, app/ui/, app/app.yaml, app/requirements.txt, and tests/app/. Own the entire Streamlit UI and UX for a community health worker, including the layout, input labels and validation, ambiguity flow, results, empty states, and errors. Render all three service choices, city/state or PIN or coordinates, a 50 km default with radius expansion, and direct or “Needs confirmation” results. Show verbatim evidence and its field, approximate distance where relevant, record-source links, and unknown availability. Build against synthetic responses, then wire in Vincent’s callable and exercise the app from a fresh session with Oliver.

Hand Oliver the UI verification results, exact demo input, app startup notes, and any access blocker. Label synthetic output during development.
```

## Oliver · Orchestration and integration

```text
Help Oliver (`oliverchennn`) lead orchestration and complete EVAL-01. Open docs/FIRST_PASS_PROMPT.md in the lead conversation. Read AGENTS.md, docs/implementation/PLAN.md, docs/implementation/OWNERSHIP.md, docs/implementation/SEARCH_CONTRACT.md, and docs/RESEARCH.md.

In your Codex desktop integration chat, create a scheduled follow-up that returns to that same chat every five minutes through the Datathon, ending Sunday, November 22 at 12:30 p.m. ET or when I stop it. Use this as the scheduled prompt: “Apply ‘What happens on each check’ in docs/KICKOFF_PROMPTS.md for oliverchennn. Start the next eligible integration task in this chat when free.” Verify the schedule and do the first board check now. Keep the GitHub board current so the other chats can pick up approved assignments on their next check.

Coordinate Vincent’s and Ayush’s Codex tasks and Andrew’s Claude Max work. Use GitHub PRs and the board for handoffs. Use a separate coding session on work/evaluation for databricks/demo/, evaluation/, and docs/submission/. Steward the shared contract and fixtures. Run dialysis near Jaipur with the real dataset when access is available and inspect the exact excerpts. Verify direct before indirect, ambiguous cities, invalid coordinates, no direct matches, and same-name campuses. Have Ayush review provenance, Vincent review ranking and warehouse integration, and Andrew review the user flow before merging. Verify the deployed app when configured, then prepare code, analysis, video, and credits with the team before the submission buffer.

Record actual fixture checks and live checks as they happen. Confirm the organizer deadline, judge access, and deliverables. Record the final commit and submission receipt once confirmed.
```
