# Data trust report: what is wrong with the facility data, and what we do about it

*CMU x Databricks datathon team, 22 November 2026. Aggregate counts only. Every figure was measured on the frozen v0 edition of the 10,088 Virtue Foundation (VF) India facility records (10,034 of them named). Each one is a lead for the data owner, not a reviewed decision. Receipts are the linked #40 comments.*

## The short version

We ran rule-based checks and source comparisons over all 10,088 records, then hand-read samples for each method.

- **The data:** every record comes from web text and carries no assertion date. Some records merge, duplicate or misplace facilities. Most service claims are self-reported.
- **Approvals:** this workflow has **no reviewed referral approvals**. No record has had its campus, service and destination reviewed and approved for sending a patient. So the app does not present a real record as a recommendation. It says what the records mention and what is still unchecked.
- **What is still open:** every identity and service lead below still awaits premises review.
- **Samples:** the hand-checked samples described under each method are quality checks on the methods. They are not approvals.

## What the problems change for a user

We replayed 2,968 top-5 searches: 742 district centres × 4 services, ranked by straight-line distance ([#40 receipt](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7076407217)).

- **Misplaced top answers.** About **1 in 6 top answers in the raw data (15.8%, 470 of 2,968) point to a facility that is not where the map puts it.** Its pin is more than 100 km from its own PIN, and the repair moves it 25 km or more or cannot place it.
- **Pin repair changes the answer.** Applying the proposed pin repairs, which are unreviewed leads and not applied in the app, changes the top answer in **21% of searches**.
- **Other fixes barely move the top answer.** Dropping broken rows changes it in 0.2% of searches, and collapsing duplicates and chains in 0%.
- **Why evidence is a badge, not a filter.** Keeping only records with independent identity evidence would leave **47% of searches (822 of 1,739) with nothing within 50 km**.
- **Caveat.** Origins are district centres, not population-weighted, and the pin repairs are themselves leads.

## How often a field is wrong: stratified audit sample

**Design.** A stratified sample of 152 named rows: 8 strata (integrity tier × hospital or not), 19 rows each, systematic draw, seed 20261122, covering 32 states. It is weighted to all 10,034 named rows with a combined ratio estimator. The 95% intervals are Wilson intervals on the effective sample size.

**Evidence.** Each field was checked automatically against:
- independent records of the same facility;
- the India Post directory;
- the facility's own website, from September 2026 Common Crawl captures (60 of 165 sites readable).

A hand-read of 10 web verdicts found 8 right; the rules were then fixed for the 2 name-variant misses. These are estimates, not a reviewed truth set.

| Field | Error estimate | 95% CI | Weighted share of rows with evidence |
|---|---:|---:|---:|
| Map point wrong (far from its PIN, or from the same facility elsewhere) | **12%** | 6–23% | 89% |
| PIN wrong (invalid, wrong state, or an outside source gives another) | **6%** | 2–15% | 98% |
| Facility type disagrees with outside sources | **13%** | 3–43% | 16% |
| Name contradicted by outside evidence | **0%** | upper bound 13% | 41% |

**Agreement with full counts.** The point rate agrees with a full-population check, which finds 10.4% of named rows more than 100 km from every post office of their own PIN. The point check partly reuses the integrity signal the strata are built on, so the census figure is shown beside it.

**Service claims.** For dialysis and MRI we drew a simple random sample of 30 claimants each (seed 20261123):
- 30% of dialysis claims (9 of 30, CI 17–48%) were backed by outside or own-site evidence.
- 27% of MRI claims (8 of 30, CI 14–44%) were backed the same way.
- **None was contradicted.**

The rest are self-reported only. A claim with no evidence counts as unbacked, not as wrong.

## The problems, sized

| Problem | How big it is | What the app does now | What would close the gap |
|---|---|---|---|
| **Misplaced pins** | 1,047 points are more than 100 km from every post office of their own PIN. 92 fall in another state, 6 fall outside India, and 119 rows have no coordinates (integrity-check count). 145 points have no building within 50 m; a hand-read of 15 of those found 7 badly wrong. | Real records are withheld: no name, place or distance is shown. PR #242 (under review) adds "straight-line distance is not the road journey". | Review of the proposed pin repair (1,244 suggested moves, none applied), then campus review. |
| **Over-merged rows** (one record with fields from two places) | Our record-integrity check rates 794 of the 10,088 rows high-risk (740 among named rows) on its input bundle: VF base, India Post directory, footprint check and three corroboration files. An independent replay using the footprint check only, with no corroboration, rated 838 ([#57 replay](https://github.com/vzhu08/databricks-datathon/issues/57#issuecomment-7076168806)). Neither run shows a planted batch. | Flags only, nothing deleted. Withheld until reviewed. | Reviewer split or approval for each flagged row. |
| **Duplicates** | 57 clusters covering 118 rows, about 61 surplus (0.6%). Service totals move under 1.5%. The same facility appears twice in up to 5.5% of top-5 MRI lists. Hand-read: about 21 of 25 high-confidence pairs were right. | Not collapsed yet. Proposed: one card with an "also listed as" line. | Reviewer merge of the high clusters. |
| **Chain pooling** (one phone or website, many campuses) | 157 phones and 55 websites are shared by more than 6 rows or 3 or more PINs. 837 rows share a phone with a differently named row more than 5 km away. 377 of 551 website identity matches cannot pick a campus. | Shared chain keys never count toward identity. | Campus-level matching, then review of each campus. |
| **Thin service claims** | Rules classed 98 to 99% of mentions as current claims; about 95% of a 160-item random sample read correctly. In about a third of rows, though, the only evidence is a 1 to 4 word listing such as "MRI scanner". 36 to 38% of MRI and CT rows mention the scanner only in the equipment list. 282 "trauma" rows describe eye, dental or fracture care only. 87 imaging mentions are outsourced or run by a public-private partner. | The evidence matcher (`app/ranking/evidence.py`) drops negated, planned and referral-only statements. The offline finder needs a reviewed, dated onsite "yes" and otherwise returns "needs confirmation". | Dated independent service evidence plus review. |
| **No dates, possibly stale** | Records carry no assertion date. 1,640 rows show no web activity since 2022 or earlier. 685 rows are missing from the current Overture release that VF cites. 148 rows have two staleness signals and 2,162 have one; 54 unnamed rows are unassessed. None is verified as closed. | PR #242 (under review) says "the record is undated". | Website and lifecycle checks from an open network, plus registry status. |
| **Sources that are not independent** | Overture Places is VF's own upstream: 7,489 of 7,916 contact matches are Meta/Facebook places, 4,678 of them within 10 m. About half of matched OSM objects are bulk imports of the government NHP directory. 132 of 212 Overture Microsoft leads sit within 10 m of VF's point. | Lineage sources are labelled and never count as a second family. | Registries with their own provenance (below). |
| **Coverage** | 189 of 735 districts have no VF record, though 149 of them have 10 or more health facilities in other open sources. Across rural-share thirds (637 Census-matched districts), VF records per million people fall 11x while government listings in OSM fall 2.4x. These figures describe what each source lists. They do not estimate what share of operating facilities VF captures. | "We found no nearby facility in this dataset." The app never claims that no care exists. | Official district counts (Rural Health Statistics, HMIS). |

## What the leads support, and under which rules

- **Identity leads: 1,549 named records** ([evidence ladder](https://github.com/vzhu08/databricks-datathon/issues/40#issuecomment-7076365499), `summary.json` sha256 `22ede93b…`).
  - **Rule:** at least one independent family agrees on the place. The families are the NABH directory, NHP/OSM (one family), Wikidata, Overture Microsoft or Foursquare places with no Meta source, the PM-JAY Haryana probe, and OpenAlex/ROR exact-website identity.
  - **Matching:** a lead is either an exact unique phone, website or email with agreeing geography, or strong name evidence within 250 m (or the same PIN) that is unique both ways.
  - **Excluded:** Meta-sourced places, NABH leads on rows that cite NABH, and Microsoft points within 10 m of VF's point are never counted.
  - **Sample:** a fixed-seed random sample of 147 leads, stratified by family (19 to 32 each) and by key versus name-and-place. One desk read compared name, PIN, distance and key: 137 were the same facility, 9 debatable and 1 probably wrong. No website was opened and no call made.
- **Dated service leads:** dialysis 74 rows, trauma 17, MRI 1, CT 0 (same receipt).
  - **Rule:** a dated outside source names the service at that facility: a nephrology or trauma department in a 2023 or later paper (OpenAlex), an NABH emergency-department certificate, or an NABH MRI empanelment.
  - **Sample:** a sample of 20 OpenAlex department matches read 20 of 20 correct after filtering.
- **Counts do not nest.** 197 rows have any dated outside evidence, and 84 rows (92 row-services) have a dated source naming the service itself. 32 of those 84 have no identity lead.
- **Referral approvals: none in this workflow.**

## What would close the gap

1. **Registries, each with its own access path.**
   - **ABDM Health Facility Registry:** search sits behind mobile number and OTP, and its terms bar bulk use without NHA permission. Dependency: NHA permission.
   - **NIN health-facility directory with geo-codes** (data.gov.in / AIKosh, GODL licence): the download did not complete from our container or browser. Dependency: Vincent's download, already requested on #40.
   - **PM-JAY:** the hospital portal uses CAPTCHA and OTP. The district empanelment lists on NIC/S3WaaS do load, and we used Haryana's (33 lists, 1,236 hospital IDs).
   - **HMIS, the PM-JAY dashboard and AERB eLORA:** not reached from our tools. Dependency: a browser session on a network those sites serve.
   - **Rural Health Statistics:** not yet obtained.
2. **Reviewer sign-off.** Two reviewers independently check campus, service wording, date and source independence, then reconcile, following the validation plan on #40. Only then does a record move from "mentioned" to "approved for referral".
3. **An open-network pass** for website liveness, OSM lifecycle tags and the newest web captures, to date or retire stale records.

## How we checked

We used rule-based checks; open sources (OSM, Overture, Wikidata, NABH, AERB, OpenAlex, India Post, Census 2011, geoBoundaries); and a hand-read sample for each method. Methods, scripts and precision notes are kept with the team's working files. Facility-level outputs stay out of Git because they hold record text and contact data.
