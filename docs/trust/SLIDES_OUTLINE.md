# Data trust: 3-slide outline

## Slide 1. "We checked the data before trusting it"
- Headline: *10,088 facility records. Zero approved for referral yet, and here is why.*
- Visual: one horizontal bar of 10,088 records with overlays.
  - 1,549 independently corroborated (identity)
  - 794 high-risk over-merged
  - 1,047 pins more than 100 km from their PIN
  - 118 duplicate rows
  - 0 reviewed
- Speaker line: "The records are real places pulled from web text. They're undated, some are merged or misplaced, and most service claims are self-reported."

## Slide 2. "Eight problems, sized"
- Visual: compact table or icon grid, one tile per problem with one number.
  - Misplaced pins: 1,047 more than 100 km off
  - Over-merged rows: 794 high-risk
  - Duplicates: 0.6% surplus
  - Chain pooling: 377 of 551 web matches can't pick a campus
  - Thin claims: a third rest on a 1 to 4 word listing
  - No dates: 148 with two staleness signals
  - Non-independent sources: 7,489 of 7,916 "matches" are VF's own upstream
  - Coverage: 189 districts have no VF record, 149 of them with 10+ other listings
- Speaker line: "Most 'second sources' turned out to be the same Facebook pages VF came from, so we only count truly independent ones."

## Slide 3. "What the app does about it, and what closes the gap"
- Left column, the app today:
  - Withholds real records rather than recommend unchecked ones
  - Shows exact source text and what is not confirmed
  - Drops negated, planned and referral-only claims
  - Says "no facility in this dataset", never "no care"
- Right column, to close the gap:
  - Indian registries via an India VPN (HFR, NIN geo directory, HMIS/RHS, AERB)
  - Two-reviewer sign-off per campus and service
  - Open-network liveness checks
- Closing line: *"Honest about what we don't know is the feature."*
