# Pune evidence-enriched planning roster v1

This variant uses the same Pune district boundary as the original 12-site roster. It retains ten original anchors and adds two named hospital outlines using documented civic addresses. The sidecar records public, branch-specific service scope. Patient demand, staffing, slots and travel are simulated. Source agreement establishes a planning location and the operator pages establish reported scope. Current operation, entrance location and available appointments require separate evidence. [Pune source and audience decision](https://github.com/vzhu08/databricks-datathon/issues/323#issuecomment-7081974455)

## Replay the selection

1. Follow the [original geography recipe](README.md) to use the pinned nationwide HOT/OSM extract, India 2021 geoBoundaries ADM2 edition and official National Health Portal (NHP) CSV. Use the resulting complete Pune OSM roster and original agreement roster, and keep the original agreement evidence file for branch review. The original roster has SHA-256 `b62f377a61f9dee796ff0a4c56afcad96195a3ad196c1e4806dcc8c119e63f35`. The complete Pune OSM roster has SHA-256 `31a26839d0122ec532cc8c41c261198b3df984c79e405689b27a49700533d439`.
2. Keep the ten retained planning IDs in original order. Remove `C01` and `C10`, which lacked admitted evidence for the four requested classes. The two replacements are separate, manually reviewed civic-address matches. In the NHP CSV, use the printed Maharashtra and Pune labels, a recognizable operator-specific name, and the same civic number and road or area as the operator and independent public address reference. Check `Address_Original_First_Line`, `Location` and `Pincode` together. Retain one distinct valid WGS 84 point per named civic site, including when two rows repeat that point.
3. Find the unique named OSM hospital outline for each replacement in the full Pune roster. Use the outline's interior point and require a separation of at most 100 m from the NHP point. Append Jehangir as `C13` and KEM as `C14`. The two admitted separations range from 22.7 to 29.0 m. The final roster has six mapped facility points and six outline interior anchors. All 12 anchors are distinct and the closest pair is 449.9 m apart. [Pune district listing](https://pune.gov.in/en/public-utility/jehangir-hospital/) · [Jehangir operator](https://www.jehangirhospital.com/) · [KEM operator address](https://www.kemhospitalpune.org/contact-us/) · [NCRA civic directory](https://www.gmrt.ncra.tifr.res.in/general/TelDir/finaldirectory.pdf)
4. Bind each service finding to its named branch using the publisher and address witnesses. Check the printed NHP address for the retained branches under review. Treat a directory or accreditation scope as identity or assessed-scope evidence. [NHP catalogue](https://www.data.gov.in/resource/national-hospital-directory-geo-code-and-additional-parameters-updated-till-last-month) · [NABH assessment scope](https://portal.nabh.co/Documents/AccreditedList/Hospitals/HN2013N0176N5th%20EditionNScope%20Correction.pdf) · [Ratna operator address](https://ratnahospital.in/contact-us/)

## Review the four service classes

Use `operator_reports_specific_service` only when the operator explicitly describes the requested scope at the named branch. Use `related_service_scope_only` for a related or narrower offering. Generic emergency care leaves minor-injury scope unresolved. Acute dialysis or a generic dialysis unit leaves scheduled maintenance outpatient dialysis unresolved. Record the publisher, URL, source locator, date if supplied and scope of each finding. Operator pages were reviewed on November 22, 2026. Leave an unknown service observation date null.

| Planning class | Original roster | Enriched v1 | Primary operator references for the admitted scope |
| --- | ---: | ---: | --- |
| High-acuity trauma (`major_trauma`) | 1 | 2 | [Jehangir emergency and trauma](https://www.jehangirhospital.com/emergency-and-trauma-coe/) · [Noble emergency and trauma](https://www.noblehrc.com/department/emergency-and-trauma) |
| Minor injury and wound care (`minor_injury_wound_care`) | 0 | 1 | [Jehangir emergency and trauma](https://www.jehangirhospital.com/emergency-and-trauma-coe/) |
| Scheduled maintenance outpatient dialysis (`maintenance_outpatient_dialysis`) | 0 | 1 | [KEM nephrology](https://www.kemhospitalpune.org/specialities/nephrology/) |
| Eye procedures (`eye_procedures`) | 1 | 2 | [KEM ophthalmology](https://www.kemhospitalpune.org/specialities/ophthalmology/) · [Noble ophthalmology](https://www.noblehrc.com/department/ophthalmology) |

The table counts six admitted site/class pairs at three of the twelve sites. A site may contribute to several classes. Use admitted findings to constrain simulated eligibility. Treat missing or related findings as unknown for the requested class, and model staffed capacity separately.

## Verify the frozen variant

Store the flat `storm-roster-v1` and the `storm-service-provenance-v1` sidecar outside Git. Verify the raw byte hashes below. Require the sidecar's `roster_sha256` to equal the flat roster hash and match all 12 entries one to one using `sites[].planning_id` and `sites[].public_site_id` against `facilities[].planning_id` and `facilities[].id`. Recompute the simulation when switching roster versions.

| Local artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `pune-evidence-enriched-v1.storm-roster-v1.json` | 12,968 | `a9c15cc82590ce3272b006562cad61e92de5d97cba9cbdb5752797839b762047` |
| `pune-evidence-enriched-v1.service-provenance-v1.json` | 19,930 | `fa7a23dfb3c9ae47b338b37cfd0f2993ab1f486142edbcafbfbfc49972323748` |

The frozen review used mutable operator pages. Use the published links to repeat the screen and the hashes to verify the frozen files. A changed source warrants a separate dated review. Carry the [original recipe's attribution](README.md#attribution-for-maps-and-recordings) into the map or recording, together with the relevant operator citation for each displayed service claim.

## National exploration finding

The nationwide public-source screen examined all 30,273 official NHP records. Of 10,843 with coordinates, 10,615 fell in exactly one pinned ADM2 geometry. The NHP text had 15 high-acuity trauma markers, 126 broad emergency or minor-injury markers, 18 dialysis markers, 37 eye-procedure markers and zero explicit scheduled maintenance dialysis markers. Strict unique name and point agreement with public OSM within 100 m yielded 244 national site groups. Across those groups there were two broad emergency or minor-injury markers and one dialysis marker. That sparsity is why this planning variant uses named-branch operator sources for service scope. The NHP screen and the national VF comparison have different source populations and denominators. [NHP–OSM source decision](https://github.com/vzhu08/databricks-datathon/issues/323#issuecomment-7081974455) · [National VF coverage report](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7081776129) · [Exploration criterion](https://github.com/vzhu08/databricks-datathon/issues/336)
