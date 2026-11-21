# Nationwide team kickoff

Start with [AGENTS.md](../AGENTS.md), the [national plan](implementation/PLAN.md), the [board on main](implementation/OWNERSHIP.md) and the [acquisition contract](implementation/ACQUISITION_CONTRACT.md). Use one owner session per task and its listed paths. The shared input is the complete version-0 Virtue Foundation facilities table and PIN directory. Carry all 10,088 facility rows through the run. Start new work only when it serves nationwide processing, coverage or validation. Submit assignments and handoffs through repo issues or the board.

## What happens on each check

1. Read the current board on `origin/main`, open PRs, changed issues and review results. If a source cannot be read, retain its last successful baseline and identify the blocker.
2. Continue the current eligible national assignment, or start the first ready assignment for your owner whose dependencies are met. Check the issue for an active session before taking it. Keep the original population and snapshot pinned throughout the handoff.
3. Verify coverage by original row, state/UT and service. Preserve unknowns. A sampled accuracy check must draw from the frozen national output. Leave completed regional investigations in the archive.
4. Record meaningful results, exact tested revision, remaining dependency and permitted private artifact location in the owning issue. All four same-version account reads are in #36. Track private artifact receipt, replay and publication separately. The integration lead tests PRs against current main before merging.

## Source packages and patient status

Use the [service-status rules](implementation/SERVICE_STATUS.md). Freeze the original-text/identity baseline and assess each approved source against every original row. Inputs can have a narrower observed area. [Oliver collects the multi-state registers](https://github.com/vzhu08/databricks-datathon/issues/63). [Andrew builds the PMNDP roster importer](https://github.com/vzhu08/databricks-datathon/issues/64). [Vincent extends the national trauma reader](https://github.com/vzhu08/databricks-datathon/issues/65). [Ayush checks the MRI source and Vincent supplies its importer](https://github.com/vzhu08/databricks-datathon/issues/66). [Vincent integrates the three-service view](https://github.com/vzhu08/databricks-datathon/issues/67) with Andrew reviewing linkage and Oliver reviewing publication. Ayush completed the independent MRI check and the national NMC source scout. Any new scout should remain one short task at a time.

## Owner prompts

- **Oliver (A/D).** Complete the [shared source handoff](https://github.com/vzhu08/databricks-datathon/issues/36) and [nationwide base preparation](https://github.com/vzhu08/databricks-datathon/issues/6). Preserve repeated source rows, publish the mapping and hash, and verify the full-base counts before handing the artifact to Andrew.
- **Andrew (C).** Run [national matching](https://github.com/vzhu08/databricks-datathon/issues/57) on the full prepared base with the national identity references. Report processed, confirmed, ambiguous, candidate-only and unmatched rows, with counts by state/UT.
- **Vincent (B/integration).** Own the [national evidence report](https://github.com/vzhu08/databricks-datathon/issues/58), stratified quality checks, board, reviews and merges. Evaluate each new data proposal for bulk national reach and measurable contribution against the original denominator.
- **Ayush (E).** The [account read](https://github.com/vzhu08/databricks-datathon/issues/60), [MRI source verification](https://github.com/vzhu08/databricks-datathon/issues/66#issuecomment-7069307319) and [NMC scout](https://github.com/vzhu08/databricks-datathon/issues/61#issuecomment-7069238912) are complete. For new data, assess one nationwide source at a time. A short issue reply with reach, bulk access, join keys and reuse evidence is sufficient.
