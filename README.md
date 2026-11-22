# CMU × Databricks Datathon · Fall 2026

Build a facility finder for community health workers in India. The first pass uses the Virtue Foundation dataset to find dialysis, MRI, or trauma care near a city, PIN code, or coordinates. The result shows nearby facilities, the text behind the match, and which details still need confirmation.

## Hosted demo

[Open the hosted Databricks app](https://vf-find-care-7474658456464525.aws.databricksapps.com/). It requires Databricks sign-in and app access. In the verified presenter deployment, **Find care** uses six synthetic facilities and the **Check symptoms** assessment provider is off. [Presenter browser verification](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7081145145)

## National evidence and project docs

The separate nationwide validation run uses all **10,088 original Virtue Foundation rows** at Delta version 0. It reports identity and service coverage across India and by state/UT, including records with missing information. The offline evidence walkthrough uses approved display files. [Implementation plan](docs/implementation/PLAN.md) · [Offline walkthrough instructions](app/facility_evidence_demo/README.md)

- Oliver owns integration, merges and release, Vincent leads data acquisition and refinement, Andrew owns the demo UI/UX, and Developer D covers the independent replay check. Coordinate through repo issues and the board. [Current team board](docs/implementation/OWNERSHIP.md) · [Kickoff prompts](docs/KICKOFF_PROMPTS.md)
- The search contract and its synthetic fixtures remain the baseline app interface. The acquisition sprint adds five evidence tables while preserving ranking and the UI. Real source snapshots and Marketplace rows stay outside Git. [Search contract](docs/implementation/SEARCH_CONTRACT.md)

## Submission

The organizer lists Sunday, November 22 at **12:30 p.m. ET** as the tentative deadline for code, analysis, and video. [Event schedule](https://cmudsc.com/datathon-fall2026/) · [Challenge brief](https://docs.google.com/document/d/e/2PACX-1vQxhDNQmgZhPgjG0M6LCb_UXNV8CJryqBNQQuqWfIg_dm40ZU1AYAXzZKViC6haFoCmLNiRVfUSBMjf/pub) · [Submission notebook status](https://github.com/vzhu08/databricks-datathon/issues/307)

## Hackathon Kit

[`kit/`](kit/README.md) contains the complete MIT-licensed upstream snapshot at [`22a5f44`](https://github.com/oliverchennn/hackathon-kit/commit/22a5f44a27375e88ac2cd1754f6976704f725bc5). Start with its [orchestration guide](kit/docs/guides/ORCHESTRATION.md), [collaboration playbook](kit/docs/playbooks/COLLABORATION.md), and [templates](kit/docs/templates/). The Datathon uses the kit's ownership, contracts, handoff, and verification practices.
