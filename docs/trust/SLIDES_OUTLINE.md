# Data trust: 3-slide outline

## Slide 1. "We checked the data before trusting it"
- Headline: *10,088 facility records measured. No reviewed referral approvals yet, and here is why.*
- Visual: flat (not nested) counts over 10,088 records, each labelled "lead". 8,726 locations pass, 670 proposed repairs, 1,549 identity backed, 197 dated outside evidence, 84 name the service, 0 approved. Other overlays:
  - 794 flagged high-risk by our integrity check (838 on an independent replay)
  - 1,047 pins more than 100 km from their PIN
  - 118 rows in duplicate clusters
- Sensitivity callout: *"1 in 6 raw top answers points to a facility that isn't where the map puts it. Applying the proposed (unreviewed) pin repairs would change the top answer in 21% of searches."*
- Audit callout (stratified sample of 152, weighted, 95% CI):
  - map point wrong 12% (6–23%)
  - PIN wrong 6% (2–15%)
  - type disagrees 13% (3–43%)
  - name contradicted 0% (upper bound 13%)
  - about 3 in 10 dialysis (30%) and MRI (27%) claims also stated elsewhere, none contradicted. These are consistency checks with VF's input (mostly sites VF cites), not independent support
  - no source shows a service running at a branch today
- Speaker line: "The hand-read samples check our methods. They are not approvals, and no record has been approved for referral."

## Slide 2. "Eight problems, sized"
- Visual: icon grid, one tile per problem with one number.
  - Misplaced pins: 1,047 more than 100 km off
  - Over-merged rows: 794 / 838 high-risk (two runs)
  - Duplicates: 0.6% surplus
  - Chain pooling: 377 of 551 web matches can't pick a campus
  - Thin claims: a third rest on a 1 to 4 word listing
  - No dates: 148 with two staleness signals
  - Non-independent sources: 7,489 of 7,916 "matches" are VF's own upstream
  - Coverage: 189 districts with no VF record, 149 of them with 10+ listings elsewhere (describes the listings, not care)
  - Road vs straight line: the median ratio is 1.33 urban, 1.44 rural, 2.14 hill and 2.35 northeast. In 31% of cases the nearest facility by road is a different one
- Speaker line: "Pins are the problem that changes answers. Duplicates and broken rows barely move the top result."

## Slide 3. "What the app does about it, and what closes the gap"
- Left column, the app today:
  - Withholds real records rather than recommend unreviewed ones
  - Shows exact source text and what is not confirmed
  - Drops negated, planned and referral-only claims
  - Says "no facility in this dataset", never "no care"
  - Proposed public layer, labelled "Other listed public facility (OpenStreetMap), not reviewed; services inferred from facility type": the median distance to a public dialysis option falls from 230 km (VF only) to 33 km
  - Evidence as a badge, not a filter: the identity filter alone would empty 45% of searches (48.5% under the stricter rule)
- Right column, to close the gap:
  - Registries, each with its own access path: HFR (NHA permission), NIN geo directory (data.gov.in download), PM-JAY (district lists work, Haryana used)
  - Two-reviewer sign-off per campus and service
  - Open-network liveness checks
- Closing line: *"Being honest about what we don't know is the feature."*
