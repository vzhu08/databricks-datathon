# CGHS local collector

This collector turns reviewed, hash-bound CGHS directory extractions into the
v1.0.0 identity-reference envelope. It serves later comparison with all 10,088
original VF rows. It does not fetch, upload, match, publish, or confirm clinical
services. All source files and generated outputs belong in ignored `data/local/`
or another explicitly authorized private location.

The workflow has two separate steps:

1. Optionally extract explicitly selected ruled PDF tables. The extraction stays
   `unreviewed`; a producer must inspect the original, classify each record,
   resolve rights, and add any group/duplicate relationships.
2. Compile frozen original bytes and producer-reviewed extraction receipts.
   Documents or rows with unresolved rights are held out. Scans and changed
   table layouts need manual extraction/review; the parser does not guess.

Use Python 3.12 for the pinned PDF dependency:

```sh
python -m pip install -r research/acquisition/cghs/requirements.txt
python -m research.acquisition.cghs.extract_pdf \
  --pdf data/local/cghs/source.pdf --layout data/local/cghs/layout.json \
  --out data/local/cghs/unreviewed.json
python -m research.acquisition.cghs \
  --manifest data/local/cghs/input.json --out data/local/cghs/release-v1
python -m unittest discover -s tests/research/acquisition/cghs -v
```

## Input receipts

`input.json` contains `manifest_version: "1.0.0"`, an explicit ISO `as_of`, and a
`sources` array. Each source supplies:

- `source_key` (stable across revisions), `source_family: "cghs_empanelment"`,
  `publisher`, `issuer`, `series_key`, `eligible_population`, and `coverage_scope`.
- Public HTTPS `url`, frozen UTC `retrieved_at` ending in `Z`, nullable ISO
  `document_date`, and lowercase raw-byte `sha256`.
- `raw_file`, `rows_file`, and `rows_sha256`. Paths are relative to the input
  manifest, confined to its directory, and portable across operating systems.
- `reuse`: `status` (`permitted`, `hold`, or `rejected`), `reason`, and
  `third_party_rights` (`cleared` or `unresolved`). Permitted, cleared sources
  also require `license` and `attribution`. These are the producer's documented
  review decisions, not permissions inferred by the code.
- Optional `selected: true` with a nonempty `selection_reason` to resolve an
  ambiguous series. Omission or `false` means no manual selection override.

Held/rejected sources need provenance and disposition metadata, but their raw
and extraction paths are never opened. A source marked permitted still remains
held when third-party rights are unresolved.

The extraction JSON contains `raw_sha256`, `review_status: "producer_checked"`,
a nonempty `reviewer`, and `rows`. This is transcription review, not independent
campus or service confirmation. Each row supplies:

```json
{
  "locator": {"page": 1, "table": 1, "section": "synthetic-main", "row": "1"},
  "kind": "campus",
  "name_raw": "Synthetic Example Campus",
  "address_raw": "Example Lane, Synthetic City",
  "city": "Synthetic City",
  "state": "Synthetic State",
  "scope_raw": "Synthetic scheme scope only",
  "validity_raw": "01.01.2025 to 31.12.2027",
  "rights": "cleared"
}
```

Nullable fields also include `pin`, `institution_type`, `scheme_id`, and
`scheme_id_namespace`. A scheme ID requires its namespace; printed serials are
only locators. Missing names/geography and invalid PINs remain visible. The
original PIN is retained while its normalized value becomes null if invalid.

`kind` is explicitly `campus`, `group_summary`, or `multi_campus_group`.
`parent_locator` links a campus to an existing summary in the same snapshot.
`branch_labels` can describe a multi-campus group without creating inferred
campus rows. `representation_of` plus `representation_reason` identifies a
producer-reviewed duplicate language representation. Chains, cycles, missing
targets, and conflicting locators fail validation. Same name/address rows with
different scopes remain separate observations and receive a repeated-identity
group; they are never automatically deduplicated.

Optional `diagnostics_only` is a reviewed boolean classification, not proof of
clinical capability. Optional `events` retain `kind`, exact `excerpt`, nullable
ISO `effective_date`, and `authority`. Supported kinds are renewal, suspension,
delisting, cashless withdrawal, nonrenewal and name change. Excerpts must occur
verbatim in the row's name, scope or validity text. Events remain in the private
observation ledger; no service evidence is emitted. `validity_raw` is preserved;
only explicit day/month/year intervals are parsed, with malformed dates and
multiple/repeated episodes separately flagged.

## PDF layouts

The layout is an ordered array of explicit `page`, `table` (both 1-based),
`section`, and `columns` objects. Each column has an expected `header` and a
`field`, including exactly one `serial` and one `name_raw` column. Other supported
fields are address, scope, validity, scheme ID/namespace, city, state, PIN and
institution type, using the names above. Header/column changes stop extraction.
Serial resets require a new explicit section. Blank-serial continuation rows
attach only within the same section; orphan continuations fail. Character-centre
extraction preserves glyphs touching cell borders. Page/table/bounding-box
fragments remain available in the observation ledger after compilation.

## Selection and outputs

Selection partitions by source family, issuer, series, eligible population and
coverage scope. It selects the newest permitted document date in each partition.
Unknown dates or two variants on the latest date leave that partition unresolved
until an explicit selection is supplied. Retrieval time never substitutes for
document date. A newer held source stays in the inventory; selecting an older
permitted source does not assert current membership or nationwide completeness.

`batch.json` includes selected snapshots and campus identity candidates only.
Groups and duplicate language representations remain in `observations.json`,
along with historical revisions, scheme wording, validity and parent links.
They do not inflate campus candidate counts. All matches and evidence arrays
are empty, live availability stays unknown, and clinical statuses remain
unconfirmed. Every emitted campus has an open independent-review item.

Other outputs are `source_inventory.json`, `snapshot_selection.json`,
`held_rows.json` (locator/hash/reason only), `repeated_identity_groups.json`,
`report.json`, and `sha256.json`. Reports reconcile selected observations by
issuer, city/state, kind and unknown geography. Source coverage and pending VF
overlap have separate denominators. Held source row totals are unknown unless
separately inventoried; the compiler does not read them to obtain a count.

Snapshot IDs use source key plus raw SHA-256. Record IDs use the snapshot,
extraction SHA-256 and original locator; review changes therefore version the
derived records. No IDs depend on clock time, filesystem location or input
source ordering. Reusing a snapshot receipt with conflicting metadata is an
error. Persist the first retrieval receipt instead of rewriting it on replay.
Outputs publish atomically to a new directory; identical replay is accepted,
while changed output or unexpected files produce a conflict without overwrite.

## Local transfer decision inventory

`file_inventory` hashes every file in explicitly named roots and applies
item-specific dispositions from a local JSON mapping. Unknown files default to
hold. It never copies files, creates a source archive or grants transfer approval.

```sh
python -m research.acquisition.cghs.file_inventory \
  --root producer=data/local/new-sources/cghs \
  --root code=research/acquisition/cghs \
  --root tests=tests/research/acquisition/cghs \
  --decisions data/local/cghs-review/decisions.json \
  --out data/local/cghs-review/file-inventory.json
```

Decision keys are `alias/relative/path`, with `disposition` and `reason`.
Dispositions are `candidate_code_synthetic`, `candidate_metadata`, `hold_rights`,
`hold_source_review`, `hold_mixed_package`, and `hold_unclassified`. The output
must be outside all scanned roots. Candidates remain subject to Oliver's exact
file-list and recipient decision; every `transfer_authorized` value is false.
