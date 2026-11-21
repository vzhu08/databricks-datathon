# CMU × Databricks Datathon · Fall 2026

Build a facility finder for community health workers in India. The first pass uses the Virtue Foundation dataset to find dialysis, MRI, or trauma care near a city, PIN code, or coordinates. The result shows nearby facilities, the text behind the match, and which details still need confirmation.

## Start here

1. Oliver starts the lead conversation with the [first-pass prompt](docs/FIRST_PASS_PROMPT.md). Vincent owns core search, Ayush owns data preparation, and Andrew owns UI and UX in Claude Max. Oliver coordinates handoffs, integration, and verification.
2. Read the [implementation plan](docs/implementation/PLAN.md) and check your assignment on the [message and task board](docs/implementation/OWNERSHIP.md). Use your [developer kickoff prompt](docs/KICKOFF_PROMPTS.md) to schedule a five-minute board check that returns to your coding chat and starts eligible assignments.
3. Build against the [search contract](docs/implementation/SEARCH_CONTRACT.md) and [synthetic fixtures](contracts/fixtures/search.json). The [research handoff](docs/RESEARCH.md) preserves ideas for later corroboration.

The launch target is a Streamlit app on Databricks Free Edition. The organizer lists Sunday, November 22 at **12:30 p.m. ET** as the tentative deadline for code, analysis, and video. The team's target is **11:45 a.m. ET**. [Event schedule](https://cmudsc.com/datathon-fall2026/) · [Challenge brief](https://docs.google.com/document/d/e/2PACX-1vQxhDNQmgZhPgjG0M6LCb_UXNV8CJryqBNQQuqWfIg_dm40ZU1AYAXzZKViC6haFoCmLNiRVfUSBMjf/pub)

## Hackathon Kit

[`kit/`](kit/README.md) contains the complete MIT-licensed upstream snapshot at [`22a5f44`](https://github.com/oliverchennn/hackathon-kit/commit/22a5f44a27375e88ac2cd1754f6976704f725bc5). Start with its [orchestration guide](kit/docs/guides/ORCHESTRATION.md), [collaboration playbook](kit/docs/playbooks/COLLABORATION.md), and [templates](kit/docs/templates/). The Datathon uses the kit's ownership, contracts, handoff, and verification practices.
