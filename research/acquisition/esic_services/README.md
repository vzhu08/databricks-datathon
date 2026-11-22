# ESIC service-return research

This lane preserves complete dated hospital/service tables for issue #143 and compares candidate retrieval with the frozen national baseline. It produces research observations, not clinical decisions or approved campus identities. Raw sources, edition configurations, source excerpts, Marketplace rows and real outputs belong in ignored private working storage, followed by the authorized Databricks handoff.

`extract.py` reads a pinned five-column PDF annexure, retains every original cell fragment, joins continued service cells across pages, and rejects serial gaps, unexpected layouts and incomplete scope. Every row keeps its printed name/state beside separate normalization. The configuration supplies reviewed name aliases; the matching adapter also records an alias derived from the ESIC hospital column heading. These aliases are candidate-retrieval aids.

The extractor retains all service wording and comma/semicolon fragments, including vocabulary outside its lexical recognizers. Counts distinguish original service cells, delimiter fragments, recognized lexical mentions and distinct source-row/category pairs. Categories can overlap: a paediatric surgery phrase can contribute to more than one lexical category. These counts are not an exhaustive count of clinical services. Exact offsets permit inspection of every recognized mention, including repeats. Generic radiology, nephrology, ICU and orthopaedics never imply MRI, dialysis or trauma care. Current decisions remain unconfirmed.

## Replay

Use Python 3.10+ with the optional dependencies in `requirements.txt`. Tested with Python 3.12.14, pdfplumber 0.11.9 and lxml 6.1.1. Run from the repository root:

```sh
python -m research.acquisition.esic_services.extract \
  --pdf data/local/edition/source.pdf \
  --config data/local/edition/config.json \
  --output data/local/edition/extracted

python -m research.acquisition.esic_services.prepare_match \
  --edition-dir data/local/edition/extracted \
  --artifact-uri private-local:edition/source.pdf \
  --output data/local/edition/identity
```

The private configuration requires `edition_id`, `sha256`, `url`, `publisher`, `source_family`, `publication_date`, `retrieved_at`, `sanctioned_beds_date`, `occupancy_period`, `annexure`, one-based `pdf_pages`, `expected_rows`, `normalized_names` keyed by serial, and `reuse_status`. Optional `state_aliases` repairs state spelling separately from original fields. Service observation dates do not inherit publication, bed or occupancy dates. A changed PDF requires a new hash and a reviewed configuration. Existing output directories are not overwritten.

The identity envelope has one source snapshot and all original annexure records. It intentionally contains no asserted service evidence or confirmed matches. Pass its `batch.json` and `attributes.json` to the existing `research.matching.national` CLI with D's pinned base, source metadata, duplicate groups and postal mapping. Do not pass the entire postal metadata object where the CLI expects its `mapping` member. Source approval and rights remain separate from schema validity. No registry or shared contract is changed by this lane.

`controls.historical_rows` reads the four-column historical SST table while preserving PPP versus in-house bullet scope. `controls.release_paragraphs` selects one PIB release body and excludes the repeated print DOM. `quantity_observation` validates reviewed quantities and units against a cited paragraph; it never converts beds to machines, staffed slots or another branch's capacity. Training, historical activity and pooled-campus wording require separate interpretation before clinical use.

`audit.compare` accepts the complete prepared base, the frozen occurrence trace and one or more complete lane results. It verifies each original payload hash and occurrence key before comparing retrieval. Supply the full geography inventory to include zero-row states/UTs. It writes three unchanged baseline service decisions per occurrence and explicit source-only, overlap, incremental-reach and geography counts. It cannot approve a new service decision. A candidate from a rights-held source is exploratory and cannot be represented as an admitted production claim.

## Verification and handoff

```sh
python -m unittest discover -s tests/research/acquisition/esic_services -v
```

Synthetic regressions cover continued rows, layout/count failures, clinical non-inference, qualifiers, repeats, typed pooled quantities, print duplication, missing geography and identical source payloads under separate occurrence keys. Real extraction must also reconcile the complete printed serial range, verify exact spans, inspect representative page boundaries, and replay to identical output hashes. Keep original hashes, source terms and every held-edition disposition in the private manifest.

The #143 run covers all 59 rows of the March 2025 return and preserves all 10,088 VF occurrences and 30,264 decisions. The checked 2026 return supplies hospital/bed identity rather than modality columns. Annual-report bed occupancy, education and collective service statements do not become hospital-level modality evidence. The seven-site tender remains procurement intent. Two campus releases belong to the same ESIC reporting family, and their repeated pooled counts are not independent corroboration.

Only explicitly permitted source text, provenance, aggregate findings and authorized private occurrence references go to shared Databricks. ESIC/Sansad/EHA source rows and excerpts remain held until permission or an eligible replacement is established. Record fixture checks, full local analysis, live upload/readback and submission separately on #143, with the inventory on #160 and campus questions on #57. Oliver owns PR disposition, merge and release.
