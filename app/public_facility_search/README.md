# Public facility search

The bundled collection contains one operator-published claim for each of two named Pune hospitals. It is a bounded public-source lookup for the judge walkthrough. Each URL supports the service wording and lists the hospital contact shown. The source publication dates are unknown. `checked_on` records when the project reviewed the page. Contact labels distinguish the main line or appointment desk from a dialysis-unit line.

From the repository root, run `python -m app.public_facility_search --place Pune --service dialysis`. From the deployed `app/` directory use `python -m public_facility_search --place Pune --service "maintenance haemodialysis"`. Streamlit can import `search_public_facilities(place, service)` directly from `public_facility_search`. Include `claims.json` alongside the module when packaging.

General dialysis returns both claims in collection order. A haemodialysis or maintenance dialysis query returns only KEM. The lookup ignores case and surrounding or repeated whitespace. Unsupported, blank or unmatched requests return an empty list. A miss means this collection has no matching claim. Collection order carries no distance, treatment suitability or availability ranking.

The location applies to the named operator in the stated city. The source supports an operator-reported service. Staffing, patient entrance and current availability are unknown. Call the public hospital contact to confirm. These two records contribute no reviewed VF match or service decisions to the national denominator of 10,088 original occurrences, 10,077 upstream IDs and 30,264 service decisions.

Only the curated public facts and source links are packaged. Each claim is paraphrased from its operator’s page. The collection reads independently of the synthetic campus files, signed-in simulation, private workspace and national snapshot.
