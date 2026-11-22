# Data trust: 3-slide outline

## Slide 1. "We checked the data before trusting it"
- Headline: *10,088 facility records measured. No reviewed referral approvals yet, and here is why.*
- Visual: one bar of 10,088 records with overlays, each labelled "lead":
  - 1,549 with an independent identity lead
  - 794 flagged high-risk by our integrity check (838 on an independent replay)
  - 1,047 pins more than 100 km from their PIN
  - 118 rows in duplicate clusters
- Sensitivity callout: *"1 in 6 raw top answers points to a facility that isn't where the map puts it. Applying the proposed (unreviewed) pin repairs would change the top answer in 21% of searches."*
- Audit callout (stratified sample of 152, weighted, 95% CI):
  - map point wrong 12% (6–23%)
  - PIN wrong 6% (2–15%)
  - type disagrees 13% (3–43%)
  - name contradicted 0% (upper bound 13%)
  - about 3 in 10 dialysis (30%) and MRI (27%) claims backed by outside or own-site evidence, none contradicted
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
- Speaker line: "Pins are the problem that changes answers. Duplicates and broken rows barely move the top result."

## Slide 3. "What the app does about it, and what closes the gap"
- Left column, the app today:
  - Withholds real records rather than recommend unreviewed ones
  - Shows exact source text and what is not confirmed
  - Drops negated, planned and referral-only claims
  - Says "no facility in this dataset", never "no care"
  - Evidence as a badge, not a filter: a filter would empty 47% of searches
- Right column, to close the gap:
  - Registries, each with its own access path: HFR (NHA permission), NIN geo directory (data.gov.in download), PM-JAY (district lists work, Haryana used)
  - Two-reviewer sign-off per campus and service
  - Open-network liveness checks
- Closing line: *"Being honest about what we don't know is the feature."*
