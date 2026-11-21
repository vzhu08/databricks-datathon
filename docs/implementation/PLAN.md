# Implementation plan

The [first-pass prompt](../FIRST_PASS_PROMPT.md) is the brief. A community health worker selects dialysis, MRI, or trauma care and enters a city and state, PIN, or coordinates. Search the full Virtue Foundation India dataset. Return up to three direct matches within the chosen radius, with the exact evidence and its field. Show indirect leads under “Needs confirmation” when there are zero direct matches.

| When (ET) | Owners | Checkpoint |
| --- | --- | --- |
| First 30 minutes | All four | Schedule five-minute checks in the coding chats and agree on the prepared row shape and search responses. Ayush checks Marketplace access. Oliver and Vincent check Apps and warehouse access. Andrew starts the UI with synthetic responses. |
| Saturday 3:00 p.m. | Ayush and Vincent | Inspect real schema and sample rows if accessible. Produce a repeatable preparation notebook and verify independent location and matching logic against synthetic cases. |
| Saturday 6:00 p.m. | Vincent, Andrew, and Oliver | Integrate the app end to end. Run “dialysis near Jaipur” on the real table and inspect the exact excerpts if available. Exercise all failure cases with a clearly labeled fixture. Record any workspace blocker precisely. |
| Saturday 9:00 p.m. | All four | Freeze scope. Verify the ranking rules and capture one success and one uncertainty case. Confirm organizer deadline, submission form, judge access, and reusable-kit rules. |
| Sunday 9:30 a.m. | Oliver and reviewers | Run acceptance checks from a fresh session. Verify the deployed app if configured and record the tested revision and any environment limits. |
| Sunday 11:00 a.m. | Andrew and Oliver | Record the video and collect code, analysis, tested app instructions, and kit/data credits. Verify judge access and shared links. |
| Sunday 11:45 a.m. | Oliver | Submit code, analysis, and video and record receipt. The published deadline is tentatively 12:30 p.m. ET. [Event schedule](https://cmudsc.com/datathon-fall2026/) |

## Dependencies and handoffs

1. **Ayush prepares the data.** Inspect the actual Marketplace table before defining the mapping. Build a parameterized Spark notebook that prepares a Unity Catalog Delta table with original evidence, record links, and campus identity. Profile missing and malformed data and demonstrate preservation of distinct same-name campuses. Give Vincent the fully qualified table name, resolved mapping, and permitted sample profile.
2. **Vincent owns core search.** Implement direct and indirect service matching, exclusions for unavailable, planned, and referred services, dataset-based location resolution, and Haversine ranking. Build the SQL adapter with bound parameters to read Ayush’s prepared table through the app’s Databricks warehouse resource. Share the callable and response examples with Andrew. [Search contract](SEARCH_CONTRACT.md)
3. **Andrew owns UI and UX.** Build Streamlit in his Claude Max session. Own service selection, validated location, ambiguity choice, the 50 km default and radius expansion, results, exact evidence, source links, availability, and empty or error states. Start with fixtures and use Vincent’s callable for integration. Work with Oliver to verify the Databricks app and judge access. [Streamlit tutorial](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/tutorial-streamlit) · [Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)
4. **Oliver runs orchestration and integration.** Own the board and the shared contract, coordinate Vincent and Ayush in Codex and Andrew in Claude Max, and review merges. Run the acceptance checks from the first-pass prompt on fixtures and real data as access allows. Document deployment, verify the judging flow, and own the submission.

Ayush can inspect the workspace while Vincent and Andrew build against synthetic fixtures and Oliver prepares the verification checklist. The app consumes the prepared table and search callable when both are integrated. The [research handoff](../RESEARCH.md) retains corroboration ideas for later work. Everything in the first pass comes from Virtue Foundation rows.
