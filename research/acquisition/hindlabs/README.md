# HINDLABS local adapter

Owner: Developer K, [source intake #75](https://github.com/vzhu08/databricks-datathon/issues/75).
This module compiles frozen HLL/HINDLABS directory HTML and located documentary
annotations into the acquisition contract v1 envelope. It makes no network calls.
Only generic code and synthetic examples belong in Git. Originals, excerpts,
annotations, inventories and generated packets stay in ignored local storage.

## Evidence boundaries

- Each directory node is a source identity. A collection point, laboratory or
  imaging unit never becomes its host hospital. District taxonomy is retained in
  the private ledger and is not substituted for city. Nearby/host suffixes cannot
  supply a modality; conflicting unit labels and categories remain unresolved.
- An explicit node-to-host relation needs the unit label, campus label and an
  exact located source excerpt. Even an `onsite` relation remains an unconfirmed
  campus claim; the adapter creates no VF identity links.
- Remote reporting, proposed installations, installation-only records and
  operator closures do not establish an operating on-site MRI service. A closure
  does not close the host hospital or establish a negative service claim.
- Expiry uses an explicit validity end and the required `--as-of` date. The end
  date is inclusive. Partial months, financial years and conflicting dates stay
  in the ledger; retrieval dates never supply operating dates. The five-table
  envelope contains only frozen source facts and is identical across assessment
  dates. Expiry, future validity and candidacy belong in the ledger/report, which
  record `as_of`. An annotated `expired` status requires a validity end and is
  normalized to `dated` or `historical` in the immutable source evidence.
- `onsite_mri_documentary_candidate` is a queue for reviewing a named unit's
  documentary service claim, including historical claims. It is not evidence of
  a confirmed host, present operation or VF service. Every emitted evidence row
  is inconclusive, unlinked and queued for review.
- All snapshots share HLL lineage. Maharashtra nodes carry a potential overlap
  flag for #66; overlapping publisher material is not independent confirmation.
  The nine previously reported MRI unit references remain unconfirmed for VF.
  National incremental coverage requires comparison with all 10,088 original VF
  rows and remains unknown here.

## Private input format

`--root` contains `manifest.json`, `annotations.json` (or a relative path supplied
with `--annotations`) and the frozen files named by the manifest. The synthetic
test corpus in `tests/research/acquisition/hindlabs/test_adapter.py` demonstrates
the complete input format without including original source material.

Each manifest source supplies `key`, `url`, `path`, `sha256`, `retrieved_at` in UTC,
`publisher`, `reuse_basis` and `status: "ok"`. `publication_date` is optional and
must be a complete ISO date, not a reporting period. `directory_pages` is checked
against the first page's final-page link and each page's current-page marker.
Directory source keys are `branchlocator`, then `branchlocator_01`, etc.
Sources marked `delivery_status: "restricted_hold"` are skipped before being
opened and cannot be referenced by annotations. Keep both held tenders excluded.

Each annotation supplies `annotation_key`, `source`, `kind`, `excerpt`,
`assertion` and `record`. Use a one-based integer `page` for PDF evidence or an
explicit CSS `selector` selecting exactly one HTML element. The
whitespace-normalized excerpt must occur there and include the emitted unit name.
Published locators are derived from the validated selector/page; input display
`locator` strings are ignored. MRI must occur in the named unit's own source
statement or row, after excluding host names and location suffixes. Unbound MRI annotations retain
their identity and review flags but emit no MRI service claim or candidate.

Record fields include `name_original`, `unit_class` and optional geography,
`mri_scope`, `host_campus`, `host_relation`, `host_excerpt`, `host_location` and
`quality_flags`. Any host claim, including an unresolved one, requires a
`host_location` object with a `page` or `selector` and optionally `source`
(defaulting to the claim source). The adapter independently checks the host quote
at that location against an eligible, hash-verified source; both unit and campus
labels must occur in the quote. Free-text input `host_locator` values cannot
provide this binding. The ledger retains the derived host locator, source URL and
snapshot ID. Host relations are `onsite`, `nearby`, `remote` or `unresolved`.
Nearby/remote source wording overrides an incompatible `onsite` annotation, whose
original value remains in `declared_host_relation`, and prevents an onsite
candidate. These conservative checks do not replace campus/service review.

Scope is checked against the original enclosing statement or complete HTML table
row for both claim and host, not just the supplied quote. Selecting a nested span
or cell cannot hide teleradiology, nearby, closure, negative or referral-only
wording. Same-unit statements and continuations such as “Images are acquired
elsewhere” stay in scope; an unrelated adjacent statement naming another unit
does not veto an onsite claim. Ambiguous quotes matching multiple HTML blocks or
rows require a narrower selector or quote. PDF scope uses statement spans in the
validated page; without sentence boundaries, the larger passage is retained for
conservative review rather than guessing a table or column split.

The ledger records `claim_scope_context`/`claim_scope_locator` and
`host_scope_context`/`host_scope_locator` separately. Context locators identify the
enclosing HTML element or PDF page and zero-based, end-exclusive character spans
in its whitespace-normalized text (or the complete HTML row). Relevant statement
fragments are separated by newlines. Original evidence/host excerpts and validated
claim/host locators remain unchanged; expanded context is never substituted for a
quoted excerpt.

Optional `dates` hold complete validity dates and/or the original
partial operating dates and date-conflict notes. Annotation selection and meaning
remain human review responsibilities.

## Run and verify

Use Python 3.9 or newer. Install the adapter and shared validator dependencies in
a local virtual environment, then run from the repository root:

```sh
python -m pip install -r research/acquisition/hindlabs/requirements.txt -r databricks/enrichment/requirements.txt
python -m unittest discover -s tests/research/acquisition/hindlabs -p 'test_*.py'
python -m research.acquisition.hindlabs.adapter \
  --root data/local/new-sources/hindlabs \
  --output data/local/new-sources/hindlabs/adapter-release-v1 \
  --as-of 2026-11-21
```

The output directory contains `batch.json`, `claim_ledger.json`, `summary.json`,
`duplicates.json`, `rejects.json` and `output_hashes.json`. Source bytes are checked
against the manifest. Conflicting node payloads, missing pages, invalid excerpts
and duplicate immutable IDs stop the entire build. Identical repeated node IDs
are recorded as duplicates; separate nodes with the same name remain separate.
Outputs are staged together and conflicting existing releases are never replaced.
IDs use the `hll_hindlabs` namespace, source URL/content hash and record identity;
they do not reuse the earlier private acquisition script's ID namespace.
Use one revision of this intake; do not import both namespaces as independent evidence.

The synthetic suite runs the adapter CLI before, on and after validity boundaries,
then imports all four envelopes together through
`databricks/enrichment/validate_batch.py` with an empty synthetic base, preserving
one copy of each source claim. It also exercises forged locators, unrelated unit
names, separately located HTML/PDF host evidence, clipped scope qualifiers,
closure/referral-only wording and unrelated neighboring statements/rows.
For private packets, run that validator separately using the authorized base. Fixture checks,
local original-source replay, live Databricks checks, publication and submission
are distinct results. This adapter performs none of the last three.

The earlier PR review builds and private packets are superseded for source
binding. Their annotations need explicit host locations and quotes naming the
unit before they can be rebuilt under these checks. Do not import old and new
review builds together. This correction's regressions use synthetic inputs;
the previously reported private replay does not validate the stricter annotations.

## Local inventory for Oliver

```sh
python -m research.acquisition.hindlabs.inventory \
  --root data/local/new-sources/hindlabs \
  --output data/local/new-sources/hindlabs/transfer-inventory-v1.json
```

The inventory records each local file's path, SHA-256, size, material type, known
reuse basis and exclusion reason. Held originals and identified derivatives,
mixed archives, response headers and superseded replay copies are excluded.
Runtime/cache directories and symbolic links are listed as skipped. The inventory
does not include itself. Use a new filename for each inventory revision.

All entries have `transfer_authorized: false` and `transferred: false`. Remaining
files await Oliver's exact file list, recipient and rights decision. Public
availability alone is not recipient reuse clearance. This tool neither packages
nor transfers anything; the inventory itself remains private.
