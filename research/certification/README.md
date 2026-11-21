# Rajasthan NQAS reference

The newer national-level register is a separate [ACQ-D04 workflow](NATIONAL.md); this page describes the preserved D03 full/partial capture.

ACQ-D03 acquires the public NHSRC QPS full/partial facility tables for a **held-out accreditation audit**. Keep this entire reference out of candidate generation, matching features, thresholds and candidate adjudication until predictions are frozen. The emitted v1 envelope is a separate audit artifact; its identity-shaped rows are not permission to feed it into the ordinary matcher. No original population is supplied, and the producer creates no base links or matches.

NQAS applies to the named facility, printed department scope and recorded validity interval. It is separate from NABH and does not establish general clinical quality, a service capability or live availability. Both NHSRC portals and all QPS presentations have the single source family `nhsrc_nqas`, assessed as `shared_origin`.

## Observed sources and access

- [QPS landing page](https://qps.nhsrcindia.org/nqas-facility-list): actual GET forms for `/nqas-certification-full` and `/nqas-certification-partial`; state `field_state1_value`, district `field_district1_value`, facility `title`, pagination `page`. The collector applies Rajasthan with blank district/title, follows observed next links, and verifies state and headers on every page. Full and partial views have separate pagination. The landing page also embeds both views for documentary comparison.
- [NQAS certificate register](https://nqas.nhsrcindia.org/facilities/list): verified TLS failed with an expired certificate on 2026-11-21. Its current records, filters, pagination, public export, NIN and category coverage are **unobserved**, not empty. There is no TLS bypass. If this endpoint becomes accessible, its raw page is retained with an explicit layout-adapter blocker; inspect the actual layout before extending extraction.
- The QPS columns are serial, state, district, facility, assessed departments, validity-from and validity-end. They expose neither NIN nor a dedicated category. Preserve these as null; do not infer a city from district, category from a name prefix, or an identifier from serial.
- The actual QPS capture ended at 20 full rows and 3 partial rows. No public export links were observed on its landing page. This is accessible view coverage, not the programme's complete/current Rajasthan population.

The linked [NHSRC copyright policy](https://nhsrcindia.org/copyright-policy) permits accurate attributed reproduction of NHSRC material with a third-party exception. Do not interpret it as a blanket open-data license. The [terms](https://nhsrcindia.org/terms-and-conditions) do not guarantee accuracy or currency. Capture both policy pages; retain all raw pages, row text and excerpts in ignored `data/local/` or an authorized restricted Volume. Only synthetic fixtures and aggregate results belong in Git.

## Run and verify

Run from the repository root with Python 3.9+:

```sh
python3 -m venv research/certification/.venv
research/certification/.venv/bin/python -m pip install -r research/certification/requirements.txt
research/certification/.venv/bin/python -m unittest discover -s tests/research/certification -v

research/certification/.venv/bin/python -m research.certification.run acquire \
  --output-dir data/local/certification/new-run \
  --as-of 2026-11-21

research/certification/.venv/bin/python -m research.certification.run replay \
  --run-dir data/local/certification/new-run

research/certification/.venv/bin/python databricks/enrichment/validate_batch.py \
  --batch data/local/certification/new-run/batch.json \
  --base data/local/certification/new-run/empty_base.json \
  --as-of 2026-11-21
```

Acquisition refuses an existing output directory or a destination outside ignored `data/local/`. Public GETs use verified TLS, a bounded response size and at most two attempts for transient failures. No auth, credentials or cookies are required. `--max-pages` defaults to 100 per view; reaching it is an explicit partial result. Source failures preserve acquired rows and blockers without declaring an incomplete view complete. A changed table/filter/pager fails that view instead of silently guessing a new layout.

`run_manifest.json` is written last. Its `complete_with_source_limitations` status means local capture/derivation finished with the listed unavailable sources; it does not certify programme coverage. A fatal interrupted run has no completion manifest. Use a new directory when retrying. Replay makes no network requests: it verifies captured and audit raw bytes, hashes all declared files, rederives seven outputs and requires byte equality, including persisted retrieval timestamps.

## Local artifacts

| File | Purpose |
| --- | --- |
| `raw/<sha256>.html` | Exact response bytes, including source and policy pages |
| `capture.json` | Exact URLs, retrieval times, bytes/hashes, attempt log, filters, per-view pagination and blockers |
| `audit_capture.json` | Alternate-view acquisition metadata and failures |
| `batch.json` | Contract v1.0.0 source, external, accreditation evidence and open-review arrays; no matches |
| `episodes.json` | Lossless printed cells and dates, district, scope, nullable NIN/category, row locator, candidate date parses, ambiguity, expiration, holdout markers and any v1 limitation |
| `relations.json` | Verified-identifier interval relations and preserved conflicts; no name-only renewal links |
| `audit_sample.json`, `audit.json` | Deterministic sample identifiers and original-table comparisons |
| `report.json` | Aggregate coverage, unknowns, date counts and blockers with explicit denominators |
| `empty_base.json` | Explicit empty input for unlinked producer validation; not a synthetic replacement for a real base population |
| `run_manifest.json` | Assessment date, local root and artifact hashes |

Source snapshot publication dates are null: retrieval time is not publication, effective date or expiry. Source URLs plus view, one-based tbody row and printed serial form locators. Local absolute artifact URIs resolve to the verified raw file. This version requires the original run location for byte-identical replay. Relocation to another machine/Volume requires deliberate artifact-URI republication and a new manifest; never silently merge conflicting immutable URIs. Do not merge the inspection captures and final run as separate evidence.

Snapshot IDs combine the fixed QPS source namespace with the raw hash. External IDs include raw hash, semantic episode ID and row position. Episode IDs hash the source family, full/partial mode, seven display cells (including serial), NIN and category; they identify an observed row, not a deduplicated campus. Evidence IDs also include the normalized interval and temporal status, so a changed assessment classification creates a new version. Review IDs bind external and evidence IDs. Identical replay retains IDs and first persisted retrieval timestamps. A fresh download may change raw HTML hashes even when displayed rows are unchanged; compare episode payloads, preserve variants and do not count them as independent sources. D's merger retains accepted retrieval timestamps but rejects other immutable payload conflicts.

## Dates, identity and validation limits

Numeric dates with plausible day/month permutations keep both candidates and a null normalized date. Equal day/month or a component above 12 can resolve exactly; ISO and named-month dates are also supported. Invalid dates and two-digit years are not repaired. Original text always survives. An interval is expired only when every supported end-date interpretation is before the explicit assessment date. The actual run has 11 ambiguous starts and 13 ambiguous ends; all 23 intervals are expired under all interpretations.

V1 cannot encode date ambiguity. Exact expired ends use `expired`; unresolved but certainly expired intervals use `historical`, retaining null ambiguous normalized dates and the full ledger. Invalid/conflicting or unresolved current intervals withhold the v1 evidence row and record a source-specific reason while preserving the external/episode/review rows. The ledger must accompany the envelope; a generic consumer cannot reconstruct scope or ambiguity from dates alone.

NINs, if supplied by a future observed adapter, remain text, including leading zeros. Only a shared identifier in this programme family, compatible campus labels and exact coherent intervals can create an identifier relation. Non-overlapping episodes are preserved separately and are not automatically called formal renewals. Conflicting labels, overlapping intervals and ambiguous dates remain unresolved. Repeated names alone do not link campuses. Current QPS output has no NINs or verified renewal links; unavailable renewal strata cannot be filled by invention.

The challenge sample uses deterministic round-robin strata for full/partial mode, expiration, repeated name/district and date ambiguity, up to 20 rows. It compares all seven displayed fields with an alternate original QPS table presentation and records both snapshot hashes/locators. This checks extraction consistency within the same source. It is neither independent corroboration, blinded human adjudication nor a population accuracy estimate. The certificate-register comparison remains unavailable. Independent reviewers still need to inspect named campuses, departments and original periods after predictions are frozen.

Fixture tests exercise parsing, date ambiguity, repeated identifiers, conflicts, pagination/caps/failures, transport guards, raw hash integrity, the existing D validator and offline replay. Keep fixture checks, public-source results, live Databricks verification and submission status separate in the handoff.
