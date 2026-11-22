# Facility evidence walkthrough (judges, real data)

Issue #252. A single Streamlit page that walks a judge through what the team's real evidence supports today:
the answer first (zero eligible destinations and the one check that would change it), then why (a four-step
evidence ladder for each case), then the national result, the Virtue Foundation trace at aggregate grain and
the separate Sanath Nagar public case, each with dates and source links.

## Run

```bash
pip install -r app/requirements.txt
FACILITY_EVIDENCE_DISPLAY=<path to the frozen display.json> streamlit run app/facility_evidence_demo/app.py
```

`FACILITY_EVIDENCE_DISPLAY` is either a local copy of the file or its `/Volumes/...` path, which is read
through the Databricks SDK with the app's own credentials. The path is configuration and is not written
in this repository. Ask Vincent for it.

## Data handshake

- The real `display.json` is never committed. Only its SHA-256 pin (`loader.PINNED_SHA256`), the field
  schema (`display_schema.json`), the loader and synthetic test data live in Git.
- The page checks the fingerprint first, then every key against the schema. An unset path, an unreadable
  file, a different fingerprint, an unknown or missing field, a non-https link, counts that do not add up, or
  any listed destination all give the **Data unavailable** state, with nothing shown in its place.
- There is no fallback to synthetic data. The synthetic file in `tests/facility_evidence_demo/` only loads
  when a test passes its own hash, and the page then says "Synthetic test file" above everything.
- No score, rank, travel time, free slot or percentage exists in the page or in the schema.
- The Volume location and custody manifest never appear on the page.

## Tests

```bash
python -m unittest tests.facility_evidence_demo.test_facility_evidence_demo
```

The two screen tests need Streamlit installed and are skipped otherwise.

## Judge walkthrough receipt

To be filled before release, on #252:

| Check | Owner | Status |
| --- | --- | --- |
| Field schema matches the frozen `display.json` | Vincent | done: `display_schema.json` is his schema from #252 (comment 7076517433) |
| Display scope and audience for each field | Vincent | cleared on #252 (comments 7076403964, 7076491893) |
| Every displayed figure against its source | D | payload verified on #252 (comment 7076496750); rendered page pending |
| Page renders the pinned edition, links open, dates read correctly | Andrew | pending real-file run |
| Publication and deployment | Oliver | not requested by this change |

D noted that the GitHub evidence links need repository access, so the page labels them "team record, needs
repository access" and carries the method, dates and denominators inline. An audience-accessible provenance
summary is Oliver's call.
