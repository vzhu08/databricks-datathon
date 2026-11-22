# CMU × Databricks Datathon · Fall 2026

Build a facility finder for community health workers in India. The first pass uses the Virtue Foundation dataset to find dialysis, MRI, or trauma care near a city, PIN code, or coordinates. The result shows nearby facilities, the text behind the match, and which details still need confirmation.

## Start here

1. Oliver leads the nationwide facility-validation run. Process all **10,088 original Virtue Foundation rows** at Delta version 0. Report identity and service coverage across India and by state/UT, including records with missing information. The [implementation plan](docs/implementation/PLAN.md) defines the denominator and release checks.
2. Read the [current team board](docs/implementation/OWNERSHIP.md) and [kickoff prompts](docs/KICKOFF_PROMPTS.md). Oliver owns integration, merges and release, Vincent leads data acquisition and refinement, Andrew owns the demo UI/UX, and Developer D covers the independent replay check. Coordinate through repo issues and the board.
3. The [search contract](docs/implementation/SEARCH_CONTRACT.md) and its synthetic fixtures remain the baseline app interface. The acquisition sprint adds five evidence tables without silently changing ranking or the UI. Real source snapshots and Marketplace rows stay outside Git.

The launch target is a Streamlit app on Databricks Free Edition. The organizer lists Sunday, November 22 at **12:30 p.m. ET** as the tentative deadline for code, analysis, and video. The team's submission target is **10:00 a.m. ET** ([Oliver's deadline update](https://github.com/vzhu08/databricks-datathon/issues/223#issuecomment-7076669521)). [Event schedule](https://cmudsc.com/datathon-fall2026/) · [Challenge brief](https://docs.google.com/document/d/e/2PACX-1vQxhDNQmgZhPgjG0M6LCb_UXNV8CJryqBNQQuqWfIg_dm40ZU1AYAXzZKViC6haFoCmLNiRVfUSBMjf/pub)

## Hackathon Kit

[`kit/`](kit/README.md) contains the complete MIT-licensed upstream snapshot at [`22a5f44`](https://github.com/oliverchennn/hackathon-kit/commit/22a5f44a27375e88ac2cd1754f6976704f725bc5). Start with its [orchestration guide](kit/docs/guides/ORCHESTRATION.md), [collaboration playbook](kit/docs/playbooks/COLLABORATION.md), and [templates](kit/docs/templates/). The Datathon uses the kit's ownership, contracts, handoff, and verification practices.
