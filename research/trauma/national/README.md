# MoHFW trauma programme brief

The B3 reader extracts the ruled tables from the registered NPPMTBI PDFs and emits a v1.0.0 producer batch. It keeps the programme level, printed functionality and construction or support stage distinct. The records describe historical programme observations. Every service observation is inconclusive for clinical use, and every base link is unresolved.

## Reproduce the B3 build

Use Python 3.10 or later. From the repository root, install the dependencies and point the runner at the frozen inputs listed in the [B3 handoff](../handoffs/B3.md).

```powershell
python -m pip install pdfplumber==0.11.7 'jsonschema[format-nongpl]==4.26.0'
$b3 = 'data/local/trauma/acq-b01/B3'
python -m unittest discover -s tests/research/trauma/national -p 'test_*.py' -v
python -m research.trauma.national --manifest "$b3/acquisition.json" --visual-review "$b3/visual_review.json" --output-dir $b3
```

The output directory contains `batch.json`, `temporal_claim_ledger.json`, `lineage.json`, `coverage.json` and `artifact_inventory.json`. The inventory records the registered and resolved URLs, UTC retrieval times, validation inputs, absolute raw paths and checksums. Run with the original input paths and preserved review timestamps for a byte-identical envelope. Moving the inputs changes the absolute artifact URIs.

To acquire the original PDFs again, use the two registered URLs and try the documented archive capture if the legacy URL returns 404. Use a bounded download and capture the resolved URL, timestamp, HTTP result and SHA-256 for each attempt.

```powershell
$b3 = 'data/local/trauma/acq-b01/B3'
$source = (Get-Content 'contracts/enrichment/source_registry.json' -Raw | ConvertFrom-Json).sources |
  Where-Object source_key -eq 'mohfw_trauma_program'
New-Item -ItemType Directory -Force -Path "$b3/raw" | Out-Null
curl.exe --fail --location --connect-timeout 10 --max-time 45 --max-filesize 10000000 --output "$b3/raw/primary.pdf" $source.entry_url
curl.exe --fail --location --connect-timeout 10 --max-time 45 --max-filesize 10000000 --output "$b3/raw/older.pdf" $source.related_urls.older_copy
# Legacy fallback after the observed HTTP 404
$archive = 'https://web.archive.org/web/20250124111309id_/https://mohfw.gov.in/sites/default/files/Prog%20brief%20Trauma%20component%20.pdf'
curl.exe --fail --location --connect-timeout 10 --max-time 45 --max-filesize 10000000 --output "$b3/raw/older.pdf" $archive
Get-FileHash "$b3/raw/*.pdf"
pdftoppm -r 120 -png "$b3/raw/primary.pdf" "$b3/primary"
```

For new bytes, keep both versions in a new ignored run directory. Supply `acquisition.json` with `primary` and `older` entries containing `file` (relative to the manifest), `registered_url`, `resolved_url`, `retrieved_at`, `sha256` and `retrieval_attempts`. Use a fresh visual review for each distinct hash. The review records all inspected PDF page numbers, each annexure's Rajasthan count, the printed row values and page, date observations with locators, and open campus questions. The existing ignored review file provides the exact field layout. A reviewed byte-identical duplicate contributes lineage and inventory only. A changed edition is retained under a distinct snapshot within the same source family.

The reader adds a missing top rule to the continuation-page grid, checks serials against each table's denominator and carries rows under merged state headings only within the same section. Visual comparison checks the Rajasthan serials, pages, names, levels and printed functionality. Plain-text order can differ from the drawn cell layout. Row excerpts preserve printed cell text joined by line breaks. The evidence locator also names the heading and page that provide the trauma-programme context.

Snapshot IDs use the registered source key and the PDF's full SHA-256. Facility and evidence IDs use the snapshot ID, subsection and serial, then the claim kind for evidence. A serial locates a programme row. It does not identify a hospital across documents. College and hospital aliases, locations embedded in names, and potential version disagreements stay visible for campus review.
