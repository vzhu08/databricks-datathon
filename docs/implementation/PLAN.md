# Implementation plan

The [first-pass prompt](../FIRST_PASS_PROMPT.md) is the brief. A community health worker selects dialysis, MRI, or trauma care and enters a city and state, PIN, or coordinates. Search the full Virtue Foundation India dataset. Return up to three direct matches within the chosen radius, with the exact evidence and its field. Show indirect leads under “Needs confirmation” when there are zero direct matches.

| When (ET) | Owners | Checkpoint |
| --- | --- | --- |
| First 30 minutes | All four | Claim roles, start five-minute board checks, and agree on the prepared row shape and search responses. Dev 1 checks Marketplace access. Dev 3 checks Apps and warehouse access. |
| Saturday 3:00 p.m. | Devs 1 and 2 | Inspect real schema and sample rows if accessible. Produce a repeatable preparation notebook and verify independent location and matching logic against synthetic cases. |
| Saturday 6:00 p.m. | Devs 2, 3, and 4 | Integrate the app end to end. Run “dialysis near Jaipur” on the real table and inspect the exact excerpts if available. Exercise all failure cases with a clearly labeled fixture. Record any workspace blocker precisely. |
| Saturday 9:00 p.m. | All four | Freeze scope. Verify the ranking rules and capture one success and one uncertainty case. Confirm organizer deadline, submission form, judge access, and reusable-kit rules. |
| Sunday 9:30 a.m. | Dev 4 and reviewers | Run acceptance checks from a fresh session. Verify the deployed app if configured and record the tested revision and any environment limits. |
| Sunday 11:00 a.m. | Devs 3 and 4 | Record the video and collect code, analysis, tested app instructions, and kit/data credits. Verify judge access and shared links. |
| Sunday 11:45 a.m. | Dev 4 | Submit code, analysis, and video and record receipt. The published deadline is tentatively 12:30 p.m. ET. [Event schedule](https://cmudsc.com/datathon-fall2026/) |

## Dependencies and handoffs

1. **Dev 1, data.** Inspect the actual Marketplace table before defining the mapping. Build a parameterized Spark notebook that prepares a Unity Catalog Delta table with original evidence, record links, and campus identity. Profile missing and malformed data and demonstrate preservation of distinct same-name campuses. Share the fully qualified prepared table, resolved mapping, and permitted sample profile with Devs 2–4.
2. **Dev 2, search.** Implement small direct and indirect service synonym sets with exclusions for unavailable, planned, and referred services. Keep matching, dataset-based location resolution, and Haversine sorting callable outside Streamlit. Return ambiguity choices and a separate indirect-lead state. Share the callable and test results with Devs 3 and 4. [Search contract](SEARCH_CONTRACT.md)
3. **Dev 3, app.** Build Streamlit in `app/`. Use a Databricks Apps SQL warehouse resource and parameterized queries to read the prepared table. Render service selection, validated location, ambiguity choice, 50 km default and radius expansion, exact evidence, source links and availability. Verify Databricks app startup and judge access early. [Streamlit tutorial](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/tutorial-streamlit) · [Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)
4. **Dev 4, verification and integration.** Own the board and the shared contract, coordinate merges, and verify direct over indirect, ambiguous city, invalid coordinates, empty direct results, and distinct campuses. Run real-data and Databricks deployment checks when configured. Record fixture and live outcomes, exact setup steps, and the judging demo. Get a human decision on any submission fallback if workspace access stays blocked.

Dev 1 can inspect the workspace while Devs 2 and 3 work from synthetic fixtures. Dev 4 can write the verification checklist in parallel. The app consumes the prepared table and search callable when both are integrated. The [research handoff](../RESEARCH.md) retains corroboration ideas for later work. Everything in the first pass comes from Virtue Foundation rows.
