# Search contract · v0

Dev 4 coordinates shared contract changes with Devs 1–3. The [first-pass brief](../FIRST_PASS_PROMPT.md) governs behavior. Use [synthetic fixtures](../../contracts/fixtures/search.json) while workspace access and the real schema are being verified.

## Prepared table

One row per preserved campus from Virtue Foundation. The proposed handoff fields are `facility_id`, `raw_row_ref`, `name`, `city`, `state`, `pin`, `latitude`, `longitude`, `description`, `capabilities`, `procedures`, `equipment`, and `record_source_urls`. The mapping from the real table belongs in the prep notebook. Store PIN as text, preserve evidence wording, normalize malformed optional fields to null or empty, and preserve raw lineage. A shared name alone cannot identify a duplicate. Preserve rows with missing coordinates for data inspection.

## Inputs and location

- `service` is `dialysis`, `mri`, or `trauma_care`.
- Location is `{city, state?}`, `{pin}`, or `{latitude, longitude}`. Validate finite coordinates and geographic bounds. Normalize place names and disambiguate city matches by state. Invalid or unmatched input returns a specific message. An ambiguous place returns choices and pauses the search until a choice is made.
- City or PIN resolution uses the median latitude and median longitude from valid Virtue Foundation facility coordinates for that place. Return an `approximate_location` flag for these cases. A place without usable coordinates produces an unresolved state.
- `radius_km` defaults to 50 and can expand. `limit` is capped at 3. Distance is straight-line Haversine in kilometers.

## Evidence and order

- Scan original description, capabilities, procedures, and equipment. Retain a verbatim excerpt and exact field for the best valid match. Direct terms document the requested service. Related terms such as nephrology for dialysis or a general emergency department for trauma care are indirect. Exclude planned, unavailable, and referred-out claims before classifying the surviving evidence.
- Within radius, return direct results by ascending distance, then stable `facility_id`. When there are no direct results, show up to three indirect leads in a separate “Needs confirmation” group, ordered the same way. Invalid coordinates are excluded from ranking.
- A facility card carries `facility_id`, `name`, location, `distance_km`, `evidence_strength`, `evidence_excerpt`, `evidence_field`, `record_source_urls`, `rank_explanation`, and `availability` (`unknown`). Record-level URLs use the label “Record sources”.

## Response states

Return `status`, `direct_results`, `indirect_leads`, and `location_choices`. Use `ok`, `needs_confirmation`, `no_match`, `ambiguous_location`, `invalid_input`, `unresolved_location`, or `unavailable`. Only one results group is populated. Location choices are populated for the ambiguous state. Surface a live warehouse error visibly. The synthetic fixture specifies key expectations for each case and omits echoed card text where the expected facility ID and evidence field identify it.
