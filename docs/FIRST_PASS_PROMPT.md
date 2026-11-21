> Historical first-pass brief. Its work assignments are superseded by the current acquisition plan and board. Retain it as baseline app context; do not launch its old tasks or timers.

# First-pass prompt for Oliver’s orchestrator

Paste everything below into the lead conversation.

---

Coordinate this first pass across four named developers with separate write scopes and explicit handoffs. Oliver (`oliverchennn`) is the orchestrator and owns integration, acceptance checks, and submission. Vincent (`vzhu08`) owns the core matcher, location resolver, ranking, and warehouse data adapter. Ayush (`ayushrgupta906`) owns the Marketplace inspection and preparation notebook. Andrew (`andrewhgu`) owns the complete UI and UX in his own Claude Max session. Publish approved assignments on the shared board. The four coding chats check the board every five minutes and start newly assigned `Ready` work when free. Vincent, Ayush, and Oliver use scheduled follow-ups in their existing Codex desktop coding chats. Andrew uses `/loop 5m` in Claude Code. Give each task one executor across coding chats and kit workers. Use the scopes in `docs/implementation/OWNERSHIP.md` and the role prompts in `docs/KICKOFF_PROMPTS.md`.

Implement the first working version of our Fall 2026 CMU Datathon project. Start by reading AGENTS.md and inspecting the existing repo. Reuse the repo’s structure and working code. Carry the implementation through to a runnable app and test the full search flow.

Challenge brief:
https://docs.google.com/document/d/e/2PACX-1vQxhDNQmgZhPgjG0M6LCb_UXNV8CJryqBNQQuqWfIg_dm40ZU1AYAXzZKViC6haFoCmLNiRVfUSBMjf/pub

## Goal

Build a Streamlit app that runs on Databricks Free Edition. The primary user is a community health worker helping a patient find care. They select a service, enter a location, and get up to three nearby facilities with clear evidence for why each was selected.

Use the provided Virtue Foundation India dataset as the sole data source for this pass. Support dialysis, MRI, and trauma care across the full dataset.

## Implementation

1. Inspect and prepare the data. Use the Marketplace table configured in the workspace and inspect its real schema and sample rows. Make the table name configurable. Keep facility identity, city, state, PIN, coordinates, original evidence text, and source URLs. Handle missing or malformed values. Preserve distinct campuses, including campuses with the same name.
2. Build a deterministic service matcher. Use a small synonym list and look for explicit claims in the description, capabilities, procedures, and equipment fields. Preserve the best matching excerpt verbatim and record its field. Classify explicit service claims as direct evidence and related terms as indirect evidence. For example, “provides hemodialysis” is direct, “nephrology” alone is indirect, and a general emergency department is indirect for trauma care. Exclude claims describing planned services, unavailable services, or referrals elsewhere.
3. Resolve the location from the dataset. Accept city and state, PIN code, or latitude and longitude. Prompt for a choice when a place name is ambiguous. For a city or PIN, derive a representative point from valid facility coordinates and label the resulting distance approximate. Start with a 50 km radius and let the user expand it.
4. Rank and explain. Return up to three direct matches ordered by straight-line distance. When there are no direct matches, say so and show any indirect leads under “Needs confirmation.” Each card should show the facility name and location, distance, exact evidence excerpt and field, available record source links, and a one-line explanation of the ranking. Label current availability as unknown. If URLs belong to the whole record, label them as record sources.
5. Make it runnable on Databricks. Use a notebook to prepare the table and a Databricks SQL warehouse resource for the Streamlit app. Keep matching and ranking testable outside the UI. Add brief setup instructions covering the Marketplace table, app configuration, and how to run and verify the app.

## Acceptance checks

- Run “dialysis near Jaipur” against the real dataset if accessible and manually inspect the top results and their excerpts.
- Verify that a closer indirect match never outranks a direct match.
- Verify ambiguous city input, invalid coordinates, no direct matches, and separate same-name campuses.
- Test the deployed app if a workspace is configured. If workspace access is unavailable, run the search flow with a clearly labeled test fixture and report which real-data and deployment checks remain.

In your final response, summarize what works, which checks passed, and any setup still needed.
