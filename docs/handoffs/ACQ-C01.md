# ACQ-C01 handoff · identity matching and geographic checks

Developer C · `@andrewhgu` · Claude Code session `session_01LWLtujoz3kp3Vn9YqdtKp8` · November 21, 2026.

Task [#5](https://github.com/vzhu08/databricks-datathon/issues/5), branch `codex/acq-c-matching`, contract **1.0.0**, matcher `matching-1.0.0`, footprint parser `footprints-1.0.0`. Implementation tested at **`a87ad0752b5cf0dbd5d5d410b59500ee32dffc6b`**; this handoff is a later documentation-only commit, and the final head is recorded on the issue and PR. The remote board was reread at `041907a` before handoff, after B's evidence work merged. No merge, deployment, board or shared-contract change was made.

Status: **fixture implementation ready for review. No real matching has been run.** The original base rows have not been exported from the workspace, and A's real batches sit in ignored storage on another machine, so there are no real candidates, no real review ledger and no real footprint extract yet.

Changed paths: `research/matching/`, `research/geography/`, `tests/research/matching/`, this file. [Workflow documentation](../../research/matching/README.md) covers every command, input, output, ID derivation and rule.

## What was delivered

1. `python -m research.matching.run --base <file> --external <batch> --output-dir <path>`. Deterministic candidate retrieval from name, alias, identifier, address, phone, state, place, PIN and distance, with a written rationale and counts of alternatives per pair.
2. Automatic confirmation only for an exact text identifier in an inspected namespace, unique on both sides, with no geography conflict and no competing campus. It applies the same conditions D's validator enforces, so a row C confirms is one D accepts.
3. A stratified review sample of up to 50 pairs, a decisions file format, and `python -m research.matching.review`, which writes the reviewed batch, D-format transitions, evidence link and unlink transitions, a ledger and a summary with denominators.
4. Coordinate screening with proposed corrections kept beside the originals, coordinate clusters, and postal context aggregated to one entry per PIN before any lookup.
5. `python -m research.geography.overture` and `python -m research.geography.footprints` for the bounded building check: case selection, a pinned 500 m extract script, metre distances, upstream lineage, and location-only evidence.

## Fixture checks

Run from the repository root:

```sh
python3 -m venv research/matching/.venv
source research/matching/.venv/bin/activate
python3 -m pip install -r research/matching/requirements.txt
python3 -m unittest discover -s tests/research/matching -p 'test_*.py' -v
python3 -m unittest discover -s tests/databricks/enrichment -p 'test_*.py' -v
PYTHONPYCACHEPREFIX=/tmp/acq-c-pyc python3 -m compileall -q research/matching/*.py research/geography tests/research/matching
git diff --check origin/main...HEAD
git ls-files data/local research/matching/.venv
```

Python 3.13.18 with `jsonschema[format]==4.23.0`. **51 matching tests passed**: 25 in `test_matching.py`, 10 in `test_review.py`, 16 in `test_geography.py`. D's 72 enrichment tests still pass on this branch. Compilation and whitespace checks passed, and no local data or environment file is tracked. The code avoids syntax newer than Python 3.9 but was not executed on 3.9.

All test data is invented. The required cases are covered: same name on different campuses, aliases from both sides, a misleading acronym, a shared switchboard and a direct phone, a conflicting same-source identifier, a namespace collision, name-only and proximity-only candidates, wrong district and PIN, missing, non-numeric, incomplete and swapped coordinates, postal join fan-out, a stale footprint, no footprint, and an OpenStreetMap-derived footprint beside an OpenStreetMap identity. Tests also verify deterministic reruns and input-order independence, stable IDs, an unchanged base (count, IDs, text and hash), that unknown values stay unknown, that evidence links only to a reviewer-confirmed match, and that a rejected or conflicting match cannot verify a service claim.

D's merged validator is imported read-only by the tests. It accepts the candidate batch, an automatic shared-identifier confirmation under an identity policy, a reviewed first submission with evidence transitions, a transition replay against already accepted candidates, an unlink after a later rejection, and reviewed spatial evidence including a duplicate replay. It also rejects a hand-forced link onto a rejected match.

Shared synthetic fixture run:

```sh
python -m research.matching.run --base contracts/fixtures/enrichment_base.json \
  --external contracts/fixtures/enrichment.json --output-dir data/local/matching/fixture
python databricks/enrichment/validate_batch.py --batch contracts/fixtures/enrichment.json \
  --batch data/local/matching/fixture/batch.json \
  --base contracts/fixtures/enrichment_base.json --as-of 2026-11-21
```

Both exited 0. The run kept 2 base rows unchanged (hash `4bf2616c4625d06f2c99de8898b6f51b629f375db0835179e103bed23c4a53fd` before and after), read 3 external rows, and wrote 6 candidate matches, 0 confirmed, and 6 open `ambiguous_campus` review items; all 6 pairs entered the review sample. `batch.json` SHA-256 is `7222bd4b1550eb5f3fab6298bfdf92d2cf87d12834de5e0a851dc72ce0cab603` and is identical on rerun. Nothing confirms because the fixture has three records with one name and no shared identifier, which is the intended outcome.

D's prepared package was exercised with the same two synthetic rows through `prepare_local_export.py` and `--source-metadata`; the run accepted D's `base.json` and observed mapping without changes.

A synthetic volume check with 10,000 invented base rows against 147,000 invented external rows finished in about 51 seconds using about 600 MB on a 4-core container. It shows the run is bounded at the size of A's national batch. It says nothing about real match rates.

## Public-source and live results

- **Public data:** none processed. A's national batch (`4b5900ba…951aa`) and Rajasthan extracts (`explicit.json` `de9f6d9e…5c31`, `additional_review.json` `a1e43991…228b`) are in ignored storage on A's machine and were not available to this session. No download was substituted.
- **B's evidence release:** 74 source-local Rajasthan records (`release-01/batch.json` `cde57eb0…ab89`) are in ignored storage on B's machine and were not available to this session.
- **Original base:** not observed. The source manifest on main still lists the table and column mapping as to be filled from a live run. No Marketplace row, table name, schema or column mapping was seen or assumed.
- **Live Databricks:** not attempted.
- **Review ledger:** 0 real identity candidates reviewed of a target of up to 50. No match, unmatched or conflict rate exists yet. Synthetic decisions in tests are not review results.
- **Footprints:** 0 of up to 10 disputed and 10 control cases. The extract script follows the documented Overture release layout and was not run against the live bucket. The registry's release prefix `2026-11-18.0` is an entry point that still needs checking.

## Base adapter requirements

- `--base` is D's `base.json`: an array of `{facility_id, source_row}` with unique text IDs. IDs are used exactly as given, including leading zeros.
- `--source-metadata` is the `source_metadata.json` written with that base. Its mapping supplies name, state, type, PIN, latitude and longitude. Its row count must equal the base file's.
- D's mapping has no address, city, district, phone or alias role. If the source has such columns, C needs their observed names in a small extra mapping file (`research/matching/examples/base_mapping.example.json`). Without them matching still runs, with weaker geography.
- An identifier can confirm automatically only through an identity policy in D's format. None is assumed. If the base carries an OSM, NHP or registry identifier column, D or the operator should state the namespace, both field names and the allowed source keys.
- Coordinates must be JSON numbers. Text coordinates are reported as unusable and are not parsed.

## Requests to other owners

- **D or an authorized operator:** follow `databricks/enrichment/LOCAL_EXPORT.md` to produce `base.json` and `source_metadata.json`, plus the observed names of any address, city, district, phone and identifier columns. This is the single blocker for real matching.
- **A:** make the Rajasthan `explicit.json`, `additional_review.json` and the national batch available in storage C can read. If the raw features carry phone numbers or district fields, a sidecar keyed by `external_facility_id` would let C use them (`examples/external_attributes.example.json`).
- **B:** make `release-01/batch.json` readable alongside A's extract; it is passed as a second `--external`. All 74 records lack coordinates and 68 lack a PIN, so their candidates will be name and district led and will go to review. Proposed aliases, districts and campus notes from the B2 and B4 ledgers can go in the same sidecar shape. B's unlinked evidence is linked only after a reviewer confirms the match for its external record.
- **Orchestrator:** C emits one match row per base and external pair under `acq-c-match:`. The shared fixture also carries matches for the same pairs under `synthetic:match:`; the validator accepts both, so on real data only C should emit matches.

## Interface notes for D

- First submission: `reviewed_batch.json` with `--transitions evidence_transitions.json`. If D already accepted C's `batch.json`: that same file with `--transitions transitions.json`. Never both sets.
- D's transition rule requires the replacement's reviewer and time to equal the transition actor and time. Linking evidence therefore stamps C's reviewer on a row B had reviewed. The earlier review remains recoverable through the prior payload hash.
- Footprint evidence always has a different snapshot from its identity record, so the validator requires review metadata. Without `--reviewer` the footprint tool writes only its ledger and review items.

## Sample-selection rules

- **Identity review:** up to 50 candidates, round-robin across nine strata (easy, alias, ambiguous name, conflicting geography, missing geography, non-hospital type, shared identifier, proximity only, other), ordered inside a stratum by SHA-256 of the match ID. All candidates are taken when there are 50 or fewer. Stratum sizes and sampled counts are written to `report.json`.
- **Footprints:** up to 10 disputed pairs (name evidence strong or moderate, coordinates more than 1 km apart) and 10 controls (name strong, within 150 m, no conflict or ambiguity), ordered by SHA-256 of the match ID; all eligible cases when fewer.

## Limits

- Candidate thresholds are retrieval heuristics and are uncalibrated. No confidence percentage is produced. Precision can be stated only for reviewed decisions, with the reviewed count as denominator and every rejected candidate listed.
- A candidate is not an identity decision. Name-only, proximity-only, acronym-only and switchboard pairs never confirm automatically.
- Missing coordinates, PINs, postal entries and footprints stay unknown. An absent footprint is never negative evidence and footprints carry no clinical meaning.
- Name folding handles Latin script and common English abbreviations; other scripts are compared after folding without abbreviation handling.
- The India envelope and the two-decimal precision flag are screening cues, not findings.

## Remaining work

1. Run the Rajasthan pilot once the base export and A's extract are readable, starting with `explicit.json`.
2. Review up to 50 candidates with B's campus evidence, apply decisions, and hand D the reviewed batch and transitions.
3. Select footprint cases from the reviewed run, check the pinned Overture release, run the bounded extract and record observations.
4. Report real counts for matched, unmatched and conflicting rows with their denominators.

Submission status: not attempted.
