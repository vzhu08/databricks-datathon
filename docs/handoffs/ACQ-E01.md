# ACQ-E01 handoff

- **Review** · [PR #12](https://github.com/vzhu08/databricks-datathon/pull/12) on `codex/acq-e-source-links`. The source-check commit and opening PR head is `2b7244321f9fc0b4c1a2ef7b020e93f9bc81393f`. See the [PR commits](https://github.com/vzhu08/databricks-datathon/pull/12/commits) for the current head.
- **Artifacts** · `docs/source-checks/ACQ-E01.md` contains the eight outcomes and three demo sentences. `docs/handoffs/ACQ-E01.md` is this handoff. [Acquisition contract v1.0.0](../implementation/ACQUISITION_CONTRACT.md)
- **Public-source check** · Used the web fetcher’s `open` operation for all eight registry URLs and retried each failure once. Five URLs returned readable content. The RGHS hospital PDF and India Post PIN directory timed out twice. The NABH directory returned HTTP 403 twice. The three access failures remain unresolved.
- **Fixtures and live Databricks** · This task covers public URLs and demo wording. It produced zero source snapshots and has no fixture or Databricks dependency.
- **Earlier DATA-01 work** · `work/data` at `a8bb82d5f5f2dec34db0828ac3242b49cc146f9f` is available to Developer D for mapping and campus checks. [PR #2](https://github.com/vzhu08/databricks-datathon/pull/2)
