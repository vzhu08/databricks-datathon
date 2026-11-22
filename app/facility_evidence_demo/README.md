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
| Every displayed figure against its source | D | payload verified on #252 (comment 7076496750) |
| Page renders the pinned edition, links open, dates read correctly | D | passed at `fb9d82a` with the production pin, plus the missing-file view ([real-browser receipt](https://github.com/vzhu08/databricks-datathon/issues/252#issuecomment-7076644560)); three wording corrections from it applied after that |
| Deployed app identity reading the `/Volumes/...` path through the SDK | Oliver | untested; local copy only |
| Publication and deployment | Oliver | not requested by this change |

D noted that the GitHub evidence links need repository access, so the page labels them "team record, needs
repository access" and carries the method, dates and denominators inline. An audience-accessible provenance
summary is Oliver's call.

## Area view (#270)

A second section, "Where the records place facilities", shows every original record once at the most specific
level its evidence supports: directory campus category, locality, city only, postal area, district only or
unknown. It reads its own audience-cleared aggregate:

```bash
FACILITY_AREA_DISPLAY=<path to the cleared area aggregate> FACILITY_EVIDENCE_DISPLAY=... streamlit run app/facility_evidence_demo/app.py
```

- The file must match `area.AREA_PINNED_SHA256` and `area_schema.json`. That schema is B3's cleared shape and holds counts and labels only. It has no field for an area name, boundary, point, travel time, rank,
  capacity or service.
- The counts must reconcile: the levels sum to the originals, the campus categories to the campus count and
  the reasons to the unknown count.
- Pinned to B3's cleared aggregate, SHA-256 `0ac26497…2032f` (#252 comment 7077110474, #270 comment 7077111112).
  Any other bytes, an unset path or a missing file give "Area data unavailable", and the rest of the page is
  unaffected.
- City-only records read "City only", with no neighbourhood or point inferred, as F's acceptance check on
  #270 requires. The campus category says it is not an independently verified building or entrance.
- A richer view needs area names or boundaries cleared for this audience, and reviewed building evidence.
  Exact membership of the area-only records stays with the data owners.
