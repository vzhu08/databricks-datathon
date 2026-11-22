# Search quality overlay (optional, off by default)

`app/ranking/quality.py` can read a per-facility overlay CSV and adjust the facility search. Without an overlay it changes nothing. The app has not been wired to it yet. A caller opts in by passing `overlay=` to `search_with_quality`, or by setting `FIND_CARE_QUALITY_OVERLAY` to the overlay's path and calling `overlay_from_env()`.

| Overlay field | Effect on the search |
|---|---|
| `point_status=repaired`, `latitude`, `longitude`, `location_method`, `location_precision` (`building`, `pin_area` or `city`) | The row is ranked at the repaired point. Its card carries `location_estimate`. |
| `point_status=unplaced`, `location_checks` | The row is not ranked by distance. For a PIN or city search, it is listed under `unplaced_matches` with no distance and a `location_warning`. The warning uses the reason codes in the Find care screen's `LOCATION_CHECKS` (PR #242). |
| `point_status=excluded` | The row is left out. This is for structurally broken records. |
| `duplicate_group` | The group collapses to its member nearest the origin. The card names the others in `also_listed_as`. |
| `evidence_dialysis`, `evidence_mri`, `evidence_trauma_care` | A badge on the card (`evidence_level`). It never filters or reorders results. |

`build_overlay.py` makes the CSV from the research outputs: record integrity, pin repair, duplicates, chain campuses and the evidence ladder. Those inputs and the overlay itself hold row-level data. Keep them in Databricks or local storage, never in Git. Tests use synthetic rows only.
