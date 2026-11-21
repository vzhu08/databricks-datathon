# PMNDP dialysis roster importer (SRC-C01)

Turns official named rosters of the Pradhan Mantri National Dialysis Programme
into a contract v1.0.0 acquisition batch. One interface serves the two Andhra
Pradesh parliamentary annexes, the Telangana list and any later official named
roster: each document is described by a descriptor and a table profile, so a new
roster needs a profile and no new code.

A listed centre, an establishment date or a past registration count says what a
document printed. None of them shows that a patient can get dialysis at that
centre today, so every claim here is `inconclusive`, unreviewed and linked to no
original facility. Campus confirmation belongs to the national comparison (#57).

## Run

```bash
# 1. Extract the printed rows, unchanged, with page/table/row locators (needs pdfplumber)
python -m research.matching.pmndp.extract --pdf data/local/pmndp/<document>.pdf \
  --output data/local/pmndp/<key>.rows.json

# 2. Import every document named in the manifest
python -m research.matching.pmndp.roster --manifest data/local/pmndp/manifest.json \
  --output-dir data/local/pmndp/out
```

Original documents, extracted rows and outputs hold source text. Keep them under
ignored `data/local/` or other authorized private storage. Only code and invented
fixtures belong in Git.

## Manifest

```json
{"documents": [{
  "key": "ap_establishment", "kind": "establishment", "state": "Andhra Pradesh",
  "publisher": "...", "family": "...", "url": "...", "sha256": "<raw SHA-256 of the PDF>",
  "retrieved_at": "2026-11-21T21:00:00Z", "published_date": null, "source_date": null,
  "license": "...", "independence_status": "shared_origin",
  "programme": "wording the document uses for the programme (optional)",
  "rows": "ap_establishment.rows.json",
  "profile": {"columns": {"serial": 0, "district": 1, "name": 2, "established": 3},
              "skip": ["^sl"], "carry": ["district"]}
}]}
```

- `kind` is `listing`, `establishment` (needs an `established` column) or
  `registrations` (needs `registrations`: period label to column index).
- `family` is the upstream source family. Documents of one family that list the
  same centre are marked `shared_origin_overlap` and are never counted as
  independent confirmation.
- `sha256` must equal the `source_sha256` recorded in the rows file, so rows
  extracted from another file are refused. The same document listed twice is
  refused.
- `source_date` is the date the document's content refers to. Evidence is
  `historical` with that date, or `undated` when it is null.
- `profile.skip` holds patterns for header rows, `profile.aggregate` overrides
  the pattern for total rows, `profile.date_formats` adds date layouts, and
  `profile.carry` names columns that inherit the previous row's value when a
  merged cell leaves them empty.

## Output

| File | Layer |
|---|---|
| `raw_rows.json` | Every programme row as printed: document, page, table, row, serial, original name, district, address, dates and counts, plus flags |
| `campus_candidates.json` | Distinct campus candidates with stable IDs and the raw rows behind each |
| `claims.json` | What each row supports: `programme_listing`, `centre_established`, `historical_registrations` |
| `batch.json` | Contract v1.0.0 batch: one snapshot per document, one external facility per campus and document, evidence, review items, no matches |
| `rejects.json` | Rows not imported, with a reason, and printed totals kept as context |
| `report.json` | Counts by document, layer, reason and flag |
| `manifest.json` | Importer version and SHA-256 of every input and output |

Rules worth knowing:

- **Rows reconcile first.** Each document's rows add up: read = header or blank
  + totals + programme rows + rejects. Missing or repeated serial numbers raise a
  review item.
- **Rejects.** `too_few_cells`, `name_missing`, `serial_unreadable`. A rejected
  row is never imported and always gets a review item naming its locator.
- **Totals** printed in a document are kept as context and never become a
  facility or a claim.
- **Campus identity** is family, state, district and centre name. A name that
  appears once per district in each document merges across documents. The same
  name in another district is another campus. Several centres with one name in
  one district stay apart and merge only on an identical address; a row that
  cannot be assigned to a branch is flagged `same_name_branch_unreconciled`.
- **Zero registrations** is a recorded value of 0 for that period, not a missing
  one. A blank or unreadable count is flagged and produces no claim.
- **One external per campus and document**, so evidence always cites the
  snapshot it was read from and D's validator needs no reviewer for it.
- **Repeat import** of the same inputs gives byte-identical outputs, in any
  manifest order.

## Tests

```bash
python3 -m unittest discover -s tests/research/matching -p 'test_roster.py' -v
```

All rows in the tests are invented. The batch built from them passes D's
`validation.semantic_check`.
