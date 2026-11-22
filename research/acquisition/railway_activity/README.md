# Railway hospital activity — #165

This producer preserves historical, source-keyed equipment and operating
observations. It does not publish clinical statuses or confirm VF campus links.
Real PDFs, extraction profiles, observations, source text, and VF outputs belong
in ignored private storage and the authorized Databricks Volume.

The [national Railway Board index](https://rb.indianrailways.gov.in/public/cms/viewContents?documentMasterId=12547)
exposes successive annual editions. The scoped national alternative is the
[CAG 2024 railway health audit](https://cag.gov.in/rly/new-delhi-ii/en/audit-report/details/120367)
and [2014 predecessor](https://cag.gov.in/en/audit-report/details/1090).
Their reporting periods differ from their publication dates and retrieval dates.
The [CAG copyright policy](https://cag.gov.in/en/page-copyright) permits accurate,
attributed reproduction, with third-party material excluded. The private
profiles retain the source terms, attribution, original bytes' SHA-256,
publication date, period, and extraction limits. Mirrors with the same hash are
one edition. Both audits share a railway health-record origin; two editions do
not establish independent clinical corroboration.

## Meaning and scope

- Equipment **shortfall** is distinct from available or functional stock.
  `NS` means no shortfall. Neither `NS` nor numeric zero establishes service
  absence, current availability, or installed inventory.
- The OT deficiency combines service types and staffing. The blood-bank
  deficiency combines in-house provision and local arrangements. Preserve the
  original scope instead of assigning trauma status or a narrower absence.
- List cells marked `NA` or `0` remain in raw cell records but produce no
  hospital-level deficiency observation. Comma-separated source hospital
  labels remain abbreviations; this code does not expand or join them.
- Historical referral volumes, onsite capacity, equipment units, and combined
  CT/MRI totals have separate measures and units. Total and component counts
  cannot be added together. Patient counts do not establish distinct patients
  unless the source says so.
- Every repeated measurement has an edition and locator. Campus keys group
  identical source strings within an edition, not reviewed real-world campuses.
  The raw source and profiles retain contradictory or differently scoped claims.

## Replay

Use Python 3.10+ with `pdfplumber` (the extraction profiles identify the reviewed
parser/layout). The repository's matching dependencies are also needed for its
existing state-label normalization. Install this directory's requirements in an
isolated environment if they are not already available.

```sh
python -m unittest discover -s tests/research/acquisition -p test_railway_activity.py -v
python -m research.acquisition.railway_activity.run \
  --base /private/path/base.json \
  --metadata /private/path/source_metadata.json \
  --baseline-manifest /private/path/coverage147/manifest.json \
  --edition /private/path/audit.pdf /private/path/reviewed-profile.json \
  --support /private/path/source-policy.html \
  --support /private/path/edition-census.json \
  --as-of YYYY-MM-DD --output /private/path/new-packet
python -m research.acquisition.railway_activity.run --verify /private/path/new-packet
```

The reviewed profile specifies exact raw hash, page count, title/legend anchors,
logical table shape, metric semantics, and expected measurement counts. For
prose, it specifies an exact span in whitespace-normalized `pdfplumber` text,
the numeric token, unit, named hospital, and scope. A changed hash, span, shape,
or count stops the run. PDF page numbers are one-based; row and column indexes
are zero-based. Logical columns omit only merged-cell `None` placeholders.
Visual verification of source pages is required when approving a new profile;
numeric-token validation alone cannot prove the reviewer's interpretation.

The comparison checks the full base hash and the 10,088-occurrence /
10,077-upstream-ID frame, retaining the eleven duplicate pairs and sparse rows.
It emits 30,264 **source screens**, not 30,264 adjudications. Literal normalized
name equality is a retrieval lead only; abbreviation expansion and city-only
matching are deliberately outside this producer. Missing accepted links do not
mean no real-world overlap. State totals use the original label with the
existing normalizer, including both unknown buckets and zero-count states;
they do not apply PIN-derived geography.

`full-frame-screen.jsonl` preserves occurrence keys, upstream IDs and original
payload hashes. It records no status change and leaves `baseline_status` null.
`summary.json` binds the frozen #147 baseline and separates measured current
eligibility (zero for these historical, unlinked observations) from unmeasured
campus overlap and candidate overlap. D owns the reviewed status ledger;
Vincent owns campus linkage. Neither gets inferred here.

## Private delivery

The packet includes original cleared source PDFs, private profiles, per-edition
extractions, observations, retrieval leads, full-frame screen, baseline/source
metadata references, and explicitly supplied policy/census support. Pass only
cleared support files; do not include restricted webpage snapshots or the
parked #71 directory rows. The baseline base itself is referenced by hash and
table/version rather than uploaded again.

`manifest.json` names every packet file with byte length and SHA-256. Its packet
ID hashes the file manifest. A recipient downloads the entire packet into a new
private directory and runs `--verify`. Upload/readback status is recorded in a
separate delivery receipt, never by rewriting the immutable evidence packet.
Local success is not a live Databricks check. This lane runs no submission or
checker. Edition dispositions and source/access gaps belong on #160 and #165;
the integration lead owns the shared board.
