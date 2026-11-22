# Data trust report: what is wrong with the facility data, and what we do about it

*CMU x Databricks datathon team, 22 November 2026. Aggregate counts only, from the team's checks of the 10,088 Virtue Foundation (VF) India facility records. All findings are leads for the data owner. None is a reviewed decision.*

## The short version

The VF records describe real places. Every check we ran found at least some independent sign of that. But the records are pulled from web text, they carry no dates, and many of them merge, duplicate or misplace facilities. **The number of records our team has reviewed and approved for sending a patient is zero.** So the app never presents a real record as a recommendation. It says what the records mention and what is still unchecked. The table shows the scale of each problem we found overnight.

| Problem | How big it is | What the app does now | What would close the gap |
|---|---|---|---|
| **Misplaced pins** | 1,047 points sit more than 100 km from every post office of their own PIN. 92 fall in another state, 6 fall outside India, and 119 rows have no coordinates. 145 points have no building within 50 m, and a hand check of 15 of those found 7 badly wrong. | Real records are withheld: no name, place or distance is shown. PR #242 (under review) adds "straight-line distance is not the road journey". | A PIN-based repair (in progress), then reviewer sign-off on the campus. |
| **Over-merged rows** (one record carrying fields from two places) | 794 rows rate high-risk on the record-integrity check, 701 of them for location conflicts. There is no sign of a planted batch. | Flags only, nothing deleted. Real records are withheld until a campus is reviewed. | Reviewer split or approval for each high-risk row. |
| **Duplicates** | 57 clusters covering 118 rows, about 61 surplus rows (0.6%). Service totals move under 1.5%. The same facility appears twice in up to 5.5% of top-5 MRI lists, mostly in big cities. | Not yet collapsed. Proposed: one card with an "also listed as" line. | Reviewer merge of the high-confidence clusters (about 21 of 25 hand-checked were right). |
| **Chain pooling** (one phone or website covers many campuses) | 157 phones and 55 websites are shared across more than 6 rows or 3 or more PINs. 837 rows share a phone with a differently named row more than 5 km away. 377 of 551 website identity matches cannot pick one campus. | Shared chain keys are never used to confirm identity. | Campus-level matching for chains, then review of each campus. |
| **Thin service claims** | Negation or plans are not the issue: 98 to 99% of mentions read as current claims, about 95% correct on hand-check. But in about a third of rows the only evidence is a 1 to 4 word listing such as "MRI scanner". 36 to 38% of MRI and CT rows mention the scanner only in the equipment list. 282 "trauma" rows describe eye, dental or fracture care only. 87 imaging mentions are outsourced or run by a public-private partner. | The evidence matcher (`app/ranking/evidence.py`) drops negated, planned and referral-only statements. The offline finder needs a reviewed, dated onsite "yes" and returns "needs confirmation" otherwise. | Dated service evidence from an independent source, and reviewer sign-off. |
| **No dates, possibly stale** | VF records carry no assertion date. 1,640 rows show no web activity since 2022 or earlier. 685 rows are missing from the current Overture release that VF cites as a source. 148 rows carry two staleness signals. None is verified as closed. | Proposed list "What this does not tell you" (PR #242, under review), which includes "the record is undated". | Website and lifecycle checks from an open network, plus registry status. |
| **Sources that are not independent** | Overture Places is VF's own upstream: 7,489 of 7,916 contact matches are Meta/Facebook places, 4,678 within 10 m. About half of matched OSM objects are bulk imports of the government NHP directory. 132 of 212 Overture Microsoft leads sit within 10 m of VF's point. | Lineage sources are labelled and never count as a second confirmation. | Registries with their own provenance (see below). |
| **Coverage gaps** | 189 of 735 districts have no VF record, while 149 of those have 10 or more health facilities in other open sources. Across rural-share thirds, VF records per million people fall 11x and government listings in OSM fall 2.4x. These figures describe what each source lists. They are not an estimate of how many operating facilities VF captures. | The app says "We found no nearby facility in this dataset". It never says that no care exists. | Official district counts (Rural Health Statistics, HMIS) through an India VPN. |

## What is actually supported

- **Identity:** 1,549 records have at least one independent source family agreeing that the facility exists at that place, such as the NABH accreditation list, NHP/OSM, Wikidata, PM-JAY Haryana, or OpenAlex/ROR. 517 have two or more agreeing families. On a hand-check, 137 of 147 sampled identity leads were the same facility.
- **Services with dated independent evidence:** dialysis 74 records, trauma 17, MRI 1, CT 0. Most service claims are self-reported only: 716 dialysis, 640 MRI, 1,108 CT and 3,276 trauma or emergency records.
- **Confirmed for referral:** 0, by design. Confirmation is a reviewer's call, and no review has happened yet.

## What would close the gap

1. **Indian registries, which are geo-blocked from outside India.** These are the ABDM Health Facility Registry, the National Hospital Directory with geo-codes (NIN), data.gov.in, the PM-JAY and HMIS dashboards, and the AERB licensed CT/X-ray search. A team member with India access can pull them. They add identifiers, coordinates, ownership and some service fields with their own provenance.
2. **Reviewer sign-off.** Two reviewers independently check campus, service wording, date and source independence, then reconcile (the validation plan on #40). Only then does a record move from "mentioned" to "approved for referral".
3. **An open-network pass** for website liveness, OSM lifecycle tags and the newest web captures, to date or retire stale records.

## How we checked

We used rule-based checks, open sources (OSM, Overture, Wikidata, NABH, AERB, OpenAlex, Census 2011, geoBoundaries) and hand-checked random samples for each method. Every figure above is a count on the frozen v0 edition. Methods, scripts and per-method precision are kept with the team's working files. Facility-level outputs stay out of Git because they hold record text and contact data.
