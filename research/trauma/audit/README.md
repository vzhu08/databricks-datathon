# B5 claim and provenance review

Use complete producer envelopes to select service claims and trauma-relevant accreditation statements. Identity lookups and source-access failures inform adjudication. If the population exceeds 30, round-robin across producer lanes, across risk and control cases within each lane, then by temporal status, wording, source family and district where available. Identify campus and wording strata before deciding outcomes. The sample is purposive and does not estimate an error rate or statewide coverage.

| Check | Evidence needed for a pass |
| --- | --- |
| Exact excerpt | Reopen the publisher bytes or another verified original and record the passage at the cited locator. The excerpt must be contiguous after whitespace normalization. Preserve punctuation, case, and word order. Inspect the row and the separate headings that give the cells meaning. |
| Locator | Find the exact page, table and row, or equivalent HTML position, with the stated section. A repeated phrase elsewhere does not repair a bad locator. |
| Campus | The source identifies the same site at the specificity claimed. Check district, locality, address or identifier and inspect competing campuses. Affiliation and name alone cannot resolve a cross-source match. |
| Dates | Verify claimed publication, effective, and expiration dates independently of retrieval. Preserve historical programme status and undated listing or marketing language. An in-range certificate cannot establish unsuspended status. |
| Service specificity | Distinguish directory listing, programme level, historical functionality, explicit service wording, accreditation scope, generic emergency, referred care, planned capacity, and negative wording. Document review cannot establish current acceptance. |
| Independence | Repeated URLs, variants of one government report, and multiple pages from one hospital represent the same candidate upstream origin. Attribute NABH-issued scope to NABH even when the hospital hosts it. Hospital service pages are self-published. Keep undocumented cross-family independence unassessed. |

Use `fail` when a check contradicts the payload or demonstrates an unsupported upgrade and `uncertain` when the original, campus, or interpretation cannot be resolved. A `pass` confirms the scoped documentary claim. Adjudication is separate from the producer's interpretation and uses the same available public record. It provides no clinical sign-off or verification of live care.

## Reproduce a run

Run from the repository root. Use the absolute input and output locations in the handoff. Keep source rows, quotes and ledgers under ignored storage. Repeat `--batch` for each lane and `--artifact` for each original inspected.

```text
python -m research.trauma.audit --batch B1/batch.json --batch B2/batch.json --batch B3/batch.json --batch B4/batch.json --strata work/strata.json --out work/sample
python -m research.trauma.audit --batch B1/batch.json --batch B2/batch.json --batch B3/batch.json --batch B4/batch.json --strata work/strata.json --freeze-selection work/sample/selection.json --observations work/observations.json --lineage work/lineage.json --artifact path/to/original --out review
python -m unittest discover -s tests/research/trauma/audit -p "test_*.py" -v
```

- `strata.json` maps evidence ID to optional `lane`, `campus` (`ambiguous` or `conflict` for priority cases), `wording`, and `district` labels. A scope statement labeled `general_emergency` can enter the service review sample.
- The selection lists each evidence ID and its full context hash. For every selected ID record `reviewed_payload_sha256`, `reviewer`, `reviewed_at` in UTC, `located_passage` (or null if unavailable), `source_temporal_status`, the five manual `checks` with outcome and reason, and a claim-specific `reason`. Under `original`, record the inspected URL, locator and archived path/hash. Include any `correction_requested`. The rubric checks quote containment separately.
- `lineage.json` contains optional `snapshots` annotations keyed by snapshot ID, with `relationship`, `upstream_origin`, and `reason`, plus `comparisons` describing observed archival comparisons. Group counts represent candidate origins. Independence between different groups requires evidence of their upstream collection.
- `audit.json` records the latest outcome per selected ID and the SHA-256 of the exact contract evidence row used by the lead's release gate. The context hash in the history binds the decision to the evidence, external facility and source snapshot together.
- When the lead routes a correction, retain the prior `audit-history.json`, inspect the corrected payload and source again, and rerun with `--prior-history` and the new observations. Increasing UTC timestamps and the full context hash distinguish re-review from a stale decision. If a producer emits a replacement ID, record the old and new IDs in the correction notes and update the frozen sample to point to the replacement.
- `batch.json` owns only contract v1.0.0 `review_queue` rows for final failed or uncertain claims. Resolve references against the combined reviewed and quarantined producer records. The lead uses the latest audit separately to gate the reviewed-only view. `artifact_inventory.json` records absolute paths, byte counts and SHA-256 checksums for replay inputs and outputs.
