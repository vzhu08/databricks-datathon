# National-level Rajasthan register · ACQ-D04

This collector captures the [NHSRC national-level register](https://qps.nhsrcindia.org/quality-certification/national-level-certificate) separately from D03's older full/partial tables. Both remain the single upstream family `nhsrc_nqas`. All D04 rows and assessment labels are **held out of matching features, threshold selection and candidate adjudication until predictions are frozen**. Nothing here establishes current certification, general clinical capability, NABH status or live availability.

## Observed interface

The actual GET form supplies Rajasthan as `field_state_target_id=38` and `field_certified_value=All`, `Certified` or `Conditionality`. The collector discovers these options, verifies selected controls and the Rajasthan table caption on every response, and follows actual next links with the observed Drupal page values `,1`, `,2`, etc. It does not guess numbered URLs. Four columns are exposed: serial, facility name, printed status and validity end. Start date, NIN, district, facility category and explicit department scope remain null. Serial is a presentation counter, not a facility identifier.

The run also acquires separate status-filtered pages for documentary comparison, the [category map report](https://qps.nhsrcindia.org/nqas-map-report), and linked copyright/terms pages. Each raw document has its exact URL, byte count, SHA-256 and UTC retrieval time. `Updated till` is captured separately from retrieval, publication and validity; publication dates remain null. The map's category counts cannot be linked to register campuses without identifiers or explicit inclusion rules.

## Commands

Use Python 3.9+ and the existing `research/certification/requirements.txt` environment. Run from the repository root:

```sh
research/certification/.venv/bin/python -m research.certification.national_run acquire \
  --run-dir data/local/certification/new-national-run --as-of 2026-11-21
research/certification/.venv/bin/python -m research.certification.national_run replay \
  --run-dir data/local/certification/new-national-run
research/certification/.venv/bin/python databricks/enrichment/validate_batch.py \
  --batch data/local/certification/new-national-run/batch.json \
  --base data/local/certification/new-national-run/empty_base.json --as-of 2026-11-21
research/certification/.venv/bin/python -m unittest discover -s tests/research/certification -v
```

Acquisition uses verified TLS, bounded public GETs and observed pagination, with the D03 transport's response/retry limits. `--max-pages` caps each view at 100 by default and records partial coverage if reached. An existing run directory is never overwritten. Raw source data stays under ignored `data/local/`; Git contains only code, synthetic tests and aggregate results. Preserve source attribution and the NHSRC copyright policy's third-party exception; no blanket open-data license is inferred.

The cutoff must be an exact `YYYY-MM-DD` calendar date. Compact dates such as `20261121` and ISO week dates are rejected before acquisition makes requests or writes files, and before classification or projection. This avoids Python-version-dependent parsing of a cutoff that would compare incorrectly with canonical source dates.

For an already acquired `national_capture.json`, `recheck --run-dir ... --as-of ...` re-fetches pages implicated by cross-view discrepancies, and `finalize --run-dir ... --as-of ...` derives the outputs. These commands refuse existing recheck/output files. Rechecks preserve the original capture and record new retrieval metadata and hashes; changed content is retained as another raw file. Finalization writes `national_run_manifest.json` last. An interrupted derivation has no completed manifest; use a fresh destination or deliberately recover the local run before retrying. `complete_with_source_limitations` describes a finished local derivation with unresolved source problems, not complete/current programme coverage.

## Outputs and interpretation

`national_capture.json` contains raw provenance, observed controls, each page's advertised total, per-view termination and any source-specific blockers. `national_recheck.json` contains targeted later observations. Eight derived artifacts are hashed in `national_run_manifest.json`:

| Artifact | Content |
| --- | --- |
| `ledger.json` | Every distinct displayed name/status/end payload; original cells, null absent fields, possible date parses, update label, cutoff classification, all occurrences, source family, holdout flags and v1 limitations |
| `occurrences.json` | Every observed primary row and locator, including any exact duplicates |
| `batch.json` | Conservative v1 projection: external rows, source snapshots, eligible accreditation evidence, open reviews, no campus matches |
| `unresolved_groups.json` | Same normalized name labels with differing status/end payloads; no campus or renewal confirmation |
| `discrepancies.json` | Missing/additional payload counts between All and the union of status views, plus each affected original locator |
| `audit.json` | Bounded challenge sample and original-row comparisons with provenance |
| `report.json` | Aggregate counts, missingness, per-view totals, date/status coverage, map comparison and unresolved discrepancies |
| `empty_base.json` | Explicit empty base for unlinked source-batch validation; not a replacement for Marketplace facilities |

Record identity hashes the exact displayed facility name, status and end text, excluding serial. Exact repeats are deduplicated in the reference ledger while all original occurrences remain available. Different status/date variants remain separate. A normalized name group is only a review aid, never a verified campus. Snapshot identity hashes the source URL and raw bytes; external IDs bind the chosen first snapshot and record payload. Evidence IDs include temporal classification; review IDs bind external and evidence IDs. Replay preserves stored retrieval timestamps. Fresh captures may have different raw HTML or artifact URIs even when row text agrees; do not merge immutable conflicts or count these as independent sources.

The D03 conservative date parser retains plausible day/month interpretations instead of guessing a locale. Expiry is certain only when all candidates precede the explicit assessment date. An end entirely after that date is `end_in_future_under_all_parses`; it is not a current-certification flag. Candidates on different sides of the cutoff remain `ambiguous_at_cutoff`; missing/invalid ends remain unknown. Original end text always survives, and every absent start stays null.

V1 cannot represent a future/uncertain end with no start using its `dated` or `undated` labels. Those records retain the complete typed ledger and open review but withhold v1 evidence. Certainly expired records project to `expired` with an exact end or `historical` with an unresolved end. Entirely missing dates may project as `undated`. `Conditionality` and other labels are never upgraded to `Certified`; their projected evidence uses inconclusive polarity. Review the ledger together with the batch.

The audit round-robins deterministic strata of printed status, cutoff classification, date ambiguity and repeated name labels, up to 20 records. It compares displayed name/status/end with separately acquired original status-filtered tables and retains all matching locators. This is an extraction-consistency check within one programme family, not independent corroboration, blinded human adjudication or a population estimate. Discrepancies do not silently repair the primary capture. The actual D04 sample contains 19 agreements and one unresolved omission, documented in the handoff.

Offline replay verifies every referenced raw file and all eight outputs byte-for-byte without network. Absolute artifact URIs currently require the original run location. Transfer to another machine or approved Volume requires deliberate URI republication and a new manifest. D03 inputs, outputs and replay remain separate and unchanged. Live Databricks publication, real original-population validation and submission require their own acceptance evidence.
