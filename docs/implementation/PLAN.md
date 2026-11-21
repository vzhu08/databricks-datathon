# Implementation plan

## What we are building

A dispatcher selects **Trauma care** and an Ajmer or Jaipur area pickup point. Show up to three facilities ranked by the strength of documented trauma capability and then by straight-line distance. Each card gives the underlying Virtue Foundation excerpt, any separately attributed corroboration, which campus matched, and the evidence and distance used to rank it. Show a clear empty or review state when the data cannot support a ranked result. The app is a datathon prototype. It shows documented capability and asks the dispatcher to confirm current availability through their existing workflow.

**First test case.** Check whether Virtue Foundation contains a compatible Ajmer J.L.N. campus row. The external listings make it a useful linkage test, and similarly named campuses make it a useful negative test. Choose the real demo query from inspection. Use the supplied synthetic fixture to demonstrate the near-versus-better-supported tradeoff during development. [Research and sources](../RESEARCH.md)

## Work sequence (ET)

| Target | Owners | Deliverable and acceptance check |
| --- | --- | --- |
| First 30 minutes on Saturday | All four | Claim a role. Start the board watcher. Data reads Marketplace schema and one permitted row. UX checks app startup and warehouse access. Ranking and evaluation agree on the query, result, split, and failure states using synthetic cases. |
| Saturday 3:00 p.m. | Data + Ranking | First clean Delta table and provenance view for Ajmer/Jaipur, with source IDs, service evidence, campus checks, and a few reviewed joins. Ranker passes the synthetic cases and returns a real cited result or an explicit no-match for the first query. |
| Saturday 6:00 p.m. | UX + Evaluation | Run the complete service-and-location flow on Databricks Free Edition. Record warehouse/app access and two real cases. If the app or judge access blocks the flow, commit to the Databricks notebook fallback and verify it in a fresh workspace session. |
| Saturday 9:00 p.m. | All four | Freeze scope and the ranking version. Rerun one real result and one uncertainty case. Freeze the evaluation queries before tuning to held-out outcomes. Confirm judge access, deadline, the form, and reusable-code rules with organizers. |
| Sunday 9:30 a.m. | Evaluation + all reviewers | Publish the baseline comparison with counts and limits. Freeze code and dry-run a fresh Databricks session. Verify exact candidate, excerpt, source and evidence labels across each demo path. |
| Sunday 11:00 a.m. | UX + Evaluation | Record the video from verified output. Collect code revision, analyses, source/kit credits, and the runnable app or notebook link. Verify view permissions and links through the judge path. |
| Sunday 11:45 a.m. | Evaluation / integration lead | Submit code, analysis, and video through the organizer form. Record the submitted SHA and receipt on the board. Use the confirmed organizer deadline if it changes. |

## Build and integration

1. **Data and evidence.** Attach the Virtue Foundation Marketplace listing in the team workspace and inspect the shared catalog. With a repeatable Spark notebook, profile duplicates, missing service text, invalid or conflicting coordinates, and geography coverage. Write normalized `facilities` and `facility_evidence` Delta tables in a writable Unity Catalog schema. Preserve raw row IDs, excerpts, sources, source dates, and geography. Import small permitted snapshots only once. Manually resolve or quarantine the first ambiguous cross-source joins.
2. **Search and ranking.** Resolve pickup from an Ajmer/Jaipur area location preset or validated coordinates. Retrieve candidates through Databricks SQL using bound parameters and a configurable 100 km straight-line radius for the first experiment. Gate on explicit Virtue Foundation service evidence and usable campus coordinates. Rank corroborated service evidence first, then facility-text-only evidence. Break ties by distance and stable facility ID. Record excluded conflicts and show them through the uncertainty state when appropriate. Keep the ranker callable from the notebook and the app. [Search contract](SEARCH_CONTRACT.md)
3. **Dispatcher workflow.** Build Streamlit on Databricks Apps against the same SQL data and search contract. Deploy `app/` with `app.yaml`, pinned app requirements, and the app's read-only resource grants. Add directions only for confirmed campus coordinates after an explicit click. Use a destination-only Maps URL and omit live ETA claims. Add a call-to-confirm link only when a campus-specific number is sourced. Check app access early and restart before judging if needed. [Streamlit tutorial](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/tutorial-streamlit) · [Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations) · [Maps URLs](https://developers.google.com/maps/documentation/urls/quick-reference)
4. **Evaluation and pitch.** Compare with the nearest case-insensitive `trauma` keyword match over the same search areas and candidate data. Aim for 20 hand-reviewed pickup points across Ajmer and Jaipur, including a weak claim, campus conflict, and sparse coverage. Freeze queries and use independent adjudication sources or manual campus review withheld from ranking. Report supported top-one/all queried, unsupported top-one/all queried, no recommendation/all queried, and coverage. Add ambiguity cases, linkage audit counts, and a district-level follow-up recommendation supported by the data. Report denominators and unknowns if fewer cases can be reviewed.

## Cut order and submission

- Gate a second service such as dialysis on the real trauma flow and evaluation being complete. Defer nationwide matching, live ETAs, dispatch automation, and live scraping.
- If external sources cannot be imported or none match the right campus, ship the Virtue Foundation evidence tier and disclose the missing corroboration. If school or workspace access blocks the app, ship the reproducible notebook and a video from a real Databricks run.
- Demo in this order: dispatcher query, why the first result won, citations and uncertainty, comparison with the baseline, and the workflow for confirming capability. Show a second query that returns no confident result.
- Deliver the final commit or code bundle, analysis with metrics and limitations, and video. Credit the pre-existing kit separately from event-period work and record data provenance. Verify links and submission receipt; the integration lead controls final submission.
