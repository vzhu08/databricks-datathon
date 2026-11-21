# Rajasthan trauma evidence

Developer B prepares campus-level public evidence for the v1.0.0 enrichment contract. Developer C reviews links to the Virtue Foundation base. Developer D validates and imports the resulting batch.

## Reproduce the combined package

Use Python 3.12. From the repository root, install the integration dependencies with `python -m pip install -r research/trauma/requirements.txt`. Each research lane documents its source acquisition, dependencies and exact reproduction commands in `research/trauma/handoffs/`.

1. Place each producer's v1.0.0 envelope at `<input-dir>/B1/batch.json` through `B4/batch.json`. Each envelope has five arrays. B owns source snapshots, external identities, evidence and review items. The base-match array is empty and base link fields are null.
2. Store the B5 final decisions at `<input-dir>/B5/audit.json` and its queue-only envelope at `B5/batch.json`. Each decision carries `evidence_id`, `evidence_sha256`, `outcome`, `reason`, `reviewer` and `reviewed_at` in UTC. Hash each original evidence object as UTF-8 compact JSON with sorted keys and `ensure_ascii=False`. The audit samples service and accreditation scope claims and reports its counts by type. Freeze corrections and re-review changed evidence before generating final decisions.
3. Place `raw_paths.json` in the input directory. It maps each snapshot ID to its exact raw file as an absolute path or a path relative to the input directory. Keep this private inventory with the raw files. The pipeline recomputes every source SHA-256 for a final release.
4. Run `python -m research.trauma.pipeline --input-dir <input-dir> --output-dir <release-dir>`. During collection, `--partial` permits missing lanes, missing raw files in the mapping, and a pending audit. The coverage report identifies that stage. A different output requires a new directory. Re-running against identical inputs verifies the existing release files.
5. Run `python -m unittest discover -s tests/research/trauma -p "test_*.py" -v`. The final handoff records per-lane results and the downstream validator revision.

## Read the output

- `batch.json` is the D ingestion envelope. Identical records deduplicate by ID. Conflicting payloads or unresolved references stop the build.
- `claim_ledger.json` retains every source assertion, including unsampled, failed, and uncertain claims. The B5 decision binds to the exact wording and metadata that the reviewer examined.
- `coverage.json` gives denominators, source families, verified raw hashes and the IDs of claims that passed B5. A pass applies to what the source said at the stated time. Availability remains unknown.
- Failed or uncertain claims stay in the local ledger and generate open review items. `source_review_ledger.json` preserves the original producer issues. Source evidence and audit results remain unlinked to Marketplace base identities.
- `sha256.json` inventories release files. Source files, lookup ledgers, audit decisions and generated batches belong in ignored local storage or an authorized Volume. Source-specific terms govern redistribution.
