# Record integrity check

A repeatable check of every Virtue Foundation (VF) facility row for signs that a record is planted, fabricated or corrupted. It **flags, it never deletes**: each original row gets a score, a tier (`high`, `medium`, `low`, `none`) and plain-language reasons, so search and routing can warn about or filter suspect rows. Rows that independent sources already corroborate are marked lower risk.

Research only. Disposition of the results belongs to the data owner (Vincent, #57). Nothing here changes shared data.

## Run

```bash
python3 -I research/record_integrity/check_records.py \
  --base base.json \                       # VF export: [{facility_id, source_row}]
  --postal postal_rows.json \              # India Post pincode directory (optional)
  --footprint footprint_check/point_flags.csv \          # optional
  --corroboration independent_check/vf_corroboration.csv \  # optional, repeatable
  --corroboration open_data_probe/independent_corroboration.csv \
  --corroboration unconventional_sources/openalex_identity_pairs.csv \
  --out <folder outside Git>
```

It runs in about 6 seconds on the full 10,088-row snapshot. Outputs:

- `integrity_flags.csv`: one row per original row, sorted by score, with `tier`, `families`, `reasons`, `details`, `corroboration`. No phone numbers, emails or people's names are written.
- `summary.json`: counts per reason, family and tier.

Keep both outside Git (they hold Marketplace row content). Tests use synthetic rows only: `python3 -m unittest tests.research.record_integrity.test_check_records`.

## Checks

| Family | Reason | Weight |
|---|---|---:|
| structure | `malformed_row` (columns shifted, wrong types), `name_missing`, `placeholder_text` (masked "XXXXXXX 000000" addresses, "placeholder", lorem ipsum) | 6 |
| location | `coords_outside_india`, `coords_null_island` | 6 |
| location | `far_from_pin_100km` (from every post office of the row's PIN) | 4 |
| location | `pin_state_mismatch`, `point_in_other_state` (post offices within 10 km agree on another state), `coords_field_disagree`, `coords_shared_unrelated` | 3 |
| location | `far_from_city_50km` (footprint check), `pin_invalid_format`, `pin_not_in_directory`, `coords_low_precision` | 2 |
| location | `far_from_pin_25km`, `no_building_within_50m` (footprint check) | 1 |
| contact | `phone_shared_unrelated` (same phone as a differently named row more than 5 km away), `phone_placeholder`, `email_placeholder` | 2 |
| contact | `phone_invalid` | 1 |
| text | `description_duplicate_unrelated` (identical once names are removed, across unrelated names) | 3 |
| text | `description_templated` (same, across related names), `description_names_other_state` | 1 |
| plausibility | `capacity_implausible`, `doctors_implausible` | 3 |
| plausibility | `year_implausible`, `small_type_claims_large_services` | 2 |

"Related" names share a distinctive word (not "hospital", "clinic", "care" and similar), so chain branches do not flag each other.

Tiers use the summed score after corroboration: `high` ≥ 6, `medium` ≥ 3, `low` ≥ 1. Strong corroboration (two or more agreeing independent families, or an OpenAlex `would_confirm`) subtracts 3 and some corroboration subtracts 1, except for structural and outside-India reasons, which corroboration never offsets.

## Result on the full snapshot (2026-11-22)

| Tier | Rows | Rows with coordinates |
|---|---:|---:|
| high | 794 | 705 |
| medium | 801 | 801 |
| low | 1,222 | 1,222 |
| none | 7,271 | 7,241 |

- **Structure (94 rows, all high):** 35 rows with shifted columns, 65 with no usable name, 5 with masked or placeholder text. These cannot be routed to.
- **Location (2,135 rows; 701 high):** 6 points outside India, 1,047 points more than 100 km from every post office of their own PIN, 92 points whose surrounding post offices are in another state. The PIN check and the earlier city check are independent and agree: 656 of the 1,047 far-from-PIN rows are also far from their city's other rows.
- **Contact (872), text (140), plausibility (21):** mostly weak on their own; they matter when they stack with location reasons.
- **Corroboration:** 1,549 rows have independent support; only 90 of them still end up medium or high.

### Planted or fabricated?

No sign of a planted batch. Flagged rows do not share thin provenance: every row has at least two source URLs, and high-tier rows have *more* sources (median 27) than clean rows (median 8). The pattern fits over-merged records, where fields from different places were combined into one row (for example a Hyderabad name with a Delhi PIN and a Puducherry point), rather than invented rows. Either way the location cannot be trusted, so the recommendation is the same: do not route to `high` rows without a source check, and show a caution on `medium` rows.

### Limits

- India Post office coordinates are noisy, so distance is measured to the nearest office of the PIN; a point is flagged only when it is far from all of them.
- Shared phones flag call centres of chains whose branch names differ; `phone_placeholder` can hit real vanity numbers. Both carry low weight.
- No imagery or web pages were checked. A `high` row may still be a real facility with a bad pin.
