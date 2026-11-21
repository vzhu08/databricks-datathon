# Rajasthan DHIS letter

The collector processes a local copy of the June 2025 Rajasthan National Health Mission letter. It emits contract v1.0.0 institutional identities, administrative milestones by annexure, district review flags and a reproducible audit sample. Source and derived records belong in ignored storage. The national and Rajasthan matching inputs are documented in [the A03 handoff](MATCHING_HANDOFF.md).

## Source and current coverage

The state publisher lists IT Cell letter 96 on June 9, 2025. The indexed official PDF renders Annexure 1 as a facility registration list with serial, district and name columns. The indexed table has consecutive serials 1–20 and nine distinct printed district labels. Five of those 20 indexed names contain a different district from that nine-label vocabulary as a whole word. A place in a facility name is a review lead and may have an explanation. Transaction rules and the worked registration example elsewhere in the indexed document are outside this institutional list. [Publisher index](https://rajswasthya.rajasthan.gov.in/link/oldletter.php?year=2025) · [Letter 96](https://rajswasthya.rajasthan.gov.in/admin/upload/letter/2025/07/96%20Dt.09.06.2025%20Letter%20to%20CMHO%20for%20DHIS%20%281%29.pdf)

Direct HTTPS and HTTP connections timed out before returning bytes on Vincent's review host. The Internet Archive availability check for the publisher URL returned an empty snapshot list. The indexed table helps identify what to inspect. Original SHA-256, eligibility across the full PDF, source-level district totals, overlap and manual audit still need the original bytes. The original-PDF audit has zero reviewed rows and an unknown source denominator. Permission to redistribute raw bytes and row excerpts is unconfirmed.

## Read a verified original

Install `research/acquisition/requirements-pdf.txt`. Preserve the publisher URL, first retrieval time, original document date, immutable artifact URI and original SHA-256 in the private layout JSON. Inspect every annexure visually to identify actual facility tables and the precise meaning of their headings. Include only the three institutional columns shown below. Any changes to column order or meaning require inspection. For printed table headings with different spelling, `header` accepts their exact three labels in serial/district/name order. The following values and names are synthetic.

```json
{
  "sha256": "RAW_PDF_SHA256",
  "url": "https://example.invalid/letter.pdf",
  "retrieved_at": "2025-08-01T12:00:00Z",
  "document_date": "2025-06-09",
  "artifact_uri": "file:///permitted-storage/letter.pdf",
  "license": null,
  "district_labels": ["North", "South"],
  "tables": [{
    "annexure": "A",
    "page": 2,
    "table": 1,
    "heading_page": 2,
    "heading": "Synthetic list of registered facilities",
    "status": "registration",
    "reviewer": "layout reviewer",
    "header": ["S. No.", "District", "Name"]
  }]
}
```

The reader uses one-based PDF page, table and physical row numbers. For an image-only table, supply a `visual_transcript` array with the exact original three-column header and cells, after viewing the original page and checking the heading. Its provenance is the raw digest, page, table and named layout reviewer. Keep wrapped lines in the same cell when possible. The parser joins a continued name-only row to its preceding entry within that table and records both physical row bounds. An orphan continuation on a later page requires visual resolution. Printed districts persist even if missing or inconsistent. The private vocabulary and word-boundary rule make review flags reproducible. A name may mention several places.

The allowed status values are `registration`, `onboarding`, `eligibility`, `incentive_claimed`, `incentive_approved`, `incentive_paid` and `unknown`. Choose each status from the specific annexure’s meaning, recording its heading and page. Preserve distinct entries for a campus in multiple administrative stages. The parser emits zero facility matches and zero clinical service claims.

```sh
python -m research.acquisition.dhis --pdf /private/dhis.pdf \
  --layout /private/layout.json --output-dir /private/dhis-first-pass \
  --explicit-batch /private/acq-a03/explicit.json
```

Outputs include the contract envelope, source-local row ledger, coverage and audit report, and SHA-256 manifest. The optional overlap report keeps IDs from both batches for every exact normalized-name candidate. It emits zero confirmed campuses. The audit sample takes up to 20 locators, cycling through annexures and pages. A second reader should reopen the original pages and check the name, district, serial, row boundaries and annexure status. Record the actual corrections in the private review history. Use a new version for any corrected input.

Put completed reviews in the layout's `audit` object keyed by the selected `record_locator`. Each entry needs `reviewer`, `reason`, `outcome` (`pass`, `uncertain` or `fail`) and the `fields_sha256` from the candidate row ledger. Rebuild in a new directory. Stale decisions or failed checks stop release. An uncertain audit creates an open review item. A missing audit leaves the report in `pending_visual_checks`.

To verify the synthetic cases, run `python -m unittest discover -s tests/research/acquisition -p 'test_dhis.py' -v`. The original-PDF audit and source permissions remain open in [#30](https://github.com/vzhu08/databricks-datathon/issues/30).
