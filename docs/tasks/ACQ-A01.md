# ACQ-A01 · Developer A · National identity acquisition

Task issue: https://github.com/vzhu08/databricks-datathon/issues/3

Owner: one new Codex chat, accountable to Oliver. Branch: `codex/acq-a-collectors`. Start state: Ready for public/fixture work. Read AGENTS.md, the current remote board, acquisition contract v1.0.0, source registry, and synthetic fixture before coding.

## Objective and boundaries

Deliver working, repeatable collectors for HOT/OSM India healthcare features and the NHP hospital-directory mirror, with normalized identity records and verifiable provenance. Own only `research/acquisition/`, `tests/research/acquisition/`, and `docs/handoffs/ACQ-A01.md`. Put real outputs in ignored `data/local/acquisition/`; do not commit downloaded data. Do not edit shared schema, app code, Databricks ingestion, or B's source parsers.

## Work packages

1. Implement `python -m research.acquisition.run --source {osm,nhp,all} --output-dir <path>` with a local replay mode that accepts an existing snapshot. Document dependencies in your own requirements file. Use the shared source registry; resolve the NHP download from the observed landing page rather than guessing object URLs.
2. Fetch with bounded timeouts and retry/backoff for temporary failures. Validate status/content type and format before parsing; an HTML error page must not become a valid snapshot. Download to temporary storage and finalize atomically. Preserve an existing good snapshot on failed refresh.
3. Hash original bytes and emit complete source metadata: URL, publisher, upstream family, UTC retrieved_at, actual publication date or null, license/attribution, parser version, artifact URI, and assessed independence. A current fetch time must not replace an unknown source date. Record attempted acquisitions and failures in an aggregate report/review queue.
4. Normalize OSM nodes/ways/relations and NHP records to `external_facilities`. Preserve original names/addresses and source IDs/locators; store PIN as text. Preserve type distinctions and coordinate quality flags. For non-point geometries retain the source geometry externally and document the representative-point method; do not call an unexamined centroid an entrance.
5. Deduplicate exact repeated rows deterministically. For the same source ID with conflicting content, preserve both variants and queue review. Document deterministic snapshot/record IDs and test that timestamps do not change content-derived identity.
6. Produce coverage by source and facility type: input/output/deduplicated/conflicting counts, populated name/address/specialty/coordinate counts, missing/invalid/outside-country coordinate counts, and distinct identifiers. Preserve unknown independence rather than claiming every row independently corroborates VF.
7. Run both real public acquisitions. Compare OSM counts to the saved profile when available (139,664 rows / 136,004 distinct IDs was the October 9 snapshot); treat that as an observation, not a forever-fixed assertion. Report actual data/version drift. Missing source access is a documented partial result, never substituted fixtures.

## Required tests and acceptance

Run `python3 -m unittest discover -s tests/research/acquisition -p 'test_*.py' -v` from the repo root. Cover:

- Identical replay yields the same IDs/normalized content and no duplicate records, while each fetch attempt can retain its separate log.
- Duplicate IDs with identical and conflicting payloads; same-name facilities at distinct addresses survive.
- Non-ASCII names, missing/empty values, PIN strings, malformed coordinates, swapped/outside-country coordinates, and point/polygon/multipolygon geometry handling.
- Pharmacy/dentist/alternative-care rows retain their type; specialty missingness is not interpreted as absence of care.
- Timeout, HTTP error, HTML masquerading as data, truncated archive, and unsafe archive paths do not corrupt an existing accepted artifact.
- Every output row has a resolving snapshot and locator; all required contract fields are present; raw hashes verify; logs contain no credentials.

Deliver fixture test results plus real acquisition results separately. Do not say nationwide identities are verified: these are external source records awaiting C's matching.

## Handoff

Open a PR from your branch, no merge. Report head SHA, command lines, fixture/public results, source snapshot IDs, input/output counts, licenses, local or authorized Volume artifact paths, unresolved failures, requirements, and interface examples using synthetic data. Write `docs/handoffs/ACQ-A01.md` and post a compact update in the task issue. C and D must be able to replay your batch without consulting your chat history.
